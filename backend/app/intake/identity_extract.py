"""Best-effort extraction of the VETERAN'S OWN identity from a document, via the
LOCAL LLM — so the profile can be pre-filled from imported records instead of
typed by hand.

Same shape as intake/classify.py: the LLM proposes, PURE validators dispose. The
validator (`validate_identity`) is deterministic and unit-tested, and it whitelists
ONLY the identity fields we pre-fill VA forms with — full_name, date_of_birth,
phone, address{street,city,state,zip}, and dependents{relationship,name,dob}.

⚖️ LEGAL / PII LINE — the SSN never enters this pipeline:
  • the prompt forbids emitting an SSN / VA file number / any 9-digit id;
  • `validate_identity` whitelists field-by-field, so an "ssn" (or any off-list)
    key the model returns is STRUCTURALLY dropped — it can never reach the output
    (the same guarantee pdf/identity_fill.py gets by having no ssn field to map);
  • as defense-in-depth, any surviving string value that CONTAINS an SSN-shaped
    token is dropped, and phone accepts exactly 10 digits so a 9-digit SSN can
    never masquerade as one.
Everything here is a SUGGESTION the veteran reviews and confirms — nothing is
written to profile.identity by this module.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from .classify import parse_llm_json  # tolerant JSON extraction — shared, no dup

log = logging.getLogger("veteran_ops.intake")

# US state / territory codes — a proposed 2-letter state is dropped unless it's a
# real one (keeps a stray "OF" / "TO" out of the address).
_US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY "
    "DC PR VI GU AS".split()
)

_DEP_RELATIONSHIPS = ("spouse", "child", "stepchild", "parent")

# Canonical SSN / TIN shape: three, two, four digits (optionally dash/space/en-dash
# separated). A 10-digit phone is 3-3-4 and a ZIP+4 is 5-4, so neither matches — only
# a real SSN-shaped token trips this. Belt-and-suspenders on top of the whitelist.
_SSN_RE = re.compile(r"\b\d{3}[-–\s]?\d{2}[-–\s]?\d{4}\b")

# The document types that authoritatively carry the veteran's OWN identity. Lay
# statements and "other" don't, and running the model on every file in a 300-doc
# C-file dump would double intake's LLM spend for little gain — so we gate. A
# DD-214 classifies as `service_record`; the gold is the VA decision letter.
_IDENTITY_DOC_TYPES = frozenset(
    {
        "decision_letter",
        "rating_decision",
        "service_record",
        "str",
        "dbq",
        "treatment_record",
        "private_medical_opinion",
    }
)

# Authority ranking for aggregation: a VA decision / DD-214 outranks a treatment
# record when two documents disagree on a field. Unknown types fall to 0.
_AUTHORITY = {
    "decision_letter": 5,
    "rating_decision": 5,
    "service_record": 4,  # DD-214
    "str": 3,
    "dbq": 2,
    "private_medical_opinion": 2,
    "treatment_record": 2,
}

IDENTITY_SYSTEM = (
    "You extract the VETERAN'S OWN identifying and contact details from a document in "
    "their VA claim file, so their VA forms can be pre-filled. Read the text and return "
    "STRICT JSON ONLY (no prose, no code fences) matching exactly this shape:\n"
    "{\n"
    '  "full_name": "the veteran\'s full legal name, or null",\n'
    '  "date_of_birth": "YYYY-MM-DD or null — VETERAN only",\n'
    '  "phone": "the veteran\'s phone number, or null",\n'
    '  "address": {"street": "street line or null", "city": "or null", '
    '"state": "2-letter code or null", "zip": "5 or 9 digit ZIP or null"},\n'
    '  "dependents": [{"relationship": "spouse|child|stepchild|parent", '
    '"full_name": "or null", "date_of_birth": "YYYY-MM-DD or null"}]\n'
    "}\n"
    "CRITICAL RULES:\n"
    "- NEVER output a Social Security Number, VA file number, or any 9-digit identifier. "
    "If you see one, ignore it entirely — do not place it in any field.\n"
    "- Report a value only when it is CLEARLY the veteran's OWN — not a doctor, examiner, "
    "witness, spouse, child, or VA office. When unsure, use null.\n"
    "- date_of_birth is the VETERAN's date of birth ONLY. Spouse / child / dependent birth "
    "dates go ONLY under dependents[]. Never put a spouse's or child's DOB in date_of_birth. "
    "If the document lists multiple dates of birth and you cannot tell which is the veteran's, "
    "set date_of_birth to null.\n"
    "- The mailing address and phone are the VETERAN'S home contact. If the document is on "
    "VA or clinic letterhead, do NOT report the VA/clinic address as the veteran's.\n"
    "- List a dependent only when the document plainly names them as the veteran's spouse "
    "or child. Put their DOB under that dependent, not on the veteran.\n"
    "- Do not invent data. Null anything not plainly present. Output valid JSON only."
)


def _contains_ssn(value: str) -> bool:
    return bool(_SSN_RE.search(value or ""))


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def _clean_text(value, max_len: int) -> str | None:
    """Trimmed, length-capped string — DROPPED (None) if empty or SSN-shaped."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or _contains_ssn(value):
        return None
    return value[:max_len]


