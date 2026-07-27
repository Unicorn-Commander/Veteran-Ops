# WAVE 6 — Produce the paperwork + installable (LOCKED CONTRACT)

Turns Rating Raider from "organize your claim" into "…and here's your completed paperwork."
Three print-ready builders + PWA installability. Same legal lane: educational self-help,
the veteran (or their provider/witness) reviews and signs, the app NEVER submits or files
anything, VSO referrals on anything actionable. Every artifact is "prepared for your review
and signature — file it yourself at VA.gov or bring it to a free VSO."

Lead owns SHARED files + PWA + scaffolding. Agents own ONE router + their page(s) each. Do
NOT edit shared files (schemas.py, main.py, api.ts, types.ts, App.tsx, Shell.tsx, hues.ts,
index.html, public/*) — the lead has wired them. No new DB tables this wave (all builders read
existing data or are pure template renders).

## Shared shapes (lead — schemas.py, api.ts, types.ts) — build to these EXACTLY

### Feature 1 — 21-526EZ application packet (AGENT A: routers/form526.py + pages/Form526.tsx + Form526Print.tsx)
A completed, print-ready Application for Disability Compensation (VA Form 21-526EZ), ASSEMBLED
from data already in the app (profile, conditions, evidence, ITF) — like the packet/records
worksheets. NOT the fillable government PDF (no reliable AcroForm map exists); a faithful,
sectioned worksheet the veteran reviews, signs, and transcribes onto VA.gov or hands a VSO.
- `GET /api/form526` → `Form526Out`:
  ```
  { veteran: {name, email}, prepared_on: null,
    service: {periods:[{branch,component,start_date,end_date,discharge_character}], combat, exposures:[str]},
    contentions: [{name, diagnostic_code, claim_type, current_rating, onset_date, in_service_event,
                   secondary_to_name, evidence_have:[{kind,title}], evidence_needed:[{kind,title}]}],
    itf: {type, filed_date, deadline, days_remaining, expired} | null,   // soonest-active ITF
    completeness: {conditions, with_evidence, missing_evidence},
    guidance: [str], disclaimer: str, source_note: str }
  ```
  Assemble from VeteranProfile + ClaimedCondition + EvidenceItem + ItfRecord (reuse the itf
  countdown helper). Educational; `guidance` = how to file (VA.gov / VSO), what to attach.
- Page (`data-section="records"`, hue amber): show the assembled application in review form, a
  completeness banner, and a "Print / save as PDF" → `/application/print` (stash to sessionStorage
  key `vo_form526`, mirror BuddyPrint). Print view = PrintShell/PrintDoc letterhead, all sections.

### Feature 2 — Nexus-letter builder (AGENT B: routers/nexus.py + pages/Nexus.tsx + NexusPrint.tsx)
A medical-nexus opinion letter template the veteran brings to their PROVIDER to complete and sign
("at least as likely as not" — the linchpin of most claims). Never written as if by the provider;
it's a template FOR the provider.
- `GET /api/nexus/guidance` → `{what_it_is, why_it_matters, prompts:[str], tips:[str], disclaimer}`
  (grounded: 38 CFR §3.303/§3.310; the "at least as likely as not" ≥50% standard; must be from a
  qualified provider; must give a rationale).
- `POST /api/nexus/draft` {veteran_name?, condition, diagnostic_code?, claim_type?, in_service_event?,
  secondary_to?, clinical_summary?} → `{title, letter_markdown, guidance:[str], disclaimer}`.
  Deterministic template with the opinion line, a rationale placeholder the PROVIDER fills, and a
  provider signature/credentials/date block. Handles direct vs secondary framing. Never fabricates a
  medical opinion — the opinion + rationale are the provider's to write/sign.
- Page (`data-section="records"`, hue orange): guidance + form + live preview (nexusApi.draft) +
  print (`/nexus/print`, sessionStorage `vo_nexus_draft`).

### Feature 3 — Personal statement / VA Form 21-4138 (AGENT C: routers/statement.py + pages/Statement.tsx + StatementPrint.tsx)
The veteran's OWN Statement in Support of Claim (21-4138) — for narrative the records don't show
(in-service event/stressor, why records are missing, how symptoms affect daily life). Distinct from
the symptom-log export (that's symptom-derived; this is free-form narrative).
- `GET /api/statement/guidance` → `{form:"VA Form 21-4138", form_title, form_url, prompts:[str], tips:[str], disclaimer}`.
- `POST /api/statement/draft` {veteran_name?, condition?, topic, statement, period?} → `{form, form_title, statement_markdown, guidance:[str], disclaimer}`.
  Deterministic 21-4138-formatted render (heading, "I am submitting this statement regarding…", the
  veteran's words, a truthfulness attestation, signature/date block). Never fabricate facts.
- Page (`data-section="records"`, hue amber): guidance + form + live preview + print
  (`/statement/print`, sessionStorage `vo_statement_draft`).

## Nav (lead — Shell.tsx, records section)
Add under "Records": Application (21-526EZ) [FileСheckShort icon], Nexus letter, Personal statement —
alongside the existing Buddy statement. Views: form526, nexus, statement → section 'records';
hues form526=amber, nexus=orange, statement=amber.

## Routes (lead — App.tsx)
In-shell: /application, /nexus, /statement. Standalone print (RequireAuth, no shell):
/application/print, /nexus/print, /statement/print.

## PWA + mobile (lead)
- `public/manifest.webmanifest` (name "Rating Raider", short_name, theme/background #7c5cff / dark,
  display standalone, start_url "/", icons → an SVG app icon `public/icon.svg`, maskable).
- `public/icon.svg` — brand app icon (shield/raider mark in brand violet).
- `index.html`: link manifest, apple-touch-icon, apple-mobile-web-app-capable + title, keep viewport.
- NO caching service worker (the suite has a history of stale-bundle pain behind nginx/CF — installability
  via manifest only). Note this choice.
- Mobile: verify the new pages use max-w + responsive stacking; the Shell drawer already handles nav.

## Tests
Each agent: pure assembler/template tests + endpoint tests (SQLite harness from test_api_documents.py
for the DB-reading 526 router; bare-app + auth-override for the pure nexus/statement routers like
test_open_data.py). Legal-lane assertions (no "we file for you"; provider/veteran signs). No network,
no live PG. Lead: keep the full suite green; frontend build clean.
