from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import psutil
import yt_dlp

from .config import JOBS_DIR, load_settings, safe_job_dir
from .models import DownloadRequest, FormatItem, JobStatus, ProbeResponse, SystemInfo
from .security import validate_media_url
from .timecode import detect_timecode, seconds_to_stamp

_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%.*?(?:at\s+(?P<speed>\S+))?.*?(?:ETA\s+(?P<eta>\S+))?",
    re.IGNORECASE,
)
_DEST_RE = re.compile(r"\[download\]\s+Destination:\s+(?P<path>.+)$")
_MERGE_RE = re.compile(r"\[Merger\]\s+Merging formats into\s+\"(?P<path>.+)\"")
_POSTPROCESS_RE = re.compile(r"\[(?:ExtractAudio|VideoConvertor|VideoRemuxer)\].*?\"(?P<path>.+?)\"")

AUDIO_CONTAINERS = {"wav", "mp3", "m4a", "flac", "opus"}
VIDEO_CONTAINERS = {"mp4", "webm", "mkv", "avi"}
JS_RUNTIME_NAMES = ["deno", "node", "bun", "qjs", "qjs-ng"]


def ffmpeg_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def yt_dlp_base_command() -> list[str]:
    return [sys.executable, "-m", "yt_dlp"]


def _common_args() -> list[str]:
    settings = load_settings()
    args = ["--ffmpeg-location", ffmpeg_path(), "--no-playlist"]
    if settings.cookies_file:
        cookie_path = Path(settings.cookies_file).expanduser()
        if cookie_path.exists() and cookie_path.is_file():
            args.extend(["--cookies", str(cookie_path)])
    if settings.allow_remote_ejs_github:
        args.extend(["--remote-components", "ejs:github"])
    if settings.js_runtime != "none":
        if settings.js_runtime == "auto":
            found = _find_js_runtimes()
            if found:
                # Pick a deterministic preference order. Deno tends to be the best supported
                # permissioned runtime, but yt-dlp decides actual challenge use internally.
                for name in ("deno", "node", "bun", "qjs", "qjs-ng"):
                    if name in found:
                        args.extend(["--js-runtimes", name])
                        break
        else:
            args.extend(["--js-runtimes", settings.js_runtime])
    return args


def _find_js_runtimes() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in JS_RUNTIME_NAMES:
        path = shutil.which(name)
        if path:
            found[name] = path
    return found


def _filesize_label(item: dict[str, Any]) -> str:
    size = item.get("filesize") or item.get("filesize_approx")
    if not size:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return ""


def _format_label(item: dict[str, Any], kind: str) -> str:
    ext = item.get("ext") or "?"
    fmt_id = item.get("format_id") or "?"
    note = item.get("format_note") or item.get("format") or ""
    filesize = _filesize_label(item)
    protocol = item.get("protocol") or ""
    if kind == "audio":
        abr = item.get("abr")
        asr = item.get("asr")
        acodec = item.get("acodec") or "audio"
        parts = [fmt_id, ext, acodec]
        if abr:
            parts.append(f"{abr:g} kbps")
        if asr:
            parts.append(f"{asr:g} Hz")
        if filesize:
            parts.append(filesize)
        if note:
            parts.append(str(note))
        return " · ".join(str(p) for p in parts if p)
    resolution = item.get("resolution") or ""
    fps = item.get("fps")
    vcodec = item.get("vcodec") or "video"
    acodec = item.get("acodec") or ""
    parts = [fmt_id, ext, resolution, vcodec]
    if acodec and acodec != "none":
        parts.append(f"audio:{acodec}")
    if fps:
        parts.append(f"{fps:g}fps")
    if filesize:
        parts.append(filesize)
    if protocol:
        parts.append(protocol)
    if note:
        parts.append(str(note))
    return " · ".join(str(p) for p in parts if p)


def _format_item(item: dict[str, Any], kind: str) -> FormatItem:
    return FormatItem(
        format_id=str(item.get("format_id") or ""),
        ext=str(item.get("ext") or ""),
        protocol=str(item.get("protocol") or ""),
        resolution=str(item.get("resolution") or ""),
        fps=item.get("fps"),
        tbr=item.get("tbr"),
        filesize=item.get("filesize"),
        filesize_approx=item.get("filesize_approx"),
        vcodec=str(item.get("vcodec") or ""),
        acodec=str(item.get("acodec") or ""),
        abr=item.get("abr"),
        asr=item.get("asr"),
        note=str(item.get("format_note") or ""),
        label=_format_label(item, kind),
    )


