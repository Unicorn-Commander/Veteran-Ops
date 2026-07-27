"""One grounded expert pass for one deterministically-enumerated rating.

The graduation rule is enforced here, before any model call:

* the enumerator supplied a non-empty ``seed_signal``; and
* retrieval returned a rating-criteria card whose diagnostic code exactly
  matches the candidate.

The card's structured tiers are the only percentages the model may repeat.  An
unsafe or ungrounded rewrite is discarded wholesale, leaving the deterministic
Finding intact.  Retrieval and the local-model pass are all best-effort so one
candidate cannot sink a larger, bounded orchestration batch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from ..analysis.mapping import extract_tiers, validate_selection
from ..kb.store import card_by_diagnostic_code, retrieve_cards
from ..llm.gateway import gateway
from ..rag import retrieve_document_chunks
from ..strategy.briefing import _LANE_BLOCK
from .base import Finding, _extract_body
from .candidates import CandidateRating

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .context import VeteranDossier

log = logging.getLogger("veteran_ops.firm")

_SYSTEM = (
    "You are one per-rating research expert inside Rating Raider, educational "
    "self-help software for veterans organizing their own records. You receive "
    "ONE candidate that a deterministic rule already selected, ONE matching VA "
    "rating-criteria card, related public adjudication cards, and excerpts from "
    "the veteran's own uploaded records. Your only job is to make the supplied "
    "deterministic explanation clearer.\n\n"
    "HARD RULES:\n"
    "1. Do not originate a condition, diagnostic code, rating tier, fact, or "
    "claim theory. Use only the supplied material.\n"
    "2. Mention only the diagnostic code and percentages explicitly listed in "
    "the matching criteria card. Never calculate or predict a rating.\n"
    "3. Do not diagnose, give a nexus opinion, assert service connection, or say "
    "what VA will decide. Never say the veteran qualifies, is entitled, will "
    "receive, or should receive anything.\n"
    "4. Organize the answer under these plain labels: 'What this is:', 'What your "
    "record shows:', and 'What's still needed:'. Describe excerpts as records to "
    "review, not as proof or a medical conclusion.\n"
    "5. Keep it to 3-6 short sentences at an eighth-grade reading level.\n\n"
    'Return strict JSON only: {"body": "<the explanation>"}'
)

_PROCESS_QUERY = {
    "direct": "direct service connection 38 CFR 3.303 initial claim evidence",
    "increase": "increased rating current severity 38 CFR 3.400 claim evidence",
    "secondary": "secondary service connection causation aggravation 38 CFR 3.310",
    "presumptive": "presumptive service connection 38 CFR 3.307 3.309 exposure",
    "concurrent": "concurrent military retired pay CRDP CRSC",
}

_PCT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent\b)", re.IGNORECASE)
# A bare 4-digit token counts as a diagnostic code ONLY in the VA schedule range
# (5000-9999); this stops years the veteran mentions ("your 2016 exam") from being
# mistaken for an introduced DC and reverting an otherwise-grounded rewrite.
_DC_RE = re.compile(r"\bDC\s*(\d{4})\b|\b([5-9]\d{3})\b", re.IGNORECASE)
_CEILING_SIGNAL = re.compile(
    r"\b(?:ceiling|maximum|max(?:imum)? tier|highest (?:authored )?tier|top tier)\b",
    re.IGNORECASE,
)
_EXTREMITY_SYSTEMS = {
    "musculoskeletal",
    "neurological",
    "peripheral nerves",
    "muscle injuries",
}
_SESSION_LOCK_KEY = "veteran_ops.deep_dive_retrieval_lock"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


@asynccontextmanager
async def _locked_retrieval(db: Any):
    """Serialize DB work when parallel experts share one AsyncSession.

    SQLAlchemy AsyncSession is stateful and does not permit concurrent execute
    calls.  The orchestrator can still fan candidates out: their bounded local
    model calls overlap, while only the short retrieval phase is serialized on
    the session's own ``info`` dictionary.  Lightweight test doubles without an
    ``info`` mapping simply use the no-op path.
    """
    try:
        info = db.info
    except (AttributeError, TypeError):
        info = None
    if not isinstance(info, dict):
        yield
        return

    loop = asyncio.get_running_loop()
    state = info.get(_SESSION_LOCK_KEY)
    if not isinstance(state, tuple) or len(state) != 2 or state[0] is not loop:
        state = (loop, asyncio.Lock())
        info[_SESSION_LOCK_KEY] = state
    async with state[1]:
        yield


def _card_dict(card: Any) -> dict:
    """The minimal mapping shape consumed by mapping.validate_selection."""
    return {
        "title": _text(getattr(card, "title", "")),
        "diagnostic_code": _text(getattr(card, "diagnostic_code", "")),
        "source": _text(getattr(card, "source", "")),
        "data": getattr(card, "data", None) or {},
    }


def _citation(card: Any) -> dict:
    return {
        "id": _text(getattr(card, "id", "")) or None,
        "title": _text(getattr(card, "title", "")),
        "source": _text(getattr(card, "source", "")),
        "card_type": _text(getattr(card, "card_type", "")),
        "diagnostic_code": _text(getattr(card, "diagnostic_code", "")) or None,
    }


def _condition_for(dossier: "VeteranDossier", cand: CandidateRating) -> dict | None:
    """Resolve a candidate's source condition without guessing across duplicates."""
    conditions = [c for c in dossier.conditions if isinstance(c, dict)]
    ref = _text(cand.source_ref)
    if ref:
        # Enumerators may use either the UUID itself or a readable ``condition:``
        # prefix.  Compare both forms, but never fuzzy-match IDs.
        bare_ref = ref.split(":", 1)[1] if ref.lower().startswith("condition:") else ref
        for condition in conditions:
            if _text(condition.get("id")) in {ref, bare_ref}:
                return condition

    dc = _text(cand.diagnostic_code)
    matches = [c for c in conditions if _text(c.get("diagnostic_code")) == dc]
    return matches[0] if len(matches) == 1 else None


