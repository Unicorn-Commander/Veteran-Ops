"""Deterministic evidence-gap analysis (38 CFR §3.303 three-element framing).

Pure functions over plain dicts — no DB, no LLM — so the rules are unit-testable
and the /conditions/{id}/gaps endpoint stays deterministic. The router layer
turns returned gaps into persisted checklist items (idempotently) and pydantic
GapItem models.

Rules per the BUILD-SPEC:
  direct      → current diagnosis, in-service event, nexus, continuity
  secondary   → current diagnosis, primary link, nexus (to the primary)
  presumptive → current diagnosis, qualifying service (from the profile)
  increase    → current-severity treatment evidence
"""

from __future__ import annotations

_SC_DIRECT = "38 CFR §3.303; Shedden v. Principi, 381 F.3d 1163 (Fed. Cir. 2004)"
_SC_SECONDARY = "38 CFR §3.310; Allen v. Brown, 7 Vet. App. 439 (1995)"
_SC_LAY = "38 CFR §3.159(a)(2); Layno v. Brown, 6 Vet. App. 465 (1994)"
_SC_INCREASE = "38 CFR §4.1–4.2 (rating on current severity)"


def _have(evidence: list[dict], *kinds: str) -> bool:
    """True when at least one evidence item of any given kind has status 'have'."""
    return any(
        (e.get("kind") in kinds) and (e.get("status") == "have") for e in evidence or []
    )


def _profile_has_qualifying_service(profile: dict | None) -> bool:
    """True when the profile has any service period or a known exposure flag.

    Exposure keys stay aligned with analysis.presumptives._EXPOSURE_KEYS so a
    POW / mustard-gas veteran is not told they lack "qualifying service" for a
    presumptive claim when the presumptive matcher already fired.
    """
    p = profile or {}
    periods = p.get("service_periods") or []
    exposures = p.get("exposures") or {}
    if not isinstance(exposures, dict):
        exposures = {}
    try:
        from .presumptives import _EXPOSURE_KEYS as _keys
        exposure_keys = _keys
    except Exception:  # noqa: BLE001 — pure fallback for isolated imports
        exposure_keys = (
            "burn_pits",
            "agent_orange",
            "gulf_war",
            "radiation",
            "camp_lejeune",
            "pow",
            "mustard_gas",
        )
    exposure_flagged = any(bool(exposures.get(k)) for k in exposure_keys)
    return bool(periods) or exposure_flagged


