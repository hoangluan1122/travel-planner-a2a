from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_json(name: str) -> list[dict[str, Any]]:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)
