"""Credit wallet, grant applications, and grant-pool admin surfaces."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..crediting import (
    CreditConfig,
    get_balance,
    grant_credits,
    now_utc,
    pool_balance,
    pool_recent,
    record_pool_claim,
    recent_transactions,
)
from ..deps import current_user_id, current_workspace_id, get_db
from ..models import GrantApplication, GrantPool, Sponsorship, User
from ..rbac import current_role, require_role
from ..schemas import (
    AdminGrantsOut,
    CreditsOut,
    GrantApplicationIn,
    GrantApplicationOut,
    GrantApplicationReviewIn,
    GrantPoolEntryOut,
    GrantPoolOut,
    SponsorshipOut,
)

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("", response_model=CreditsOut)
async def credits_status(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> CreditsOut:
    balance = await get_balance(db, uid)
    recent = await recent_transactions(db, uid, limit=12)
    return CreditsOut(balance=balance, recent=recent)


@router.get("/grant-applications", response_model=list[GrantApplicationOut])
async def my_grant_applications(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[GrantApplicationOut]:
    rows = (
        await db.execute(
            select(GrantApplication)
            .where(GrantApplication.user_id == uuid.UUID(uid))
            .order_by(GrantApplication.created_at.desc())
        )
    ).scalars().all()
    return [GrantApplicationOut.model_validate(r) for r in rows]


@router.post("/grant-applications", response_model=GrantApplicationOut, status_code=status.HTTP_201_CREATED)
async def submit_grant_application(
    payload: GrantApplicationIn,
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> GrantApplicationOut:
    user = await db.get(User, uuid.UUID(uid))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    app = GrantApplication(
        user_id=uuid.UUID(uid),
        workspace_id=uuid.UUID(workspace_id),
        monthly_income_band=payload.monthly_income_band,
        household_size=payload.household_size,
        employment_status=payload.employment_status,
        hardship_summary=payload.hardship_summary.strip(),
        contact_email=str(payload.contact_email or user.email),
        status="pending",
    )
    db.add(app)
    await db.flush()
    await audit.log(
        db,
        uid,
        "grant.application.submit",
        entity="grant_application",
        entity_id=str(app.id),
        meta={"status": "pending"},
    )
    await db.refresh(app)
    return GrantApplicationOut.model_validate(app)


@router.get("/admin/grant-applications", response_model=AdminGrantsOut)
async def admin_grant_applications(
    _role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AdminGrantsOut:
    apps = (
        await db.execute(
            select(GrantApplication).order_by(
                GrantApplication.status.asc(), GrantApplication.created_at.desc()
            )
        )
    ).scalars().all()
    pool_rows = await pool_recent(db, limit=25)
    sponsorships = (
        await db.execute(
            select(Sponsorship).order_by(Sponsorship.created_at.desc()).limit(25)
        )
    ).scalars().all()
    total = await pool_balance(db)
    earned = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(case((GrantPool.claims_delta > 0, GrantPool.claims_delta), else_=0)), 0))
            )
        ).scalar_one()
        or 0
    )
    spent = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(case((GrantPool.claims_delta < 0, -GrantPool.claims_delta), else_=0)), 0))
            )
        ).scalar_one()
        or 0
    )
    return AdminGrantsOut(
        pool=GrantPoolOut(
            available_claims=total,
            earned_claims=earned,
            spent_claims=spent,
            recent=[GrantPoolEntryOut.model_validate(r) for r in pool_rows],
        ),
        applications=[GrantApplicationOut.model_validate(r) for r in apps],
        sponsorships=[SponsorshipOut.model_validate(r) for r in sponsorships],
    )


@router.patch("/admin/grant-applications/{application_id}", response_model=GrantApplicationOut)
async def review_grant_application(
    application_id: uuid.UUID,
    payload: GrantApplicationReviewIn,
    uid: str = Depends(current_user_id),
    _role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> GrantApplicationOut:
    app = await db.get(GrantApplication, application_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant application not found.")
    if app.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This application has already been reviewed.")
    if payload.status == "denied" and not (payload.review_note or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A denial reason is required.")

    if payload.status == "approved":
        user = await db.get(User, app.user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Applicant user not found.")

        # Prefer an earmarked sponsor claim for this person when one exists.
        sponsor = (
            await db.execute(
                select(Sponsorship)
                .where(Sponsorship.consumed_at.is_(None))
                .where(
                    (Sponsorship.beneficiary_user_id == app.user_id)
                    | (Sponsorship.beneficiary_email == user.email)
                    | (Sponsorship.beneficiary_email == app.contact_email)
                )
                .order_by(Sponsorship.created_at.asc())
            )
        ).scalar_one_or_none()
        if sponsor is None:
            sponsor = (
                await db.execute(
                    select(Sponsorship)
                    .where(Sponsorship.consumed_at.is_(None))
                    .where(Sponsorship.beneficiary_email.is_(None))
                    .order_by(Sponsorship.created_at.asc())
                )
            ).scalar_one_or_none()
        if sponsor is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "No sponsor claim is available in the grant pool yet.",
            )

        sponsor.consumed_at = now_utc()
        sponsor.status = "consumed"
        await record_pool_claim(
            db,
            claims_delta=-1,
            kind="grant_awarded",
            sponsorship_id=sponsor.id,
            grant_application_id=app.id,
            reserved_email=sponsor.beneficiary_email,
            reserved_user_id=sponsor.beneficiary_user_id,
            note=f"Approved by {uid}",
        )
        await grant_credits(
            db,
            app.user_id,
            CreditConfig.full_claim_credits,
            operation="grant.approved",
            reference_type="grant_application",
            reference_id=str(app.id),
            note="Full Claim grant award",
            idempotency_key=f"grant:{app.id}",
            meta={"sponsorship_id": str(sponsor.id)},
        )
        app.funded_sponsorship_id = sponsor.id

    app.status = payload.status
    app.reviewer_user_id = uuid.UUID(uid)
    app.reviewed_at = datetime.now(timezone.utc)
    app.review_note = payload.review_note
    await audit.log(
        db,
        uid,
        "grant.application.review",
        entity="grant_application",
        entity_id=str(app.id),
        meta={"status": payload.status, "funded": payload.status == "approved"},
    )
    await db.flush()
    await db.refresh(app)
    return GrantApplicationOut.model_validate(app)
