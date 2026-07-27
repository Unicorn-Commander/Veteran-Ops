"""Buddy-statement builder (VA Form 21-10210) — pure assembler + endpoints.

Both endpoints are DB-free and LLM-free: guidance is static grounded content,
draft is a deterministic template over the request body. We mount the real
router on a bare FastAPI app with the auth dependency overridden (same pattern
as test_open_data.py's client fixture). No network, no SQLite.
"""

from __future__ import annotations

import pytest

from app.routers.buddy import FORM, _render_statement
from app.schemas import BuddyDraftIn

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import buddy as buddy_router_mod  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(buddy_router_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = (
        lambda: "00000000-0000-0000-0000-000000000001"
    )
    with TestClient(app) as c:
        yield c


# ── Pure assembler ───────────────────────────────────────────────────────────
def test_render_statement_weaves_all_inputs():
    md = _render_statement(
        BuddyDraftIn(
            witness_name="Jane Doe",
            witness_relationship="spouse",
            veteran_name="John Doe",
            condition="PTSD",
            observations="He wakes screaming most nights and avoids crowds.",
            period="from 2019 to the present",
        )
    )
    assert "Jane Doe" in md
    assert "spouse" in md
    assert "John Doe" in md
    assert "PTSD" in md
    assert "He wakes screaming most nights and avoids crowds." in md
    assert "from 2019 to the present" in md
    # opener structure + first-hand attestation + signature block
    assert "I, Jane Doe, spouse of John Doe, state the following" in md
    assert "first-hand knowledge" in md.lower()
    assert "Signature:" in md and "Date:" in md
    assert FORM in md


def test_render_statement_optional_fields_absent():
    md = _render_statement(
        BuddyDraftIn(
            witness_name="Sam Roe",
            witness_relationship="former squad leader",
            observations="I saw him limp badly after every ruck march.",
        )
    )
    assert "Sam Roe" in md
    assert "former squad leader" in md
    # falls back to a neutral veteran reference, no fabricated name/condition
    assert "the veteran" in md
    assert "I saw him limp badly after every ruck march." in md
    assert "Signature:" in md


# ── /buddy/situation-brief ───────────────────────────────────────────────────
def test_situation_brief_endpoint(client):
    r = client.post(
        "/api/buddy/situation-brief",
        json={
            "condition": "ME/CFS",
            "veteran_name": "Aaron",
            "themes": ["stairs", "work absences"],
            "period": "since 2020",
            "known_facts": ["Needs rest after short walks"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["condition"] == "ME/CFS"
    assert len(body["hit_list"]) >= 4
    assert body["avoid"]
    assert "own words" in body["starter_outline"].lower() or "your words" in body["starter_outline"].lower()
    # legal lane: never tells witness to diagnose
    blob = " ".join(body["hit_list"] + body["avoid"]).lower()
    assert "will be granted" not in blob


# ── /buddy/guidance ──────────────────────────────────────────────────────────
def test_guidance_endpoint(client):
    r = client.get("/api/buddy/guidance")
    assert r.status_code == 200
    body = r.json()
    assert body["form"] == "VA Form 21-10210"
    assert body["form_title"]
    assert body["form_url"].startswith("https://")
    assert len(body["prompts"]) >= 3
    assert len(body["tips"]) >= 3
    assert body["disclaimer"]
    # grounded in the governing authority
    assert "3.159" in body["disclaimer"] or any("3.159" in t for t in body["tips"])
    assert "Layno" in body["disclaimer"] or any("Layno" in t for t in body["tips"])


def test_guidance_requires_auth():
    # a bare app WITHOUT the override should reject (no bearer -> 401/403)
    app = FastAPI()
    app.include_router(buddy_router_mod.router, prefix="/api")
    with TestClient(app) as c:
        assert c.get("/api/buddy/guidance").status_code in (401, 403)


# ── /buddy/draft ─────────────────────────────────────────────────────────────
def test_draft_endpoint_renders_statement(client):
    r = client.post(
        "/api/buddy/draft",
        json={
            "witness_name": "Maria Vega",
            "witness_relationship": "coworker",
            "veteran_name": "Alex Stone",
            "condition": "lumbar strain",
            "observations": "She could not lift boxes and left work early in pain.",
            "period": "over the last two years",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["form"] == "VA Form 21-10210"
    md = body["statement_markdown"]
    assert "Maria Vega" in md
    assert "coworker" in md
    assert "Alex Stone" in md
    assert "She could not lift boxes and left work early in pain." in md
    assert "Signature:" in md
    assert isinstance(body["guidance"], list) and body["guidance"]
    assert body["disclaimer"]


def test_draft_endpoint_optional_fields_omitted(client):
    r = client.post(
        "/api/buddy/draft",
        json={
            "witness_name": "Pat Lee",
            "witness_relationship": "neighbor",
            "observations": "I helped him up the porch steps most days.",
        },
    )
    assert r.status_code == 200
    md = r.json()["statement_markdown"]
    assert "Pat Lee" in md
    assert "I helped him up the porch steps most days." in md


@pytest.mark.parametrize(
    "bad",
    [
        {"witness_relationship": "spouse", "observations": "x"},  # no witness_name
        {"witness_name": "A", "observations": "x"},  # no relationship
        {"witness_name": "A", "witness_relationship": "spouse"},  # no observations
        {"witness_name": "", "witness_relationship": "spouse", "observations": "x"},
        {"witness_name": "A", "witness_relationship": "spouse", "observations": ""},
    ],
)
def test_draft_rejects_missing_required_fields(client, bad):
    assert client.post("/api/buddy/draft", json=bad).status_code == 422
