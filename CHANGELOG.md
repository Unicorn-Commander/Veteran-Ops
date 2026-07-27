# Changelog

All notable changes to Rating Raider (veteran-ops platform). Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses semantic versioning.

## [1.9.33] — 2026-07-27

### Added
- **Rating Raider chat history:** conversations persist on this device (Past chats / New chat);
  survive navigate-away and refresh. Optional `?c=` deep-link to a conversation.
- **OSS prep:** hardened `export-veteran-ops-oss.sh`; local secrets-clean tree at `~/veteran-ops-oss`
  (not public yet). Docs updated for GitHub handoff.

### Changed
- Version **1.9.33** (`1.9.33-raider-chat-history.20260727`).

## [1.9.32] — 2026-07-27

### Changed
- **Do this first ranking:** ITF when missing (locks date), then reclaim/TDIU; plain-language *why*.
- **Quieter Outstanding:** collapse reclaim families, few gaps, cautions behind “Show more”.
- **Post-analysis flow:** Analysis complete → Talk through plan first → Claim Plan; Raider skip/continue CTAs.

### Added
- Version **1.9.32** (`1.9.32-coach-clarity.20260727`).

## [1.9.31] — 2026-07-27

### Added
- **Claim Plan coach:** Do this first / Then / Parked, Outstanding rail, per-section
  What·Why·Do guides, case brief print, Rating Raider post-analysis interview seed.
- **Duplicate conditions:** GET /conditions/duplicates + park-duplicates; Conditions UI.
- **MCP:** case brief, interview seed, list/park duplicates.
- Version **1.9.31** (`1.9.31-coach-outstanding.20260727`).

## [1.9.30] — 2026-07-27

### Added
- **Claim Plan:** TDIU work-history priority action when §4.16 screen fires; caution
  CTAs to TDIU workspace / provider brief; reclaim → Buddy situation-brief deep-link.
- **Buddy / Nexus deep-links:** query prefill + auto-generate briefs when `brief=1`.
- Product version **1.9.30**; release id `1.9.30-claim-safety-complete.20260727`.

## [1.9.29] — 2026-07-27

### Added
- **Poking the bear** Claim Plan cautions: CFS vs fibromyalgia filing trade-offs,
  TDIU employment / side-gig education (never “stop working”).
- **Reclaim cards** for denied conditions with a new §3.310 secondary theory:
  Supplemental path, attach checklist, priority actions.
- **Buddy situation brief** (`POST /buddy/situation-brief`) + UI panel.
- **Nexus provider brief** (`POST /nexus/provider-brief`) + UI panel; Claim Plan
  reclaim deep-links prefill the provider brief.
- **Decision-letter overlay:** decoded grants/denials set effective `va_status`
  when still `unknown` after C-file ingest (reclaim/secondaries can fire).
- **MCP expansion:** strategy, comprehensive analysis poll/cancel, TDIU worksheet,
  ITF, document reprocess/decode, What’s Changed, forms catalog, buddy/nexus
  briefs, case candidates, evidence review (~60 tools).

### Changed
- Product version **1.9.29**; release id `1.9.29-claim-safety-mcp.20260727`.

### Added (1.9.29 dogfood follow-up)
- **Apply decision-letter statuses:** GET/POST `/strategy/decision-statuses` (+ `/apply`)
  persists formal decision-letter grants/denials onto claimed conditions still
  `unknown` (opt-in UI on Claim Plan; MCP tools). C&P exams ignored.

## [1.9.28] — 2026-07-26

### Fixed
- **Customer-safe document intake:** large Blue Buttons no longer pin the fleet for
  30–60+ minutes of serial classify windows. Caps sampled segments (default 9),
  classifies in parallel (default 3), saves text early, hard-timeouts per doc,
  recovers stuck `processing` rows on boot, strips NUL bytes that crashed Postgres.
- **Blue Button PDF+TXT twins:** same-export fingerprint / stem dedupe so both
  formats uploaded together don't double-classify (prefer `.txt` over `.pdf`).
- **Documents confirm flicker:** list poll preserves extracted fields so rating
  confirm chips don't blink off every 3s.
- **Document viewer PDFs/images:** CSP allows `blob:` frames/images; MIME stamped
  for previews.
- **Analyze after upload survives navigation:** session store + Shell poller.

### Added
- Profile **location chips + typeahead** with records keyword suggestions.
- Config: `INTAKE_CLASSIFY_MAX_SEGMENTS`, `INTAKE_CLASSIFY_CONCURRENCY`,
  `INTAKE_DOC_TIMEOUT_SECONDS`, `INTAKE_STUCK_MINUTES`.

