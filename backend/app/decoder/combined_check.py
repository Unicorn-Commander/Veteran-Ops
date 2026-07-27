"""Educational cross-check of the letter's combined evaluation.

We recompute the §4.25 combined rating from the GRANTED percentages the decoder
extracted, using the frozen rating engine, and compare it to the combined
evaluation the VA stated on the letter. This surfaces the two things veterans
most often miss: (1) a possible VA math/transcription question worth raising, and
(2) the far more common benign explanation — the stated combined includes
conditions granted in EARLIER decisions that aren't listed on this one.

The VA's stated combined ALWAYS controls. This is a teaching aid, never a claim
that the VA is wrong.
"""

from __future__ import annotations

from ..rating.engine import RatingEntry, combined_rating

_MATCH_NOTE = (
    "Your own §4.25 combine of the conditions GRANTED on this letter matches the "
    "combined evaluation the VA stated. (If you have other service-connected "
    "conditions from earlier decisions, your overall combined rating is higher — "
    "this letter only shows what changed here.)"
)
_MISMATCH_NOTE = (
    "Heads up — combining just the conditions GRANTED on THIS letter with the "
    "§4.25 table gives a different number than the combined evaluation printed on "
    "it. That is USUALLY expected: the stated combined also folds in conditions "
    "granted in earlier decisions that aren't listed here, plus the bilateral "
    "factor and any SMC. Occasionally it flags a real transcription or math "
    "question worth raising with a VSO. Compare against your full list of "
    "service-connected conditions before assuming anything."
)
_UNKNOWN_NOTE = (
    "Not enough was detected on this letter to cross-check the combined "
    "evaluation. The number printed on the letter is what controls."
)


def cross_check_combined(
    granted: list[dict],
    va_stated: int | None,
) -> dict:
    """granted: [{name, rating_percent, ...}] — GRANTED lines only (the caller
    filters). va_stated: the combined evaluation parsed off the letter, or None.

    Returns {va_stated, computed, matches, note}. `computed` is our §4.25 recompute
    from the granted percents (None when there's nothing compensable to combine).
    `matches` is None when either side is unknown. Bilateral/side info isn't on a
    decision letter, so this is a plain combine — the note owns that caveat.
    """
    percents = [
        g.get("rating_percent")
        for g in granted or []
        if isinstance(g.get("rating_percent"), int)
        and not isinstance(g.get("rating_percent"), bool)
    ]
    computed: int | None = None
    if percents:
        entries = [RatingEntry(label=f"c{i}", percent=p) for i, p in enumerate(percents)]
        computed = combined_rating(entries).combined

    if va_stated is None or computed is None:
        matches: bool | None = None
        note = _UNKNOWN_NOTE
    else:
        matches = va_stated == computed
        note = _MATCH_NOTE if matches else _MISMATCH_NOTE

    return {
        "va_stated": va_stated,
        "computed": computed,
        "matches": matches,
        "note": note,
    }
