# WAVE 4 — Decision-Letter Decoder (LOCKED CONTRACT)

The #1 nationally unmet veteran need (reached Congress; no dedicated app exists).
Extends the existing intake pipeline: a VA rating decision / decision letter the
veteran already uploaded is decoded into plain English + actionable next steps.

**Legal lane (load-bearing, same as the rest of the app):** educational only.
Never "we'll appeal for you." Every next-step surfaces a free VSO referral. The
VA's official combined evaluation on the letter CONTROLS — our recompute is an
educational cross-check, never presented as authoritative. Denial-reason decoding
is explicitly "our plain-language reading — read the letter and talk to a VSO."

---

## Backend — `backend/app/decoder/` (authored by lead; DO NOT rewrite)

Pure functions + one LLM pass (propose/dispose split, mirrors intake/classify.py).

- `deadline.py` — pure appeal-window math (no dateutil): `add_one_year(d)` (Feb-29→Feb-28), `appeal_window(decision_date, today)` → `{deadline, days_remaining, expired}`.
- `combined_check.py` — pure: recompute the §4.25 combined from GRANTED percents via `rating/engine.combined_rating`, compare to the VA-stated combined. Returns `{va_stated, computed, matches, note}`.
- `schema.py` + `decode.py` — the decode LLM pass: extends extraction with per-condition `effective_date` + `reasons_plain` + denied-element flags, and the overall `combined_evaluation`. Pure validators dispose of anything off-contract.
- `analyze.py` — pure assembler: builds the final decode payload, grounding the appeal-lane copy against KB `process` cards passed in.

## Endpoint (documents.py router)

`POST /api/documents/{id}/decode` → 200 `DecodeOut`. Runs the decode on the stored
decision letter's `text_content` (no re-upload). Caches the result in
`Document.extracted['decode']`. 409 if the document isn't a VA decision / has no
text. `GET /api/documents/{id}/decode` → cached `DecodeOut` or 404.

`GET /api/documents/decodable` → `list[DocumentOut]` — every ready document that is
a VA decision (doc_type in {rating_decision, decision_letter} OR
extracted.is_va_decision). Registered BEFORE `/{document_id}` so the literal wins.

## `DecodeOut` payload (THE LOCKED SHAPE — frontend builds to this)

```jsonc
{
  "document_id": "uuid",
  "decoded_at": "2026-07-06T…Z",
  "decision_date": "2019-03-14",          // null if unknown
  "decisions": [                          // one per contention
    {
      "name": "PTSD",
      "diagnostic_code": "9411",          // or null
      "decision": "granted",              // granted|denied|deferred|null
      "rating_percent": 50,               // or null
      "effective_date": "2018-11-02",     // or null
      "va_classification": "Mental Disorders",       // from contention taxonomy, or null
      "va_classification_code": 8989,                // or null
      "plain": "VA granted service connection…",     // ≤2 sentences, plain English
      "missing_elements": ["nexus"],      // denials only: subset of
                                          //   ["current_disability","in_service_event","nexus"]
      "next_step": "supplemental_claim"   // denied→supplemental_claim; deferred→awaiting;
                                          //   granted→null (or increase_or_effective_date)
    }
  ],
  "combined_check": {
    "va_stated": 70,        // parsed from the letter, or null
    "computed": 70,         // our §4.25 recompute from granted percents, or null
    "matches": true,        // null when either side is unknown
    "note": "Educational cross-check…"    // always present; explains mismatch causes
  },
  "appeal_window": {
    "deadline": "2020-03-14",   // decision_date + 1 year, or null
    "days_remaining": 42,       // signed int (negative = past), or null
    "expired": false            // or null
  },
  "options": [                  // AMA lanes, grounded in the KB decision-review card
    { "key": "supplemental_claim", "title": "Supplemental Claim (VA Form 20-0995)",
      "form": "20-0995", "when": "You have NEW and relevant evidence.",
      "detail": "…", "source": "…" },
    { "key": "higher_level_review", "form": "20-0996", … },
    { "key": "board_appeal", "form": "10182", … }
  ],
  "has_denials": true,
  "has_grants": true,
  "vso_referral": "For free help appealing, a VA-accredited VSO…",  // legal-lane string
  "disclaimer": "Our plain-language reading — read the letter itself and talk to a VSO. …",
  "source_note": "Decoded from the text of your uploaded letter. VA's official …"
}
```

Notes:
- `plain` / `reasons` come from the LLM but are grounded: the decoder never asserts
  a percent/DC/date the extraction didn't surface.
- `options` is ALWAYS the three AMA lanes (educational), regardless of grants/denials,
  but the UI leads with supplemental_claim when `has_denials`.
- All strings are safe to render as text (no HTML).

## Frontend — Agent B owns these files ONLY

- `src/pages/Decode.tsx` (new) — the decoder surface, `data-section="insight"`.
- `src/lib/api.ts` — ADD a `decoderApi` block (decodable/decode/getDecode). Do not touch other blocks.
- `src/types.ts` — ADD `DecodeResult` + sub-types. Additive only.
- `src/App.tsx` — ADD `<Route path="decode" …>`. Additive only.
- `src/components/Shell.tsx` — ADD a "Decision decoder" nav item to the `insight` group. Additive only.
- `src/pages/Documents.tsx` — ADD a "Decode this decision" link on VA-decision cards → `/decode?doc=<id>`. Minimal, additive.
- `src/pages/Dashboard.tsx` — OPTIONAL: a nudge when a decodable, not-yet-decoded letter exists. Skip if risky.

Frontend must degrade: if the endpoints 404 (older backend), the nav item + page still
render, page shows a graceful "not available yet" empty state.

## Section / hue
Decoder = `insight` section (analysis tool). Decision hues: granted=emerald,
denied=rose, deferred=amber. Deadline urgency badge: >90d emerald, 30-90d amber,
<30d/expired rose.

## Tests — Agent A owns `backend/tests/test_decoder.py` ONLY
Pure-unit the deadline math (incl. leap year), the combined cross-check (match +
mismatch + unknown), the validators (drops off-contract), and the analyze assembler.
Endpoint tests mount the documents router with auth overridden; the LLM decode pass
is monkeypatched (no network). No live Postgres, no network.
