from __future__ import annotations

from app.benefits.filter import filter_benefits


def test_filter_benefits_groups_by_category_and_filters_state():
    dataset = {
        "verified_as_of": "2026-07-08",
        "benefits": [
            {
                "id": "fed",
                "name": "Federal",
                "description": "Federal benefit",
                "category": "federal",
                "min_rating": 30,
                "requires_pt": False,
                "states": [],
                "source_name": "Source",
                "source_url": "https://example.com/fed",
                "confidence": "established",
            },
            {
                "id": "sc",
                "name": "South Carolina",
                "description": "State benefit",
                "category": "state",
                "min_rating": 100,
                "requires_pt": True,
                "states": ["SC"],
                "source_name": "Source",
                "source_url": "https://example.com/sc",
                "confidence": "varies",
            },
            {
                "id": "other",
                "name": "Other state",
                "description": "State benefit",
                "category": "state",
                "min_rating": 10,
                "requires_pt": False,
                "states": ["NC"],
                "source_name": "Source",
                "source_url": "https://example.com/nc",
                "confidence": "varies",
            },
        ],
    }

    out = filter_benefits(dataset, rating=100, state="sc")
    assert [b["id"] for b in out["federal"]] == ["fed"]
    assert [b["id"] for b in out["state"]] == ["sc"]
    assert out["commercial"] == []

    out_nc = filter_benefits(dataset, rating=100, state="nc")
    assert [b["id"] for b in out_nc["state"]] == ["other"]
    assert out_nc["federal"][0]["id"] == "fed"

