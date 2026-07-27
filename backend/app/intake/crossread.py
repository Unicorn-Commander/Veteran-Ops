"""Per-page OCR cross-read — two independent transcriptions, one fidelity score.

A scanned C-file page is read TWICE by two independent engines (dots.ocr on the
GPU and the local vision model) and this module compares them on the tokens that
actually decide a rating: the evaluation PERCENT, the 4-digit DIAGNOSTIC CODE, the
DATE, and the DECISION word (granted/denied/deferred). Where the two reads
disagree on one of those, the page is low-confidence and gets flagged for a human
look — a 50-vs-70 misread of an evaluation is exactly the error a single OCR pass
hides.

PURE + stdlib-only (mirrors intake/segment.py): no LLM, no I/O — the two reads are
produced upstream in intake/ocr.py and handed here as plain strings, so this whole
comparison is unit-testable without the fleet. The normalizers are the SAME pure
cleaners the classifier disposes with (classify._clean_percent / _clean_dc /
_clean_date), so "50%", "50 percent" and "50" collapse to one token and a cosmetic
OCR difference (P.T.S.D. vs PTSD) never reads as a disagreement — only a real value
conflict does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .classify import _clean_date, _clean_dc, _clean_percent

# The four token classes a rating turns on. Anything else (prose, headers, a
# condition name's punctuation) is deliberately ignored — cosmetic OCR noise must
# not manufacture a false dispute.
CRITICAL_FIELDS = ("percent", "diagnostic_code", "date", "decision")

_PERCENT_RE = re.compile(r"(\d{1,3})\s*(?:%|percent\b|pct\b)", re.IGNORECASE)
# Any 4-digit (or 4-4) token; the VA diagnostic-code band gate below drops years
# and other incidental 4-digit numbers so they don't masquerade as a DC conflict.
_DC_RE = re.compile(r"\b(\d{4}(?:-\d{4})?)\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_US_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
_DECISION_RE = re.compile(r"\b(granted|denied|deferred)\b", re.IGNORECASE)

# VA rating diagnostic codes live in 5000–9999 (musculoskeletal 5xxx … mental
# 9xxx … dental 99xx). Gating on that band keeps a mis-transcribed YEAR (1900–2099)
# out of the DC comparison — it belongs to the date check instead.
_DC_MIN = 5000
_DC_MAX = 9999


def _percents(text: str) -> set[int]:
    """VALID VA evaluation percents (0–100, multiple of 10) the read states. Using
    the classifier's cleaner means off-grid OCR noise (a stray '55') is dropped
    rather than raised as a phantom disagreement."""
    out: set[int] = set()
    for m in _PERCENT_RE.findall(text or ""):
        p = _clean_percent(m)
        if p is not None:
            out.add(p)
    return out


def _dcs(text: str) -> set[str]:
    """4-digit diagnostic codes in the VA band (years/incidental 4-digit tokens
    excluded), normalized through the classifier's _clean_dc."""
    out: set[str] = set()
    for m in _DC_RE.findall(text or ""):
        code = _clean_dc(m)
        if code and _DC_MIN <= int(code[:4]) <= _DC_MAX:
            out.add(code)
    return out


def _norm_date(token: str) -> str | None:
    """Normalize a date token to ISO for comparison. ISO goes straight through the
    classifier's _clean_date; a common US M/D/Y form is canonicalized so the two
    reads compare on the same footing."""
    iso = _clean_date(token)
    if iso:
        return iso
    parts = token.split("/")
    if len(parts) == 3:
        try:
            month, day, year = (int(p) for p in parts)
        except ValueError:
            return None
        if year < 100:
            year += 2000 if year < 70 else 1900
        return _clean_date(f"{year:04d}-{month:02d}-{day:02d}")
    return None


def _dates(text: str) -> set[str]:
    out: set[str] = set()
    for token in _ISO_DATE_RE.findall(text or "") + _US_DATE_RE.findall(text or ""):
        iso = _norm_date(token)
        if iso:
            out.add(iso)
    return out


def _decisions(text: str) -> set[str]:
    return {d.lower() for d in _DECISION_RE.findall(text or "")}


def _tokens(text: str) -> dict[str, set]:
    return {
        "percent": _percents(text),
        "diagnostic_code": _dcs(text),
        "date": _dates(text),
        "decision": _decisions(text),
    }


@dataclass(frozen=True)
class PageCrossRead:
    """One page's two-engine agreement.

    ocr_confidence is the agreement RATIO over every critical token the two reads
    saw between them (1.0 when they agree or there was nothing at stake; 0.0 when
    every critical token conflicts). deltas name the exact conflicting values so
    the review UI can show "OCR: 50%  vs  vision: 70%".
    """

    page: int
    ocr_confidence: float
    deltas: list[dict]

    @property
    def flagged(self) -> bool:
        return bool(self.deltas)

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "ocr_confidence": round(self.ocr_confidence, 4),
            "deltas": self.deltas,
        }


def compare_page(page: int, ocr_text: str, vision_text: str) -> PageCrossRead:
    """Compare two reads of the SAME page image on the four critical token classes.

    A page with no critical tokens is confidence 1.0 with no deltas (nothing a
    rating depends on was read either way — there is nothing to dispute)."""
    ocr = _tokens(ocr_text)
    vision = _tokens(vision_text)
    agree = union = 0
    deltas: list[dict] = []
    for field in CRITICAL_FIELDS:
        o, v = ocr[field], vision[field]
        agree += len(o & v)
        union += len(o | v)
        if o != v:
            deltas.append(
                {
                    "field": field,
                    "ocr_only": sorted(o - v, key=str),
                    "vision_only": sorted(v - o, key=str),
                }
            )
    confidence = 1.0 if union == 0 else agree / union
    return PageCrossRead(page=page, ocr_confidence=confidence, deltas=deltas)


def cross_read_document(page_reads: list[dict]) -> dict:
    """Reduce a document's per-page two-engine reads into a fidelity record.

    `page_reads` is [{"page": int, "ocr": str, "vision": str}, ...] (produced by
    intake/ocr.py when both engines ran). Returns per-page confidences + the
    conflicting pages, honest about how much of the file was actually cross-read.
    Pages the caller could not read at all are NOT here (they carry no second read);
    the caller records those separately as unreadable.
    """
    pages: list[PageCrossRead] = []
    for entry in page_reads or []:
        if not isinstance(entry, dict):
            continue
        pages.append(
            compare_page(
                int(entry.get("page") or 0),
                str(entry.get("ocr") or ""),
                str(entry.get("vision") or ""),
            )
        )
    flagged = [p for p in pages if p.flagged]
    min_conf = min((p.ocr_confidence for p in pages), default=1.0)
    return {
        "pages_cross_read": len(pages),
        "pages_flagged": len(flagged),
        "min_confidence": round(min_conf, 4),
        "flagged_pages": [p.to_dict() for p in flagged],
        "pages": [p.to_dict() for p in pages],
    }
