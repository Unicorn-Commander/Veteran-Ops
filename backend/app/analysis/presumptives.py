"""Presumptive-eligibility screen — PURE RULES, no LLM, ever.

Matches a veteran profile (service_periods + exposures) against the KB
presumptive cards' structured data. The LLM never decides membership; the
router may not alter these results, only render them.

Pure functions over plain dicts so the matcher is unit-testable without a DB.
"""

from __future__ import annotations

from datetime import date, timedelta

_EXPOSURE_KEYS = (
    "burn_pits",
    "agent_orange",
    "gulf_war",
    "radiation",
    "camp_lejeune",
    "pow",
    "mustard_gas",
)

# ALS (§3.318) is condition-gated: 90+ days of active service alone must NOT
# spam every veteran. Callers pass condition_names when the veteran has (or is
# claiming) an ALS / motor-neuron condition.
_ALS_KEYWORDS = ("als", "amyotrophic", "lou gehrig", "motor neuron")


def _parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _period_overlaps_window(
    p_start: date | None,
    p_end: date | None,
    w_from: date | None,
    w_to: date | None,
    today: date,
) -> bool:
    """Date-overlap: null window bound = open; a period missing its end date is
    treated as ongoing (through today). A period with no dates at all cannot
    match by window."""
    if p_start is None and p_end is None:
        return False
    start = p_start or p_end
    end = p_end or today
    if w_from is not None and end < w_from:
        return False
    if w_to is not None and start > w_to:
        return False
    return True


def cumulative_service_days(service_periods: list[dict] | None) -> int:
    """Total calendar days across a veteran's service periods.

    Pure function for testability — used by the ALS targeted check."""
    total = 0
    for p in service_periods or []:
        if not isinstance(p, dict):
            continue
        start = _parse_date(p.get("start_date"))
        end = _parse_date(p.get("end_date"))
        if not start:
            continue
        total += (end - start).days if end else 0
    return total


def _has_als_condition(condition_names: list[str] | None) -> bool:
    blob = " ".join(str(n or "") for n in (condition_names or [])).lower()
    if not blob.strip():
        return False
    return any(kw in blob for kw in _ALS_KEYWORDS)


def _latest_separation(service_periods: list[dict], today: date) -> date | None:
    """Most recent service end date; None when no period has an end date."""
    ends = [_parse_date(p.get("end_date")) for p in service_periods or []]
    ends = [e for e in ends if e is not None and e <= today]
    return max(ends) if ends else None


def _pow_internment_days(exposures: dict) -> int | None:
    """Optional cumulative POW internment length from profile exposures.

    None means the veteran marked POW but did not supply a duration — we only
    surface the any-period list (safer educational floor) and note that 30+ day
    conditions exist. Non-int / negative values coerce to None.
    """
    raw = exposures.get("pow_internment_days")
    if raw is None or raw == "":
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    if days < 0:
        return None
    return days


def _pow_condition_list(data: dict, internment_days: int | None) -> list[str]:
    """38 CFR §3.309(c): any-period list always; 30+ day list only when known ≥30.

    Falls back to the flat `conditions` bag when the card has no split lists
    (older fixtures / tests).
    """
    any_period = list(data.get("conditions_any_period") or [])
    thirty = list(data.get("conditions_thirty_days") or [])
    flat = list(data.get("conditions") or [])
    if not any_period and not thirty:
        return flat
    if internment_days is not None and internment_days >= 30:
        # Preserve order: any-period first, then 30-day-only entries.
        seen: set[str] = set()
        out: list[str] = []
        for name in any_period + thirty:
            key = name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(name)
        return out
    # Unknown duration or under 30 days: any-period list only.
    return any_period or flat