### Changed
- Product version **1.9.28**; release id `1.9.28-intake-customer-safe.20260726`.
- **No 3090 / long-pool routing changes** — batch classify stays on existing
  throughput pool.

## [1.9.27] — 2026-07-26

### Fixed
- **Rating-floor mapping persists:** results saved per conditions set; reopen uses
  cache (no re-run). Full comprehensive analysis includes a **mapping** step that
  saves the same cache. GET + POST `?force=` for refresh.

### Changed
- Product version **1.9.27**; release id `1.9.27-map-conditions-persist.20260726`.

## [1.9.26] — 2026-07-26

### Changed
- **Brand:** product/app name **Veteran-Ops**; flagship agent remains **Rating Raider**.
  Production domains planned: `veteranops.magicunicorn.dev`, email
  `veteran-ops@magicunicorn.dev` (see `docs/BRANDING.md`). Dogfood stays
  `valor.magicunicorn.dev` until cutover.
- Product version **1.9.26**; release id `1.9.26-brand-veteran-ops.20260726`.

## [1.9.25] — 2026-07-26

### Changed
- **Model routing (local-first):** privacy mode blocks *cloud/frontier* for PII, not
  other on-fleet aliases — so long-context `qwen3.6-35b-64k` may be used with
  record text. Defaults: batch `qwen3.6-35b` for extract/classify/briefing;
  `REASONING_MODEL=qwen3.6-35b-64k` for agent/long work. Fleet: 32k×3 throughput
  pools + 131k long P40 (3090 when loaded); no 64k product tier.
- Product version **1.9.25**; release id `1.9.25-model-routing-batch-long.20260726`.

## [1.9.24] — 2026-07-26

### Fixed
- **Comprehensive analysis MissingGreenlet crash:** dossier `load_only` omitted
  `Document.updated_at` while facts-hash read it under async SQLAlchemy, aborting
  the run at assemble. Load all dossier document columns used downstream, expunge
  after materialize, and read deferred attrs safely.

### Changed
- Product version **1.9.24**; release id `1.9.24-missing-greenlet-dossier.20260726`.

## [1.9.23] — 2026-07-26

### Fixed
- **Review queue empty-flag cards:** in-app **View file / View this document**
  (DocumentViewer), clearer copy when OCR left a soft flag with no field to pick,
  **Clear flag & continue** instead of a blind “mark reviewed.”
- **Bulk actions explained:** Accept all “record shows” / Accept agreed only /
  Clear all flags each describe what they do (record shows = second reader’s value).
- **Populate case dead-end:** when every suggested condition is already on the
  case, **Continue to analysis** (no disabled “Confirm 0 & continue”). Queue-clear
  CTAs prioritize populate case / analysis over profile.

### Changed
- Product version **1.9.23**; release id `1.9.23-review-viewer-case-continue.20260726`.

## [1.9.22] — 2026-07-26

### Fixed
- **Review queue stuck / “0 applied”:** bulk clear of orphan flags; always drop
  fields the veteran bulk-accepted even if write-back fails; **Mark document
  reviewed** / bulk **Mark all reviewed**; cards open by default with clear choices.
- **Identity:** auto-start one record scan on Profile when empty; email field on panel.
- **Ratings:** Profile button **Apply ratings from decision records** sets condition
  percents + profile combined estimate from processed VA decisions.

### Changed
- Product version **1.9.22**; release id `1.9.22-review-unblock.20260726`.

## [1.9.21] — 2026-07-26

### Added
- **Single claim path model** (`lib/claimProgress.ts`): one ordered spine
  (profile → records → review → case → analysis → plan → file) with one
  `resolveNextAction` used by Home and Journey.
- **ClaimContinue** hero: primary Continue + mini path track + % complete.

### Changed
- Home uses ClaimContinue only (removed competing next-step + claim spine stack).
- Journey uses the same progress model in stable order (no open-first reshuffle).
- Soft profile suggestions only when profile is still empty.
- Product version **1.9.21**; release id `1.9.21-single-spine.20260726`.

## [1.9.20] — 2026-07-26

### Fixed
- **Profile never marked complete** when identity suggestions remained (including
  account email). Journey ring no longer requires “no suggestions left.”
- **isEmptyProfile** treats saved name/DOB/phone/email/address as progress.
- Home **next-step stage** uses real ITF, not checklist checkbox.
- Checklist panel retitled **Optional reminders** so it is not a second walkthrough.
- Profile guided save continues to Documents (or Analysis after build-case).

