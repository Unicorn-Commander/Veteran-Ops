"""C-CDA (Consolidated CDA / CCD) parser — VA Health Summary & friends.

Veterans can download their VA medical record as a C-CDA XML "Continuity of
Care Document" (VA Blue Button / My HealtheVet "VA Health Summary"). This
module parses it DETERMINISTICALLY — structured clinical XML needs no LLM, so
the intake pipeline bypasses classification entirely when a CCD is detected
(see intake/process.py): the parse is exact, repeatable, and keeps the whole
document local.

Security — XML parsing:
  requirements.txt has no defusedxml and we must not add dependencies, so we
  use stdlib xml.etree.ElementTree with an explicit pre-parse guard: any
  document containing a DTD ("<!DOCTYPE") or entity declaration ("<!ENTITY")
  is REJECTED outright. ElementTree already refuses undefined entities and
  never fetches external ones; the guard closes the remaining internal
  entity-expansion (billion-laughs) vector, which requires a DTD to declare
  entities. A legitimate C-CDA never carries a DTD. If defusedxml appears in
  the environment later, it is picked up automatically and the guard remains
  as belt-and-suspenders. Input size is capped.

Everything extracted is best-effort: a section or field that isn't present (or
is malformed) is skipped, never invented.
"""

from __future__ import annotations

import logging
import re

try:  # optional hardening — NOT a new requirement (see module docstring)
    from defusedxml import ElementTree as ET  # type: ignore[import-not-found]
except ImportError:
    from xml.etree import ElementTree as ET

log = logging.getLogger("veteran_ops.intake.ccd")

MAX_CCD_CHARS = 15_000_000  # ~15 MB of text — far above any real CCD
_MAX_ITEMS_PER_SECTION = 500

# LOINC section codes (C-CDA R2.1 section templates).
_SECTIONS = {
    "11450-4": "problems",       # Problem list
    "10160-0": "medications",    # History of medication use
    "48765-2": "allergies",      # Allergies and adverse reactions
    "11369-6": "immunizations",  # Immunization history
    "8716-3": "vitals",          # Vital signs
    "30954-2": "labs",           # Relevant diagnostic tests / lab results
    "46240-8": "encounters",     # Encounters
}

_DTD_RE = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_ROOT_RE = re.compile(
    r"<\s*(?:[\w.-]+:)?ClinicalDocument[\s>]",  # first real element, any ns prefix
)
_DECL_OR_MISC_RE = re.compile(r"(<\?.*?\?>|<!--.*?-->|\s+)", re.DOTALL)


def sniff_ccd(text: str | None) -> bool:
    """Cheap detection: is this XML whose ROOT element is ClinicalDocument?
    Looks only at the head of the document (after the XML declaration,
    comments, and whitespace)."""
    if not text:
        return False
    head = text.lstrip("﻿")[:8000]
    # Strip leading declaration/comments/whitespace, then require the root tag.
    pos = 0
    while True:
        m = _DECL_OR_MISC_RE.match(head, pos)
        if not m:
            break
        pos = m.end()
    return bool(_ROOT_RE.match(head, pos))


# ── Element helpers (namespace-agnostic: match by local name) ────────────────

def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _children(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _child(el, name: str):
    kids = _children(el, name)
    return kids[0] if kids else None


def _descendants(el, name: str):
    return [d for d in el.iter() if _local(d.tag) == name]


def _text(el) -> str | None:
    if el is None:
        return None
    value = " ".join("".join(el.itertext()).split())
    return value or None


def _hl7_date(value: str | None) -> str | None:
    """HL7 TS ('20190314', '201903141030-0500') → ISO 'YYYY-MM-DD'."""
    if not value:
        return None
    digits = re.match(r"(\d{4})(\d{2})?(\d{2})?", value.strip())
    if not digits:
        return None
    y, m, d = digits.group(1), digits.group(2), digits.group(3)
    try:
        year = int(y)
        month = int(m) if m else None
        day = int(d) if d else None
    except ValueError:
        return None
    if not (1900 <= year <= 2200):
        return None
    if month and not 1 <= month <= 12:
        month = None
    if day and not 1 <= day <= 31:
        day = None
    if month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    if month:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}"


