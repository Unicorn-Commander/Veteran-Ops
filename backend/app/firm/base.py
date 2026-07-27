"""The specialist-firm framework — a `Finding` value object + the `Specialist` ABC.

Rating Raider's "firm" graduates the deterministic rating-strategy SEEDS
(app/strategy/rating_rules.py, app/analysis/presumptives.py) into grounded
specialist agents. The design is deliberately conservative:

GRADUATION RULE (the legal spine): a Finding surfaces ONLY if its deterministic
seed fires (seed confidence = 1.0). The local LLM may ENRICH a finding's write-up
(body / needs) but it can NEVER originate a finding, invent a fact, predict an
outcome, or assert service connection. Every seed is a PURE function over the
veteran's own data; the model only rewords what the seed already established,
grounded in the same regs and cards.

Two-phase `find()` per specialist:
    seed()      PURE deterministic gate (reuses rating_rules / presumptives)
    retrieve()  pull the grounding (VA-law KB cards + the vet's own evidence)
    explain()   grounded write-up — local LLM best-effort, ALWAYS falls back to
                the seed's deterministic note on any failure or lane-gate hit.

A specialist with no LLM value (`llm_enrich = False`) skips the model entirely
and returns the deterministic seed as a Finding with no model call.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..llm.gateway import gateway
from ..strategy.briefing import _LANE_BLOCK  # reuse the output-side legal-lane gate

if TYPE_CHECKING:  # avoid import cycles / keep pure-fn tests importable
    from sqlalchemy.ext.asyncio import AsyncSession

    from .context import VeteranDossier

log = logging.getLogger("veteran_ops.firm")


# ── VA-register confidence (Phase 2b) ────────────────────────────────────────────
# The four levels VA adjudication itself speaks in. The pivot is `at_least_as_likely`
# = 0.50 — the NEXUS THRESHOLD: under the benefit-of-the-doubt rule (38 U.S.C.
# §5107(b); 38 CFR §3.102) evidence in approximate balance is resolved FOR the
# veteran, so "at least as likely as not" is the WINNING line, not a coin-flip loss.
# A deterministic FLOOR finding is not one of these — it is settled fact (confidence
# 1.0, confidence_level None). Only an ORIGINATED theory carries a register level.
CONFIDENCE_LEVELS: tuple[str, ...] = (
    "more_likely_than_not",
    "at_least_as_likely",
    "less_likely_than_not",
    "insufficient_evidence",
)
_CONFIDENCE_LEVEL_VALUE: dict[str, float] = {
    "more_likely_than_not": 0.65,
    "at_least_as_likely": 0.50,  # the nexus threshold — pinned by the benefit-of-the-doubt rule
    "less_likely_than_not": 0.35,
    "insufficient_evidence": 0.15,
}


def confidence_for_level(level: str | None) -> float | None:
    """Numeric confidence for a VA-register level, or None when `level` is not one
    of CONFIDENCE_LEVELS (so callers can tell 'no tag' from a real level)."""
    return _CONFIDENCE_LEVEL_VALUE.get(str(level or "").strip())


# Human phrasing of each register level, for the server-side FRAMING stamped onto a
# theory body so no client can render an originated opinion as settled fact. Kept
# lower-case / single-capital so it never trips the reviewer's proper-noun/year
# prose-grounding check.
_LEVEL_PHRASE: dict[str, str] = {
    "more_likely_than_not": "more likely than not",
    "at_least_as_likely": "at least as likely as not",
    "less_likely_than_not": "less likely than not",
    "insufficient_evidence": "insufficient evidence so far",
}


def frame_theory_body(body: str, level: str) -> str:
    """Stamp a theory body with its register level — a hard, server-side annotation
    that travels with the persisted text (belt-and-suspenders with layer=='theory')."""
    phrase = _LEVEL_PHRASE.get(level, "an opinion")
    return f"[Assessment ({phrase}) — our opinion; the VA decides] {body}"


@dataclass
class Finding:
    """One graduated rating-strategy finding.

    Shaped so a secondary/underrating finding drops straight into
    `plan.build_game_plan`'s `opportunities` list (and a pyramiding one into
    `cautions`) via `to_render()`, which merges the (possibly enriched) `body`
    over the deterministic `seed` dict — so the rendered shape is byte-identical
    to what the seeds produce today, plus a warmer body.

    `seed` is the raw deterministic dict the seed produced (already in the target
    render shape). `det_body` is the always-safe deterministic write-up we revert
    to if enrichment or review rejects the model's version — the graduated seed
    therefore never disappears because the LLM misbehaved.
    """

    specialist: str
    kind: str  # secondary | underrating | pyramiding | tdiu | presumptive
    key: str  # stable dedupe key
    title: str
    body: str
    severity: str = "medium"  # high | medium | low
    regs: list[str] = field(default_factory=list)
    card_ids: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    suggested_form: str | None = None
    confidence: float = 1.0  # seed fired → 1.0 (the LLM never lowers/raises this)
    # ── Phase 2b: layer + VA-register confidence + structured citations ──────────
    #: "floor"  = the deterministic seed (settled; confidence 1.0, no register level)
    #: "theory" = an ORIGINATED opinion above the floor (0<confidence<1, a level, cites)
    layer: str = "floor"
    #: VA-register level for a theory (None for the deterministic floor). See
    #: CONFIDENCE_LEVELS. `at_least_as_likely` = the 0.50 nexus threshold.
    confidence_level: str | None = None
    #: Inline citations backing a theory's claims: [{card_id?, chunk_id?, reg?}] — a
    #: law cite (card_id / CFR reg) and a record cite (chunk_id) per claim. The
    #: reviewer's Check A requires ≥1 resolvable law cite AND ≥1 record cite.
    citations: list[dict] = field(default_factory=list)
    reviewed: bool = False
    review_note: str | None = None
    # ── internal (not part of the rendered opportunity/caution) ──────────────
    seed: dict = field(default_factory=dict)
    det_body: str = ""  # the deterministic seed note — the always-safe fallback
    enriched: bool = False  # True once the LLM body passed the local lane gate

    def revert_to_deterministic(self, note: str | None = None) -> None:
        """Drop any LLM enrichment and fall back to the deterministic seed note.
        Used by explain() on failure and by the reviewer on rejection, so a valid
        graduated seed always survives with safe wording."""
        self.body = self.det_body
        self.enriched = False
        if note:
            self.review_note = note

    def to_render(self) -> dict:
        """The render dict for the Battle Plan: the deterministic seed shape with
        the (possibly enriched) body overlaid. Faithful to the seed's key/kind/
        reg/severity/etc. — only `body` may differ from what the seed produced."""
        return {**self.seed, "body": self.body}

    def to_dict(self) -> dict:
        """JSON-serializable form for the facts-hash cache."""
        return {
            "specialist": self.specialist,
            "kind": self.kind,
            "key": self.key,
            "title": self.title,
            "body": self.body,
            "severity": self.severity,
            "regs": self.regs,
            "card_ids": self.card_ids,
            "evidence_refs": self.evidence_refs,
            "needs": self.needs,
            "suggested_form": self.suggested_form,
            "confidence": self.confidence,
            "layer": self.layer,
            "confidence_level": self.confidence_level,
            "citations": self.citations,
            "reviewed": self.reviewed,
            "review_note": self.review_note,
            "seed": self.seed,
            "det_body": self.det_body,
            "enriched": self.enriched,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(
            specialist=d.get("specialist", ""),
            kind=d.get("kind", ""),
            key=d.get("key", ""),
            title=d.get("title", ""),
            body=d.get("body", ""),
            severity=d.get("severity", "medium"),
            regs=list(d.get("regs") or []),
            card_ids=list(d.get("card_ids") or []),
            evidence_refs=list(d.get("evidence_refs") or []),
            needs=list(d.get("needs") or []),
            suggested_form=d.get("suggested_form"),
            confidence=float(d.get("confidence", 1.0)),
            layer=str(d.get("layer") or "floor"),
            confidence_level=d.get("confidence_level"),
            citations=list(d.get("citations") or []),
            reviewed=bool(d.get("reviewed", False)),
            review_note=d.get("review_note"),
            seed=dict(d.get("seed") or {}),
            det_body=d.get("det_body", ""),
            enriched=bool(d.get("enriched", False)),
        )


def _extract_body(raw: str) -> str | None:
    """Pull an enriched `body` string out of a local model's reply, defensively —
    accepts a bare JSON object {"body": "..."} (fenced or not) or, failing that,
    plain prose. Returns None when there's nothing usable."""
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict) and isinstance(obj.get("body"), str):
                b = obj["body"].strip()
                return b or None
        except (json.JSONDecodeError, ValueError):
            pass
    # No JSON object — treat the whole (think-stripped) reply as prose.
    return text or None