### Changed
- Product version **1.9.20**; release id `1.9.20-progress-coherence.20260726`.

## [1.9.19] — 2026-07-26

### Fixed
- **Build Case no longer GPU-scans on navigation.** Open the page freely; scan only
  starts when you click **Scan records for conditions** (fast, deterministic, free).
  Optional **Improve grouping (AI)** uses the local model + a credit.
- Documents no longer prewarms case-candidates after processing (same accidental GPU).
- **Identity suggestions** seed account name + email when PDFs lack them; email field
  shown on the suggestion panel. Profile apply copies email.

### Changed
- Product version **1.9.19**; release id `1.9.19-scan-opt-in.20260726`.

## [1.9.18] — 2026-07-26

### Fixed
- Empty-state recovery CTAs on Presumptives, Actions (evidence review), ITF.
- ITF form toggle uses type=button.

### Changed
- Product version **1.9.18**; release id `1.9.18-overnight-polish.20260726`.

## [1.9.17] — 2026-07-26

### Fixed
- Analysis Center banner when Build Case requested full analysis but it did not start.
- Readiness empty dual CTAs; more `type="button"` on Conditions / ErrorBlock.
- Copy consistency: “Populate case from records” on Strategy empty.

### Changed
- Product version **1.9.17**; release id `1.9.17-overnight-polish.20260726`.

## [1.9.16] — 2026-07-26

### Added
- **Shared `lib/claimSpine.ts`** — one completion model for Home spine + Analysis next rings.
- **Friendly 404** page (Home / Journey / Help) instead of silent redirect to Home.
- **Deep links:** `/conditions?add=Name` pre-fills add form; Build Case `?q=` prefers a candidate.
- **Sticky mobile footer** utility for Raider composer + Build Case confirm bar.

### Fixed
- Conditions / Evidence / Strategy empty states use dual recovery CTAs (records-first).
- Conditions toolbar buttons use `type="button"` (no accidental form submit).

### Changed
- Product version **1.9.16**; release id `1.9.16-overnight-polish.20260726`.

## [1.9.15] — 2026-07-26

### Fixed
- **Dashboard ITF nudge** uses real tracked/VA ITF status, not checklist checkbox alone.
- **Onboarding** seeds `vo_journey_stage` from “where you are” answers.
- **Analysis next rings** after a completed run point to Claim plan / Application / Filing.
- Legal one-liners on Documents + Build Case headers.

### Changed
- Product version **1.9.15**; release id `1.9.15-overnight-ux.20260726`.

## [1.9.14] — 2026-07-26

### Fixed
- **Raider deadlines tool** — was always empty (wrong ITF/decode/dependents shapes).
  Now uses the same `load_deadlines_for_user` path as GET /deadlines.
- **Dossier** — includes `dependents`, keeps `in_service_event`/`nexus_notes` on
  conditions, and loads documents without multi-MB `text_content` blobs.
- **Claim spine / Journey rings** — Analysis is done only after a comprehensive
  run completes; Claim plan ring requires a real plan payload (not “has conditions”).
- **Dashboard** — no more N+1 per-condition gaps calls (uses file-readiness);
  file-readiness panel no longer double-fetches; empty next-actions has recovery CTAs.
- **Presumptive gaps** — POW / mustard gas exposures count as qualifying service
  (aligned with presumptives matcher).
- **PII tool matrix** — includes `prepare_cp_exam`.
- **Raider legal-lane prompt** — aligned with full-advocate gate (bar guarantees
  only; cited analysis allowed).
- **Suite Glitter CTA** — deep-links to `/conditions?import=glitter`.
- **Review queue missed conditions** — add-to-case / populate CTAs, not only dismiss.
- **Form 526 / Build Case** — dual empty CTAs; after confirm, routes to Analysis
  when comprehensive was requested.
- **Mobile “Case” tab** — highlights review, evidence, analysis, plan, application.

### Changed
- Product version **1.9.14**; release id `1.9.14-overnight-audit.20260726`.

## [1.9.13] — 2026-07-26

### Added
- **Raider chat token-budget guard.** Conversation history is bounded by message
  count *and* character budget (backend `bound_history` + matching client window)
  so long sessions never blow local model context. Tool results stay hard-capped.
- **POW internment duration branching (§3.309(c)).** Profile field
  `pow_internment_days` (optional UI when POW is checked) selects any-period vs
  30+ day presumptive condition lists. Unknown duration → safer any-period floor.
