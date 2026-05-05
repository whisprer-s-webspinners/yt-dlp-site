from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_TIME_RE = re.compile(
    r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+(?:\.\d+)?)s?)?$",
    re.IGNORECASE,
)


def parse_time_value(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip().lower()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    if ":" in value:
        parts = value.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        return None
    m = _TIME_RE.match(value)
    if not m:
        return None
    h = float(m.group("h") or 0)
    minute = float(m.group("m") or 0)
    sec = float(m.group("s") or 0)
    total = h * 3600 + minute * 60 + sec
    return total if total > 0 else None


def detect_timecode(url: str) -> float | None:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in ("t", "start", "time_continue"):
        values = params.get(key)
        if values:
            parsed_value = parse_time_value(values[0])
            if parsed_value is not None:
                return parsed_value
    fragment_params = parse_qs(parsed.fragment)
    for key in ("t", "start"):
        values = fragment_params.get(key)
        if values:
            parsed_value = parse_time_value(values[0])
            if parsed_value is not None:
                return parsed_value
    return None


def seconds_to_stamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    h = whole // 3600
    m = (whole % 3600) // 60
    s = whole % 60
    if millis:
        return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"
