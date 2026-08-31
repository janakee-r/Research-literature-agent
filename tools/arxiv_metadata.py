from __future__ import annotations

import time
import urllib.parse

import feedparser
import requests

from .arxiv_ids import normalize_arxiv_id

ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = "ResearchLiteratureAgent/0.2 (academic research prototype)"


def entry_to_metadata(entry) -> dict:
    arxiv_id = normalize_arxiv_id(entry.id.split('/abs/')[-1])
    return {
        "arxiv_id": arxiv_id,
        "title": " ".join(entry.title.split()),
        "authors": [author.name for author in entry.authors],
        "abstract": " ".join(entry.summary.split()),
        "published": getattr(entry, "published", None),
        "updated": getattr(entry, "updated", None),
        "doi": getattr(entry, "arxiv_doi", None),
        "categories": [tag["term"] for tag in getattr(entry, "tags", [])],
        "url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def fetch_arxiv_metadata(arxiv_id: str) -> dict | None:
    """Internal metadata fetcher used by deterministic tools."""
    arxiv_id = normalize_arxiv_id(arxiv_id)
    if not arxiv_id:
        return None

    url = ARXIV_API + "?" + urllib.parse.urlencode({"id_list": arxiv_id})
    response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if not feed.entries:
        return None
    return entry_to_metadata(feed.entries[0])


def get_arxiv_paper_metadata(arxiv_id: str) -> dict:
    """Retrieve title, abstract, authors and metadata for one arXiv paper.

    ``arxiv_id`` may be a bare arXiv ID, an ``arXiv:`` identifier, a versioned
    identifier, or an arxiv.org ``/abs/`` or ``/pdf/`` URL.  This is an
    abstract/metadata lookup only; it does not read the full PDF.
    """
    normalized = normalize_arxiv_id(arxiv_id)
    if not normalized:
        return {
            "status": "error",
            "message": "Provide an arXiv ID or arXiv URL.",
        }

    # A little resilience for transient arXiv failures without making a single
    # paper lookup slow under normal conditions.
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 2, 5), start=1):
        if delay:
            time.sleep(delay)
        try:
            paper = fetch_arxiv_metadata(normalized)
            if paper is None:
                return {
                    "status": "not_found",
                    "arxiv_id": normalized,
                    "message": f"No arXiv record was found for {normalized}.",
                }
            return {
                "status": "success",
                "paper": paper,
            }
        except requests.RequestException as exc:
            last_error = exc
            status = getattr(exc.response, "status_code", None)
            # Retry only transient failures.  Fail immediately on ordinary 4xx.
            if status is not None and status not in {429, 500, 502, 503, 504}:
                break
        except Exception as exc:  # feed/parser/network edge cases
            last_error = exc

    return {
        "status": "error",
        "arxiv_id": normalized,
        "message": f"Could not retrieve this arXiv paper after retries: {last_error}",
    }
