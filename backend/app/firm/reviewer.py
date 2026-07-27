"""The adversarial senior reviewer — the firm's second, independent gate.

Phase 2b flips this role from SUPPRESS to VERIFY-WELL-FOUNDED. Under the full-advocate
posture the app is ALLOWED to give cited, confidence-tagged opinions — including on
service connection and nexus. The reviewer's job is no longer to muzzle a conclusion;
it is to confirm the conclusion is EARNED by the veteran's record and the cited law,
and to reject only what is unfounded or guarantees a VA outcome.

Two cheap DETERMINISTIC gates run BEFORE any model call, on every CONCLUSION (an
originated theory, or an enriched floor finding whose body newly asserts service
connection / nexus):
  • Check A — it must carry ≥1 resolvable LAW cite (a CFR reg or a KB card id) AND
    ≥1 RECORD cite (a veteran-record chunk id).
  • Check B — it must carry a confidence tag (a VA-register confidence_level).
Then the existing structural gates and the adversarial LLM verdict run.

Remediation depends on the LAYER:
  • a THEORY that fails (uncited, untagged, guaranteed-outcome, or rejected) is
    REMOVED — it has no safe floor to fall back to;
  • an enriched FLOOR finding that fails REVERTS to its always-safe deterministic
    seed note (the existing behavior — a valid graduated seed never disappears);
  • a well-founded but OVER-CONFIDENT theory is DOWNGRADED (the reviewer writes the
    lower confidence), not removed.

Check A also closes the known HIGH-3 gap: a fabricated prose SC assertion used to
clear the numeric-only grounding; an uncited one is now caught here.
"""

from __future__ import annotations

import json
import logging
import re

from ..strategy.briefing import _LANE_BLOCK
from .base import Finding, confidence_for_level

log = logging.getLogger("veteran_ops.firm")

_VERDICT_CONTRACT = (
    'Return STRICT JSON only: {"supported": <bool>, "lane_ok": <bool>, '
    '"confidence_level": <null OR one of EXACTLY these four strings — copy verbatim, '
    'never "high"/"medium"/"low"/"strong": "more_likely_than_not" | "at_least_as_likely" '
    '| "less_likely_than_not" | "insufficient_evidence">, "note": "<one short reason>"}'
)

_REVIEWER_SYSTEM = (
    "You are Rating Raider's senior reviewer — a skeptical, protective VA-claims "
    "advocate. Rating Raider is a FULL ADVOCATE: it gives cited, confidence-tagged "
    "opinions, including on service connection and nexus. Your job is NOT to silence "
    "honest analysis — it is to VERIFY the analysis is WELL-FOUNDED, and to reject only "
    "what is unfounded or promises an outcome.\n\n"
    "You are given (a) a pre-approved deterministic explanation, (b) a rewritten version "
    "of it, and (c) the reference cards the rewrite could use. Judge the REWRITE against "
    "the original and the cards.\n\n"
    "Reject (supported=false) if the rewrite asserts a veteran fact, condition, rating, "
    "percentage, diagnostic code, dollar amount, or regulation that is NOT in the original "
    "or the cards — every assertion must be backed by something shown to you. Reject "
    "(lane_ok=false) ONLY if it GUARANTEES a VA outcome — says the veteran 'will be "
    "granted', 'will get', or is 'certain to receive' a rating or money. An opinion that a "
    "condition is service-connected, or is 'at least as likely as not' related to service, "
    "framed as analysis rather than a promise, is IN LANE — keep it.\n\n"
    + _VERDICT_CONTRACT
)

# Percentages ("40%") and 4-digit diagnostic codes ("DC 6354" / bare "6354").
# Bare codes are limited to the VA schedule range (5000-9999) so a year the model
# mentions ("your 2016 exam") is not mistaken for an introduced diagnostic code.
_PCT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent\b)")
_DC_RE = re.compile(r"\bDC\s*(\d{4})\b|\b([5-9]\d{3})\b", re.IGNORECASE)


def _lane_ok(text: str) -> bool:
    return not _LANE_BLOCK.search(text or "")


def _codes(text: str) -> tuple[set[str], set[str]]:
    """(percentages, diagnostic-codes) mentioned in `text`."""
    pcts = set(_PCT_RE.findall(text or ""))
    dcs = {a or b for a, b in _DC_RE.findall(text or "")}
    return pcts, dcs


