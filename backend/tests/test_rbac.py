"""WAVE12 — intra-tenant role authorization (app/rbac.py). Pure unit tests: the role
ranking and the require_role dependency factory. We invoke the inner dependency
coroutine directly with a role= kwarg (bypassing the current_role DB lookup) to prove
the 403 boundary at the rank threshold.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.rbac import ROLE_RANK, rank, require_role


def test_role_rank_ordering():
    assert (
        ROLE_RANK["owner"] > ROLE_RANK["admin"] > ROLE_RANK["staff"] > ROLE_RANK["member"]
    )


def test_rank_unknown_or_none_is_negative():
    assert rank(None) == -1
    assert rank("") == -1
    assert rank("bogus") == -1
    assert rank("owner") == ROLE_RANK["owner"]


async def test_require_role_forbids_below_minimum():
    dep = require_role("admin")
    with pytest.raises(HTTPException) as ei:
        await dep(role="member")
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException) as ei2:
        await dep(role="staff")
    assert ei2.value.status_code == 403


async def test_require_role_allows_at_or_above_minimum():
    dep = require_role("admin")
    assert await dep(role="admin") == "admin"
    assert await dep(role="owner") == "owner"


async def test_require_role_unknown_role_is_forbidden():
    dep = require_role("member")
    # Even the lowest bar rejects an unknown/absent role (rank -1 < 0).
    with pytest.raises(HTTPException) as ei:
        await dep(role="nobody")
    assert ei.value.status_code == 403
    # A real member passes the member bar.
    assert await dep(role="member") == "member"