def _valid_percent(value: Any, allowed: set[int]) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        percent = int(value)
    except (TypeError, ValueError):
        return None
    return percent if percent in allowed else None


def _rating_percent(
    cand: CandidateRating,
    condition: dict | None,
    allowed: set[int],
) -> tuple[int | None, str | None]:
    """Select projection input only from deterministic, card-authored values.

    A target/current value from a sibling code must not leak across diagnostic
    codes.  The card ceiling is metadata by default; it becomes a projection
    input only when the deterministic seed explicitly says it is a ceiling
    scenario.
    """
    exact_condition = bool(
        condition
        and _text(condition.get("diagnostic_code")) == _text(cand.diagnostic_code)
    )
    if exact_condition:
        target = _valid_percent(condition.get("target_rating"), allowed)
        if target is not None:
            return target, "veteran-entered target rating"
        if cand.origin in {"direct", "increase"}:
            current = _valid_percent(condition.get("current_rating"), allowed)
            if current is not None:
                return current, "current rating recorded in the dossier"
    if allowed and _CEILING_SIGNAL.search(cand.seed_signal or ""):
        return max(allowed), "authored card ceiling named by the deterministic seed"
    return None, None


def _side_and_group(
    cand: CandidateRating,
    condition: dict | None,
    body_system: str | None,
) -> tuple[str | None, str | None]:
    """Carry laterality only where §4.26 could apply; otherwise leave it unset."""
    ref = _text(cand.source_ref)
    group = (ref if ref.lower().startswith("condition:") else f"condition:{ref}") if ref else None
    if not condition or _text(body_system).lower() not in _EXTREMITY_SYSTEMS:
        return None, group
    name = _text(condition.get("name")).lower()
    left = bool(re.search(r"\bleft\b", name))
    right = bool(re.search(r"\bright\b", name))
    if left == right:  # neither or both: laterality is not deterministic
        return None, group
    return ("left" if left else "right"), group