# ── Theory origination (Phase 2b) ────────────────────────────────────────────────
# The full-advocate posture, in a prompt: ORIGINATE reasoned service-connection /
# nexus / secondary theories ABOVE the deterministic floor — but cite law AND record
# per claim, tag confidence in the VA register, and never guarantee a VA outcome.
_THEORY_SYSTEM = (
    "You are Rating Raider's theory strategist — a skeptical, well-read VA-claims "
    "advocate. Rating Raider is a full advocate for ONE veteran. Your job is to "
    "ORIGINATE reasoned service-connection theories (direct §3.303, secondary §3.310, "
    "or presumptive) that the deterministic rules did NOT already surface, using ONLY "
    "this veteran's dossier and the VA-law reference cards provided. This is analysis "
    "ABOVE the floor — you may reach a conclusion the automatic rules did not.\n\n"
    "HARD RULES — a theory that breaks any of these is worthless and will be discarded:\n"
    "1. CITE EVERYTHING. Every theory MUST carry citations: the card_id(s) of the law "
    "it rests on AND the chunk_id(s) of the veteran-record excerpt it relies on. A "
    "theory with no law cite or no record cite is thrown out.\n"
    "2. TAG YOUR CONFIDENCE in the VA register, exactly one of: "
    "\"more_likely_than_not\", \"at_least_as_likely\" (the nexus threshold — evidence "
    "in balance, benefit of the doubt to the veteran), \"less_likely_than_not\", "
    "\"insufficient_evidence\".\n"
    "3. NEVER GUARANTEE an outcome. Do not say the veteran 'will be granted', 'will "
    "get', or is 'certain to receive' anything — VA decides. You MAY say a theory is "
    "'at least as likely as not' service-connected; that is analysis, not a promise.\n"
    "4. INVENT NOTHING. Use no condition, diagnostic code, percentage, or dollar amount "
    "that is not in the cards or the veteran's record shown to you.\n"
    "5. Propose AT MOST 4 theories, strongest first. If nothing is well-founded, return "
    "an empty list.\n\n"
    "Return STRICT JSON only, no markdown fences: {\"theories\": [{"
    "\"kind\": \"secondary\"|\"direct\"|\"presumptive\", "
    "\"title\": \"<short name of the theory>\", "
    "\"body\": \"<2-5 sentences, plain 8th-grade language, why the record + law support it>\", "
    "\"confidence_level\": \"<one of the four register values>\", "
    "\"citations\": [{\"card_id\": \"<id from a reference card>\", \"chunk_id\": \"<id from a record excerpt>\"}]"
    "}]}"
)

