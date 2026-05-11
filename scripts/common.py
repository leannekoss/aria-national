#!/usr/bin/env python3
"""Shared paths and helpers for the static ANIA build."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT_DIR / "build"
RAW_DIR = BUILD_DIR / "raw"
NORMALIZED_DIR = BUILD_DIR / "normalized"
REPORTS_DIR = BUILD_DIR / "reports"
DATA_DIR = ROOT_DIR / "data"
ASSETS_DIR = ROOT_DIR / "assets"


def ensure_dirs() -> None:
    for path in (BUILD_DIR, RAW_DIR, NORMALIZED_DIR, REPORTS_DIR, DATA_DIR, ASSETS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")


def is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_age_hours * 3600


def fetch_bytes(url: str, *, headers: dict[str, str] | None = None, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "ANIA-Static-Build/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def decode_response(payload: bytes, content_type: str | None = None) -> str:
    """
    Decode public feeds without losing accents.
    Some official RSS feeds declare ISO-8859-15 in XML but are not UTF-8.
    """
    candidates: list[str] = []
    if content_type:
        match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
        if match:
            candidates.append(match.group(1).strip("\"'"))
    head = payload[:300].decode("ascii", errors="ignore")
    match = re.search(r"encoding=[\"']([^\"']+)[\"']", head, flags=re.I)
    if match:
        candidates.append(match.group(1))
    candidates.extend(["utf-8", "iso-8859-15", "windows-1252"])

    seen = set()
    for encoding in candidates:
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def fetch_text(url: str, *, encoding: str = "utf-8", timeout: int = 60) -> str:
    return fetch_bytes(url, timeout=timeout).decode(encoding, errors="replace")


def cache_fetch(
    url: str,
    cache_path: Path,
    *,
    max_age_hours: float,
    binary: bool = False,
    timeout: int = 60,
) -> tuple[bytes | str, bool]:
    """
    Return cached content when still fresh, otherwise refresh it.
    Returns (content, refreshed_now).
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if is_fresh(cache_path, max_age_hours):
        if binary:
            return cache_path.read_bytes(), False
        return cache_path.read_text(encoding="utf-8"), False

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ANIA-Static-Build/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type")
        if binary:
            cache_path.write_bytes(payload)
            return payload, True
        text = decode_response(payload, content_type)
        cache_path.write_text(text, encoding="utf-8")
        return text, True
    except Exception:
        if cache_path.exists():
            if binary:
                return cache_path.read_bytes(), False
            return cache_path.read_text(encoding="utf-8"), False
        raise