def _needs(cand: CandidateRating, condition: dict | None) -> list[str]:
    if condition:
        missing = [
            _text(item)
            for item in (condition.get("missing") or [])
            if _text(item)
        ]
        safe_missing = [item[:240] for item in missing if not _LANE_BLOCK.search(item)]
        if safe_missing:
            return safe_missing[:6]
    defaults = {
        "direct": "records addressing the current condition, in-service event, and medical link",
        "increase": "records describing current severity against the cited rating criteria",
        "secondary": "a medical opinion addressing causation or aggravation under 38 CFR §3.310",
        "presumptive": "service or exposure records and current-condition records for the cited rule",
    }
    need = defaults.get(cand.origin)
    return [need] if need else []


def _safe_seed_signal(seed_signal: str) -> str:
    signal = _text(seed_signal)
    if _LANE_BLOCK.search(signal):
        return "A deterministic dossier rule flagged this rating for review."
    # Bound user-derived or rule-derived prose before it reaches either cache or
    # prompt.  The complete anchor remains in Finding.seed for auditability.
    return signal[:500]


def _safe_title(value: Any, dc: str) -> str:
    title = _text(value)
    if not title or _LANE_BLOCK.search(title):
        return f"Rating criteria for DC {dc}"
    return title[:512]


def _deterministic_body(
    *,
    cand: CandidateRating,
    card: Any,
    tiers: list[dict],
    condition: dict | None,
    chunks: list[Any],
    needs: list[str],
) -> str:
    dc = _text(cand.diagnostic_code)
    title = _safe_title(getattr(card, "title", "") or cand.title, dc)
    percents = [int(t["percent"]) for t in tiers]
    if percents:
        tier_text = ", ".join(f"{p}%" for p in percents)
        criteria_note = (
            f"The cited card lists {tier_text}; its highest authored tier is "
            f"{max(percents)}%, which is a ceiling, not an expected outcome."
        )
    else:
        criteria_note = "Use the cited criteria card to compare the documented impairment."

    record_bits: list[str] = []
    if condition:
        band = _text(condition.get("band"))
        if band:
            record_bits.append(f"the dossier marks this item in the {band} readiness band")
        current = _valid_percent(condition.get("current_rating"), set(percents))
        if current is not None:
            record_bits.append(f"it records a current {current}% rating")
        target = _valid_percent(condition.get("target_rating"), set(percents))
        if target is not None:
            record_bits.append(f"you entered {target}% as a review target")
    if chunks:
        record_bits.append(f"the records search found {len(chunks)} cited excerpt(s) to review")
    record_note = "; ".join(record_bits) if record_bits else (
        "No matching uploaded-record excerpt was available in this pass; that does not mean "
        "the full record lacks support"
    )
    need_note = "; ".join(needs) if needs else "compare the full record with each cited criterion"
    return (
        f"What this is: {title} is evaluated under DC {dc}. {criteria_note} "
        f"Why it was checked: {_safe_seed_signal(cand.seed_signal)} "
        f"What your record shows: {record_note}. "
        f"What's still needed: {need_note}. This is a record-organizing review, not a prediction."
    )[:2000]


def _facts(
    cand: CandidateRating,
    card: Any,
    adjudication_cards: list[Any],
    chunks: list[Any],
    deterministic_body: str,
) -> str:
    tiers = extract_tiers(getattr(card, "data", None))
    lines = [
        "DETERMINISTIC EXPLANATION (keep its meaning):",
        deterministic_body,
        "",
        "MATCHING RATING CARD (the only permitted DC and percentages):",
        f"Title: {_text(getattr(card, 'title', ''))}",
        f"Diagnostic code: {_text(getattr(card, 'diagnostic_code', ''))}",
        f"Source: {_text(getattr(card, 'source', ''))}",
        f"Authored tiers: {json.dumps(tiers, ensure_ascii=False)[:5000]}",
        f"Criteria summary: {_text(getattr(card, 'content', ''))[:2500]}",
    ]
    if adjudication_cards:
        lines.extend(["", "RELATED PUBLIC ADJUDICATION CARDS:"])
        for row in adjudication_cards[:4]:
            lines.append(
                f"- {_text(getattr(row, 'title', ''))} | "
                f"{_text(getattr(row, 'source', ''))}: "
                f"{_text(getattr(row, 'content', ''))[:700]}"
            )
    if chunks:
        lines.extend(["", "VETERAN-OWNED RECORD EXCERPTS (quote or cautiously organize only):"])
        for chunk in chunks[:3]:
            lines.append(f"- {_text(getattr(chunk, 'content', ''))[:700]}")
    else:
        lines.extend(["", "VETERAN-OWNED RECORD EXCERPTS: none retrieved in this pass."])
    return "\n".join(lines)[:12000]


