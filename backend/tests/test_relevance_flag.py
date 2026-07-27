"""Claim-relevance flagging (intake.classify) — the deterministic guard that
decides whether a document is SOFTLY flagged as possibly off-topic so the veteran
can review/delete it. The safety property under test: real evidence is NEVER
flagged, and 'off_topic' only ever suggests deletion, never removes anything.
"""

from __future__ import annotations

from app.intake.classify import relevance_flag, validate_extraction


def test_validate_defaults_relevance_to_unclear_when_missing():
    out = validate_extraction({"doc_type": "other"})
    assert out["relevance"] == "unclear"
    assert out["relevance_reason"] is None


def test_validate_rejects_bogus_relevance_value():
    # A hallucinated label outside the enum degrades to the SAFE 'unclear'.
    out = validate_extraction({"doc_type": "other", "relevance": "definitely_junk"})
    assert out["relevance"] == "unclear"


def test_validate_keeps_valid_relevance_and_reason():
    out = validate_extraction(
        {"doc_type": "other", "relevance": "off_topic", "relevance_reason": "utility bill"}
    )
    assert out["relevance"] == "off_topic"
    assert out["relevance_reason"] == "utility bill"


def test_off_topic_other_document_is_flagged():
    ex = {"doc_type": "other", "relevance": "off_topic", "relevance_reason": "store receipt"}
    v = relevance_flag(ex, "other")
    assert v["flagged"] is True
    assert v["reason"] == "store receipt"


def test_relevant_document_is_not_flagged():
    ex = {"doc_type": "other", "relevance": "relevant"}
    assert relevance_flag(ex, "other")["flagged"] is False


def test_unclear_never_flags():
    ex = {"doc_type": "other", "relevance": "unclear", "relevance_reason": "maybe"}
    v = relevance_flag(ex, "other")
    assert v["flagged"] is False
    assert v["reason"] is None  # reason only rides along when actually flagged


def test_evidentiary_doctype_never_flagged_even_if_model_says_off_topic():
    # The core safety invariant: a rating decision the model mislabeled off_topic
    # must NOT be put up for deletion.
    for dt in (
        "rating_decision",
        "decision_letter",
        "str",
        "dbq",
        "treatment_record",
        "private_medical_opinion",
        "lay_statement",
        "service_record",
    ):
        ex = {"doc_type": dt, "relevance": "off_topic", "relevance_reason": "x"}
        assert relevance_flag(ex, dt)["flagged"] is False, dt


def test_va_decision_content_overrides_off_topic_label():
    # Even doc_type 'other', if it is a VA decision or mentions conditions, it has
    # claim content and is never flagged.
    ex = {"doc_type": "other", "relevance": "off_topic", "is_va_decision": True}
    assert relevance_flag(ex, "other")["flagged"] is False


def test_mentioned_conditions_override_off_topic_label():
    ex = {
        "doc_type": "other",
        "relevance": "off_topic",
        "conditions_mentioned": [{"name": "tinnitus"}],
    }
    assert relevance_flag(ex, "other")["flagged"] is False


def test_none_extracted_is_safe():
    v = relevance_flag(None, None)
    assert v["flagged"] is False
    assert v["relevance"] == "unclear"
