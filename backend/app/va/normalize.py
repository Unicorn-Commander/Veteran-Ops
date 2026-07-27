"""PURE normalizers for VA Lighthouse responses + the diff-style suggestion
builder. No I/O, no LLM — everything here is deterministic and unit-testable.

Response shapes verified 2026-07 against the live sandbox OpenAPI specs:
  Service History & Eligibility v2 (/services/veteran_verification/v2):
    /service_history  → {"data":[{id,type,attributes:{branch_of_service,
                         start_date, end_date, discharge_status, pay_grade,
                         separation_reason, service_type, deployments[], ...}}]}
    /disability_rating→ {"data":{id,type,attributes:{combined_disability_rating,
                         combined_effective_date, legal_effective_date,
                         individual_ratings:[{decision, rating_percentage,
                         diagnostic_type_code, diagnostic_type_name,
                         diagnostic_text, effective_date, rating_end_date,
                         static_ind}]}}}
    /permanent_and_total_disability → {"data":{permanent_and_total:
                         {service_connected_status, pension_award_status},
                         total_disability:{status, effective_date}}}
    /status           → {"data":{...attributes:{veteran_status: "confirmed"|
                         "not confirmed", ...}}}
  Benefits Claims v1 (/services/claims/v1):
    /claims           → {"data":[{id,type:"evss_claims",attributes:{status,
                         date_filed, open, documents_needed,
                         development_letter_sent, decision_letter_sent,
                         claim_type, requested_decision, ...}}]}

Everything is tolerant: missing keys become None/[]; unknown values pass
through as-is (never invented, never guessed).

The suggestion builder produces a PREVIEW ONLY. Nothing it returns is applied
until the veteran explicitly confirms via POST /va/apply — same contract as the
document-intake pipeline's suggested_links.
"""

from __future__ import annotations

from typing import Any

# VA.gov's 5-step claim status → the step number the UI can render as a phase.
CLAIM_PHASES = {
    "claim received": 1,
    "initial review": 2,
    "evidence gathering, review, and decision": 3,
    "preparation for notification": 4,
    "complete": 5,
}


def _attrs(obj: Any) -> dict:
    """JSON:API tolerance: unwrap {..., "attributes": {...}} or pass a plain
    dict through."""
    if not isinstance(obj, dict):
        return {}
    attrs = obj.get("attributes")
    return attrs if isinstance(attrs, dict) else obj


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# ── Service History & Eligibility ────────────────────────────────────────────

def normalize_service_history(raw: dict) -> list[dict]:
    """Lighthouse episodes → the app's veteran_profiles.service_periods shape
    ({branch, component, start_date, end_date, discharge_character}) plus
    read-only extras the UI can show."""
    periods: list[dict] = []
    data = raw.get("data") if isinstance(raw, dict) else None
    for episode in data or []:
        a = _attrs(episode)
        periods.append(
            {
                "branch": _clean(a.get("branch_of_service")) or "",
                "component": _clean(a.get("component_of_service"))
                or _clean(a.get("service_type"))
                or "",
                "start_date": _clean(a.get("start_date")),
                "end_date": _clean(a.get("end_date")),
                "discharge_character": _clean(a.get("discharge_status")) or "",
                "pay_grade": _clean(a.get("pay_grade")),
                "separation_reason": _clean(a.get("separation_reason")),
                "deployments": [
                    {
                        "start_date": _clean(_attrs(d).get("start_date")),
                        "end_date": _clean(_attrs(d).get("end_date")),
                        "location": _clean(_attrs(d).get("location")),
                    }
                    for d in a.get("deployments") or []
                ],
            }
        )
    return periods


def normalize_disability_rating(raw: dict) -> dict:
    """→ {combined, combined_effective_date, legal_effective_date,
         ratings: [{name, diagnostic_code, percent, effective_date,
                    rating_end_date, decision, static}]}"""
    a = _attrs(raw.get("data") if isinstance(raw, dict) else None)
    ratings: list[dict] = []
    for r in a.get("individual_ratings") or []:
        ra = _attrs(r)
        ratings.append(
            {
                "name": _clean(ra.get("diagnostic_text"))
                or _clean(ra.get("diagnostic_type_name")),
                "diagnostic_code": _clean(ra.get("diagnostic_type_code")),
                "percent": ra.get("rating_percentage"),
                "effective_date": _clean(ra.get("effective_date")),
                "rating_end_date": _clean(ra.get("rating_end_date")),
                "decision": _clean(ra.get("decision")),
                "static": ra.get("static_ind"),
            }
        )
    return {
        "combined": a.get("combined_disability_rating"),
        "combined_effective_date": _clean(a.get("combined_effective_date")),
        "legal_effective_date": _clean(a.get("legal_effective_date")),
        "ratings": ratings,
    }


def normalize_pt(raw: dict) -> dict:
    """→ {permanent_and_total: bool|None, pension_award: bool|None,
         total_disability: bool|None, total_disability_effective_date}"""
    d = raw.get("data") if isinstance(raw, dict) else None
    d = d if isinstance(d, dict) else {}
    pt = _attrs(d.get("permanent_and_total"))
    td = _attrs(d.get("total_disability"))
    return {
        "permanent_and_total": pt.get("service_connected_status"),
        "pension_award": pt.get("pension_award_status"),
        "total_disability": td.get("status"),
        "total_disability_effective_date": _clean(td.get("effective_date")),
    }


