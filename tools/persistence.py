from __future__ import annotations

import os
import threading
from pathlib import Path

from google.cloud import storage

from ..config import DB_PATH, PROFILE_PATH, WORK_PATH, REPORT_DIR

_BUCKET = os.getenv("RESEARCH_AGENT_GCS_BUCKET", "").strip()
_PREFIX = os.getenv("RESEARCH_AGENT_GCS_PREFIX", "research-literature-agent").strip("/")
_LOCK = threading.RLock()
_LOADED: set[str] = set()


def enabled() -> bool:
    return bool(_BUCKET)


def _object_name(relative_name: str) -> str:
    relative_name = relative_name.lstrip("/")
    return f"{_PREFIX}/{relative_name}" if _PREFIX else relative_name


def _blob(relative_name: str):
    client = storage.Client()
    return client.bucket(_BUCKET).blob(_object_name(relative_name))


def ensure_local_file(local_path: Path, relative_name: str) -> None:
    """On first access in this process, restore a mutable file from GCS if present."""
    if not enabled():
        return
    key = str(local_path.resolve())
    with _LOCK:
        if key in _LOADED:
            return
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob = _blob(relative_name)
        if blob.exists():
            blob.download_to_filename(str(local_path))
        _LOADED.add(key)


def sync_local_file(local_path: Path, relative_name: str) -> None:
    """Upload a mutable local file to GCS after a successful write."""
    if not enabled() or not local_path.exists():
        return
    with _LOCK:
        blob = _blob(relative_name)
        blob.upload_from_filename(str(local_path))
        _LOADED.add(str(local_path.resolve()))


def ensure_db_local() -> None:
    ensure_local_file(DB_PATH, "storage/papers.db")


def sync_db() -> None:
    sync_local_file(DB_PATH, "storage/papers.db")


def ensure_profile_local() -> None:
    ensure_local_file(PROFILE_PATH, "data/researcher_profile.md")


def sync_profile() -> None:
    sync_local_file(PROFILE_PATH, "data/researcher_profile.md")


def ensure_work_local() -> None:
    ensure_local_file(WORK_PATH, "data/researcher_work.md")


def sync_work() -> None:
    sync_local_file(WORK_PATH, "data/researcher_work.md")


def sync_report(report_path: Path) -> None:
    try:
        rel = report_path.relative_to(REPORT_DIR)
        name = f"data/scheduled_reports/{rel.as_posix()}"
    except ValueError:
        name = f"data/scheduled_reports/{report_path.name}"
    sync_local_file(report_path, name)
