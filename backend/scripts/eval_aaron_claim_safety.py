#!/usr/bin/env python3
"""Evaluate claim-safety surfaces (bear / reclaim / briefs) on Aaron-shaped record.

Uses the deterministic engines only (no deploy required). Optionally calls the
fleet LLM via LLM_BASE_URL / LLM_API_KEY / LLM_MODEL for a short Qwen smoke and
for firm specialists when --llm is set.

Legal lane: educational eval output only — not a claim determination.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running as scripts/… from backend/
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routers.buddy import (  # noqa: E402
    _situation_hit_list,
    _situation_outline,
)
from app.routers.nexus import _provider_missing, _provider_scaffold  # noqa: E402
from app.schemas import (  # noqa: E402
    BuddySituationBriefIn,
    NexusProviderBriefIn,
)
from app.strategy.plan import build_game_plan  # noqa: E402
from app.strategy.rating_rules import (  # noqa: E402
    cautions_for,
    opportunities_for,
    screen_tdiu,
)

# Aaron-shaped dossier: CFS granted @60, combined 60, denials from decision letters
# (knee/anxiety/fibro), MH cluster, duplicates collapsed for strategy engines.
def _c(
    i: int,
    name: str,
    *,
    dc: str | None = None,
    claim_type: str = "direct",
    va_status: str = "unknown",
    current_rating: int | None = None,
    status: str = "considering",
    band: str = "early",
    missing: list[str] | None = None,
    score: int = 20,
) -> dict:
    return {
        "id": f"00000000-0000-0000-0000-{i:012d}",
        "name": name,
        "diagnostic_code": dc,
        "claim_type": claim_type,
        "va_status": va_status,
        "current_rating": current_rating,
        "status": status,
        "band": band,
        "missing": missing or [],
        "score": score,
    }


AARON_CONDITIONS = [
    _c(1, "Chronic Fatigue Syndrome (ME/CFS)", dc="6354", claim_type="increase",
       va_status="service_connected", current_rating=60, status="decided",
       band="complete", missing=[], score=100),
    _c(2, "Fibromyalgia", dc="5025", va_status="denied",
       missing=["nexus", "current_disability"], score=20),
    _c(3, "Unspecified anxiety disorder", dc="9413", va_status="denied",
       missing=["nexus"], score=25),
    _c(4, "Generalized Anxiety Disorder", dc="9400", va_status="denied",
       missing=["nexus"], score=25),
    _c(5, "Major Depressive Disorder", dc="9434",
       missing=["nexus", "in_service_event"], score=15),
    _c(6, "Left Knee Disorder", dc="5260", va_status="denied",
       missing=["nexus", "in_service_event"], score=20),
    _c(7, "Right Knee Disorder", dc="5260", va_status="denied",
       missing=["nexus"], score=20),
    _c(8, "Hypertension", dc="7101", missing=["nexus"], score=15),
    _c(9, "Migraine", dc="8100", missing=["nexus"], score=15),
]


def _assert(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  OK:   {msg}")


def eval_deterministic() -> list[str]:
    failures: list[str] = []
    print("\n=== Deterministic claim-safety (Aaron-shaped) ===")
    tdiu = screen_tdiu(AARON_CONDITIONS, 60)
    cautions = cautions_for(AARON_CONDITIONS, tdiu=tdiu)
    opps = opportunities_for(AARON_CONDITIONS)

    kinds_c = {c["kind"] for c in cautions}
    kinds_o = {o["kind"] for o in opps}
    print(f"  cautions kinds: {sorted(kinds_c)}")
    print(f"  opportunity kinds: {sorted(kinds_o)}")
    for c in cautions:
        print(f"  - caution[{c['kind']}] {c['title'][:80]}")
    for o in opps:
        print(f"  - opp[{o['kind']}] {o['title'][:90]}")

    _assert(tdiu is not None, "TDIU screen fires at 60% combined", failures)
    _assert("tdiu_employment" in kinds_c, "TDIU employment caution present", failures)
    _assert("reduction" in kinds_c, "Reduction (poke the bear) caution present", failures)
    _assert("filing_tradeoff" in kinds_c, "CFS/fibro filing trade-off present", failures)
    _assert("pyramiding" in kinds_c, "MH §4.130 pyramiding caution present", failures)
    reclaim = [o for o in opps if o["kind"] == "reclaim"]
    _assert(any("anxiety" in o["secondary"].lower() for o in reclaim),
            "Anxiety reclaim secondary to CFS", failures)
    for o in reclaim:
        _assert(bool(o.get("attach_checklist")), f"Reclaim checklist: {o['secondary'][:40]}", failures)
        _assert(o.get("pathway") == "supplemental", f"Supplemental path: {o['secondary'][:40]}", failures)

    plan = build_game_plan(
        conditions=AARON_CONDITIONS,
        denials=[
            {"name": "Anxiety", "missing_elements": ["nexus"]},
            {"name": "Left knee", "missing_elements": ["nexus", "in_service_event"]},
            {"name": "Fibromyalgia", "missing_elements": ["nexus"]},
        ],
        active_itf=None,
        current_combined=60,
        suggestions=[],
        generated_at="2026-07-27T00:00:00Z",
    )
    _assert(any(c["kind"] == "tdiu_employment" for c in plan.get("cautions") or []),
            "Game plan includes TDIU employment caution", failures)
    _assert(any(o["kind"] == "reclaim" for o in plan.get("opportunities") or []),
            "Game plan includes reclaim opportunity", failures)
    _assert(
        any("reclaim" in a["title"].lower() for a in plan.get("priority_actions") or []),
        "Priority actions include reclaim step",
        failures,
    )

    # Buddy situation brief
    print("\n=== Buddy situation brief ===")
    b_in = BuddySituationBriefIn(
        condition="ME/CFS and unemployability",
        veteran_name="Aaron",
        themes=["work absences", "stairs", "post-exertional crashes"],
        period="since 2020",
        known_facts=["Often needs to rest after short walks"],
    )
    hits = _situation_hit_list(b_in)
    outline = _situation_outline(b_in)
    _assert(len(hits) >= 5, f"Buddy hit list length {len(hits)}", failures)
    _assert("own words" in outline.lower() or "your words" in outline.lower(),
            "Buddy outline stresses own words", failures)
    _assert("first-hand" in " ".join(hits).lower() or "personally" in " ".join(hits).lower(),
            "Buddy hits require first-hand observations", failures)
    print(f"  hits ({len(hits)}):")
    for h in hits[:6]:
        print(f"    • {h[:100]}")

    # Provider brief — anxiety secondary to CFS
    print("\n=== Nexus provider brief (anxiety 2° CFS) ===")
    n_in = NexusProviderBriefIn(
        condition="Unspecified anxiety disorder",
        claim_type="secondary",
        secondary_to="Chronic Fatigue Syndrome (ME/CFS)",
        diagnostic_code="9413",
        prior_denial_notes="Denied 2016 on direct service connection; nexus element missing.",
        missing_elements=["nexus", "secondary_link"],
        records_to_review=[
            "2016 rating decision denying anxiety",
            "2024 CFS grant decision",
            "Psychologist notes re secondary anxiety",
        ],
    )
    missing = _provider_missing(n_in)
    scaffold = _provider_scaffold(n_in)
    _assert(any("secondary" in m.lower() or "link" in m.lower() for m in missing),
            "Provider brief surfaces secondary/nexus gap", failures)
    _assert("at least as likely as not" in scaffold.lower(),
            "Provider scaffold uses ≥50% language", failures)
    _assert("PROVIDER" in scaffold or "Provider" in scaffold or "_[Provider" in scaffold,
            "Rationale left for provider", failures)
    _assert("will be granted" not in scaffold.lower(),
            "No outcome promise in scaffold", failures)
    print(f"  missing: {missing}")
    print(f"  scaffold head: {scaffold[:220].replace(chr(10), ' ')}…")

    return failures


async def eval_llm() -> list[str]:
    failures: list[str] = []
    print("\n=== Local Qwen / fleet LLM smoke ===")
    base = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL", "qwen3.6-35b")
    if not base:
        print("  SKIP: LLM_BASE_URL not set")
        return failures
    print(f"  base={base} model={model}")
    try:
        from app.llm.gateway import gateway
    except Exception as e:
        failures.append(f"gateway import: {e}")
        print(f"  FAIL: gateway import {e}")
        return failures

    try:
        ok = await gateway.ping_llm()
        _assert(ok, "gateway.ping_llm()", failures)
    except Exception as e:
        failures.append(f"ping: {e}")
        print(f"  FAIL: ping {e}")

    try:
        text = await gateway.complete(
            messages=[{
                "role": "user",
                "content": "Reply with exactly the token QWEN_OK and nothing else.",
            }],
            max_tokens=32,
            temperature=0.0,
        )
        print(f"  complete response: {text[:200]!r}")
        _assert(
            "QWEN_OK" in text.upper() or "OK" in text.upper(),
            "Qwen returns expected token (fuzzy)",
            failures,
        )
    except Exception as e:
        failures.append(f"complete: {e}")
        print(f"  FAIL: complete {e}")

    # Firm seed path (no full dossier DB): specialists should still seed reclaim/TDIU
    try:
        from app.firm.context import VeteranDossier
        from app.firm.specialists.secondaries import SecondariesSpecialist
        from app.firm.specialists.tdiu import TdiuSpecialist
        from app.firm.specialists.pyramiding import PyramidingSpecialist

        d = VeteranDossier(
            uid="eval-aaron",
            conditions=AARON_CONDITIONS,
            current_combined=60,
            generated_at="2026-07-27T00:00:00Z",
        )
        sec_seed = SecondariesSpecialist().seed(d)
        tdiu_seed = TdiuSpecialist().seed(d)
        pyr_seed = PyramidingSpecialist().seed(d)
        print(f"  secondaries seed n={len(sec_seed)} tdiu={bool(tdiu_seed)} pyr n={len(pyr_seed)}")
        _assert(len(sec_seed) >= 1, "SecondariesSpecialist seeds ≥1 from Aaron dossier", failures)
        _assert(bool(tdiu_seed), "TdiuSpecialist seeds from 60% combined", failures)
        _assert(len(pyr_seed) >= 1, "PyramidingSpecialist seeds MH/underrating", failures)

        # Optional: run_firm with LLM if db is None allowed
        if os.environ.get("EVAL_RUN_FIRM") == "1":
            from app.firm import run_firm
            findings = await run_firm(d, None)
            print(f"  run_firm findings n={len(findings)}")
            for f in findings[:8]:
                print(f"    [{getattr(f, 'specialist', '?')}] {getattr(f, 'title', f)[:80]}")
            _assert(len(findings) >= 1, "run_firm returns findings with local LLM", failures)
    except Exception as e:
        failures.append(f"firm: {e}")
        print(f"  FAIL: firm {e}")

    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="Also smoke the fleet/local Qwen path")
    args = ap.parse_args()
    failures = eval_deterministic()
    if args.llm:
        failures.extend(asyncio.run(eval_llm()))
    print("\n=== Summary ===")
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
