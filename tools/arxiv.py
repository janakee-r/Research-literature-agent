import time
import re
from datetime import datetime, timedelta

import feedparser
import requests
from bs4 import BeautifulSoup

from .arxiv_ids import base_arxiv_id

ARXIV_API = "https://export.arxiv.org/api/query"

def clean_text(text: str) -> str:
    """Collapse repeated whitespace/newlines into normal spaces."""
    return " ".join(text.split())

def _entry_to_dict(entry) -> dict:
    arxiv_id = entry.id.split("/abs/")[-1]

    return {
        "arxiv_id": arxiv_id,
        "title": clean_text(entry.title),
        "authors": [
            author.name
            for author in entry.authors
        ],
        "abstract": clean_text(entry.summary),
        "published": getattr(
            entry,
            "published",
            None,
        ),
        "updated": getattr(
            entry,
            "updated",
            None,
        ),
        "categories": [
            tag["term"]
            for tag in getattr(entry, "tags", [])
        ],
        "url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def search_arxiv_date_range(
    categories: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
    page_size: int = 200,
    max_total: int = 2000,
) -> dict:
    """
    Retrieve arXiv papers submitted within a date range.

    Either:
      - give days=7, days=30, etc.
    or
      - give explicit start_date and end_date in YYYY-MM-DD format.
    """

    if not categories:
        return {
            "status": "error",
            "message": "At least one arXiv category is required.",
        }

    if days is not None:

        if days < 1:
            return {
                "status": "error",
                "message": "days must be at least 1.",
            }

        end = datetime.now()
        start = end - timedelta(days=days)

        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")

    elif start_date is not None and end_date is not None:

        try:
            start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            )

            end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            )

        except ValueError:
            return {
                "status": "error",
                "message": "Dates must be in YYYY-MM-DD format.",
            }

    else:
        return {
            "status": "error",
            "message": (
                "Provide either days, or both start_date and end_date."
            ),
        }

    if end < start:
        return {
            "status": "error",
            "message": "end_date must not be earlier than start_date.",
        }

    # arXiv submittedDate uses GMT and minute precision.
    start_arxiv = start.strftime(
        "%Y%m%d0000"
    )

    end_arxiv = end.strftime(
        "%Y%m%d2359"
    )

    category_query = " OR ".join(
        f"cat:{category}"
        for category in categories
    )

    search_query = (
        f"({category_query}) "
        f"AND submittedDate:"
        f"[{start_arxiv} TO {end_arxiv}]"
    )

    papers = {}
    start_index = 0

    while start_index < max_total:

        current_size = min(
            page_size,
            max_total - start_index,
        )

        params = {
            "search_query": search_query,
            "start": start_index,
            "max_results": current_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        try:
            response = requests.get(
                ARXIV_API,
                params=params,
                timeout=60,
                headers={
                    "User-Agent": (
                        "ResearchLiteratureAgent/0.1 "
                        "(academic research prototype)"
                    )
                },
            )

            response.raise_for_status()

        except Exception as exc:
            return {
                "status": "error",
                "message": str(exc),
                "papers": list(papers.values()),
            }

        feed = feedparser.parse(
            response.content
        )

        entries = feed.entries

        if not entries:
            break

        for entry in entries:

            paper = _entry_to_dict(entry)

            # Ignore v1/v2/version number for identity.
            base_id = base_arxiv_id(paper["arxiv_id"])

            papers[base_id] = paper

        start_index += len(entries)

        # Last page.
        if len(entries) < current_size:
            break

        # arXiv explicitly recommends a delay between
        # repeated API requests.
        time.sleep(3)

    return {
        "status": "success",
        "categories": categories,
        "start_date": start_date,
        "end_date": end_date,
        "number_of_papers": len(papers),
        "papers": list(papers.values()),
    }


def search_arxiv_by_author(
    author: str,
    categories: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
    max_results: int = 200,
) -> dict:
    """Search arXiv directly by author, with optional category and date filters.

    The author name is searched using arXiv's ``au:`` field rather than by
    filtering a broader category scan in the language model.  This makes author
    lookup deterministic and allows searches without requiring a category or
    date range.
    """
    clean_author = clean_text(author or "")
    if not clean_author:
        return {
            "status": "error",
            "message": "An author name is required.",
        }

    if max_results < 1:
        return {
            "status": "error",
            "message": "max_results must be at least 1.",
        }

    # Escape quotes so a normal name can safely be placed in an arXiv field query.
    escaped_author = clean_author.replace('\\', '\\\\').replace('"', '\\"')
    clauses = [f'au:"{escaped_author}"']

    if categories:
        category_query = " OR ".join(f"cat:{category}" for category in categories)
        clauses.append(f"({category_query})")

    resolved_start = start_date
    resolved_end = end_date

    if days is not None:
        if days < 1:
            return {
                "status": "error",
                "message": "days must be at least 1.",
            }
        end = datetime.now()
        start = end - timedelta(days=days)
        resolved_start = start.strftime("%Y-%m-%d")
        resolved_end = end.strftime("%Y-%m-%d")
    elif start_date is not None or end_date is not None:
        if not (start_date and end_date):
            return {
                "status": "error",
                "message": "Provide both start_date and end_date, or neither.",
            }
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return {
                "status": "error",
                "message": "Dates must be in YYYY-MM-DD format.",
            }
        if end < start:
            return {
                "status": "error",
                "message": "end_date must not be earlier than start_date.",
            }

    if resolved_start and resolved_end:
        start = datetime.strptime(resolved_start, "%Y-%m-%d")
        end = datetime.strptime(resolved_end, "%Y-%m-%d")
        clauses.append(
            "submittedDate:"
            f"[{start.strftime('%Y%m%d0000')} TO {end.strftime('%Y%m%d2359')}]"
        )

    search_query = " AND ".join(clauses)
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": min(max_results, 1000),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    try:
        response = requests.get(
            ARXIV_API,
            params=params,
            timeout=60,
            headers={
                "User-Agent": (
                    "ResearchLiteratureAgent/0.1 "
                    "(academic research prototype)"
                )
            },
        )
        response.raise_for_status()
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "papers": [],
        }

    feed = feedparser.parse(response.content)
    papers = {}
    for entry in feed.entries:
        paper = _entry_to_dict(entry)
        papers[base_arxiv_id(paper["arxiv_id"])] = paper

    return {
        "status": "success",
        "author": clean_author,
        "categories": categories or [],
        "start_date": resolved_start,
        "end_date": resolved_end,
        "number_of_papers": len(papers),
        "papers": list(papers.values()),
    }

