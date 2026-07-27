"""WAVE8 — Game Plan strategy engine. Pure-engine unit tests (no DB) + the /strategy
endpoint on the SQLite harness. Legal lane is asserted: NO outcome-promise language,
every estimate carries its basis label.
"""

from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from app.strategy.plan import build_game_plan

# ── Pure engine unit tests (no DB, no network) ───────────────────────────────

_GEN = "2026-07-06T00:00:00+00:00"

# Language that would cross the legal lane — must never appear anywhere in a plan.
_PROMISE = re.compile(
    r"\b(you will (?:get|receive|be granted|qualify)|guarantee|guaranteed|"
    r"we will file|approved for|entitled to \d|100% chance|definitely)\b",
    re.IGNORECASE,
)


def _cond(**kw):
    base = dict(id=str(uuid.uuid4()), name="X", claim_type="direct", status="considering",
                current_rating=None, target_rating=None, band="early", missing=[],
                has_have_evidence=False)
    base.update(kw)
    return base


def _plan(**kw):
    args = dict(conditions=[], denials=[], suggestions=[], active_itf=None,
                current_combined=None, generated_at=_GEN)
    args.update(kw)
    return build_game_plan(**args)


def _no_promises(plan):
    blob = str(plan)
    assert not _PROMISE.search(blob), f"promise language leaked: {_PROMISE.search(blob).group()!r}"


def test_empty_account_is_graceful():
    p = _plan()
    assert p["has_conditions"] is False
    assert p["pathways"] == []
    assert p["priority_actions"] == []
    assert p["snapshot"]["conditions_total"] == 0
    assert p["disclaimer"] and p["vso_referral"]
    _no_promises(p)


def test_ready_condition_yields_file_now_recommended_and_estimate():
    ready = _cond(name="Tinnitus", band="complete", target_rating=10)
    # An already-decided condition contributes its current rating to the baseline
    # (it's not re-pursued on this path).
    existing = _cond(name="PTSD", status="decided", band="complete", current_rating=50)
    p = _plan(conditions=[ready, existing])
    keys = {pw["key"]: pw for pw in p["pathways"]}
    assert "file_now" in keys
    assert keys["file_now"]["recommended"] is True
    # exactly one recommended
    assert sum(1 for pw in p["pathways"] if pw["recommended"]) == 1
    # file_now includes only the claimable ready one (PTSD is already decided)
    fn = keys["file_now"]
    assert fn["included_conditions"] == ["Tinnitus"]
    # estimate is real §4.25 math and carries its basis label
    assert isinstance(fn["estimated_combined"], int)
    assert "§4.25" in fn["estimated_combined_basis"]
    assert "not a prediction" in fn["estimated_combined_basis"].lower()
    # baseline PTSD(50) + Tinnitus pursued at target(10) → combine(50,10)=55
    assert fn["estimated_combined"] == 55
    _no_promises(p)


def test_no_target_ratings_gives_none_estimate_with_honest_basis():
    c = _cond(name="Knee", band="complete")  # no current, no target
    p = _plan(conditions=[c])
    fn = next(pw for pw in p["pathways"] if pw["key"] == "file_now")
    assert fn["estimated_combined"] is None
    assert "target rating" in fn["estimated_combined_basis"].lower()
    _no_promises(p)


def test_building_band_gets_its_label_not_the_fallback():
    """The engine emits early|building|strong|complete. A 'building' condition must
    render its warm label — regression guard for the stale 'moderate' key that made
    the most common in-progress state read the generic 'In progress' fallback."""
    c = _cond(name="Hip", band="building", missing=["A nexus opinion"])
    p = _plan(conditions=[c])
    line = next(l for l in p["condition_lines"] if l["name"] == "Hip")
    assert line["band"] == "building"
    assert line["band_label"] == "Coming together"


def test_ready_increase_without_target_still_counts_at_current_rating():
    """A ready increase claim with a real current rating but no target set must not
    vanish from the file_now estimate (which would read lower than the veteran's
    actual combined) — it falls back to its current rating."""
    c = _cond(name="CFS", claim_type="increase", band="complete", current_rating=60, target_rating=None)
    p = _plan(conditions=[c])
    fn = next(pw for pw in p["pathways"] if pw["key"] == "file_now")
    assert fn["estimated_combined"] == 60  # not None, not dropped
    _no_promises(p)


