"""Analysis endpoints — the brain, with a hard grounding rule.

  * map-conditions: KB retrieval picks candidate rating-criteria cards; the LLM
    only SELECTS among them and points at a tier — anything it says that is not
    in the retrieved cards' structured data is dropped (app/analysis/mapping.py).
    Degrades to pure retrieval (cards, no tier suggestion) when the gateway is down.
  * secondaries: deterministic keyword match against the KB secondary map; the
    LLM may only add a short personalized sentence per suggestion (skipped
    silently on failure).
  * presumptives: PURE RULES over profile × KB presumptive lists. No LLM.

Every item carries the KB card's `source` cite. Educational tone throughout —
never "you will receive X%".

NOTE: response models extend the shared schemas with additive fields
(card_title / suggested_discussion_tier / caveat, dbq, matched_reason /
conditions). schemas.py is BACKEND-CORE-owned, so the extensions live here.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..analysis.mapping import (
    MAPPING_CAVEAT,
    build_mapping_prompt,
    extract_tiers,
    parse_llm_json,
    validate_selection,
)
from .. import audit
from ..analysis import comprehensive_run as crun
from ..analysis import jobs as analysis_jobs
from ..analysis import file_readiness as filereadiness
from ..analysis import landscape_scan as landscape
from ..analysis import whats_changed as whatschanged
from ..analysis.case import aggregate_mentions, canonicalize_candidates
from ..analysis.presumptives import match_presumptives
from ..analysis.secondaries import match_secondaries
from ..config import settings
from ..crediting import CreditConfig, require_credits
from ..deps import current_user_id, current_workspace_id, get_db
from ..firm.jobs import run_deep_dive_for_user
from ..kb.store import cached_max_ratings, cards_by_type, load_cards, load_secondary_map, retrieve_cards
from ..models import (
    AnalysisJob,
    AnalysisRun,
    CFilePictureCache,
    ClaimedCondition,
    Document,
    EvidenceItem,
    VeteranProfile,
)
from ..schemas import (
    AnalysisMapIn,
    ConditionMappingOut,
    ConditionOut,
    PresumptiveMatchOut,
    RatingTierOut,
    SecondariesIn,
    SecondarySuggestionOut,
)

log = logging.getLogger("veteran_ops.analysis")

router = APIRouter(prefix="/analysis", tags=["analysis"])

_MAX_CONDITIONS = 8  # per-request LLM budget


def _disclaimer() -> str:
    try:
        from ..main import DISCLAIMER

        return DISCLAIMER
    except Exception:  # noqa: BLE001 — main not importable in isolated tests
        return (
            "Rating Raider is self-help educational software, not legal advice and not a "
            "VA-accredited representative. Verify current criteria at eCFR / VA.gov."
        )


# ── Local response models (additive supersets of the shared schemas) ─────────
class MappingItemOut(ConditionMappingOut):
    card_title: str | None = None
    suggested_discussion_tier: int | None = None
    caveat: str = MAPPING_CAVEAT


class MapConditionsOut(BaseModel):
    items: list[MappingItemOut] = Field(default_factory=list)
    disclaimer: str


class SecondaryItemOut(SecondarySuggestionOut):
    dbq: str | None = None


class SecondariesResponseOut(BaseModel):
    items: list[SecondaryItemOut] = Field(default_factory=list)
    disclaimer: str


class PresumptiveItemOut(PresumptiveMatchOut):
    matched_reason: str | None = None
    conditions: list[str] = Field(default_factory=list)


class PresumptivesResponseOut(BaseModel):
    matches: list[PresumptiveItemOut] = Field(default_factory=list)
    disclaimer: str


# ── Helpers ──────────────────────────────────────────────────────────────────
async def _user_conditions(db: AsyncSession) -> list[ClaimedCondition]:
    return list(
        (
            await db.execute(
                select(ClaimedCondition).order_by(ClaimedCondition.created_at)
            )
        ).scalars().all()
    )


async def _profile(db: AsyncSession, uid: str) -> VeteranProfile | None:
    return (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()


# ── GET/POST /analysis/map-conditions ────────────────────────────────────────
def _map_out_from_blob(blob: dict) -> MapConditionsOut:
    items: list[MappingItemOut] = []
    for raw in blob.get("items") or []:
        if not isinstance(raw, dict):
            continue
        tiers_raw = raw.get("tiers") or []
        tiers = [
            RatingTierOut(**t) if isinstance(t, dict) else t
            for t in tiers_raw
            if isinstance(t, dict)
        ]
        items.append(
            MappingItemOut(
                name=raw.get("name") or "",
                diagnostic_code=raw.get("diagnostic_code"),
                body_system=raw.get("body_system"),
                tiers=tiers,
                under_rated=bool(raw.get("under_rated")),
                rationale=raw.get("rationale"),
                source=raw.get("source") or "",
                card_title=raw.get("card_title"),
                suggested_discussion_tier=raw.get("suggested_discussion_tier"),
                caveat=raw.get("caveat") or MAPPING_CAVEAT,
            )
        )
    return MapConditionsOut(
        items=items,
        disclaimer=blob.get("disclaimer") or _disclaimer(),
    )


@router.get("/map-conditions", response_model=MapConditionsOut)
async def get_map_conditions(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the **saved** rating-floor mapping for the current conditions set.

    Does not run the model or charge credits. Empty items when never run (or
    conditions changed since the last map).
    """
    from ..analysis import map_conditions as mapmod

    conditions = await _user_conditions(db)
    chash = mapmod.conditions_facts_hash(conditions)
    cached = await mapmod.get_cached_map(db, uid, chash)
    if not cached:
        return MapConditionsOut(items=[], disclaimer=_disclaimer())
    return _map_out_from_blob(cached)