def _enrichment_is_grounded(f: Finding) -> bool:
    """An enriched body may not introduce a percentage or diagnostic code the
    deterministic seed note didn't already contain — the same anti-hallucination
    rule mapping.validate_selection enforces on tier selections, applied to prose."""
    allow_pcts, allow_dcs = _codes(f.det_body)
    body_pcts, body_dcs = _codes(f.body)
    if body_pcts - allow_pcts:
        log.warning("firm/reviewer: %r introduced percentage(s) %s not in seed — reject.",
                    f.key, sorted(body_pcts - allow_pcts))
        return False
    if body_dcs - allow_dcs:
        log.warning("firm/reviewer: %r introduced diagnostic code(s) %s not in seed — reject.",
                    f.key, sorted(body_dcs - allow_dcs))
        return False
    return True


# ── Well-foundedness gates (Phase 2b) — deterministic, run before the LLM verdict ──
# A resolvable LAW cite is a CFR/USC reg string OR a KB card id; a RECORD cite is a
# veteran-record chunk id. A CONCLUSION is either an originated theory (always) or an
# enriched floor finding whose body newly ASSERTS service connection / nexus / a met
# criterion — the strong claims the flipped lane now ALLOWS but that must be earned.
_CFR_RE = re.compile(r"\bC\.?F\.?R\.?\b|\bU\.?S\.?C\.?\b|§\s*\d|\b\d+\.\d{2,4}\b", re.IGNORECASE)
_CONCLUSION_RE = re.compile(
    r"\bis\s+service[-\s]connected\b"
    r"|\bare\s+service[-\s]connected\b"
    r"|\bat least as likely as not\b"
    r"|\bmore likely than not\b"
    r"|\bis\s+secondary\s+to\b"
    r"|\b(?:is|was|are)\s+(?:caused|aggravated)\s+by\b"
    r"|\b(?:is|are)\s+(?:related|linked|connected|due)\s+to\s+(?:your|his|her|their|military|active)\s+service\b"
    r"|\byou\s+meet\s+the\s+(?:criteria|requirements)\s+for\b",
    re.IGNORECASE,
)


def _asserts_conclusion(text: str) -> bool:
    """True when prose makes a firm service-connection / nexus / criteria-met claim
    (not a hedge like 'may be' / 'worth reviewing'). Used to decide whether an
    ENRICHED FLOOR body has crossed into a conclusion that must be cited (Check A)."""
    return bool(_CONCLUSION_RE.search(text or ""))


def _law_cites(f: Finding) -> list[str]:
    """Resolvable law citations on a finding: CFR/USC reg strings + KB card ids
    (from `regs`, `card_ids`, and the structured `citations`)."""
    out = [r for r in (f.regs or []) if r and _CFR_RE.search(str(r))]
    out += [c for c in (f.card_ids or []) if c]
    for c in f.citations or []:
        if isinstance(c, dict):
            if c.get("card_id"):
                out.append(str(c["card_id"]))
            if c.get("reg") and _CFR_RE.search(str(c["reg"])):
                out.append(str(c["reg"]))
    return out


def _record_cites(f: Finding) -> list[str]:
    """Veteran-record citations: chunk ids (from `evidence_refs` + `citations`)."""
    out = [e for e in (f.evidence_refs or []) if e]
    for c in f.citations or []:
        if isinstance(c, dict) and c.get("chunk_id"):
            out.append(str(c["chunk_id"]))
    return out


def _check_a_well_cited(f: Finding) -> bool:
    """Check A — a conclusion carries ≥1 resolvable LAW cite AND ≥1 RECORD cite."""
    return bool(_law_cites(f)) and bool(_record_cites(f))


def _check_b_tagged(f: Finding) -> bool:
    """Check B — a conclusion carries a valid VA-register confidence tag."""
    return confidence_for_level(f.confidence_level) is not None


