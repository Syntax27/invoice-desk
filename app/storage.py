import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import time
from uuid import uuid4


STATUSES = ("queued", "processing", "needs_review", "ready", "failed")
LEASE_SECONDS = 120
MAX_ATTEMPTS = 3
JOB_COLUMNS = """
    id, filename, status, invoice_number, invoice_date, total, currency,
    source_text, issues, error, attempts, created_at, updated_at
"""


@dataclass(frozen=True)
class Claim:
    id: int
    token: str
    pdf: bytes
    attempt: int


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def job_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["issues"] = json.loads(job["issues"])
    return job


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    pdf BLOB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'processing', 'needs_review', 'ready', 'failed')),
                    invoice_number TEXT,
                    invoice_date TEXT,
                    total TEXT,
                    currency TEXT,
                    source_text TEXT NOT NULL DEFAULT '',
                    issues TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    claim_token TEXT,
                    lease_until REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (status != 'ready' OR (
                        invoice_number IS NOT NULL AND invoice_date IS NOT NULL
                        AND total IS NOT NULL AND currency IS NOT NULL
                    ))
                );
                CREATE INDEX IF NOT EXISTS invoices_status_id ON invoices(status, id);
            """)

    def enqueue(self, filename: str, pdf: bytes) -> tuple[int, bool]:
        digest = hashlib.sha256(pdf).hexdigest()
        timestamp = utc_timestamp()
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO invoices (filename, sha256, pdf, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (sha256) DO NOTHING
                """,
                (filename, digest, pdf, timestamp, timestamp),
            )
            if inserted.rowcount == 1:
                return inserted.lastrowid, True
            row = connection.execute("SELECT id FROM invoices WHERE sha256 = ?", (digest,)).fetchone()
            return row["id"], False

    def list_jobs(self, status: str | None = None) -> list[dict]:
        query = f"SELECT {JOB_COLUMNS} FROM invoices"
        parameters = ()
        if status is not None:
            query += " WHERE status = ?"
            parameters = (status,)
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY id DESC", parameters)
            return [job_dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        totals = dict.fromkeys(STATUSES, 0)
        with self._connect() as connection:
            for row in connection.execute("SELECT status, COUNT(*) AS count FROM invoices GROUP BY status"):
                totals[row["status"]] = row["count"]
        return totals

    def get_job(self, job_id: int) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {JOB_COLUMNS} FROM invoices WHERE id = ?", (job_id,)
            ).fetchone()
            return job_dict(row) if row is not None else None

    def get_pdf(self, job_id: int) -> bytes | None:
        with self._connect() as connection:
            row = connection.execute("SELECT pdf FROM invoices WHERE id = ?", (job_id,)).fetchone()
            return row["pdf"] if row is not None else None

    def claim(self) -> Claim | None:
        with self._connect() as connection:
            # Lock before reading the queue so two workers cannot select the same job.
            connection.execute("BEGIN IMMEDIATE")
            now = time()
            timestamp = utc_timestamp()
            connection.execute(
                """
                UPDATE invoices
                SET status = 'failed', error = 'Processing timed out. Retry to try again.',
                    claim_token = NULL, lease_until = NULL, updated_at = ?
                WHERE status = 'processing' AND lease_until <= ? AND attempts >= ?
                """,
                (timestamp, now, MAX_ATTEMPTS),
            )
            row = connection.execute(
                """
                SELECT id, pdf, attempts FROM invoices
                WHERE status = 'queued' OR (status = 'processing' AND lease_until <= ?)
                ORDER BY id LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None

            token = uuid4().hex
            attempt = row["attempts"] + 1
            connection.execute(
                """
                UPDATE invoices
                SET status = 'processing', attempts = ?, claim_token = ?, lease_until = ?, updated_at = ?
                WHERE id = ?
                """,
                (attempt, token, now + LEASE_SECONDS, timestamp, row["id"]),
            )
            return Claim(row["id"], token, row["pdf"], attempt)

    def complete(
        self,
        claim: Claim,
        *,
        invoice_number: str | None,
        invoice_date: str | None,
        total: str | None,
        currency: str | None,
        source_text: str,
        issues: tuple[str, ...],
    ) -> bool:
        status = "needs_review" if issues else "ready"
        with self._connect() as connection:
            # A worker whose lease was reclaimed cannot overwrite the new attempt.
            result = connection.execute(
                """
                UPDATE invoices
                SET status = ?, invoice_number = ?, invoice_date = ?, total = ?, currency = ?,
                    source_text = ?, issues = ?, claim_token = NULL, lease_until = NULL, updated_at = ?
                WHERE id = ? AND status = 'processing' AND claim_token = ?
                """,
                (status, invoice_number, invoice_date, total, currency, source_text,
                 json.dumps(issues), utc_timestamp(), claim.id, claim.token),
            )
            return result.rowcount == 1

    def fail(self, claim: Claim, message: str) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE invoices
                SET status = 'failed', error = ?, claim_token = NULL, lease_until = NULL, updated_at = ?
                WHERE id = ? AND status = 'processing' AND claim_token = ?
                """,
                (message, utc_timestamp(), claim.id, claim.token),
            )
            return result.rowcount == 1

    def approve(
        self, job_id: int, *, invoice_number: str, invoice_date: str, total: str, currency: str
    ) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE invoices
                SET status = 'ready', invoice_number = ?, invoice_date = ?, total = ?, currency = ?,
                    issues = '[]', updated_at = ?
                WHERE id = ? AND status = 'needs_review'
                """,
                (invoice_number, invoice_date, total, currency, utc_timestamp(), job_id),
            )
            return result.rowcount == 1

    def retry(self, job_id: int) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE invoices
                SET status = 'queued', attempts = 0, error = NULL, updated_at = ?
                WHERE id = ? AND status = 'failed'
                """,
                (utc_timestamp(), job_id),
            )
            return result.rowcount == 1

    def ready_for_export(self) -> list[dict]:
        return self.list_jobs("ready")
