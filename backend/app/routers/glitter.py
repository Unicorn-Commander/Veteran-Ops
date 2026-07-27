"""Glitter Mane seam — env-level trusted caller.

Valor mints a brigade-style HS256 JWT {sub: email, email, aud: glitter-mane,
exp: +5min} signed with the shared GLITTER_BRIDGE_SECRET and calls the Glitter
Mane REST API for the SAME email. Entirely optional: every endpoint 503s
cleanly when the bridge is unconfigured and the app works fully without it.

GM endpoint shapes (from glitter-mane/backend/app/routers):
  GET /api/conditions → [{id, name, status, diagnosed_on, notes, created_at}]
  GET /api/checkins   → [{id, mood, energy, pain, symptoms, note, created_at}]
  GET /api/labs       → [{id, name, value, unit, reference_range, taken_on, notes, source, confidence}]
  GET /api/vitals     → [{id, type, value, unit, taken_on, notes, source, confidence}]

LEGAL-LANE FIREWALL: this bridge reads ONLY raw, provider/veteran-authored
records — conditions, check-ins, and objective MEASUREMENTS (labs/vitals). It
must NEVER read Glitter Mane's AI-generated fields (imaging `findings`,
`second_opinion`, consult/review text): those are medical interpretations, and
Valor's legal lane forbids surfacing a medical opinion into a claim. The bridge
is GET-only and names each field it consumes, so the firewall is enforced here
by construction — do not add reads of GM's AI surfaces.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, EvidenceItem, User
from ..schemas import GlitterEvidenceImportIn, GlitterImportIn, GlitterStatusOut

log = logging.getLogger("veteran_ops.glitter")

router = APIRouter(prefix="/glitter", tags=["glitter"])

_UNCONFIGURED = HTTPException(
    status.HTTP_503_SERVICE_UNAVAILABLE,
    "Glitter Mane bridge is not configured (set GLITTER_BASE_URL + GLITTER_BRIDGE_SECRET).",
)
_UPSTREAM = HTTPException(
    status.HTTP_503_SERVICE_UNAVAILABLE, "Glitter Mane is not reachable right now."
)


class GlitterBridgeStatusOut(GlitterStatusOut):
    """Superset of the shared schema: `configured` mirrors `enabled` (the spec's
    status wording); schemas.py is BACKEND-CORE-owned so the alias lives here."""

    configured: bool = False


def _mint_token(email: str) -> str:
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {
            "sub": email,
            "email": email,
            "aud": settings.glitter_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.glitter_bridge_secret,
        algorithm="HS256",
    )


async def _user_email(db: AsyncSession, uid: str) -> str:
    user = await db.get(User, uuid.UUID(uid))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user.email


async def _gm_get(email: str, path: str, params: dict | None = None) -> list | dict:
    """Authenticated GET against Glitter Mane. Raises 503 on any transport failure."""
    if not settings.glitter_enabled:
        raise _UNCONFIGURED
    url = f"{settings.glitter_base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {_mint_token(email)}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("Glitter Mane call %s failed: %s", path, exc)
        raise _UPSTREAM from exc


async def fetch_continuity(email: str, condition: str | None = None) -> list[dict]:
    """Check-ins from GM, optionally filtered to entries mentioning the condition.
    Used by /glitter/continuity and the evidence packet. Raises on failure — the
    packet catches and degrades to []."""
    checkins = await _gm_get(email, "/api/checkins")
    rows = checkins if isinstance(checkins, list) else []
    if condition:
        tokens = [t for t in condition.lower().split() if len(t) >= 3]
        if tokens:
            rows = [
                r
                for r in rows
                if any(
                    t in f"{(r.get('symptoms') or '')} {(r.get('note') or '')}".lower()
                    for t in tokens
                )
            ]
    return rows


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.get("/status", response_model=GlitterBridgeStatusOut)
async def glitter_status(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """{configured, reachable} — never 503s; this IS the health probe."""
    if not settings.glitter_enabled:
        return GlitterBridgeStatusOut(
            enabled=False, configured=False, reachable=False, detail="Bridge not configured."
        )
    email = await _user_email(db, uid)
    try:
        await _gm_get(email, "/api/conditions")
        return GlitterBridgeStatusOut(enabled=True, configured=True, reachable=True)
    except HTTPException as exc:
        return GlitterBridgeStatusOut(
            enabled=True, configured=True, reachable=False, detail=str(exc.detail)
        )


@router.get("/conditions")
async def glitter_conditions(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list:
    email = await _user_email(db, uid)
    data = await _gm_get(email, "/api/conditions")
    return data if isinstance(data, list) else []


@router.get("/continuity")
async def glitter_continuity(
    condition: str | None = None,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = await _user_email(db, uid)
    entries = await fetch_continuity(email, condition)
    return {"condition": condition, "checkins": entries, "count": len(entries)}


class GlitterImportOut(BaseModel):
    imported: int
    skipped: list[str] = []
    conditions: list[dict] = []


@router.post("/import-conditions", response_model=GlitterImportOut)
async def import_conditions(
    payload: GlitterImportIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Copy selected GM conditions into claimed_conditions (claim_type='direct',
    status='considering', notes marking the Glitter Mane origin)."""
    email = await _user_email(db, uid)
    gm_rows = await _gm_get(email, "/api/conditions")
    by_id = {str(r.get("id")): r for r in gm_rows if isinstance(r, dict)}

    imported: list[dict] = []
    skipped: list[str] = []
    for cid in payload.condition_ids:
        row = by_id.get(str(cid))
        if row is None:
            skipped.append(str(cid))
            continue
        gm_notes = (row.get("notes") or "").strip()
        note = f"Imported from Glitter Mane (condition {row.get('id')})."
        onset: date | None = None
        if row.get("diagnosed_on"):
            try:
                onset = date.fromisoformat(str(row["diagnosed_on"])[:10])
            except ValueError:
                onset = None
        obj = ClaimedCondition(
            user_id=uuid.UUID(uid),
            name=str(row.get("name") or "Unnamed condition"),
            claim_type="direct",
            status="considering",
            onset_date=onset,
            notes=f"{note} {gm_notes}".strip(),
        )
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        await audit.log(
            db, uid, "condition.import_glitter", entity="claimed_condition",
            entity_id=str(obj.id), meta={"glitter_condition_id": str(cid)},
        )
        imported.append({"id": str(obj.id), "name": obj.name})

    return GlitterImportOut(imported=len(imported), skipped=skipped, conditions=imported)


