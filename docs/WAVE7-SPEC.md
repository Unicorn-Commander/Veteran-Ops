# Wave 7 — Appeals draft assist · Real fillable 21-526EZ PDF · Code-split + mobile

Three tracks. **Lead (Claude) owns every shared file and both correctness-critical
cores.** Two agents build separable features against the locked shapes below and
**never touch a shared file**.

Legal lane (unchanged, load-bearing — 38 CFR §14.629): educational self-help
software the veteran operates. Rating Raider is NOT a VA-accredited representative,
does NOT file or appeal anything, and NEVER renders a medical opinion. Every
denial/appeal path routes to a free VSO. All produced paperwork is "prepared for
YOUR review and signature." The veteran's own words pass through VERBATIM.

## Ownership

Shared files — LEAD ONLY (agents must not edit):
- backend: `app/schemas.py`, `app/main.py`, `app/routers/form526.py`
- frontend: `src/lib/api.ts`, `src/lib/hues.ts`, `src/types.ts`, `src/App.tsx`,
  `src/components/Shell.tsx`, `frontend/index.html`, `vite.config.ts`

Track A — Appeals draft assist → **Agent A** owns exclusively:
- `backend/app/appeals/__init__.py`, `backend/app/appeals/draft.py`
- `backend/app/routers/appeals.py`
- `backend/tests/test_appeals.py`
- `frontend/src/pages/Appeals.tsx`, `frontend/src/pages/AppealsPrint.tsx`

Track B — Real fillable 21-526EZ PDF → **LEAD** owns:
- `backend/app/pdf/__init__.py`, `backend/app/pdf/form526_fill.py`
- `backend/app/pdf/templates/va-21-526ez.pdf` (bundled: VA Form 21-526EZ, **JAN 2026**,
  OMB 2900-0747, 15 pages, 357 AcroForm fields — introspected & verified)
- `GET /form526/pdf` endpoint added to `routers/form526.py`
- `backend/tests/test_form526_pdf.py`
- download button + "what's filled / what you complete" panel in `pages/Form526.tsx`

Track C — Route code-split + mobile responsive → split:
- **LEAD**: React.lazy + Suspense in `App.tsx`; manualChunks in `vite.config.ts`.
- **Agent B** owns a responsive pass on the page set listed in §C (page bodies only).

---

## Track A — Appeals draft assist (Supplemental Claim / HLR / Board)

