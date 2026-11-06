from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.storage import LEASE_SECONDS, MAX_ATTEMPTS, Store


FIELDS = {
    "invoice_number": "INV-1048",
    "invoice_date": "2026-04-19",
    "total": "172.80",
    "currency": "USD",
}


class StoreTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "invoices.sqlite3")
        self.store.initialize()

    def test_concurrent_duplicate_uploads_keep_one_document(self):
        pdf = b"same document"
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda name: self.store.enqueue(name, pdf), ("a.pdf", "b.pdf")))
        job_id = results[0][0]
        self.assertCountEqual(results, [(job_id, True), (job_id, False)])
        self.assertEqual(self.store.counts()["queued"], 1)
        self.assertEqual(self.store.get_pdf(job_id), pdf)

    def test_concurrent_workers_claim_different_jobs(self):
        first, _ = self.store.enqueue("a.pdf", b"first")
        second, _ = self.store.enqueue("b.pdf", b"second")
        with ThreadPoolExecutor(max_workers=3) as workers:
            futures = [workers.submit(self.store.claim) for _ in range(3)]
            claims = [future.result() for future in futures]
        self.assertEqual(claims.count(None), 1)
        self.assertCountEqual([claim.id for claim in claims if claim], [first, second])

    @patch("app.storage.time", return_value=1000)
    def test_restart_reclaims_expired_lease_and_ignores_old_worker(self, clock):
        job_id, _ = self.store.enqueue("a.pdf", b"document")
        abandoned = self.store.claim()
        reopened = Store(self.store.path)
        self.assertIsNone(reopened.claim())

        clock.return_value += LEASE_SECONDS
        active = reopened.claim()
        self.assertEqual((active.id, active.attempt), (job_id, 2))
        self.assertNotEqual(abandoned.token, active.token)
        self.assertFalse(self.store.fail(abandoned, "stale error"))
        self.assertFalse(self.store.complete(abandoned, source_text="stale", issues=(), **FIELDS))
        self.assertTrue(reopened.complete(active, source_text="active", issues=(), **FIELDS))
        self.assertEqual(self.store.get_job(job_id)["source_text"], "active")

    @patch("app.storage.time", return_value=1000)
    def test_expired_lease_has_a_retry_cap(self, clock):
        job_id, _ = self.store.enqueue("a.pdf", b"document")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.assertEqual(self.store.claim().attempt, attempt)
            clock.return_value += LEASE_SECONDS

        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.get_job(job_id)["status"], "failed")
        self.assertTrue(self.store.retry(job_id))
        self.assertFalse(self.store.retry(job_id))
        self.assertIsNone(self.store.get_job(job_id)["error"])
        self.assertEqual(self.store.claim().attempt, 1)

    def test_only_ready_records_export_and_review_cannot_be_repeated(self):
        job_id, _ = self.store.enqueue("a.pdf", b"document")
        claim = self.store.claim()
        self.assertFalse(self.store.approve(job_id, **FIELDS))

        partial_fields = {**FIELDS, "total": None}
        self.assertTrue(self.store.complete(
            claim, source_text="Invoice text", issues=("Total is missing.",), **partial_fields
        ))
        self.assertEqual(self.store.get_job(job_id)["issues"], ["Total is missing."])
        self.assertEqual(self.store.ready_for_export(), [])

        self.assertTrue(self.store.approve(job_id, **FIELDS))
        self.assertFalse(self.store.approve(job_id, **{**FIELDS, "total": "10.00"}))
        records = self.store.ready_for_export()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["total"], "172.80")
        self.assertEqual(records[0]["issues"], [])