def analyze_gaps(
    condition: dict,
    evidence: list[dict],
    profile: dict | None = None,
    max_ratings: dict[str, dict] | None = None,
) -> list[dict]:
    """Return the evidence gaps for one condition.

    condition: {name, claim_type, secondary_to, in_service_event, nexus_notes,
               diagnostic_code, current_rating, ...}
    evidence:  [{kind, status, ...}] — only status='have' items count as satisfied.
    profile:   {service_periods, exposures, ...} (used for presumptive claims).
    max_ratings: optional kb.store.load_max_ratings() map — enables the
               at-schedular-maximum informational item on increase claims.

    Each gap: {kind, label, detail, source} — kind is an evidence_items kind so
    the UI can pre-fill a 'need' evidence row from a gap.
    """
    claim_type = (condition or {}).get("claim_type") or "direct"
    name = (condition or {}).get("name") or "this condition"
    gaps: list[dict] = []

    # Every claim path rests on a CURRENT diagnosed disability.
    if not _have(evidence, "diagnosis"):
        gaps.append(
            {
                "kind": "diagnosis",
                "label": "Current diagnosis",
                "detail": (
                    f"A claim for {name} needs a current diagnosis from a medical "
                    "provider — recent treatment records or a diagnostic evaluation. "
                    "Without element (1), the current disability, the claim cannot be granted."
                ),
                "source": _SC_DIRECT,
            }
        )

    if claim_type == "direct":
        has_event = bool((condition or {}).get("in_service_event")) or _have(
            evidence, "service_record"
        )
        if not has_event:
            gaps.append(
                {
                    "kind": "service_record",
                    "label": "In-service event, injury, or disease",
                    "detail": (
                        "Document what happened in service: service treatment records, "
                        "personnel/unit records, or a specific dated description of the "
                        "event. Credible lay statements can establish this where records "
                        "are thin."
                    ),
                    "source": _SC_DIRECT,
                }
            )
        has_nexus = bool((condition or {}).get("nexus_notes")) or _have(
            evidence, "nexus_letter", "dbq"
        )
        if not has_nexus:
            gaps.append(
                {
                    "kind": "nexus_letter",
                    "label": "Medical nexus opinion",
                    "detail": (
                        "A medical opinion linking the current condition to the in-service "
                        "event, phrased 'at least as likely as not' — typically from a "
                        "treating provider or via a completed DBQ."
                    ),
                    "source": _SC_DIRECT,
                }
            )
        if not _have(evidence, "continuity", "lay_statement", "treatment_record"):
            gaps.append(
                {
                    "kind": "continuity",
                    "label": "Continuity of symptoms since service",
                    "detail": (
                        "Evidence the symptoms have continued since service: treatment "
                        "records over time, a symptom log, or lay statements from people "
                        "who observed the symptoms (spouse, fellow service members)."
                    ),
                    "source": _SC_LAY,
                }
            )

    elif claim_type == "secondary":
        if not (condition or {}).get("secondary_to"):
            gaps.append(
                {
                    "kind": "other",
                    "label": "Link to the primary service-connected condition",
                    "detail": (
                        "A secondary claim must name the service-connected condition that "
                        "caused or aggravated this one — set the primary condition on this "
                        "claim and confirm it is (or will be) service-connected."
                    ),
                    "source": _SC_SECONDARY,
                }
            )
        has_nexus = bool((condition or {}).get("nexus_notes")) or _have(
            evidence, "nexus_letter", "dbq"
        )
        if not has_nexus:
            gaps.append(
                {
                    "kind": "nexus_letter",
                    "label": "Nexus opinion linking to the primary condition",
                    "detail": (
                        "The key evidence for a secondary claim: a medical opinion that "
                        "the primary service-connected condition 'at least as likely as "
                        "not' caused OR aggravated this condition, ideally citing medical "
                        "literature."
                    ),
                    "source": _SC_SECONDARY,
                }
            )

    elif claim_type == "presumptive":
        if not _profile_has_qualifying_service(profile):
            gaps.append(
                {
                    "kind": "service_record",
                    "label": "Qualifying service documentation",
                    "detail": (
                        "Presumptive service connection turns on WHERE and WHEN you "
                        "served (or a recognized exposure). Add your service periods and "
                        "exposures to your profile, and gather DD-214/personnel records "
                        "showing the qualifying service."
                    ),
                    "source": "38 CFR §§3.307, 3.309, 3.317, 3.320",
                }
            )

    elif claim_type == "increase":
        if not _have(evidence, "treatment_record", "dbq"):
            gaps.append(
                {
                    "kind": "treatment_record",
                    "label": "Current treatment evidence showing severity",
                    "detail": (
                        "An increase claim is decided on CURRENT severity: recent "
                        "treatment records, a current DBQ from your provider, and a "
                        "symptom log demonstrating the criteria of the higher tier."
                    ),
                    "source": _SC_INCREASE,
                }
            )
        # Informational (additive — never replaces the gaps above): the VA
        # max-ratings dataset says this diagnostic code tops out at the
        # veteran's CURRENT rating, so a schedular increase under this code
        # can't go higher. Educational pointers only — the veteran decides.
        dc = str((condition or {}).get("diagnostic_code") or "").strip()
        current = (condition or {}).get("current_rating")
        row = (max_ratings or {}).get(dc) if dc else None
        if (
            row
            and isinstance(current, int)
            and not isinstance(current, bool)
            and isinstance(row.get("max_rating"), int)
            and current >= row["max_rating"]
        ):
            issue = row.get("rated_issue_name") or "this code"
            cfr = row.get("cfr_reference") or "38 CFR Part 4"
            gaps.append(
                {
                    "kind": "other",
                    "label": "Already at the schedular maximum for this diagnostic code",
                    "detail": (
                        f"{name} is rated {current}% — the schedular maximum under "
                        f"diagnostic code {dc} ({issue}; {cfr}). An increase claim "
                        "can't go higher under this code. Veterans in this situation "
                        "often discuss two other paths with their provider or VSO: "
                        "TDIU — total disability based on individual unemployability "
                        "(38 CFR §4.16) — when service-connected conditions prevent "
                        "substantially gainful employment, and Special Monthly "
                        "Compensation (38 CFR §3.350) for specific losses or "
                        "housebound status. A different diagnostic code may also fit "
                        "if the symptoms meet another criteria set — verify at eCFR."
                    ),
                    "source": (
                        "38 CFR §4.16 (TDIU); 38 CFR §3.350 (SMC); "
                        "VA max-ratings dataset (CC0)"
                    ),
                }
            )

    return gaps


def map_dbq(
    name: str | None,
    body_system: str | None,
    catalog: list[dict],
) -> str | None:
    """Best-match DBQ form from the dbq.json catalog.

    Match by condition-name keyword overlap first (most specific wins), then by
    body_system. Pure and deterministic.
    """
    name_l = (name or "").lower()
    tokens = {t for t in name_l.replace("/", " ").replace("(", " ").replace(")", " ").split() if len(t) >= 3}

    best: tuple[int, str] | None = None
    for entry in catalog or []:
        cond = str(entry.get("condition") or "").lower()
        cond_tokens = {
            t
            for t in cond.replace("/", " ").replace("(", " ").replace(")", " ").split()
            if len(t) >= 3 and t not in {"incl", "other", "than", "and", "conditions"}
        }
        overlap = len(tokens & cond_tokens)
        # A whole-phrase hit (e.g. 'sleep apnea' in the name) is the strongest signal.
        phrase = cond.split("(")[0].strip()
        if phrase and phrase in name_l:
            overlap += 2
        if overlap > 0 and (best is None or overlap > best[0]):
            best = (overlap, str(entry.get("dbq") or ""))
    if best:
        return best[1] or None

    if body_system:
        # Prefer the body system's GENERIC entry (e.g. "Respiratory Conditions
        # DBQ") over whichever specific entry happens to come first in the
        # catalog — without this, sinusitis fell back to the Sleep Apnea DBQ.
        candidates = [e for e in catalog or [] if e.get("body_system") == body_system]
        for entry in sorted(candidates, key=lambda e: not e.get("generic")):
            return str(entry.get("dbq") or "") or None
    return None
