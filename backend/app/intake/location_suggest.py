"""Suggest exposure/deployment locations by scanning the veteran's own document text.

Deterministic keyword match against a curated list (same places as presumptive
"where" windows). No LLM. Used to pre-populate profile location chips.
"""

from __future__ import annotations

import re

# Longer phrases first so "Camp Lejeune" wins over partials.
_LOCATION_KEYWORDS: tuple[str, ...] = tuple(
    sorted(
        [
            "Camp Lejeune",
            "MCAS New River",
            "Republic of Vietnam",
            "Korean DMZ",
            "United Arab Emirates",
            "Camp Pendleton",
            "Fort Liberty",
            "Fort Bragg",
            "Fort Cavazos",
            "Fort Hood",
            "Fort Campbell",
            "Fort Moore",
            "Fort Benning",
            "Camp Casey",
            "Cam Ranh Bay",
            "Da Nang",
            "Johnston Atoll",
            "American Samoa",
            "Persian Gulf",
            "Diego Garcia",
            "Enewetak Atoll",
            "Afghanistan",
            "Saudi Arabia",
            "South Korea",
            "Philippines",
            "Uzbekistan",
            "Vietnam",
            "Thailand",
            "Cambodia",
            "Iraq",
            "Kuwait",
            "Bahrain",
            "Qatar",
            "Oman",
            "UAE",
            "Syria",
            "Jordan",
            "Djibouti",
            "Egypt",
            "Lebanon",
            "Yemen",
            "Somalia",
            "Okinawa",
            "Germany",
            "Korea",
            "Laos",
            "Guam",
            "Saigon",
            "Hiroshima",
            "Nagasaki",
        ],
        key=len,
        reverse=True,
    )
)


def suggest_locations_from_text(blob: str, *, limit: int = 24) -> list[str]:
    """Return curated location labels found in free text (case-insensitive)."""
    if not (blob or "").strip():
        return []
    text = blob
    # Case-insensitive search without destroying original display labels
    lower = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    for label in _LOCATION_KEYWORDS:
        key = label.lower()
        if key in seen:
            continue
        # Word-ish boundary: avoid matching "Iraq" inside unrelated tokens when possible
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lower):
            seen.add(key)
            found.append(label)
            if len(found) >= limit:
                break
    return found
