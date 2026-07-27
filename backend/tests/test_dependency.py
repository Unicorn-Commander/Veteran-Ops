"""Dependency workflow — 21-686c worksheet render (verbatim, no SSN, legal lane)."""

from __future__ import annotations

import re

from app.routers.dependency import _render_worksheet
from app.schemas import DependencyWorksheetIn, DependentEntry

# Filing/legal-opinion overreach the app must never assert.
_OVERREACH = re.compile(
    r"you (?:will|are) (?:awarded|entitled|owed)|we (?:will )?file|guarantee|"
    r"you qualify|this is legal advice",
    re.IGNORECASE,
)


def test_worksheet_reproduces_explanation_verbatim():
    words = "We were married on February 3, 2001 and remain married; the removal in 2025 was an error."
    out = _render_worksheet(DependencyWorksheetIn(
        veteran_name="Aaron Stransky",
        action="respond_to_removal",
        dependents=[DependentEntry(full_name="Jordan Example", relationship="spouse",
                                   event="Marriage", event_date="2001-02-03",
                                   notes="Still married; VA removed her in error.")],
        explanation=words,
        prior_removal_note="VA letter dated 2002-01 proposed removing my spouse.",
    ))
    assert words in out  # verbatim
    assert "Jordan Example" in out and "Still married; VA removed her in error." in out
    assert "VA Form 21-686c" in out
    assert "responding to" in out.lower()  # removal path rendered
    assert not _OVERREACH.search(out)


def test_worksheet_add_path_and_empty_is_safe():
    out = _render_worksheet(DependencyWorksheetIn(action="add"))
    assert "Add" in out and "Signature:" in out
    assert "____" in out  # placeholders, no crash
    assert not _OVERREACH.search(out)


def test_worksheet_never_prompts_for_ssn():
    out = _render_worksheet(DependencyWorksheetIn(
        veteran_name="X", dependents=[DependentEntry(full_name="Kai", relationship="child")],
    ))
    # No SSN input FIELD, and the worksheet actively warns not to write one here.
    assert not re.search(r"ssn\s*:|social security (?:number|no)\.?\s*:", out, re.IGNORECASE)
    assert "do not write social security" in out.lower()


def test_worksheet_skips_blank_dependents():
    out = _render_worksheet(DependencyWorksheetIn(
        dependents=[DependentEntry(), DependentEntry(full_name="Avery Example", event="Birth")],
    ))
    assert "Avery Example" in out
    assert "2. " not in out  # only the one real dependent numbered
