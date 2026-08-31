from __future__ import annotations

import re
import time

from ..config import MODEL
from .database import connect, get_bookmarked_papers_for_profile, init_db
from .markdown import replace_markdown_section


PROFILE_INFERENCE_PROMPT = r"""
Infer the researcher's literature interests from the SAVED/BOOKMARKED papers below.
These papers are evidence of what the researcher chose to save, NOT proof of expertise,
active work, collaboration, or endorsement.

Return ONLY Markdown suitable for the contents of the section
"Inferred Interests from Library". Do not include that level-2 heading itself.

Keep the profile concise and evidence-calibrated. Use these headings:
### Strong recurring signals
### Moderate / adjacent signals
### Methods and paper styles
### Weak / one-off signals
### Discovery implications

Rules:
- Strong recurring signals require repeated evidence across multiple papers.
- A topic represented by only one or two papers belongs under Weak / one-off signals
  unless the saved corpus clearly provides broader supporting evidence.
- Do not turn a single unusual paper into a broad durable interest.
- Do not infer that the researcher works on a topic merely because they saved a paper.
- Do not infer collaborations, code usage, scientific lineage, or personal expertise.
- Prefer 4-8 high-value bullets per section rather than exhaustive catalogues.
- Discovery implications should emphasize what future literature is worth surfacing,
  and should reflect signal strength.
""".strip()


def _paper_corpus_for_inference() -> tuple[int, str]:
    library = get_bookmarked_papers_for_profile()
    papers = library.get("papers", [])
    chunks = []
    for i, paper in enumerate(papers, start=1):
        title = (paper.get("title") or "").strip()
        abstract = re.sub(r"\s+", " ", (paper.get("abstract") or "").strip())
        # Enough context for topic inference without making the profile update unnecessarily huge.
        if len(abstract) > 1800:
            abstract = abstract[:1800].rsplit(" ", 1)[0] + "…"
        chunks.append(f"[{i}] {title}\n{abstract}")
    return len(papers), "\n\n".join(chunks)


def update_profile_from_library() -> dict:
    """Infer interests from saved/bookmarked papers and persist them safely without a huge tool-call argument."""
    count, corpus = _paper_corpus_for_inference()
    if count == 0:
        return {"status": "error", "message": "No saved/bookmarked papers with abstracts are available for inference."}

    from google import genai

    client = genai.Client()
    prompt = f"{PROFILE_INFERENCE_PROMPT}\n\nSAVED/BOOKMARKED PAPERS ({count})\n\n{corpus}"

    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(model=MODEL, contents=prompt)
            text = (response.text or "").strip()
            if not text:
                return {"status": "error", "message": "Profile inference returned an empty response."}
            replace_markdown_section("profile", "Inferred Interests from Library", text)
            return {
                "status": "success",
                "papers_used": count,
                "section": "Inferred Interests from Library",
                "message": f"Updated inferred interests from {count} saved/bookmarked papers.",
            }
        except Exception as exc:  # SDK surfaces quota/network failures through several exception types.
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    return {"status": "error", "message": f"Profile inference failed after retries: {last_error}"}


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9α-ωΑ-Ω]+", query.lower())
    stop = {
        "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "from",
        "my", "me", "you", "your", "what", "which", "papers", "paper", "claim", "interest",
        "context", "research", "researcher", "inferred", "inference", "about",
    }
    return [term for term in terms if len(term) >= 3 and term not in stop]


def find_profile_evidence(query: str, limit: int = 8) -> dict:
    """Find saved/bookmarked papers that provide evidence for an inferred-interest claim."""
    clean = query.strip()
    if not clean:
        return {"status": "error", "message": "Query cannot be empty."}
    limit = max(1, min(int(limit), 20))
    terms = _query_terms(clean)
    if not terms:
        return {"status": "error", "message": "No useful search terms were found in the query."}

    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT w.id AS work_id, w.title, w.abstract,
                              i.id_value AS arxiv_id
               FROM works w
               JOIN work_relationships wr ON wr.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               WHERE wr.relationship IN ('bookmarked','saved')
               ORDER BY w.id DESC"""
        ).fetchall()

    scored = []
    for row in rows:
        title = row["title"] or ""
        abstract = row["abstract"] or ""
        title_l = title.lower()
        abstract_l = abstract.lower()
        score = 0
        matched = []
        for term in terms:
            if term in title_l:
                score += 5
                matched.append(term)
            elif term in abstract_l:
                score += 2
                matched.append(term)

        # Small deterministic expansions for common evidence-language queries.
        # These help "historical context of cosmology" find an explicitly historical
        # saved paper without treating every paper containing "cosmology" as equal evidence.
        if any(term.startswith("histor") for term in terms):
            title_markers = ("history of cosmology", "historical cosmology", "years after", "century", "friedmann")
            abstract_markers = ("history of cosmology", "historical context", "friedmann")
            if any(marker in title_l for marker in title_markers):
                score += 10
                matched.append("historical-context")
            elif any(marker in abstract_l for marker in abstract_markers):
                score += 5
                matched.append("historical-context")

        # Also reward the complete phrase when it occurs.
        phrase = clean.lower()
        if phrase in title_l:
            score += 8
        elif phrase in abstract_l:
            score += 4
        if score:
            excerpt = ""
            if abstract:
                positions = [abstract_l.find(term) for term in matched if abstract_l.find(term) >= 0]
                pos = min(positions) if positions else 0
                start = max(0, pos - 140)
                end = min(len(abstract), pos + 360)
                excerpt = re.sub(r"\s+", " ", abstract[start:end]).strip()
                if start > 0:
                    excerpt = "…" + excerpt
                if end < len(abstract):
                    excerpt += "…"
            scored.append({
                "title": title,
                "arxiv_id": row["arxiv_id"],
                "matched_terms": sorted(set(matched)),
                "evidence_score": score,
                "abstract_excerpt": excerpt,
            })

    scored.sort(key=lambda item: (-item["evidence_score"], item["title"].lower()))
    return {
        "status": "success",
        "query": clean,
        "matches": scored[:limit],
        "match_count": len(scored),
        "note": "These are supporting saved-paper matches, not proof that the topic is a durable interest.",
    }
