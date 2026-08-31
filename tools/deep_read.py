from __future__ import annotations

from pathlib import Path

import requests
from pypdf import PdfReader

from ..config import PDF_DIR
from ..tools.database import find_existing_work, set_pdf_path
from .arxiv_ids import base_arxiv_id

USER_AGENT = "ResearchLiteratureAgent/0.2 (academic research prototype)"


def download_arxiv_pdf(arxiv_id: str) -> dict:
    """Download an arXiv PDF for a paper already in the persistent library."""
    arxiv_id = base_arxiv_id(arxiv_id)
    work_id = find_existing_work(arxiv_id=arxiv_id)
    if work_id is None:
        return {"status": "not_in_library", "arxiv_id": arxiv_id, "message": "Paper is not in library."}
    pdf_path = PDF_DIR / f"{arxiv_id.replace('/', '_')}.pdf"
    if not pdf_path.exists():
        try:
            response = requests.get(
                f"https://arxiv.org/pdf/{arxiv_id}", timeout=120, headers={"User-Agent": USER_AGENT}
            )
            response.raise_for_status()
            pdf_path.write_bytes(response.content)
        except requests.RequestException as exc:
            return {"status": "error", "message": f"PDF download failed: {exc}"}
    set_pdf_path(work_id, str(pdf_path))
    return {"status": "success", "work_id": work_id, "arxiv_id": arxiv_id, "pdf_path": str(pdf_path)}


def extract_pdf_text(pdf_path: str) -> dict:
    """Extract machine-readable text from a local PDF; does not interpret it."""
    path = Path(pdf_path)
    if not path.exists():
        return {"status": "error", "message": f"PDF does not exist: {path}"}
    try:
        reader = PdfReader(str(path))
        pages = []
        for number, page in enumerate(reader.pages, 1):
            pages.append(f"\n\n--- PAGE {number} ---\n\n{page.extract_text() or ''}")
        text = "".join(pages)
        return {"status": "success", "pages": len(reader.pages), "characters": len(text), "text": text}
    except Exception as exc:  # pypdf raises a heterogeneous set of parse exceptions
        return {"status": "error", "message": f"PDF extraction failed: {exc}"}


def get_arxiv_paper_for_deep_read(arxiv_id: str) -> dict:
    """Download if needed and return extracted full text for an explicit user-requested deep read."""
    download = download_arxiv_pdf(arxiv_id)
    if download["status"] != "success":
        return download
    extracted = extract_pdf_text(download["pdf_path"])
    if extracted["status"] != "success":
        return extracted
    return {
        "status": "success", "work_id": download["work_id"], "arxiv_id": download["arxiv_id"],
        "pdf_path": download["pdf_path"], "pages": extracted["pages"],
        "characters": extracted["characters"], "full_text": extracted["text"],
    }
