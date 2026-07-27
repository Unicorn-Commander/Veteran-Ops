"""Build a claim CASE from a veteran's uploaded records.

The bridge between "132 documents were read" and "here's your situation": the
intake classifier already extracted `conditions_mentioned` from every document.
This aggregates those mentions across all ready documents, then groups the
synonym mess (a dozen ways of writing "chronic fatigue syndrome" / "mono") into
a handful of clean CANDIDATE conditions the veteran can confirm with one click —
which then feed the Game Plan.

LEGAL LANE: this ORGANIZES the conditions the veteran's own records already
name. It never invents a condition that isn't in their documents, never
diagnoses, and produces SUGGESTIONS the veteran confirms — nothing is claimed or
filed. The LLM only groups/cleans names; a pure deterministic grouping is the
fallback when the gateway is down, so the feature always works.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("veteran_ops.case")

# Cap the candidate LLM budget / UI list — the highest-signal conditions first.
MAX_CANDIDATES = 24
_CLAIM_TYPES = ("direct", "secondary", "presumptive")

# Deterministic alias table: chart/OCR spellings → a stable grouping key.
# Applied *before* exact-name de-dupe so "CFS", "ME/CFS", and "chronic fatigue"
# collapse even when the LLM canonicalize step is offline. Display names for the
# group come from ALIAS_CANONICAL when the raw form is a known short alias;
# otherwise the first-seen surface form is kept.
#
# Keys and values are lowercased normalized strings. Keep this list conservative:
# only merge when a VSO would treat the strings as the same claimed condition.
_ALIAS_TO_KEY: dict[str, str] = {
    # ME/CFS / systemic exertion intolerance
    "cfs": "chronic fatigue syndrome me/cfs",
    "me/cfs": "chronic fatigue syndrome me/cfs",
    "me cfs": "chronic fatigue syndrome me/cfs",
    "chronic fatigue": "chronic fatigue syndrome me/cfs",
    "chronic fatigue syndrome": "chronic fatigue syndrome me/cfs",
    "myalgic encephalomyelitis": "chronic fatigue syndrome me/cfs",
    "systemic exertion intolerance disease": "chronic fatigue syndrome me/cfs",
    "seid": "chronic fatigue syndrome me/cfs",
    # PTSD
    "ptsd": "ptsd",
    "post traumatic stress disorder": "ptsd",
    "post-traumatic stress disorder": "ptsd",
    "posttraumatic stress disorder": "ptsd",
    # Tinnitus / hearing
    "tinnitus": "tinnitus",
    "ringing in ears": "tinnitus",
    "ringing in the ears": "tinnitus",
    "bilateral tinnitus": "tinnitus",
    "hearing loss": "hearing loss",
    "bilateral hearing loss": "hearing loss",
    "sensorineural hearing loss": "hearing loss",
    # Mood / anxiety (kept distinct from PTSD)
    "mdd": "major depressive disorder",
    "major depression": "major depressive disorder",
    "major depressive disorder": "major depressive disorder",
    "depression": "depression",
    "depressive disorder": "depression",
    "gad": "generalized anxiety disorder",
    "generalized anxiety": "generalized anxiety disorder",
    "generalized anxiety disorder": "generalized anxiety disorder",
    "anxiety": "anxiety",
    "anxiety disorder": "anxiety",
    # Common MSK
    "lumbago": "lumbar strain",
    "low back pain": "lumbar strain",
    "lower back pain": "lumbar strain",
    "lumbar strain": "lumbar strain",
    "degenerative disc disease": "degenerative disc disease",
    "ddd": "degenerative disc disease",
    "djd": "degenerative joint disease",
    "degenerative joint disease": "degenerative joint disease",
    "osteoarthritis": "osteoarthritis",
    "oa": "osteoarthritis",
    # Migraine
    "migraines": "migraine",
    "migraine headaches": "migraine",
    "migraine": "migraine",
    # Sleep
    "osa": "obstructive sleep apnea",
    "obstructive sleep apnea": "obstructive sleep apnea",
    "sleep apnea": "sleep apnea",
    # IBS / gut
    "ibs": "irritable bowel syndrome",
    "irritable bowel syndrome": "irritable bowel syndrome",
    # Hypertension
    "htn": "hypertension",
    "high blood pressure": "hypertension",
    "hypertension": "hypertension",
    # Diabetes
    "dm2": "type 2 diabetes mellitus",
    "diabetes mellitus type 2": "type 2 diabetes mellitus",
    "type 2 diabetes": "type 2 diabetes mellitus",
    "type ii diabetes": "type 2 diabetes mellitus",
    "diabetes mellitus": "diabetes mellitus",
    # TBI
    "tbi": "traumatic brain injury",
    "traumatic brain injury": "traumatic brain injury",
    "concussion": "traumatic brain injury",
    # Erectile dysfunction (common secondary)
    "ed": "erectile dysfunction",
    "erectile dysfunction": "erectile dysfunction",
    # Mono / EBV (often co-mentioned with CFS)
    "mono": "infectious mononucleosis",
    "mononucleosis": "infectious mononucleosis",
    "infectious mononucleosis": "infectious mononucleosis",
    "ebv": "epstein-barr virus",
    "epstein barr": "epstein-barr virus",
    "epstein-barr": "epstein-barr virus",
    "epstein-barr virus": "epstein-barr virus",
}

# Prefer these display labels when the grouping key is a known alias group.
_ALIAS_DISPLAY: dict[str, str] = {
    "chronic fatigue syndrome me/cfs": "Chronic Fatigue Syndrome (ME/CFS)",
    "ptsd": "PTSD",
    "tinnitus": "Tinnitus",
    "hearing loss": "Hearing loss",
    "major depressive disorder": "Major depressive disorder",
    "depression": "Depression",
    "generalized anxiety disorder": "Generalized anxiety disorder",
    "anxiety": "Anxiety",
    "lumbar strain": "Lumbar strain",
    "degenerative disc disease": "Degenerative disc disease",
    "degenerative joint disease": "Degenerative joint disease",
    "osteoarthritis": "Osteoarthritis",
    "migraine": "Migraine",
    "obstructive sleep apnea": "Obstructive sleep apnea",
    "sleep apnea": "Sleep apnea",
    "irritable bowel syndrome": "Irritable bowel syndrome",
    "hypertension": "Hypertension",
    "type 2 diabetes mellitus": "Type 2 diabetes mellitus",
    "diabetes mellitus": "Diabetes mellitus",
    "traumatic brain injury": "Traumatic brain injury",
    "erectile dysfunction": "Erectile dysfunction",
    "infectious mononucleosis": "Infectious mononucleosis",
    "epstein-barr virus": "Epstein-Barr virus",
}


def _norm(name: str) -> str:
    """Normalized key for de-duping raw mention strings."""
    return " ".join((name or "").lower().split()).strip(" .,:;")


def alias_key(name: str) -> str:
    """Map a raw condition name to its deterministic grouping key.

    Unknown names pass through `_norm` unchanged so nothing is over-merged.
    """
    key = _norm(name)
    if not key:
        return ""
    return _ALIAS_TO_KEY.get(key, key)


def aggregate_mentions(documents) -> list[dict]:
    """Collapse `conditions_mentioned` across ready documents into one row per
    distinct condition (alias-aware): {name, count, document_ids, diagnostic_code,
    aliases}. `documents` are ORM rows with `.extracted` (JSONB) and `.id`."""
    by_key: dict[str, dict] = {}
    for doc in documents:
        extracted = doc.extracted if isinstance(doc.extracted, dict) else {}
        for item in extracted.get("conditions_mentioned") or []:
            if not isinstance(item, dict):
                continue
            raw = (item.get("name") or "").strip()
            key = alias_key(raw)
            if not key:
                continue
            row = by_key.setdefault(
                key,
                {
                    "name": _ALIAS_DISPLAY.get(key) or raw,
                    "count": 0,
                    "document_ids": set(),
                    "diagnostic_code": None,
                    "raw_aliases": set(),
                },
            )
            row["count"] += 1
            row["document_ids"].add(str(doc.id))
            row["raw_aliases"].add(raw)
            # Prefer a longer, more specific surface form over a short alias
            # when we don't have a curated display name.
            if key not in _ALIAS_DISPLAY and len(raw) > len(str(row["name"] or "")):
                row["name"] = raw
            if not row["diagnostic_code"] and item.get("diagnostic_code"):
                row["diagnostic_code"] = item.get("diagnostic_code")
    rows = []
    for row in by_key.values():
        rows.append(
            {
                "name": row["name"],
                "count": row["count"],
                "document_ids": row["document_ids"],
                "diagnostic_code": row["diagnostic_code"],
                # Surface the OCR spellings that collapsed into this row so the
                # LLM canonicalize step (and the UI) can show provenance.
                "aliases": sorted(row["raw_aliases"]),
            }
        )
    rows.sort(key=lambda r: r["count"], reverse=True)
    return rows


CANONICALIZE_SYSTEM = (
    "You help a veteran organize their OWN uploaded medical/service records for a "
    "VA disability self-help tool. Below is a list of condition NAMES that were "
    "extracted from their documents, each with how many documents mention it. "
    "Group variants/synonyms of the SAME condition together into clean candidate "
    "conditions.\n"
    "STRICT RULES:\n"
    "- Use ONLY names from the provided list. NEVER introduce a condition that is "
    "not in the list. Every alias you output MUST appear verbatim in the input.\n"
    "- Merge obvious synonyms (e.g. 'CFS', 'ME/CFS', 'chronic fatigue' → one "
    "candidate 'Chronic Fatigue Syndrome (ME/CFS)').\n"
    "- Keep DISTINCT conditions separate (left knee vs right knee; anxiety vs "
    "depression).\n"
    "- Do NOT diagnose, rate, or predict outcomes. A one-sentence plain-language "
    "note of what the condition is is fine; no medical opinion.\n"
    "Return STRICT JSON ONLY (no prose, no code fences):\n"
    '{"candidates":[{\n'
    '  "name":"clean claim-appropriate condition name",\n'
    '  "aliases":["exact input strings merged into this candidate"],\n'
    '  "diagnostic_code":"4-digit VA code or null (only if standard/obvious)",\n'
    '  "body_system":"short body-system label or null",\n'
    '  "claim_type":"direct|secondary|presumptive",\n'
    '  "note":"one plain sentence; no diagnosis/opinion"\n'
    "}]}\n"
    "claim_type is only a GENERAL organizational hint (e.g. a condition your "
    "records tie to another is 'secondary'); the veteran decides. Output valid JSON only."
)


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            try:
                out = json.loads(raw[s : e + 1])
                return out if isinstance(out, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _dc_ok(v) -> str | None:
    if isinstance(v, str) and re.fullmatch(r"[0-9]{4}", v.strip()):
        return v.strip()
    return None


def _finalize(candidates: list[dict], agg: list[dict]) -> list[dict]:
    """Map grouped candidates back to real mention counts + source document ids,
    using the aggregated raw rows. Drops candidates whose aliases don't match any
    real mention (defends against an LLM inventing names)."""
    # Index by display name AND every raw OCR alias so LLM output can match
    # either the curated label or the chart spelling.
    by_key: dict[str, dict] = {}
    for r in agg:
        by_key[_norm(r["name"])] = r
        by_key[alias_key(r["name"])] = r
        for a in r.get("aliases") or []:
            by_key[_norm(a)] = r
            by_key[alias_key(a)] = r
    out: list[dict] = []
    used: set[str] = set()
    for cand in candidates:
        name = (cand.get("name") or "").strip()
        aliases = cand.get("aliases") or []
        matched_rows: list[dict] = []
        seen_ids: set[int] = set()
        for a in aliases:
            row = by_key.get(_norm(a)) or by_key.get(alias_key(a))
            if row is None:
                continue
            rid = id(row)
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            matched_rows.append(row)
        if not name or not matched_rows:
            continue
        doc_ids: set[str] = set()
        count = 0
        dc = _dc_ok(cand.get("diagnostic_code"))
        surface_aliases: list[str] = []
        for m in matched_rows:
            used.add(_norm(m["name"]))
            used.add(alias_key(m["name"]))
            for a in m.get("aliases") or []:
                used.add(_norm(a))
                used.add(alias_key(a))
            doc_ids |= m["document_ids"]
            count += m["count"]
            surface_aliases.extend(m.get("aliases") or [m["name"]])
            if not dc:
                dc = _dc_ok(m.get("diagnostic_code"))
        # De-dupe surface aliases while preserving order.
        seen_a: set[str] = set()
        clean_aliases: list[str] = []
        for a in surface_aliases:
            k = _norm(a)
            if k in seen_a:
                continue
            seen_a.add(k)
            clean_aliases.append(a)
        ct = cand.get("claim_type")
        out.append({
            "name": name[:255],
            "aliases": clean_aliases or [name],
            "mention_count": count,
            "document_ids": sorted(doc_ids),
            "diagnostic_code": dc,
            "body_system": (cand.get("body_system") or None) and str(cand["body_system"])[:64],
            "claim_type": ct if ct in _CLAIM_TYPES else "direct",
            "note": (cand.get("note") or "")[:400] or None,
        })
    # Any aggregated row the model didn't place becomes its own candidate, so
    # nothing a veteran's records name is silently dropped.
    for r in agg:
        if _norm(r["name"]) in used or alias_key(r["name"]) in used:
            continue
        if any(_norm(a) in used or alias_key(a) in used for a in (r.get("aliases") or [])):
            continue
        out.append(_bare_candidate(r))
    out.sort(key=lambda c: c["mention_count"], reverse=True)
    return out[:MAX_CANDIDATES]


def _bare_candidate(r: dict) -> dict:
    # Prefer curated display name; otherwise title-case all-lowercase OCR blobs.
    display = r["name"][:255]
    if display.islower():
        display = display.title()
    aliases = list(r.get("aliases") or [r["name"]])
    # Ensure the display name itself is in the alias list for finalize matching.
    if r["name"] not in aliases:
        aliases = [r["name"], *aliases]
    return {
        "name": display,
        "aliases": aliases,
        "mention_count": r["count"],
        "document_ids": sorted(r["document_ids"]),
        "diagnostic_code": _dc_ok(r.get("diagnostic_code")),
        "body_system": None,
        "claim_type": "direct",
        "note": None,
    }


def deterministic_candidates(agg: list[dict]) -> list[dict]:
    """No-LLM fallback: each alias-grouped mention becomes a candidate.

    Because aggregate_mentions already collapses known synonyms, this path is
    much stronger than one-row-per-raw-string — and always available offline.
    """
    return [_bare_candidate(r) for r in agg][:MAX_CANDIDATES]


async def canonicalize_candidates(agg: list[dict]) -> list[dict]:
    """Group the aggregated raw mentions into clean candidates via the LOCAL LLM,
    falling back to the deterministic grouping on any gateway failure."""
    if not agg:
        return []
    listing = "\n".join(f"- {r['name']} (mentioned in {r['count']} document(s))" for r in agg)
    try:
        from ..llm.gateway import gateway

        raw = await gateway.complete(
            [
                {"role": "system", "content": CANONICALIZE_SYSTEM},
                {"role": "user", "content": listing[:8000]},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
        parsed = _parse_json(raw)
        cands = (parsed or {}).get("candidates")
        if isinstance(cands, list) and cands:
            return _finalize([c for c in cands if isinstance(c, dict)], agg)
    except Exception:  # noqa: BLE001 — degrade to deterministic grouping
        log.warning("case canonicalization LLM failed; using deterministic grouping", exc_info=True)
    return deterministic_candidates(agg)