@router.post("/map-conditions", response_model=MapConditionsOut)
async def map_conditions(
    payload: AnalysisMapIn,
    background: BackgroundTasks,
    force: bool = Query(False, description="Recompute even if a saved map exists"),
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Map conditions to VA rating-schedule floors.

    By default returns the **cached** result for the current conditions set
    (no credit). Set ``force=true`` (or first run) to compute and save.
    Comprehensive analysis also runs and saves this mapping.
    """
    from ..analysis import map_conditions as mapmod

    conditions = await _user_conditions(db)
    chash = mapmod.conditions_facts_hash(conditions)
    if not force:
        cached = await mapmod.get_cached_map(db, uid, chash)
        if cached is not None:
            return _map_out_from_blob(cached)

    await require_credits(
        db,
        uid,
        -CreditConfig.analysis_map_conditions,
        operation="analysis.map_conditions",
        reference_type="analysis",
        reference_id="map-conditions",
    )
    names = [n.strip() for n in payload.names if n.strip()] or None
    if names:
        names = names[:_MAX_CONDITIONS]
    blob = await mapmod.run_map_conditions(
        db, uid, names=names, force=True, conditions=conditions
    )

    if settings.deep_dive_on_analysis:
        background.add_task(
            run_deep_dive_for_user,
            uid,
            workspace_id,
            trigger="analysis",
            force=False,
        )
    return _map_out_from_blob(blob)


# ── POST /analysis/secondaries ───────────────────────────────────────────────
@router.post("/secondaries", response_model=SecondariesResponseOut)
async def secondaries(
    payload: SecondariesIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await require_credits(
        db,
        uid,
        -CreditConfig.analysis_secondaries,
        operation="analysis.secondaries",
        reference_type="analysis",
        reference_id="secondaries",
    )
    conditions = await _user_conditions(db)
    names = [n.strip() for n in payload.names if n.strip()] or [c.name for c in conditions]
    # Suggestions already claimed are filtered against EVERY known condition name.
    known = list(dict.fromkeys(names + [c.name for c in conditions]))

    matched = match_secondaries(known, load_secondary_map())
    # Keep only suggestions whose primary is in the requested name set.
    req = {n.lower() for n in names}
    matched = [m for m in matched if m["primary"].lower() in req]

    # LLM garnish: ONE short personalized sentence per suggestion — deterministic
    # core untouched; skipped silently on any failure.
    if matched:
        try:
            from ..llm.gateway import gateway

            listing = json.dumps(
                [{"i": i, "primary": m["primary"], "secondary": m["secondary"]}
                 for i, m in enumerate(matched)]
            )
            raw = await gateway.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You write ONE short educational sentence per item telling a "
                            "veteran what to bring up with their medical provider about a "
                            "possible secondary condition — you may explain why the causal "
                            "link is plausible. Never GUARANTEE a VA outcome. Reply with "
                            'strict JSON only: {"notes": ["<sentence for i=0>", ...]} in '
                            "input order."
                        ),
                    },
                    {"role": "user", "content": listing},
                ],
                temperature=0.3,
                max_tokens=768,
            )
            parsed = parse_llm_json(raw) or {}
            notes = parsed.get("notes")
            if isinstance(notes, list):
                for i, m in enumerate(matched):
                    if i < len(notes) and isinstance(notes[i], str) and notes[i].strip():
                        note = notes[i].strip()
                        # Outcome-guarantee gate for the garnish: the educational
                        # sentence may explain why a link is plausible, but must never
                        # promise a GUARANTEED VA outcome (VA decides). It only augments a
                        # curated, attributed link, so fabricated facts aren't the risk here.
                        if _GARNISH_BLOCK.search(note):
                            log.warning("Secondaries garnish rejected (guaranteed-outcome claim): %r", note)
                            continue
                        m["rationale"] = f"{m['rationale']} {note}"
        except Exception:  # noqa: BLE001 — garnish only, never required
            log.warning("secondaries rationale garnish failed", exc_info=True)

    items = [SecondaryItemOut(**m) for m in matched]
    return SecondariesResponseOut(items=items, disclaimer=_disclaimer())


# Share the app's single guaranteed-outcome pattern so the two gates can't drift — the
# garnish previously missed contractions, "going to", present-tense verbs, and idioms
# that the hardened _LANE_BLOCK now catches. The note only augments a curated,
# attributed secondary-condition link, so the no-guaranteed-outcome guard is the right
# check here.
from ..strategy.briefing import _LANE_BLOCK as _GARNISH_BLOCK  # noqa: E402


# ── GET /analysis/presumptives ───────────────────────────────────────────────
_PROGRAM_LABELS = {
    "pact_burn_pits": "PACT Act — burn pits / airborne hazards",
    "agent_orange": "Agent Orange / herbicide exposure",
    "gulf_war": "Gulf War illness (§3.317)",
    "camp_lejeune": "Camp Lejeune contaminated water",
    "radiation": "Radiation-exposed veterans",
    "chronic_one_year": "Chronic diseases within 1 year of separation",
}


@router.get("/presumptives", response_model=PresumptivesResponseOut)
async def presumptives(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """RULE-BASED presumptive screen: profile service periods + exposures × the
    KB presumptive lists. No LLM anywhere in this path."""
    profile = await _profile(db, uid)
    profile_dict = (
        {
            "service_periods": profile.service_periods or [],
            "exposures": profile.exposures or {},
        }
        if profile
        else {}
    )

    rows = await cards_by_type(db, "presumptive")
    if rows:
        cards = [
            {"title": r.title, "source": r.source, "data": r.data} for r in rows
        ]
    else:  # corpus not seeded yet — authored files are the same data
        cards = [c for c in load_cards() if c.get("card_type") == "presumptive"]

    # Condition names gate ALS (§3.318) so 90+ service days alone never spam.
    cond_rows = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == uuid.UUID(uid))
            .order_by(ClaimedCondition.created_at)
        )
    ).scalars().all()
    condition_names = [c.name for c in cond_rows if c.name]
    matches = match_presumptives(
        profile_dict, cards, condition_names=condition_names
    )
    out = [
        PresumptiveItemOut(
            condition=m["title"],
            program=_PROGRAM_LABELS.get(m["program"], m["program"] or m["title"]),
            rationale=(
                m["matched_reason"]
                + " If you have a diagnosis on this program's list, presumptive service "
                "connection may apply — no nexus opinion needed, just the diagnosis "
                "plus qualifying service. Verify eligibility details with an "
                "accredited VSO."
            ),
            source=m["source"],
            matched_reason=m["matched_reason"],
            conditions=m["conditions"],
        )
        for m in matches
    ]
    return PresumptivesResponseOut(matches=out, disclaimer=_disclaimer())


# ── Build a CASE from uploaded records ───────────────────────────────────────
# The bridge from "documents were read" to "here's your situation": aggregate the
# conditions the veteran's own records mention, group the synonyms, and let them
# confirm which to add as claimed conditions — which then power the Game Plan.


class CaseCandidateOut(BaseModel):
    name: str
    aliases: list[str]
    mention_count: int
    document_ids: list[str]
    diagnostic_code: str | None = None
    body_system: str | None = None
    claim_type: str = "direct"
    note: str | None = None
    already_claimed: bool = False


class CaseCandidatesOut(BaseModel):
    candidates: list[CaseCandidateOut]
    documents_scanned: int
    distinct_mentions: int
    existing_conditions: int
    disclaimer: str


class CaseCandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    diagnostic_code: str | None = Field(default=None, max_length=8)
    body_system: str | None = Field(default=None, max_length=64)
    claim_type: str = "direct"
    note: str | None = Field(default=None, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)


class BuildCaseIn(BaseModel):
    candidates: list[CaseCandidateIn] = Field(default_factory=list)
    link_evidence: bool = True
    #: When true, after a successful build attempt, best-effort enqueue the
    #: durable comprehensive analysis job (same path as POST /comprehensive/start).
    #: Failures to start analysis never fail the build response.
    start_comprehensive: bool = False


class BuildCaseOut(BaseModel):
    created: list[ConditionOut]
    skipped_existing: list[str]
    evidence_linked: int
    comprehensive_started: bool = False
    comprehensive_run_id: str | None = None


_DOC_KIND = {
    "rating_decision": "other", "decision_letter": "other", "str": "service_record",
    "dbq": "dbq", "treatment_record": "treatment_record",
    "private_medical_opinion": "nexus_letter",
    "lay_statement": "lay_statement", "service_record": "service_record", "other": "other",
}

# Document types that can genuinely establish a CURRENT diagnosis. A rating
# decision / decision letter that grants a condition establishes current
# disability; dbq / treatment_record / private medical opinion / str are clinical records. A lay/buddy
# statement or bare service_record is NEVER clinical — the legal lane forbids
# inferring a diagnosis from it (this app organizes evidence; it is not a doctor).
CLINICAL_DOC_TYPES = {
    "treatment_record", "private_medical_opinion", "dbq",
    "rating_decision", "decision_letter", "str",
}
# Which clinical record to cite first when several name the condition — the
# strongest evidence of a current disability leads.
_DIAGNOSIS_DOC_PRIORITY = (
    "rating_decision", "decision_letter", "private_medical_opinion",
    "dbq", "treatment_record", "str",
)


def _best_diagnosis_doc(docs: list[Document]) -> Document | None:
    """Pick the strongest CLINICAL source document to cite as establishing a
    current diagnosis, or None if none of `docs` is a clinical record.

    Prefers by `_DIAGNOSIS_DOC_PRIORITY`, then the most recent `doc_date`
    (records with no date sort last within a priority band). LEGAL LANE: only
    genuine clinical/decision records qualify — a lay/buddy statement or bare
    service_record can never establish a diagnosis here."""
    clinical = [d for d in docs if d.doc_type in CLINICAL_DOC_TYPES]
    if not clinical:
        return None

    def _rank(d: Document) -> tuple:
        try:
            pri = _DIAGNOSIS_DOC_PRIORITY.index(d.doc_type)
        except ValueError:  # clinical but unranked — after the known types
            pri = len(_DIAGNOSIS_DOC_PRIORITY)
        dated = d.doc_date is not None
        # dated before undated; within that, most recent first (negated ordinal).
        return (pri, 0 if dated else 1, -(d.doc_date.toordinal() if dated else 0))

    return sorted(clinical, key=_rank)[0]


def _diagnosis_evidence(
    user_uuid: uuid.UUID, condition_id: uuid.UUID, doc: Document
) -> EvidenceItem:
    """Build a 'have' diagnosis EvidenceItem auto-identified from a clinical
    record. Framed honestly: it says an uploaded record NAMES the condition and
    asks the veteran to confirm it reflects a CURRENT diagnosis (old records may
    not). It is a normal, fully-editable evidence item and never asserts VA will
    accept it."""
    dated = f" dated {doc.doc_date}" if doc.doc_date else ""
    return EvidenceItem(
        user_id=user_uuid,
        condition_id=condition_id,
        kind="diagnosis",
        status="have",
        title=f"Diagnosis noted in {doc.title or doc.filename}"[:255],
        source="Uploaded record",
        file_ref=doc.file_ref,
        notes=(
            "Auto-identified from your uploaded record" + dated
            + " — confirm this reflects a CURRENT diagnosis. Editable."
        ),
    )


async def _ready_docs_with_mentions(db: AsyncSession, user_uuid: uuid.UUID) -> list[Document]:
    return list(
        (
            await db.execute(
                select(Document).where(
                    Document.user_id == user_uuid, Document.status == "ready"
                )
            )
        ).scalars().all()
    )


@router.get("/case-candidates", response_model=CaseCandidatesOut)
async def case_candidates(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
    enrich: bool = Query(
        False,
        description=(
            "When true, run the local LLM grouping pass (uses GPU/credits). "
            "Default false is deterministic alias-collapse only — free and instant."
        ),
    ),
):
    """Conditions the veteran's OWN uploaded records name, grouped into clean
    candidates to confirm. Organizes what their documents already say — it never
    invents a condition and nothing is claimed until they build the case.

    Default is deterministic (no LLM): navigating here or a first click must not
    spin the GPU. Pass enrich=true for the optional LLM synonym merge.
    """
    from ..analysis.case import deterministic_candidates

    if enrich:
        await require_credits(
            db,
            uid,
            -CreditConfig.analysis_case_candidates,
            operation="analysis.case_candidates",
            reference_type="analysis",
            reference_id="case-candidates",
        )
    user_uuid = uuid.UUID(uid)
    docs = await _ready_docs_with_mentions(db, user_uuid)
    agg = aggregate_mentions(docs)
    if enrich:
        candidates = await canonicalize_candidates(agg)
    else:
        candidates = deterministic_candidates(agg)

    existing = {
        _norm_name(c.name)
        for c in (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
            )
        ).scalars().all()
    }
    out = [
        CaseCandidateOut(**c, already_claimed=_norm_name(c["name"]) in existing)
        for c in candidates
    ]
    return CaseCandidatesOut(
        candidates=out,
        documents_scanned=len(docs),
        distinct_mentions=len(agg),
        existing_conditions=len(existing),
        disclaimer=(
            "These are conditions your own uploaded records mention, grouped for "
            "you to review. Nothing is claimed or filed — you choose what to add, "
            "and an accredited VSO can help you decide."
            + (
                " (AI grouping applied.)"
                if enrich
                else " (Fast scan — alias grouping only; optional AI grouping available.)"
            )
        ),
    )


def _norm_name(name: str) -> str:
    return " ".join((name or "").lower().split()).strip(" .,:;")


async def _try_enqueue_comprehensive(
    db: AsyncSession,
    uid: str,
    workspace_id: str,
    *,
    idempotency_key: str | None = None,
) -> AnalysisRun | None:
    """Best-effort enqueue of the durable comprehensive job.

    Mirrors POST /comprehensive/start but never raises to the caller — used by
    build-case opt-in so a failed analysis start cannot undo a successful case
    build. Returns the AnalysisRun when enqueued (or an already-active run), else
    None when prerequisites fail or enqueue is impossible.
    """
    try:
        digest = analysis_jobs.idempotency_digest(uid, workspace_id, idempotency_key)
    except ValueError:
        log.warning("build-case: invalid comprehensive idempotency key — skip start")
        return None
    user_uuid = uuid.UUID(uid)
    workspace_uuid = uuid.UUID(workspace_id)

    existing_job = (
        await db.execute(
            select(AnalysisJob).where(
                AnalysisJob.user_id == user_uuid,
                AnalysisJob.workspace_id == workspace_uuid,
                AnalysisJob.idempotency_key == digest,
            )
        )
    ).scalar_one_or_none()
    if existing_job is None:
        existing_job = (
            await db.execute(
                select(AnalysisJob)
                .where(
                    AnalysisJob.user_id == user_uuid,
                    AnalysisJob.workspace_id == workspace_uuid,
                    AnalysisJob.status.in_(analysis_jobs.ACTIVE_STATUSES),
                )
                .order_by(AnalysisJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if existing_job is not None:
        existing_run = await db.get(AnalysisRun, existing_job.run_id)
        if existing_run is not None:
            return existing_run

    prereq = await _comprehensive_prerequisites(db, uid)
    if not prereq.ready:
        log.info(
            "build-case: comprehensive not started (prerequisites incomplete): %s",
            [m.key for m in prereq.missing],
        )
        return None

    run = AnalysisRun(
        user_id=user_uuid,
        workspace_id=workspace_uuid,
        status="queued",
        idempotency_key=digest,
        steps=crun.seed_steps(),
        max_attempts=max(1, settings.analysis_job_max_attempts),
    )
    try:
        async with db.begin_nested():
            db.add(run)
            await db.flush()
            db.add(
                AnalysisJob(
                    run_id=run.id,
                    user_id=user_uuid,
                    workspace_id=workspace_uuid,
                    idempotency_key=digest,
                    status="queued",
                    max_attempts=max(1, settings.analysis_job_max_attempts),
                    run_synced_at=analysis_jobs.utcnow(),
                )
            )
            await db.flush()
    except IntegrityError:
        winner = (
            await db.execute(
                select(AnalysisJob)
                .where(
                    AnalysisJob.user_id == user_uuid,
                    AnalysisJob.workspace_id == workspace_uuid,
                    (AnalysisJob.idempotency_key == digest)
                    | AnalysisJob.status.in_(analysis_jobs.ACTIVE_STATUSES),
                )
                .order_by(AnalysisJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if winner is None:
            return None
        return await db.get(AnalysisRun, winner.run_id)

    await db.refresh(run)
    await audit.log(
        db, uid, "analysis.comprehensive.start",
        entity="analysis_run", entity_id=str(run.id),
        meta={"source": "build_case"},
    )
    return run


@router.post("/build-case", response_model=BuildCaseOut)
async def build_case(
    payload: BuildCaseIn,
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Turn confirmed candidates into claimed conditions (status 'considering'),
    optionally linking their source documents as 'have' evidence so the Game Plan
    reflects what the veteran already holds. Existing conditions (same name) are
    skipped, so this is safe to re-run. When ``start_comprehensive`` is true,
    best-effort enqueue the full analysis after the build (never fails the build)."""
    user_uuid = uuid.UUID(uid)
    existing = {
        _norm_name(c.name): c
        for c in (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
            )
        ).scalars().all()
    }
    # Source documents (for evidence linking), fetched once and RLS-fenced.
    docs_by_id = {
        str(d.id): d for d in await _ready_docs_with_mentions(db, user_uuid)
    }

    created: list[ClaimedCondition] = []
    skipped: list[str] = []
    evidence_linked = 0
    for cand in payload.candidates:
        key = _norm_name(cand.name)
        if not key or key in existing:
            skipped.append(cand.name)
            continue
        ct = cand.claim_type if cand.claim_type in ("direct", "secondary", "presumptive") else "direct"
        cond = ClaimedCondition(
            user_id=user_uuid,
            name=cand.name[:255],
            diagnostic_code=cand.diagnostic_code or None,
            body_system=cand.body_system or None,
            claim_type=ct,
            status="considering",
            notes=cand.note or None,
        )
        db.add(cond)
        await db.flush()
        existing[key] = cond
        created.append(cond)

        if payload.link_evidence:
            source_docs: list[Document] = []
            for did in cand.document_ids:
                doc = docs_by_id.get(did)
                if doc is None:
                    continue
                source_docs.append(doc)
                db.add(EvidenceItem(
                    user_id=user_uuid,
                    condition_id=cond.id,
                    kind=_DOC_KIND.get(doc.doc_type, "treatment_record"),
                    title=(doc.title or doc.filename)[:255],
                    status="have",
                    source="Uploaded record",
                    file_ref=doc.file_ref,
                    notes=doc.summary,
                ))
                evidence_linked += 1

            # Also surface a CURRENT-diagnosis item when a genuine clinical source
            # record names this condition. Without it, readiness always reports a
            # missing diagnosis even though the veteran uploaded records that name
            # it (see gaps.py). The condition is brand-new here, so exactly one is
            # added and there is nothing to duplicate.
            dx_doc = _best_diagnosis_doc(source_docs)
            if dx_doc is not None:
                db.add(_diagnosis_evidence(user_uuid, cond.id, dx_doc))
                evidence_linked += 1

    if created:
        await db.flush()
        for cond in created:
            await db.refresh(cond)
        await audit.log(
            db, uid, "case.build", entity="claimed_condition",
            meta={
                "created": len(created),
                "evidence_linked": evidence_linked,
                "start_comprehensive": payload.start_comprehensive,
            },
        )

    comprehensive_started = False
    comprehensive_run_id: str | None = None
    if payload.start_comprehensive:
        try:
            run = await _try_enqueue_comprehensive(
                db, uid, workspace_id,
                idempotency_key=f"build-case:{uid}:{workspace_id}",
            )
            if run is not None:
                comprehensive_started = True
                comprehensive_run_id = str(run.id)
        except Exception:  # noqa: BLE001 — never fail the build on analysis start
            log.warning("build-case: comprehensive start failed", exc_info=True)

    return BuildCaseOut(
        created=[ConditionOut.model_validate(c) for c in created],
        skipped_existing=skipped,
        evidence_linked=evidence_linked,
        comprehensive_started=comprehensive_started,
        comprehensive_run_id=comprehensive_run_id,
    )


