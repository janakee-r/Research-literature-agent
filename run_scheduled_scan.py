from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Import this source directory as a package regardless of its folder name.
_SOURCE_DIR = Path(__file__).resolve().parent
_PARENT_DIR = _SOURCE_DIR.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

_PACKAGE = _SOURCE_DIR.name
config = importlib.import_module(f"{_PACKAGE}.config")
persistence = importlib.import_module(f"{_PACKAGE}.tools.persistence")

PROJECT_DIR = config.PROJECT_DIR
REPORT_DIR = config.REPORT_DIR
TIMEZONE = config.TIMEZONE
sync_report = persistence.sync_report


def extract_agent_response(output: str) -> str:
    marker = "[research_literature_agent]:"
    if marker not in output:
        return output.strip()
    response = output.split(marker, 1)[1]
    if "[user]:" in response:
        response = response.split("[user]:", 1)[0]
    return response.strip()


def _find_adk() -> str:
    candidates = [
        PROJECT_DIR / ".venv" / "bin" / "adk",
        Path("/layers/google.python.uv/uv-dependencies/.venv/bin/adk"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    executable = shutil.which("adk")
    if executable:
        return executable
    raise RuntimeError("Could not find the ADK executable.")


def run_scan() -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    report_file = REPORT_DIR / f"report_{now.strftime('%Y-%m-%d_%H-%M-%S')}.md"
    prompt = (
        "Run the latest personalized arXiv literature scan using my configured feeds and research context. "
        "Also check for new papers by any authors explicitly listed under Authors to Follow in my researcher profile."
    )

    result = subprocess.run(
        [_find_adk(), "run", PROJECT_DIR.name],
        cwd=PROJECT_DIR.parent,
        input=prompt + "\nexit\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ADK scheduled scan failed:\n{result.stdout}")

    report_file.write_text(extract_agent_response(result.stdout), encoding="utf-8")
    sync_report(report_file)
    return str(report_file)


if __name__ == "__main__":
    print(f"Saved report to {run_scan()}")
