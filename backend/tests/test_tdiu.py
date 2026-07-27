"""TDIU workflow — worksheet render (verbatim, no fabrication) + legal lane."""

from __future__ import annotations

import re

from app.routers.tdiu import _render_worksheet
from app.schemas import TdiuJob, TdiuWorksheetIn

# TDIU is decided by VA — the worksheet must never assert the veteran qualifies.
_PROMISE = re.compile(
    r"you (?:will|are) (?:granted|entitled|unemployable|qualif)|you qualify|guarantee",
    re.IGNORECASE,
)


def test_worksheet_reproduces_narrative_verbatim():
    words = "I missed 8+ days a month from migraines and my manager let me go in March 2021."
    out = _render_worksheet(TdiuWorksheetIn(
        veteran_name="Aaron Stransky",
        last_full_time_date="March 2021",
        how_conditions_limit_work=words,
        jobs=[TdiuJob(employer="Acme", job_title="Analyst", dates="2018-2021",
                      hours_per_week="40", reason_ended="Let go after too many absences.")],
    ))
    assert words in out  # verbatim, unaltered
    assert "Acme" in out and "Let go after too many absences." in out
    assert "Aaron Stransky" in out
    assert "VA Form 21-8940" in out
    assert not _PROMISE.search(out)


def test_worksheet_is_usable_when_empty():
    out = _render_worksheet(TdiuWorksheetIn())
    # placeholders, not a crash; still names the form + signature block
    assert "____" in out
    assert "Signature:" in out
    assert not _PROMISE.search(out)


def test_worksheet_skips_blank_jobs():
    out = _render_worksheet(TdiuWorksheetIn(
        jobs=[TdiuJob(), TdiuJob(employer="Real Co", reason_ended="Quit due to pain.")],
    ))
    assert "Real Co" in out and "Quit due to pain." in out
    # the fully-blank job is not rendered as a numbered entry beyond the real one
    assert "2. " not in out