def _maybe_downgrade(f: Finding, verdict: dict) -> str | None:
    """If the reviewer judged a well-founded theory OVER-confident, write the LOWER
    confidence (register level + numeric) into the finding. Never RAISES confidence.
    Returns a note when it downgraded, else None."""
    rlevel = str(verdict.get("confidence_level") or "").strip()
    rval = confidence_for_level(rlevel)
    if rval is None or rval >= float(f.confidence):
        return None
    from ..config import settings

    lo = float(getattr(settings, "theory_confidence_floor", 0.05))
    hi = float(getattr(settings, "theory_confidence_ceiling", 0.85))
    old = f.confidence_level
    f.confidence_level = rlevel
    f.confidence = min(hi, max(lo, rval))
    return f"reviewer downgraded confidence {old}→{rlevel}: " + str(verdict.get("note") or "")


# Deterministic prose-grounding for a theory — the record-text analogue of
# _theory_numbers_grounded (which only guards %/DC). A concrete asserted FACT must
# resolve to the veteran's RECORD (or the cited law): every year must appear in the
# record text; every multi-word proper-noun phrase (a place, base, program, person)
# must appear in the record or the law. Catches a fabricated prose fact that carries
# no number — e.g. "service records document Camp Lejeune stationing in 1985".
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b")
_PROSE_LEAD = {
    "the", "this", "that", "these", "those", "your", "you", "a", "an", "and", "or",
    "but", "if", "because", "under", "when", "while", "since", "for", "in", "on",
    "at", "as", "it", "he", "she", "they", "we", "his", "her", "their", "our", "then",
    "so", "to", "of", "with", "without", "even", "also", "both", "each", "every", "no",
}


def _theory_prose_grounded(body: str, record_text: str, law_text: str) -> bool:
    """True when a theory's concrete asserted facts resolve to the cited record/law.
    Fail CLOSED on a miss. Years must appear in the RECORD (a claimed service date the
    veteran's own record does not show is fabricated); multi-word proper nouns must
    appear in the record or the law (a leading capitalized function word is stripped
    first so a sentence-start capital isn't mistaken for a named entity)."""
    body = body or ""
    rec = (record_text or "").lower()
    corpus = rec + " \n " + (law_text or "").lower()
    for yr in set(_YEAR_RE.findall(body)):
        if yr not in rec:
            return False
    for phrase in set(_PROPER_RE.findall(body)):
        words = phrase.split()
        if words and words[0].lower() in _PROSE_LEAD:
            words = words[1:]
        if len(words) < 2:  # a lone capitalized token isn't a checkable named entity
            continue
        if " ".join(words).lower() not in corpus:
            return False
    return True


async def _resolve_theory_citations(f: Finding, db) -> tuple[list, list] | None:
    """RE-RESOLVE a theory's cited ids against the DB — defense-in-depth, never trust
    the finding's own card_ids/evidence_refs (which only prove EXISTENCE at origination
    time). Returns (cards, chunks) actually found, or None → the caller DROPS. Fails
    CLOSED when: the db is unavailable, the veteran uid is unknown, the theory carries
    no law+record cite, retrieval errors, or ANY cited id fails to resolve (stale or
    fabricated). Chunks are scoped to the theory's own veteran."""
    if db is None:
        return None
    card_ids = [str(c["card_id"]) for c in (f.citations or [])
                if isinstance(c, dict) and c.get("card_id")]
    chunk_ids = [str(c["chunk_id"]) for c in (f.citations or [])
                 if isinstance(c, dict) and c.get("chunk_id")]
    uid = str((f.seed or {}).get("uid") or "")
    if not card_ids or not chunk_ids or not uid:
        return None
    try:
        from ..kb.store import cards_by_ids
        from ..rag import chunks_by_ids

        cards = await cards_by_ids(db, card_ids)
        chunks = await chunks_by_ids(db, uid, chunk_ids)
    except Exception:  # noqa: BLE001 — a resolution failure fails CLOSED
        log.warning("firm/reviewer: citation re-resolution errored for %r — dropping.", f.key, exc_info=True)
        return None
    got_cards = {str(getattr(c, "id", "")) for c in cards}
    got_chunks = {str(getattr(ch, "id", "")) for ch in chunks}
    if set(card_ids) - got_cards or set(chunk_ids) - got_chunks:
        log.warning("firm/reviewer: theory %r has unresolvable citation id(s) — dropping.", f.key)
        return None
    return cards, chunks


def _parse_verdict(raw: str) -> dict | None:
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or "supported" not in obj or "lane_ok" not in obj:
        return None
    return obj