- **Deterministic condition auto-aliasing.** Chart/OCR spellings (CFS/ME/CFS,
  PTSD variants, tinnitus, HTN, OSA, etc.) collapse into clean claim candidates
  *without* the LLM — so Build Case stays sharp when the gateway is offline.
- **Golden eval expansion.** New domains `presumptive` and `alias`, plus a
  four-extremity bilateral rating golden case (10 de-identified cases total).
- **Raider starter chips** for “Am I ready to file?” and “What should I do next?”

### Changed
- Product version **1.9.13**; release id `1.9.13-world-class.20260726`.
  Rule fingerprint unchanged (authored KB corpus not re-distilled this pass).

## [1.9.12] — 2026-07-26

### Added
- **SMC educational specialist** (`smc_screen` / `smc_education`) — deterministic
  firm seed reusing rating-engine `smc_flags` (SMC-S housebound screen + SMC-K
  nature note). Educational language only; TDIU remains on its own specialist.
- **Build-case → full analysis opt-in.** `POST /analysis/build-case` accepts
  `start_comprehensive` (default false). When true, best-effort enqueues the
  durable comprehensive job after the case is populated (never fails the build).
  Build Case UI checkbox defaults on: “Run full analysis after I confirm conditions.”

### Changed
- Product version **1.9.12**; release id `1.9.12-claim-quality.20260726`.
  Rule fingerprint unchanged.

## [1.9.11] — 2026-07-25

### Fixed
- **KB currency gate.** Re-verified authored Title 38 rating/process/presumptive
  corpus after eCFR reported `latest_amended_on=2026-07-13`. That amendment
  (FR 2026-14084) was a Loan Guaranty civil monetary penalties notice with no
  Part 3/4 impact; content fingerprint unchanged. `KB_VERIFIED_AS_OF` →
  2026-07-25; rule version `38cfr-2026.07.25.1`. Clears live `kb_stale` synthesis
  freeze once deployed.
- **Unified first-run.** New empty profiles land on `/onboarding?start=1` (or
  `/documents` if records already exist) — no more profile-vs-onboarding fork.
- **Review queue prominence.** Primary nav item; Dashboard next-step prioritizes
  confirmations; Documents surfaces pending-review banner after processing.

### Added
- **Mobile bottom tab bar** (Raider · Home · Upload · Case · More) + always-visible
  988 crisis chip on mobile topbar.
- **Lean primary nav** with secondary tools collapsed under “More tools.”
- **Analysis quality metadata** (`full` / `partial` / `minimal` + notes) on
  comprehensive runs; Analysis Center amber banner when degraded.
- **File-readiness score + handoff** (`file_ready_score`, blockers, VA.gov/VSO/ITF
  links) and reusable `FileReadyHandoff` panel on Filing, Form 526, and Dashboard.
- Dashboard next-step when core evidence is identified: “You're ready to prepare
  filing.”

### Changed
- Product version **1.9.11**; release id `1.9.11-overnight.20260725`.

## [1.9.10] — 2026-07-20

### Added
- Durable, restart-safe comprehensive-analysis jobs with bounded retries,
  cancellation, lease fencing, worker heartbeats, and RLS-safe reconciliation.
- Fingerprinted release/rule metadata, public privacy-safe release identity,
  readiness enforcement, queue/KB/release metrics, alert rules, and a read-only
  synthetic canary.
- Credential-free backup/restore drills that validate complete artifact sets,
  reject unsafe archive members, and prove tenant isolation through a
  NOBYPASSRLS runtime role.
- Release, migration, rollback, SLO, rule-governance, evaluation-card, and
  release-hygiene gates. The prior raw research-session artifact is replaced by
  a curated public-source brief.

### Security
- Removed embedded object-store credentials from the backup script. Any exposed
  credential and previously published sensitive Git history still require
  operator rotation and approved history remediation before promotion.
- Raised FastAPI/Starlette, Pillow, and pillow-heif to patched release lines and
  made backend and frontend dependency audits required CI gates.

## [1.9.9] — 2026-07-14

### Fixed
- **Dashboard crash ("this page hit a snag") on a freshly-reset profile.** The
  journey stage detector (`isTransitioning`) called `.some()` on
  `profile.service_periods`, which a reset profile can return as `null` — the
  raw profile was reaching `detectStage` without going through `normalizeProfile`
  (the helper built precisely to coerce these nulls). Fixed at both levels:
  `detectStage`/`isTransitioning` now guard null arrays, and the Dashboard and
  Journey loaders normalize the profile before use, so no page reads `null.some`.

