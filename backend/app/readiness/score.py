"""Evidence readiness score — PURE, deterministic, reuses analysis/gaps.py.

A single 0–100 % per condition = share of the core service-connection elements
that are satisfied, derived from the SAME gap engine the app teaches with (so the
score and the gap checklist can never disagree). The informational
"at schedular maximum" item is not a missing element and is excluded.

Educational only — a readiness score is not a prediction of the VA's decision.
"""

from __future__ import annotations

from ..analysis.gaps import analyze_gaps

# Core required elements per claim type — the maximum number of distinct gaps the
# gap engine can raise for that path (must track analysis/gaps.py). Used as the
# denominator so the score is a clean fraction of what a claim of that type needs.
_TOTAL_BY_TYPE = {"direct": 4, "secondary": 3, "presumptive": 2, "increase": 2}
_DEFAULT_TOTAL = 4

# Bands: score → (band key, hue is the frontend's concern). Kept here so the API
# and any test agree on the thresholds.
_BANDS = (
    (0, "early"),
    (34, "building"),
    (67, "strong"),
    (100, "complete"),
)


def band_for(score: int) -> str:
    band = "early"
    for threshold, name in _BANDS:
        if score >= threshold:
            band = name
    return band


def _is_informational(gap: dict) -> bool:
    """The at-schedular-maximum item is educational, not a missing element."""
    return "schedular maximum" in (gap.get("label") or "").lower()


def score_condition(
    condition: dict,
    evidence: list[dict],
    profile: dict | None = None,
    max_ratings: dict[str, dict] | None = None,
) -> dict:
    """{condition_id, name, claim_type, score, band, missing, satisfied, total}."""
    claim_type = (condition or {}).get("claim_type") or "direct"
    total = _TOTAL_BY_TYPE.get(claim_type, _DEFAULT_TOTAL)

    gaps = analyze_gaps(condition, evidence, profile, max_ratings=max_ratings)
    real_gaps = [g for g in gaps if not _is_informational(g)]
    # A malformed condition can't raise more gaps than its element count; clamp so
    # satisfied never goes negative.
    missing_count = min(len(real_gaps), total)
    satisfied = total - missing_count
    score = round(100 * satisfied / total) if total else 0

    return {
        "condition_id": condition.get("id"),
        "name": condition.get("name") or "this condition",
        "claim_type": claim_type,
        "score": score,
        "band": band_for(score),
        "missing": [g.get("label") for g in real_gaps if g.get("label")],
        "satisfied": satisfied,
        "total": total,
    }


def overall_readiness(condition_scores: list[dict]) -> dict:
    """Simple average of per-condition scores → {score, band, label, conditions_scored}."""
    scored = [c for c in condition_scores if isinstance(c.get("score"), int)]
    if not scored:
        return {
            "score": 0,
            "band": "early",
            "label": "Add a condition to see your readiness",
            "conditions_scored": 0,
        }
    avg = round(sum(c["score"] for c in scored) / len(scored))
    band = band_for(avg)
    label = {
        "early": "Just getting started — key evidence still needed",
        "building": "Coming together — a few gaps left to close",
        "strong": "Strong — most evidence is in place",
        "complete": "All core evidence identified for every condition",
    }[band]
    return {"score": avg, "band": band, "label": label, "conditions_scored": len(scored)}