# ── Backfill diagnosis evidence for conditions built before this logic ────────
class BackfillOut(BaseModel):
    conditions_updated: int
    evidence_added: int
    skipped_existing: int


@router.post("/backfill-diagnosis-evidence", response_model=BackfillOut)
async def backfill_diagnosis_evidence(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """One-shot backfill for conditions created before diagnosis auto-identification:
    for each condition that has no 'diagnosis' evidence yet, if a genuine CLINICAL
    source record names it, add ONE 'have' diagnosis EvidenceItem so readiness
    reflects the evidence the veteran already holds. Idempotent — conditions that
    already carry a diagnosis item are skipped, so it is safe to re-run.

    LEGAL LANE: the diagnosis item is only created from a clinical/decision record
    (never a lay/buddy statement), is framed as auto-identified + needing the
    veteran's confirmation of a CURRENT diagnosis, and stays fully editable."""
    user_uuid = uuid.UUID(uid)
    conditions = list(
        (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
            )
        ).scalars().all()
    )
    if not conditions:
        return BackfillOut(conditions_updated=0, evidence_added=0, skipped_existing=0)

    # Conditions that already carry a diagnosis item — never double-add.
    have_dx = {
        cid
        for (cid,) in (
            await db.execute(
                select(EvidenceItem.condition_id).where(
                    EvidenceItem.user_id == user_uuid,
                    EvidenceItem.kind == "diagnosis",
                )
            )
        ).all()
    }

    docs = await _ready_docs_with_mentions(db, user_uuid)
    docs_by_id = {str(d.id): d for d in docs}
    # Aggregated mentions → the source document ids for each condition NAME.
    mentions_by_name = {_norm_name(r["name"]): r for r in aggregate_mentions(docs)}

    conditions_updated = 0
    evidence_added = 0
    skipped_existing = 0
    for cond in conditions:
        if cond.id in have_dx:
            skipped_existing += 1
            continue
        row = mentions_by_name.get(_norm_name(cond.name))
        if not row:
            continue
        source_docs = [docs_by_id[did] for did in row["document_ids"] if did in docs_by_id]
        dx_doc = _best_diagnosis_doc(source_docs)
        if dx_doc is None:
            continue
        db.add(_diagnosis_evidence(user_uuid, cond.id, dx_doc))
        conditions_updated += 1
        evidence_added += 1

    if evidence_added:
        await db.flush()
        await audit.log(
            db, uid, "analysis.backfill_diagnosis", entity="evidence_item",
            meta={"conditions_updated": conditions_updated, "evidence_added": evidence_added},
        )
    return BackfillOut(
        conditions_updated=conditions_updated,
        evidence_added=evidence_added,
        skipped_existing=skipped_existing,
    )


