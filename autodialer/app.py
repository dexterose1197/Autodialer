import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, get_args

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .interchange import FORMATS, MAX_UPLOAD, ImportErrorDetail, export_rows, parse_import
from .storage import Conflict, Store
from .verification import (
    CATALOG, FIXTURES, FixtureTranscriber, OfflineWhisper, SimulatedIVR, Workflow,
    check_exportable_text,
)
from .worker import Worker

STATIC = Path(__file__).with_name("static")
DEMO_ROWS = [
    ("+12025550101", "confirmed"),
    ("+12025550102", "action_required"),
    ("+12025550103", "ambiguous"),
]
Status = Literal["queued", "running", "done", "review", "failed"]


PilotResult = Literal["Confirmed", "Action required", "Unable to verify"]
TAILNET_HOSTNAME = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){2,}ts\.net",
    re.ASCII,
)


class PilotReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: PilotResult


class Review(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=1500)

    @field_validator("label")
    @classmethod
    def check_label(cls, label):
        if not label.strip():
            raise ValueError("Enter a review result.")
        return label.strip()

    @field_validator("label", "note")
    @classmethod
    def check_characters(cls, value):
        return check_exportable_text(value)


def create_app(db_path: Path, *, model_dir=None, access_code=None, android_url=None, pilot_host=None):
    pilot = pilot_host is not None
    if pilot and (not TAILNET_HOSTNAME.fullmatch(pilot_host) or access_code or android_url):
        raise ValueError("Pilot mode requires a Tailscale DNS name and loopback serving.")
    store = Store(db_path)
    transcriber = OfflineWhisper(model_dir) if model_dir else FixtureTranscriber()

    @asynccontextmanager
    async def lifespan(app):
        store.initialize(pilot=pilot)
        worker = Worker(store, SimulatedIVR(), transcriber)
        worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            await run_in_threadpool(worker.close)

    app = FastAPI(title="AutoDialer", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = ["*"] if access_code else ["localhost", "127.0.0.1"]
    if pilot:
        allowed_hosts.append(pilot_host)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts,
        www_redirect=False,
    )
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.middleware("http")
    async def protect(request, call_next):
        if pilot and (request.method, request.url.path.rstrip("/")) in {
            ("POST", "/api/jobs/import"), ("PUT", "/api/workflow"),
        }:
            return JSONResponse({"detail": "This feature is unavailable in the synthetic pilot."}, status_code=403)
        if request.url.path.startswith("/api/"):
            if access_code and not secrets.compare_digest(
                request.headers.get("x-autodialer-code", "").encode(), access_code.encode()
            ):
                return JSONResponse({"detail": "Enter this session's access code."}, status_code=401)
            if request.method not in {"GET", "HEAD"}:
                if request.headers.get("x-autodialer-client") != "web":
                    return JSONResponse({"detail": "Missing client header."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "media-src 'self' blob:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    if pilot:
        @app.exception_handler(RequestValidationError)
        async def invalid_pilot_request(request, error):
            return JSONResponse({"detail": "Invalid request for the synthetic pilot."}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": error.args[0]}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        return {
            "provider": "Simulated IVR", "engine": transcriber.name,
            "android_url": android_url, "pilot": pilot,
            "review_choices": list(get_args(PilotResult)) if pilot else [],
        }

    @app.get("/api/workflow")
    def workflow():
        return store.workflow()

    @app.get("/api/workflow/{revision}")
    def workflow_revision(revision: int):
        return store.workflow(revision)

    if not pilot:
        @app.put("/api/workflow")
        def save_workflow(data: Workflow):
            revision = store.save_workflow(data)
            return {"revision": revision, **data.model_dump()}

    @app.get("/api/jobs")
    def jobs():
        return store.jobs()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int):
        return store.jobs(job_id)

    @app.post("/api/jobs/demo", status_code=201)
    def demo(request: Request):
        job_id = store.create_job("Synthetic appointment demo", DEMO_ROWS, synthetic=True, start=True)
        request.app.state.worker.wake.set()
        return store.jobs(job_id)

    if not pilot:
        @app.post("/api/jobs/import", status_code=201)
        async def import_job(request: Request, filename: str = Query(min_length=1, max_length=240)):
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_UPLOAD:
                    raise HTTPException(413, "Choose a file no larger than 5 MiB.")
                data.extend(chunk)
            try:
                rows = await run_in_threadpool(parse_import, filename, bytes(data))
            except ImportErrorDetail as error:
                raise HTTPException(422, str(error)) from error
            name = Path(filename.replace("\\", "/")).stem.strip()[:100] or "Imported verification"
            job_id = await run_in_threadpool(store.create_job, name, rows)
            return await run_in_threadpool(store.jobs, job_id)

    @app.post("/api/jobs/{job_id}/{action}")
    def change_job(job_id: int, action: Literal["pause", "resume"], request: Request):
        store.set_paused(job_id, action == "pause")
        request.app.state.worker.wake.set()
        return store.jobs(job_id)

    @app.get("/api/jobs/{job_id}/items")
    def items(job_id: int, status: Status | None = None,
              limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        store.jobs(job_id)
        return store.items(job_id, status, limit, offset)

    review_route = "/api/jobs/{job_id}/items/{item_id}/review"
    if pilot:
        @app.post(review_route)
        def review_pilot_item(job_id: int, item_id: int, data: PilotReview):
            store.review(job_id, item_id, data.label, "")
            return {"ok": True}
    else:
        @app.post(review_route)
        def review_item(job_id: int, item_id: int, data: Review):
            store.review(job_id, item_id, data.label, data.note)
            return {"ok": True}

    @app.get("/api/jobs/{job_id}/export/{fmt}")
    def export(job_id: int, fmt: Literal["csv", "txt", "xlsx"]):
        store.jobs(job_id)
        return Response(export_rows(store.items(job_id), fmt), media_type=FORMATS[fmt],
                        headers={"Content-Disposition": f'attachment; filename="autodialer-{job_id}.{fmt}"'})

    @app.get("/api/audio/{fixture}")
    def audio(fixture: str):
        if fixture not in CATALOG:
            raise HTTPException(404, "Recording not found.")
        return FileResponse(FIXTURES / f"{fixture}.wav", media_type="audio/wav")

    @app.get("/api/audit")
    def audit(before: int | None = Query(None, ge=1), limit: int = Query(100, ge=1, le=200)):
        return store.audit(before, limit)

    return app