# ── Rating-strategy intelligence (§4.14 / §4.130 / §4.16 / §3.344) ────────────

def test_already_granted_condition_is_not_ready_to_file():
    """A VA-service-connected condition must never show as 'ready to file' — it's
    already granted. Regression for 'Ready to file for things already approved'."""
    granted = _cond(name="Chronic Fatigue Syndrome", band="complete",
                    va_status="service_connected", current_rating=60)
    p = _plan(conditions=[granted], current_combined=60)
    # not in the file_now ready set / count
    assert p["snapshot"]["ready_count"] == 0
    assert not any(pw["key"] == "file_now" for pw in p["pathways"])
    assert not any(a["category"] == "file" for a in p["priority_actions"])
    _no_promises(p)


def test_increase_on_granted_condition_is_still_claimable():
    """An increase claim on a service-connected condition is legitimate (unlike a
    re-file), so it is NOT excluded from ready."""
    inc = _cond(name="CFS", claim_type="increase", band="complete",
                va_status="service_connected", current_rating=60, target_rating=100)
    p = _plan(conditions=[inc], current_combined=60)
    assert p["snapshot"]["ready_count"] == 1


def test_cfs_and_fibromyalgia_are_separately_ratable_not_pyramiding():
    """CORRECTED (was a false positive): CFS (DC 6354, §4.88b) and fibromyalgia
    (DC 5025, §4.71a) are DIFFERENT body systems and can be rated SEPARATELY when
    distinct symptoms support each. A granted CFS must NOT trigger a §4.14
    pyramiding caution against fibromyalgia — it surfaces an UNDER-RATING
    opportunity instead (Esteban-positive)."""
    cfs = _cond(name="Chronic Fatigue Syndrome", band="complete",
                va_status="service_connected", current_rating=60, diagnostic_code="6354")
    fibro = _cond(name="Fibromyalgia", band="early", va_status="denied", diagnostic_code="5025")
    p = _plan(conditions=[cfs, fibro], current_combined=60)
    assert not [c for c in p["cautions"] if c["kind"] == "pyramiding"], \
        "CFS/fibromyalgia must not be flagged as pyramiding"
    under = [o for o in p["opportunities"] if o["kind"] == "underrating"]
    assert any("cfs_and_fibromyalgia" in o["key"] for o in under), \
        "expected a CFS/fibromyalgia separate-rating opportunity"
    _no_promises(p)


def test_secondary_hypertension_to_granted_ptsd():
    """Game Plan now catches HTN as a §3.310 secondary theory to granted PTSD —
    previously present only in the analysis map, silently missing from the Game
    Plan's own secondary-opportunity finder. Denied → reclaim card."""
    ptsd = _cond(name="PTSD", band="complete", va_status="service_connected",
                 current_rating=50, diagnostic_code="9411")
    htn = _cond(name="Hypertension", band="early", va_status="denied", diagnostic_code="7101")
    p = _plan(conditions=[ptsd, htn], current_combined=50)
    opps = [o for o in p["opportunities"] if o["kind"] in ("secondary", "reclaim")]
    assert any("hypertension" in str(o).lower() for o in opps), \
        "expected an HTN-secondary-to-PTSD opportunity"
    _no_promises(p)


def test_mental_health_one_rating_caution():
    """PTSD + anxiety + depression together → a §4.130 'one combined mental rating'
    caution (they are not stacked)."""
    conds = [
        _cond(name="PTSD", band="strong", diagnostic_code="9411"),
        _cond(name="Unspecified anxiety disorder", band="early"),
        _cond(name="Major depressive disorder", band="early"),
    ]
    p = _plan(conditions=conds)
    mh = [c for c in p["cautions"] if "4.130" in c["reg"]]
    assert mh, "expected a §4.130 mental-health caution"


