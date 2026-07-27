"""Deterministic deep-dive dedupe, conflict, and rating-math coverage."""

from __future__ import annotations

from app.firm.base import Finding
from app.firm.candidates import CandidateRating
from app.firm.context import VeteranDossier
from app.firm.orchestrator import _dedupe_candidates
from app.firm.resolve import resolve_conflicts


def _finding(
    key: str,
    dc: str,
    percent: int,
    *,
    title: str,
    source_ref: str | None = None,
) -> Finding:
    body = f"Review DC {dc} at the card-authored {percent}% planning input."
    return Finding(
        specialist=f"rating_expert:{dc}",
        kind="direct",
        key=key,
        title=title,
        body=body,
        det_body=body,
        reviewed=True,
        seed={
            "diagnostic_code": dc,
            "origin": "direct",
            "rating_percent": percent,
            "tier_percents": [percent],
            "source_ref": source_ref,
        },
    )


def _dossier(conditions: list[dict] | None = None, current: int | None = None) -> VeteranDossier:
    return VeteranDossier(uid="00000000-0000-0000-0000-000000000001", conditions=conditions or [], current_combined=current)


def test_candidate_dedupe_uses_dc_origin_and_primary_dc_first_wins():
    first = CandidateRating("5257", "First", "musculoskeletal", "direct", "seed one", "c1", None)
    duplicate = CandidateRating("5257", "Second", "musculoskeletal", "direct", "seed two", "c2", None)
    secondary = CandidateRating("5257", "Secondary", "musculoskeletal", "secondary", "seed three", "c2", "5237")
    assert _dedupe_candidates([first, duplicate, secondary]) == [first, secondary]


def test_pyramiding_marks_lower_value_lane_without_deleting_it():
    # §4.130: two mental-health conditions carry ONE combined rating, so resolve
    # marks the lower-value lane superseded (not deleted). NOTE: CFS (6354) and
    # fibromyalgia (5025) are deliberately NO LONGER a pyramiding pair — different
    # body systems, separately ratable — so this uses the mental-health group.
    ptsd = _finding("ptsd", "9411", 50, title="PTSD", source_ref="p1")
    depression = _finding("depression", "9434", 30, title="Major depressive disorder", source_ref="p2")
    result = resolve_conflicts([depression, ptsd], _dossier(current=0))

    assert result.findings == [depression, ptsd]
    assert depression.seed["superseded_by"] == "ptsd"
    assert depression.seed["active"] is False
    assert "4.1" in depression.seed["conflict_cfr"]
    assert ptsd.seed["active"] is True


def test_exclusion_pair_keeps_higher_lane_and_cites_rule():
    # Ankylosis (5256) vs limitation of extension (5261) of the SAME knee: a fused
    # joint has no motion left to separately limit, so these are truly mutually
    # exclusive (unlike instability 5257 vs cartilage 5259, which ARE separately
    # ratable under Esteban and must not be in the exclusion table).
    ankylosis = _finding("ankylosis", "5256", 40, title="Knee ankylosis", source_ref="knee-1")
    limited_ext = _finding("limited_ext", "5261", 10, title="Limited extension", source_ref="knee-1")
    result = resolve_conflicts([limited_ext, ankylosis], _dossier(current=0))

    assert len(result.findings) == 2
    assert limited_ext.seed["excluded_by"] == "ankylosis"
    assert limited_ext.seed["active"] is False
    assert "4.14" in limited_ext.seed["conflict_cfr"]
    assert any("Mutual-exclusivity" in note for note in result.notes)


def test_same_dc_direct_and_increase_are_alternative_lanes():
    direct = _finding("deepdive:direct:8100:", "8100", 30, title="Migraines", source_ref="c1")
    increase = _finding("deepdive:increase:8100:", "8100", 50, title="Migraines", source_ref="c1")
    increase.kind = "increase"
    increase.seed["origin"] = "increase"

    result = resolve_conflicts([direct, increase], _dossier(current=30))

    assert len(result.findings) == 2
    assert direct.seed["superseded_by"] == increase.key
    assert direct.seed["active"] is False
    assert increase.seed["active"] is True
    assert any("Same-code review" in note for note in result.notes)


def test_projection_calls_engine_with_bilateral_factor_and_survivor():
    conditions = [
        {
            "id": "left-knee",
            "name": "Left knee strain",
            "diagnostic_code": "5260",
            "current_rating": 20,
        },
        {
            "id": "right-knee",
            "name": "Right knee strain",
            "diagnostic_code": "5260",
            "current_rating": 20,
        },
    ]
    tinnitus = _finding("tinnitus", "6260", 10, title="Tinnitus", source_ref="new-tinnitus")
    result = resolve_conflicts([tinnitus], _dossier(conditions, current=40))

    # 20 + 20 -> 36; §4.26 adds 3.6 -> 40; combine 40 + 10 -> 46; final -> 50.
    assert result.projected_combined == 50
    assert any("bilateral factor" in note.lower() for note in result.notes)
    assert any("+10 points" in note for note in result.notes)


def test_projection_preserves_profile_baseline_when_itemized_ratings_are_partial():
    conditions = [
        {
            "id": "known-one",
            "name": "Known condition",
            "diagnostic_code": "8100",
            "current_rating": 30,
            "va_status": "service_connected",
        }
    ]
    tinnitus = _finding("tinnitus", "6260", 10, title="Tinnitus", source_ref="new")
    result = resolve_conflicts([tinnitus], _dossier(conditions, current=70))

    # The profile's 70% is authoritative when the one imported 30% item cannot
    # reproduce it; engine math then combines that baseline with the new 10% -> 73 -> 70.
    assert result.projected_combined == 70
    assert any("do not reproduce" in note for note in result.notes)
