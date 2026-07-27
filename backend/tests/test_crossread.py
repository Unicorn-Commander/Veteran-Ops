"""OCR cross-read (Phase 3 intake): two independent reads of the SAME page, one
fidelity score on the tokens a rating turns on. PURE — no fleet, no DB.

The one that matters: a 50-vs-70 misread of an evaluation is a real disagreement
(flagged), while cosmetic OCR noise (P.T.S.D. vs PTSD, '50%' vs '50 percent') is
NOT — only a genuine value conflict lowers confidence.
"""

from __future__ import annotations

from app.intake import crossread
from app.intake.crossread import compare_page, cross_read_document


def test_percent_misread_50_vs_70_is_a_delta():
    p = compare_page(0, "PTSD evaluated at 50 percent disabling.", "PTSD evaluated at 70 percent disabling.")
    assert p.flagged
    assert p.ocr_confidence < 1.0
    delta = next(d for d in p.deltas if d["field"] == "percent")
    assert delta["ocr_only"] == [50]
    assert delta["vision_only"] == [70]


def test_cosmetic_acronym_and_format_differences_align():
    # P.T.S.D. vs PTSD and "50%" vs "50 percent" carry the SAME critical tokens.
    p = compare_page(1, "PTSD granted at 50%.", "P.T.S.D. granted at 50 percent.")
    assert not p.flagged
    assert p.ocr_confidence == 1.0
    assert p.deltas == []


def test_decision_word_conflict_flags():
    p = compare_page(0, "The claim was granted.", "The claim was denied.")
    assert p.flagged
    assert {d["field"] for d in p.deltas} == {"decision"}


def test_diagnostic_code_band_excludes_years():
    # 9411 is a diagnostic code; 2019 is a year (outside the 5000–9999 DC band).
    assert crossread._dcs("PTSD under DC 9411, decided 2019.") == {"9411"}
    # A real DC conflict IS caught.
    p = compare_page(0, "Rated under 9411.", "Rated under 9434.")
    assert {d["field"] for d in p.deltas} == {"diagnostic_code"}


def test_no_critical_tokens_is_full_confidence():
    p = compare_page(0, "Narrative prose, no rating here.", "Entirely different narrative prose.")
    assert p.ocr_confidence == 1.0
    assert not p.flagged


def test_agreement_ratio_between_zero_and_one():
    # They agree on the decision (granted) but conflict on the percent → partial.
    p = compare_page(0, "PTSD granted at 50 percent.", "PTSD granted at 70 percent.")
    assert 0.0 < p.ocr_confidence < 1.0


def test_cross_read_document_summarizes_flags():
    reads = [
        {"page": 0, "ocr": "PTSD 50%", "vision": "PTSD 70%"},
        {"page": 1, "ocr": "tinnitus 10%", "vision": "tinnitus 10%"},
    ]
    out = cross_read_document(reads)
    assert out["pages_cross_read"] == 2
    assert out["pages_flagged"] == 1
    assert out["min_confidence"] < 1.0
    assert out["flagged_pages"][0]["page"] == 0