def test_no_pyramiding_caution_for_unrelated_conditions():
    p = _plan(conditions=[_cond(name="Tinnitus", band="complete"),
                          _cond(name="Left knee strain", band="early")])
    assert not any(c["kind"] == "pyramiding" for c in p["cautions"])


def test_reduction_caution_when_holding_a_granted_rating():
    granted = _cond(name="GERD", band="complete", va_status="service_connected", current_rating=10)
    p = _plan(conditions=[granted], current_combined=10)
    red = [c for c in p["cautions"] if c["kind"] == "reduction"]
    assert red and "3.951" in red[0]["reg"]
    # never predicts a reduction
    assert "will be reduced" not in red[0]["body"].lower()


def test_secondary_opportunity_anxiety_to_granted_cfs():
    """Aaron's case: ME/CFS is service-connected; anxiety was DENIED on a direct
    basis. The plan should CATCH anxiety as a RECLAIM on a §3.310 secondary theory —
    high severity (denied) — with supplemental attach checklist, without asserting
    the link or predicting an outcome."""
    cfs = _cond(name="ME/CFS", band="complete", va_status="service_connected",
                current_rating=60, diagnostic_code="6354")
    anxiety = _cond(name="Anxiety disorder", band="early", va_status="denied")
    p = _plan(conditions=[cfs, anxiety], current_combined=60)
    reclaim = [o for o in p["opportunities"] if o["kind"] == "reclaim"]
    assert reclaim, "expected a reclaim opportunity for denied anxiety"
    assert reclaim[0]["severity"] == "high"
    assert "3.310" in reclaim[0]["reg"]
    assert reclaim[0]["needs_nexus"] is True
    assert reclaim[0].get("pathway") == "supplemental"
    assert reclaim[0].get("attach_checklist"), "expected attach checklist on reclaim"
    # It becomes an actionable step, not just a note.
    assert any(
        "reclaim" in a["title"].lower() or "secondary" in a["title"].lower()
        for a in p["priority_actions"]
    )
    _no_promises(p)


def test_cfs_fibro_filing_tradeoff_caution_when_both_present():
    """CFS granted + fibro in record → filing_tradeoff caution (not pyramiding)."""
    cfs = _cond(name="Chronic Fatigue Syndrome", band="complete",
                va_status="service_connected", current_rating=60, diagnostic_code="6354")
    fibro = _cond(name="Fibromyalgia", band="early", va_status="denied", diagnostic_code="5025")
    p = _plan(conditions=[cfs, fibro], current_combined=60)
    trade = [c for c in p["cautions"] if c["kind"] == "filing_tradeoff"]
    assert trade, "expected CFS/fibro filing trade-off caution"
    assert not [c for c in p["cautions"] if c["kind"] == "pyramiding"]
    _no_promises(p)


def test_tdiu_employment_caution_when_schedular_door_open():
    """Single SC disability at 60% → TDIU screen + employment caution."""
    cfs = _cond(name="ME/CFS", band="complete", va_status="service_connected",
                current_rating=60, diagnostic_code="6354")
    p = _plan(conditions=[cfs], current_combined=60)
    assert p["tdiu"] and p["tdiu"]["eligible_schedular"] is True
    emp = [c for c in p["cautions"] if c["kind"] == "tdiu_employment"]
    assert emp, "expected TDIU employment caution when door is open"
    assert "will be reduced" not in emp[0]["body"].lower()
    assert "stop working" not in emp[0]["body"].lower()
    _no_promises(p)


def test_no_secondary_opportunity_when_effect_already_granted():
    """If the mental-health condition is already service-connected, there's nothing
    new to surface."""
    cfs = _cond(name="ME/CFS", va_status="service_connected", current_rating=60,
                diagnostic_code="6354")
    dep = _cond(name="Depression", va_status="service_connected", current_rating=30)
    p = _plan(conditions=[cfs, dep], current_combined=70)
    assert not [o for o in p["opportunities"] if o["kind"] == "secondary"]