## [1.9.8] — 2026-07-14

### Changed
- **Dropped the streaming agent greeting.** Removed the Rating Raider "speaking"
  persona bubble and typewriter effect from the onboarding welcome (and the
  `StreamingText` component + caret CSS). The welcome is now a calm, immediate
  header + the three-phase overall-process map (Get organized → See where you
  stand → Take action) + first-action buttons — no persona monologue, no
  animation gate.

## [1.9.7] — 2026-07-14

### Changed
- **Welcome no longer gates action behind the animation.** The onboarding
  greeting still streams in, but the process map and first-action buttons are now
  live immediately instead of hidden until the typing finishes — the streaming is
  ambiance, not friction.
- **Theory-origination enabled (hosted).** Turned on the `THEORY_ORIGINATION_ENABLED`
  flag so the advocate proposes cited, confidence-tagged theories above the
  deterministic rule floor (adversarially reviewed, fail-closed). Runs on the
  local model under privacy mode — the deterministic floor is unchanged and every
  originated theory stays confidence-clamped and citation-verified.

## [1.9.6] — 2026-07-14

### Added
- **Streaming Rating Raider welcome.** The onboarding welcome is now a greeting
  from Rating Raider (your claims agent) that streams in like a live agent — a
  predetermined script with a typewriter reveal (click to skip; instant under
  reduced-motion). It frames the **overall** process as three phases — Get
  organized → See where you stand → Take action — making clear that filing a
  claim is one part of the journey, not the whole thing, with first-action
  buttons (bring in records / set up profile) that fade in when it finishes.
  New reusable `StreamingText` component + `vo-caret` cursor.

## [1.9.5] — 2026-07-14

### Changed
- **Journey map now fits the whole process in view.** Widened the page and let
  the stage nodes distribute evenly across the full width (instead of a fixed
  narrow size), so all eight stages read as one connected flow chart at a glance
  rather than packing to one side.

## [1.9.4] — 2026-07-14

### Fixed
- **Confirmed ratings now show on the Dashboard.** Accepting a "potential rating"
  from a document updates that condition's rating, but the Dashboard's hero dial
  reads the profile's *combined* rating — which was only ever set by VA import or
  manual entry, so a confirmed rating had no path to the dial and looked lost.
  Now, when there's no official combined rating stored, the dial shows a §4.25
  combined derived from the conditions you've confirmed ratings for (labeled
  "Estimated combined rating," with a note pointing to Profile to set your
  official number). It never overwrites or understates an authoritative value —
  it only fills the gap when none exists.

### Changed
- **Journey is now a horizontal flow map.** The "Your VA journey" page showed the
  eight stages as a tall vertical stack you had to scroll. It's now a compact
  horizontal map that wraps (serpentine) so the whole path is visible on one
  screen — each stage is a tappable node (behind = checked, current = highlighted,
  ahead = outlined, chevrons show the flow), and tapping one pulls up its detailed
  "what to do here" card below. Cleaner, and you can see where you are at a glance.

## [1.9.3] — 2026-07-14

### Fixed
- **"I confirmed my rating but it didn't do anything."** The "Confirm & update my
  ratings" button flipped itself to "Updated" the instant it was clicked —
  before the async update had actually persisted, and even when it failed or
  no-oped — so a click could look done while nothing changed, and the button
  then locked so it couldn't be retried. It now waits for the real result: shows
  an "Updating…" spinner while in flight, only marks "Updated" on a persisted
  success, stays live (retryable) on failure, and surfaces an explicit message if
  a line has no rating percentage to confirm.
- **Same fix for "Link to condition."** That button had the identical
  optimistic-on-click bug (showed "Linked" even if the link call failed); it now
  confirms only on success, with a "Linking…" in-flight state.

## [1.9.2] — 2026-07-14

### Added
- **Document grouping by type.** The Documents list now groups uploads by
  document type (in the same evidence-first order used everywhere), with a
  count per group, so a large pile reads clearly instead of as one long stream.
  Anything not yet classified collects under "Not yet sorted", and the softly
  "possibly not related" documents surface in their own group last (never hidden
  inside "Other"). A "Group by type" toggle (on by default, auto-disabled when a
  single type is already filtered) flips back to the flat list. Reuses the
  existing doc-type badges/hues — no new visual vocabulary.

## [1.9.1] — 2026-07-14

