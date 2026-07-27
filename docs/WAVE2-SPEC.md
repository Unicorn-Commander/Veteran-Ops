# Rating Raider — Wave 2 Spec (LOCKED)

Additive to docs/BUILD-SPEC.md (still authoritative for everything it covers). Brand is now
**Rating Raider**; infra identifiers unchanged (repo valor-ops, SKU valor-ops, host
valor.magicunicorn.dev, container/db names).

## New features

### 1. Onboarding wizard (frontend `/onboarding`)
First-run (no profile row → Dashboard prompts; also reachable from Settings). Steps:
1. Welcome + the legal-lane framing (friendly, not the modal again).
2. Service history (same editor as Profile, shared components).
3. Exposures (checkboxes + locations; explain each program in one line).
4. Current ratings: "already rated?" → add current conditions+percents quickly (creates
   claimed_conditions with claim_type=increase status=considering current_rating set)
   OR skip.
5. What are you considering claiming? quick-add conditions (name + body system).
6. Records check: which do you have? (DD-214, STRs, C-file, VA medical records, private
   records) → for each missing one, generate checklist items pointing at the records-request
   flows (category "records").
7. Finish → dashboard; ITF nudge card if any condition exists and no ITF checklist item done.
Wizard PUTs profile + POSTs conditions/checklist via existing APIs. No new backend needed
except `GET /profile` already 200s with nulls (frontend normalizes — see Profile.tsx pattern).

### 2. Records requests (`/records` page + KB `process` cards, category "records")
Self-help automation: PRE-FILL, veteran signs/submits (never submit for them — legal lane).
Frontend page lists each record type as a card with: what it is, why it matters, the
automated path, and a "Add to checklist" button.
- DD-214 / OMPF: milConnect online (guided steps), or NPRC via SF-180 — backend endpoint
  `GET /records/sf180?prefill=1` returns prefilled data JSON (name, branches, service dates
  from profile) the frontend renders into a printable SF-180 worksheet (print view like the
  packet; veteran copies onto the official form or brings worksheet to VSO). Include eVetRecs
  link guidance.
- VA claims file (C-file): VA Form 20-10206 (FOIA/PA) — same prefill worksheet pattern.
- VA medical records: VA.gov Blue Button download — guided steps card (no form).
- STRs: included in C-file/OMPF guidance.
- Private records: per-provider request letter generator — `POST /records/request-letter`
  {provider_name, address?, condition_ids[]} → letter text (deterministic template, no LLM)
  the veteran prints/signs; also creates evidence_items status=requested.
Backend router `records.py` (prefix /records): prefill endpoints read profile via RLS; audit.

### 3. Military records CORRECTION (educational — `/corrections` page + KB cards)
DIFFERENT legal process from VA claims (military department boards). KB process cards
(card_type `process`, body_system `corrections`, authored by orchestrator — DO NOT write
these cards yourself):
- DRB discharge review (DD Form 293, 10 U.S.C. §1553, 15-year window)
- BCMR/BCNR (DD Form 149, §1552, catch-all incl. >15yr)
- DD-215 / how corrections issue
- Liberal consideration (PTSD/TBI/MST — Hagel/Kurta/Wilkie memos)
- Why it matters for VA benefits (character-of-discharge bar, §3.12)
Frontend `/corrections`: guide page rendering those cards (same pattern as /filing) +
"add to checklist" actions. Nav section "Records" groups /records + /corrections.

### 4. Document intake pipeline (the big one)
Veteran dumps files (rating decisions, STRs, DBQs, treatment records, decision letters,
lay statements) → OCR → classify → extract → link.
- New FENCED table `documents`: id, user_id, filename, content_type, size_bytes,
  sha256 (dedupe per user), status enum-str `uploaded|processing|ready|failed`,
  doc_type enum-str `rating_decision|decision_letter|str|dbq|treatment_record|lay_statement|
  service_record|other` (nullable until classified), doc_date date nullable, title,
  summary text, extracted JSONB (see below), text_content text (OCR/parsed), condition_id
  FK nullable (primary link), file_ref (disk path under /app/uploads/{user_id}/),
  created_at, updated_at. ADD "documents" to FENCED_TABLES in db.py.
