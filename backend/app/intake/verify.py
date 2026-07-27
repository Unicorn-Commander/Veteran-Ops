"""Extract-verify — a decorrelated second pass that must QUOTE the record.

The classifier proposes structured facts; this pass makes the model earn each one
by returning a verbatim SPAN from the source that supports the tuple
``(condition, %, DC, decision)`` — plus a recall check for conditions that are in
the text but fell out of the extraction. Then a PURE validator disposes:

  * the span must be a real substring of the source AND contain the claimed value
    → otherwise the field is ``unsupported`` (a hallucinated quote, or a value the
    quote doesn't actually carry);
  * a span that carries a DIFFERENT value of the same class → ``disputed``
    (e.g. the extraction says 50% but the quote says 70%).

Nothing here overwrites the extraction. A disagreement is FLAGGED onto the
document's review queue and the veteran reconciles it — a disputed rating percent
is never silently persisted as fact. This mirrors classify.validate_extraction:
the model proposes, the deterministic validator disposes, the human decides.
"""

from __future__ import annotations

import json
import re

from . import crossread
from .classify import _clean_str, parse_llm_json
from .segment import map_segments

VERIFY_SYSTEM = (
    "You are a meticulous VERIFICATION agent for a veteran's VA claim records. You "
    "are given the SOURCE TEXT of a document and a list of facts a first pass "
    "EXTRACTED from it. For EACH extracted condition, find the single VERBATIM "
    "sentence or phrase in the source that supports it (the condition name and any "
    "percent / diagnostic code / decision), and return it EXACTLY as it appears — "
    "do not paraphrase, correct, or invent. If nothing in the source supports a "
    "condition, return an empty span for it. Then list any condition that IS "
    "discussed in the source but is MISSING from the extraction, each with its own "
    "verbatim span. Return STRICT JSON ONLY (no prose, no code fences):\n"
    "{\n"
    '  "conditions": [{"name": "<extracted condition name>", "span": "<verbatim quote or empty>"}],\n'
    '  "missing": [{"name": "<condition in the text but not extracted>", "span": "<verbatim quote>"}]\n'
    "}\n"
    "The span must be copied CHARACTER-FOR-CHARACTER from the source. Output valid JSON only."
)

# Verified field statuses. `confirmed` is the only clean one; the rest flag review.
CONFIRMED = "confirmed"
DISPUTED = "disputed"
UNSUPPORTED = "unsupported"
UNVERIFIED = "unverified"  # the pass returned no span — we can't confirm OR refute

_VALUE_FIELDS = (
    ("rating_percent", "percent"),
    ("diagnostic_code", "diagnostic_code"),
    ("decision", "decision"),
)


def _norm(text: str) -> str:
    """Whitespace-collapsed casefold — span grounding is insensitive to how the OCR
    or the model spaced/cased the quote, but not to its actual content."""
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _cond_key(name) -> str:
    return _norm(name or "")


def _span_tokens(span: str, field: str) -> set:
    """The critical tokens the grounded span actually carries, via the crossread
    extractors (the SAME pure cleaners the classifier disposes with)."""
    if field == "percent":
        return crossread._percents(span)
    if field == "diagnostic_code":
        return crossread._dcs(span)
    if field == "decision":
        return crossread._decisions(span)
    return set()


def _field_item(
    idx: int, condition: str, field: str, extracted_value, candidate_value, status: str, span: str | None
) -> dict:
    """One reconcilable review field: which value the veteran should pick, with the
    quote that motivated the flag. field_id is stable ("<condition-index>:<field>")
    so POST /reconcile can write the chosen value back onto the exact tuple."""
    return {
        "field_id": f"{idx}:{field}",
        "index": idx,
        "condition": condition,
        "field": field,
        "extracted_value": extracted_value,
        "candidate_value": candidate_value,
        "status": status,
        "span": (span.strip()[:600] if span else None),
        "source": "verify",
    }


