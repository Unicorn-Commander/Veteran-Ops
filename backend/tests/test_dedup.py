"""Unit tests for content-level near-duplicate detection (intake/dedup.py)."""

from app.intake import dedup


def test_normalized_text_folds_incidental_differences():
    a = dedup.normalized_text("Rating Decision — 70%!!  \n\n VA.gov")
    b = dedup.normalized_text("rating   decision 70 va gov")
    assert a == b == "rating decision 70 va gov"


def test_content_fingerprint_matches_after_normalization_only():
    # Same words, different case/punctuation/whitespace → same fingerprint.
    assert dedup.content_fingerprint("The C&P exam, dated 2019.") == dedup.content_fingerprint(
        "the c p   exam dated 2019"
    )
    # Genuinely different text → different fingerprint.
    assert dedup.content_fingerprint("knee condition") != dedup.content_fingerprint("back condition")
    # Empty → None (nothing to compare).
    assert dedup.content_fingerprint("   \n ") is None


_LONG = (
    "The veteran underwent a compensation and pension examination for the claimed "
    "condition of post traumatic stress disorder. The examiner reviewed the entire "
    "claims file and all available service treatment records in detail, then rendered a "
    "nexus opinion linking the current diagnosed condition to active military service, "
    "specifically citing the documented in service stressor event and the continuity of "
    "symptomatology reported by the veteran since separation from active duty. The "
    "examination was thorough and the supporting rationale was fully consistent with the "
    "record and the applicable regulations governing service connection."
)


def test_simhash_identical_text_has_zero_hamming():
    a = dedup.simhash64(_LONG)
    b = dedup.simhash64(_LONG)
    assert a is not None and a == b
    assert dedup.hamming(a, b) == 0


# A realistic OCR drift: a handful of scattered single-character misreads.
_NEAR = _LONG.replace("claims file", "clalms flle").replace("military service", "mllitary servlce")


def test_simhash_near_duplicate_is_close():
    assert _NEAR != _LONG  # the drift actually landed
    bits = dedup.hamming(dedup.simhash64(_LONG), dedup.simhash64(_NEAR))
    assert bits is not None and 0 < bits <= dedup.NEAR_DUP_FLAG_BITS


def test_simhash_distinct_text_is_far():
    other = (
        "This is an entirely unrelated buddy statement about a completely different "
        "back injury sustained years after separation, with no examination and no "
        "medical opinion of any kind in the record whatsoever."
    )
    bits = dedup.hamming(dedup.simhash64(_LONG), dedup.simhash64(other))
    assert bits is not None and bits > dedup.NEAR_DUP_FLAG_BITS


def test_hamming_none_when_missing():
    assert dedup.hamming(None, "0" * 16) is None
    assert dedup.hamming("0" * 16, None) is None


def test_verdict_exact_fingerprint_skips():
    fp = dedup.content_fingerprint(_LONG)
    sh = dedup.simhash64(_LONG)
    verdict, matched = dedup.duplicate_verdict(fp, sh, [("doc-1", fp, sh)])
    assert verdict == "skip" and matched == "doc-1"


def test_verdict_near_match_flags_never_skips():
    # A close-but-not-exact match FLAGS (safe) — fuzzy similarity must never auto-skip,
    # because VA boilerplate makes different documents look similar.
    sh = dedup.simhash64(_LONG)
    verdict, matched = dedup.duplicate_verdict(
        dedup.content_fingerprint(_NEAR), dedup.simhash64(_NEAR),
        [("orig", dedup.content_fingerprint(_LONG), sh)],
    )
    assert verdict == "flag" and matched == "orig"


def test_verdict_distinct_when_no_candidate_matches():
    fp = dedup.content_fingerprint(_LONG)
    sh = dedup.simhash64(_LONG)
    other_fp = dedup.content_fingerprint("nothing alike here at all friend")
    other_sh = dedup.simhash64(
        "nothing alike here at all friend and some more unrelated filler words to shingle"
    )
    verdict, matched = dedup.duplicate_verdict(fp, sh, [("x", other_fp, other_sh)])
    assert verdict == "distinct" and matched is None


def test_verdict_no_candidates_is_distinct():
    assert dedup.duplicate_verdict("abc", "0" * 16, []) == ("distinct", None)
