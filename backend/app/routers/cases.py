"""Org caseload — cases, assignments, consent, notes (Wave 13).

An organization's caseworkers help veterans build their claims. A **case** is one such
veteran; it lives in the ORG workspace (RLS-fenced by workspace_id, so it can NEVER
cross tenants) and is worked by assigned staff.

Authorization, layered outside-in:
- RLS (db.py): the request only ever touches THIS org's rows.
- require_feature('staff_caseload'): the caseload is a team-tier capability.
- Role + caseload scope (rbac.py): admin/owner see & manage the whole caseload; a
  `staff` user sees only cases ASSIGNED to them (a non-member can't reach the caseload).
- Audit (audit.py): every mutation writes an append-only workspace-scoped trail naming
  the acting staff member — the accountability an org (and the veteran) can rely on.

⚖️ Legal lane (load-bearing): a case is the org's file for ASSISTING/organizing a
veteran's claim — educational self-help, the veteran still drives and files. It is NOT
VA power of attorney. Formally representing a veteran before VA requires the org to be
VA-accredited and appointed on VA Form 21-22 / 21-22a; capturing consent here demands
the caseworker affirm they told the veteran that distinction.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import log as audit_log
from ..deps import current_user_id, current_workspace_id, get_db
from ..features import require_feature
from ..rbac import is_manager, require_role
from ..schemas import (
    AssignIn,
    CaseAssigneeOut,
    CaseCreateIn,
    CaseNoteIn,
    CaseNoteOut,
    CaseOut,
    CaseUpdateIn,
    ConsentCaptureIn,
    ConsentOut,
)

router = APIRouter(prefix="/cases", tags=["caseload"])

# Every caseload endpoint requires the team-tier caseload feature on the active org.
_FEATURE = Depends(require_feature("staff_caseload"))


async def _require_org(db: AsyncSession, workspace_id: str) -> None:
    """The caseload only exists inside an ORG workspace — a personal workspace has no
    caseload (and enforcing this keeps a solo veteran's own data out of these tables)."""
    kind = (await db.execute(
        text("SELECT kind FROM organizations WHERE id = CAST(:w AS uuid) LIMIT 1"),
        {"w": workspace_id},
    )).scalar()
    if kind != "org":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The caseload is a team feature. Switch to a team workspace to use it.",
        )


async def _can_see(db: AsyncSession, case_id: str, uid: str, role: str) -> bool:
    """A manager sees any case in the org; a staff user only cases assigned to them."""
    if is_manager(role):
        return True
    hit = (await db.execute(
        text(
            "SELECT 1 FROM case_assignments "
            "WHERE case_id = CAST(:c AS uuid) AND user_id = CAST(:u AS uuid) LIMIT 1"
        ),
        {"c": case_id, "u": uid},
    )).first()
    return hit is not None


async def _load_case(db: AsyncSession, case_id: str) -> dict | None:
    row = (await db.execute(
        text(
            "SELECT id::text AS id, veteran_name, veteran_email, veteran_phone, status, "
            "       consent_status, summary, created_at, updated_at "
            "FROM cases WHERE id = CAST(:c AS uuid) LIMIT 1"
        ),
        {"c": case_id},
    )).mappings().first()
    return dict(row) if row else None


async def _assignees_out(db: AsyncSession, case_id: str) -> list[CaseAssigneeOut]:
    rows = (await db.execute(
        text(
            "SELECT a.user_id::text AS user_id, COALESCE(u.email,'') AS email, "
            "       COALESCE(u.full_name,'') AS full_name "
            "FROM case_assignments a LEFT JOIN users u ON u.id = a.user_id "
            "WHERE a.case_id = CAST(:c AS uuid) ORDER BY u.email"
        ),
        {"c": case_id},
    )).mappings().all()
    return [CaseAssigneeOut(**r) for r in rows]


async def _note_count(db: AsyncSession, case_id: str) -> int:
    return int((await db.execute(
        text("SELECT count(*) FROM case_notes WHERE case_id = CAST(:c AS uuid)"),
        {"c": case_id},
    )).scalar() or 0)