_THEORY_PCT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent\b)", re.IGNORECASE)
_THEORY_DC_RE = re.compile(r"\bDC\s*(\d{4})\b|\b([5-9]\d{3})\b", re.IGNORECASE)
_THEORY_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _THEORY_SLUG_RE.sub("-", (text or "").lower()).strip("-")[:60] or "theory"


def _parse_theories(raw: str) -> list[dict]:
    """Pull the `theories` array out of a model reply, defensively (fenced or not)."""
    if not raw:
        return []
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    arr = obj.get("theories") if isinstance(obj, dict) else None
    return [t for t in arr if isinstance(t, dict)] if isinstance(arr, list) else []


def _grounding_text(grounding: dict) -> str:
    """All text the model was grounded on — used to verify a theory invents no
    percentage or diagnostic code (the numbers must appear in the grounding)."""
    parts: list[str] = []
    for c in grounding.get("cards") or []:
        parts.append(getattr(c, "content", "") or "")
        parts.append(getattr(c, "source", "") or "")
        parts.append(getattr(c, "title", "") or "")
    for ch in grounding.get("chunks") or []:
        parts.append(getattr(ch, "content", "") or "")
    return " ".join(parts)


def _theory_numbers_grounded(body: str, grounding_text: str) -> bool:
    """True when every percentage and diagnostic code in a theory body also appears
    in the grounding — the anti-hallucination guard the floor path applies to prose,
    applied to originated theories (a theory has no seed note to diff against)."""
    g = grounding_text or ""
    if set(_THEORY_PCT_RE.findall(body)) - set(_THEORY_PCT_RE.findall(g)):
        return False
    body_dcs = {a or b for a, b in _THEORY_DC_RE.findall(body)}
    g_dcs = {a or b for a, b in _THEORY_DC_RE.findall(g)}
    return not (body_dcs - g_dcs)