def test_underrating_opportunity_knee_instability_and_motion():
    """A granted knee condition surfaces the Esteban-positive separate-rating hint
    (instability + limitation of motion can each be rated)."""
    knee = _cond(name="Right knee instability", band="complete",
                 va_status="service_connected", current_rating=10, diagnostic_code="5257")
    p = _plan(conditions=[knee], current_combined=10)
    under = [o for o in p["opportunities"] if o["kind"] == "underrating"]
    assert under, "expected an Esteban under-rating opportunity"
    assert "Esteban" in under[0]["reg"]
    _no_promises(p)


def _under(p):
    return [o for o in p["opportunities"] if o["kind"] == "underrating"]


def test_underrating_radiculopathy_separate_from_spine():
    """The single most commonly missed separation: a granted back/neck condition and
    the §4.71a Note 1 radiculopathy separate rating (its own cite, not the §4.14 default)."""
    back = _cond(name="Lumbar degenerative disc disease", band="complete",
                 va_status="service_connected", current_rating=20, diagnostic_code="5242")
    p = _plan(conditions=[back], current_combined=20)
    hit = next((o for o in _under(p) if "radiculopathy" in o["title"].lower()), None)
    assert hit, "expected a radiculopathy separate-rating opportunity"
    assert "4.71a" in hit["reg"]
    assert hit["needs_nexus"] is False
    _no_promises(p)


def test_underrating_diabetic_complications_separate():
    dm = _cond(name="Diabetes mellitus type 2", band="complete",
               va_status="service_connected", current_rating=20, diagnostic_code="7913")
    p = _plan(conditions=[dm], current_combined=20)
    assert any("4.119" in o["reg"] for o in _under(p))
    _no_promises(p)


def test_underrating_tinnitus_separate_from_hearing_loss():
    hl = _cond(name="Bilateral hearing loss", band="complete",
               va_status="service_connected", current_rating=0, diagnostic_code="6100")
    p = _plan(conditions=[hl], current_combined=0)
    assert any("tinnitus" in o["title"].lower() for o in _under(p))
    _no_promises(p)


def test_underrating_smc_k_for_granted_ed():
    ed = _cond(name="Erectile dysfunction", band="complete",
               va_status="service_connected", current_rating=0, diagnostic_code="7522")
    p = _plan(conditions=[ed], current_combined=0)
    assert any("SMC-K" in o["title"] or "1114(k)" in o["reg"] for o in _under(p))
    _no_promises(p)


def test_underrating_wound_muscle_nerve_scar_separate():
    wound = _cond(name="Shrapnel wound, muscle group XIII", band="complete",
                  va_status="service_connected", current_rating=10, diagnostic_code="5313")
    p = _plan(conditions=[wound], current_combined=10)
    assert any("muscle" in o["title"].lower() for o in _under(p))
    _no_promises(p)


def test_underrating_requires_a_granted_primary():
    """Findings originate only from a GRANTED primary — a denied/unclaimed spine
    condition must NOT surface the radiculopathy separation."""
    back = _cond(name="Lumbar strain", va_status="denied", diagnostic_code="5237")
    p = _plan(conditions=[back])
    assert _under(p) == []


def test_no_opportunities_for_unrelated_granted_conditions():
    p = _plan(conditions=[_cond(name="Tinnitus", va_status="service_connected",
                                current_rating=10, diagnostic_code="6260")])
    assert p["opportunities"] == []


def test_tdiu_screen_fires_at_single_60():
    """One SC disability at 60% meets §4.16(a) → TDIU screen present + eligible."""
    cfs = _cond(name="CFS", band="complete", va_status="service_connected", current_rating=60)
    p = _plan(conditions=[cfs], current_combined=60)
    assert p["tdiu"] is not None
    assert p["tdiu"]["eligible_schedular"] is True
    assert "21-8940" in p["tdiu"]["form"]
    _no_promises(p)


def test_tdiu_absent_when_far_below_threshold():
    c = _cond(name="Tinnitus", band="complete", va_status="service_connected", current_rating=10)
    p = _plan(conditions=[c], current_combined=10)
    assert p["tdiu"] is None


