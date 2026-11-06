import csv
import io
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import MAX_UPLOAD_BYTES, PROJECT_DIR, create_app


class InvoiceWorkflowTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        app = create_app(Path(directory) / "test.sqlite3")
        self.client = self.enterContext(TestClient(app, base_url="http://127.0.0.1", follow_redirects=False))
        self.samples = sorted((PROJECT_DIR / "samples").glob("*.pdf"))

    def upload(self, filename, data):
        return self.client.post("/jobs", files={"file": (filename, data, "application/pdf")})

    def wait_for(self, job_path, status):
        until = time.monotonic() + 5
        while time.monotonic() < until:
            response = self.client.get(f"{job_path}/status")
            if response.json()["status"] == status:
                return
            time.sleep(0.05)
        self.fail(f"Job {job_path} did not reach {status}. Last response: {response.text}")

    def export_rows(self):
        response = self.client.get("/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-disposition"], 'attachment; filename="invoices.csv"')
        return list(csv.DictReader(io.StringIO(response.text)))

    def test_upload_process_download_and_deduplicate(self):
        sample = self.samples[0]
        pdf = sample.read_bytes()
        uploaded = self.upload(sample.name, pdf)
        self.assertEqual(uploaded.status_code, 303)
        job_path = uploaded.headers["location"]
        self.wait_for(job_path, "ready")
        self.assertIn(sample.name, self.client.get(job_path).text)
        self.assertEqual(self.client.get(f"{job_path}/pdf").content, pdf)
        repeated = self.upload("different-name.pdf", pdf)
        self.assertEqual(repeated.headers["location"], f"{job_path}?notice=duplicate")
        self.assertEqual(len(self.export_rows()), 1)

    def test_review_rejects_bad_input_and_exports_after_approval(self):
        sample = self.samples[2]
        uploaded = self.upload(sample.name, sample.read_bytes())
        job_path = uploaded.headers["location"]
        self.wait_for(job_path, "needs_review")
        self.assertEqual(self.export_rows(), [])
        fields = {"invoice_number": "REVIEW-17", "invoice_date": "2026-04-03", "total": "19.50", "currency": "usd"}
        invalid = self.client.post(f"{job_path}/review", data={**fields, "invoice_date": "2026-02-30"})
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("REVIEW-17", invalid.text)
        self.assertEqual(self.export_rows(), [])

        approved = self.client.post(f"{job_path}/review", data=fields)
        self.assertEqual(approved.headers["location"], f"{job_path}?notice=approved")
        self.assertEqual(self.client.post(f"{job_path}/review", data=fields).status_code, 409)
        self.assertEqual(self.export_rows(), [{**fields, "currency": "USD"}])

    def test_samples_can_be_loaded_twice_without_duplicate_jobs(self):
        self.assertEqual(self.client.post("/samples").headers["location"], "/?samples=loaded")
        self.assertEqual(self.client.post("/samples").headers["location"], "/?samples=existing")
        self.wait_for("/jobs/1", "ready")
        self.wait_for("/jobs/2", "ready")
        self.wait_for("/jobs/3", "needs_review")
        review_queue = self.client.get("/?status=needs_review").text
        self.assertIn(self.samples[2].name, review_queue)
        self.assertNotIn(self.samples[0].name, review_queue)
        self.assertEqual(len(self.export_rows()), 2)

    def test_bad_pdf_fails_and_can_be_retried(self):
        self.assertEqual(self.upload("not-a-pdf.pdf", b"plain text").status_code, 400)
        self.assertEqual(self.upload("large.pdf", b"%PDF-" + b"x" * MAX_UPLOAD_BYTES).status_code, 413)
        broken = self.upload("damaged.pdf", b"%PDF-1.7\nInvalid PDF body")
        job_path = broken.headers["location"]
        self.wait_for(job_path, "failed")
        retried = self.client.post(f"{job_path}/retry")
        self.assertEqual(retried.headers["location"], f"{job_path}?notice=retried")
        self.wait_for(job_path, "failed")
        self.assertEqual(self.export_rows(), [])

    def test_unknown_job_and_cross_site_post(self):
        self.assertEqual(self.client.get("/jobs/999").status_code, 404)
        self.assertEqual(self.client.post(f"/jobs/{2**63}/retry").status_code, 404)
        self.assertEqual(self.client.post("/samples", headers={"Origin": "https://example.com"}).status_code, 403)