Extends the decoder. After a denial (surfaced by the decoder, cached in a
document's `extracted['decode']`) — or for any claimed condition — help the
veteran DRAFT a decision-review response. Primary lane: **Supplemental Claim (VA
Form 20-0995)**, which requires NEW and RELEVANT evidence. Also offer Higher-Level
Review (20-0996) and Board Appeal (10182) as educational lanes.

Reuse existing building blocks:
- `app/decoder/deadline.py::appeal_window(decision_date, today)` — the 1-year AMA window.
- `app/decoder/analyze.py::_lanes(source)` — the three AMA lanes (import & reuse; do
  NOT re-author the lane copy). If not importable cleanly, replicate the same three
  dicts verbatim.
- Missing-element vocabulary: `current_disability | in_service_event | nexus`
  (same three §3.303 elements the whole app uses).

### Endpoints (`routers/appeals.py`, prefix `/appeals`)

`GET /appeals/candidates` → `AppealCandidatesOut`
- Candidates from TWO sources, per user (RLS via `current_user_id`):
  1. `decoded_letter`: every ready document that is a VA decision AND has a cached
     decode (`extracted['decode']`); one candidate per **denied** decision row.
     Carry name, diagnostic_code, missing_elements, document_id, decision_date,
     appeal_window (recomputed with today).
  2. `condition`: every ClaimedCondition (source='condition', condition_id, name,
     diagnostic_code; decision=None, missing_elements=[]). Lets a veteran draft a
     supplemental claim even without an uploaded letter.
- `new_evidence`: for each candidate, the veteran's EvidenceItem rows with
  status=='have' whose condition matches by name (case-insensitive) or by
  condition_id — these are the "new and relevant" candidates. `AppealEvidenceRef`.
- Also return the three `lanes` (educational), `vso_referral`, `disclaimer`.
- Pure helper `build_candidates(...)` in `appeals/draft.py`; router does DB only.

`POST /appeals/draft` (body `AppealDraftIn`) → `AppealDraftOut`
- PURE assembly in `appeals/draft.py::build_appeal_draft(payload, today, prepared_on)`.
- For each contention: plain-English of each missing element
  (`_MISSING_PLAIN` map below), the veteran's `new_evidence_titles` echoed as the
  "new and relevant evidence" list, the veteran_statement VERBATIM (never rewritten),
  and a `what_this_addresses` sentence tying the chosen lane to the missing element.
- Lane-aware framing:
  - supplemental_claim → emphasize NEW and relevant evidence; note filing within one
    year of the decision preserves the effective date.
  - higher_level_review → NO new evidence; a senior reviewer re-examines the same
    record for error; informal conference available.
  - board_appeal → Veterans Law Judge; direct/evidence/hearing dockets.
- Always include: `deadline` (appeal_window from decision_date, may be all-None),
  `lane_guidance` (the three lanes), `veteran_attestation`, `signature_block`,
  `vso_referral`, `disclaimer`, `source_note`.

`_MISSING_PLAIN = {`
`  "current_disability": "a current, diagnosed disability (a doctor's diagnosis today)",`
`  "in_service_event": "an in-service event, injury, exposure, or illness in your service records",`
`  "nexus": "a medical link (\"nexus\") connecting your current diagnosis to your service",`
`}`

### Locked schema shapes (LEAD adds to `schemas.py`; Agent A imports)

```
AppealEvidenceRef:      { kind: str, title: str }
AppealCandidate:        { source: "decoded_letter"|"condition", name: str,
                          diagnostic_code: str|None, decision: str|None,
                          missing_elements: list[str], document_id: str|None,
                          condition_id: str|None, decision_date: str|None,
                          appeal_window: dict|None, new_evidence: list[AppealEvidenceRef] }
AppealCandidatesOut:    { candidates: list[AppealCandidate], lanes: list[dict],
                          vso_referral: str, disclaimer: str }
AppealDraftContentionIn:{ name: str, diagnostic_code: str|None=None,
                          missing_elements: list[str]=[], new_evidence_titles: list[str]=[],
                          veteran_statement: str|None=None }
AppealDraftIn:          { lane: "supplemental_claim"|"higher_level_review"|"board_appeal"
                            = "supplemental_claim",
                          decision_date: str|None=None,
                          contentions: list[AppealDraftContentionIn] }   # >=1 required
AppealDraftContentionOut:{ name, diagnostic_code, missing_element_plain: list[str],
                          new_and_relevant_evidence: list[str],
                          veteran_statement: str|None, what_this_addresses: str }
AppealDraftOut:         { lane_key, lane_title, lane_form, prepared_on: str|None,
                          heading, intro, contentions: list[AppealDraftContentionOut],
                          deadline: dict|None, lane_guidance: list[dict],
                          veteran_attestation, signature_block, vso_referral,
                          disclaimer, source_note }
```

### Frontend (Agent A)
- `Appeals.tsx` (`data-section="insight"`, view key `appeals`, hue fuchsia): loads
  `appealsApi.candidates()`. Empty state → point to the decoder / conditions. Lets the
  veteran (1) pick a lane, (2) select candidates, (3) tick which "new evidence" applies,
  (4) type their own statement per contention, then `appealsApi.draft(...)` and hand off
  to the print view via `sessionStorage['vo_appeal_draft']` (Decode/Form526 handoff
  pattern), navigating to `/appeals/print`.
- `AppealsPrint.tsx`: standalone `RequireAuth` route (no Shell), uses
  `PrintShell`/`PrintDoc` (`components/print/*`) exactly like `Form526Print.tsx`.
  Reads the draft from sessionStorage; renders heading/intro, per-contention blocks
  (plain missing element, new & relevant evidence, veteran statement verbatim, what it
  addresses), deadline countdown, lane guidance, attestation, signature block, VSO
  referral, disclaimer footer. Read `Form526Print.tsx` first and mirror it.
- Use `apiCall`/loading/error patterns from an existing page (e.g. `Buddy.tsx`).
- Do NOT edit api.ts/types.ts/hues.ts/App.tsx/Shell.tsx — LEAD wires nav+route+api+types.

---

## Track B — Real fillable 21-526EZ PDF (LEAD)

`app/pdf/form526_fill.py`:
- `TEMPLATE = <app/pdf/templates/va-21-526ez.pdf>`; `FORM_EDITION = "JAN 2026"`;
  `FORM_OMB = "2900-0747"`.
- Pure `build_field_values(*, full_name, email, service_periods, contentions) -> dict`
  mapping ONLY high-confidence data to exact AcroForm field names:
  - name split → `Veteran_Service_Member_First_Name[0]` / `_Last_Name[0]` / `_Middle_Initial[0]`
  - `Email_Address_Optional[0]`
  - first service period → `Beginning_Date_{Month,Day,Year}[0]` / `Ending_Date_{...}[0]`
  - claim process → check `Standard_Claim_Process[0]` (`/1`)
  - each condition i (0..14) → `#subform[10].CURRENTDISABILITY[i]` = name;
    `ExplainHowDisabilityRelatesToEvent_Exposure_Injury[i]` = in_service_event (trunc);
    onset date → `Date_Disability_Began_Or_Worsened[i]` when present (i has a date field).
  - NEVER fill SSN, VA file number, DOB, address, or signature — we don't collect them;
    the veteran completes those. `AUTO_FILLED` / `YOU_COMPLETE` label lists exported for the UI.
- `fill_pdf(values: dict) -> bytes`: pypdf PdfReader→PdfWriter(append), set
  NeedAppearances, `update_page_form_field_values(...auto_regenerate=False)`, set doc
  metadata Title = "DRAFT VA Form 21-526EZ — review, complete, and sign before filing
  (prepared with Rating Raider; we do not file for you)". Return bytes. NO fitz (optional-only).
- `GET /form526/pdf` (in form526.py): reuse the same data-gather as `get_form526`,
  build values, StreamingResponse `application/pdf`,
  `Content-Disposition: attachment; filename="VA-21-526EZ-DRAFT-review-and-sign.pdf"`.
- Test: seed user+profile+conditions+evidence (SQLite harness), GET /form526/pdf,
  reopen bytes with pypdf, assert name/service-year/first-condition landed and SSN blank.
- Form526.tsx: "Download pre-filled PDF (JAN 2026 edition)" button + a panel listing
  what's auto-filled vs. what you must still complete & sign; keep the existing
  worksheet. Prominent: not filed, review every field.

---

## Track C — Code-split (LEAD) + mobile responsive (Agent B)

LEAD: convert `App.tsx` page imports to `React.lazy`, wrap `<Routes>` content in
`<Suspense fallback={<RouteFallback/>}>`; add `manualChunks` (react/vendor, katex if
present) in `vite.config.ts` to quiet the 500KB warning.

Agent B — responsive pass, PAGE BODIES ONLY, over: `Dashboard.tsx`, `Conditions.tsx`,
`ConditionDetail.tsx`, `Documents.tsx`, `Decode.tsx`, `Readiness.tsx`, `Calculator.tsx`,
`Backpay.tsx`, `SymptomLog.tsx`, `CpCompanion.tsx`. Hunt ONLY known anti-patterns and
fix in place: (1) flex children missing `min-w-0` that cause horizontal overflow,
(2) wide tables/grids without an `overflow-x-auto` wrapper, (3) fixed pixel widths that
should be `max-w-full`, (4) multi-column grids that don't collapse to 1 col on small
screens (add `grid-cols-1 sm:grid-cols-…`), (5) touch targets < 40px on primary actions.
Do NOT restyle, recolor, or change copy/logic. Must not touch Form526.tsx, Appeals*.tsx,
or any shared file. Run `npm run build` + typecheck; report exactly what changed per file.

---

## Definition of done
- Backend tests all green (existing 303 + new appeals + pdf tests).
- `npm run typecheck` + `npm run build` clean; bundle no longer emits the >500KB warning.
- Deploy: git bundle → edge-host → `docker compose -p valor-ops -f docker-compose.edge-host.yml
  up -d --build backend frontend`. Prod E2E through public HTTPS with a seeded temp user
  (server-side seed; delete after): appeal draft renders (verbatim statement preserved,
  no medical opinion), /form526/pdf returns a real filled PDF (fields verify, SSN blank),
  new routes live, mobile has no horizontal scroll. Record in memory + Project-Ops P-00113.
