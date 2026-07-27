"""Nexus-letter builder (WAVE6 F2) — pure assembler + endpoints.

Both endpoints are DB-free and LLM-free: guidance is static grounded content,
draft is a deterministic template over the request body. We mount the real
router on a bare FastAPI app with the auth dependency overridden (same pattern
as test_open_data.py / test_buddy.py). No network, no SQLite.

Legal-lane assertions run throughout: the template must never assert a COMPLETED
medical opinion — the opinion sentence is a fill-in, and the rationale is left
blank for the PROVIDER to write and sign.
"""

from __future__ import annotations

import pytest

from app.routers.nexus import _render_letter
from app.schemas import NexusDraftIn

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import nexus as nexus_router_mod  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(nexus_router_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = (
        lambda: "00000000-0000-0000-0000-000000000001"
    )
    with TestClient(app) as c:
        yield c


# ── Pure assembler ───────────────────────────────────────────────────────────
def test_render_letter_weaves_condition_and_veteran():
    md = _render_letter(
        NexusDraftIn(
            veteran_name="John Doe",
            condition="tinnitus",
            diagnostic_code="6260",
            claim_type="direct",
            in_service_event="repeated exposure to artillery fire without hearing protection",
        )
    )
    assert "John Doe" in md
    assert "tinnitus" in md
    assert "6260" in md
    assert "artillery fire" in md
    # RE line
    assert "RE: Nexus opinion for John Doe — tinnitus" in md
    # direct framing cites §3.303
    assert "3.303" in md


def test_render_letter_has_provider_to_complete_sections():
    md = _render_letter(NexusDraftIn(condition="lumbar strain"))
    # both provider-owned sections are clearly labeled
    assert "[PROVIDER TO COMPLETE]" in md
    assert md.count("[PROVIDER TO COMPLETE]") >= 2
    assert "OPINION" in md
    assert "RATIONALE" in md
    # the magic language is present as a fill-in, not a conclusion
    assert "at least as likely as not" in md
    assert "50% or greater probability" in md
    # provider signature block
    assert "Provider signature:" in md
    assert "license" in md.lower()
    # falls back to a neutral veteran reference, no fabricated name
    assert "the veteran" in md


def test_render_letter_opinion_is_a_fill_in_not_a_conclusion():
    """The template must NEVER assert a completed medical opinion — the opinion
    sentence is a blank the provider fills, and the rationale is left empty."""
    md = _render_letter(
        NexusDraftIn(condition="migraines", in_service_event="head injury in a blast")
    )
    # the opinion sentence contains a bracketed CHOICE + a blank to fill
    assert "[caused by / related to / aggravated by]" in md
    assert "______" in md  # fill-in blanks exist
    # it is framed as the PROVIDER's opinion to make, not the app's conclusion
    assert "It is my professional medical opinion that" in md
    # the rationale section explicitly asks the provider to complete it
    assert "RATIONALE" in md
    assert "complete it in your own words" in md
    # the app never states the condition simply "is related to service" as fact
    assert "is at least as likely as not (50% or greater probability) [caused by" in md


def test_render_letter_secondary_framing_uses_secondary_to():
    md = _render_letter(
        NexusDraftIn(
            veteran_name="Jane Roe",
            condition="depression",
            claim_type="secondary",
            secondary_to="chronic lower back pain",
        )
    )
    assert "Jane Roe" in md
    assert "depression" in md
    # secondary framing weaves in the primary service-connected condition
    assert "chronic lower back pain" in md
    assert "SECONDARY" in md
    # causation / aggravation framing to the primary (38 CFR §3.310)
    assert "3.310" in md
    assert "CAUSED" in md
    assert "AGGRAVATED" in md


def test_render_letter_clinical_summary_marked_not_the_opinion():
    md = _render_letter(
        NexusDraftIn(
            condition="sleep apnea",
            clinical_summary="Veteran reports loud snoring and daytime fatigue since 2010.",
        )
    )
    assert "Veteran reports loud snoring and daytime fatigue since 2010." in md
    # explicitly framed as veteran-provided background, NOT a medical opinion
    assert "Background provided by the veteran" in md
    assert "NOT a medical opinion" in md


# ── /nexus/provider-brief ────────────────────────────────────────────────────
def test_provider_brief_endpoint(client):
    r = client.post(
        "/api/nexus/provider-brief",
        json={
            "condition": "Unspecified anxiety disorder",
            "claim_type": "secondary",
            "secondary_to": "Chronic Fatigue Syndrome (ME/CFS)",
            "diagnostic_code": "9413",
            "prior_denial_notes": "Denied 2016 on direct SC; nexus missing.",
            "missing_elements": ["nexus", "secondary_link"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["condition"] == "Unspecified anxiety disorder"
    assert body["what_was_missing"]
    assert "at least as likely as not" in body["opinion_scaffold"].lower()
    assert "3.310" in body["opinion_scaffold"]
    assert "will be granted" not in body["opinion_scaffold"].lower()
    assert body["blank_rationale_prompt"]
    assert body["disclaimer"]


# ── /nexus/guidance ──────────────────────────────────────────────────────────
def test_guidance_endpoint(client):
    r = client.get("/api/nexus/guidance")
    assert r.status_code == 200
    body = r.json()
    assert body["what_it_is"]
    assert body["why_it_matters"]
    assert len(body["prompts"]) >= 3
    assert len(body["tips"]) >= 3
    assert body["disclaimer"]
    # the "at least as likely as not" language appears in the grounded content
    joined = " ".join([body["what_it_is"], body["why_it_matters"], body["disclaimer"]]) + " ".join(
        body["prompts"]
    ) + " ".join(body["tips"])
    assert "at least as likely as not" in joined
    # grounded in the governing authority
    assert "3.303" in joined
    assert "3.310" in joined


def test_guidance_requires_auth():
    # a bare app WITHOUT the override should reject (no bearer -> 401/403)
    app = FastAPI()
    app.include_router(nexus_router_mod.router, prefix="/api")
    with TestClient(app) as c:
        assert c.get("/api/nexus/guidance").status_code in (401, 403)


# ── /nexus/draft ─────────────────────────────────────────────────────────────
def test_draft_endpoint_renders_template(client):
    r = client.post(
        "/api/nexus/draft",
        json={
            "veteran_name": "Alex Stone",
            "condition": "PTSD",
            "diagnostic_code": "9411",
            "claim_type": "direct",
            "in_service_event": "witnessed an IED strike on convoy",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"]
    md = body["letter_markdown"]
    assert "Alex Stone" in md
    assert "PTSD" in md
    assert "witnessed an IED strike on convoy" in md
    # provider-owned sections + fill-in opinion + signature block
    assert "[PROVIDER TO COMPLETE]" in md
    assert "at least as likely as not" in md
    assert "Provider signature:" in md
    assert isinstance(body["guidance"], list) and body["guidance"]
    assert body["disclaimer"]


def test_draft_endpoint_secondary(client):
    r = client.post(
        "/api/nexus/draft",
        json={
            "condition": "radiculopathy",
            "claim_type": "secondary",
            "secondary_to": "service-connected lumbar strain",
        },
    )
    assert r.status_code == 200
    md = r.json()["letter_markdown"]
    assert "radiculopathy" in md
    assert "service-connected lumbar strain" in md
    assert "SECONDARY" in md


@pytest.mark.parametrize(
    "bad",
    [
        {},  # no condition
        {"veteran_name": "A"},  # no condition
        {"condition": ""},  # empty condition
        {"claim_type": "secondary", "secondary_to": "back pain"},  # no condition
    ],
)
def test_draft_rejects_missing_condition(client, bad):
    assert client.post("/api/nexus/draft", json=bad).status_code == 422