def test_gaps_yield_strengthen_and_close_gap_actions():
    c = _cond(name="Back", band="early", missing=["A nexus opinion linking it to service"])
    p = _plan(conditions=[c])
    assert any(pw["key"] == "strengthen_first" for pw in p["pathways"])
    gap_actions = [a for a in p["priority_actions"] if a["category"] == "close_gap"]
    assert gap_actions and gap_actions[0]["condition_name"] == "Back"
    assert gap_actions[0]["impact"] == "high"  # early band → high
    assert gap_actions[0]["link"] == f"/conditions/{c['id']}"
    _no_promises(p)


def test_no_itf_surfaces_high_protect_backpay_action_first():
    c = _cond(name="PTSD", band="strong", target_rating=50)
    p = _plan(conditions=[c], active_itf=None)
    assert p["priority_actions"][0]["category"] == "protect_backpay"
    assert p["priority_actions"][0]["impact"] == "high"
    # with an active ITF, that action is gone
    p2 = _plan(conditions=[c], active_itf={"type": "compensation", "deadline": "2027-01-01", "days_remaining": 180})
    assert all(a["category"] != "protect_backpay" for a in p2["priority_actions"])


def test_denials_yield_appeal_pathway_and_action_no_estimate():
    c = _cond(name="PTSD", band="strong", has_have_evidence=True)
    p = _plan(conditions=[c],
              denials=[{"name": "PTSD", "missing_elements": ["nexus"]}])
    ap = next(pw for pw in p["pathways"] if pw["key"] == "appeal_denials")
    assert ap["estimated_combined"] is None  # appeals never get a numeric estimate
    appeal_actions = [a for a in p["priority_actions"] if a["category"] == "appeal"]
    assert appeal_actions and appeal_actions[0]["impact"] == "high"  # has evidence
    assert appeal_actions[0]["link"] == "/appeals"
    _no_promises(p)


def test_denied_va_status_yields_appeal_pathway_and_supplemental_action():
    # A condition the veteran/VA recorded as denied — with NO decoded letter — still
    # routes to the "Respond to your denials" path + a Supplemental Claim action.
    c = _cond(name="Sleep apnea", band="strong", va_status="denied")
    p = _plan(conditions=[c])
    assert any(pw["key"] == "appeal_denials" for pw in p["pathways"])
    assert p["snapshot"]["denied_count"] == 1
    appeal_titles = [a["title"] for a in p["priority_actions"] if a["category"] == "appeal"]
    assert "Start a Supplemental Claim for Sleep apnea" in appeal_titles
    _no_promises(p)


def test_denied_condition_not_double_listed_with_decoded_letter_denial():
    # The same condition denied in a decoded letter AND flagged va_status='denied'
    # must be deduped by name — one denial, one appeal action, one included entry.
    c = _cond(name="PTSD", band="strong", va_status="denied")
    p = _plan(conditions=[c], denials=[{"name": "PTSD", "missing_elements": ["nexus"]}])
    assert p["snapshot"]["denied_count"] == 1
    ap = next(pw for pw in p["pathways"] if pw["key"] == "appeal_denials")
    assert ap["included_conditions"] == ["PTSD"]
    appeal_titles = [a["title"] for a in p["priority_actions"] if a["category"] == "appeal"]
    assert appeal_titles == ["Start a Supplemental Claim for PTSD"]
    _no_promises(p)


def test_condition_lines_include_va_status():
    sc = _cond(name="Knee", band="early", va_status="service_connected", missing=["x"])
    plain = _cond(name="Back", band="early", missing=["y"])  # no va_status → unknown
    p = _plan(conditions=[sc, plain])
    by_name = {l["name"]: l for l in p["condition_lines"]}
    assert by_name["Knee"]["va_status"] == "service_connected"
    assert by_name["Back"]["va_status"] == "unknown"


def test_suggestions_yield_add_conditions_pathway():
    c = _cond(name="PTSD", band="strong", target_rating=50)
    sug = [{"name": "Sleep apnea", "relation": "secondary to PTSD", "kind": "secondary"}]
    p = _plan(conditions=[c], suggestions=sug)
    add = next(pw for pw in p["pathways"] if pw["key"] == "add_conditions")
    assert "Sleep apnea" in add["included_conditions"]
    assert any(a["category"] == "add_condition" and a["link"] == "/secondaries"
               for a in p["priority_actions"])
    _no_promises(p)


