from __future__ import annotations

import sqlite3

from ..config import DB_PATH
from .persistence import ensure_db_local, sync_db


def connect() -> sqlite3.Connection:
    ensure_db_local()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the v2 schema. Safe to call on every process start."""
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                abstract TEXT,
                summary TEXT,
                publication_date TEXT,
                first_seen_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS authors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS work_authors (
                work_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                author_order INTEGER,
                PRIMARY KEY (work_id, author_id),
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE,
                FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS identifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL,
                id_type TEXT NOT NULL,
                id_value TEXT NOT NULL,
                UNIQUE(id_type, id_value),
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                url TEXT,
                source_identifier TEXT,
                version TEXT,
                added_at TEXT NOT NULL,
                UNIQUE(work_id, source_type, url),
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS work_relationships (
                work_id INTEGER NOT NULL,
                relationship TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (work_id, relationship),
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS work_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reading_state (
                work_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'unread',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS paper_roles (
                work_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (work_id, role),
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER,
                arxiv_id TEXT,
                title TEXT,
                feedback TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS deep_reads (
                work_id INTEGER PRIMARY KEY,
                analysis TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS work_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(work_id, file_type, path),
                FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
import re
from typing import Optional

from ..config import local_timestamp
from .arxiv_ids import normalize_arxiv_id, base_arxiv_id, arxiv_version

VALID_READING_STATUSES = {"unread", "deep_read_later", "reading", "read"}
VALID_ROLES = {"knowledge", "citation", "awareness", "methodology"}
VALID_FEEDBACK = {"interesting", "not_interesting"}


def _normalize_feedback(feedback: str) -> str:
    """Normalize natural-language recommendation feedback to DB values."""
    value = (feedback or "").strip().lower()
    value = re.sub(r"[\s-]+", "_", value)

    aliases = {
        "interesting": "interesting",
        "interested": "interesting",
        "positive": "interesting",
        "good": "interesting",
        "good_recommendation": "interesting",
        "relevant": "interesting",
        "not_interesting": "not_interesting",
        "uninteresting": "not_interesting",
        "not_relevant": "not_interesting",
        "irrelevant": "not_interesting",
        "negative": "not_interesting",
        "bad_recommendation": "not_interesting",
    }

    canonical = aliases.get(value)
    if canonical is None:
        raise ValueError(
            f"Invalid feedback: {feedback!r}. "
            "Use a positive signal such as 'interesting' or a negative signal such as 'not interesting'."
        )
    return canonical


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip().lower())


def _find_by_identifier(conn, id_type: str, id_value: Optional[str]):
    if not id_value:
        return None
    row = conn.execute(
        "SELECT work_id FROM identifiers WHERE id_type=? AND id_value=?",
        (id_type, id_value),
    ).fetchone()
    return row["work_id"] if row else None


def find_existing_work(arxiv_id=None, doi=None, ads_bibcode=None):
    init_db()
    values = [
        ("arxiv", base_arxiv_id(arxiv_id)),
        ("doi", normalize_doi(doi)),
        ("ads", ads_bibcode),
    ]
    with connect() as conn:
        for id_type, value in values:
            work_id = _find_by_identifier(conn, id_type, value)
            if work_id:
                return work_id
    return None


def normalize_title(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def find_title_candidates(title: str) -> list[dict]:
    init_db()
    target = normalize_title(title)
    with connect() as conn:
        rows = conn.execute("SELECT id,title FROM works").fetchall()
    return [
        {"work_id": row["id"], "title": row["title"], "match": "exact_normalized_title"}
        for row in rows
        if normalize_title(row["title"]) == target
    ]


def _store_authors(conn, work_id: int, authors: list[str]) -> None:
    for order, name in enumerate(authors):
        name = name.strip()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO authors(name) VALUES (?)", (name,))
        author = conn.execute("SELECT id FROM authors WHERE name=?", (name,)).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO work_authors(work_id,author_id,author_order) VALUES (?,?,?)",
            (work_id, author["id"], order),
        )


def add_relationship(work_id: int, relationship: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO work_relationships(work_id,relationship,created_at) VALUES (?,?,?)",
            (work_id, relationship, local_timestamp()),
        )
        conn.commit()



        sync_db()
def remove_relationship(work_id: int, relationship: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "DELETE FROM work_relationships WHERE work_id=? AND relationship=?",
            (work_id, relationship),
        )
        conn.commit()



        sync_db()
def record_event(work_id: int, event_type: str, detail: str = "") -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT INTO work_events(work_id,event_type,detail,created_at) VALUES (?,?,?,?)",
            (work_id, event_type, detail, local_timestamp()),
        )
        conn.commit()



        sync_db()
def store_paper(
    title: str,
    authors: list[str],
    abstract: str = "",
    summary: str = "",
    arxiv_id: Optional[str] = None,
    doi: Optional[str] = None,
    ads_bibcode: Optional[str] = None,
    source_type: str = "unknown",
    source_url: Optional[str] = None,
    publication_date: Optional[str] = None,
    first_seen_date: Optional[str] = None,
    relationship: Optional[str] = None,
    event_type: Optional[str] = None,
) -> dict:
    """Store bibliographic identity separately from user relationships/provenance."""
    init_db()
    arxiv_full = normalize_arxiv_id(arxiv_id)
    arxiv_base = base_arxiv_id(arxiv_id)
    version = arxiv_version(arxiv_id)
    doi = normalize_doi(doi)
    work_id = find_existing_work(arxiv_id=arxiv_id, doi=doi, ads_bibcode=ads_bibcode)
    matched_existing = work_id is not None
    now = local_timestamp()

    with connect() as conn:
        if work_id is None:
            cursor = conn.execute(
                """INSERT INTO works(title,abstract,summary,publication_date,first_seen_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (title, abstract, summary, publication_date, first_seen_date, now, now),
            )
            work_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO reading_state(work_id,status,updated_at) VALUES (?,?,?)",
                (work_id, "unread", now),
            )
        else:
            conn.execute(
                """UPDATE works SET
                     title=CASE WHEN ?!='' THEN ? ELSE title END,
                     abstract=CASE WHEN ?!='' THEN ? ELSE abstract END,
                     summary=CASE WHEN ?!='' THEN ? ELSE summary END,
                     publication_date=COALESCE(?, publication_date),
                     updated_at=? WHERE id=?""",
                (title, title, abstract, abstract, summary, summary, publication_date, now, work_id),
            )

        _store_authors(conn, work_id, authors)
        for id_type, value in (("arxiv", arxiv_base), ("doi", doi), ("ads", ads_bibcode)):
            if value:
                conn.execute(
                    "INSERT OR IGNORE INTO identifiers(work_id,id_type,id_value) VALUES (?,?,?)",
                    (work_id, id_type, value),
                )
        if source_url:
            conn.execute(
                """INSERT OR IGNORE INTO sources(work_id,source_type,url,source_identifier,version,added_at)
                   VALUES (?,?,?,?,?,?)""",
                (work_id, source_type, source_url, arxiv_full, version, now),
            )
        if relationship:
            conn.execute(
                "INSERT OR IGNORE INTO work_relationships(work_id,relationship,created_at) VALUES (?,?,?)",
                (work_id, relationship, now),
            )
        if event_type:
            conn.execute(
                "INSERT INTO work_events(work_id,event_type,detail,created_at) VALUES (?,?,?,?)",
                (work_id, event_type, "", now),
            )
        conn.commit()
        sync_db()
    return {"work_id": work_id, "matched_existing": matched_existing}


