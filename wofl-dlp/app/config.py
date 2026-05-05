from __future__ import annotations

import json
import secrets
import shutil
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir, user_config_dir

from .models import AppSettings

APP_NAME = "wofl-dlp"
APP_AUTHOR = "whispr"

CONFIG_DIR = Path(user_config_dir(APP_NAME, APP_AUTHOR))
CACHE_DIR = Path(user_cache_dir(APP_NAME, APP_AUTHOR))
JOBS_DIR = CACHE_DIR / "jobs"
CONFIG_FILE = CONFIG_DIR / "settings.json"
TOKEN_FILE = CONFIG_DIR / "agent-token.txt"


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def get_or_create_token() -> str:
    ensure_dirs()
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return token


def load_settings() -> AppSettings:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        settings = AppSettings()
        save_settings(settings)
        return settings
    try:
        data: dict[str, Any] = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return AppSettings.model_validate(data)
    except Exception:
        broken = CONFIG_FILE.with_suffix(".broken.json")
        try:
            shutil.copy2(CONFIG_FILE, broken)
        except OSError:
            pass
        settings = AppSettings()
        save_settings(settings)
        return settings


def save_settings(settings: AppSettings) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")


def safe_job_dir(job_id: str) -> Path:
    if not job_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in job_id):
        raise ValueError("invalid job id")
    path = (JOBS_DIR / job_id).resolve()
    jobs_root = JOBS_DIR.resolve()
    if jobs_root not in path.parents and path != jobs_root:
        raise ValueError("job path escaped jobs directory")
    return path