def test_actions_sorted_high_before_medium_and_capped():
    conds = [_cond(name=f"C{i}", band="building",
                   missing=[f"gap {i}"]) for i in range(20)]
    p = _plan(conditions=conds, active_itf=None)
    impacts = [a["impact"] for a in p["priority_actions"]]
    order = {"high": 0, "medium": 1, "low": 2}
    assert impacts == sorted(impacts, key=lambda x: order[x])
    assert len(p["priority_actions"]) <= 12


def test_strong_band_with_a_gap_is_not_ready_to_file():
    # A "strong" band (67-99) still has one §3.303 element missing — it must NOT be
    # called ready-to-file, and must not produce both a "file" and a "close gap"
    # action for the same condition (review finding 1).
    c = _cond(name="Back", claim_type="direct", band="strong",
              missing=["a medical link (nexus)"])
    p = _plan(conditions=[c])
    assert all(pw["key"] != "file_now" for pw in p["pathways"])
    assert any(pw["key"] == "strengthen_first" for pw in p["pathways"])
    cats = {a["category"] for a in p["priority_actions"]}
    assert "file" not in cats and "close_gap" in cats
    _no_promises(p)


def test_all_filed_conditions_get_a_track_fallback():
    # Everything already with VA → not an empty page; a "track your claims" plan.
    c = _cond(name="PTSD", status="decided", band="complete", current_rating=50)
    p = _plan(conditions=[c], active_itf={"type": "compensation",
                                          "deadline": "2027-01-01", "days_remaining": 200})
    assert p["has_conditions"] is True
    assert [pw["key"] for pw in p["pathways"]] == ["track_progress"]
    assert p["pathways"][0]["recommended"] is True
    assert p["priority_actions"] and p["priority_actions"][0]["category"] == "track"
    _no_promises(p)


# ── Endpoint test on the SQLite harness ──────────────────────────────────────

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import strategy as strategy_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


@compiles(PGUUID, "sqlite")
def _u(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _j(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _v(type_, compiler, **kw):  # noqa: ANN001, ANN003
        return "TEXT"


_TABLES = [
    models.User.__table__, models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__, models.EvidenceItem.__table__,
    models.ItfRecord.__table__, models.Document.__table__,
    models.KBCard.__table__, models.GamePlanFirmCache.__table__,
]
for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

UA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
UB = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
C_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=UA, email="a@e.test", password_hash="x", full_name="Alex V"),
                models.User(id=UB, email="b@e.test", password_hash="x", full_name="Blair O"),
                models.VeteranProfile(user_id=UA, current_combined_rating=50,
                                      service_periods=[], exposures={}),
                models.ClaimedCondition(id=C_PTSD, user_id=UA, name="PTSD",
                                        claim_type="direct", current_rating=50,
                                        target_rating=70,
                                        in_service_event="IED blast"),
                models.ClaimedCondition(user_id=UB, name="Back strain", claim_type="direct"),
            ])
            # PTSD has all three §3.303 elements → readiness complete → file_now.
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_PTSD, kind="diagnosis",
                                      title="Dx", status="have"))
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_PTSD, kind="nexus_letter",
                                      title="Nexus", status="have"))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(strategy_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.get_db] = _test_db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


def test_endpoint_returns_plan(env):
    r = env.client.get("/api/strategy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_conditions"] is True
    assert body["snapshot"]["conditions_total"] == 1
    assert body["snapshot"]["current_combined"] == 50
    assert body["pathways"]  # at least one
    # no active ITF → top action protects back pay
    assert body["priority_actions"][0]["category"] == "protect_backpay"
    assert not _PROMISE.search(str(body))


def test_endpoint_cross_user_isolation(env):
    env.current["uid"] = str(UB)
    body = env.client.get("/api/strategy").json()
    assert body["snapshot"]["conditions_total"] == 1  # only Blair's own
    # Blair's condition is "Back strain"; PTSD never appears
    assert "PTSD" not in str(body)