def set_reading_status(work_id: int, status: str) -> dict:
    if status not in VALID_READING_STATUSES:
        raise ValueError(f"Invalid reading status: {status}")
    init_db()
    now = local_timestamp()
    with connect() as conn:
        conn.execute(
            """INSERT INTO reading_state(work_id,status,updated_at) VALUES (?,?,?)
               ON CONFLICT(work_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at""",
            (work_id, status, now),
        )
        conn.commit()
        sync_db()
    return {"status": "success", "work_id": work_id, "reading_status": status}


def add_role(work_id: int, role: str) -> dict:
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO paper_roles(work_id,role,created_at) VALUES (?,?,?)",
            (work_id, role, local_timestamp()),
        )
        conn.commit()
        sync_db()
    return {"status": "success", "work_id": work_id, "role": role}


def remove_role(work_id: int, role: str) -> dict:
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM paper_roles WHERE work_id=? AND role=?", (work_id, role))
        conn.commit()
        sync_db()
    return {"status": "success", "work_id": work_id, "role": role}


def set_pdf_path(work_id: int, pdf_path: str) -> dict:
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO work_files(work_id,file_type,path,created_at) VALUES (?,?,?,?)",
            (work_id, "pdf", pdf_path, local_timestamp()),
        )
        conn.commit()
        sync_db()
    return {"status": "success", "work_id": work_id, "pdf_path": pdf_path}


