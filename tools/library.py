from __future__ import annotations

import time
import urllib.parse

import feedparser
import requests

from ..config import BOOKMARKS_PATH
from ..tools.database import store_paper
from .arxiv_ids import normalize_arxiv_id, base_arxiv_id
from .arxiv_metadata import ARXIV_API, USER_AGENT, entry_to_metadata, fetch_arxiv_metadata


def save_arxiv_paper(arxiv_id: str) -> dict:
    """Save an arXiv work to the user's library without downloading or deep-reading it."""
    arxiv_id = normalize_arxiv_id(arxiv_id)
    try:
        metadata = fetch_arxiv_metadata(arxiv_id)
        if metadata is None:
            return {"status": "error", "message": f"Could not find arXiv paper {arxiv_id}"}
        stored = store_paper(
            title=metadata["title"],
            authors=metadata["authors"],
            abstract=metadata["abstract"],
            arxiv_id=metadata["arxiv_id"],
            doi=metadata["doi"],
            source_type="arxiv",
            source_url=metadata["url"],
            publication_date=metadata["published"],
            relationship="saved",
            event_type="agent_save",
        )
        return {
            "status": "success",
            "work_id": stored["work_id"],
            "title": metadata["title"],
            "already_existed": stored["matched_existing"],
            "arxiv_id": metadata["arxiv_id"],
        }
    except requests.RequestException as exc:
        return {"status": "error", "message": f"arXiv request failed: {exc}"}


def import_arxiv_bookmarks(bookmark_file: str, batch_size: int = 25) -> dict:
    """Batch-import arXiv IDs/URLs from a text file and mark them as bookmarked."""
    with open(bookmark_file, "r", encoding="utf-8") as handle:
        raw = [line.strip() for line in handle if line.strip() and not line.strip().startswith("#")]
    arxiv_ids = [normalize_arxiv_id(item) for item in raw]
    results = []

    for start in range(0, len(arxiv_ids), batch_size):
        batch = arxiv_ids[start:start + batch_size]
        params = {"id_list": ",".join(batch), "max_results": len(batch)}
        url = ARXIV_API + "?" + urllib.parse.urlencode(params)
        try:
            response = None
            last_error = None
            for attempt, delay in enumerate((0, 3, 6), start=1):
                if delay:
                    time.sleep(delay)
                try:
                    response = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    status = getattr(exc.response, "status_code", None)
                    if status not in {429, 500, 502, 503, 504} or attempt == 3:
                        raise
            feed = feedparser.parse(response.content)
            returned = {base_arxiv_id(entry.id.split('/abs/')[-1]): entry for entry in feed.entries}
            for requested in batch:
                entry = returned.get(base_arxiv_id(requested))
                if entry is None:
                    results.append({"input": requested, "status": "not_found"})
                    continue
                metadata = entry_to_metadata(entry)
                stored = store_paper(
                    title=metadata["title"], authors=metadata["authors"], abstract=metadata["abstract"],
                    arxiv_id=metadata["arxiv_id"], doi=metadata["doi"], source_type="arxiv",
                    source_url=metadata["url"], publication_date=metadata["published"],
                    relationship="bookmarked", event_type="bookmark_import",
                )
                results.append({
                    "input": requested, "status": "success",
                    "matched_existing": stored["matched_existing"], "title": metadata["title"],
                    "arxiv_id": metadata["arxiv_id"],
                })
        except requests.RequestException as exc:
            results.extend({"input": item, "status": "error", "error": str(exc)} for item in batch)

    successful = [item for item in results if item["status"] == "success"]
    return {
        "total": len(arxiv_ids),
        "successful": len(successful),
        "newly_imported": sum(not item.get("matched_existing", False) for item in successful),
        "already_present": sum(item.get("matched_existing", False) for item in successful),
        "failed": sum(item["status"] != "success" for item in results),
        "results": results,
    }


def import_default_bookmarks() -> dict:
    """Import/sync the configured bookmarks.txt file into the library."""
    if not BOOKMARKS_PATH.exists():
        return {"status": "error", "message": f"Bookmark file not found: {BOOKMARKS_PATH}"}
    return import_arxiv_bookmarks(str(BOOKMARKS_PATH))
