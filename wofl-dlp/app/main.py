from __future__ import annotations

import mimetypes
import webbrowser
from pathlib import Path
from threading import Timer

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .config import CONFIG_FILE, get_or_create_token, load_settings, save_settings
from .models import AppSettings, DownloadRequest, ProbeRequest
from .security import require_local_origin, require_token
from .ytdlp_runner import JobManager, probe, system_info

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TOKEN = get_or_create_token()
JOBS = JobManager()

app = FastAPI(
    title="wofl-dlp local agent",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def token_dependency(x_local_agent_token: str | None = None) -> None:
    require_token(TOKEN, x_local_agent_token)


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        require_local_origin(request)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, str | bool]:
    return {
        "token": TOKEN,
        "app": "wofl-dlp",
        "localOnly": True,
        "configFile": str(CONFIG_FILE),
    }


@app.get("/api/system")
def get_system() -> dict:
    return system_info().model_dump()


@app.get("/api/settings")
def get_settings() -> dict:
    return load_settings().model_dump()


@app.put("/api/settings")
def put_settings(settings: AppSettings, request: Request) -> dict:
    require_token(TOKEN, request.headers.get("x-local-agent-token"))
    save_settings(settings)
    return {"ok": True, "settings": settings.model_dump()}


@app.post("/api/probe")
def post_probe(req: ProbeRequest, request: Request) -> dict:
    require_token(TOKEN, request.headers.get("x-local-agent-token"))
    try:
        return probe(req.url).model_dump()
    except Exception as exc:  # noqa: BLE001 - user-facing local tool
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/download")
def post_download(req: DownloadRequest, request: Request) -> dict:
    require_token(TOKEN, request.headers.get("x-local-agent-token"))
    try:
        return JOBS.start(req).model_dump()
    except Exception as exc:  # noqa: BLE001 - user-facing local tool
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return JOBS.status(job_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown job") from exc


@app.get("/api/jobs/{job_id}/file")
def get_job_file(job_id: str) -> FileResponse:
    try:
        job = JOBS.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown job") from exc
    if job.state != "done" or not job.filename:
        raise HTTPException(status_code=409, detail="Job is not ready yet")
    file_path = (job.job_dir / job.filename).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Output file is gone")
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
        background=BackgroundTask(JOBS.mark_served_and_cleanup, job_id),
    )


def open_browser() -> None:
    webbrowser.open("http://127.0.0.1:8765/")


def main() -> None:
    Timer(0.8, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
