# Rating Raider — Build Spec (LOCKED)

**Working name:** Rating Raider (final name = Aaron's pick; keep the string in one place per tier).
**What it is:** self-service VA disability compensation tool for veterans — "TurboTax for VA
claims." Sibling app to Glitter Mane. The veteran always drives; the app informs and organizes.

This document is the contract. Agents build against it; do not invent schema or endpoints.

## Legal lane (non-negotiable, shapes all copy)

38 CFR §14.629 restricts paid claim *preparation/representation* to accredited agents. Rating Raider
is **software the veteran operates themselves** (TurboTax model). Rules for every string in the app:
- Never "we file for you," "we'll handle your claim," "maximize your rating with us."
  Always "your claim," "you file," "bring this to your provider/VSO."
- Global persistent footer + first-run acknowledgment: *"Rating Raider is self-help educational
  software. It is not legal advice, not a VA-accredited representative or agent, and is not
  affiliated with the U.S. Department of Veterans Affairs. For free help filing or appealing,
  use a VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The American Legion, or your
  state/county veterans office. Verify current rating criteria at eCFR / VA.gov — regulations
  change."*
- No outcome-contingent anything. Educational framing: "the criteria say," "veterans in this
  situation often discuss X with their provider," never "you will get 70%."
- Every AI answer cites the KB card used (source string, e.g. "38 CFR §4.130, DC 9411").

## Stack + naming

| Thing | Value |
|---|---|
| Repo | `~/valor-ops` (mirrors `~/glitter-mane` layout: backend/ frontend/ mcp/ db/init/ infrastructure/ docs/) |
| Backend | FastAPI, SQLAlchemy async + asyncpg, Postgres 16 + pgvector |
| DB / role / port(dev) | db `valor`, non-superuser role `valor_app`, host port **5434** (GM uses 5433) |
| Backend dev port | **8001** (GM uses 8000); in-container always 8000 |
| Frontend | React + Vite + TS + Tailwind, Aurora design language copied from GM |
| Frontend dev port | **5174** |
| SSO | uchub Keycloak OIDC code flow, client id `valor-ops`, entitlement SKU **`valor-ops`**, allowlist bootstrap `VALOR_SSO_ALLOWED_EMAILS` |
| RLS GUC | `app.current_user_id` (identical mechanism to GM) |
| LLM | UC LiteLLM gateway `http://localhost:4000/v1`, default model env-set (local Qwen); deny-by-default `llm_allowed_models`; PII never to cloud models by default |
| Embeddings | OpenAI-compatible bge-m3 (env), dim 1024; KB retrieval degrades gracefully |
| Env prefix | settings via pydantic-settings, `.env`, same var names as GM where the concept matches |
| Deploy | edge-host, Traefik `web` network, host `valor.magicunicorn.dev`, frontend nginx proxies `/api` → backend |
| MCP | `mcp/valor_mcp.py`, SSE, port 8766, calls backend REST with a service/user token |
| Versioning | 0.1.0; container names `valor-ops-db|backend|frontend|mcp` |

Copy these GM files as the starting point (adapt names only where the spec says):
`backend/app/{db,deps,config,security,audit}.py`, `backend/app/routers/{auth,sso}.py`,
`backend/app/llm/gateway.py`, `db/init/00-init.sh`, `infrastructure/docker-compose.edge-host.yml`,
`docker-compose.yml`, `frontend/src/index.css`, `frontend/tailwind.config.js`,
`frontend/src/lib/hues.ts`, `mcp/glitter_mcp.py`, frontend `Dockerfile` + nginx conf.

## Data model (LOCKED)

`users` — NOT fenced (login resolves before RLS): id UUID pk default gen_random_uuid,
email unique, password_hash, full_name, created_at. (No care-circle in v1; audit_log keeps
`actor_user_id` so shared access can land later.)

FENCED_TABLES (RLS `user_id = NULLIF(current_setting('app.current_user_id', true),'')::uuid`,
ENABLE + FORCE, policy `user_isolation`):

- `veteran_profiles` — user_id (unique), service_periods JSONB
  `[{branch, component, start_date, end_date, discharge_character}]`,
  combat_service bool, exposures JSONB
  `{burn_pits, agent_orange, gulf_war, radiation, camp_lejeune, other: str, locations: [str]}`,
  current_combined_rating int nullable, state varchar(2) nullable, notes text.
- `claimed_conditions` — id, user_id, name, body_system, diagnostic_code varchar(8) nullable,
  claim_type enum-str `direct|secondary|presumptive|increase`, secondary_to UUID nullable
  (FK claimed_conditions.id), current_rating int nullable, target_rating int nullable,
  status enum-str `considering|gathering_evidence|ready_to_file|filed|decided`,
  onset_date date nullable, in_service_event text, nexus_notes text, dbq_form varchar(160),
  notes text, created_at, updated_at.
- `evidence_items` — id, user_id, condition_id FK, kind enum-str
  `diagnosis|service_record|nexus_letter|dbq|lay_statement|continuity|treatment_record|other`,
  title, status enum-str `have|need|requested|not_applicable`, source varchar(255),
  file_ref varchar(512) nullable, notes text, created_at, updated_at.
- `rating_scenarios` — id, user_id, name, entries JSONB
  `[{label, percent int, side: "left"|"right"|null, group: str|null}]`
  (side non-null marks a bilateral-candidate extremity entry), result JSONB (engine output
  snapshot), created_at.
- `checklist_items` — id, user_id, condition_id FK nullable, text, category varchar(64),
  done bool default false, sort int default 0, created_at.
- `audit_log` — id, user_id, actor_user_id nullable, action varchar(64), entity varchar(64),
  entity_id varchar(64), meta JSONB, created_at. Append-only.

NOT fenced (global reference, no PII):
- `kb_cards` — id, card_type `rating_criteria|rule|presumptive|dbq|process`, title,
  body_system varchar(64), diagnostic_code varchar(8) nullable, source varchar(255) (the cite),
  content text (markdown), data JSONB (structured tiers etc.), embedding vector(1024) nullable.
  Seeded idempotently from `backend/app/kb/data/*.json` exactly like GM `seed_guidelines()`
  (embed BEFORE delete; skip if unchanged+embedded).

## Rating engine (already authored — do not touch)

`backend/app/rating/engine.py` — pure, deterministic; LLM never does the math.
Public API (import and call; see docstrings):
- `combine(percents: list[int]) -> int` — §4.25 pairwise table combine (intermediate integer
  rounding), NOT final-rounded.
- `combined_rating(entries: list[RatingEntry]) -> CombinedResult` — full §4.25+§4.26:
  bilateral grouping, factor, descending order, step log, final rounding to nearest 10
  (ending-in-5 rounds up). `CombinedResult` has `.combined` (final), `.raw` (pre-rounding),
  `.steps` (list of human-readable step dicts), `.bilateral_factor_applied`, `.smc_flags`.
- `RatingEntry(label, percent, side=None, group=None)`.
- `smc_screen(entries, raw_combined) -> list[dict]` — educational SMC-S/K pointers.

## API contract (all under `/api`)

Auth (copy GM): `POST /auth/register` (closed-registration posture: `ALLOW_REGISTRATION`
bootstrap-first-account semantics), `POST /auth/login`, `GET /auth/me`,
`GET /auth/keycloak`, `GET /auth/keycloak/callback`. JWT bearer, RLS via `get_db`.

- `GET|PUT /profile` — veteran_profiles upsert (PUT creates if missing).
- `GET|POST /conditions`, `GET|PATCH|DELETE /conditions/{id}`.
- `GET|POST /conditions/{id}/evidence`, `PATCH|DELETE /evidence/{id}`.
- `GET /conditions/{id}/gaps` — deterministic evidence-gap analysis (rules: needs
  current diagnosis, in-service event/nexus, continuity; secondary needs primary link +
  nexus; increase needs current treatment evidence) + KB DBQ mapping. Returns gaps +
  auto-generated checklist items (persisted, idempotent per condition).
- `GET|POST|DELETE /checklist`, `PATCH /checklist/{id}` (toggle done).
- `POST /rating/calculate` — body `{entries: [{label, percent, side?, group?}]}` →
  CombinedResult JSON. No persistence, no auth-free access (still authed).
- `GET|POST /rating/scenarios`, `DELETE /rating/scenarios/{id}` — saved what-ifs
  (server recomputes result on save; never trusts client math).
- `GET /kb/cards?type=&body_system=&q=` — list/search (vector search when q + embeddings
  up, else ILIKE fallback). `GET /kb/cards/{id}`. `GET /kb/dbq?condition=...`.
- `POST /analysis/map-conditions` — LLM+KB: for the user's claimed conditions (or posted
  names), return likely diagnostic codes, tier table, evidence each tier needs,
  under-rated flag when current_rating < a tier whose criteria the user's notes suggest.
  Every item carries `source` cites from kb_cards. LLM output is constrained: it selects
  from retrieved cards; it does not invent codes or percentages (validate: any DC/percent
  in the response must exist in the retrieved cards' structured data, else drop + log).
- `POST /analysis/secondaries` — given claimed/granted conditions, suggest plausible
  secondaries from the KB secondary-map + LLM rationale ("discuss with your provider").
- `GET /analysis/presumptives` — RULE-BASED screen: profile service_periods + exposures ×
  KB presumptive lists (PACT/AO/Gulf War/radiation/Camp Lejeune) → matches with
  eligibility rationale + source. LLM only phrases, never decides membership.
- `GET /packet/{condition_id}` — printable "bring to your provider / DBQ prep" packet
  (HTML print view + JSON): condition, DC + criteria tiers, evidence on hand/missing,
  continuity summary (incl. Glitter Mane data if connected), lay-statement prompts.
- `GET /filing/lanes` — static KB `process` cards (FDC, supplemental, HLR, Board/AMA,
  effective dates, CUE) for the guide page.
- Glitter Mane seam: `GET /glitter/status`, `POST /glitter/connect` (store per-user GM
  base+token? NO — env-level trusted-caller: backend mints brigade-style JWT
  {email, aud:"glitter-mane"} signed with shared `GLITTER_BRIDGE_SECRET`, calls GM REST),
  `GET /glitter/conditions`, `GET /glitter/continuity?condition=...` (check-ins),
  `POST /glitter/import-conditions` (copy selected GM conditions into claimed_conditions).
  All optional: app fully works with GM unset.
- `GET /healthz` (no auth).

Audit: every mutating endpoint writes audit_log via the shared helper (copy GM audit.py).

## Frontend pages (React Router)

`/login` (email/pw + "Sign in with Unicorn Commander" when SSO on), `/auth/sso-callback`,
`/` dashboard (combined rating hero dial, conditions summary, gaps count, next actions),
`/profile` (service history + exposures editor), `/conditions` (+ detail
`/conditions/:id` with evidence, gaps, DBQ, packet button), `/calculator` (interactive
§4.25 with bilateral toggle, live steps explanation, what-if add/remove, save scenario),
`/scenarios`, `/secondaries`, `/presumptives`, `/evidence` (organizer across conditions),
`/filing` (lanes guide), `/settings`. First-run disclaimer modal (stored ack in
localStorage + shown in settings). Footer disclaimer on every page. Print stylesheet for
the packet view. Dark-first + light theme via CSS vars (copy GM index.css mechanism).

Tone: respectful, empowering, plain language, veteran-first. No dark patterns.

## File ownership (parallel agents — do not cross)

- Agent BACKEND-CORE: `backend/app/{config,db,deps,security,audit,main,models,schemas}.py`,
  `backend/app/routers/{auth,sso}.py`, `backend/app/llm/gateway.py`, `backend/Dockerfile`,
  `backend/requirements*.txt`, `backend/pytest.ini`, `db/init/00-init.sh`,
  `docker-compose.yml`, `infrastructure/docker-compose.edge-host.yml`, `.gitignore`,
  `infrastructure/.env.example`.
- Me (orchestrator): `backend/app/rating/*`, `backend/app/kb/data/*`, `backend/tests/test_rating.py`, `docs/*`.
- Agent ROUTERS: `backend/app/routers/{profile,conditions,evidence,checklist,rating,kb,analysis,packet,filing,glitter}.py`, `backend/app/kb/{__init__,store}.py`, `backend/app/analysis/*.py`, `backend/tests/test_api_*.py`.
- Agent FRONTEND: everything under `frontend/`.
- Agent MCP: `mcp/*`, `README.md`.

Routers agent must not edit models.py — if a column is missing, it's a spec bug; flag it.