# ── Analysis Center — unified "run everything" + status surface ────────────────
# One place the frontend can (1) READ the cached whole-C-file case picture, (2) RUN
# the full analysis on demand, and (3) SEE what already ran automatically. The heavy
# endpoint only ORCHESTRATES: it reuses the strategy helpers (specialist firm +
# local-LLM briefing + forced deep dive) and the intake comprehension trigger, so
# every result caches exactly as its own existing path does. Read endpoints never
# spin the GPU; the run endpoint degrades a dead sub-step to ran.<step>=false and
# never crashes, mirroring how those underlying endpoints already fail safe.


class CasePictureOut(BaseModel):
    status: str  # "ready" | "not_generated"
    generated_at: str | None = None
    picture: dict | None = None


class ComprehensiveRanOut(BaseModel):
    firm: bool
    briefing: bool
    deep_dive: bool
    comprehension: bool


class ComprehensiveSummaryOut(BaseModel):
    conditions: int
    pathways: int
    deep_dive_findings: int
    new_findings: int
    case_picture_ready: bool
    # Enrichment completeness after assemble succeeded. Optional so legacy run
    # rows (pre-quality) still deserialize; durable worker always stamps these.
    quality: str | None = None  # full | partial | minimal
    quality_notes: list[str] = Field(default_factory=list)
    degraded: bool | None = None


class ComprehensiveOut(BaseModel):
    status: str = "complete"
    ran: ComprehensiveRanOut
    summary: ComprehensiveSummaryOut


class AnalysisPrerequisiteItemOut(BaseModel):
    key: str
    label: str
    detail: str
    route: str


class AnalysisPrerequisitesOut(BaseModel):
    ready: bool
    conditions: int
    ready_documents: int
    processing_documents: int
    failed_documents: int
    missing: list[AnalysisPrerequisiteItemOut] = Field(default_factory=list)


class AnalysisStepOut(BaseModel):
    key: str
    label: str
    status: str  # pending | running | complete | failed
    seconds: float | None = None
    detail: str | None = None


class AnalysisRunOut(BaseModel):
    """A backgrounded comprehensive run the UI polls. `steps` carries live per-stage
    status + wall-clock; on completion `ran`/`summary` mirror the synchronous
    ComprehensiveOut, and `total_seconds` is the per-file benchmark."""

    id: str
    status: str  # queued | leased | running | retryable | completed | failed | cancelled
    steps: list[AnalysisStepOut] = Field(default_factory=list)
    ran: ComprehensiveRanOut | None = None
    summary: ComprehensiveSummaryOut | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    total_seconds: float | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    next_attempt_at: str | None = None
    lease_expires_at: str | None = None
    cancel_requested: bool = False
    created_at: str | None = None


class IntakeBenchmarkOut(BaseModel):
    """Approximate cost of the DOCUMENT-INTAKE phase (OCR → cross-read → verify →
    map), derived from each document's created→updated span. Pairs with an
    AnalysisRun's timings to give the full 'timeframe to complete a file'. Marked
    approximate because `updated_at` also moves on later edits (e.g. a reconcile)."""

    documents: int
    ready: int
    failed: int
    processing: int
    duplicates: int = 0
    total_bytes: int
    total_processing_seconds: float | None = None
    wall_clock_seconds: float | None = None
    avg_seconds_per_doc: float | None = None
    first_uploaded_at: str | None = None
    last_ready_at: str | None = None