def update_summary(work_id: int, summary: str) -> dict:
    init_db()
    with connect() as conn:
        conn.execute("UPDATE works SET summary=?,updated_at=? WHERE id=?", (summary, local_timestamp(), work_id))
        conn.commit()
        sync_db()
    return {"status": "success", "work_id": work_id}


def get_paper(work_id: int):
    init_db()
    with connect() as conn:
        work = conn.execute(
            """SELECT w.*,rs.status AS reading_status FROM works w
               LEFT JOIN reading_state rs ON rs.work_id=w.id WHERE w.id=?""",
            (work_id,),
        ).fetchone()
        if not work:
            return None
        authors = conn.execute(
            """SELECT a.name FROM authors a JOIN work_authors wa ON wa.author_id=a.id
               WHERE wa.work_id=? ORDER BY wa.author_order""",
            (work_id,),
        ).fetchall()
        identifiers = conn.execute("SELECT id_type,id_value FROM identifiers WHERE work_id=?", (work_id,)).fetchall()
        sources = conn.execute(
            "SELECT source_type,url,source_identifier,version,added_at FROM sources WHERE work_id=?",
            (work_id,),
        ).fetchall()
        relationships = conn.execute(
            "SELECT relationship,created_at FROM work_relationships WHERE work_id=?", (work_id,)
        ).fetchall()
        roles = conn.execute("SELECT role FROM paper_roles WHERE work_id=?", (work_id,)).fetchall()
        files = conn.execute("SELECT file_type,path,created_at FROM work_files WHERE work_id=?", (work_id,)).fetchall()
    return {
        "work": dict(work),
        "authors": [r["name"] for r in authors],
        "identifiers": [dict(r) for r in identifiers],
        "sources": [dict(r) for r in sources],
        "relationships": [dict(r) for r in relationships],
        "roles": [r["role"] for r in roles],
        "files": [dict(r) for r in files],
    }


def get_all_papers() -> list[dict]:
    """Return user-facing paper metadata. Internal database IDs are intentionally omitted."""
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT w.title,w.publication_date,COALESCE(rs.status,'unread') AS reading_status,
                      i.id_value AS arxiv_id
               FROM works w
               LEFT JOIN reading_state rs ON rs.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               ORDER BY w.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_papers_by_relationship(relationship: str) -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT w.title,w.abstract,w.publication_date,COALESCE(rs.status,'unread') AS reading_status,
                      i.id_value AS arxiv_id,wr.created_at AS relationship_since
               FROM works w
               JOIN work_relationships wr ON wr.work_id=w.id AND wr.relationship=?
               LEFT JOIN reading_state rs ON rs.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               ORDER BY w.publication_date DESC,w.id DESC""",
            (relationship,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_bookmarked_papers_for_profile() -> dict:
    """Return papers explicitly bookmarked or saved, excluding papers known only as own-work metadata."""
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT w.title,w.abstract,i.id_value AS arxiv_id
               FROM works w JOIN work_relationships wr ON wr.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv' 
               WHERE wr.relationship IN ('bookmarked','saved') AND COALESCE(w.abstract,'')!=''
               ORDER BY w.id"""
        ).fetchall()
    return {"count": len(rows), "papers": [dict(r) for r in rows]}


def get_own_publications() -> dict:
    papers = get_papers_by_relationship("own_publication")
    return {"count": len(papers), "papers": papers}


