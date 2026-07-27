# Wave 8 — Game Plan: the strategy engine that ties everything together

The capstone. One deterministic engine reads everything the app already knows —
conditions, evidence/gaps, readiness, decoded denials, suggested secondaries &
presumptives, current combined rating, ITF status — and produces (1) an organized
snapshot, (2) a few ranked **pathways**, and (3) a prioritized **action list**.

**Lead (Claude) owns the correctness-critical engine + all shared wiring.** One
agent builds the frontend; one agent adversarially reviews the engine's legal lane.

## Legal lane (load-bearing — this feature is the riskiest for it)
Educational self-help ONLY. The plan proposes options to *consider*; the veteran
decides. **No outcome promises, ever.** Every estimated combined rating is labeled
as computed from the veteran's OWN target ratings (§4.25 math) and explicitly "not a
prediction of what VA will decide." No "you will get / you qualify for / this
guarantees." Ranking is by evidence-readiness and known VA rules, NOT by predicting
VA behavior. Heavy disclaimer + VSO referral on every surface. Veteran-Ops never
files, represents, or renders a medical opinion.

## Ownership
Shared — LEAD ONLY: `app/schemas.py`, `app/main.py`, `src/lib/api.ts`, `src/types.ts`,
`src/lib/hues.ts`, `src/components/Shell.tsx`, `src/App.tsx`.
LEAD builds: `app/strategy/__init__.py`, `app/strategy/plan.py` (PURE engine),
`app/routers/strategy.py`, `backend/tests/test_strategy.py`.
Agent A builds: `src/pages/Strategy.tsx`, `src/pages/StrategyPrint.tsx`, and the
Game-Plan hero card wired into `src/pages/Dashboard.tsx` (Dashboard is Agent A's).
Agent B: read-only adversarial review of `app/strategy/plan.py` — reports findings,
does NOT edit.

## Engine (`app/strategy/plan.py`) — PURE `build_game_plan(...)`
Router (`routers/strategy.py`, `GET /strategy`) gathers DB data + calls the existing
analysis helpers, then passes PLAIN data to the pure engine. Reuse, do not re-derive:
- `readiness/score.py::score_condition` — per-condition band/missing (same gap engine).
- `rating/engine.py::combine(percents:list[int])->int` — §4.25 for estimated combined.
- Router calls `analysis.secondaries.match_secondaries` + `analysis.presumptives
  .match_presumptives` and passes the suggested NAMES (minus already-claimed).
- Denials: router reads each ready VA-decision document's `extracted['decode']`
  (decoder cache) and passes denied {name, missing_elements} + decision_date.
- ITF: reuse `decoder/deadline.py::appeal_window` for the active-ITF countdown.

Deterministic logic:
- **snapshot**: current_combined (profile.current_combined_rating), conditions_total,
  ready_count (band strong|complete), needs_evidence_count, denied_count, active_itf.
- **pathways** (include only if applicable; mark exactly ONE `recommended`):
  - `file_now` (if any ready): file the ready conditions now; protects the effective
    date. estimated_combined = combine(existing current_ratings + ready targets).
  - `strengthen_first` (if any condition has a real gap): close the top gaps first,
    then file the strongest claim. Lists the specific missing items.
  - `add_conditions` (if suggested secondaries/presumptives exist): explore adding
    them; names listed; numeric estimate stays on claimed targets, notes "+N to explore."
  - `appeal_denials` (if any denial): respond to each denial (missing element →
    Supplemental Claim), link `/appeals`.
  Recommend: `file_now` if ready exists, else `strengthen_first`, else `appeal_denials`.
  Each Pathway: key,title,summary,steps[],included_conditions[],estimated_combined:int|None,
  estimated_combined_basis:str,tradeoff:str,recommended:bool.
- **priority_actions** (ranked high→low, cap 12): no-ITF→"File an Intent to File
  today" (high, protect_backpay,/itf); denial w/ have-evidence→"Start a Supplemental
  Claim for X" (high, appeal,/appeals); condition missing required element→"Get {item}
  for X" (early=high/building=medium, close_gap,/conditions/{id}); ready condition→
  "File your claim for X" (high, file,/application); suggested add→"Explore X" (medium,
  add_condition,/secondaries or /presumptives). Action{title,why,category,condition_name?,
  impact,link?}.
- Always: disclaimer, vso_referral, source_note. Estimates NEVER without the basis label.
- Edge cases MUST be graceful: no conditions (empty plan + onboarding nudge), no
  ratings set (estimated_combined=None + honest basis), all denied, no profile.

## Locked schemas (LEAD adds to schemas.py; Agent A imports types)
```
GamePlanSnapshot: { current_combined:int|None, conditions_total:int, ready_count:int,
  needs_evidence_count:int, denied_count:int, active_itf:dict|None }
GamePlanPathway: { key:str, title:str, summary:str, steps:list[str],
  included_conditions:list[str], estimated_combined:int|None,
  estimated_combined_basis:str, tradeoff:str, recommended:bool }
GamePlanAction: { title:str, why:str, category:str, condition_name:str|None,
  impact:"high"|"medium"|"low", link:str|None }
GamePlanOut: { generated_at:str, snapshot:GamePlanSnapshot, pathways:list[GamePlanPathway],
  priority_actions:list[GamePlanAction], has_conditions:bool, disclaimer:str,
  vso_referral:str, source_note:str }
```

## Frontend (Agent A)
- `Strategy.tsx` — named export, `data-section="insight"` (or a new hue), view key
  `strategy`. Loads `strategyApi.get()`. Shows the snapshot, the pathway cards
  (recommended one highlighted; estimated combined with its basis label + a "not a
  prediction" note), and the ranked action list (each action links to where you act).
  Print/save handoff to `/strategy/print` via `sessionStorage['vo_game_plan']`.
  Strong empty state (no conditions → /conditions, /onboarding). LegalLaneBanner.
- `StrategyPrint.tsx` — mirror `Form526Print.tsx` (PrintShell/PrintDoc). Print-ready
  game plan: snapshot, pathways, actions, disclaimers.
- Dashboard hero: a compact "Your Game Plan" card at the top of `Dashboard.tsx` —
  recommended pathway + top 3 actions + a "See full plan" link to `/strategy`.
  Degrade gracefully if `/strategy` 404s (older backend). Do NOT touch shared files.

## Done
Backend tests green (engine unit tests + endpoint + edge cases + cross-user +
NO-outcome-promise assertions). Frontend typecheck+build clean. Deploy git-bundle →
edge-host `docker compose -p valor-ops -f infrastructure/docker-compose.edge-host.yml up -d
--build backend frontend`. Prod E2E (seed → /strategy returns ranked pathways +
actions, estimates labeled, no promise language). Record memory + Project-Ops P-00113.