def probe(url: str, timeout_seconds: int = 90) -> ProbeResponse:
    url = validate_media_url(url)
    command = yt_dlp_base_command() + _common_args() + [
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        url,
    ]
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp metadata probe timed out after {timeout_seconds}s") from exc

    warnings: list[str] = []
    if proc.stderr.strip():
        warnings.extend([line.strip() for line in proc.stderr.splitlines() if line.strip()][-20:])
    if proc.returncode != 0:
        error_tail = "\n".join((proc.stderr or proc.stdout).splitlines()[-12:])
        raise RuntimeError(f"yt-dlp probe failed.\n{error_tail}")

    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp returned metadata that was not valid JSON") from exc

    formats = info.get("formats") or []
    audio: list[FormatItem] = []
    video: list[FormatItem] = []
    seen_audio: set[str] = set()
    seen_video: set[str] = set()
    for fmt in formats:
        fmt_id = str(fmt.get("format_id") or "")
        if not fmt_id:
            continue
        vcodec = fmt.get("vcodec") or "none"
        acodec = fmt.get("acodec") or "none"
        if acodec != "none" and vcodec == "none":
            if fmt_id not in seen_audio:
                audio.append(_format_item(fmt, "audio"))
                seen_audio.add(fmt_id)
        if vcodec != "none":
            if fmt_id not in seen_video:
                video.append(_format_item(fmt, "video"))
                seen_video.add(fmt_id)

    start = detect_timecode(url)
    duration = info.get("duration")
    suggested_end = None
    if start is not None:
        max_len = load_settings().max_clip_seconds
        suggested_end = start + max_len
        if duration:
            suggested_end = min(float(duration), suggested_end)

    return ProbeResponse(
        title=str(info.get("title") or ""),
        webpage_url=str(info.get("webpage_url") or url),
        extractor=str(info.get("extractor") or info.get("extractor_key") or ""),
        id=str(info.get("id") or ""),
        duration=duration,
        detected_start_seconds=start,
        suggested_clip_end_seconds=suggested_end,
        video_formats=video,
        audio_formats=audio,
        warnings=warnings,
    )


def _smart_format(mode: str, container: str, selected_format_id: str) -> list[str]:
    if selected_format_id != "smart":
        if mode == "video":
            # If the selected stream is video-only, this asks yt-dlp to add best audio.
            return ["-f", f"{selected_format_id}+bestaudio/{selected_format_id}/best"]
        return ["-f", f"{selected_format_id}/bestaudio/best"]

    if mode == "audio":
        return ["-f", "bestaudio[ext=webm]/bestaudio/best"]
    if container == "mp4":
        return ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]
    if container == "webm":
        return ["-f", "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best"]
    return ["-f", "bestvideo+bestaudio/best"]


def build_download_command(req: DownloadRequest, job_dir: Path) -> list[str]:
    normalized_url = validate_media_url(req.url)
    if req.mode == "audio" and req.container not in AUDIO_CONTAINERS:
        raise ValueError("Audio mode only supports wav, mp3, m4a, flac, or opus.")
    if req.mode == "video" and req.container not in VIDEO_CONTAINERS:
        raise ValueError("Video mode only supports mp4, webm, mkv, or avi.")

    output_template = "%(title).200B - [%(id)s].%(ext)s"
    if req.title_prefix.strip():
        safe_prefix = re.sub(r"[^A-Za-z0-9 _.-]+", "_", req.title_prefix.strip())[:80]
        output_template = f"{safe_prefix} - {output_template}"

    command = yt_dlp_base_command() + _common_args() + [
        "--newline",
        "--no-playlist",
        "--restrict-filenames",
        "--paths",
        f"home:{job_dir}",
        "-o",
        output_template,
    ]
    command.extend(_smart_format(req.mode, req.container, req.selected_format_id))

    if req.use_clip:
        start = req.clip_start_seconds if req.clip_start_seconds is not None else detect_timecode(req.url)
        if start is None:
            start = 0
        end = start + req.clip_length_seconds
        command.extend(["--download-sections", f"*{seconds_to_stamp(start)}-{seconds_to_stamp(end)}", "--force-keyframes-at-cuts"])

    if req.mode == "audio":
        command.extend(["--extract-audio", "--audio-format", req.container, "--audio-quality", "0"])
        if req.container == "wav":
            command.extend([
                "--postprocessor-args",
                "ffmpeg:-c:a pcm_s24le -ar 48000 -ac 2",
                "--ppa",
                "ffmpeg:-vn -sn",
            ])
    else:
        if req.container in {"mp4", "webm", "mkv"}:
            command.extend(["--merge-output-format", req.container])
        elif req.container == "avi":
            command.extend(["--recode-video", "avi"])

    command.append(normalized_url)
    return command


