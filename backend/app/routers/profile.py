"""Veteran profile — service history, exposures, current combined rating."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .. import audit
from ..deps import current_user_id, current_workspace_id, get_db
from ..intake.identity_extract import merge_identity_suggestions
from ..models import Document, User, VeteranProfile
from ..schemas import (
    IdentitySuggestionsOut,
    LocationSuggestionsOut,
    ProfileIn,
    ProfileOut,
    SimpleMessage,
)

log = logging.getLogger("veteran_ops.profile")

router = APIRouter(prefix="/profile", tags=["profile"])


async def _reextract_identity_task(uid: str, wsid: str | None) -> None:
    """Re-run best-effort identity extraction over the veteran's OWN ready documents
    and refresh the non-destructive `extracted['identity_suggestion']` on each. Its
    own RLS-scoped session (background tasks never reuse the request session). SSN is
    never collected (intake/identity_extract.py); a failure never surfaces."""
    from ..db import session_for_user
    from ..intake.identity_extract import extract_identity

    try:
        async with asynccontextmanager(session_for_user)(uid, wsid) as db:
            docs = (
                await db.execute(
                    select(Document).where(
                        Document.user_id == uuid.UUID(uid), Document.status == "ready"
                    )
                )
            ).scalars().all()
            for doc in docs:
                text = doc.text_content or ""
                if not text.strip():
                    continue
                try:
                    sugg = await extract_identity(text, (doc.extracted or {}).get("doc_type") or doc.doc_type)
                except Exception:  # noqa: BLE001 — one doc must not sink the sweep
                    continue
                if sugg:
                    extracted = dict(doc.extracted or {})
                    extracted["identity_suggestion"] = sugg
                    doc.extracted = extracted
                    flag_modified(doc, "extracted")
            await db.commit()
    except Exception:  # noqa: BLE001 — a background convenience, never fatal
        log.warning("identity re-extract sweep failed", exc_info=True)

IDENTITY_SUGGESTION_DISCLAIMER = (
    "We read these from your uploaded records to save you typing. Review every field "
    "and save your profile — nothing here is used until you do."
)


async def _get_or_create(db: AsyncSession, uid: str) -> VeteranProfile:
    user_id = uuid.UUID(uid)
    sel = select(VeteranProfile).where(VeteranProfile.user_id == user_id)
    profile = (await db.execute(sel)).scalar_one_or_none()
    if profile is None:
        # Race-safe: the unique index on user_id guarantees a single profile.
        try:
            async with db.begin_nested():
                profile = VeteranProfile(user_id=user_id)
                db.add(profile)
            await db.refresh(profile)
        except IntegrityError:
            profile = (await db.execute(sel)).scalar_one()
    return profile


@router.get("", response_model=ProfileOut)
async def get_profile(
    uid: str = Depends(current_user_id), db: AsyncSession = Depends(get_db)
) -> VeteranProfile:
    return await _get_or_create(db, uid)


@router.put("", response_model=ProfileOut)
async def put_profile(
    payload: ProfileIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VeteranProfile:
    """Upsert — creates the row if missing. mode='json' so dates land as ISO
    strings in the JSONB columns."""
    profile = await _get_or_create(db, uid)
    for key, value in payload.model_dump(exclude_unset=True, mode="json").items():
        setattr(profile, key, value)
    await db.flush()
    await db.refresh(profile)
    await audit.log(db, uid, "profile.update", entity="veteran_profile", entity_id=str(profile.id))
    return profile


@router.get("/identity-suggestions", response_model=IdentitySuggestionsOut)
async def identity_suggestions(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> IdentitySuggestionsOut:
    """Aggregate the best-effort identity extractions the intake pipeline stashed on
    the veteran's own READY documents into ONE proposed identity + dependents — most
    authoritative (VA decision / DD-214), then most recent, winning per field, with
    the source document noted for each.

    A SUGGESTION surface only: the veteran reviews it and clicks 'Use these' to fill
    the profile form, then saves. Nothing here writes profile.identity, and — by
    construction (intake/identity_extract.py) — NO SSN is ever present. Returns
    has_suggestions=False (and empty fields) when no records yielded anything.

    The `identity_suggestion` blob lives in JSONB; we filter for it in Python so the
    query stays dialect-independent (mirroring documents.decodable_documents)."""
    rows = (
        await db.execute(
            select(Document).where(
                Document.user_id == uuid.UUID(uid),
                Document.status == "ready",
            )
        )
    ).scalars().all()

    entries = [
        {
            "document_id": str(doc.id),
            "title": doc.title,
            "doc_type": doc.doc_type,
            "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "suggestion": suggestion,
        }
        for doc in rows
        if isinstance(suggestion := (doc.extracted or {}).get("identity_suggestion"), dict)
        and suggestion
    ]

    merged = merge_identity_suggestions(entries)
    identity = dict(merged["identity"] or {})
    sources = dict(merged["sources"] or {})

    # Seed from the account when records did not yield a field — email is NEVER
    # extracted from PDFs (by design); name often already lives on User.full_name
    # from SSO/register. Still a SUGGESTION: the veteran must Use these + Save.
    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(uid)))
    ).scalar_one_or_none()
    account_src = {
        "document_id": None,
        "title": "your account",
        "doc_type": None,
        "doc_date": None,
    }
    if user:
        acct_name = (user.full_name or "").strip()
        if acct_name and not (identity.get("full_name") or "").strip():
            identity["full_name"] = acct_name
            sources["full_name"] = account_src
        acct_email = (user.email or "").strip()
        if acct_email and "@" in acct_email and not (identity.get("email") or "").strip():
            identity["email"] = acct_email
            sources["email"] = account_src

    has = bool(identity or merged.get("dependents"))
    return IdentitySuggestionsOut(
        has_suggestions=has,
        identity=identity,
        dependents=merged["dependents"],
        sources=sources,
        disclaimer=IDENTITY_SUGGESTION_DISCLAIMER if has else "",
    )


@router.get("/location-suggestions", response_model=LocationSuggestionsOut)
async def location_suggestions(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> LocationSuggestionsOut:
    """Scan READY document text for known deployment/exposure place names.

    Deterministic keyword match (no LLM). Used to pre-offer chips on Profile
    locations; the veteran still confirms and saves.
    """
    from ..intake.location_suggest import suggest_locations_from_text

    rows = (
        await db.execute(
            select(Document.text_content).where(
                Document.user_id == uuid.UUID(uid),
                Document.status == "ready",
            )
        )
    ).all()
    # Cap total text scanned to keep this cheap on large C-files
    parts: list[str] = []
    budget = 400_000
    for (text,) in rows:
        if not text:
            continue
        chunk = text[:80_000]
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break
    found = suggest_locations_from_text("\n".join(parts))
    return LocationSuggestionsOut(
        locations=found,
        disclaimer=(
            "Places named in your uploaded records. Review and add only those that "
            "apply — nothing is saved until you update and save your profile."
            if found
            else ""
        ),
    )


@router.post("/reextract-identity", response_model=SimpleMessage)
async def reextract_identity(
    background: BackgroundTasks,
    uid: str = Depends(current_user_id),
    wsid: str | None = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> SimpleMessage:
    """Re-scan the veteran's own uploaded records for their identity (name, DOB,
    address, phone, dependents) and refresh GET /profile/identity-suggestions. Runs
    in the background over their READY documents; poll the suggestions endpoint for
    the result. Non-destructive + SSN-free by construction; never writes the profile."""
    await audit.log(db, uid, "profile.reextract_identity")
    background.add_task(_reextract_identity_task, uid, wsid)
    return SimpleMessage(
        ok=True,
        message="Scanning your records — your suggestions will refresh in about a minute.",
    )


@router.post("/apply-ratings-from-records", response_model=dict)
async def apply_ratings_from_records(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply VA decision rating_percent values from READY documents onto claimed
    conditions (create or update current_rating). Optionally set profile
    current_combined_rating via the deterministic §4.25 engine when multiple
    percents exist. Never silent: the veteran must call this (or confirm on
    Documents). SSN-free; educational self-help only.
    """
    from ..models import ClaimedCondition
    from ..rating.engine import RatingEntry, combined_rating

    user_uuid = uuid.UUID(uid)
    docs = (
        await db.execute(
            select(Document).where(
                Document.user_id == user_uuid,
                Document.status == "ready",
            )
        )
    ).scalars().all()

    # name (lower) -> best percent from VA decisions / rating_summary
    found: dict[str, dict] = {}
    for doc in docs:
        extracted = doc.extracted if isinstance(doc.extracted, dict) else {}
        summary = extracted.get("rating_summary") or []
        mentions = extracted.get("conditions_mentioned") or []
        rows = summary if isinstance(summary, list) and summary else mentions
        for m in rows:
            if not isinstance(m, dict):
                continue
            name = (m.get("name") or "").strip()
            pct = m.get("rating_percent")
            if not name or pct is None:
                continue
            try:
                pct_i = int(pct)
            except (TypeError, ValueError):
                continue
            if pct_i < 0 or pct_i > 100:
                continue
            key = " ".join(name.lower().split())
            prev = found.get(key)
            if prev is None or pct_i >= prev["percent"]:
                found[key] = {"name": name, "percent": pct_i, "dc": m.get("diagnostic_code")}

    if not found:
        return {
            "updated": 0,
            "created": 0,
            "combined": None,
            "message": "No rating percentages found in ready VA/decision-style records.",
        }

    existing = {
        " ".join((c.name or "").lower().split()): c
        for c in (
            await db.execute(select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid))
        ).scalars().all()
    }
    updated = 0
    created = 0
    for key, row in found.items():
        cond = existing.get(key)
        if cond:
            cond.current_rating = row["percent"]
            if row.get("dc") and not cond.diagnostic_code:
                cond.diagnostic_code = str(row["dc"])[:16]
            updated += 1
        else:
            cond = ClaimedCondition(
                user_id=user_uuid,
                name=row["name"][:255],
                claim_type="increase",
                status="considering",
                current_rating=row["percent"],
                diagnostic_code=(str(row["dc"])[:16] if row.get("dc") else None),
            )
            db.add(cond)
            existing[key] = cond
            created += 1

    percents = [r["percent"] for r in found.values()]
    combined = None
    if percents:
        try:
            result = combined_rating(
                [RatingEntry(label=f"r{i}", percent=p) for i, p in enumerate(percents)]
            )
            combined = int(result.combined)
        except Exception:  # noqa: BLE001
            combined = max(percents)

    profile = await _get_or_create(db, uid)
    if combined is not None and (
        profile.current_combined_rating is None or profile.current_combined_rating < combined
    ):
        profile.current_combined_rating = combined

    await db.flush()
    await audit.log(
        db,
        uid,
        "profile.apply_ratings_from_records",
        entity="veteran_profile",
        entity_id=str(profile.id),
        meta={"updated": updated, "created": created, "combined": combined},
    )
    return {
        "updated": updated,
        "created": created,
        "combined": combined,
        "message": (
            f"Applied ratings for {updated + created} condition(s)"
            + (f"; combined estimate {combined}% saved to profile." if combined is not None else ".")
        ),
    }