### Added
- **"What should I upload?" panel (surfaces M1 in the UI).** The Documents page
  now has a calm, collapsible panel under the drop area that lazy-loads the
  `GET /documents/upload-guidance` map the first time a veteran opens it (never
  on page load) and shows, per document type, what it is, concrete examples of
  what to upload, and why it helps. Educational self-help framing only; ordered
  most-common-evidence-first; degrades silently on an older backend. This
  completes the M1 arc — the guidance endpoint is now actually consumed.

## [1.9.0] — 2026-07-14

### Added
- **Doc-type "what to upload" guidance + endpoint (M1).** A deterministic,
  plain-language guide (`intake/doc_guidance.py`) for every classifier doc type —
  what it is, 2–4 concrete examples of what to upload, and why it helps — surfaced
  via `GET /documents/upload-guidance`. Educational self-help framing only (no
  invented VA form numbers, no outcome promises); a module assertion keeps the map
  in lockstep with `DOC_TYPES`, and `guidance_for()` never raises.
- **Analyze-after-upload opt-in (M2).** A "Run full analysis once these finish
  processing" checkbox on the Documents page. When checked, the app fires the
  comprehensive analysis exactly once, only after every doc in the uploaded batch
  settles and at least one reaches `ready` — never on page load or navigation.
- **Sidebar cleanup + tooltips + legends (F3).** The nav now shows only core
  per-phase items by default with secondary tools under a per-group "More tools"
  toggle (auto-expands on a hidden page; no routes removed). New keyboard-reachable
  `InfoTip`/`Tooltip` and a reusable collapsible `Legend` explain doc-type badges,
  the "possibly not related" relevance flag, duplicate markers, and confidence
  registers on the Documents and Analysis Center pages.

### Changed
- **Edit-before-accept for populated fields (F1).** Suggested identity/record values
  (name, DOB, phone, address parts, dependents) are now individually editable inputs
  before the veteran commits them — never all-or-nothing — with per-field provenance
  preserved. Nothing is "true" until adopted.
- **Profile-first onboarding (F2).** A brand-new veteran with an empty profile is
  routed once to `/profile?start=1` (one-shot localStorage guard; returning users go
  straight to the dashboard) with a welcome banner and skippable affordances. Pre-fill
  comes only from real extracted/derived values — no fabricated suggestions, no
  analysis call on load.

## [1.8.0] — 2026-07-13

### Added
- **Off-topic document flagging.** Intake now also reads each document for
  claim-relevance and softly flags one that looks like it doesn't belong to a VA
  claim (a stray receipt, a utility bill, an unrelated photo) so the veteran can
  review and delete it. It is a SUGGESTION only — nothing is auto-removed, and the
  guard is deliberately one-sided: an off-topic flag can land ONLY on an
  `other`/unclassified document, so real evidence (rating decisions, STRs, DBQs,
  treatment records, medical opinions, lay/service records) can never be flagged
  even if the model mislabels it, and a document that is a VA decision or mentions
  any condition is always treated as relevant. The label rides inside `extracted`
  (no migration); `DocumentOut` exposes `relevance` / `relevance_flagged` /
  `relevance_reason`, and the Documents page shows a gentle "this doesn't look like
  it belongs — delete?" notice. Local model, PII-on-fleet. 10 unit tests pin the
  safety invariant (a false flag on evidence is treated as a bug).

### Changed
- **Rename groundwork: "valor-ops" → "veteran-ops" (internal).** First, safe pass of
  the platform rename — internal log namespaces (`valor_ops.*` → `veteran_ops.*`) and
  the frontend package name. The user-facing brand ("Rating Raider" + the Sarge CWO
  persona) is unchanged. The cross-system identifiers that still read "valor" — the
  Keycloak client id, the Brigade JWT audience, the SSO entitlement gate, the
  `valor_app` DB role, the `VALOR_*` env aliases, the domains, and the Prometheus
  metric names — are deliberately deferred to a lockstep infra migration (renaming
  any of them in code alone would break auth / RLS / billing / dashboards).

## [1.7.0] — 2026-07-13

