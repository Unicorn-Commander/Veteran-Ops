from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent / "data" / "benefits.json"
CATEGORIES = ("federal", "state", "commercial")


@lru_cache(maxsize=1)
def load_benefits_data() -> dict[str, Any]:
    with DATA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_state(state: str | None) -> str | None:
    if not state:
        return None
    code = state.strip().upper()
    return code if len(code) == 2 else None


def filter_benefits(dataset: dict[str, Any], rating: int, state: str | None) -> dict[str, list[dict[str, Any]]]:
    """Return the curated benefits grouped by category after rating/state filters.

    The helper is intentionally pure so it can be unit-tested without FastAPI or DB
    fixtures. Eligibility is based only on the fields the directory knows about.
    """

    state_code = _normalize_state(state)
    grouped: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORIES}
    for benefit in dataset.get("benefits", []):
        if benefit.get("category") not in grouped:
            continue
        if rating < int(benefit.get("min_rating", 0)):
            continue
        benefit_states = benefit.get("states") or []
        if benefit_states and state_code not in benefit_states:
            continue
        grouped[benefit["category"]].append(benefit)
    return grouped
