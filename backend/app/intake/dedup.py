"""Near-duplicate detection over a document's extracted text.

VA C-files are downloaded in overlapping bundles and records get re-scanned, so
the same content arrives as different *bytes* — the upload-time sha256 (raw bytes)
can't catch it. This runs AFTER text extraction, on the OCR/PDF text, and answers
one question: does this document say substantially the same thing as one the
veteran already has ready?

Two cheap, deterministic signals:

  * a CONTENT FINGERPRINT — sha256 of normalized text. Identical after normalization
    (whitespace/case/punctuation folded) ⇒ same content, zero false positives. This
    catches the common case: the same C-file re-downloaded, a PDF re-exported, a
    re-scan that OCRs to the same words.
  * a 64-bit SIMHASH over token 3-shingles — near-identical text has a small Hamming
    distance. This catches the fuzzy band (a re-scan with minor OCR drift) that the
    exact fingerprint misses. Compact (one hex column), O(1) to compare.

SAFETY POLICY — auto-skip ONLY on an EXACT content match. VA records share heavy
boilerplate (form headers, standard exam language), so two DIFFERENT documents can be
highly similar by any fuzzy metric. Silently dropping a veteran's evidence because it
resembles a template would be a real harm, so fuzzy similarity never auto-skips — it
only FLAGS a possible duplicate for the veteran to judge, and the record stays in the
analysis until they decide. Exact normalized-content matches (a re-downloaded bundle,
a re-exported PDF) are safe to skip and carry the bulk of real duplication.
"""

from __future__ import annotations

import hashlib
import re

# Hamming distance (of the 64-bit simhash) at or below which the newcomer is KEPT but
# flagged as a POSSIBLE duplicate for the veteran to judge (never auto-dropped). On
# realistic records an OCR-drifted re-scan lands at 2–6 bits while distinct documents
# sit far above (~35), so this comfortably separates the two without over-flagging.
NEAR_DUP_FLAG_BITS = 8

_WORD_RE = re.compile(r"[a-z0-9]+")
_SHINGLE = 3  # token n-gram width for the simhash


def normalized_text(text: str) -> str:
    """Fold text to its content skeleton: lowercase alphanumeric tokens, single
    spaces. Strips the incidental differences (case, punctuation, whitespace,
    header/footer spacing) that make re-scans differ byte-for-byte."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def content_fingerprint(text: str) -> str | None:
    """sha256 over the normalized text — a stable exact-content key. None for empty
    text (nothing to compare)."""
    norm = normalized_text(text)
    if not norm:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def simhash64(text: str) -> str | None:
    """A 64-bit SimHash over token 3-shingles, returned as a 16-char hex string
    (DB-agnostic; no signed-BIGINT juggling). None for text too short to shingle."""
    tokens = _tokens(text)
    if len(tokens) < _SHINGLE:
        # Too short for shingles — fall back to single tokens so short records still
        # get a signature rather than none.
        shingles = tokens
    else:
        shingles = [" ".join(tokens[i : i + _SHINGLE]) for i in range(len(tokens) - _SHINGLE + 1)]
    if not shingles:
        return None
    bits = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode("utf-8"), digest_size=8).digest(), "big")
        for b in range(64):
            bits[b] += 1 if (h >> b) & 1 else -1
    value = 0
    for b in range(64):
        if bits[b] > 0:
            value |= 1 << b
    return f"{value:016x}"


def hamming(a: str | None, b: str | None) -> int | None:
    """Bit-difference between two hex simhashes (0 = identical signature). None if
    either is missing."""
    if not a or not b:
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def file_stem(name: str) -> str:
    """Lowercase basename without extension — Blue Button pdf/txt twin detection."""
    base = (name or "").strip().rsplit("/", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.casefold().strip()


def prefer_keep_other(my_name: str, other_name: str) -> bool:
    """True when the other file is the better keep for the same export stem.

    Prefer plain-text My HealtheVet / Blue Button exports over a PDF of the same
    stem — the .txt skips OCR and classifies with cleaner text.
    """
    my_stem, other_stem = file_stem(my_name), file_stem(other_name)
    if not my_stem or my_stem != other_stem:
        return False
    my_l, other_l = (my_name or "").casefold(), (other_name or "").casefold()
    if my_l.endswith(".pdf") and (
        other_l.endswith(".txt") or other_l.endswith(".text") or other_l.endswith(".csv")
    ):
        return True
    return False


def same_export_stem_peer(
    my_name: str,
    candidates: list[tuple],
) -> str | None:
    """If a ready peer shares our filename stem as a pdf↔txt twin, return its id.

    `candidates` rows are (id, fingerprint, simhash, status, filename, created_at).
    """
    my_stem = file_stem(my_name)
    if not my_stem:
        return None
    my_l = (my_name or "").casefold()
    for row in candidates:
        if len(row) < 5:
            continue
        cid, _fp, _sh, st, fn = row[0], row[1], row[2], row[3], row[4]
        if st != "ready":
            continue
        if file_stem(fn or "") != my_stem:
            continue
        other_l = (fn or "").casefold()
        formats = {my_l.rsplit(".", 1)[-1], other_l.rsplit(".", 1)[-1]}
        if formats <= {"pdf", "txt", "text", "csv"} and len(formats) >= 2:
            return str(cid)
    return None


def duplicate_verdict(
    fingerprint: str | None,
    simhash: str | None,
    candidates: list[tuple[str, str | None, str | None]],
) -> tuple[str, str | None]:
    """Decide this document's relation to already-ready documents.

    `candidates` is (document_id, fingerprint, simhash) for the veteran's other ready
    documents. Returns (verdict, matched_document_id) where verdict is:
      * "skip"     — EXACT same content as `matched_document_id`; don't process/analyze.
      * "flag"     — possibly a duplicate of `matched_document_id`; KEEP + flag (never
                     auto-dropped — the veteran decides; the record stays analyzed).
      * "distinct" — no near-match; process normally (matched_document_id is None).
    Exact fingerprint match wins (skip). Otherwise the closest simhash within
    NEAR_DUP_FLAG_BITS is a flag only — fuzzy similarity NEVER auto-skips (see the
    module's safety policy on VA boilerplate).
    """
    best_bits: int | None = None
    best_id: str | None = None
    for cand_id, cand_fp, cand_sh in candidates:
        if fingerprint and cand_fp and fingerprint == cand_fp:
            return "skip", cand_id
        bits = hamming(simhash, cand_sh)
        if bits is None:
            continue
        if best_bits is None or bits < best_bits:
            best_bits, best_id = bits, cand_id
    if best_bits is not None and best_bits <= NEAR_DUP_FLAG_BITS:
        return "flag", best_id
    return "distinct", None
