"""Personal-statement builder (VA Form 21-4138) — pure assembler + endpoints.

Both endpoints are DB-free and LLM-free: guidance is static grounded content,
draft is a deterministic template over the request body that passes the
veteran's own words through VERBATIM. We mount the real router on a bare FastAPI
app with the auth dependency overridden (same pattern as test_buddy.py /
test_open_data.py). No network, no SQLite.
"""

from __future__ import annotations

import pytest

from app.routers.statement import FORM, FORM_TITLE, _render_statement
from app.schemas import StatementDraftIn

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import statement as statement_router_mod  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(statement_router_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = (
        lambda: "00000000-0000-0000-0000-000000000001"
    )
    with TestClient(app) as c:
        yield c


# ── Pure assembler ───────────────────────────────────────────────────────────
def test_render_statement_weaves_all_inputs():
    distinctive = (
        "In March 2004 our convoy was hit by an IED outside Camp Victory and I "
        "have not slept a full night since."
    )
    md = _render_statement(
        StatementDraftIn(
            veteran_name="John Doe",
            condition="PTSD",
            topic="my PTSD from a 2004 convoy attack",
            statement=distinctive,
            period="March 2004 to the present",
        )
    )
    assert "John Doe" in md
    assert "PTSD" in md
    assert "my PTSD from a 2004 convoy attack" in md
    assert "March 2004 to the present" in md
    # veteran's words pass through VERBATIM — not reworded/embellished
    assert distinctive in md
    # 21-4138 structure: heading, opener, truthfulness attestation, signature
    assert FORM in md and FORM_TITLE in md
    assert "am submitting this statement in support of my claim regarding" in md
    assert "true and correct to the best of my knowledge and belief" in md
    assert "Signature:" in md and "Date:" in md
    assert "Printed name:" in md


def test_render_statement_optional_fields_absent():
    body = "I was never given paperwork for the injury; they told me to walk it off."
    md = _render_statement(
        StatementDraftIn(
            topic="my right knee",
            statement=body,
        )
    )
    # no fabricated veteran name / condition / period
    assert body in md
    assert "the undersigned veteran" in md
    assert "my right knee" in md
    assert "Signature:" in md
    # nothing invented for the blank name
    assert "____" in md


def test_render_statement_does_not_reword_body():
    quirky = "The dang generator ran ALL night and my ears been ringing ever since."
    md = _render_statement(
        StatementDraftIn(topic="tinnitus", statement=quirky)
    )
    assert quirky in md  # exact, character-for-character


# ── /statement/guidance ──────────────────────────────────────────────────────
def test_guidance_endpoint(client):
    r = client.get("/api/statement/guidance")
    assert r.status_code == 200
    body = r.json()
    assert body["form"] == "VA Form 21-4138"
    assert body["form_title"] == "Statement in Support of Claim"
    assert body["form_url"].startswith("https://")
    assert len(body["prompts"]) >= 3
    assert len(body["tips"]) >= 3
    assert body["disclaimer"]
    # legal lane: the app never files it for the veteran
    assert "never files it" in body["disclaimer"] or "never signs" in body["disclaimer"]


def test_guidance_requires_auth():
    # a bare app WITHOUT the override should reject (no bearer -> 401/403)
    app = FastAPI()
    app.include_router(statement_router_mod.router, prefix="/api")
    with TestClient(app) as c:
        assert c.get("/api/statement/guidance").status_code in (401, 403)


# ── /statement/draft ─────────────────────────────────────────────────────────
def test_draft_endpoint_renders_statement(client):
    distinctive = "I still check every doorway before I walk through it."
    r = client.post(
        "/api/statement/draft",
        json={
            "veteran_name": "Alex Stone",
            "condition": "PTSD",
            "topic": "combat stressor and its effect on my daily life",
            "statement": distinctive,
            "period": "2010 to now",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["form"] == "VA Form 21-4138"
    md = body["statement_markdown"]
    assert "Alex Stone" in md
    assert "combat stressor and its effect on my daily life" in md
    # verbatim veteran statement + attestation + signature block
    assert distinctive in md
    assert "true and correct to the best of my knowledge and belief" in md
    assert "Signature:" in md
    assert isinstance(body["guidance"], list) and body["guidance"]
    assert body["disclaimer"]


def test_draft_endpoint_optional_fields_omitted(client):
    body_text = "No one wrote it down, but it happened just like I said."
    r = client.post(
        "/api/statement/draft",
        json={"topic": "back injury", "statement": body_text},
    )
    assert r.status_code == 200
    md = r.json()["statement_markdown"]
    assert body_text in md
    assert "back injury" in md


@pytest.mark.parametrize(
    "bad",
    [
        {"statement": "x"},  # no topic
        {"topic": "knee"},  # no statement
        {"topic": "", "statement": "x"},  # empty topic
        {"topic": "knee", "statement": ""},  # empty statement
        {},  # nothing
    ],
)
def test_draft_rejects_missing_required_fields(client, bad):
    assert client.post("/api/statement/draft", json=bad).status_code == 422
