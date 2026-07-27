"""API tests for POST /rating/calculate — no Postgres required.

The calculate endpoint is deliberately DB-free (pure engine call behind auth),
so we mount the rating router on a bare FastAPI app and override the auth
dependency. Scenario CRUD needs a real database and is exercised in deployment
smoke tests, not here.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import rating  # noqa: E402

FAKE_UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(rating.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = lambda: FAKE_UID
    return TestClient(app)


def _calc(client: TestClient, entries: list[dict]) -> dict:
    resp = client.post("/api/rating/calculate", json={"entries": entries})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_single_rating(client):
    data = _calc(client, [{"label": "PTSD", "percent": 50}])
    assert data["combined"] == 50
    assert data["raw"] == 50


def test_va_math_50_30(client):
    """The canonical §4.25 example: 50 + 30 → raw 65 → final 70."""
    data = _calc(client, [{"label": "A", "percent": 50}, {"label": "B", "percent": 30}])
    assert data["raw"] == 65
    assert data["combined"] == 70
    assert any(s["kind"] == "round" for s in data["steps"])


def test_bilateral_factor_applied(client):
    """§4.26 regulation example: 60 + 20 paired → 68 + 6.8 = 74.8 → 75."""
    data = _calc(
        client,
        [
            {"label": "Left knee", "percent": 60, "side": "left"},
            {"label": "Right knee", "percent": 20, "side": "right"},
        ],
    )
    assert data["bilateral_factor_applied"] is True
    assert data["bilateral_value"] == 75
    assert data["combined"] == 80  # 75 raw → final-round 80 (ends in 5, rounds up)


def test_one_sided_entries_get_no_bilateral_factor(client):
    data = _calc(
        client,
        [
            {"label": "Left knee", "percent": 20, "side": "left"},
            {"label": "Left ankle", "percent": 10, "side": "left"},
        ],
    )
    assert data["bilateral_factor_applied"] is False


def test_zero_ratings_do_not_move_combined(client):
    data = _calc(
        client,
        [{"label": "Tinnitus", "percent": 10}, {"label": "Scar", "percent": 0}],
    )
    assert data["combined"] == 10
    assert any(s["kind"] == "note" for s in data["steps"])


def test_percent_validation_422(client):
    resp = client.post(
        "/api/rating/calculate", json={"entries": [{"label": "X", "percent": 150}]}
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/rating/calculate", json={"entries": [{"label": "X", "percent": -5}]}
    )
    assert resp.status_code == 422


def test_side_validation_422(client):
    resp = client.post(
        "/api/rating/calculate",
        json={"entries": [{"label": "X", "percent": 10, "side": "middle"}]},
    )
    assert resp.status_code == 422


def test_empty_entries_422(client):
    resp = client.post("/api/rating/calculate", json={"entries": []})
    assert resp.status_code == 422


def test_requires_auth():
    """Without the dependency override, the endpoint 401s/403s (no bearer)."""
    app = FastAPI()
    app.include_router(rating.router, prefix="/api")
    client = TestClient(app)
    resp = client.post(
        "/api/rating/calculate", json={"entries": [{"label": "X", "percent": 10}]}
    )
    assert resp.status_code in (401, 403)


def test_smc_flags_educational(client):
    """100% + independent 60% should raise the SMC-S educational pointer."""
    data = _calc(
        client,
        [{"label": "Condition A", "percent": 100}, {"label": "Condition B", "percent": 60}],
    )
    keys = {f["key"] for f in data["smc_flags"]}
    assert "smc_s" in keys
    smc_s = next(f for f in data["smc_flags"] if f["key"] == "smc_s")
    assert smc_s["source"] == "38 CFR §3.350(i)"
