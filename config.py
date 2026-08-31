from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RESEARCH_AGENT_DATA_DIR", PROJECT_DIR / "data"))
STORAGE_DIR = Path(os.getenv("RESEARCH_AGENT_STORAGE_DIR", PROJECT_DIR / "storage"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("RESEARCH_AGENT_DB_PATH", STORAGE_DIR / "papers.db"))
PROFILE_PATH = Path(os.getenv("RESEARCH_AGENT_PROFILE_PATH", DATA_DIR / "researcher_profile.md"))
WORK_PATH = Path(os.getenv("RESEARCH_AGENT_WORK_PATH", DATA_DIR / "researcher_work.md"))
BOOKMARKS_PATH = Path(os.getenv("RESEARCH_AGENT_BOOKMARKS_PATH", DATA_DIR / "bookmarks.txt"))
PDF_DIR = Path(os.getenv("RESEARCH_AGENT_PDF_DIR", DATA_DIR / "papers"))
REPORT_DIR = Path(os.getenv("RESEARCH_AGENT_REPORT_DIR", DATA_DIR / "scheduled_reports"))

PDF_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TIMEZONE = os.getenv("RESEARCH_AGENT_TIMEZONE", "Asia/Kolkata")
MODEL = os.getenv("RESEARCH_AGENT_MODEL", "gemini-3.5-flash")


def local_timestamp() -> str:
    """Return an unambiguous ISO timestamp in the configured user timezone."""
    return datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds")