def _enrichment_grounded(body: str, cand: CandidateRating, card: Any) -> bool:
    """Apply mapping.validate_selection's anti-hallucination contract to prose."""
    card_dict = _card_dict(card)
    _, _, rationale = validate_selection(
        {"card_index": 0, "suggested_tier_percent": None, "rationale": body},
        [card_dict],
    )
    if rationale is None:
        return False

    # mapping.validate_selection intentionally recognizes explicit ``DC 1234``.
    # The firm reviewer additionally treats bare four-digit tokens as codes, so
    # enforce that stricter prose rule here too.
    allowed_dcs = {_text(cand.diagnostic_code), _text(getattr(card, "diagnostic_code", ""))}
    allowed_dcs.discard("")
    cited_dcs = {a or b for a, b in _DC_RE.findall(body or "")}
    if cited_dcs - allowed_dcs:
        log.warning(
            "firm/deepdive: candidate DC %s rewrite introduced code(s) %s — dropped.",
            cand.diagnostic_code,
            sorted(cited_dcs - allowed_dcs),
        )
        return False

    # Keep an explicit check near this safety boundary even though
    # validate_selection already applies it to rationale prose.
    allowed_pcts = {int(t["percent"]) for t in extract_tiers(getattr(card, "data", None))}
    cited_pcts = {int(value) for value in _PCT_RE.findall(body or "")}
    if cited_pcts - allowed_pcts:
        log.warning(
            "firm/deepdive: candidate DC %s rewrite introduced percentage(s) %s — dropped.",
            cand.diagnostic_code,
            sorted(cited_pcts - allowed_pcts),
        )
        return False
    return True


async def _best_effort_cards(db: "AsyncSession", query: str, *, card_type: str) -> list[Any]:
    try:
        return await retrieve_cards(db, query, k=2, card_type=card_type)
    except Exception:  # noqa: BLE001 - optional adjudication grounding
        log.warning(
            "firm/deepdive: %s-card retrieval failed; continuing with rating card.",
            card_type,
            exc_info=True,
        )
        return []