@dataclass
class Job:
    job_id: str
    request: DownloadRequest
    job_dir: Path
    command: list[str]
    state: str = "queued"
    progress_percent: float | None = None
    speed: str = ""
    eta: str = ""
    message: str = "Queued"
    log_tail: deque[str] = field(default_factory=lambda: deque(maxlen=120))
    filename: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    proc: subprocess.Popen[str] | None = None

    def status(self) -> JobStatus:
        return JobStatus(
            job_id=self.job_id,
            state=self.state,  # type: ignore[arg-type]
            progress_percent=self.progress_percent,
            speed=self.speed,
            eta=self.eta,
            message=self.message,
            log_tail=list(self.log_tail)[-40:],
            filename=self.filename,
            file_url=f"/api/jobs/{self.job_id}/file" if self.state == "done" and self.filename else None,
            command=self.command,
        )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.cleanup_old_job_dirs(max_age_hours=load_settings().cleanup_ttl_hours)

    def start(self, req: DownloadRequest) -> JobStatus:
        with self._lock:
            running = [j for j in self._jobs.values() if j.state in {"queued", "running"}]
            if running:
                raise RuntimeError("A download is already running. This local agent deliberately allows one job at a time.")
            job_id = uuid.uuid4().hex
            job_dir = safe_job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=False)
            command = build_download_command(req, job_dir)
            job = Job(job_id=job_id, request=req, job_dir=job_dir, command=command)
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        thread.start()
        return job.status()

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return job

    def status(self, job_id: str) -> JobStatus:
        return self.get(job_id).status()

    def mark_served_and_cleanup(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job:
            shutil.rmtree(job.job_dir, ignore_errors=True)

    def cleanup_old_job_dirs(self, max_age_hours: int = 6) -> None:
        cutoff = time.time() - max_age_hours * 3600
        if not JOBS_DIR.exists():
            return
        for path in JOBS_DIR.iterdir():
            if not path.is_dir():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def _run_job(self, job: Job) -> None:
        with self._lock:
            job.state = "running"
            job.message = "Starting yt-dlp"
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = subprocess.Popen(
                job.command,
                cwd=str(job.job_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            with self._lock:
                job.proc = proc
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.strip("\r\n")
                if not line:
                    continue
                self._consume_line(job, line)
            return_code = proc.wait()
            if return_code != 0:
                with self._lock:
                    job.state = "error"
                    job.message = f"yt-dlp failed with exit code {return_code}"
                    job.completed_at = time.time()
                return
            final_file = self._find_final_file(job.job_dir)
            if not final_file:
                with self._lock:
                    job.state = "error"
                    job.message = "yt-dlp finished, but no output media file was found."
                    job.completed_at = time.time()
                return
            with self._lock:
                job.state = "done"
                job.progress_percent = 100.0
                job.filename = final_file.name
                job.message = "Done. Click Save file to download it through your browser."
                job.completed_at = time.time()
        except Exception as exc:  # noqa: BLE001 - intentionally surfaces friendly job error
            with self._lock:
                job.state = "error"
                job.message = f"Download crashed: {exc}"
                job.completed_at = time.time()

    def _consume_line(self, job: Job, line: str) -> None:
        with self._lock:
            job.log_tail.append(line)
            job.message = line
            match = _PROGRESS_RE.search(line)
            if match:
                try:
                    job.progress_percent = float(match.group("pct"))
                except (TypeError, ValueError):
                    pass
                job.speed = match.group("speed") or job.speed
                job.eta = match.group("eta") or job.eta
            for regex in (_DEST_RE, _MERGE_RE, _POSTPROCESS_RE):
                found = regex.search(line)
                if found:
                    path = found.group("path")
                    job.filename = Path(path).name

    @staticmethod
    def _find_final_file(job_dir: Path) -> Path | None:
        candidates = []
        partial_suffixes = {".part", ".ytdl", ".temp", ".tmp"}
        sidecar_suffixes = {".json", ".description", ".annotations.xml"}
        for path in job_dir.rglob("*"):
            if not path.is_file():
                continue
            lower = path.name.lower()
            if any(lower.endswith(s) for s in partial_suffixes):
                continue
            if path.suffix.lower() in sidecar_suffixes:
                continue
            if path.stat().st_size <= 0:
                continue
            candidates.append(path)
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]


def system_info() -> SystemInfo:
    vm = psutil.virtual_memory()
    warnings: list[str] = []
    available_gb = round(vm.available / (1024**3), 2)
    if available_gb < 4:
        warnings.append("Available memory is below 4 GB; long videos and WAV conversion may struggle.")
    if not Path(ffmpeg_path()).exists():
        warnings.append("Bundled ffmpeg could not be found.")
    runtimes = _find_js_runtimes()
    if not runtimes:
        warnings.append("No JavaScript runtime was found on PATH. Some sites/formats may need Deno, Node, Bun, or QuickJS.")
    settings = load_settings()
    if settings.cookies_file and not Path(settings.cookies_file).expanduser().exists():
        warnings.append("Configured cookies file does not exist.")
    return SystemInfo(
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        python=sys.version.split()[0],
        total_memory_gb=round(vm.total / (1024**3), 2),
        available_memory_gb=available_gb,
        ffmpeg_path=ffmpeg_path(),
        yt_dlp_version=yt_dlp.version.__version__,
        js_runtimes_found=runtimes,
        warnings=warnings,
    )