def _clean_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


def _clean_phone(value) -> str | None:
    """A US phone is EXACTLY 10 digits — so a 9-digit SSN can never become one.
    Normalized to '(NNN) NNN-NNNN'."""
    if not isinstance(value, str):
        return None
    d = _digits(value)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return None
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"


def _clean_state(value) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if code in _US_STATES else None


def _clean_zip(value) -> str | None:
    if not isinstance(value, str):
        return None
    d = _digits(value)
    if len(d) == 5:
        return d
    if len(d) == 9:
        return f"{d[:5]}-{d[5:]}"
    return None


def _clean_address(value) -> dict:
    """{street, city, state, zip} — only the non-empty, valid parts. No 'unit'
    (the model rarely splits it reliably) and never a country (assumed USA)."""
    if not isinstance(value, dict):
        return {}
    out: dict = {}
    street = _clean_text(value.get("street"), 255)
    if street:
        out["street"] = street
    city = _clean_text(value.get("city"), 120)
    if city:
        out["city"] = city
    state = _clean_state(value.get("state"))
    if state:
        out["state"] = state
    zip_code = _clean_zip(value.get("zip"))
    if zip_code:
        out["zip"] = zip_code
    return out


def _clean_dependents(value) -> list[dict]:
    """[{relationship, full_name?, date_of_birth?}] — a dependent is kept only with
    a valid relationship AND at least a name or DOB. Names are SSN-scrubbed like any
    other string; no dependent SSN is ever collected."""
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value[:12]:  # bounded — the form (21-686c) covers a real household
        if not isinstance(item, dict):
            continue
        rel = item.get("relationship")
        if rel not in _DEP_RELATIONSHIPS:
            continue
        name = _clean_text(item.get("full_name"), 200)
        dob = _clean_date(item.get("date_of_birth"))
        if not name and not dob:
            continue
        dep: dict = {"relationship": rel}
        if name:
            dep["full_name"] = name
        if dob:
            dep["date_of_birth"] = dob
        out.append(dep)
    return out


def _dependent_dobs(dependents: list[dict]) -> set[str]:
    return {
        str(d.get("date_of_birth"))
        for d in dependents
        if isinstance(d, dict) and d.get("date_of_birth")
    }


def _strip_dob_if_dependent(
    identity_dob: str | None, dependents: list[dict]
) -> str | None:
    """Never promote a spouse/child DOB onto the veteran's identity.

    Models often list both people on a dependency form and put the spouse's birth
    date in date_of_birth. If that same ISO date appears on any dependent, drop it
    from the veteran field (keep it only under dependents).
    """
    if not identity_dob:
        return None
    if identity_dob in _dependent_dobs(dependents):
        return None
    return identity_dob


def validate_identity(raw) -> dict:
    """PURE: whitelist a best-effort identity suggestion from arbitrary LLM output.

    Returns ONLY the fields that are clearly present (empty dict when nothing is) —
    so a caller can treat a non-empty result as "there is something to propose".

    The whitelist is the SSN guarantee: only full_name, date_of_birth, phone,
    address, and dependents are ever read. An "ssn"/"va_file_number"/any other key
    the model emits is structurally discarded — it cannot appear in the output.

    Veteran date_of_birth is dropped when it matches a dependent DOB in the same
    payload (spouse/child confusion).
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    full_name = _clean_text(raw.get("full_name"), 200)
    if full_name:
        out["full_name"] = full_name
    dependents = _clean_dependents(raw.get("dependents"))
    if dependents:
        out["dependents"] = dependents
    dob = _strip_dob_if_dependent(_clean_date(raw.get("date_of_birth")), dependents)
    if dob:
        out["date_of_birth"] = dob
    phone = _clean_phone(raw.get("phone"))
    if phone:
        out["phone"] = phone
    address = _clean_address(raw.get("address"))
    if address:
        out["address"] = address
    return out


def should_extract_identity(doc_type: str | None) -> bool:
    """True only for the document types that authoritatively carry the veteran's own
    identity — the gate that keeps a big dump from doubling intake's LLM spend."""
    return doc_type in _IDENTITY_DOC_TYPES