def test_deep_dive_read_and_force_run_are_cached_safe_results(env):
    # on_analysis is OFF by default: GET never runs the many-expert fan-out inline
    # (no synchronous battle-plan latency / gateway-timeout risk). Before any run it
    # is a safe empty cache read.
    first = env.client.get("/api/strategy/deepdive")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["candidates_considered"] == 0
    assert body["current_combined"] == 50
    # An un-run deep dive surfaces nothing new (no notification, or an empty one).
    assert not body["notification"] or body["notification"]["has_new_findings"] is False

    # The explicit veteran-requested run forces the fan-out and caches it.
    forced = env.client.post("/api/strategy/deepdive/run")
    assert forced.status_code == 200, forced.text
    forced_body = forced.json()
    assert forced_body["candidates_considered"] >= 1
    assert forced_body["projected_combined"] == 50

    # A subsequent GET now serves the cached deep dive (no recompute).
    cached = env.client.get("/api/strategy/deepdive").json()
    assert cached["candidates_considered"] == forced_body["candidates_considered"]
    assert cached["generated_at"] == forced_body["generated_at"]

    # The fast firm writes its sibling namespace after a deep dive already owns
    # this facts hash; the JSON cache update must preserve the deep-dive result.
    assert env.client.get("/api/strategy").status_code == 200
    cached_again = env.client.get("/api/strategy/deepdive").json()
    assert cached_again["generated_at"] == forced_body["generated_at"]


def test_deep_dive_overlay_only_updates_an_existing_exact_key():
    from app.routers.strategy import _merge_deep_dive

    plan = {
        "opportunities": [
            {"key": "same", "body": "deterministic", "reg": "38 CFR §3.310"},
            {"key": "untouched", "body": "keep me", "reg": "Esteban"},
        ]
    }
    _merge_deep_dive(
        plan,
        {
            "findings": [
                {"key": "same", "body": "reviewed grounded wording"},
                {"key": "new-key", "body": "must not be appended"},
            ]
        },
    )
    assert plan["opportunities"][0]["body"] == "reviewed grounded wording"
    assert plan["opportunities"][0]["reg"] == "38 CFR §3.310"
    assert plan["opportunities"][1]["body"] == "keep me"
    assert len(plan["opportunities"]) == 2


def test_facts_hash_includes_deep_dive_only_dossier_facts():
    from app.routers.strategy import _facts_hash

    common = {
        "snapshot": {"current_combined": 50},
        "condition_lines": [{"name": "Knee", "band": "building"}],
        "money": None,
        "denials": [],
        "suggestions": [],
        "focus": None,
    }
    before = _facts_hash(
        **common,
        dossier_facts={"conditions": [{"name": "Knee", "diagnostic_code": "5257"}]},
    )
    same = _facts_hash(
        **common,
        dossier_facts={"conditions": [{"name": "Knee", "diagnostic_code": "5257"}]},
    )
    changed_dc = _facts_hash(
        **common,
        dossier_facts={"conditions": [{"name": "Knee", "diagnostic_code": "5260"}]},
    )
    changed_doc = _facts_hash(
        **common,
        dossier_facts={"documents": [{"id": "doc-1", "sha256": "new"}]},
    )
    assert before == same
    assert len({before, changed_dc, changed_doc}) == 3


# ── Wave 9 — deeper briefing surface (condition lines, roadmap, focus, briefing)

def test_condition_lines_reflect_readiness_and_sort_ready_first():
    ready = _cond(name="Tinnitus", band="complete")
    early = _cond(name="Knee", band="early", missing=["a medical link (nexus)"])
    p = _plan(conditions=[early, ready])  # deliberately unsorted input
    lines = p["condition_lines"]
    assert [l["name"] for l in lines] == ["Tinnitus", "Knee"]  # most-ready first
    t = next(l for l in lines if l["name"] == "Tinnitus")
    assert t["ready"] is True and t["band_label"] == "Ready to file" and t["missing"] == []
    k = next(l for l in lines if l["name"] == "Knee")
    assert k["ready"] is False and k["missing"] == ["a medical link (nexus)"]
    assert k["link"] and k["link"].startswith("/conditions/")