- Endpoints (router documents.py, prefix /documents): POST /documents (multipart, multiple
  files, cap 25MB/file, pdf/png/jpg/tiff/txt; sha256 dedupe → 409-style skip flag),
  GET /documents?status=&doc_type=, GET /documents/{id} (full incl. extracted),
  PATCH /documents/{id} (veteran corrects doc_type/title/condition link),
  DELETE /documents/{id}, POST /documents/{id}/reprocess,
  POST /documents/{id}/link {condition_id, kind} → creates evidence_item status=have
  with file_ref, linked to condition.
- Processing (async task per doc, in-process asyncio like GM's pattern — read GM
  backend/app/routers/documents.py + rag/ocr.py + medical/extraction.py and mirror):
  1. text: pdf text layer (pypdf) else OCR (settings.ocr_base_url multipart POST /ocr,
     optional) else vision-model fallback via gateway; txt read directly.
  2. classify + extract via gateway LLM (LOCAL ONLY — PII guard already enforces):
     strict-JSON prompt → {doc_type, doc_date, title, summary(2 sentences),
     conditions_mentioned: [{name, rating_percent?, diagnostic_code?, decision? granted|denied|deferred}],
     is_va_decision: bool}. VALIDATION: doc_type must be in the enum; percents 0-100
     multiples of 10 or null; drop anything else. Store in extracted.
  3. suggestions, deterministic: fuzzy-match conditions_mentioned against user's
     claimed_conditions (casefold substring) → extracted.suggested_links =
     [{condition_id, name, match}] — veteran confirms in UI (link endpoint); NEVER
     auto-link without confirmation.
- Rating-decision special case: if is_va_decision and conditions_mentioned carry percents,
  extracted.rating_summary lists them; UI offers "update my current ratings" (PATCHes
  claimed_conditions current_rating / creates condition with claim_type increase) —
  again veteran-confirmed, never automatic.
- Uploads volume already exists in compose (valor-uploads:/app/uploads). Wire nginx
  client_max_body_size 30m (frontend nginx.conf) + backend limit.
- Frontend `/documents`: drop-zone (multi-file), processing list with live status
  (poll every 3s while any processing), review cards (doc type chip editable, summary,
  extracted conditions with "link to..." confirm buttons, rating-decision import flow),
  filter by type/status, delete. Route in nav under "Records".

### 5. Glitter Mane bridge UI
/settings gains a "Connections" card: GET /glitter/status → show configured/reachable;
when live: /conditions page gets "Import from Glitter Mane" button (lists GM conditions
via GET /glitter/conditions, multi-select → POST /glitter/import-conditions), and packet
continuity section explained. (Server env wiring is ops, done by orchestrator.)

## Ownership (parallel agents — do not cross)
- Agent BACKEND-INTAKE: backend/app/routers/{documents,records}.py, backend/app/intake/*.py
  (ocr/classify/process), models.py + schemas.py + db.py EDITS (additive only: documents
  table + FENCED_TABLES + schemas), backend/tests/test_api_documents.py, compose uploads
  wiring check, requirements additions (pypdf, python-multipart if missing).
- Agent FRONTEND-FEATURES: frontend/* — onboarding wizard, /records, /corrections,
  /documents, Settings connections card, GM import UI, nav regrouping. Read the real
  routers for shapes (BUILD-SPEC lesson: routers are truth).
- Orchestrator: corrections + records KB cards, GM bridge env, prod deploy.
Coordination: FRONTEND-FEATURES may run before BACKEND-INTAKE finishes ONLY on
onboarding/records/corrections; documents UI must be built against the real
documents.py (wait or re-verify shapes at the end).

## Copy rules
Same legal lane as BUILD-SPEC. Records requests/corrections pages must say: free VSO help
exists at every step; forms are prepared FOR YOUR SIGNATURE — you submit them.