async def _case_out(db: AsyncSession, case_id: str) -> CaseOut:
    c = await _load_case(db, case_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    return CaseOut(
        **c,
        assignees=await _assignees_out(db, case_id),
        note_count=await _note_count(db, case_id),
    )


# ── Cases ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CaseOut])
async def list_cases(
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> list[CaseOut]:
    """The caller's caseload: every case for a manager, only assigned cases for staff."""
    await _require_org(db, workspace_id)
    if is_manager(role):
        rows = (await db.execute(text(
            "SELECT id::text AS id FROM cases ORDER BY updated_at DESC"
        ))).scalars().all()
    else:
        rows = (await db.execute(
            text(
                "SELECT c.id::text AS id FROM cases c "
                "JOIN case_assignments a ON a.case_id = c.id "
                "WHERE a.user_id = CAST(:u AS uuid) ORDER BY c.updated_at DESC"
            ),
            {"u": uid},
        )).scalars().all()
    return [await _case_out(db, cid) for cid in rows]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreateIn,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> CaseOut:
    """Open a case. The creator is auto-assigned (so a staff worker immediately has it on
    their caseload). workspace_id is stamped by the RLS trigger."""
    await _require_org(db, workspace_id)
    case_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO cases (id, veteran_name, veteran_email, veteran_phone, summary, "
            "                   created_by, status, consent_status) "
            "VALUES (CAST(:id AS uuid), :n, :e, :p, :s, CAST(:by AS uuid), 'intake', 'none')"
        ),
        {"id": case_id, "n": payload.veteran_name.strip(),
         "e": (str(payload.veteran_email) if payload.veteran_email else None),
         "p": payload.veteran_phone, "s": payload.summary, "by": uid},
    )
    await db.execute(
        text(
            "INSERT INTO case_assignments (id, case_id, user_id, assigned_by) "
            "VALUES (gen_random_uuid(), CAST(:c AS uuid), CAST(:u AS uuid), CAST(:u AS uuid))"
        ),
        {"c": case_id, "u": uid},
    )
    await audit_log(db, uid, "case.create", entity="case", entity_id=case_id,
                    meta={"veteran_name": payload.veteran_name.strip()})
    return await _case_out(db, case_id)


async def _guard_case(db, case_id, uid, role) -> dict:
    """Load a case the caller may see, or 404 (never leak existence to a staff worker
    the case isn't assigned to)."""
    if not await _can_see(db, case_id, uid, role):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    c = await _load_case(db, case_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    return c


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: str,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> CaseOut:
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    return await _case_out(db, case_id)


@router.patch("/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: str,
    payload: CaseUpdateIn,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> CaseOut:
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return await _case_out(db, case_id)
    sets, params = [], {"c": case_id}
    col_map = {
        "veteran_name": "veteran_name", "veteran_email": "veteran_email",
        "veteran_phone": "veteran_phone", "status": "status", "summary": "summary",
    }
    for key, col in col_map.items():
        if key in fields:
            val = fields[key]
            if key == "veteran_email" and val is not None:
                val = str(val)
            sets.append(f"{col} = :{key}")
            params[key] = val
    if sets:
        sets.append("updated_at = now()")
        await db.execute(
            text(f"UPDATE cases SET {', '.join(sets)} WHERE id = CAST(:c AS uuid)"), params
        )
        await audit_log(db, uid, "case.update", entity="case", entity_id=case_id,
                        meta={"fields": list(fields.keys())})
    return await _case_out(db, case_id)


# ── Assignments (managers only) ─────────────────────────────────────────────

@router.post("/{case_id}/assignees", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def assign_staff(
    case_id: str,
    payload: AssignIn,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    _role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> CaseOut:
    """Assign a staff member to a case. The assignee must be a member of THIS org (an
    admin can't assign an outsider — enforced by the membership check)."""
    await _require_org(db, workspace_id)
    if not await _load_case(db, case_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    member = (await db.execute(
        text(
            "SELECT 1 FROM organization_members "
            "WHERE org_id = CAST(:w AS uuid) AND user_id = CAST(:u AS uuid) LIMIT 1"
        ),
        {"w": workspace_id, "u": payload.user_id},
    )).first()
    if not member:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That person isn't a member of this team."
        )
    # WHERE NOT EXISTS (not ON CONFLICT): ON CONFLICT's arbiter probe has bitten this
    # codebase under FORCE RLS before (W11) — the idempotent guard avoids it entirely.
    await db.execute(
        text(
            "INSERT INTO case_assignments (id, case_id, user_id, assigned_by) "
            "SELECT gen_random_uuid(), CAST(:c AS uuid), CAST(:u AS uuid), CAST(:by AS uuid) "
            "WHERE NOT EXISTS (SELECT 1 FROM case_assignments "
            "  WHERE case_id = CAST(:c AS uuid) AND user_id = CAST(:u AS uuid))"
        ),
        {"c": case_id, "u": payload.user_id, "by": uid},
    )
    await audit_log(db, uid, "case.assign", entity="case", entity_id=case_id,
                    meta={"assignee": payload.user_id})
    return await _case_out(db, case_id)


@router.delete("/{case_id}/assignees/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_staff(
    case_id: str,
    target_id: str,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    _role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
):
    await _require_org(db, workspace_id)
    res = await db.execute(
        text(
            "DELETE FROM case_assignments "
            "WHERE case_id = CAST(:c AS uuid) AND user_id = CAST(:u AS uuid)"
        ),
        {"c": case_id, "u": target_id},
    )
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't assigned to this case.")
    await audit_log(db, uid, "case.unassign", entity="case", entity_id=case_id,
                    meta={"assignee": target_id})
    return None


# ── Consent ─────────────────────────────────────────────────────────────────

@router.get("/{case_id}/consent", response_model=ConsentOut | None)
async def get_consent(
    case_id: str,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> ConsentOut | None:
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    row = (await db.execute(
        text(
            "SELECT id::text AS id, case_id::text AS case_id, method, scope, statement, "
            "       granted_by_name, captured_by::text AS captured_by, status, "
            "       granted_at, revoked_at "
            "FROM case_consents WHERE case_id = CAST(:c AS uuid) "
            "ORDER BY granted_at DESC LIMIT 1"
        ),
        {"c": case_id},
    )).mappings().first()
    return ConsentOut(**row) if row else None


@router.post("/{case_id}/consent", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def capture_consent(
    case_id: str,
    payload: ConsentCaptureIn,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> ConsentOut:
    """Record the veteran's authorization for the org to assist. The caseworker must
    affirm they told the veteran this is app-assist, NOT VA-accredited representation
    (VA Form 21-22) — the legal-lane guard."""
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    if not payload.acknowledged_not_poa:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Confirm the veteran was told this authorizes app-assistance only — not "
            "VA-accredited representation (VA Form 21-22).",
        )
    consent_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO case_consents (id, case_id, method, scope, statement, "
            "                           granted_by_name, captured_by, status) "
            "VALUES (CAST(:id AS uuid), CAST(:c AS uuid), :m, :sc, :st, :gbn, "
            "        CAST(:by AS uuid), 'granted')"
        ),
        {"id": consent_id, "c": case_id, "m": payload.method, "sc": payload.scope,
         "st": payload.statement, "gbn": payload.granted_by_name.strip(), "by": uid},
    )
    await db.execute(
        text("UPDATE cases SET consent_status = 'granted', updated_at = now() "
             "WHERE id = CAST(:c AS uuid)"),
        {"c": case_id},
    )
    await audit_log(db, uid, "case.consent.grant", entity="case", entity_id=case_id,
                    meta={"method": payload.method, "by_name": payload.granted_by_name.strip()})
    row = (await db.execute(
        text(
            "SELECT id::text AS id, case_id::text AS case_id, method, scope, statement, "
            "       granted_by_name, captured_by::text AS captured_by, status, "
            "       granted_at, revoked_at FROM case_consents WHERE id = CAST(:id AS uuid)"
        ),
        {"id": consent_id},
    )).mappings().first()
    return ConsentOut(**row)


@router.post("/{case_id}/consent/revoke", response_model=CaseOut)
async def revoke_consent(
    case_id: str,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> CaseOut:
    """Revoke consent (the veteran withdrew authorization). Flips the latest consent to
    revoked and the case's consent_status; audited."""
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    await db.execute(
        text(
            "UPDATE case_consents SET status = 'revoked', revoked_at = now() "
            "WHERE case_id = CAST(:c AS uuid) AND status = 'granted'"
        ),
        {"c": case_id},
    )
    await db.execute(
        text("UPDATE cases SET consent_status = 'revoked', updated_at = now() "
             "WHERE id = CAST(:c AS uuid)"),
        {"c": case_id},
    )
    await audit_log(db, uid, "case.consent.revoke", entity="case", entity_id=case_id)
    return await _case_out(db, case_id)


# ── Notes ───────────────────────────────────────────────────────────────────

@router.get("/{case_id}/notes", response_model=list[CaseNoteOut])
async def list_notes(
    case_id: str,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> list[CaseNoteOut]:
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    rows = (await db.execute(
        text(
            "SELECT n.id::text AS id, n.case_id::text AS case_id, "
            "       n.author_id::text AS author_id, COALESCE(u.email,'') AS author_email, "
            "       n.body, n.created_at "
            "FROM case_notes n LEFT JOIN users u ON u.id = n.author_id "
            "WHERE n.case_id = CAST(:c AS uuid) ORDER BY n.created_at DESC"
        ),
        {"c": case_id},
    )).mappings().all()
    return [CaseNoteOut(**r) for r in rows]


@router.post("/{case_id}/notes", response_model=CaseNoteOut, status_code=status.HTTP_201_CREATED)
async def add_note(
    case_id: str,
    payload: CaseNoteIn,
    workspace_id: str = Depends(current_workspace_id),
    uid: str = Depends(current_user_id),
    role: str = Depends(require_role("staff")),
    db: AsyncSession = Depends(get_db),
    _feat: str = _FEATURE,
) -> CaseNoteOut:
    await _require_org(db, workspace_id)
    await _guard_case(db, case_id, uid, role)
    note_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO case_notes (id, case_id, author_id, body) "
            "VALUES (CAST(:id AS uuid), CAST(:c AS uuid), CAST(:by AS uuid), :b)"
        ),
        {"id": note_id, "c": case_id, "by": uid, "b": payload.body.strip()},
    )
    await db.execute(
        text("UPDATE cases SET updated_at = now() WHERE id = CAST(:c AS uuid)"),
        {"c": case_id},
    )
    await audit_log(db, uid, "case.note.add", entity="case", entity_id=case_id)
    row = (await db.execute(
        text(
            "SELECT n.id::text AS id, n.case_id::text AS case_id, "
            "       n.author_id::text AS author_id, COALESCE(u.email,'') AS author_email, "
            "       n.body, n.created_at "
            "FROM case_notes n LEFT JOIN users u ON u.id = n.author_id "
            "WHERE n.id = CAST(:id AS uuid)"
        ),
        {"id": note_id},
    )).mappings().first()
    return CaseNoteOut(**row)