def _verify_condition(source_norm: str, idx: int, cond: dict, span: str | None) -> dict:
    """Grade one extracted condition against its returned span (PURE)."""
    name = cond.get("name") or ""
    if not span or not span.strip():
        return {
            "condition": {"index": idx, "name": name, "status": UNVERIFIED, "span": None},
            "fields": [],
        }
    span_norm = _norm(span)
    if span_norm not in source_norm:
        # Hallucinated quote — the "support" isn't in the record at all.
        return {
            "condition": {"index": idx, "name": name, "status": UNSUPPORTED, "span": span.strip()[:600]},
            "fields": [_field_item(idx, name, "name", name, None, UNSUPPORTED, span)],
        }

    fields: list[dict] = []
    statuses: dict[str, str] = {}
    # The grounded span must at least mention the condition it claims to support.
    if name and _norm(name) not in span_norm:
        statuses["name"] = UNSUPPORTED
        fields.append(_field_item(idx, name, "name", name, None, UNSUPPORTED, span))
    for attr, klass in _VALUE_FIELDS:
        value = cond.get(attr)
        if value is None:
            continue
        present = _span_tokens(span, klass)
        cmp_value = value if klass != "decision" else str(value).lower()
        if cmp_value in present:
            statuses[attr] = CONFIRMED
        elif present:
            candidate = sorted(present, key=str)[0]
            statuses[attr] = DISPUTED
            fields.append(_field_item(idx, name, attr, value, candidate, DISPUTED, span))
        else:
            statuses[attr] = UNSUPPORTED
            fields.append(_field_item(idx, name, attr, value, None, UNSUPPORTED, span))

    if DISPUTED in statuses.values():
        status = DISPUTED
    elif UNSUPPORTED in statuses.values():
        status = UNSUPPORTED
    else:
        status = CONFIRMED
    return {
        "condition": {
            "index": idx,
            "name": name,
            "status": status,
            "span": span.strip()[:600],
            "field_statuses": statuses,
        },
        "fields": fields,
    }


def validate_verification(text: str, extracted: dict, raw) -> dict:
    """PURE: grade a verification pass against the source (mirrors
    classify.validate_extraction — deterministic, unit-tested, no LLM).

    Returns {status, fields, conditions, missing_conditions}: `fields` are the
    reconcilable per-tuple disagreements (disputed/unsupported), `conditions` the
    per-condition verdicts, `missing_conditions` the recall hits (a condition in
    the text that the extraction dropped, span-grounded so a hallucinated "missing"
    is discarded). status='flagged' when ANYTHING needs a human; else 'clear'.
    """
    source_norm = _norm(text)
    raw = raw if isinstance(raw, dict) else {}
    by_name: dict[str, dict] = {}
    for c in raw.get("conditions") or []:
        if isinstance(c, dict) and c.get("name") is not None:
            by_name.setdefault(_cond_key(c.get("name")), c)

    conditions_out: list[dict] = []
    fields_out: list[dict] = []
    extracted_names = set()
    for idx, cond in enumerate(extracted.get("conditions_mentioned", []) if isinstance(extracted, dict) else []):
        if not isinstance(cond, dict):
            continue
        extracted_names.add(_cond_key(cond.get("name")))
        v = by_name.get(_cond_key(cond.get("name")))
        span = v.get("span") if isinstance(v, dict) and isinstance(v.get("span"), str) else None
        graded = _verify_condition(source_norm, idx, cond, span)
        conditions_out.append(graded["condition"])
        fields_out.extend(graded["fields"])

    missing: list[dict] = []
    seen_missing: set[str] = set()
    for m in raw.get("missing") or []:
        if not isinstance(m, dict):
            continue
        mname = _clean_str(m.get("name"), 255)
        mspan = m.get("span") if isinstance(m.get("span"), str) else None
        if not mname or not mspan:
            continue
        key = _cond_key(mname)
        # Recall must be REAL: the span is grounded in the source and names the
        # condition, and it isn't already an extracted condition. Otherwise a
        # confabulated "you also missed X" is thrown away.
        if key in extracted_names or key in seen_missing:
            continue
        if _norm(mspan) in source_norm and _norm(mname) in _norm(mspan):
            seen_missing.add(key)
            missing.append({"name": mname, "span": mspan.strip()[:600]})

    flagged = bool(fields_out) or bool(missing)
    return {
        "status": "flagged" if flagged else "clear",
        "fields": fields_out,
        "conditions": conditions_out,
        "missing_conditions": missing,
    }


# Per-call source cap (matched to the classifier read window).
_VERIFY_MAX_CHARS = 24_000


def _compact(conditions: list) -> list[dict]:
    """The (name, %, DC, decision) tuples handed to the verifier — the only fields it
    needs to quote-check, stripped of everything else."""
    return [
        {
            "name": c.get("name"),
            "rating_percent": c.get("rating_percent"),
            "diagnostic_code": c.get("diagnostic_code"),
            "decision": c.get("decision"),
        }
        for c in conditions
        if isinstance(c, dict)
    ]