# For a HIGH-STAKES finding (an originated theory, or a high-severity floor finding) one
# skeptical pass isn't enough — we check it from three DISTINCT well-foundedness lenses and
# require consensus. Each lens shares the strict-JSON contract but looks for a different
# failure mode (redundancy catches less than diversity does). Re-aimed for Phase 2b: the
# question is "is this EARNED?", not "did it dare to conclude?".
_LENSES = {
    "evidence": (
        "You are the EVIDENCE reviewer. Judge ONLY well-foundedness on the FACTS: is every "
        "assertion about THIS veteran's record (a document, a symptom, a diagnosis, a date) "
        "backed by a cited record excerpt or by the original? supported=false if the finding "
        "leans on a veteran fact that is not cited or not shown to you."
    ),
    "regulatory": (
        "You are the REGULATORY reviewer. Judge ONLY the LAW: does every regulation, "
        "diagnostic code, percentage, or criterion cited actually appear in the reference "
        "cards, and is it ON-POINT for this theory (the right rule for the right condition)? "
        "supported=false if a law cite does not resolve to a card or is off-point."
    ),
    "soundness": (
        "You are the SOUNDNESS reviewer. Judge ONLY whether this is a WELL-FOUNDED opinion "
        "with NO GUARANTEED OUTCOME. lane_ok=false only if it promises what VA will decide "
        "('will be granted' / 'will get' / 'certain to receive') — an 'at least as likely as "
        "not' nexus opinion is fine. Then set confidence_level to the level the EVIDENCE "
        "actually supports; set it LOWER than the finding claims if it is over-stated."
    ),
}


async def _one_verdict(system: str, user: str) -> dict | None:
    from ..llm.gateway import gateway

    raw = await gateway.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=200,
    )
    return _parse_verdict(raw)


async def _llm_verdict(f: Finding, db) -> dict | None:
    """The adversarial LLM pass for a FLOOR finding (an enriched reword). A
    high-severity finding earns the three-lens panel and must win a MAJORITY on both
    `supported` and `lane_ok`; everything else gets one skeptical pass. Best-effort:
    returns None on any failure — the caller reverts the enrichment to its always-safe
    deterministic seed. (Theories do NOT come here; they go through
    `_theory_panel_verdict`, which fails CLOSED, not through this revert-safe path.)"""
    if db is None:
        return None
    try:
        from ..kb.store import retrieve_cards

        query = f.seed.get("secondary") or f.title
        cards = await retrieve_cards(db, str(query), k=3)
        card_text = "\n".join(
            f"  • {getattr(c, 'title', '')}: {(getattr(c, 'content', '') or '')[:300]}"
            for c in cards
        ) or "  (no reference cards retrieved)"
        user = (
            f"ORIGINAL (pre-approved) explanation:\n{f.det_body}\n\n"
            f"REWRITE to review:\n{f.body}\n\n"
            f"Reference cards the rewrite could use:\n{card_text}"
        )

        if str(getattr(f, "severity", "")) == "high":
            import asyncio

            lens_system = [f"{sys_}\n\n{_VERDICT_CONTRACT}" for sys_ in _LENSES.values()]
            verdicts = await asyncio.gather(
                *(_one_verdict(sys_, user) for sys_ in lens_system), return_exceptions=True
            )
            good = [v for v in verdicts if isinstance(v, dict)]
            if not good:
                return None  # panel unreachable → caller reverts to seed
            n = len(good)
            supported = sum(1 for v in good if v.get("supported")) * 2 >= n
            lane_ok = sum(1 for v in good if v.get("lane_ok")) * 2 >= n
            note = "; ".join(str(v.get("note") or "") for v in good if v.get("note"))[:300]
            return {"supported": supported, "lane_ok": lane_ok, "note": f"panel({n}): {note}"}

        return await _one_verdict(_REVIEWER_SYSTEM, user)
    except Exception:  # noqa: BLE001 — reviewer down → caller reverts to seed
        log.warning("firm/reviewer: verdict failed for %r — will revert to seed.", f.key, exc_info=True)
        return None


