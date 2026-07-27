# WAVE 5 — Readiness · ITF reminders · Symptom log · Buddy-statement · C&P companion · Dump-everything (LOCKED CONTRACT)

"Yes to it all" — the full next queue, PLUS first-class dumping of files / folders / ZIPs for
any records or evidence. Same legal lane as the whole app: educational self-help, the veteran
drives, never files/represents, VSO referrals on anything actionable, the letter/VA controls.

Lead authors the SHARED files + correctness cores + data model. Agents own ONE new router
module + ONE new page each, building to the locked shapes below. NEVER edit a shared file
(models.py, db.py, schemas.py, main.py, api.ts, types.ts, App.tsx, Shell.tsx, hues.ts) — the
lead has already wired them; if something you need is missing, STOP and report it.

## Data model (lead — models.py / db.py / schemas.py)
- `SymptomLogEntry` (FENCED): id, user_id, condition_id (nullable FK→claimed_conditions SET NULL),
  entry_date (date), title (str), symptoms (text), severity (int 0–10 nullable),
  functional_impact (text nullable), criteria_tags (JSONB list[str] — §4 criteria phrases it
  supports), source (str: "manual"|"glitter"), created_at, updated_at.
- `ItfRecord` (FENCED): id, user_id, type (str: compensation|pension|survivors), filed_date (date),
  source (str: manual|va), notes (text nullable), created_at.
- Both added to FENCED_TABLES with the standard user_isolation policy. New tables → created by
  create_all on boot; no ALTER needed.

## Feature 1 — Readiness score (lead: readiness/score.py + routers/readiness.py)
`GET /api/readiness` → `{overall: {score, band, label, conditions_scored}, conditions: [{condition_id, name, claim_type, score, band, missing: [labels], satisfied: n, total: n}], disclaimer}`.
Deterministic: reuses analysis/gaps.analyze_gaps; score = round(100 * satisfied/total) with
total per claim_type {direct:4, secondary:3, presumptive:2, increase:2}, excluding the
informational "schedular maximum" item. Bands: 0–33 early(rose), 34–66 building(amber),
67–99 strong(sky), 100 complete(emerald).

## Feature 2 — ITF reminders (lead: routers/itf.py, reuses decoder/deadline.py)
- `GET /api/itf` → `{records: [{id, type, filed_date, source, notes, deadline, days_remaining, expired}], active: <the soonest-expiring not-yet-expired record or null>, disclaimer}`. deadline = filed_date + 1yr.
- `POST /api/itf` {type, filed_date, source?, notes?} → the record. `DELETE /api/itf/{id}` → 204.
- Also surfaces any VA-synced active ITF (from va/itf) as source="va" when the VA connector is on — read-only, best-effort, never fails the endpoint if VA is off.

## Feature 3 — Symptom log (AGENT S: routers/symptomlog.py + pages/SymptomLog.tsx + a print view)
Dated lay evidence mirroring §4 rating-criteria fields — the natural Glitter Mane bridge.
- `GET /api/symptomlog?condition_id=` → `SymptomLogEntryOut[]` (newest first).
- `POST /api/symptomlog` {condition_id?, entry_date, title, symptoms, severity?, functional_impact?, criteria_tags?} → entry.
- `PATCH /api/symptomlog/{id}` (partial) · `DELETE /api/symptomlog/{id}` → 204.
- `GET /api/symptomlog/criteria?condition_id=` → the §4 criteria phrases for that condition's
  diagnostic code, pulled from KB rating_criteria cards (kb.store), so the UI can offer
  tag chips. Returns `{diagnostic_code, tiers: [{percent, criteria: [phrases]}]}` or empty.
- `POST /api/symptomlog/import-from-glitter` → pull symptom/continuity entries for the veteran's
  email via the existing glitter bridge (routers/glitter.fetch_continuity), map to draft entries
  (source="glitter"), veteran CONFIRMS before persist is NOT required here — persist directly but
  tagged source="glitter" and clearly labeled; degrade cleanly (503-ish → empty) when GM is off.