def get_recently_saved_papers(days: int = 7) -> list[dict]:
    init_db()
    modifier = f"-{int(days)} days"
    with connect() as conn:
        rows = conn.execute(
            """SELECT w.title,i.id_value AS arxiv_id,wr.relationship,wr.created_at
               FROM works w JOIN work_relationships wr ON wr.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv' 
               WHERE wr.relationship IN ('bookmarked','saved')
                 AND datetime(substr(wr.created_at,1,19)) >= datetime('now', ?)
               ORDER BY wr.created_at DESC""",
            (modifier,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_deep_read_queue() -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT w.title,w.summary,i.id_value AS arxiv_id
               FROM works w JOIN reading_state rs ON rs.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               WHERE rs.status='deep_read_later' ORDER BY rs.updated_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_citation_library() -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT w.title,w.abstract,w.summary,i.id_value AS arxiv_id
               FROM works w
               JOIN paper_roles r ON r.work_id=w.id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               WHERE r.role='citation' ORDER BY r.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def add_paper_feedback(feedback: str, arxiv_id: str = "", title: str = "", note: str = "") -> dict:
    """Record explicit recommendation feedback.

    Natural variants are accepted, e.g. ``interesting``, ``not interesting``,
    ``not-interesting`` and ``not_interesting``. They are normalized to the
    canonical database values ``interesting`` or ``not_interesting``.
    """
    canonical_feedback = _normalize_feedback(feedback)
    init_db()
    clean_arxiv_id = base_arxiv_id(arxiv_id) if arxiv_id else ""
    work_id = find_existing_work(arxiv_id=clean_arxiv_id) if clean_arxiv_id else None
    with connect() as conn:
        conn.execute(
            """INSERT INTO recommendation_feedback(work_id,arxiv_id,title,feedback,note,created_at)
               VALUES (?,?,?,?,?,?)""",
            (work_id, clean_arxiv_id, title, canonical_feedback, note, local_timestamp()),
        )
        conn.commit()
        sync_db()
    return {
        "status": "success",
        "feedback": canonical_feedback,
        "arxiv_id": clean_arxiv_id or None,
        "title": title or None,
    }


def get_paper_feedback() -> list[dict]:
    """Return recommendation feedback without exposing internal database IDs."""
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT arxiv_id,title,feedback,note,created_at
               FROM recommendation_feedback
               ORDER BY created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def save_deep_read_analysis(work_id: int, analysis: str) -> dict:
    init_db()
    now = local_timestamp()
    with connect() as conn:
        conn.execute(
            """INSERT INTO deep_reads(work_id,analysis,created_at,updated_at) VALUES (?,?,?,?)
               ON CONFLICT(work_id) DO UPDATE SET analysis=excluded.analysis,updated_at=excluded.updated_at""",
            (work_id, analysis, now, now),
        )
        conn.execute(
            """INSERT INTO reading_state(work_id,status,updated_at) VALUES (?,?,?)
               ON CONFLICT(work_id) DO UPDATE SET status='read',updated_at=excluded.updated_at""",
            (work_id, "read", now),
        )
        conn.execute(
            "INSERT INTO work_events(work_id,event_type,detail,created_at) VALUES (?,?,?,?)",
            (work_id, "deep_read", "analysis_saved", now),
        )
        conn.commit()
        sync_db()
    return {"status": "success", "work_id": work_id}


def list_deep_reads() -> dict:
    """List papers with a persisted deep-read analysis, without returning the full analyses."""
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """SELECT w.title, i.id_value AS arxiv_id,
                      dr.created_at, dr.updated_at
               FROM deep_reads dr
               JOIN works w ON w.id=dr.work_id
               LEFT JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               ORDER BY dr.updated_at DESC"""
        ).fetchall()
    return {"count": len(rows), "deep_reads": [dict(r) for r in rows]}


def get_deep_read_analysis(arxiv_id: str) -> dict:
    """Return a persisted deep-read analysis using the paper's public arXiv identifier."""
    init_db()
    arxiv_id = base_arxiv_id(arxiv_id)
    with connect() as conn:
        row = conn.execute(
            """SELECT w.title, i.id_value AS arxiv_id,
                      dr.analysis, dr.created_at, dr.updated_at
               FROM deep_reads dr
               JOIN works w ON w.id=dr.work_id
               JOIN identifiers i ON i.work_id=w.id AND i.id_type='arxiv'
               WHERE i.id_value=?""",
            (arxiv_id,),
        ).fetchone()
    if row is None:
        return {"status": "not_found", "arxiv_id": arxiv_id}
    result = dict(row)
    result["status"] = "success"
    return result


init_db()
