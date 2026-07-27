# Legal accuracy audit — 2026-07-26

**Engineering baseline, not legal certification.**  
This document records what this engineering pass checked and changed in Rating Raider / Valor Ops. It is **not** a formal legal opinion, not accredited representation, and not a certification that the product’s VA-law content is complete or correct for every fact pattern. Accredited VSOs / attorneys should review before treating any rule as final.

---

## Scope of this pass

| Area | In scope | Out of scope |
|------|----------|--------------|
| Firm specialists (claims-legal lane) | New deterministic C&P prep + nexus-gap specialists; roster registration | Full multi-specialist “medical board” LLM agents |
| Presumptives ALS / POW | Authored cards, matcher logic, unit tests | Full §3.309(c) internment-duration branching UI |
| Bilateral §4.26 | Golden multi-extremity cases; no engine rewrite | Paired skeletal-muscle edge cases, amputation math |
| SMC / CRDP / CRSC | Not re-audited here | Deep SMC ladder, concurrent-pay edge cases |
| Content corpus | Spot-check programs `als`, `pow` | Full eCFR refresh of all rating_criteria / secondary maps |

Related product decisions (dual-use records GM vs claim file; C&P prep as claims medical prep, not diagnosing agents) remain as previously recorded.

---

## ALS / POW status

### POW — `program: pow` (38 CFR §3.309(c))

| Check | Status |
|-------|--------|
| Authored card in `backend/app/kb/data/presumptives.json` | **Present** — “Former prisoner of war (POW) presumptives”, source `38 CFR §3.309(c)` |
| Exposure flag | **`pow`** with `match: flag_only` (dates alone never match) |
| Matcher | `match_presumptives` honors `pow` via profile `exposures.pow` |
| Internment duration | **`pow_internment_days`** (optional): `None`/blank → any-period list only; `<30` → any-period; `≥30` → any-period ∪ 30-day lists (deduped). Educational UI on ExposuresEditor. |
| Specialist reg line | PresumptivesSpecialist maps `pow` → `38 CFR §3.309(c)` |
| Tests | `test_pow_presumptive_flag_match`, `test_pow_presumptive_no_flag_no_match`, `test_pow_internment_duration_branches_condition_lists` + golden `presumptive-pow-internment-branch` |

**Open (accredited review):** confirm internment “cumulative days” capture matches how VSOs document captivity length; confirm any edge conditions that sit only on one list.

### ALS — `program: als` (38 CFR §3.318)

| Check | Status |
|-------|--------|
| Authored card | **Added** this pass — title “ALS (amyotrophic lateral sclerosis)”, source `38 CFR §3.318` |
| Matching logic | **Condition-gated**: cumulative active service ≥ 90 days **and** claimed/considered condition name matches ALS keywords (`als`, `amyotrophic`, `lou gehrig`, `motor neuron`). 90+ days alone **never** matches (avoids spam). |
| API | `match_presumptives(..., condition_names=[...])` optional kwarg |
| Call sites | PresumptivesSpecialist + dossier `_suggestions` pass condition names |
| Specialist reg line | Already mapped: `als` → `38 CFR §3.318` |
| Tests | `test_als_presumptive_requires_condition_and_90_days`, `test_als_presumptive_no_match_under_90_days`, `test_cumulative_service_days` |

**Open (accredited review):** confirm “active continuous service” nuance vs cumulative calendar days as implemented; confirm inactive-duty / Guard edge cases are out of product scope or need separate flags.

---

## Bilateral §4.26 status

| Check | Status |
|-------|--------|
| Engine location | `backend/app/rating/engine.py` — pure §4.25 / §4.26 arithmetic |
| Reg worked examples | Covered: 60&20 → 75; 30&20 → 48; 10&10 → 21 |
| Both sides required | One-sided extremities get **no** bilateral factor |
| Multi-extremity same side-pair | Three sided entries with L+R present join **one** group |
| Upper + lower together (§4.26(b)) | **Golden tests added** this pass: four extremities single bilateral group; bilateral group + non-sided PTSD |
| SMC-S remainder + bilateral | Existing `test_smc_s_remainder_includes_bilateral_factor` |

No clear engine bugs found; no production arithmetic change in this pass—tests only.

**Open (accredited review):** paired skeletal muscles without left/right side tags; amputation / “loss of use” bilateral interactions; whether `group` labels should ever force separate bilateral pools (engine currently uses a single L/R pool when both sides exist).

---

## Firm specialists (claims-legal panel)

| Specialist | Kind | LLM | Notes |
|------------|------|-----|-------|
| Secondaries | `secondary` | enrich | Existing |
| Pyramiding | `pyramiding` + **`underrating`** (Esteban) | no | Underrating already seeded here — no separate specialist file |
| TDIU | `tdiu` | no | Existing educational screen |
| Presumptives | `presumptive` | no | Now ALS-aware via `condition_names` |
| **NexusEvidence** *(new)* | `nexus_gap` | no | Seeds when readiness `missing` includes nexus; route `/nexus` |
| **CpExam** *(new)* | `cp_exam_prep` | no | Per condition: `map_dbq`, still_needed, route `/cp-companion`; no “you will get X%” |
| Theory | theory layer | gated | Existing |

Raider tool `prepare_cp_exam` remains independent deterministic prep and does not conflict with CpExamSpecialist (same educational lane, separate surfaces).

---

## Remaining open items for accredited review

1. **POW internment duration** — *engineered* (any-period vs 30+ day lists). Accredited review still needed on capture UX and edge conditions.
2. **ALS service definition** — validate calendar-day cumulative proxy against §3.318 “active continuous service.”
3. **Bilateral edge cases** — skeletal muscle pairs, amputations, multi-group policies.
4. **Full presumptive corpus** — PACT / Agent Orange / Gulf War / Lejeune content vs current eCFR (not re-fetched this pass).
5. **SMC ladder beyond SMC-S screen** — educational flags only today.
6. **Secondary map medical theories** — clinical plausibility is not validated by engineers as medical fact.
7. **Decision-letter decoder legal phrasing** — separate from this pass.
8. **Esteban underrating hints** — keep educational; never auto-assert under-rating.

---

## Explicit disclaimer

> **This is an engineering baseline, not legal certification.**  
> Rating Raider / Valor Ops provides free educational self-help software for U.S. veterans. Nothing in this audit certifies regulatory completeness, fitness for a particular claim, or compliance with representation rules. VA decides claims. Veterans should confirm strategy and filings with an accredited VSO or attorney.

---

## Files touched (this pass)

- `backend/app/firm/specialists/cp_exam.py` *(new)*
- `backend/app/firm/specialists/nexus_evidence.py` *(new)*
- `backend/app/firm/specialists/__init__.py`
- `backend/app/firm/specialists/presumptives.py`
- `backend/app/firm/orchestrator.py`
- `backend/app/firm/context.py`
- `backend/app/firm/enumerate.py`
- `backend/app/analysis/presumptives.py`
- `backend/app/routers/analysis.py` (presumptives endpoint passes condition names)
- `backend/app/kb/data/presumptives.json`
- `backend/tests/test_firm.py`
- `backend/tests/test_api_analysis.py`
- `backend/tests/test_api_kb.py`
- `backend/tests/test_rating.py`
- `docs/LEGAL-ACCURACY-AUDIT-2026-07-26.md` *(this file)*

## Suggested verification

```bash
cd backend && pytest tests/test_firm.py tests/test_rating.py \
  tests/test_api_analysis.py tests/test_api_kb.py -q
```
