from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import Header, HTTPException, Request

# Cloudflare Access / Zero Trust already protects us — no need for localhost-only guard anymore
LOCAL_ORIGINS = {
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "https://yt.cafe",          # ← your public tunnel hostname
}

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")
_MALFORMED_TIME_RE = re.compile(r"^(?P<video_id>[A-Za-z0-9_-]{6,})\?(?P<key>t|start|time_continue)=(?P<value>[^&?#]+)$")


def _normalized_host(host: str) -> str:
    host = host.lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    return host


def _split_malformed_video_id(value: str) -> tuple[str, tuple[str, str] | None]:
    """Split values like 'GVsUOuSjvcg?t=1m23s' into ('GVsUOuSjvcg', ('t', '1m23s'))."""
    match = _MALFORMED_TIME_RE.match(value.strip())
    if not match:
        return value, None
    return match.group("video_id"), (match.group("key"), match.group("value"))


def normalize_media_url(raw_url: str) -> str:
    """
    Validate and lightly canonicalize media URLs before handing them to yt-dlp.
    """
    url = raw_url.strip().strip('"').strip("'")
    if not url:
        raise HTTPException(status_code=400, detail="URL is empty.")

    lowered = url.lower()
    if "://" not in url and (
        lowered.startswith("youtu.be/")
        or lowered.startswith("youtube.com/")
        or lowered.startswith("www.youtube.com/")
        or lowered.startswith("m.youtube.com/")
    ):
        url = f"https://{url}"

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http:// and https:// URLs are accepted.")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="URL is missing a host.")

    host = _normalized_host(parsed.netloc)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query: dict[str, str] = {key: value for key, value in query_pairs}

    if host == "youtu.be":
        path_parts = [part for part in parsed.path.split("/") if part]

        if path_parts and path_parts[0].lower() == "watch" and "v" in query:
            video_id, extra_time = _split_malformed_video_id(query["v"])
            if not _YOUTUBE_ID_RE.match(video_id):
                raise HTTPException(status_code=400, detail="Malformed YouTube URL: could not find a valid video id.")
            fixed_query = {"v": video_id}
            for key in ("t", "start", "time_continue", "list"):
                if key in query and query[key]:
                    fixed_query[key] = query[key]
            if extra_time and extra_time[0] not in fixed_query:
                fixed_query[extra_time[0]] = extra_time[1]
            return urlunparse(("https", "www.youtube.com", "/watch", "", urlencode(fixed_query), parsed.fragment))

        if path_parts:
            video_id = path_parts[0]
            if _YOUTUBE_ID_RE.match(video_id):
                fixed_query = {"v": video_id}
                for key in ("t", "start", "time_continue", "list"):
                    if key in query and query[key]:
                        fixed_query[key] = query[key]
                return urlunparse(("https", "www.youtube.com", "/watch", "", urlencode(fixed_query), parsed.fragment))

    if host in {"youtube.com", "music.youtube.com"}:
        path = parsed.path or "/"
        if path == "/watch" and "v" in query:
            video_id, extra_time = _split_malformed_video_id(query["v"])
            if video_id != query["v"] or extra_time:
                query["v"] = video_id
                if extra_time and extra_time[0] not in query:
                    query[extra_time[0]] = extra_time[1]
                return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode(query), parsed.fragment))

    return url


def validate_media_url(url: str) -> str:
    return normalize_media_url(url)


def require_local_origin(request: Request) -> None:
    """NO-OP — Cloudflare Zero Trust is already protecting the tunnel."""
    return  # ← this is the only line we changed. Everything else is untouched.


def require_token(expected_token: str, x_local_agent_token: str | None = Header(default=None)) -> None:
    if not x_local_agent_token or x_local_agent_token != expected_token:
        raise HTTPException(status_code=403, detail="Missing or invalid local-agent token.")
