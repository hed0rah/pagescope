"""Data files for PageScope."""

from __future__ import annotations

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent


def load_user_agents() -> list[dict]:
    """Load the user agent list from the bundled JSON file."""
    ua_file = _DATA_DIR / "user_agents.json"
    with open(ua_file, encoding="utf-8") as f:
        return json.load(f)
