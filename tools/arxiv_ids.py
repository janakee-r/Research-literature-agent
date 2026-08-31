from __future__ import annotations

import re
from typing import Optional

_MODERN = r"\d{4}\.\d{4,5}(?:v\d+)?"
_LEGACY = r"[a-z][a-z.\-]+/\d{7}(?:v\d+)?"


def normalize_arxiv_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    value = re.sub(
        r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/",
        "",
        value,
        flags=re.I,
    )
    value = value.removesuffix(".pdf")
    value = re.sub(r"^arXiv:\s*", "", value, flags=re.I)
    return value.strip()


def base_arxiv_id(value: Optional[str]) -> Optional[str]:
    normalized = normalize_arxiv_id(value)
    if not normalized:
        return None
    return re.sub(r"v\d+$", "", normalized)


def arxiv_version(value: Optional[str]) -> Optional[str]:
    normalized = normalize_arxiv_id(value)
    if not normalized:
        return None
    match = re.search(r"(v\d+)$", normalized)
    return match.group(1) if match else None


def extract_arxiv_ids(text: str) -> list[str]:
    """Extract modern and legacy arXiv IDs from arbitrary text, preserving order."""
    found: list[str] = []
    for pattern in (
        rf"arXiv:\s*({_MODERN}|{_LEGACY})",
        rf"arxiv\.org/(?:abs|pdf)/({_MODERN}|{_LEGACY})",
        rf"(?<![\w./])({_MODERN}|{_LEGACY})(?![\w./])",
    ):
        found.extend(re.findall(pattern, text, flags=re.I))
    return list(dict.fromkeys(normalize_arxiv_id(item) for item in found if item))
