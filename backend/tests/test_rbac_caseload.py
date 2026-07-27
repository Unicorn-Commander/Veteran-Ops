"""WAVE13 — pure unit tests for the caseload RBAC helpers in app/rbac.py.

No DB, no app: these exercise the role math (`rank`/`ROLE_RANK`), the manager
predicate (`is_manager`) that gates whole-org caseload visibility, and the
`require_role` dependency factory (403 below the minimum). This is the app-level
INTRA-tenant authorization layer that sits on top of Postgres RLS isolation.
"""

from __future__ import annotations

import asyncio

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402

from app.rbac import ROLE_RANK, is_manager, rank, require_role  # noqa: E402


def test_is_manager_true_for_owner_and_admin():
    assert is_manager("owner") is True
    assert is_manager("admin") is True


def test_is_manager_false_for_staff_member_none_and_unknown():
    assert is_manager("staff") is False
    assert is_manager("member") is False
    assert is_manager(None) is False
    assert is_manager("bogus") is False


def test_rank_ordering_holds():
    assert rank("owner") > rank("admin") > rank("staff") > rank("member")
    assert ROLE_RANK == {"member": 0, "staff": 1, "admin": 2, "owner": 3}
    # Unknown / absent role sinks below every real role.
    assert rank(None) == -1
    assert rank("bogus") == -1
    assert rank("member") > rank(None)


def test_require_role_staff_blocks_member_allows_staff_and_up():
    dep = require_role("staff")

    with pytest.raises(HTTPException) as ei:
        asyncio.run(dep(role="member"))
    assert ei.value.status_code == 403

    assert asyncio.run(dep(role="staff")) == "staff"
    assert asyncio.run(dep(role="admin")) == "admin"
    assert asyncio.run(dep(role="owner")) == "owner"


def test_require_role_admin_blocks_staff_allows_admin():
    dep = require_role("admin")

    with pytest.raises(HTTPException) as ei:
        asyncio.run(dep(role="staff"))
    assert ei.value.status_code == 403

    assert asyncio.run(dep(role="admin")) == "admin"
    assert asyncio.run(dep(role="owner")) == "owner"


def test_caseload_scope_truth_table():
    """The intended caseload SCOPING RULE (the raw-SQL router can't run on SQLite, so
    this is a lightweight guard on the policy): managers (admin/owner) see the whole
    org caseload; staff/member are NOT managers → staff visibility is assignment-based,
    a plain member has none."""
    manager_sees_all = {r: is_manager(r) for r in ("owner", "admin", "staff", "member", None)}
    assert manager_sees_all == {
        "owner": True,
        "admin": True,
        "staff": False,
        "member": False,
        None: False,
    }