def _time_bounds(el) -> tuple[str | None, str | None]:
    """(low, high) — or (value, None) for point-in-time effectiveTime."""
    et = _child(el, "effectiveTime")
    if et is None:
        return None, None
    low = _child(et, "low")
    high = _child(et, "high")
    if low is None and high is None:
        return _hl7_date(et.get("value")), None
    return (
        _hl7_date(low.get("value") if low is not None else None),
        _hl7_date(high.get("value") if high is not None else None),
    )


def _display(el) -> str | None:
    """displayName attr, else originalText/name text."""
    if el is None:
        return None
    name = (el.get("displayName") or "").strip()
    if name:
        return name
    for tag in ("originalText", "name"):
        t = _text(_child(el, tag))
        if t:
            return t
    return None


def _value_quantity(obs) -> tuple[str | None, str | None]:
    val = _child(obs, "value")
    if val is None:
        return None, None
    v = val.get("value")
    if v is not None:
        return str(v), (val.get("unit") or None)
    return _display(val) or _text(val), None


# ── Parse ────────────────────────────────────────────────────────────────────

def _safe_parse(text: str):
    if len(text) > MAX_CCD_CHARS:
        log.info("CCD rejected: too large (%s chars)", len(text))
        return None
    if _DTD_RE.search(text):
        log.info("CCD rejected: contains a DTD/entity declaration")
        return None
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def parse_ccd(text: str) -> dict | None:
    """Full best-effort parse. None when the text isn't a parseable
    ClinicalDocument (caller falls back to the normal pipeline)."""
    root = _safe_parse(text.lstrip("﻿"))
    if root is None or _local(root.tag) != "ClinicalDocument":
        return None

    doc_time = _child(root, "effectiveTime")
    out: dict = {
        "title": _text(_child(root, "title")),
        "doc_date": _hl7_date(doc_time.get("value") if doc_time is not None else None),
        "problems": [],
        "medications": [],
        "allergies": [],
        "immunizations": [],
        "vitals": [],
        "labs": [],
        "encounters": [],
    }

    for section in _descendants(root, "section"):
        code_el = _child(section, "code")
        key = _SECTIONS.get(code_el.get("code") if code_el is not None else None)
        if key is None:
            continue
        parser = _SECTION_PARSERS[key]
        try:
            items = parser(section)
        except Exception:  # noqa: BLE001 — one bad section must not sink the doc
            log.exception("CCD section %s failed to parse", key)
            continue
        out[key].extend(items[: _MAX_ITEMS_PER_SECTION - len(out[key])])
    return out


def _parse_problems(section) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for obs in _descendants(section, "observation"):
        val = _child(obs, "value")
        name = _display(val)
        if not name:
            continue
        low, high = _time_bounds(obs)
        key = f"{name.casefold()}|{low}"
        if key in seen:
            continue
        seen.add(key)
        status = _child(obs, "statusCode")
        items.append(
            {
                "name": name,
                "code": (val.get("code") or None) if val is not None else None,
                "code_system": (val.get("codeSystemName") or None)
                if val is not None
                else None,
                "onset_date": low,
                "resolved_date": high,
                "status": (status.get("code") or None) if status is not None else None,
            }
        )
    return items


def _parse_medications(section) -> list[dict]:
    items: list[dict] = []
    for sa in _descendants(section, "substanceAdministration"):
        material = None
        for m in _descendants(sa, "manufacturedMaterial"):
            material = m
            break
        name = _display(_child(material, "code")) if material is not None else None
        if not name:
            continue
        low, high = _time_bounds(sa)
        dose = _child(sa, "doseQuantity")
        status = _child(sa, "statusCode")
        items.append(
            {
                "name": name,
                "dose": (dose.get("value") or None) if dose is not None else None,
                "dose_unit": (dose.get("unit") or None) if dose is not None else None,
                "start_date": low,
                "end_date": high,
                "status": (status.get("code") or None) if status is not None else None,
            }
        )
    return items