def test_focus_is_top_ranked_action():
    ready = _cond(name="Tinnitus", band="complete", target_rating=10)
    p = _plan(conditions=[ready])
    # no ITF → focus should be the protect-backpay ITF action (highest priority)
    assert p["focus"] is not None
    assert p["focus"]["title"] == p["priority_actions"][0]["title"]
    assert p["focus"]["link"] == "/itf"


def test_process_roadmap_marks_where_you_are():
    denied_doc = [{"name": "Tinnitus", "missing_elements": ["nexus"]}]
    ready = _cond(name="Back", band="complete", target_rating=20)
    p = _plan(conditions=[ready], denials=denied_doc, active_itf={"type": "compensation", "days_remaining": 100})
    steps = {s["key"]: s["state"] for s in p["process_roadmap"]}
    assert steps["itf"] == "done"          # active ITF
    assert steps["file"] == "now"          # a ready condition
    assert steps["decision"] == "done"     # a denial means a decision arrived
    assert steps["appeal"] == "now"        # denial waiting for a response
    _no_promises(p)


def test_briefing_fallback_summary_is_grammatical_and_safe():
    from app.strategy.briefing import _summary
    snap = {"conditions_total": 1, "ready_count": 1, "needs_evidence_count": 0,
            "denied_count": 0, "active_itf": None, "current_combined": 40}
    b = _summary(snapshot=snap, condition_lines=[], money={"current_combined": 40, "current_monthly": 774.16},
                 denials=[], suggestions=[], focus={"title": "File an ITF", "why": "Protects your date."})
    assert b["generated_by"] == "summary"
    assert "1 conditions" not in str(b)  # grammatical singular
    assert b["headline"] and b["paragraphs"]
    assert not _PROMISE.search(str(b))


def test_briefing_parser_rejects_junk_and_accepts_valid_json():
    from app.strategy.briefing import _parse
    assert _parse("the model rambled with no json") is None
    assert _parse("") is None
    good = '```json\n{"headline":"You are close","paragraphs":["One.","Two."],' \
           '"strengths":["a"],"watch_outs":["b"]}\n```'
    out = _parse(good)
    assert out and out["headline"] == "You are close"
    assert out["paragraphs"] == ["One.", "Two."] and out["generated_by"] == "local"
    # missing required keys → reject
    assert _parse('{"strengths":["a"]}') is None


def test_briefing_parser_allows_opinions_but_blocks_guaranteed_outcomes():
    """2026 full-advocate posture: the output-side gate no longer muzzles
    conclusions — cited opinions, nexus analysis, and 'meets the criteria' are
    legitimate. It drops ONLY a GUARANTEED VA OUTCOME (VA decides); a dropped
    briefing falls back to the safe deterministic summary."""
    import json as _json

    from app.strategy.briefing import _parse

    def _wrap(headline, para="Some neutral filler sentence."):
        return _json.dumps({"headline": headline, "paragraphs": [para],
                            "strengths": ["a"], "watch_outs": ["b"]})

    # GUARANTEED-outcome phrasings are still rejected (each in a different field).
    assert _parse(_wrap("You will get 70% for this")) is None
    assert _parse(_wrap("Great", "You will be granted service connection.")) is None
    assert _parse(_wrap("Sure", "This is a guarantee of back pay.")) is None
    # Full-advocate ANALYSIS is now allowed.
    assert _parse(_wrap("You may be entitled to back pay")) is not None
    assert _parse(_wrap("Good news", "Your PTSD looks service-connected on this record.")) is not None
    assert _parse(_wrap("Close", "It is at least as likely as not related to service.")) is not None
    assert _parse(_wrap("Almost there", "Your evidence supports the criteria for an increase.")) is not None
    # a clean briefing that restates the veteran's own current rating still passes
    ok = _parse(_wrap("You have 2 conditions ready", "You are already rated at 60%, which counts toward your baseline."))
    assert ok is not None and ok["generated_by"] == "local"