class Specialist(ABC):
    """A firm specialist: a PURE seed, a grounding retrieval, and a grounded
    explainer. Subclasses supply `seed()` (deterministic gate reusing
    rating_rules) and the per-specialist LLM contract; the two-phase `find()`
    and the default `explain()` are provided here."""

    name: str = "specialist"
    #: When False, the specialist never calls the model — explain() returns the
    #: deterministic seed as a Finding (pyramiding/tdiu/presumptive in Phase 1).
    llm_enrich: bool = False
    #: Per-specialist system prompt for the enriched write-up. MUST forbid new
    #: facts and require reg-cited grounding. Only used when llm_enrich is True.
    system_prompt: str = ""
    #: Phase 2b opt-in: when True (and llm_enrich is True and origination is enabled
    #: in config), this specialist ORIGINATES theories ABOVE the floor via theorize().
    #: The four floor specialists leave it False; only TheorySpecialist flips it on.
    can_theorize: bool = False
    #: System prompt for the theory-origination pass. Empty → the module default
    #: (_THEORY_SYSTEM). Only used when can_theorize is True.
    theory_system_prompt: str = ""

    # ── phase 1: the pure deterministic gate ─────────────────────────────────
    @abstractmethod
    def seed(self, dossier: "VeteranDossier") -> list[dict]:
        """PURE, deterministic. Returns the raw seed dicts (already in the target
        render shape) for every finding this specialist establishes. No DB, no
        LLM. If this is empty, the specialist surfaces nothing."""

    # ── phase 2a: grounding ───────────────────────────────────────────────────
    async def retrieve(
        self, db: "AsyncSession", dossier: "VeteranDossier", seed: dict
    ) -> dict:
        """Pull grounding for ONE seed: VA-law KB cards + the veteran's own
        evidence chunks. Best-effort — never raises. Default: no grounding
        (deterministic specialists don't need it). Returns
        {"cards": [KBCard...], "chunks": [DocumentChunk...]}."""
        return {"cards": [], "chunks": []}

    # ── phase 2b: the grounded write-up ──────────────────────────────────────
    def _facts(self, dossier: "VeteranDossier", seed: dict, grounding: dict) -> str:
        """Compact, literal facts block for the model. Only data already
        established: the seed's own theory + reg, the retrieved card criteria,
        and any of the veteran's own records that mention the condition. Invents
        nothing. Subclasses may override to add specialist-specific context."""
        lines: list[str] = []
        lines.append(f"Finding to reword (do NOT change its meaning): {seed.get('title')}")
        lines.append(f"Regulation it rests on: {seed.get('reg')}")
        lines.append("The established, plain-language explanation:")
        lines.append(seed.get("body") or "")
        cards = grounding.get("cards") or []
        if cards:
            lines.append("\nVA-law reference cards (the ONLY law you may cite):")
            for c in cards[:4]:
                title = getattr(c, "title", None) or "(untitled)"
                dc = getattr(c, "diagnostic_code", None)
                src = getattr(c, "source", None)
                lines.append(f"  • {title}" + (f" [DC {dc}]" if dc else "") + (f" — {src}" if src else ""))
        chunks = grounding.get("chunks") or []
        if chunks:
            lines.append("\nThe veteran's OWN records mention (verbatim excerpts):")
            for ch in chunks[:3]:
                snippet = (getattr(ch, "content", "") or "")[:240].replace("\n", " ")
                if snippet:
                    lines.append(f"  • …{snippet}…")
        return "\n".join(lines)

    async def explain(
        self, db: "AsyncSession", dossier: "VeteranDossier", seed: dict, grounding: dict
    ) -> Finding:
        """Build the Finding for one seed. Mirrors briefing.build_briefing:
        best-effort local-LLM enrichment gated by _LANE_BLOCK, ALWAYS falling
        back to the deterministic seed note. Never raises."""
        finding = self._base_finding(seed, grounding)
        if not self.llm_enrich:
            return finding  # deterministic specialist — no model call
        try:
            facts = self._facts(dossier, seed, grounding)
            raw = await gateway.complete(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": "The established finding and its grounding:\n\n" + facts},
                ],
                temperature=0.3,
                max_tokens=400,
            )
            body = _extract_body(raw)
            if not body:
                return finding
            # Local output-side legal-lane gate (same one the briefing uses).
            if _LANE_BLOCK.search(body):
                log.warning(
                    "firm/%s: enrichment rejected (legal-lane phrase %r) — using seed note.",
                    self.name, _LANE_BLOCK.search(body).group(0),
                )
                return finding
            finding.body = body.strip()[:1200]
            finding.enriched = True
            return finding
        except Exception:  # noqa: BLE001 — enrichment is a bonus, never a blocker
            log.warning("firm/%s: enrichment failed — using deterministic seed note.", self.name, exc_info=True)
            return finding

    def _base_finding(self, seed: dict, grounding: dict) -> Finding:
        """The deterministic Finding for a seed (before any enrichment): the seed
        note IS the body and the always-safe fallback. `confidence` is 1.0 — the
        seed fired; that's the whole graduation contract."""
        reg = seed.get("reg")
        det_body = seed.get("body") or ""
        needs: list[str] = []
        if seed.get("needs_nexus"):
            needs.append("a medical nexus opinion")
        cards = grounding.get("cards") or []
        chunks = grounding.get("chunks") or []
        return Finding(
            specialist=self.name,
            kind=str(seed.get("kind") or ""),
            key=str(seed.get("key") or ""),
            title=str(seed.get("title") or ""),
            body=det_body,
            severity=str(seed.get("severity") or "medium"),
            regs=[reg] if reg else [],
            card_ids=[str(getattr(c, "id", "")) for c in cards if getattr(c, "id", None)],
            evidence_refs=[str(getattr(ch, "id", "")) for ch in chunks if getattr(ch, "id", None)],
            needs=needs,
            suggested_form=seed.get("suggested_form") or seed.get("form"),
            confidence=1.0,
            seed=dict(seed),
            det_body=det_body,
        )

    # ── phase 2b: theory origination ABOVE the floor ─────────────────────────
    async def retrieve_for_theory(
        self, db: "AsyncSession", dossier: "VeteranDossier"
    ) -> dict:
        """Dossier-level grounding for theory origination: VA-law cards + the
        veteran's own record chunks. Best-effort. Default: none (only the opted-in
        TheorySpecialist overrides this with real retrieval)."""
        return {"cards": [], "chunks": []}

    def _theory_facts(self, dossier: "VeteranDossier", grounding: dict) -> str:
        """The dossier + grounding block for theory origination, with the card_id /
        chunk_id of every source EXPOSED so the model can cite them inline."""
        lines: list[str] = ["THE VETERAN'S CLAIM PICTURE (their own entered data):"]
        for c in (dossier.conditions or [])[:20]:
            if not isinstance(c, dict):
                continue
            name = c.get("name") or "(unnamed condition)"
            bits = [f"status={c.get('va_status') or c.get('status') or 'unknown'}"]
            if c.get("diagnostic_code"):
                bits.append(f"DC {c.get('diagnostic_code')}")
            if isinstance(c.get("current_rating"), int):
                bits.append(f"{c['current_rating']}%")
            lines.append(f"  • {name} ({', '.join(bits)})")
        cards = grounding.get("cards") or []
        if cards:
            lines.append("\nVA-LAW REFERENCE CARDS — cite by card_id for any law you rely on:")
            for c in cards[:6]:
                cid = getattr(c, "id", None)
                title = getattr(c, "title", None) or "(untitled)"
                src = getattr(c, "source", None) or ""
                content = (getattr(c, "content", "") or "")[:400].replace("\n", " ")
                lines.append(f"  [card_id={cid}] {title} — {src}: {content}")
        chunks = grounding.get("chunks") or []
        if chunks:
            lines.append("\nTHE VETERAN'S OWN RECORD EXCERPTS — cite by chunk_id for any record fact:")
            for ch in chunks[:6]:
                chid = getattr(ch, "id", None)
                snippet = (getattr(ch, "content", "") or "")[:400].replace("\n", " ")
                lines.append(f"  [chunk_id={chid}] …{snippet}…")
        return "\n".join(lines)

    def _build_theories(
        self, raw: str, grounding: dict, dossier: "VeteranDossier"
    ) -> list[Finding]:
        """Parse the model's proposed theories into layer='theory' Findings. Each
        surviving theory is lane-clean (no guaranteed outcome), invents no number,
        carries a valid VA-register confidence tag, and cites BOTH a real retrieved
        card (law) AND a real retrieved chunk (record) — a citation the model
        fabricated (an id not in the grounding) is dropped, so the reviewer's Check A
        only ever sees resolvable cites. Confidence is CLAMPED into the config band
        so a theory can never present as the deterministic floor (1.0). The persisted
        body is FRAMED with its register level, and the veteran uid rides on the seed
        so the reviewer can RE-RESOLVE the cited chunk ids to that veteran's records."""
        uid = str(getattr(dossier, "uid", "") or "")
        from ..config import settings

        theories = _parse_theories(raw)
        if not theories:
            return []
        card_ids = {str(getattr(c, "id", "")) for c in (grounding.get("cards") or []) if getattr(c, "id", None)}
        chunk_ids = {str(getattr(ch, "id", "")) for ch in (grounding.get("chunks") or []) if getattr(ch, "id", None)}
        reg_by_card = {
            str(getattr(c, "id", "")): (getattr(c, "source", "") or "")
            for c in (grounding.get("cards") or [])
        }
        grounding_text = _grounding_text(grounding)
        lo = float(getattr(settings, "theory_confidence_floor", 0.05))
        hi = float(getattr(settings, "theory_confidence_ceiling", 0.85))

        out: list[Finding] = []
        seen: set[str] = set()
        for t in theories[:4]:
            body = str(t.get("body") or "").strip()
            title = str(t.get("title") or "").strip()
            kind = (str(t.get("kind") or "secondary").strip().lower()) or "secondary"
            level = str(t.get("confidence_level") or "").strip()
            if not body or not title:
                continue
            if level not in _CONFIDENCE_LEVEL_VALUE:  # Check B, enforced at origination too
                continue
            if _LANE_BLOCK.search(body):  # a guaranteed VA outcome — never originate one
                continue
            if not _theory_numbers_grounded(body, grounding_text):  # no invented %/DC
                continue
            # Keep only citations that resolve to a card/chunk actually retrieved.
            cites: list[dict] = []
            law_ok = record_ok = False
            for cit in t.get("citations") or []:
                if not isinstance(cit, dict):
                    continue
                cid = str(cit.get("card_id") or "").strip()
                chid = str(cit.get("chunk_id") or "").strip()
                entry: dict = {}
                if cid and cid in card_ids:
                    entry["card_id"] = cid
                    if reg_by_card.get(cid):
                        entry["reg"] = reg_by_card[cid]
                    law_ok = True
                if chid and chid in chunk_ids:
                    entry["chunk_id"] = chid
                    record_ok = True
                if entry:
                    cites.append(entry)
            if not (law_ok and record_ok):  # Check A, enforced at origination too
                continue
            key = f"theory:{self.name}:{kind}:{_slug(title)}"
            if key in seen:
                continue
            seen.add(key)
            conf = min(hi, max(lo, confidence_for_level(level) or lo))
            severity = (
                "high" if level in ("more_likely_than_not", "at_least_as_likely")
                else "medium" if level == "less_likely_than_not"
                else "low"
            )
            regs = list(dict.fromkeys(e["reg"] for e in cites if e.get("reg")))
            f_card_ids = list(dict.fromkeys(e["card_id"] for e in cites if e.get("card_id")))
            f_chunk_ids = list(dict.fromkeys(e["chunk_id"] for e in cites if e.get("chunk_id")))
            framed = frame_theory_body(body, level)[:1700]
            seed = {
                "key": key, "kind": kind, "title": title[:512], "body": framed,
                "reg": regs[0] if regs else "", "severity": severity, "layer": "theory",
                "confidence_level": level, "citations": cites,
                "needs_nexus": kind == "secondary", "uid": uid,
            }
            out.append(Finding(
                specialist=self.name, kind=kind, key=key, title=title[:512],
                body=framed, severity=severity, regs=regs,
                card_ids=f_card_ids, evidence_refs=f_chunk_ids,
                needs=["a medical nexus opinion"] if kind == "secondary" else [],
                confidence=conf, layer="theory", confidence_level=level,
                citations=cites, seed=seed, det_body="",
            ))
        return out

    async def theorize(
        self, db: "AsyncSession", dossier: "VeteranDossier"
    ) -> list[Finding]:
        """Originate reasoned theories ABOVE the deterministic floor. No-op unless
        origination is enabled in config AND this specialist opts in (can_theorize)
        AND it has LLM enrichment — so a floor-only install (the default) never runs
        it. Best-effort: never raises; returns [] on any failure. Every returned
        Finding is layer='theory' with 0<confidence<1, a VA-register level, and
        resolvable citations."""
        from ..config import settings

        if not (
            getattr(settings, "theory_origination_enabled", False)
            and self.can_theorize
            and self.llm_enrich
        ):
            return []
        try:
            grounding = await self.retrieve_for_theory(db, dossier)
        except Exception:  # noqa: BLE001 — grounding is best-effort
            log.warning("firm/%s: theory grounding failed — no theories.", self.name, exc_info=True)
            return []
        # Nothing to cite → nothing well-founded to originate.
        if not (grounding.get("cards") and grounding.get("chunks")):
            return []
        try:
            raw = await gateway.complete(
                [
                    {"role": "system", "content": self.theory_system_prompt or _THEORY_SYSTEM},
                    {"role": "user", "content": self._theory_facts(dossier, grounding)},
                ],
                temperature=0.3,
                max_tokens=900,
            )
        except Exception:  # noqa: BLE001 — the model call is best-effort
            log.warning("firm/%s: theory model call failed.", self.name, exc_info=True)
            return []
        return self._build_theories(raw, grounding, dossier)

    # ── the two-phase run ────────────────────────────────────────────────────
    async def find(self, db: "AsyncSession", dossier: "VeteranDossier") -> list[Finding]:
        """seed → retrieve → explain per seed (the deterministic FLOOR), then append
        any ORIGINATED theories ABOVE it. Only seeds that fired produce floor
        Findings; theories only appear when origination is enabled and this
        specialist opts in. Never raises — a failing grounding, explain, or theorize
        step degrades gracefully and never sinks the floor."""
        seeds = self.seed(dossier)
        out: list[Finding] = []
        for s in seeds:
            try:
                grounding = await self.retrieve(db, dossier, s) if self.llm_enrich else {"cards": [], "chunks": []}
            except Exception:  # noqa: BLE001
                log.warning("firm/%s: retrieve failed — proceeding ungrounded.", self.name, exc_info=True)
                grounding = {"cards": [], "chunks": []}
            out.append(await self.explain(db, dossier, s, grounding))
        # The theory layer sits ABOVE the floor — appended after it, never replacing
        # it. Wrapped so a theorize failure can never drop the floor findings.
        try:
            out.extend(await self.theorize(db, dossier))
        except Exception:  # noqa: BLE001 — theories are additive, never a blocker
            log.warning("firm/%s: theorize failed — floor unaffected.", self.name, exc_info=True)
        return out