def normalize_veteran_status(raw: dict) -> str | None:
    a = _attrs(raw.get("data") if isinstance(raw, dict) else None)
    return _clean(a.get("veteran_status"))


# ── Benefits Claims ──────────────────────────────────────────────────────────

def normalize_claim(item: dict) -> dict:
    """One claim (list or detail item) → the app's stable shape."""
    a = _attrs(item)
    status = _clean(a.get("status"))
    events = []
    for ev in a.get("events_timeline") or []:
        ea = _attrs(ev)
        events.append(
            {
                "type": _clean(ea.get("type")),
                "date": _clean(ea.get("date")),
                # phase-transition entries carry these; plain events don't.
                "phase": ea.get("phase"),
                "filename": _clean(ea.get("filename")),
            }
        )
    return {
        "id": str(item.get("id")) if isinstance(item, dict) and item.get("id") else None,
        "status": status,
        "phase": CLAIM_PHASES.get((status or "").lower()),
        "claim_type": _clean(a.get("claim_type")),
        "date_filed": _clean(a.get("date_filed")),
        "min_est_date": _clean(a.get("min_est_date")),
        "max_est_date": _clean(a.get("max_est_date")),
        "open": a.get("open"),
        "documents_needed": a.get("documents_needed"),
        "development_letter_sent": a.get("development_letter_sent"),
        "decision_letter_sent": a.get("decision_letter_sent"),
        "requested_decision": a.get("requested_decision"),
        "events": events,
    }


def normalize_claims(raw: dict) -> list[dict]:
    data = raw.get("data") if isinstance(raw, dict) else None
    return [normalize_claim(item) for item in data or []]


def normalize_itf(raw: dict) -> dict:
    """Intent to File (form 0966) → {id, type, status, creation_date,
    expiration_date}."""
    d = raw.get("data") if isinstance(raw, dict) else None
    d = d if isinstance(d, dict) else {}
    a = _attrs(d)
    return {
        "id": str(d.get("id")) if d.get("id") else None,
        "type": _clean(a.get("type")),
        "status": _clean(a.get("status")),
        "creation_date": _clean(a.get("creation_date")),
        "expiration_date": _clean(a.get("expiration_date")),
    }


# ── Diff-style suggestions (preview only — the veteran confirms) ─────────────

def _match_condition(rating: dict, conditions: list[dict]) -> dict | None:
    """Deterministic match of a VA individual rating to one of the veteran's
    claimed conditions: exact diagnostic-code match first, then the same
    casefold-substring rule the document pipeline uses. Never fuzzy-guesses
    beyond that."""
    dc = (rating.get("diagnostic_code") or "").strip()
    if dc:
        for cond in conditions:
            if (cond.get("diagnostic_code") or "").strip() == dc:
                return cond
    name = (rating.get("name") or "").strip().casefold()
    if not name:
        return None
    for cond in conditions:
        c_name = (cond.get("name") or "").strip().casefold()
        if c_name and (name in c_name or c_name in name):
            return cond
    return None


def build_suggestions(
    *,
    service_periods: list[dict],
    rating: dict,
    profile: dict | None,
    conditions: list[dict],
) -> dict:
    """→ {profile_updates: {...}, condition_updates: [...]} — a PREVIEW.

    profile_updates: proposed service_periods import (when the profile has none
    or they differ) + current_combined_rating change.
    condition_updates: per VA individual rating, either
      {action: "update_rating", condition_id, ...} when it matches a claimed
      condition whose current_rating differs, or
      {action: "create", condition_id: null, ...} for a service-connected
      rating the veteran hasn't tracked here yet (claim_type=increase on
      apply — it is already rated, so any new claim would be for an increase).
    NOTHING here mutates state; POST /va/apply applies only what the veteran
    picks, and only values present in this synced snapshot.
    """
    profile = profile or {}
    profile_updates: dict = {}

    existing_periods = profile.get("service_periods") or []
    if service_periods:
        va_keys = {
            (p.get("branch"), p.get("start_date"), p.get("end_date"))
            for p in service_periods
        }
        have_keys = {
            (p.get("branch"), p.get("start_date"), p.get("end_date"))
            for p in existing_periods
            if isinstance(p, dict)
        }
        if va_keys != have_keys:
            profile_updates["service_periods"] = service_periods

    combined = rating.get("combined")
    if combined is not None and combined != profile.get("current_combined_rating"):
        profile_updates["current_combined_rating"] = {
            "from": profile.get("current_combined_rating"),
            "to": combined,
        }

    condition_updates: list[dict] = []
    for r in rating.get("ratings") or []:
        percent = r.get("percent")
        if percent is None:
            continue
        base = {
            "name": r.get("name"),
            "diagnostic_code": r.get("diagnostic_code"),
            "percent": percent,
            "effective_date": r.get("effective_date"),
        }
        matched = _match_condition(r, conditions)
        if matched is not None:
            if matched.get("current_rating") != percent:
                condition_updates.append(
                    {
                        "action": "update_rating",
                        "condition_id": str(matched["id"]),
                        "condition_name": matched.get("name"),
                        "current_rating": matched.get("current_rating"),
                        **base,
                    }
                )
        else:
            condition_updates.append(
                {"action": "create", "condition_id": None, **base}
            )
    return {"profile_updates": profile_updates, "condition_updates": condition_updates}