async def _verify_call(gateway, source: str, compact: list[dict], *, model: str) -> dict | None:
    """ONE model pass over a bounded window: quote each condition in `compact` and
    surface any condition discussed in `source` but missing from it. Returns the raw
    parsed JSON, or None (gateway down / unparseable). Never raises."""
    user = json.dumps(
        {"source_text": source[:_VERIFY_MAX_CHARS], "extracted_conditions": compact},
        ensure_ascii=False,
    )
    try:
        raw = await gateway.complete(
            [
                {"role": "system", "content": VERIFY_SYSTEM},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=0.0,
            max_tokens=2000,
            touches_pii=True,
        )
    except Exception:  # noqa: BLE001 — gateway down → nothing to flag (retryable)
        return None
    return parse_llm_json(raw)


def _best_span(candidates: list[str], source_norm: str) -> str:
    """Merge a condition's per-segment span candidates into the one to keep: a span
    that is a REAL substring of the source (a grounded quote) beats a non-grounded
    one, so a correct quote found in a LATER segment isn't lost behind an empty or
    hallucinated span from an earlier one; '' only when every candidate was empty.
    The authoritative grading still happens in validate_verification — this is just
    the whole-document merge."""
    grounded = [s for s in candidates if s.strip() and _norm(s) in source_norm]
    if grounded:
        return grounded[0].strip()
    nonempty = [s for s in candidates if s.strip()]
    return nonempty[0].strip() if nonempty else ""


async def verify_extraction(text: str, extracted: dict, *, model: str) -> dict | None:
    """Model seam, WHOLE-DOCUMENT. Ask the model (resolved by the caller via
    overrides.effective_model_for(tier="reasoning", touches_pii=True, ...)) to quote
    the record for each extracted condition.

    A large record (a C-file of thousands of pages) is split into the SAME overlapping
    segments the classifier reads, so a condition whose supporting sentence sits on
    page 300 can still be quoted — the old head-only 24K cap made that span invisible
    and every deep condition came back `unverified`. Each segment is asked to (a) quote
    the subset of extracted conditions whose name appears in it and (b) surface any
    condition discussed there but missing from the extraction; the per-condition spans
    are unioned (a grounded quote wins, `_best_span`) and the missing hits deduped.

    Returns the merged RAW {"conditions", "missing"} (disposed by validate_verification
    against the FULL text), or None when there's nothing to verify or no segment ever
    answered. Never raises — a verification miss just means the doc isn't flagged."""
    if not (text or "").strip():
        return None
    conditions = (extracted or {}).get("conditions_mentioned") or []
    if not conditions:
        return None
    from ..llm.gateway import gateway  # lazy — keep the pure validators importable

    compact = _compact(conditions)
    segments = map_segments(text)
    # Small document → the original single pass (behavior unchanged).
    if len(segments) <= 1:
        return await _verify_call(gateway, text, compact, model=model)

    source_norm = _norm(text)
    # Which conditions any segment actually names — the rest (e.g. an extraction that
    # normalized "post-traumatic stress disorder" to "PTSD") get one shot on the head
    # segment so they aren't silently unverifiable.
    seg_norms = [_norm(seg.text) for seg in segments]
    matched: set[str] = set()
    for c in compact:
        cn = _norm(c.get("name") or "")
        if cn and any(cn in sn for sn in seg_norms):
            matched.add(_cond_key(c.get("name")))
    orphans = [c for c in compact if _cond_key(c.get("name")) not in matched]

    spans: dict[str, list[str]] = {_cond_key(c.get("name")): [] for c in compact}
    name_by_key: dict[str, str] = {}
    for c in compact:
        name_by_key.setdefault(_cond_key(c.get("name")), c.get("name"))
    missing: list[dict] = []
    seen_missing: set[str] = set()
    answered = False

    for seg, seg_norm in zip(segments, seg_norms):
        subset = [c for c in compact if (_norm(c.get("name") or "") and _norm(c.get("name")) in seg_norm)]
        if seg.index == 0:  # give the orphans their one chance on the head
            subset = subset + [c for c in orphans if c not in subset]
        raw = await _verify_call(gateway, seg.text, subset, model=model)
        if raw is None:
            continue
        answered = True
        for c in raw.get("conditions") or []:
            if not isinstance(c, dict):
                continue
            k = _cond_key(c.get("name"))
            if k in spans and isinstance(c.get("span"), str):  # only our extracted conditions
                spans[k].append(c.get("span"))
        for m in raw.get("missing") or []:
            if not isinstance(m, dict):
                continue
            mname, mspan = m.get("name"), m.get("span")
            key = _cond_key(mname)
            if not mname or not isinstance(mspan, str) or key in seen_missing:
                continue
            seen_missing.add(key)
            missing.append({"name": mname, "span": mspan})

    if not answered:  # every segment's gateway call failed → retryable, nothing flagged
        return None
    merged = [{"name": name_by_key[k], "span": _best_span(v, source_norm)} for k, v in spans.items()]
    return {"conditions": merged, "missing": missing}
