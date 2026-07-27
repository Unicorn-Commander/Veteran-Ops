"""Back-pay estimator tests — rate table integrity, §3.31 logic, COLA
boundaries, dependent changes, excluded-year gaps, and the API endpoint.

Anchor values below were spot-verified 2026-07-05 against TWO independent
fetches of the official VA.gov pages (WebFetch content read + raw-HTML table
parse of the same URLs). Do not edit anchors without re-fetching VA.gov.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.rating import backpay as bp
from app.rating.backpay import Dependents, RatingPeriod, compute_backpay
from app.rating.rates_data import (
    available_rate_years,
    load_rates,
    monthly_rate,
    rate_year_for,
)

D = Decimal


# --- table integrity -------------------------------------------------------

def test_table_loads_all_years():
    assert available_rate_years() == list(range(2018, 2027))
    data = load_rates()["rate_years"]
    combos = {"alone", "spouse", "spouse_1_parent", "spouse_2_parents", "one_parent", "two_parents"}
    for y, d in data.items():
        assert d["source_url"].startswith("https://www.va.gov/disability/compensation-rates/veteran-rates")
        assert d["fetched"]
        # rate year Y is effective Dec 1 of Y-1
        assert d["effective_date"] == f"{int(y) - 1}-12-01"
        assert set(d["flat"]) == {"10", "20"}
        for pct in ("30", "40", "50", "60", "70", "80", "90", "100"):
            assert set(d["base_no_children"][pct]) == combos
            assert set(d["base_with_1_child"][pct]) == combos
            assert set(d["added"][pct]) == {"child_under_18", "child_over_18_school", "spouse_aa"}


def test_anchor_values_match_va_gov():
    """Spot-checked anchors, each verified across two independent fetches.

    - 2025 rate year (eff. 2024-12-01), 100% veteran alone = $3,831.30
      source: https://www.va.gov/disability/compensation-rates/veteran-rates/past-rates-2025/
    - 2023 rate year (eff. 2022-12-01), 10% = $165.92
      source: https://www.va.gov/disability/compensation-rates/veteran-rates/past-rates-2023/
    - 2024 rate year (eff. 2023-12-01), 100% veteran alone = $3,737.85
      source: https://www.va.gov/disability/compensation-rates/veteran-rates/past-rates-2024/
    - 2026 rate year (eff. 2025-12-01), 100% veteran alone = $3,938.58
      source: https://www.va.gov/disability/compensation-rates/veteran-rates/ (fetched 2026-07-05)
    """
    ry = load_rates()["rate_years"]
    assert ry["2025"]["base_no_children"]["100"]["alone"] == "3831.30"
    assert ry["2023"]["flat"]["10"] == "165.92"
    assert ry["2024"]["base_no_children"]["100"]["alone"] == "3737.85"
    assert ry["2026"]["base_no_children"]["100"]["alone"] == "3938.58"


def test_rate_year_boundaries():
    assert rate_year_for(date(2024, 11, 1)) == 2024
    assert rate_year_for(date(2024, 12, 1)) == 2025  # COLA effective Dec 1
    assert rate_year_for(date(2025, 1, 1)) == 2025


def test_monthly_rate_dependents_math():
    ry = load_rates()["rate_years"]["2026"]
    m = date(2026, 1, 1)  # rate year 2026
    # 10/20 flat regardless of dependents
    assert monthly_rate(m, 10, Dependents(spouse=True, parents=2)) == D(ry["flat"]["10"])
    # base combos
    assert monthly_rate(m, 100, Dependents()) == D(ry["base_no_children"]["100"]["alone"])
    assert monthly_rate(m, 100, Dependents(spouse=True, parents=2)) == D(
        ry["base_no_children"]["100"]["spouse_2_parents"]
    )
    # first child = with-1-child row; extras use added amounts; spouse A&A adds
    expected = (
        D(ry["base_with_1_child"]["100"]["spouse"])
        + 1 * D(ry["added"]["100"]["child_under_18"])
        + 1 * D(ry["added"]["100"]["child_over_18_school"])
        + D(ry["added"]["100"]["spouse_aa"])
    )
    got = monthly_rate(
        m, 100,
        Dependents(spouse=True, children_under_18=2, children_in_school=1, spouse_aa=True),
    )
    assert got == expected
    # only school-age children: one fills the base-row slot
    only_school = monthly_rate(m, 70, Dependents(children_in_school=2))
    assert only_school == D(ry["base_with_1_child"]["70"]["alone"]) + D(
        ry["added"]["70"]["child_over_18_school"]
    )


def test_monthly_rate_validation():
    with pytest.raises(ValueError):
        monthly_rate(date(2025, 1, 1), 55, Dependents())
    with pytest.raises(ValueError):
        monthly_rate(date(2025, 1, 1), 30, Dependents(spouse_aa=True))  # A&A without spouse
    with pytest.raises(ValueError):
        monthly_rate(date(2025, 1, 1), 30, Dependents(parents=3))
    assert monthly_rate(date(2010, 5, 1), 30, Dependents()) is None  # uncovered year


# --- §3.31 month-after rule ------------------------------------------------

def test_331_month_after_effective_date():
    out = compute_backpay(
        [RatingPeriod(from_date=date(2024, 1, 15), combined_percent=10)],
        today=date(2024, 5, 10),
    )
    months = [m["month"] for m in out["months"]]
    assert months == ["2024-02", "2024-03", "2024-04"]  # Feb first; April = last full month
    assert "3.31" in out["months"][0]["note"]
    assert any("3.31" in a for a in out["assumptions"])


def test_331_effective_on_first_of_month_still_waits():
    out = compute_backpay(
        [RatingPeriod(from_date=date(2024, 3, 1), combined_percent=10)],
        today=date(2024, 6, 15),
    )
    assert [m["month"] for m in out["months"]] == ["2024-04", "2024-05"]


# --- multi-year scenario across a COLA boundary ----------------------------

def test_cola_boundary_multi_year():
    ry = load_rates()["rate_years"]
    out = compute_backpay(
        [RatingPeriod(from_date=date(2024, 10, 15), combined_percent=70)],
        today=date(2025, 2, 10),
    )
    by_month = {m["month"]: m for m in out["months"]}
    assert list(by_month) == ["2024-11", "2024-12", "2025-01"]
    assert by_month["2024-11"]["rate"] == float(D(ry["2024"]["base_no_children"]["70"]["alone"]))
    # December is paid at the NEW rate year (COLA effective Dec 1, not delayed by §3.31)
    assert by_month["2024-12"]["rate"] == float(D(ry["2025"]["base_no_children"]["70"]["alone"]))
    assert by_month["2024-12"]["rate_year"] == 2025
    assert "COLA" in by_month["2024-12"]["note"]
    assert by_month["2025-01"]["rate"] == by_month["2024-12"]["rate"]
    total = sum(D(str(m["rate"])) for m in out["months"])
    assert out["total"] == float(total)
    assert set(out["by_year_subtotals"]) == {"2024", "2025"}


# --- dependent-status change mid-stream ------------------------------------

def test_dependent_change_mid_stream():
    ry = load_rates()["rate_years"]["2024"]
    out = compute_backpay(
        [
            RatingPeriod(from_date=date(2024, 1, 10), to_date=date(2024, 4, 20),
                         combined_percent=50),
            RatingPeriod(from_date=date(2024, 4, 20), combined_percent=50,
                         dependents=Dependents(spouse=True)),
        ],
        today=date(2024, 7, 3),
    )
    by_month = {m["month"]: m for m in out["months"]}
    alone = float(D(ry["base_no_children"]["50"]["alone"]))
    spouse = float(D(ry["base_no_children"]["50"]["spouse"]))
    # spouse added effective 4/20 → higher rate starts with May (§3.31)
    assert [by_month[k]["rate"] for k in ("2024-02", "2024-03", "2024-04")] == [alone] * 3
    assert [by_month[k]["rate"] for k in ("2024-05", "2024-06")] == [spouse] * 2


# --- excluded rate-year gap handling ----------------------------------------

def test_excluded_year_gap():
    out = compute_backpay(
        [RatingPeriod(from_date=date(2016, 6, 10), combined_percent=30)],
        today=date(2017, 4, 5),
    )
    # ledger Jul 2016 .. Mar 2017: rate years 2016 (Jul–Nov 2016) and 2017
    # (Dec 2016–Mar 2017) are both uncovered → every month is a gap
    assert all(m["rate"] is None for m in out["months"])
    assert out["total"] == 0.0
    assert len(out["excluded_months"]) == len(out["months"]) == 9
    assert "excluded from totals" in out["months"][0]["note"]

    # mixed: effective Oct 2017 → Nov 2017 uncovered (rate year 2017),
    # Dec 2017 onward covered (rate year 2018)
    out2 = compute_backpay(
        [RatingPeriod(from_date=date(2017, 10, 3), combined_percent=30)],
        today=date(2018, 2, 14),
    )
    by_month = {m["month"]: m for m in out2["months"]}
    assert by_month["2017-11"]["rate"] is None
    assert out2["excluded_months"] == ["2017-11"]
    ry2018 = load_rates()["rate_years"]["2018"]
    assert by_month["2017-12"]["rate"] == float(D(ry2018["base_no_children"]["30"]["alone"]))
    assert out2["total"] == pytest.approx(
        float(D(ry2018["base_no_children"]["30"]["alone"]) * 2)
    )


# --- payment_already_received netting ---------------------------------------

def test_received_offset_netting():
    ry = load_rates()["rate_years"]["2024"]
    out = compute_backpay(
        [RatingPeriod(from_date=date(2023, 12, 20), combined_percent=70)],
        received=[RatingPeriod(from_date=date(2023, 12, 20), combined_percent=50)],
        today=date(2024, 4, 2),
    )
    r70 = D(ry["base_no_children"]["70"]["alone"])
    r50 = D(ry["base_no_children"]["50"]["alone"])
    assert [m["month"] for m in out["months"]] == ["2024-01", "2024-02", "2024-03"]
    for m in out["months"]:
        assert m["net"] == float(r70 - r50)
    assert out["entitled_total"] == float(r70 * 3)
    assert out["received_total"] == float(r50 * 3)
    assert out["total"] == float((r70 - r50) * 3)


# --- guardrails --------------------------------------------------------------

def test_educational_guardrails_present():
    out = compute_backpay(
        [RatingPeriod(from_date=date(2025, 1, 5), combined_percent=10)],
        today=date(2025, 3, 1),
    )
    text = " ".join(out["assumptions"])
    assert "3.31" in text
    assert "COLA" in text
    assert "award letter" in text.lower()
    nm = " ".join(out["not_modeled"])
    for term in ("SMC", "Apportionment", "severance", "CRDP", "CRSC", "Incarceration"):
        assert term in nm
    assert set(out["rate_sources"]) == {str(y) for y in range(2018, 2027)}


def test_input_validation():
    with pytest.raises(ValueError):
        compute_backpay([])
    with pytest.raises(ValueError):
        compute_backpay([RatingPeriod(from_date=date(2024, 1, 1), combined_percent=55)])
    with pytest.raises(ValueError):
        compute_backpay([
            RatingPeriod(from_date=date(2024, 5, 1), to_date=date(2024, 1, 1),
                         combined_percent=30)
        ])


# --- endpoint ----------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import rating  # noqa: E402

FAKE_UID = "00000000-0000-0000-0000-000000000001"


class _FakeDB:
    """Stub session for the audit write (add + flush only)."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


