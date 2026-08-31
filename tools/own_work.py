from __future__ import annotations

import requests

from .markdown import get_work_section
from ..tools.database import store_paper
from .arxiv_ids import extract_arxiv_ids
from .arxiv_metadata import fetch_arxiv_metadata


def import_own_publications() -> dict:
    """Import arXiv publications listed in researcher_work.md as own_publication relationships."""
    publications = get_work_section("Publications")
    arxiv_ids = extract_arxiv_ids(publications)
    if not arxiv_ids:
        return {"status": "error", "message": "No arXiv identifiers found in Publications."}
    results = []
    for arxiv_id in arxiv_ids:
        try:
            metadata = fetch_arxiv_metadata(arxiv_id)
            if metadata is None:
                results.append({"arxiv_id": arxiv_id, "status": "not_found"})
                continue
            stored = store_paper(
                title=metadata["title"], authors=metadata["authors"], abstract=metadata["abstract"],
                arxiv_id=metadata["arxiv_id"], doi=metadata["doi"], source_type="arxiv",
                source_url=metadata["url"], publication_date=metadata["published"],
                relationship="own_publication", event_type="own_work_import",
            )
            results.append({
                "arxiv_id": arxiv_id, "title": metadata["title"],
                "matched_existing": stored["matched_existing"], "status": "success",
            })
        except requests.RequestException as exc:
            results.append({"arxiv_id": arxiv_id, "status": "error", "message": str(exc)})
    return {
        "status": "success",
        "found": len(arxiv_ids),
        "imported": sum(item["status"] == "success" for item in results),
        "results": results,
    }