async def _theory_panel_verdict(f: Finding, cards: list, chunks: list) -> dict | None:
    """The record-AWARE three-lens panel for a THEORY. It hands each lens the veteran's
    OWN record excerpt TEXT (not opaque ids) so the evidence lens can actually verify
    the asserted record-facts, plus the re-resolved law cards. Fails CLOSED: it requires
    ALL THREE lenses to return a parseable verdict AND UNANIMOUS `supported` and
    `lane_ok` (a partial panel, or any dissent, → None → the caller DROPS the theory).
    The most-conservative confidence_level rides back for a possible downgrade."""
    try:
        import asyncio

        record_text = "\n".join(
            f"  • {(getattr(ch, 'content', '') or '')[:500]}" for ch in chunks
        ) or "  (no record excerpts resolved)"
        card_text = "\n".join(
            f"  • {getattr(c, 'title', '')} [{getattr(c, 'source', '')}]: "
            f"{(getattr(c, 'content', '') or '')[:400]}"
            for c in cards
        ) or "  (no reference cards resolved)"
        user = (
            "THEORY to verify (originated ABOVE the deterministic floor):\n"
            f"Claim: {f.title}\n"
            f"Reasoning: {f.body}\n"
            f"Stated confidence: {f.confidence_level}\n\n"
            "The VETERAN'S OWN RECORD EXCERPTS it must be grounded in — verify EVERY "
            "asserted record-fact against THIS text; anything not here is unsupported:\n"
            f"{record_text}\n\n"
            "The VA-LAW reference cards it relies on:\n"
            f"{card_text}"
        )
        lens_system = [f"{sys_}\n\n{_VERDICT_CONTRACT}" for sys_ in _LENSES.values()]
        verdicts = await asyncio.gather(
            *(_one_verdict(sys_, user) for sys_ in lens_system), return_exceptions=True
        )
        good = [v for v in verdicts if isinstance(v, dict)]
        if len(good) < len(lens_system):  # HIGH-1: require the FULL panel, fail CLOSED
            log.warning("firm/reviewer: theory %r panel incomplete (%d/%d) — dropping.",
                        f.key, len(good), len(lens_system))
            return None
        supported = all(v.get("supported") for v in good)  # unanimous — any dissent kills it
        lane_ok = all(v.get("lane_ok") for v in good)
        note = "; ".join(str(v.get("note") or "") for v in good if v.get("note"))[:300]
        out = {"supported": supported, "lane_ok": lane_ok, "note": f"panel({len(good)}): {note}"}
        levels = [lv for v in good if (lv := str(v.get("confidence_level") or ""))
                  and confidence_for_level(lv) is not None]
        if levels:
            out["confidence_level"] = min(levels, key=lambda lv: confidence_for_level(lv))
        return out
    except Exception:  # noqa: BLE001 — a broken panel fails CLOSED (theory dropped)
        log.warning("firm/reviewer: theory panel errored for %r — dropping.", f.key, exc_info=True)
        return None


def _finalize(f: Finding, note: str) -> tuple[str, bool]:
    """After a revert, the body is the deterministic seed note; keep it only if it
    is itself lane-safe (a real seed always is). Otherwise the finding has no safe
    version and is REMOVED."""
    if not _lane_ok(f.body):
        return note + " — deterministic body ALSO unsafe, removed", False
    return note, True


