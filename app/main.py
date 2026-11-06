import csv
import io
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .extraction import validate_invoice
from .storage import Store
from .worker import run_worker


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
MAX_UPLOAD_MB = 10
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
REVIEW_FIELDS = ("invoice_number", "invoice_date", "total", "currency")
STATUSES = {
    "queued": "Queued",
    "processing": "Processing",
    "needs_review": "Needs review",
    "ready": "Ready to export",
    "failed": "Failed",
}
DETAIL_NOTICES = {
    "duplicate": "This PDF is already on the desk. The original job is shown below.",
    "approved": "Invoice approved and ready to export.",
    "retried": "The invoice is back in the queue.",
}


def display_time(value: str) -> str:
    timestamp = datetime.fromisoformat(value).astimezone(UTC)
    return timestamp.strftime("%d %b %Y, %H:%M UTC")


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["display_time"] = display_time


def create_app(db_path: Path | None = None) -> FastAPI:
    store = Store(db_path or Path(os.environ.get("INVOICE_DB", PROJECT_DIR / "data/invoices.sqlite3")))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        stopped = Event()
        worker = Thread(target=run_worker, args=(store, stopped), name="invoice-worker", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            await run_in_threadpool(worker.join, 5)

    app = FastAPI(title="Invoice desk", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @app.middleware("http")
    async def protect_local_requests(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            expected_origin = f"{request.url.scheme}://{request.url.netloc}"
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != expected_origin):
                return render_error(request, "Request refused", "Open Invoice desk directly and try again.", 403)

        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def render_index(
        request: Request, *, status: str = "", error: str | None = None,
        notice: str | None = None, status_code: int = 200,
    ) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {
            "jobs": store.list_jobs(status or None),
            "counts": store.counts(),
            "selected_status": status,
            "statuses": STATUSES,
            "error": error,
            "notice": notice,
            "max_upload_mb": MAX_UPLOAD_MB,
        }, status_code=status_code)

    def get_job(job_id: int) -> dict:
        job = store.get_job(job_id) if 0 < job_id < 2**63 else None
        if job is None:
            raise HTTPException(404, "That invoice job could not be found.")
        return job

    def render_detail(
        request: Request, job: dict, *, error: str | None = None, notice: str | None = None,
        values: dict | None = None, errors: dict | None = None, status_code: int = 200,
    ) -> HTMLResponse:
        return templates.TemplateResponse(request, "detail.html", {
            "job": job,
            "statuses": STATUSES,
            "error": error,
            "notice": notice,
            "values": values if values is not None else {field: job[field] or "" for field in REVIEW_FIELDS},
            "errors": errors or {},
        }, status_code=status_code)

    def render_error(request: Request, title: str, error: str, status_code: int) -> HTMLResponse:
        return templates.TemplateResponse(request, "error.html", {"title": title, "error": error}, status_code=status_code)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> HTMLResponse:
        title = "Page unavailable" if exc.status_code == 404 else "Request could not be completed"
        detail = exc.detail if exc.detail != "Not Found" else "This page could not be found."
        return render_error(request, title, detail, exc.status_code)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, status: str = "", samples: str = "") -> HTMLResponse:
        notice = {
            "loaded": "Sample invoices added to the queue.",
            "existing": "The sample invoices are already on the desk.",
        }.get(samples)
        return render_index(request, status=status if status in STATUSES else "", notice=notice)

    @app.post("/jobs", response_model=None)
    async def upload(request: Request) -> Response:
        length = request.headers.get("content-length", "")
        if not length.isascii() or not length.isdecimal():
            raise HTTPException(411, "Send the PDF using the upload form.")
        if int(length) > MAX_UPLOAD_BYTES + 64 * 1024:
            return await run_in_threadpool(render_index, request, error=f"Choose a PDF under {MAX_UPLOAD_MB} MB.", status_code=413)

        async with request.form(max_files=1, max_fields=0) as form:
            file = form.get("file")
            if not isinstance(file, UploadFile) or not file.filename:
                return await run_in_threadpool(render_index, request, error="Choose a PDF to upload.", status_code=400)
            filename = Path(file.filename.replace("\\", "/")).name
            data = await file.read(MAX_UPLOAD_BYTES + 1)

        if len(data) > MAX_UPLOAD_BYTES:
            return await run_in_threadpool(render_index, request, error=f"Choose a PDF under {MAX_UPLOAD_MB} MB.", status_code=413)
        if not filename.lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
            return await run_in_threadpool(render_index, request, error="Choose a valid PDF file.", status_code=400)

        filename = filename if len(filename) <= 160 else f"{filename[:156]}.pdf"
        job_id, created = await run_in_threadpool(store.enqueue, filename, data)
        suffix = "" if created else "?notice=duplicate"
        return RedirectResponse(f"/jobs/{job_id}{suffix}", status_code=303)

    @app.post("/samples")
    def load_samples() -> RedirectResponse:
        files = sorted((PROJECT_DIR / "samples").glob("*.pdf"))
        if not files:
            raise HTTPException(404, "The sample PDFs are missing from this copy of the project.")
        new_jobs = [store.enqueue(file.name, file.read_bytes())[1] for file in files]
        return RedirectResponse(f"/?samples={'loaded' if any(new_jobs) else 'existing'}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def detail(request: Request, job_id: int, notice: str = "") -> HTMLResponse:
        return render_detail(request, get_job(job_id), notice=DETAIL_NOTICES.get(notice))

    @app.get("/jobs/{job_id}/status")
    def job_status(job_id: int) -> dict[str, str]:
        return {"status": get_job(job_id)["status"]}

    @app.get("/jobs/{job_id}/pdf")
    def original_pdf(job_id: int) -> Response:
        job = get_job(job_id)
        data = store.get_pdf(job_id)
        return Response(data, media_type="application/pdf", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(job['filename'], safe='')}",
        })

    @app.post("/jobs/{job_id}/review", response_model=None)
    async def approve(request: Request, job_id: int) -> Response:
        job = await run_in_threadpool(get_job, job_id)
        if job["status"] != "needs_review":
            return render_detail(request, job, error="Only invoices awaiting review can be approved.", status_code=409)

        length = request.headers.get("content-length", "")
        if not length.isascii() or not length.isdecimal() or int(length) > 16 * 1024:
            return render_detail(request, job, error="The review form is too large. Use the fields below.", status_code=413)
        async with request.form(max_files=0, max_fields=len(REVIEW_FIELDS)) as form:
            values = {field: str(form.get(field, "")) for field in REVIEW_FIELDS}

        normalized, errors = validate_invoice(**values)
        if errors:
            return render_detail(request, job, values=values, errors=errors, status_code=422)
        if not await run_in_threadpool(store.approve, job_id, **normalized):
            job = await run_in_threadpool(get_job, job_id)
            return render_detail(request, job, error="The invoice changed while you were editing it.", status_code=409)
        return RedirectResponse(f"/jobs/{job_id}?notice=approved", status_code=303)

    @app.post("/jobs/{job_id}/retry", response_model=None)
    def retry(request: Request, job_id: int) -> Response:
        get_job(job_id)
        if not store.retry(job_id):
            return render_detail(request, get_job(job_id), error="Only failed invoices can be retried.", status_code=409)
        return RedirectResponse(f"/jobs/{job_id}?notice=retried", status_code=303)

    @app.get("/export.csv")
    def export_csv() -> Response:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(REVIEW_FIELDS)
        for row in store.ready_for_export():
            number = row["invoice_number"]
            if number.lstrip().startswith(("=", "+", "-", "@")):
                number = "'" + number
            writer.writerow((number, row["invoice_date"], row["total"], row["currency"]))
        return Response(output.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="invoices.csv"',
        })

    return app


app = create_app()