### Added
- **Assisted personal-statement drafting** (`POST /statement/assist`, "Draft from my
  records" on the Statement page). Proposes a first-person 21-4138 draft built ONLY from
  facts the veteran already recorded — their logged symptoms, in-service event, and
  condition notes — plus condition-specific prompts to jog their memory (phrased as
  questions, never assertions). The veteran edits every line, adopts it as their own
  words, and attests before signing. Invents nothing (missing details become `[add …]`
  blanks), never predicts an outcome, and — deliberately — never signs, submits, or
  files: the app proposes and organizes; the veteran authors and attests, the way a VSO
  assists. The verbatim `POST /statement/draft` path is unchanged. Local model,
  on-demand, PII-on-fleet.

## [1.6.0] — 2026-07-13

### Added
- **"To file, you still need…" delta on the Dashboard.** A prominent, deterministic
  (no AI, safe on every load) answer to *what's left to file*: it folds every
  condition's evidence gaps into one prioritized to-do list — what's missing, why it
  matters, which conditions need it, and a direct link to where to fix it (a nexus →
  `/nexus`, a diagnosis → `/documents`, …). Shared needs are grouped ("Medical nexus
  opinion — for Back and Neck") and needs blocking the most claims sort first. When
  every condition's core evidence is identified, it celebrates and points to the Battle
  Plan. `GET /analysis/file-readiness`. (First of the onboarding/file-readiness cluster.)

## [1.5.0] — 2026-07-13

### Added
- **Deep landscape scan** (`POST /analysis/landscape-scan`, on the Secondaries page as
  "Look deeper — leads to research"). The one agent that reaches beyond curated data: it
  uses the model's own medical knowledge to surface plausible secondary-connection LEADS
  the curated map doesn't have, each with a mechanism and an honest strength tag
  (well-documented / plausible / emerging). Framed strictly as hypotheses to research
  with a provider — never facts, never "you qualify." Opt-in (no model runs on page
  load); excludes connections already surfaced for the veteran; local model by default,
  forced local under privacy mode (it sends only condition names, not records). Model
  bake-off (Qwen vs DeepSeek-v4-flash vs frontier) settled the tier: local Qwen is
  capable; no frontier needed.

### Fixed
- Reviewer verdict contract now pins `confidence_level` to the exact VA-register enum
  (was occasionally emitting "high" — harmless, but a meant downgrade could be lost).

## [1.4.0] — 2026-07-13

### Added
- **"What's changed since you were rated" workflow** (`/whats-changed`). Compares the
  veteran's rating date (derived from their own rating-decision / decision-letter
  documents) against dated VA regulatory changes — rule revisions and new presumptives —
  and surfaces the ones that took effect *afterward* and touch their conditions (by
  diagnostic code) or service exposures. Built on the two rules: the facts (what changed,
  when, the source) come from a curated, cited backend dataset
  (`analysis/regulatory_changes.py`), **never AI**; only the optional per-item "what this
  means for me" read is model-generated, **on demand** (no model runs just by opening the
  page — `POST /analysis/whats-changed/{id}/assess`), local-first and PII-on-fleet.
  Proposed rules are always labeled "watch, not final." Reachable from the sidebar
  ("After you file"), the guided workflows, and its own page. 8 unit tests on the
  deterministic matching (a false "you may now qualify" is treated as a safety bug).

### Fixed
- Corrected the default `llm_model` from `qwen3.6-35b-a3b` to `qwen3.6-35b` — the id the
  UC gateway actually exposes (the wrong id 401s, silently degrading to
  deterministic-only output). Prod already overrode it via env; this fixes fresh/self-host
  installs.

## [1.3.0] — 2026-07-13

### Added
- **Journey spine on the Dashboard.** The home page now leads with "you're here + your
  single next move," detected from where the veteran actually is in the VA arc
  (lib/journey.ts), with a progress bar of the whole path and the tools that matter at
  this stage. When detection isn't confident (a brand-new profile) it says so and
  routes to /journey to confirm — never a false certainty.

### Changed
- **The sidebar is organized by journey phase, not tool category.** It now reads
  top-to-bottom as the veteran's arc — Start here → 1 · Build your claim → 2 ·
  Understand your rating → 3 · File your claim → 4 · After you file → Help — so the nav
  answers "where am I and what's next" instead of "what kinds of tools exist." Each
  page keeps its own theme and breadcrumb (resolved from its canonical section via
  VIEW_SECTIONS), so the regrouping changes only organization, not identity.

### Fixed
- **The sidebar logo/wordmark now links to the Dashboard** (desktop, mobile topbar,
  and the mobile drawer) — clicking it did nothing before.