async def deep_dive_candidate(
    db: "AsyncSession",
    dossier: "VeteranDossier",
    cand: CandidateRating,
) -> Finding | None:
    """Run the seed -> retrieve -> explain shape for exactly one rating.

    The function never raises.  ``None`` means the hard graduation gate did not
    pass; a returned Finding always has a non-empty deterministic seed and an
    exact matching rating-criteria citation.
    """
    seed_signal = _text(cand.seed_signal)
    dc = _text(cand.diagnostic_code)
    if not seed_signal or not dc:
        return None

    # The graduation gate is an EXACT diagnostic-code lookup, not embedding
    # similarity: rating cards cluster tightly by body system, so a k=1 nearest
    # neighbour is often a sibling DC and would drop a validly-seeded candidate.
    async with _locked_retrieval(db):
        try:
            card = await card_by_diagnostic_code(db, dc, card_type="rating_criteria")
        except Exception:  # noqa: BLE001 - no grounding means no Finding
            log.warning(
                "firm/deepdive: rating-card lookup failed for DC %s.",
                dc,
                exc_info=True,
            )
            return None
        if card is None:
            log.info(
                "firm/deepdive: DC %s has no exact criteria card; not graduated.",
                dc,
            )
            return None

        query = f"{cand.title} {dc}".strip()
        try:
            chunks = await retrieve_document_chunks(db, dossier.uid, query, k=3)
        except Exception:  # noqa: BLE001 - optional after the hard card gate
            log.warning("firm/deepdive: record retrieval failed for DC %s.", dc, exc_info=True)
            chunks = []

        process_query = _PROCESS_QUERY.get(cand.origin, f"{cand.origin} disability claim")
        # The authored corpus currently tags §3.303/§3.310 as ``rule`` cards and
        # filing/review material as ``process`` cards. Pull both bounded sets so
        # the expert gets the relevant CFR rule and adjudication path.
        process_cards = await _best_effort_cards(db, process_query, card_type="process")
        rule_cards = await _best_effort_cards(db, process_query, card_type="rule")
    adjudication_cards = process_cards + [c for c in rule_cards if c not in process_cards]

    tiers = extract_tiers(getattr(card, "data", None))
    allowed = {int(t["percent"]) for t in tiers}
    condition = _condition_for(dossier, cand)
    rating_percent, rating_basis = _rating_percent(cand, condition, allowed)
    body_system = _text(getattr(card, "body_system", "")) or cand.body_system
    side, group = _side_and_group(cand, condition, body_system)
    needs = _needs(cand, condition)
    det_body = _deterministic_body(
        cand=cand,
        card=card,
        tiers=tiers,
        condition=condition,
        chunks=chunks,
        needs=needs,
    )
    if _LANE_BLOCK.search(det_body):
        # This should only be possible through an unexpectedly phrased title or
        # dossier field. The candidate remains auditable, but it has no safe body.
        log.warning("firm/deepdive: deterministic body failed legal-lane gate for DC %s.", dc)
        return None

    title = _safe_title(getattr(card, "title", "") or cand.title, dc)
    severity = "high" if cand.origin in {"increase", "secondary"} else "medium"
    all_cards = [card, *adjudication_cards]
    citations = [_citation(row) for row in all_cards]
    evidence_refs = [
        _text(getattr(chunk, "id", ""))
        for chunk in chunks
        if _text(getattr(chunk, "id", ""))
    ]
    key = f"deepdive:{cand.origin}:{dc}:{_text(cand.primary_dc)}"
    seed = {
        "key": key,
        "kind": cand.origin,
        "title": title,
        "body": det_body,
        "reg": _text(getattr(card, "source", "")),
        "diagnostic_code": dc,
        "origin": cand.origin,
        "seed_signal": seed_signal,
        "source_ref": cand.source_ref,
        "primary_dc": cand.primary_dc,
        "body_system": body_system or None,
        "tier_percents": sorted(allowed),
        "max_tier_percent": max(allowed) if allowed else None,
        "rating_percent": rating_percent,
        "rating_basis": rating_basis,
        "side": side,
        "group": group,
        "needs": needs,
        "needs_nexus": cand.origin == "secondary",
        "severity": severity,
        "citations": citations,
        "evidence_refs": evidence_refs,
    }
    regs = list(
        dict.fromkeys(
            _text(getattr(row, "source", ""))
            for row in all_cards
            if _text(getattr(row, "source", ""))
        )
    )
    finding = Finding(
        specialist=f"rating_expert:{dc}",
        kind=cand.origin,
        key=key,
        title=title,
        body=det_body,
        severity=severity,
        regs=regs,
        card_ids=[c["id"] for c in citations if c["id"]],
        evidence_refs=evidence_refs,
        needs=needs,
        confidence=1.0,
        seed=seed,
        det_body=det_body,
        enriched=False,
    )

    try:
        raw = await gateway.complete(
            [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": _facts(cand, card, adjudication_cards, chunks, det_body),
                },
            ],
            temperature=0.2,
            max_tokens=500,
        )
        body = _extract_body(raw)
        if not body:
            return finding
        body = body.strip()[:1600]
        if _LANE_BLOCK.search(body):
            log.warning("firm/deepdive: DC %s rewrite failed legal-lane gate — dropped.", dc)
            return finding
        if not _enrichment_grounded(body, cand, card):
            return finding
        finding.body = body
        finding.enriched = True
    except Exception:  # noqa: BLE001 - enrichment is optional, seed remains
        log.warning("firm/deepdive: enrichment failed for DC %s; using seed.", dc, exc_info=True)
    return finding


__all__ = ["deep_dive_candidate"]