# ── Objective measurements (labs / vitals) → evidence ────────────────────────
# The VA rating schedule is quantitative — hypertension on diastolic BP, kidney
# on eGFR, diabetes on A1c, respiratory on FEV1. These dated, provider-authored
# measurements are the highest-value severity/continuity evidence a self-help
# tool can surface, and they carry NO medical opinion (see the firewall note in
# the module docstring): only the raw value + reference range cross the bridge.


def _lab_title(row: dict) -> str:
    """A one-line, human-readable evidence title for a GM lab result."""
    name = str(row.get("name") or "Lab result").strip()
    value = str(row.get("value") or "").strip()
    unit = str(row.get("unit") or "").strip()
    ref = str(row.get("reference_range") or "").strip()
    taken = str(row.get("taken_on") or "")[:10]
    parts = name
    if value:
        parts += f": {value}" + (f" {unit}" if unit else "")
    if ref:
        parts += f" (ref {ref})"
    if taken:
        parts += f" — {taken}"
    return parts[:255]


def _vital_title(row: dict) -> str:
    """A one-line evidence title for a GM vital sign (e.g. blood pressure)."""
    vtype = str(row.get("type") or "Vital").replace("_", " ").strip().capitalize()
    value = str(row.get("value") or "").strip()
    unit = str(row.get("unit") or "").strip()
    taken = str(row.get("taken_on") or "")[:10]
    parts = vtype
    if value:
        parts += f": {value}" + (f" {unit}" if unit else "")
    if taken:
        parts += f" — {taken}"
    return parts[:255]


async def _gm_list(email: str, path: str) -> list[dict]:
    data = await _gm_get(email, path)
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


@router.get("/labs")
async def glitter_labs(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Raw lab results from the veteran's Glitter Mane record (read-only)."""
    email = await _user_email(db, uid)
    return await _gm_list(email, "/api/labs")


@router.get("/vitals")
async def glitter_vitals(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Raw vital signs from the veteran's Glitter Mane record (read-only)."""
    email = await _user_email(db, uid)
    return await _gm_list(email, "/api/vitals")


@router.post("/import-evidence", response_model=GlitterImportOut)
async def import_evidence(
    payload: GlitterEvidenceImportIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Attach selected GM labs/vitals to a Valor claimed condition as
    EvidenceItems (kind='treatment_record', status='have', source='Glitter
    Mane'). Provenance is preserved: the origin + any GM confidence is recorded
    in the evidence notes so it's never presented as Valor's own finding."""
    if not (payload.lab_ids or payload.vital_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one measurement to import.")

    # The condition must exist and belong to the caller (RLS also fences this;
    # the explicit check gives a clean 404 instead of a silent no-op).
    try:
        cond_uuid = uuid.UUID(payload.condition_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found.")
    cond = (
        await db.execute(
            select(ClaimedCondition).where(
                ClaimedCondition.id == cond_uuid,
                ClaimedCondition.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if cond is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found.")

    email = await _user_email(db, uid)
    imported: list[dict] = []
    skipped: list[str] = []

    async def _attach(rows: list[dict], ids: list[str], titler, kind_label: str) -> None:
        by_id = {str(r.get("id")): r for r in rows}
        for rid in ids:
            row = by_id.get(str(rid))
            if row is None:
                skipped.append(str(rid))
                continue
            note = f"Imported from Glitter Mane ({kind_label} {row.get('id')})."
            conf = row.get("confidence")
            if conf is not None:
                note += f" Source confidence: {conf}."
            gm_src = (row.get("source") or "").strip()
            if gm_src:
                note += f" Record source: {gm_src}."
            obj = EvidenceItem(
                user_id=uuid.UUID(uid),
                condition_id=cond.id,
                kind="treatment_record",
                title=titler(row),
                status="have",
                source="Glitter Mane",
                notes=note.strip(),
            )
            db.add(obj)
            await db.flush()
            await db.refresh(obj)
            await audit.log(
                db, uid, "evidence.import_glitter", entity="evidence_item",
                entity_id=str(obj.id),
                meta={"glitter_kind": kind_label, "glitter_id": str(rid), "condition_id": str(cond.id)},
            )
            imported.append({"id": str(obj.id), "name": obj.title})

    if payload.lab_ids:
        await _attach(await _gm_list(email, "/api/labs"), payload.lab_ids, _lab_title, "lab")
    if payload.vital_ids:
        await _attach(await _gm_list(email, "/api/vitals"), payload.vital_ids, _vital_title, "vital")

    return GlitterImportOut(imported=len(imported), skipped=skipped, conditions=imported)