- Corrected `VIEW_SECTIONS['vasync']` to `records` (it said `settings`, disagreeing
  with the Connect-VA page's own theme).

## [1.2.0] — 2026-07-13

### Added
- **Content-level near-duplicate detection.** The upload-time check only caught
  byte-identical files; VA C-files arrive in overlapping bundles and records get
  re-scanned, so the same content slips in as different bytes. Intake now fingerprints
  each document's extracted TEXT (normalized-content sha256 + a 64-bit SimHash) and,
  *before* the expensive classify/chunk/analysis work — and before charging a credit —
  auto-skips a document whose content exactly matches one already on file (status
  `duplicate`, excluded from all analysis so nothing is double-counted). A close-but-
  not-exact match is KEPT and softly flagged (`duplicate_of`), never silently dropped:
  VA records share heavy boilerplate, so fuzzy similarity only ever suggests a possible
  duplicate for the veteran to judge — it never auto-removes evidence. The Documents
  page shows a "Duplicate — skipped" state, and the intake benchmark reports how many
  were skipped.

## [1.1.1] — 2026-07-13

### Fixed
- **Analysis Center no longer blanks to the background.** A case-picture whose
  roster/timeline/contradiction items carry structured provenance (an object, or a
  list of them — what the comprehension map-reduce emits) was rendered as a raw React
  child, which throws "Objects are not valid as a React child" and, with no error
  boundary, unmounted the whole app to just the wallpaper. Provenance now renders via
  a safe `formatProvenance()` (humane "found in N places / pages X, Y of your file").
- **A page error can no longer take down the whole app.** Added an `ErrorBoundary`
  around the routed page area: a page-level throw now shows a recoverable "reload this
  page" card with the app shell intact, instead of a blank screen.

### Changed
- **Opening the Battle Plan no longer silently spins the GPU.** `GET /strategy/briefing`
  and `GET /strategy/deepdive` are now strictly cache-only — a plain page load never
  starts LLM work. The plain-language briefing and rating deep dive are produced only
  by an explicit action: the "Re-analyze" / "Run deep dive" buttons, or the
  comprehensive analysis run on `/analysis`. Until then the Battle Plan shows the
  complete deterministic plan and offers the run.

## [1.1.0] — 2026-07-12

### Added
- **Analysis Center** (`/analysis`) — one place to run every analysis. A single
  "Run Full Comprehensive Analysis" hero (specialist firm + plain-language briefing +
  exhaustive deep dive + whole-C-file comprehension), a targeted-analysis menu, the
  whole-C-file **Case Picture** panel (timeline, condition roster with the three
  service-connection elements, contradictions, coverage gaps), and a "what we've
  automated for you" panel.
- **Background comprehensive run with live progress** — the full pass now runs as a
  background job (`POST /analysis/comprehensive/start` → poll
  `/analysis/comprehensive/runs/{id}`) so a large C-file can't time out behind the
  proxy. A live panel streams each stage's status + wall-clock and a running total.
- **Per-file benchmark** — every run records per-step seconds + a total; a
  `GET /analysis/intake-benchmark` endpoint reports approximate document-intake cost,
  and a run-history table compares cold vs. warm runs.
- **Reset my records** (`POST /documents/reset`) — the veteran's own right-to-erasure
  of their C-file and everything derived from it (documents, facts, chunks, conditions,
  evidence, citations, scenarios, checklist, analysis caches, and document-extracted
  profile identity/dependents). Reachable from **Settings → "Your data"** and the
  Documents page. Preserves the account, onboarding inputs, deadlines, symptom logs,
  VA connections, and run history.
- **Re-OCR my records** — re-read already-uploaded documents through the current OCR
  pipeline (per-document `force_ocr` + a bulk `POST /documents/reprocess-ocr`).
- **Real-Postgres integration test tier** — `scripts/test-pg.sh` spins the prod
  database image (`pgvector/pg16`) and runs `backend/tests/integration/` as a
  NOBYPASSRLS role to prove Row-Level-Security genuinely enforces tenant isolation —
  the layer the fast SQLite unit suite can't exercise.

### Changed
- **OCR accuracy** — page preprocessing (deskew, upscale, denoise, autocontrast) is on
  by default, and a second decorrelated OCR engine (PaddleOCR, GPU) cross-reads intake,
  raising rating-critical token fidelity. Both OCR models run on GPU.
- **Presumptives** — each VA presumptive list (PACT Act, Agent Orange, …) now collapses
  behind an expandable disclosure instead of an always-open wall of condition pills.

### Fixed
- Reset entry surfaced in Settings so it is always reachable (previously only in the
  Documents search footer, which could be occluded and only rendered with ≥1 ready doc).

## [1.0.0]

Initial release: profile, conditions + evidence, the §4.25/§4.26 rating engine, KB
grounding, condition-mapping / secondary / presumptive analysis, the advocate + Game
Plan, document intake with OCR + cross-read, VA Lighthouse integration, multi-tenant
Postgres with FORCE Row-Level Security, and the MCP agent surface.