- `GET /api/symptomlog/export?condition_id=` → `{markdown, entries_count, condition_name}` — a
  printable dated lay-evidence statement ("Statement in Support of Claim" style, FOR THE VETERAN'S
  SIGNATURE, never submitted). Frontend renders a print view.
Legal-lane: symptom log is the veteran's own lay evidence; never fabricate symptoms; export is
"prepared for your review and signature."

## Feature 4 — Buddy-statement builder (AGENT B: routers/buddy.py + pages/Buddy.tsx + BuddyPrint)
Guided VA Form 21-10210 (Lay/Witness Statement) builder → printable statement for a buddy/witness.
- `GET /api/buddy/guidance` → `{form, form_title, form_url, prompts: [str], tips: [str], disclaimer}`
  (what makes a strong buddy statement; grounded in 38 CFR §3.159(a)(2) / Layno).
- `POST /api/buddy/draft` {witness_name, witness_relationship, veteran_name?, condition?, observations, period?} → `{form, form_title, statement_markdown, guidance: [str], disclaimer}` — a deterministic 21-10210-formatted statement the WITNESS reviews, edits, and signs. Never auto-submitted.
Follow the records.py worksheet + RecordsPrintViews.tsx print pattern EXACTLY (print route, no shell chrome).

## Feature 5 — C&P exam companion (AGENT C: routers/cp.py + pages/CpCompanion.tsx)
Prepare the veteran for a Compensation & Pension exam per condition — educational.
- `GET /api/cp/conditions` → the veteran's conditions (id, name, diagnostic_code, claim_type) for the picker.
- `GET /api/cp/{condition_id}` → `{condition: {...}, dbq: <mapped DBQ form or null>, what_to_expect: [str], rating_criteria: [{percent, criteria:[phrases]}] (from KB), how_to_describe: [str], dos: [str], donts: [str], disclaimer}`.
  Ground rating_criteria + DBQ in the KB (kb.store / analysis.map_dbq). how_to_describe teaches
  honest worst-day/frequency/duration framing; donts includes "never exaggerate — it can void the exam."
Educational only; not medical advice; the examiner's findings drive the rating.

## Dump-everything (lead: DropZone.tsx + Documents.tsx + Evidence surfaces)
The existing intake already takes multi-file + ZIP (bomb-guarded, 200MB) + OCR + local-LLM classify.
Add:
- **Folder upload**: a "Select folder" control (`webkitdirectory`) AND recursive directory
  drag-drop (walk `DataTransferItem.webkitGetAsEntry()` directories) so a veteran can literally
  drop a whole folder tree. All files flatten into the same multi-file upload the server already
  handles; per-file caps + dedupe + ZIP expansion unchanged.
- Keep the reframed copy: "Dump everything — any records or evidence, in any mix of loose files,
  folders, or ZIPs; sorted privately on our own servers."

## Shared frontend wiring (lead — api.ts, types.ts, App.tsx, Shell.tsx, hues.ts)
New views/sections/hues (register in VIEW_SECTIONS + VIEW_HUES):
- readiness → section 'claim' (or 'home' surfacing); nav under Claim tools. hue: emerald family.
- itf → surfaced on Dashboard + a small page; section 'claim'. hue: sky.
- symptomlog → section 'claim', nav "Symptom log". hue: teal.
- buddy → section 'records', nav "Buddy statement". hue: pink/orange.
- cp → section 'guide', nav "C&P companion". hue: indigo.
Agents' pages import their `*Api` block + types from api.ts/types.ts (lead pre-writes them to the
shapes above). If a field is missing, STOP and report — do not edit api.ts/types.ts.

## Tests
Lead: readiness scoring (per claim type, bands, exclude schedular-max), ITF countdown, model/RLS
smoke via the SQLite harness. Each agent: unit-test their pure assembler + endpoint (SQLite harness
from test_api_documents.py, auth overridden, GM/LLM monkeypatched, no network/live PG).