def get_latest_arxiv_papers(
    categories: list[str],
) -> dict:
    """
    Retrieve the latest announced papers from one or more arXiv categories.

    Includes:
      - New submissions
      - Cross submissions

    Excludes:
      - Replacement submissions

    Papers appearing in multiple requested categories are deduplicated
    by base arXiv ID.
    """

    if not categories:
        return {
            "status": "error",
            "message": "At least one arXiv category is required.",
        }

    headers = {
        "User-Agent": (
            "ResearchLiteratureAgent/0.1 "
            "(academic hackathon prototype)"
        )
    }

    all_papers = {}
    listing_dates = {}

    for category in categories:

        url = f"https://arxiv.org/list/{category}/new"

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=30,
            )

            response.raise_for_status()

        except Exception as exc:
            return {
                "status": "error",
                "message": (
                    f"Could not retrieve {category}: {exc}"
                ),
            }

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # --------------------------------------------------
        # Find listing date
        # --------------------------------------------------

        listing_date = "unknown"

        for h3 in soup.find_all("h3"):

            text = clean_text(
                h3.get_text()
            )

            if text.startswith(
                "Showing new listings for"
            ):
                listing_date = text.replace(
                    "Showing new listings for",
                    "",
                ).strip()

                break

        listing_dates[category] = listing_date

        # --------------------------------------------------
        # Sections we want
        # --------------------------------------------------

        wanted_sections = {
            "New submissions": "new",
            "Cross submissions": "cross-list",
            "Cross-lists": "cross-list",
        }

        for heading in soup.find_all("h3"):

            heading_text = clean_text(
                heading.get_text()
            )

            section_type = None

            for section_name, type_name in (
                wanted_sections.items()
            ):

                if heading_text.startswith(
                    section_name
                ):
                    section_type = type_name
                    break

            if section_type is None:
                continue

            # --------------------------------------------------
            # Walk sibling entries until next section heading
            # --------------------------------------------------

            entries = []

            sibling = heading.find_next_sibling()

            while sibling is not None:

                if sibling.name == "h3":
                    break

                if sibling.name == "dt":
                    entries.append(sibling)

                sibling = (
                    sibling.find_next_sibling()
                )

            # --------------------------------------------------
            # Parse papers
            # --------------------------------------------------

            for dt in entries:

                dd = dt.find_next_sibling("dd")

                if dd is None:
                    continue

                abs_link = dt.find(
                    "a",
                    href=re.compile(r"^/abs/")
                )

                if abs_link is None:
                    continue

                href = abs_link.get("href")

                arxiv_id = href.split(
                    "/abs/"
                )[-1]

                base_id = base_arxiv_id(arxiv_id)

                paper_url = (
                    "https://arxiv.org"
                    + href
                )

                # ------------------------------------------
                # Title
                # ------------------------------------------

                title_div = dd.find(
                    "div",
                    class_="list-title",
                )

                title = "Unknown title"

                if title_div:

                    title = clean_text(
                        title_div.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    title = re.sub(
                        r"^Title:\s*",
                        "",
                        title,
                    )

                # ------------------------------------------
                # Authors
                # ------------------------------------------

                authors_div = dd.find(
                    "div",
                    class_="list-authors",
                )

                authors = []

                if authors_div:

                    authors = [
                        clean_text(
                            a.get_text()
                        )
                        for a
                        in authors_div.find_all(
                            "a"
                        )
                    ]

                # ------------------------------------------
                # Subjects
                # ------------------------------------------

                subjects_div = dd.find(
                    "div",
                    class_="list-subjects",
                )

                subjects = ""

                if subjects_div:

                    subjects = clean_text(
                        subjects_div.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    subjects = re.sub(
                        r"^Subjects:\s*",
                        "",
                        subjects,
                    )

                # ------------------------------------------
                # Abstract
                # ------------------------------------------

                abstract = ""

                abstract_p = dd.find(
                    "p",
                    class_="mathjax",
                )

                if abstract_p:

                    abstract = clean_text(
                        abstract_p.get_text(
                            " ",
                            strip=True,
                        )
                    )

                # ------------------------------------------
                # Store / merge
                # ------------------------------------------

                if base_id not in all_papers:

                    all_papers[base_id] = {
                        "arxiv_id": arxiv_id,
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "subjects": subjects,
                        "url": paper_url,
                        "listing_type": section_type,
                        "seen_in_categories": [
                            category
                        ],
                    }

                else:

                    existing = all_papers[
                        base_id
                    ]

                    if (
                        category
                        not in existing[
                            "seen_in_categories"
                        ]
                    ):
                        existing[
                            "seen_in_categories"
                        ].append(
                            category
                        )

    papers = list(
        all_papers.values()
    )

    new_count = sum(
        p["listing_type"] == "new"
        for p in papers
    )

    cross_count = sum(
        p["listing_type"] == "cross-list"
        for p in papers
    )

    return {
        "status": "success",
        "categories": categories,
        "listing_dates": listing_dates,
        "new_submissions": new_count,
        "cross_lists": cross_count,
        "number_of_papers": len(papers),
        "papers": papers,
    }