class DeepDiveAutomationOut(BaseModel):
    last_run: str | None = None
    has_new_findings: bool = False
    auto_on_intake: bool


class ComprehensionAutomationOut(BaseModel):
    available: bool
    generated_at: str | None = None
    auto_on_intake: bool


class VerificationAutomationOut(BaseModel):
    flagged_docs: int
    enabled: bool


class CrossReadAutomationOut(BaseModel):
    disagreement_pages: int


class ReviewQueueAutomationOut(BaseModel):
    pending: int


class AutomationFlagOut(BaseModel):
    key: str
    on: bool
    label: str
    plain: str


class AutomationStatusOut(BaseModel):
    deep_dive: DeepDiveAutomationOut
    comprehension: ComprehensionAutomationOut
    verification: VerificationAutomationOut
    cross_read: CrossReadAutomationOut
    review_queue: ReviewQueueAutomationOut
    automations: list[AutomationFlagOut] = Field(default_factory=list)


async def _comprehensive_prerequisites(
    db: AsyncSession, uid: str
) -> AnalysisPrerequisitesOut:
    """Return the minimum inputs needed for a meaningful whole-file pass."""
    user_id = uuid.UUID(uid)
    conditions = len(
        (
            await db.execute(
                select(ClaimedCondition.id).where(ClaimedCondition.user_id == user_id)
            )
        ).all()
    )
    documents = (
        await db.execute(
            select(Document.status, Document.text_content).where(Document.user_id == user_id)
        )
    ).all()
    ready_documents = sum(
        1 for doc_status, text_content in documents
        if doc_status == "ready" and bool((text_content or "").strip())
    )
    processing_documents = sum(
        1 for doc_status, _ in documents if doc_status in {"uploaded", "processing"}
    )
    failed_documents = sum(
        1 for doc_status, text_content in documents
        if doc_status == "failed" or (doc_status == "ready" and not (text_content or "").strip())
    )
    missing: list[AnalysisPrerequisiteItemOut] = []
    if conditions == 0:
        missing.append(
            AnalysisPrerequisiteItemOut(
                key="conditions",
                label="Add at least one condition",
                detail="A condition tells the analysis what parts of your file to evaluate.",
                route="/conditions",
            )
        )
    if ready_documents == 0:
        if processing_documents:
            detail = (
                f"{processing_documents} record(s) are still being read. Wait for at least one "
                "to finish, then check again."
            )
        elif failed_documents:
            detail = "No readable record is ready yet. Review or reprocess the failed record(s)."
        else:
            detail = "Upload at least one readable service, medical, exam, or decision record."
        missing.append(
            AnalysisPrerequisiteItemOut(
                key="documents",
                label="Add a readable record",
                detail=detail,
                route="/documents",
            )
        )
    return AnalysisPrerequisitesOut(
        ready=not missing,
        conditions=conditions,
        ready_documents=ready_documents,
        processing_documents=processing_documents,
        failed_documents=failed_documents,
        missing=missing,
    )


async def _require_comprehensive_prerequisites(db: AsyncSession, uid: str) -> None:
    prerequisites = await _comprehensive_prerequisites(db, uid)
    if prerequisites.ready:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "analysis_prerequisites",
            "message": "Add the missing case information before starting a comprehensive analysis.",
            "prerequisites": prerequisites.model_dump(),
        },
    )


@router.get("/case-picture", response_model=CasePictureOut)
async def case_picture(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The caller's cached whole-C-file case picture (analysis/comprehension.py's
    build_case_picture output). READ-ONLY: a GET never forces the map-reduce — if no
    picture is cached yet it honestly reports not_generated. Build it by uploading
    (with comprehension-on-intake) or via POST /analysis/comprehensive."""
    row = (
        await db.execute(
            select(CFilePictureCache.payload, CFilePictureCache.created_at)
            .where(CFilePictureCache.user_id == uuid.UUID(uid))
            .order_by(CFilePictureCache.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None or not isinstance(row[0], dict):
        return CasePictureOut(status="not_generated", generated_at=None, picture=None)
    payload, created_at = row[0], row[1]
    # `facts_hash` is the cache key run_comprehension stamps on ABOVE build_case_picture's
    # output; strip it so `picture` is exactly the picture shape (never mutate the cached row).
    picture = {k: v for k, v in payload.items() if k != "facts_hash"}
    return CasePictureOut(
        status="ready",
        generated_at=created_at.isoformat() if created_at else None,
        picture=picture,
    )


@router.get("/comprehensive/prerequisites", response_model=AnalysisPrerequisitesOut)
async def comprehensive_prerequisites(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AnalysisPrerequisitesOut:
    """Explain whether a meaningful whole-file pass can run and what is missing."""
    return await _comprehensive_prerequisites(db, uid)


@router.post("/comprehensive", response_model=ComprehensiveOut)
async def comprehensive(
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Run the FULL analysis in one call: the specialist firm + local-LLM briefing
    (like POST /strategy/refresh), the forced exhaustive deep dive (like POST
    /strategy/deepdive/run), and the whole-C-file comprehension (the intake
    map-reduce — run here even if comprehension-on-intake is off, because THIS is the
    explicit request). Each result caches exactly as its existing path does. A
    sub-step whose gateway is down degrades to ran.<step>=false and never crashes the
    call, mirroring how the underlying endpoints already fail safe."""
    await _require_comprehensive_prerequisites(db, uid)
    from ..analysis import comprehension as comprehension_mod
    from ..routers import strategy as strat
    from ..strategy.briefing import build_briefing

    plan, facts_hash, briefing_args, dossier = await strat._assemble_strategy(db, uid)
    # Snapshot the prior deep dive BEFORE forcing a fresh one, so we can report how
    # many findings are new (the same active-key diff the proactive path computes).
    previous_dive = await strat._latest_deep_dive(db, uid)

    # 1) Local-LLM briefing — mirrors POST /strategy/refresh (build on a facts miss).
    ran_briefing = False
    briefing = await strat._cached_briefing(db, uid, facts_hash)
    if briefing is None:
        try:
            briefing = await build_briefing(**briefing_args)
            await strat._store_briefing(db, uid, facts_hash, briefing)
            ran_briefing = True
        except Exception:  # noqa: BLE001 — enrichment is additive, never a blocker
            log.warning("comprehensive: briefing failed", exc_info=True)
            briefing = None
    else:
        ran_briefing = True
    plan["briefing"] = briefing

    # 2) Specialist firm — mirrors POST /strategy/refresh (run=True). _apply_firm is
    # best-effort (swallows a firm failure); we read the cache back to learn whether
    # it produced findings.
    try:
        await strat._apply_firm(db, uid, dossier, plan, facts_hash, run=True)
    except Exception:  # noqa: BLE001 — belt-and-suspenders; _apply_firm already swallows
        log.warning("comprehensive: firm merge failed", exc_info=True)
    ran_firm = (await strat._cached_firm(db, uid, facts_hash)) is not None

    # 3) Forced exhaustive deep dive — mirrors POST /strategy/deepdive/run. It never
    # raises (degrades to a safe result internally); a real run stamps a generated_at,
    # the empty fallback does not — that is our ran flag.
    deep_dive_result: dict = {}
    try:
        deep_dive_result = await strat._run_cached_deep_dive(
            db, uid, dossier, facts_hash, force=True, trigger="manual"
        )
    except Exception:  # noqa: BLE001 — additive analysis never blocks the call
        log.warning("comprehensive: deep dive failed", exc_info=True)
        deep_dive_result = {}
    ran_deep_dive = bool(deep_dive_result.get("generated_at"))

    # 4) Whole-C-file comprehension — the intake map-reduce, in its OWN RLS-scoped
    # session (its consent-aware PII model resolution + audit release live inside).
    # Run unconditionally (this endpoint IS the explicit request), even when the
    # comprehension-on-intake flag is off. run_comprehension_for_user never raises,
    # but we still guard so an unexpected error only zeroes this one flag.
    try:
        ran_comprehension = await comprehension_mod.run_comprehension_for_user(
            uid, workspace_id, force=True
        )
    except Exception:  # noqa: BLE001 — comprehension is additive, never blocks the call
        log.warning("comprehensive: comprehension failed", exc_info=True)
        ran_comprehension = False

    picture = await comprehension_mod.get_case_picture(db, uid)
    new_findings = len(
        strat._active_finding_keys(deep_dive_result)
        - strat._active_finding_keys(previous_dive)
    )
    from ..analysis.comprehensive_run import classify_run_quality

    ran_map = {
        "firm": bool(ran_firm),
        "briefing": bool(ran_briefing),
        "deep_dive": bool(ran_deep_dive),
        "comprehension": bool(ran_comprehension),
    }
    quality_meta = classify_run_quality(ran_map)
    summary = ComprehensiveSummaryOut(
        conditions=int(
            (plan.get("snapshot") or {}).get("conditions_total") or len(dossier.conditions)
        ),
        pathways=len(plan.get("pathways") or []),
        deep_dive_findings=len(deep_dive_result.get("findings") or []),
        new_findings=new_findings,
        case_picture_ready=picture is not None,
        quality=quality_meta["quality"],
        quality_notes=quality_meta["quality_notes"],
        degraded=quality_meta["degraded"],
    )
    return ComprehensiveOut(
        status="complete",
        ran=ComprehensiveRanOut(
            firm=bool(ran_firm),
            briefing=bool(ran_briefing),
            deep_dive=bool(ran_deep_dive),
            comprehension=bool(ran_comprehension),
        ),
        summary=summary,
    )