async def _review_one(f: Finding, db) -> tuple[str, bool]:
    is_theory = getattr(f, "layer", "floor") == "theory"

    # ── Deterministic well-foundedness gates (Phase 2b), before any model call ──
    # A CONCLUSION — an originated theory (always), or an enriched floor finding whose
    # body newly ASSERTS service connection / nexus — must cite law AND record (Check
    # A) and carry a confidence tag (Check B). A THEORY that fails is REMOVED (no safe
    # floor to fall back to); an enriched FLOOR finding REVERTS to its deterministic
    # body (existing behavior). This closes HIGH-3: an uncited prose SC assertion no
    # longer clears the numeric-only grounding.
    if is_theory or (f.enriched and _asserts_conclusion(f.body)):
        if not _check_a_well_cited(f):
            if is_theory:
                return "theory removed: uncited (Check A needs a law cite AND a record cite)", False
            f.revert_to_deterministic()
            return _finalize(f, "enriched conclusion was uncited (Check A); reverted to seed")
        if not _check_b_tagged(f):
            if is_theory:
                return "theory removed: no confidence tag (Check B)", False
            f.revert_to_deterministic()
            return _finalize(f, "enriched conclusion had no confidence tag (Check B); reverted to seed")

    # Lane gate: a guaranteed VA outcome is never in lane (both layers).
    if not _lane_ok(f.body):
        if is_theory:
            return "theory removed: guaranteed-outcome phrasing (legal-lane gate)", False
        if not f.enriched:
            return "deterministic body tripped legal-lane gate — removed", False
        f.revert_to_deterministic()
        return _finalize(f, "enriched body tripped legal-lane gate; reverted to seed")

    # ── THEORY: fail CLOSED. A theory has no safe floor to fall back to, so anything
    # short of an independently-verified, well-founded opinion is DROPPED. ──
    if is_theory:
        # HIGH-2: RE-RESOLVE the cited ids against the DB (don't trust the finding's
        # own lists). A stale/fabricated id, an unknown veteran, or an unreachable DB
        # → drop. This also yields the record TEXT the panel needs (CRITICAL-1).
        resolved = await _resolve_theory_citations(f, db)
        if resolved is None:
            return "theory removed: citations did not re-resolve against the record (fail closed)", False
        cards, chunks = resolved
        record_text = "\n".join((getattr(ch, "content", "") or "") for ch in chunks)
        law_text = " \n ".join(
            f"{getattr(c, 'title', '') or ''} {getattr(c, 'source', '') or ''} {getattr(c, 'content', '') or ''}"
            for c in cards
        )
        # CRITICAL-1 backstop: a concrete asserted record-fact must resolve to the
        # cited record (a fabricated prose fact carrying no number is caught here).
        if not _theory_prose_grounded(f.body, record_text, law_text):
            return "theory removed: asserted a record-fact absent from the cited record (prose grounding)", False
        # CRITICAL-1 + CRITICAL-2 + HIGH-1: the record-aware full panel, failing CLOSED
        # on an unavailable/incomplete panel (None) — never keep an unverified theory.
        verdict = await _theory_panel_verdict(f, cards, chunks)
        if verdict is None:
            return "theory removed: reviewer panel unavailable or incomplete (fail closed)", False
        if not (verdict.get("supported") and verdict.get("lane_ok")):
            return "theory removed by reviewer panel: " + str(verdict.get("note") or ""), False
        # Well-founded. Honor a DOWNGRADE of over-confidence (never a removal, never a raise).
        note = _maybe_downgrade(f, verdict)
        return (note or "theory verified well-founded: " + str(verdict.get("note") or "")), True

    # ── FLOOR: deterministic seed, or an enriched reword (revert-to-seed, fail SAFE). ──
    if not f.enriched:
        return "deterministic seed (no enrichment to review)", True
    if not _enrichment_is_grounded(f):
        f.revert_to_deterministic()
        return _finalize(f, "enriched body added an ungrounded code/percentage; reverted to seed")
    verdict = await _llm_verdict(f, db)
    if verdict is None:
        f.revert_to_deterministic()
        return _finalize(f, "reviewer unavailable; reverted to deterministic write-up")
    if not (verdict.get("supported") and verdict.get("lane_ok")):
        f.revert_to_deterministic()
        return _finalize(f, "reviewer rejected enrichment; reverted to seed: " + str(verdict.get("note") or ""))
    return "reviewer approved enrichment: " + str(verdict.get("note") or ""), True


async def review(findings: list[Finding], db) -> list[Finding]:
    """Adversarially review every finding. Returns the survivors with
    `reviewed=True` set; drops any finding with no lane-safe version. Never
    raises — a reviewer-infra failure reverts enrichments to the safe seed note."""
    kept: list[Finding] = []
    for f in findings:
        try:
            note, ok = await _review_one(f, db)
        except Exception:  # noqa: BLE001 — a broken review must not sink the finding
            log.warning("firm/reviewer: error on %r — reverting to seed.", f.key, exc_info=True)
            f.revert_to_deterministic()
            note, ok = _finalize(f, "reviewer error; reverted to deterministic write-up")
        if not ok:
            log.info("firm/reviewer: removed finding %r (%s)", f.key, note)
            continue
        f.reviewed = True
        f.review_note = note
        kept.append(f)
    return kept
