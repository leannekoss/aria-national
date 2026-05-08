#!/usr/bin/env python3
"""Shared paths and helpers for the static ANIA build."""

from __future__ import annotations

import json
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
        payload = fetch_bytes(url, timeout=timeout)
        if binary:
            cache_path.write_bytes(payload)
            return payload, True
        text = payload.decode("utf-8", errors="replace")
        cache_path.write_text(text, encoding="utf-8")
        return text, True
    except Exception:
        if cache_path.exists():
            if binary:
                return cache_path.read_bytes(), False
            return cache_path.read_text(encoding="utf-8"), False
        raise