def authority_rank(doc_type: str | None) -> int:
    """How much a document type's identity claim is trusted when documents disagree."""
    return _AUTHORITY.get(doc_type or "", 0)


def _sort_key(entry: dict) -> tuple:
    """Best-first: highest authority, then most-recent doc_date, then most-recent
    created_at. Missing dates sort last (empty string < any ISO date)."""
    return (
        authority_rank(entry.get("doc_type")),
        entry.get("doc_date") or "",
        entry.get("created_at") or "",
    )


def _source_of(entry: dict) -> dict:
    return {
        "document_id": entry.get("document_id"),
        "title": entry.get("title"),
        "doc_type": entry.get("doc_type"),
        "doc_date": entry.get("doc_date"),
    }


def merge_identity_suggestions(entries: list[dict]) -> dict:
    """PURE: fold per-document identity suggestions into ONE proposed identity +
    dependents, most-authoritative-then-most-recent winning per field, noting which
    document supplied each field.

    entries: [{document_id, title, doc_type, doc_date, created_at, suggestion}] where
    `suggestion` is a validate_identity() dict. Address and the dependents list are
    each taken as a COHERENT UNIT from the best document that has them (never a
    street from one letter stitched onto a ZIP from another).

    Returns {identity, dependents, sources, has_suggestions}. `identity` is shaped
    for schemas.VeteranIdentity (address nested); `sources` maps a field name
    (full_name | date_of_birth | phone | address | dependents) to its source doc.
    """
    ranked = sorted(
        (e for e in entries if isinstance(e.get("suggestion"), dict) and e["suggestion"]),
        key=_sort_key,
        reverse=True,
    )
    identity: dict = {}
    dependents: list = []
    sources: dict = {}

    for field in ("full_name", "date_of_birth", "phone"):
        for entry in ranked:
            value = entry["suggestion"].get(field)
            if value:
                identity[field] = value
                sources[field] = _source_of(entry)
                break

    for entry in ranked:
        address = entry["suggestion"].get("address")
        if address:
            identity["address"] = dict(address)
            sources["address"] = _source_of(entry)
            break

    for entry in ranked:
        deps = entry["suggestion"].get("dependents")
        if deps:
            dependents = [dict(d) for d in deps]
            sources["dependents"] = _source_of(entry)
            break

    # Cross-document safety: if the winning veteran DOB is also listed as any
    # dependent's DOB (from the chosen dependents list or any document), drop it.
    dep_dobs = _dependent_dobs(dependents)
    for entry in ranked:
        for d in entry["suggestion"].get("dependents") or []:
            if isinstance(d, dict) and d.get("date_of_birth"):
                dep_dobs.add(str(d["date_of_birth"]))
    if identity.get("date_of_birth") and identity["date_of_birth"] in dep_dobs:
        identity.pop("date_of_birth", None)
        sources.pop("date_of_birth", None)

    return {
        "identity": identity,
        "dependents": dependents,
        "sources": sources,
        "has_suggestions": bool(identity or dependents),
    }


async def _gateway_complete(messages: list[dict]) -> str:
    """The one gateway touch, isolated as a seam: the DEFAULT LOCAL model via the
    allowlisted gateway (no `model` arg → settings.llm_model, so PII stays on the
    fleet). Import is LAZY and INSIDE the seam so the pure validators stay importable
    without the OpenAI SDK, and so a missing/broken gateway surfaces as an exception
    the caller degrades on (rather than an import error at call time). Tests
    monkeypatch this symbol, exactly like intake.process does with classify_text."""
    from ..llm.gateway import gateway  # lazy — keeps pure validators importable sans SDK

    return await gateway.complete(messages, temperature=0.0, max_tokens=700)


async def extract_identity(text: str, doc_type: str | None) -> dict:
    """Best-effort identity extraction over a document's text via the DEFAULT LOCAL
    model (PII stays on the fleet). Returns a VALIDATED suggestion dict, or {} when
    the type isn't authoritative, the text is empty, or the gateway is down / missing
    / returns garbage.

    NEVER raises — identity extraction is a bonus on top of intake and must never
    break processing a document.
    """
    if not (text or "").strip() or not should_extract_identity(doc_type):
        return {}
    try:
        raw = await _gateway_complete(
            [
                {"role": "system", "content": IDENTITY_SYSTEM},
                # Identity lives at the top of a record — the head is plenty, and
                # short input keeps this second pass cheap.
                {"role": "user", "content": text[:8000]},
            ]
        )
    except Exception:  # noqa: BLE001 — degrade silently; intake continues
        log.debug("identity extraction gateway error; skipping", exc_info=True)
        return {}
    parsed = parse_llm_json(raw)
    if parsed is None:
        return {}
    return validate_identity(parsed)
