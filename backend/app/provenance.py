"""Where a result came from, so it can be reproduced (docs/plans/confidence-v1.md):
the code that made it, the settings it used and the data it saw.

The code version is a hash of the backend's own source files, so it works inside the
Docker image too, where there is no git checkout; `JERON_GIT_SHA`, when set, is
recorded beside it. The data side is the backtest's market fingerprint
(`app.backtest.walkforward.market_fingerprint`) and the last session it read.
"""

import hashlib
import json
import os
from functools import cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent


@cache
def code_hash() -> str:
    """sha256 of every .py and .csv file under `app/`, by relative path and content:
    two installs with the same hash run the same code and reference files."""
    h = hashlib.sha256()
    for path in sorted(p for p in APP_DIR.rglob("*") if p.suffix in (".py", ".csv")):
        if "__pycache__" in path.parts:
            continue
        h.update(path.relative_to(APP_DIR).as_posix().encode())
        h.update(b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def git_sha() -> str | None:
    return os.environ.get("JERON_GIT_SHA") or None


def settings_hash(settings: Any) -> str:
    """Hash of a JSON-able settings dict (sorted keys), to tell two configurations apart."""
    text = json.dumps(settings, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def provenance(data_fingerprint: str, data_end: str, settings: Any) -> dict[str, Any]:
    return {
        "code": code_hash(),
        "git": git_sha(),
        "data": data_fingerprint,
        "data_end": data_end,
        "settings": settings_hash(settings),
    }