def _parse_allergies(section) -> list[dict]:
    items: list[dict] = []
    for obs in _descendants(section, "observation"):
        substance = None
        for pe in _descendants(obs, "playingEntity"):
            substance = _display(_child(pe, "code")) or _text(_child(pe, "name"))
            if substance:
                break
        if not substance:
            continue
        reaction = None
        severity = None
        for er in _children(obs, "entryRelationship"):
            inner = _child(er, "observation")
            if inner is None:
                continue
            code_el = _child(inner, "code")
            code = code_el.get("code") if code_el is not None else None
            if code == "SEV":
                severity = _display(_child(inner, "value"))
            elif reaction is None:
                reaction = _display(_child(inner, "value"))
        items.append({"substance": substance, "reaction": reaction, "severity": severity})
    return items


def _parse_immunizations(section) -> list[dict]:
    items: list[dict] = []
    for sa in _descendants(section, "substanceAdministration"):
        name = None
        for m in _descendants(sa, "manufacturedMaterial"):
            name = _display(_child(m, "code")) or _text(_child(m, "name"))
            break
        if not name:
            continue
        low, _high = _time_bounds(sa)
        items.append({"name": name, "date": low})
    return items


def _parse_observations(section) -> list[dict]:
    """Vitals and labs share a shape: named observation + value/unit + date."""
    items: list[dict] = []
    for obs in _descendants(section, "observation"):
        name = _display(_child(obs, "code"))
        value, unit = _value_quantity(obs)
        if not name or value is None:
            continue
        low, _high = _time_bounds(obs)
        item = {"name": name, "value": value, "unit": unit, "date": low}
        ref = _child(obs, "referenceRange")
        rng = _text(_child(ref, "observationRange")) if ref is not None else None
        if rng:
            item["reference_range"] = rng
        items.append(item)
    return items


def _parse_encounters(section) -> list[dict]:
    items: list[dict] = []
    for enc in _descendants(section, "encounter"):
        desc = _display(_child(enc, "code")) or _text(_child(enc, "text"))
        low, _high = _time_bounds(enc)
        location = None
        for pr in _descendants(enc, "participantRole"):
            for pe in _children(pr, "playingEntity"):
                location = _text(_child(pe, "name"))
                break
            if location:
                break
        if not (desc or low):
            continue
        items.append({"description": desc, "date": low, "location": location})
    return items


_SECTION_PARSERS = {
    "problems": _parse_problems,
    "medications": _parse_medications,
    "allergies": _parse_allergies,
    "immunizations": _parse_immunizations,
    "vitals": _parse_observations,
    "labs": _parse_observations,
    "encounters": _parse_encounters,
}


# ── Pipeline adapter ─────────────────────────────────────────────────────────

def extract_ccd(text: str) -> dict | None:
    """Parse a CCD into the intake pipeline's `extracted` shape — the
    deterministic stand-in for classify_text(). None when the text isn't a
    parseable ClinicalDocument (the pipeline then falls back to the LLM path).

    doc_type is always treatment_record: a health summary is clinical
    treatment evidence. conditions_mentioned mirrors the problems section so
    the existing suggested-links matcher and UI flows work unchanged; percents
    and decisions are never present in a CCD, so they stay null.
    """
    parsed = parse_ccd(text)
    if parsed is None:
        return None
    counts = ", ".join(
        f"{len(parsed[k])} {label}"
        for k, label in (
            ("problems", "problems"),
            ("medications", "medications"),
            ("allergies", "allergies"),
            ("immunizations", "immunizations"),
            ("vitals", "vital signs"),
            ("labs", "lab results"),
            ("encounters", "encounters"),
        )
        if parsed[k]
    )
    title = parsed.get("title") or "Health Summary (C-CDA)"
    summary = (
        f"Structured clinical summary parsed directly from the document "
        f"({counts or 'no coded sections found'}). "
        "Parsed deterministically — no AI was involved."
    )
    return {
        "doc_type": "treatment_record",
        "doc_date": parsed.get("doc_date")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parsed.get("doc_date") or "")
        else None,
        "title": title[:255],
        "summary": summary[:2000],
        "conditions_mentioned": [
            {
                "name": p["name"][:255],
                "rating_percent": None,
                "diagnostic_code": None,
                "decision": None,
            }
            for p in parsed["problems"]
        ],
        "is_va_decision": False,
        "ccd": parsed,
    }
