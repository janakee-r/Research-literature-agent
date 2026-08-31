from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ..config import PROFILE_PATH, WORK_PATH
from .persistence import ensure_profile_local, ensure_work_local, sync_profile, sync_work


DEFAULT_PROFILE = """# Researcher Profile

This file describes the researcher's current scientific interests and literature preferences.
Explicit preferences stated by the researcher should take priority over interests inferred from saved literature.

## arXiv Feeds

- astro-ph.CO

## Current Priorities

## Growing Interests

## Broader Interests

## Reduced-Priority Areas

## Reading Preferences

## Authors to Follow

## Inferred Interests from Library
"""

DEFAULT_WORK = """# Researcher Work

This file describes the researcher's own scientific work.

## Current Projects

## Publications

## Past Research Areas

## Methods and Tools Used

## Important Assumptions / Models

## Open Questions
"""

PROFILE_SECTIONS = {
    "arXiv Feeds",
    "Current Priorities",
    "Growing Interests",
    "Broader Interests",
    "Reduced-Priority Areas",
    "Reading Preferences",
    "Authors to Follow",
    "Inferred Interests from Library",
}

WORK_SECTIONS = {
    "Current Projects",
    "Publications",
    "Past Research Areas",
    "Methods and Tools Used",
    "Important Assumptions / Models",
    "Open Questions",
}

PROFILE_EXPLICIT_SECTIONS = {
    "Current Priorities",
    "Growing Interests",
    "Broader Interests",
    "Reduced-Priority Areas",
    "Reading Preferences",
    "Authors to Follow",
}

_DOCUMENTS = {
    "profile": (PROFILE_PATH, DEFAULT_PROFILE, PROFILE_SECTIONS),
    "work": (WORK_PATH, DEFAULT_WORK, WORK_SECTIONS),
}


def _document_info(document: str) -> tuple[Path, str, set[str]]:
    try:
        return _DOCUMENTS[document]
    except KeyError as exc:
        raise ValueError(
            f"Unknown document '{document}'. Choose from {sorted(_DOCUMENTS)}."
        ) from exc


def _ensure(document: str) -> Path:
    path, default_text, _ = _document_info(document)
    if document == "profile":
        ensure_profile_local()
    elif document == "work":
        ensure_work_local()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default_text, encoding="utf-8")
    return path


def _validate_section(document: str, section: str) -> None:
    _, _, sections = _document_info(document)
    if section not in sections:
        raise ValueError(
            f"Invalid section '{section}' for {document}. Choose from {sorted(sections)}."
        )


def read_markdown_document(document: str) -> str:
    """Return the complete researcher 'profile' or 'work' Markdown document."""
    return _ensure(document).read_text(encoding="utf-8")


def get_markdown_section(document: str, section: str) -> str:
    """Return one allowed level-2 section from the researcher profile/work Markdown."""
    _validate_section(document, section)
    text = read_markdown_document(document)
    pattern = rf"(?ms)^## {re.escape(section)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def replace_markdown_section(document: str, section: str, content: str) -> dict:
    """Replace the complete contents of one allowed Markdown section."""
    _validate_section(document, section)
    path = _ensure(document)
    text = path.read_text(encoding="utf-8")
    pattern = rf"(?ms)^## {re.escape(section)}\s*\n.*?(?=^## |\Z)"
    replacement = f"## {section}\n\n{content.strip()}\n\n"
    if re.search(pattern, text):
        text = re.sub(pattern, lambda _: replacement, text, count=1)
    else:
        text = text.rstrip() + "\n\n" + replacement
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    if document == "profile":
        sync_profile()
    elif document == "work":
        sync_work()
    return {"status": "success", "document": document, "section": section}


def add_markdown_bullet(document: str, section: str, text: str) -> dict:
    """Append one bullet to an allowed Markdown section."""
    _validate_section(document, section)
    clean = text.strip()
    if not clean:
        raise ValueError("Bullet text cannot be empty.")
    if document == "profile" and section in PROFILE_EXPLICIT_SECTIONS:
        if "explicit user preference" not in clean.lower():
            clean += f" _(explicit user preference; added {date.today().isoformat()})_"
    existing = get_markdown_section(document, section)
    content = f"{existing}\n- {clean}".strip()
    replace_markdown_section(document, section, content)
    return {"status": "success", "document": document, "section": section, "text": clean}


def remove_markdown_bullet(document: str, section: str, match: str) -> dict:
    """Remove bullets containing `match` (case-insensitive) from an allowed section."""
    _validate_section(document, section)
    clean = match.strip()
    if not clean:
        raise ValueError("Match text cannot be empty.")
    lines = get_markdown_section(document, section).splitlines()
    kept = [line for line in lines if not (line.lstrip().startswith("- ") and clean.lower() in line.lower())]
    removed = len(lines) - len(kept)
    replace_markdown_section(document, section, "\n".join(kept).strip())
    return {"status": "success", "document": document, "section": section, "removed": removed}


def get_researcher_profile() -> str:
    """Return the complete persistent researcher-interest profile."""
    return read_markdown_document("profile")


def get_arxiv_feeds() -> list[str]:
    content = get_markdown_section("profile", "arXiv Feeds")
    return [line[2:].strip() for line in content.splitlines() if line.strip().startswith("- ")]


def get_researcher_work() -> str:
    """Return the researcher's persistent own-work context."""
    return read_markdown_document("work")


def get_work_section(section_name: str) -> str:
    """Internal convenience wrapper for deterministic tools."""
    return get_markdown_section("work", section_name)
