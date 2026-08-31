from __future__ import annotations

import importlib
import sys
from pathlib import Path

source_dir = Path(__file__).resolve().parent
parent_dir = source_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

package = source_dir.name
config = importlib.import_module(f"{package}.config")
database = importlib.import_module(f"{package}.tools.database")
markdown = importlib.import_module(f"{package}.tools.markdown")

database.init_db()
print("db:", config.DB_PATH)
print("papers:", len(database.get_all_papers()))
print("bookmarked_or_saved_for_profile:", database.get_bookmarked_papers_for_profile()["count"])
print("own_publications:", database.get_own_publications()["count"])
print("feeds:", markdown.get_arxiv_feeds())
print("profile_chars:", len(markdown.get_researcher_profile()))
print("work_chars:", len(markdown.get_researcher_work()))