@pytest.fixture()
def client_db():
    app = FastAPI()
    app.include_router(rating.router, prefix="/api")
    fake = _FakeDB()

    async def _fake_db():
        yield fake

    app.dependency_overrides[deps.current_user_id] = lambda: FAKE_UID
    app.dependency_overrides[deps.get_db] = _fake_db
    return TestClient(app), fake


def test_backpay_endpoint(client_db):
    client, fake = client_db
    resp = client.post("/api/rating/backpay", json={
        "periods": [
            {"from_date": "2024-06-10", "combined_percent": 70,
             "dependents": {"spouse": True, "children_under_18": 1}},
        ],
        "end_date": "2025-01-31",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["months"][0]["month"] == "2024-07"
    assert data["total"] > 0
    assert data["total"] == data["entitled_total"]
    assert any("3.31" in a for a in data["assumptions"])
    assert data["not_modeled"]
    # audited
    assert len(fake.added) == 1
    assert fake.added[0].action == "rating.backpay"


def test_backpay_endpoint_aliases_and_received(client_db):
    client, _ = client_db
    # short aliases from the spec: {from, to, percent}
    resp = client.post("/api/rating/backpay", json={
        "periods": [{"from": "2024-06-10", "percent": 70}],
        "payment_already_received": [{"from": "2024-06-10", "percent": 50}],
        "end_date": "2024-10-31",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["received_total"] > 0
    assert data["total"] == pytest.approx(data["entitled_total"] - data["received_total"])


def test_backpay_endpoint_validation(client_db):
    client, _ = client_db
    resp = client.post("/api/rating/backpay", json={
        "periods": [{"from_date": "2024-06-10", "combined_percent": 55}],
    })
    assert resp.status_code == 422
    resp = client.post("/api/rating/backpay", json={"periods": []})
    assert resp.status_code == 422
