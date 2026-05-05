from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator


class AppSettings(BaseModel):
    cookies_file: str = ""
    allow_remote_ejs_github: bool = False
    js_runtime: str = "auto"  # auto, none, deno, node, bun, qjs, qjs-ng
    max_clip_seconds: int = Field(default=300, ge=5, le=3600)
    cleanup_ttl_hours: int = Field(default=6, ge=1, le=168)
    public_mode: bool = False

    @field_validator("cookies_file")
    @classmethod
    def normalize_cookies(cls, value: str) -> str:
        return value.strip().strip('"')

    @field_validator("js_runtime")
    @classmethod
    def normalize_js_runtime(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = {"auto", "none", "deno", "node", "bun", "qjs", "qjs-ng"}
        if value not in allowed:
            raise ValueError(f"js_runtime must be one of {sorted(allowed)}")
        return value


class ProbeRequest(BaseModel):
    url: str = Field(min_length=5, max_length=4096)


class FormatItem(BaseModel):
    format_id: str
    ext: str = ""
    protocol: str = ""
    resolution: str = ""
    fps: float | None = None
    tbr: float | None = None
    filesize: int | None = None
    filesize_approx: int | None = None
    vcodec: str = ""
    acodec: str = ""
    abr: float | None = None
    asr: int | None = None
    note: str = ""
    label: str = ""


class ProbeResponse(BaseModel):
    title: str = ""
    webpage_url: str = ""
    extractor: str = ""
    id: str = ""
    duration: float | None = None
    detected_start_seconds: float | None = None
    suggested_clip_end_seconds: float | None = None
    video_formats: list[FormatItem]
    audio_formats: list[FormatItem]
    warnings: list[str] = []
    command_preview_note: str = "Command preview is generated at download time from your selected options."


class DownloadRequest(BaseModel):
    url: str = Field(min_length=5, max_length=4096)
    mode: Literal["audio", "video"] = "audio"
    container: str = "wav"
    selected_format_id: str = "smart"
    use_clip: bool = False
    clip_start_seconds: float | None = None
    clip_length_seconds: int = Field(default=300, ge=5, le=3600)
    title_prefix: str = ""

    @field_validator("container")
    @classmethod
    def normalize_container(cls, value: str) -> str:
        value = value.strip().lower().lstrip(".")
        allowed = {"wav", "mp3", "m4a", "flac", "opus", "mp4", "webm", "mkv", "avi"}
        if value not in allowed:
            raise ValueError(f"container must be one of {sorted(allowed)}")
        return value

    @field_validator("selected_format_id")
    @classmethod
    def normalize_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return "smart"
        if len(value) > 200:
            raise ValueError("selected_format_id is too long")
        return value


class JobStatus(BaseModel):
    job_id: str
    state: Literal["queued", "running", "done", "error"]
    progress_percent: float | None = None
    speed: str = ""
    eta: str = ""
    message: str = ""
    log_tail: list[str] = []
    filename: str | None = None
    file_url: str | None = None
    command: list[str] = []


class SystemInfo(BaseModel):
    platform: str
    python: str
    total_memory_gb: float
    available_memory_gb: float
    ffmpeg_path: str
    yt_dlp_version: str
    js_runtimes_found: dict[str, str]
    warnings: list[str]
