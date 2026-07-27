"""Extract-verify (Phase 3 intake): the model must QUOTE the record for every
extracted fact, and a PURE validator disposes — a hallucinated quote is
`unsupported`, a real quote carrying the value is `confirmed`, a real quote
carrying a DIFFERENT value is `disputed`. No fleet, no DB.
"""

from __future__ import annotations

from app.intake.verify import (
    CONFIRMED,
    DISPUTED,
    UNSUPPORTED,
    UNVERIFIED,
    validate_verification,
)

SOURCE = (
    "VA Rating Decision. The veteran's PTSD is evaluated at 50 percent disabling "
    "under diagnostic code 9411. Tinnitus was granted at 10 percent."
)


def _extracted(conds):
    return {"conditions_mentioned": conds}


def test_real_span_carrying_the_value_confirms():
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": None}]
    )
    raw = {
        "conditions": [
            {"name": "PTSD", "span": "PTSD is evaluated at 50 percent disabling under diagnostic code 9411"}
        ]
    }
    out = validate_verification(SOURCE, extracted, raw)
    assert out["status"] == "clear"
    assert out["fields"] == []
    assert out["conditions"][0]["status"] == CONFIRMED


def test_hallucinated_span_is_unsupported():
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": None, "decision": None}]
    )
    raw = {"conditions": [{"name": "PTSD", "span": "The veteran's left leg was amputated below the knee"}]}
    out = validate_verification(SOURCE, extracted, raw)
    assert out["status"] == "flagged"
    f = out["fields"][0]
    assert f["status"] == UNSUPPORTED
    assert f["field"] == "name"
    assert out["conditions"][0]["status"] == UNSUPPORTED


def test_real_span_with_a_different_value_is_disputed():
    # The extraction says 70%, but the (real) quote says 50% → dispute, candidate 50.
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 70, "diagnostic_code": None, "decision": None}]
    )
    raw = {"conditions": [{"name": "PTSD", "span": "PTSD is evaluated at 50 percent disabling"}]}
    out = validate_verification(SOURCE, extracted, raw)
    assert out["status"] == "flagged"
    f = next(x for x in out["fields"] if x["field"] == "rating_percent")
    assert f["status"] == DISPUTED
    assert f["extracted_value"] == 70
    assert f["candidate_value"] == 50


def test_grounded_span_with_conflicting_value_is_disputed():
    # The span is real and carries 10%, but the extraction claims 30% → a conflict.
    extracted = _extracted(
        [{"name": "Tinnitus", "rating_percent": 30, "diagnostic_code": None, "decision": None}]
    )
    raw = {"conditions": [{"name": "Tinnitus", "span": "Tinnitus was granted at 10 percent"}]}
    out = validate_verification(SOURCE, extracted, raw)
    f = next(x for x in out["fields"] if x["field"] == "rating_percent")
    assert f["status"] == DISPUTED
    assert f["candidate_value"] == 10


def test_grounded_span_missing_the_value_is_unsupported():
    # The span is real but says nothing about a percent the extraction claims.
    extracted = _extracted(
        [{"name": "Tinnitus", "rating_percent": 10, "diagnostic_code": None, "decision": None}]
    )
    # "Tinnitus was granted" IS in the source but carries no percent.
    raw = {"conditions": [{"name": "Tinnitus", "span": "Tinnitus was granted"}]}
    out = validate_verification(SOURCE, extracted, raw)
    f = next(x for x in out["fields"] if x["field"] == "rating_percent")
    assert f["status"] == UNSUPPORTED
    assert f["candidate_value"] is None


def test_no_span_returned_is_unverified_not_a_flag():
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": None, "decision": None}]
    )
    out = validate_verification(SOURCE, extracted, {"conditions": [{"name": "PTSD", "span": ""}]})
    assert out["status"] == "clear"
    assert out["conditions"][0]["status"] == UNVERIFIED
    assert out["fields"] == []


def test_recall_flags_a_real_missing_condition():
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": None, "decision": None}]
    )
    raw = {
        "conditions": [{"name": "PTSD", "span": "PTSD is evaluated at 50 percent disabling"}],
        "missing": [{"name": "Tinnitus", "span": "Tinnitus was granted at 10 percent"}],
    }
    out = validate_verification(SOURCE, extracted, raw)
    assert out["status"] == "flagged"
    assert [m["name"] for m in out["missing_conditions"]] == ["Tinnitus"]


def test_recall_discards_a_hallucinated_missing_condition():
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": None, "decision": None}]
    )
    raw = {
        "conditions": [{"name": "PTSD", "span": "PTSD is evaluated at 50 percent disabling"}],
        # not in the source at all → thrown away
        "missing": [{"name": "Diabetes", "span": "Diabetes mellitus type 2 with peripheral neuropathy"}],
    }
    out = validate_verification(SOURCE, extracted, raw)
    assert out["missing_conditions"] == []
    assert out["status"] == "clear"