def _run_out(run: AnalysisRun) -> AnalysisRunOut:
    summary_out = None
    if run.summary:
        # Tolerate extra keys from older/newer payload shapes; only known fields
        # pass into the response model (quality* are optional for legacy rows).
        raw = dict(run.summary)
        known = {
            "conditions", "pathways", "deep_dive_findings", "new_findings",
            "case_picture_ready", "quality", "quality_notes", "degraded",
        }
        summary_out = ComprehensiveSummaryOut(**{k: raw[k] for k in known if k in raw})
    return AnalysisRunOut(
        id=str(run.id),
        status=run.status,
        steps=[AnalysisStepOut(**s) for s in (run.steps or [])],
        ran=ComprehensiveRanOut(**run.ran) if run.ran else None,
        summary=summary_out,
        error=run.error,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        total_seconds=run.total_seconds,
        attempt_count=run.attempt_count,
        max_attempts=run.max_attempts,
        next_attempt_at=run.next_attempt_at.isoformat() if run.next_attempt_at else None,
        lease_expires_at=run.lease_expires_at.isoformat() if run.lease_expires_at else None,
        cancel_requested=run.cancel_requested_at is not None,
        created_at=run.created_at.isoformat() if run.created_at else None,
    )


@router.post(
    "/comprehensive/start",
    response_model=AnalysisRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def comprehensive_start(
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Durably enqueue the full analysis and return its pollable run immediately."""
    try:
        digest = analysis_jobs.idempotency_digest(uid, workspace_id, idempotency_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    user_uuid = uuid.UUID(uid)
    workspace_uuid = uuid.UUID(workspace_id)

    existing_job = (
        await db.execute(
            select(AnalysisJob).where(
                AnalysisJob.user_id == user_uuid,
                AnalysisJob.workspace_id == workspace_uuid,
                AnalysisJob.idempotency_key == digest,
            )
        )
    ).scalar_one_or_none()
    if existing_job is None:
        existing_job = (
            await db.execute(
                select(AnalysisJob)
                .where(
                    AnalysisJob.user_id == user_uuid,
                    AnalysisJob.workspace_id == workspace_uuid,
                    AnalysisJob.status.in_(analysis_jobs.ACTIVE_STATUSES),
                )
                .order_by(AnalysisJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if existing_job is not None:
        existing_run = await db.get(AnalysisRun, existing_job.run_id)
        if existing_run is not None:
            return _run_out(existing_run)

    # Resolve a retried idempotency key before revalidating mutable prerequisites.
    # Once accepted, the durable enqueue remains the authoritative response even if
    # intake state changes before the client receives and retries that response.
    await _require_comprehensive_prerequisites(db, uid)

    run = AnalysisRun(
        user_id=user_uuid,
        workspace_id=workspace_uuid,
        status="queued",
        idempotency_key=digest,
        steps=crun.seed_steps(),
        max_attempts=max(1, settings.analysis_job_max_attempts),
    )
    try:
        async with db.begin_nested():
            db.add(run)
            await db.flush()
            db.add(
                AnalysisJob(
                    run_id=run.id,
                    user_id=user_uuid,
                    workspace_id=workspace_uuid,
                    idempotency_key=digest,
                    status="queued",
                    max_attempts=max(1, settings.analysis_job_max_attempts),
                    run_synced_at=analysis_jobs.utcnow(),
                )
            )
            await db.flush()
    except IntegrityError:
        winner = (
            await db.execute(
                select(AnalysisJob)
                .where(
                    AnalysisJob.user_id == user_uuid,
                    AnalysisJob.workspace_id == workspace_uuid,
                    (AnalysisJob.idempotency_key == digest)
                    | AnalysisJob.status.in_(analysis_jobs.ACTIVE_STATUSES),
                )
                .order_by(AnalysisJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        winner_run = await db.get(AnalysisRun, winner.run_id) if winner else None
        if winner_run is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "An analysis job was enqueued concurrently; check the latest run.",
            )
        return _run_out(winner_run)
    await db.refresh(run)
    run_id = str(run.id)
    await audit.log(
        db, uid, "analysis.comprehensive.start",
        entity="analysis_run", entity_id=run_id,
    )
    return _run_out(run)


@router.post(
    "/comprehensive/runs/{run_id}/cancel",
    response_model=AnalysisRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def comprehensive_cancel(
    run_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Request cooperative cancellation, fenced to the caller and active workspace."""
    user_uuid = uuid.UUID(uid)
    workspace_uuid = uuid.UUID(workspace_id)
    run = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id,
                AnalysisRun.user_id == user_uuid,
                AnalysisRun.workspace_id == workspace_uuid,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis run not found")
    if run.status in analysis_jobs.TERMINAL_STATUSES or run.status == "complete":
        return _run_out(run)
    job = (
        await db.execute(
            select(AnalysisJob).where(
                AnalysisJob.run_id == run_id,
                AnalysisJob.user_id == user_uuid,
                AnalysisJob.workspace_id == workspace_uuid,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Analysis job metadata is unavailable")
    if job.status in analysis_jobs.TERMINAL_STATUSES:
        # The worker may have completed while this request waited for the row lock.
        # Refresh the earlier snapshot and treat the terminal transition as final.
        await db.refresh(run)
        return _run_out(run)
    now = analysis_jobs.utcnow()
    job.cancel_requested_at = now
    run.cancel_requested_at = now
    if job.status in analysis_jobs.QUEUED_STATUSES:
        job.status = "cancelled"
        job.cancelled_at = now
        run.status = "cancelled"
        run.error = "Analysis cancelled at your request."
        run.finished_at = now
        run.next_attempt_at = None
        job.last_error = run.error
        job.run_synced_at = now
    await audit.log(
        db,
        uid,
        "analysis.comprehensive.cancel",
        entity="analysis_run",
        entity_id=str(run_id),
    )
    await db.flush()
    return _run_out(run)


@router.get("/comprehensive/latest", response_model=AnalysisRunOut | None)
async def comprehensive_latest(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The caller's most recent run (any status), so the UI can resume showing an
    in-flight job or the last result on page load. Null when they've never run one."""
    run = (
        await db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.user_id == uuid.UUID(uid))
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _run_out(run) if run is not None else None


@router.get("/comprehensive/runs", response_model=list[AnalysisRunOut])
async def comprehensive_runs(
    limit: int = 10,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Recent runs, newest first — the per-file benchmark history (timings survive a
    records-reset so cold vs. warm runs can be compared)."""
    rows = (
        await db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.user_id == uuid.UUID(uid))
            .order_by(AnalysisRun.created_at.desc())
            .limit(min(max(limit, 1), 50))
        )
    ).scalars().all()
    return [_run_out(r) for r in rows]


@router.get("/comprehensive/runs/{run_id}", response_model=AnalysisRunOut)
async def comprehensive_run(
    run_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Poll one run's live progress. RLS + an explicit user_id filter fence it to the
    caller; 404 when it isn't theirs or doesn't exist."""
    run = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id,
                AnalysisRun.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis run not found")
    return _run_out(run)


@router.get("/intake-benchmark", response_model=IntakeBenchmarkOut)
async def intake_benchmark(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Approximate document-intake cost (OCR → cross-read → verify → map) derived from
    each document's created→updated span. Pairs with an AnalysisRun's timings to show
    the full 'timeframe to complete a file'. Approximate: `updated_at` also moves on a
    later reconcile, so per-doc seconds can over-count for edited documents."""
    rows = (
        await db.execute(
            select(
                Document.status,
                Document.created_at,
                Document.updated_at,
                Document.size_bytes,
            ).where(Document.user_id == uuid.UUID(uid))
        )
    ).all()
    # Auto-skipped near-duplicates are reported separately and kept OUT of the intake
    # figures — they were never truly processed, so counting them would inflate the
    # "time to complete a file" story with records we deliberately skipped.
    duplicates = sum(1 for r in rows if r[0] == "duplicate")
    real = [r for r in rows if r[0] != "duplicate"]
    total = len(real)
    ready = sum(1 for r in real if r[0] == "ready")
    failed = sum(1 for r in real if r[0] == "failed")
    processing = sum(1 for r in real if r[0] in ("uploaded", "processing"))
    total_bytes = sum(int(r[3] or 0) for r in real)
    # Per-doc processing seconds for docs that reached a terminal state (have a real
    # updated_at delta). Sum = raw compute; wall-clock = first upload → last ready.
    done = [r for r in rows if r[0] in ("ready", "failed") and r[1] and r[2]]
    per_doc = [max((r[2] - r[1]).total_seconds(), 0.0) for r in done]
    total_proc = round(sum(per_doc), 2) if per_doc else None
    avg = round(sum(per_doc) / len(per_doc), 2) if per_doc else None
    uploaded_at = [r[1] for r in rows if r[1]]
    ready_at = [r[2] for r in rows if r[0] == "ready" and r[2]]
    first_up = min(uploaded_at) if uploaded_at else None
    last_ready = max(ready_at) if ready_at else None
    wall = (
        round((last_ready - first_up).total_seconds(), 2)
        if first_up and last_ready and last_ready > first_up
        else None
    )
    return IntakeBenchmarkOut(
        documents=total,
        ready=ready,
        failed=failed,
        processing=processing,
        duplicates=duplicates,
        total_bytes=total_bytes,
        total_processing_seconds=total_proc,
        wall_clock_seconds=wall,
        avg_seconds_per_doc=avg,
        first_uploaded_at=first_up.isoformat() if first_up else None,
        last_ready_at=last_ready.isoformat() if last_ready else None,
    )


# Plain-language copy — one entry per flag the record-level automations key off.
# Kept beside the endpoint so the UI's "what runs for me" list can never drift from
# the flags actually read below.
_AUTOMATION_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("deep_dive_on_intake", "Auto deep-dive on upload",
     "We re-run your full rating analysis automatically whenever new records arrive."),
    ("comprehension_on_intake", "Auto case picture on upload",
     "We rebuild your whole-file case picture automatically once new records are read."),
    ("intake_verify_default", "Double-check every extraction",
     "A second AI pass re-reads each record and flags anything it can't confirm, so a "
     "wrong number never slips in without you seeing it."),
    ("deep_dive_on_rule_change", "Re-analyze when VA rules change",
     "If a rating rule that affects your conditions changes, we re-run your analysis so "
     "your plan stays current."),
    ("deep_dive_on_schedule", "Periodic re-analysis",
     "We periodically re-check your whole file for new opportunities, even when nothing "
     "on your end changed."),
)


@router.get("/automation-status", response_model=AutomationStatusOut)
async def automation_status(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """What ran automatically for this veteran's record: the last proactive deep dive
    (and whether it surfaced anything new), whether the whole-C-file picture is built,
    how many documents the verification / OCR cross-read flagged, the review-queue
    depth, and the plain-language state of each record automation. All RLS-scoped to
    the caller; pure reads — no analysis is triggered here."""
    from ..routers import strategy as strat

    user_uuid = uuid.UUID(uid)

    # Deep dive: the latest cached run across facts hashes + its local notification.
    latest_payload = await strat._latest_firm_payload(db, uid)
    dive = (latest_payload or {}).get("deep_dive") or {}
    notification = (latest_payload or {}).get("notification") or {}
    deep_dive_out = DeepDiveAutomationOut(
        last_run=dive.get("generated_at") or None,
        has_new_findings=bool(notification.get("has_new_findings")),
        auto_on_intake=bool(settings.deep_dive_on_intake),
    )

    # Comprehension: latest cached whole-C-file picture (row created_at = generated_at).
    cp_row = (
        await db.execute(
            select(CFilePictureCache.created_at)
            .where(CFilePictureCache.user_id == user_uuid)
            .order_by(CFilePictureCache.created_at.desc())
            .limit(1)
        )
    ).first()
    comprehension_out = ComprehensionAutomationOut(
        available=cp_row is not None,
        generated_at=(cp_row[0].isoformat() if cp_row and cp_row[0] else None),
        auto_on_intake=bool(settings.comprehension_on_intake),
    )

    # Documents flagged for the veteran's eye. Verification / OCR-cross-read detail
    # only persists on flagged docs (intake/process.py), so scanning that subset is
    # exact — a verify dispute has review.fields/missing_conditions; a two-engine OCR
    # conflict carries review.crossread.pages_flagged.
    flagged_extracts = (
        await db.execute(
            select(Document.extracted).where(
                Document.user_id == user_uuid,
                Document.review_status == "flagged",
            )
        )
    ).scalars().all()
    review_pending = len(flagged_extracts)
    verify_flagged = 0
    crossread_pages = 0
    for extracted in flagged_extracts:
        review = (extracted or {}).get("review") or {}
        if review.get("fields") or review.get("missing_conditions"):
            verify_flagged += 1
        crossread_pages += int((review.get("crossread") or {}).get("pages_flagged") or 0)

    automations = [
        AutomationFlagOut(key=key, on=bool(getattr(settings, key)), label=label, plain=plain)
        for key, label, plain in _AUTOMATION_FLAGS
    ]

    return AutomationStatusOut(
        deep_dive=deep_dive_out,
        comprehension=comprehension_out,
        verification=VerificationAutomationOut(
            flagged_docs=verify_flagged,
            enabled=bool(settings.intake_verify_default),
        ),
        cross_read=CrossReadAutomationOut(disagreement_pages=crossread_pages),
        review_queue=ReviewQueueAutomationOut(pending=review_pending),
        automations=automations,
    )


# ── "What's changed since you were rated" ─────────────────────────────────────────
# Deterministic core (rating date vs. dated regulatory changes matching THIS veteran's
# conditions/exposures) loads freely — no AI, no GPU. The per-change person-specific
# read is a SEPARATE, on-demand POST so opening the page never spins the model.


class WhatsChangedItemOut(BaseModel):
    id: str
    status: str  # "changed" | "proposed"
    effective_date: str
    title: str
    summary: str
    action_hint: str
    source_url: str
    confidence: str
    matched_by: str  # "condition" | "exposure"
    matched_detail: str
    action_signal: str  # "review" | "watch" | "check_eligibility"


class WhatsChangedOut(BaseModel):
    rating_date: str | None = None
    rating_date_source: str | None = None
    needs_rating_date: bool = False
    items: list[WhatsChangedItemOut] = Field(default_factory=list)


class AssessOut(BaseModel):
    assessment: str  # plain-language person-specific read; "" if the model was unavailable


def _whats_changed_item(m: whatschanged.ChangeMatch) -> WhatsChangedItemOut:
    c = m.change
    return WhatsChangedItemOut(
        id=c.id, status=c.status, effective_date=c.effective_date, title=c.title,
        summary=c.summary, action_hint=c.action_hint, source_url=c.source_url,
        confidence=c.confidence, matched_by=m.matched_by, matched_detail=m.matched_detail,
        action_signal=m.action_signal,
    )


@router.get("/whats-changed", response_model=WhatsChangedOut)
async def whats_changed(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """VA regulatory changes that took effect AFTER this veteran was last rated and that
    touch their claimed conditions or service exposures. Pure DB + date math — the facts
    (what changed, when, the source) are curated, never model-generated. `needs_rating_date`
    is true when no rating document is on file to anchor the comparison."""
    result = await whatschanged.find_changes(db, uid)
    return WhatsChangedOut(
        rating_date=result["rating_date"],
        rating_date_source=result["rating_date_source"],
        needs_rating_date=result["rating_date"] is None,
        items=[_whats_changed_item(m) for m in result["matches"]],
    )


@router.post("/whats-changed/{change_id}/assess", response_model=AssessOut)
async def whats_changed_assess(
    change_id: str,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """On-demand PERSON-SPECIFIC read of one surfaced change (the only AI step — local
    model, PII stays on-fleet). Rebuilds the match for `change_id`, assembles this
    veteran's own condition context, and asks the model whether there's plausibly enough
    to act + what evidence to gather. 404 if the change doesn't currently apply to them."""
    result = await whatschanged.find_changes(db, uid)
    match = next((m for m in result["matches"] if m.change.id == change_id), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That change doesn't apply to your record.")
    # Person-specific context from the veteran's OWN matched conditions (no PII beyond
    # what the veteran already entered; the call is forced local when privacy mode is on).
    dcs = set(match.change.diagnostic_codes)
    conds = list(
        (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == uuid.UUID(uid))
            )
        ).scalars()
    )
    relevant = [c for c in conds if (c.diagnostic_code or "").strip() in dcs] or conds
    parts = []
    for c in relevant[:5]:
        bits = [c.name]
        if c.diagnostic_code:
            bits.append(f"DC {c.diagnostic_code}")
        if c.current_rating is not None:
            bits.append(f"rated {c.current_rating}%")
        if c.va_status and c.va_status != "unknown":
            bits.append(c.va_status.replace("_", " "))
        if c.nexus_notes:
            bits.append(f"nexus: {c.nexus_notes[:200]}")
        parts.append(" — ".join(bits))
    context = "; ".join(parts) if parts else "no conditions recorded yet"
    assessment = await whatschanged.assess_actionability(match, context)
    return AssessOut(assessment=assessment)


# ── Deep landscape scan (model-suggested leads BEYOND the curated map) ─────────────
# The one agent that uses the model's own medical knowledge rather than cited cards, so
# its output is framed strictly as LEADS to research with a provider — never facts or a
# claim of qualification. On-demand (no model runs on page load). Local model by default;
# under privacy mode the call is forced local (it sends only condition names, not records).


class LandscapeLeadOut(BaseModel):
    secondary: str
    primary: str
    mechanism: str
    strength: str  # well_documented | plausible | emerging
    discuss: str


class LandscapeScanOut(BaseModel):
    leads: list[LandscapeLeadOut] = Field(default_factory=list)
    disclaimer: str


@router.post("/landscape-scan", response_model=LandscapeScanOut)
async def landscape_scan_endpoint(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Surface plausible secondary-connection LEADS beyond the curated map, using the
    model's medical knowledge. Excludes connections the curated system already surfaces
    for this veteran. Educational hypotheses to discuss with a provider — never claims."""
    await require_credits(
        db, uid, -CreditConfig.analysis_secondaries,
        operation="analysis.landscape_scan",
        reference_type="analysis", reference_id="landscape-scan",
    )
    conditions = await _user_conditions(db)
    names = [c.name for c in conditions]
    known = (
        [m["secondary"] for m in match_secondaries(names, load_secondary_map())] if names else []
    )
    leads = await landscape.scan_landscape(db, uid, known_secondaries=known)
    return LandscapeScanOut(
        leads=[
            LandscapeLeadOut(
                secondary=l.secondary, primary=l.primary, mechanism=l.mechanism,
                strength=l.strength, discuss=l.discuss,
            )
            for l in leads
        ],
        disclaimer=(
            "These are model-suggested medical leads to research with your doctor or a VSO "
            "— not established facts, and not a claim that you qualify for anything. Your "
            "cited, established secondary connections are on the Secondaries page."
        ),
    )


# ── File-readiness delta ("what do I still need to file?") ────────────────────────
# Deterministic aggregation of the per-condition gap engine — no AI, safe on every load.


class FileReadinessNeedOut(BaseModel):
    label: str
    detail: str
    how: str
    route: str
    kind: str
    conditions: list[str] = Field(default_factory=list)


class FileReadinessConditionOut(BaseModel):
    condition_id: str
    name: str
    ready: bool
    still_needs: list[str] = Field(default_factory=list)


class FileReadinessBlockerOut(BaseModel):
    label: str
    route: str
    how: str


class FileReadinessHandoffOut(BaseModel):
    """Static pro-se handoff destinations — we prepare the packet; veteran/VSO files."""
    va_gov_claim_url: str
    vso_url: str
    itf_url: str
    form526_route: str
    packet_note: str


class FileReadinessOut(BaseModel):
    total_conditions: int
    ready_conditions: int
    all_ready: bool
    has_conditions: bool
    still_needed: list[FileReadinessNeedOut] = Field(default_factory=list)
    per_condition: list[FileReadinessConditionOut] = Field(default_factory=list)
    file_ready_score: int = 0
    blockers: list[FileReadinessBlockerOut] = Field(default_factory=list)
    handoff: FileReadinessHandoffOut
    disclaimer: str


@router.get("/file-readiness", response_model=FileReadinessOut)
async def file_readiness(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The delta between where the veteran is and a filable claim: what's still needed
    (grouped, prioritized, with where to fix it) + which conditions are ready. Pure rules
    over the gap engine — educational, not a prediction of the VA's decision."""
    from collections import defaultdict

    user_uuid = uuid.UUID(uid)
    conditions = (
        await db.execute(select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid))
    ).scalars().all()
    ev_by_cond: dict[str, list[dict]] = defaultdict(list)
    for e in (
        await db.execute(select(EvidenceItem).where(EvidenceItem.user_id == user_uuid))
    ).scalars():
        ev_by_cond[str(e.condition_id)].append({"kind": e.kind, "status": e.status})
    profile = (
        await db.execute(select(VeteranProfile).where(VeteranProfile.user_id == user_uuid))
    ).scalar_one_or_none()
    prof = (
        {"service_periods": profile.service_periods, "exposures": profile.exposures}
        if profile
        else None
    )
    cond_dicts = [
        {
            "id": str(c.id), "name": c.name, "claim_type": c.claim_type,
            "secondary_to": str(c.secondary_to) if c.secondary_to else None,
            "in_service_event": c.in_service_event, "nexus_notes": c.nexus_notes,
            "diagnostic_code": c.diagnostic_code, "current_rating": c.current_rating,
        }
        for c in conditions
    ]
    result = filereadiness.assemble_file_readiness(
        cond_dicts, ev_by_cond, prof, cached_max_ratings()
    )
    return FileReadinessOut(
        **result,
        disclaimer=(
            "This is a checklist of the core service-connection evidence you've identified "
            "— not a prediction of the VA's decision. A VSO can review it with you for free."
        ),
    )