def match_presumptives(
    profile: dict | None,
    cards: list[dict],
    today: date | None = None,
    *,
    condition_names: list[str] | None = None,
) -> list[dict]:
    """Rule-based screen of a veteran profile against presumptive KB cards.

    profile: {service_periods: [{start_date, end_date, ...}], exposures: {...}}
    cards:   kb_card dicts with card_type='presumptive' and data =
             {program, exposure_flags, qualifying_service: [{where, from, to}],
              conditions: [...]}
    condition_names: optional claimed/considered condition names — required for
             the ALS (§3.318) program so 90+ service days alone never spam.

    Returns one match dict per matched card:
      {title, program, matched_reason, conditions, source}
    """
    today = today or date.today()
    p = profile or {}
    periods = [pp for pp in (p.get("service_periods") or []) if isinstance(pp, dict)]
    exposures = p.get("exposures") or {}
    if not isinstance(exposures, dict):
        exposures = {}
    flagged = {k for k in _EXPOSURE_KEYS if bool(exposures.get(k))}

    matches: list[dict] = []
    for card in cards or []:
        data = (card or {}).get("data") or {}
        program = str(data.get("program") or "")
        matched_reason: str | None = None
        conditions_out: list[str] | None = None

        # Special rule: chronic diseases within one year of separation.
        if program == "chronic_one_year":
            sep = _latest_separation(periods, today)
            if sep is not None and (today - sep) <= timedelta(days=365):
                matched_reason = (
                    f"Your most recent separation date ({sep.isoformat()}) is within "
                    "one year of today — chronic diseases manifesting to 10%+ in this "
                    "window are presumed service-connected."
                )
        # Special rule: ALS (§3.318) — 90+ cumulative active-service days AND an
        # ALS / motor-neuron condition signal (condition-gated to avoid spam).
        elif program == "als":
            days = cumulative_service_days(periods)
            if days >= 90 and _has_als_condition(condition_names):
                matched_reason = (
                    f"Your profile shows about {days} cumulative days of active "
                    "service and an ALS / motor-neuron condition. Under 38 CFR "
                    "§3.318, amyotrophic lateral sclerosis is presumed "
                    "service-connected for veterans with 90 or more days of active "
                    "continuous service — the claim needs the diagnosis, not a "
                    "nexus opinion. Confirm details with an accredited VSO."
                )
        # Special rule: POW (§3.309(c)) — flag_only, with internment-duration
        # branching for any-period vs 30+ day condition lists.
        elif program == "pow":
            if "pow" in flagged:
                internment = _pow_internment_days(exposures)
                conditions_out = _pow_condition_list(data, internment)
                if internment is None:
                    matched_reason = (
                        "Your profile reports former prisoner-of-war status. Under "
                        "38 CFR §3.309(c), certain conditions are presumed after any "
                        "period of internment. Add approximate internment days on your "
                        "profile to also surface the 30+ day presumptive list. Confirm "
                        "details with an accredited VSO."
                    )
                elif internment >= 30:
                    matched_reason = (
                        f"Your profile reports former POW status with about "
                        f"{internment} days of internment. Under 38 CFR §3.309(c), "
                        "both the any-period and the 30+ day presumptive lists may "
                        "apply. Confirm details with an accredited VSO."
                    )
                else:
                    matched_reason = (
                        f"Your profile reports former POW status with about "
                        f"{internment} days of internment (under 30). Under 38 CFR "
                        "§3.309(c), the any-period presumptive list may apply; the "
                        "30+ day list is not shown for this duration. Confirm details "
                        "with an accredited VSO."
                    )
        else:
            # (a) exposure-flag overlap
            card_flags = set(data.get("exposure_flags") or [])
            hit_flags = sorted(card_flags & flagged)
            if hit_flags:
                matched_reason = (
                    "Your profile reports exposure: "
                    + ", ".join(f.replace("_", " ") for f in hit_flags)
                    + "."
                )
            elif data.get("match") != "flag_only":
                # (b) service-period overlap with a qualifying window.
                # Cards marked match='flag_only' (radiation-risk activity, Camp
                # Lejeune) never match on dates alone: their windows span so
                # much of history that date overlap says nothing about the actual
                # exposure — the explicit profile flag is the only signal.
                for window in data.get("qualifying_service") or []:
                    w_from = _parse_date((window or {}).get("from"))
                    w_to = _parse_date((window or {}).get("to"))
                    for pp in periods:
                        if _period_overlaps_window(
                            _parse_date(pp.get("start_date")),
                            _parse_date(pp.get("end_date")),
                            w_from,
                            w_to,
                            today,
                        ):
                            where = str((window or {}).get("where") or "the covered area")
                            matched_reason = (
                                "A service period in your profile overlaps the "
                                f"qualifying window for: {where} "
                                f"({(w_from.isoformat() if w_from else 'open')}–"
                                f"{(w_to.isoformat() if w_to else 'present')}). "
                                "Dates alone don't confirm location — verify you "
                                "served in the covered location."
                            )
                            break
                    if matched_reason:
                        break

        if matched_reason:
            matches.append(
                {
                    "title": str(card.get("title") or ""),
                    "program": program,
                    "matched_reason": matched_reason,
                    "conditions": (
                        conditions_out
                        if conditions_out is not None
                        else list(data.get("conditions") or [])
                    ),
                    "source": str(card.get("source") or ""),
                }
            )
    return matches
