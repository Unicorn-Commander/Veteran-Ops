"""Credit ledger helpers.

The app-owned billing spine is deliberately simple: a per-user credit wallet,
an append-only transaction ledger, and a global grant pool ledger for sponsor-
funded claims. Routes use these helpers so the accounting stays centralized.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

from .models import (
    CreditBalance,
    CreditTransaction,
    GrantApplication,
    GrantPool,
    Sponsorship,
)


@dataclass(slots=True)
class CreditLimitError(Exception):
    """Raised when a debit would take a wallet negative."""

    balance: int
    required: int
    operation: str

    @property
    def message(self) -> str:
        return (
            f"This action costs {self.required} credits, but your balance is "
            f"{self.balance}. Add credits or wait for a grant."
        )


class CreditConfig:
    document_process = 1
    analysis_map_conditions = 1
    analysis_secondaries = 1
    analysis_case_candidates = 1
    decoder = 1
    full_claim_credits = 1000
    topup_credits = 300
    sponsor_claims = 1
    full_claim_amount_cents = 10_000
    topup_amount_cents = 2_500
    sponsor_amount_cents = 10_000


def _uid(user_id: str | uuid.UUID) -> str:
    return str(user_id)


async def _ensure_balance_row(db: AsyncSession, user_id: str | uuid.UUID) -> None:
    user_uuid = uuid.UUID(_uid(user_id))
    existing = (
        await db.execute(
            select(CreditBalance).where(CreditBalance.user_id == user_uuid)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(CreditBalance(user_id=user_uuid, balance=0))
        await db.flush()


async def get_balance(db: AsyncSession, user_id: str | uuid.UUID) -> int:
    row = (
        await db.execute(
            select(CreditBalance.balance).where(CreditBalance.user_id == uuid.UUID(_uid(user_id)))
        )
    ).scalar_one_or_none()
    if row is not None:
        return int(row)
    await _ensure_balance_row(db, user_id)
    row = (
        await db.execute(
            select(CreditBalance.balance).where(CreditBalance.user_id == uuid.UUID(_uid(user_id)))
        )
    ).scalar_one_or_none()
    return int(row or 0)


async def recent_transactions(
    db: AsyncSession, user_id: str | uuid.UUID, limit: int = 10
) -> list[CreditTransaction]:
    return list(
        (
            await db.execute(
                select(CreditTransaction)
                .where(CreditTransaction.user_id == uuid.UUID(_uid(user_id)))
                .order_by(CreditTransaction.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


async def _existing_transaction(
    db: AsyncSession, idempotency_key: str | None
) -> CreditTransaction | None:
    if not idempotency_key:
        return None
    return (
        await db.execute(
            select(CreditTransaction).where(CreditTransaction.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()


async def adjust_credits(
    db: AsyncSession,
    user_id: str | uuid.UUID,
    delta: int,
    *,
    operation: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    note: str | None = None,
    meta: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> int:
    """Apply a positive or negative delta and write the ledger row.

    When `idempotency_key` is provided, a prior matching transaction is treated as
    already processed and its balance is returned without mutating state.
    """
    user_uuid = uuid.UUID(_uid(user_id))
    if delta == 0:
        return await get_balance(db, user_uuid)

    # Metering dormant: never debit or block an AI operation while credits_enabled is
    # off (the default). Positive deltas (purchases, grants) still apply so a balance
    # can accrue; only the enforcement/debit path is gated, so no existing veteran is
    # 402'd out of a free feature until we deliberately turn metering on.
    if delta < 0 and not settings.credits_enabled:
        # A disabled meter is a true no-op: do not require the ledger table (or
        # create/read a balance row) merely to let a free operation proceed.
        # Callers of debit paths use this value only as an acknowledged balance.
        return 0

    existing = await _existing_transaction(db, idempotency_key)
    if existing is not None:
        return int(existing.balance_after)

    await _ensure_balance_row(db, user_uuid)
    if delta < 0:
        result = await db.execute(
            update(CreditBalance)
            .where(CreditBalance.user_id == user_uuid)
            .where(CreditBalance.balance + delta >= 0)
            .values(balance=CreditBalance.balance + delta, updated_at=func.now())
        )
        if result.rowcount == 0:
            balance = await get_balance(db, user_uuid)
            raise CreditLimitError(balance=balance, required=abs(delta), operation=operation)
    else:
        await db.execute(
            update(CreditBalance)
            .where(CreditBalance.user_id == user_uuid)
            .values(balance=CreditBalance.balance + delta, updated_at=func.now())
        )

    balance_after = await get_balance(db, user_uuid)

    tx = CreditTransaction(
        user_id=user_uuid,
        delta=delta,
        balance_after=int(balance_after),
        operation=operation,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        note=note,
        meta=meta,
    )
    db.add(tx)
    await db.flush()
    return int(balance_after)


async def require_credits(
    db: AsyncSession,
    user_id: str | uuid.UUID,
    delta: int,
    *,
    operation: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    note: str | None = None,
    meta: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> int:
    try:
        return await adjust_credits(
            db,
            user_id,
            delta,
            operation=operation,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            meta=meta,
            idempotency_key=idempotency_key,
        )
    except CreditLimitError as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, exc.message) from exc


async def grant_credits(
    db: AsyncSession,
    user_id: str | uuid.UUID,
    delta: int,
    *,
    operation: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    note: str | None = None,
    meta: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> int:
    """Positive credit grant wrapper."""
    if delta < 0:
        raise ValueError("grant_credits expects a positive delta")
    return await adjust_credits(
        db,
        user_id,
        delta,
        operation=operation,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        meta=meta,
        idempotency_key=idempotency_key,
    )


async def pool_balance(db: AsyncSession) -> int:
    row = (
        await db.execute(select(func.coalesce(func.sum(GrantPool.claims_delta), 0)))
    ).scalar_one()
    return int(row or 0)


async def pool_recent(db: AsyncSession, limit: int = 20) -> list[GrantPool]:
    return list(
        (
            await db.execute(
                select(GrantPool).order_by(GrantPool.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    )


async def record_pool_claim(
    db: AsyncSession,
    *,
    claims_delta: int,
    kind: str,
    sponsorship_id: str | uuid.UUID | None = None,
    grant_application_id: str | uuid.UUID | None = None,
    reserved_email: str | None = None,
    reserved_user_id: str | uuid.UUID | None = None,
    note: str | None = None,
) -> GrantPool:
    row = GrantPool(
        claims_delta=claims_delta,
        kind=kind,
        sponsorship_id=uuid.UUID(str(sponsorship_id)) if sponsorship_id else None,
        grant_application_id=uuid.UUID(str(grant_application_id)) if grant_application_id else None,
        reserved_email=reserved_email,
        reserved_user_id=uuid.UUID(str(reserved_user_id)) if reserved_user_id else None,
        note=note,
    )
    db.add(row)
    await db.flush()
    return row


async def application_by_id(db: AsyncSession, application_id: str | uuid.UUID) -> GrantApplication | None:
    return await db.get(GrantApplication, uuid.UUID(str(application_id)))


async def sponsorship_by_session(
    db: AsyncSession, checkout_session_id: str
) -> Sponsorship | None:
    return (
        await db.execute(
            select(Sponsorship).where(Sponsorship.checkout_session_id == checkout_session_id)
        )
    ).scalar_one_or_none()


async def available_sponsorship_claims(db: AsyncSession, beneficiary_email: str | None = None) -> list[Sponsorship]:
    stmt = select(Sponsorship).where(Sponsorship.consumed_at.is_(None), Sponsorship.status != "failed")
    if beneficiary_email:
        stmt = stmt.where(Sponsorship.beneficiary_email == beneficiary_email)
    return list((await db.execute(stmt.order_by(Sponsorship.created_at.asc()))).scalars().all())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
