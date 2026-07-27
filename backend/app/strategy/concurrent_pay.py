"""Concurrent-pay intelligence — the CRDP / CRSC eligibility read the "Ongoing"
stage needs so a military retiree who also draws VA disability compensation can
see, in plain terms, which concurrent-receipt program likely fits them.

Two very different programs let a retiree stop *waiving* retired pay dollar-for-
dollar against VA compensation:

  • CRDP — Concurrent Retirement and Disability Pay (10 U.S.C. §1414). Restores
    the retired pay a retiree waives to receive VA compensation. For retirees
    with a VA combined rating of 50% or more. AUTOMATIC — DFAS pays it, no
    application. Taxable (it is retired pay). Full concurrent receipt since the
    phase-in ended Jan 1, 2014.

  • CRSC — Combat-Related Special Compensation (10 U.S.C. §1413a). A separate,
    TAX-FREE payment for disabilities that are combat-related (armed conflict,
    hazardous service, training that simulates war, or an instrumentality of
    war; Purple Heart). Requires an APPLICATION — DD Form 2860 — to the
    veteran's BRANCH of service, not the VA and not DFAS.

A veteran eligible for both cannot receive both at once — they ELECT the one that
pays more, with an annual open season to switch.

Pure functions (no DB, no network, NO LLM), grounded in the statutes above. This
is DETERMINISTIC like app/rating/engine.py — same inputs, same read, forever.

EDUCATIONAL only. Every output is framed as "based on what you've told us, this
program likely fits / likely doesn't" — never "you qualify", never "you will
receive". DFAS and your branch decide eligibility and the exact amount; this
organizes where you stand and what to do. The veteran always decides.
"""

from __future__ import annotations

# ── program facts (citations carried through to the UI) ──────────────────────
CRDP_STATUTE = "10 U.S.C. §1414"
CRSC_STATUTE = "10 U.S.C. §1413a"
CRSC_FORM = "DD Form 2860"

# CRDP restores waived retired pay at a 50%+ VA combined rating.
CRDP_MIN_RATING = 50
# CRSC covers combat-related disabilities the VA compensates at 10%+.
CRSC_MIN_RATING = 10


def _norm_rating(combined_rating: int | None) -> int:
    """A safe 0–100 integer for the read (VA combined ratings are multiples of 10;
    anything out of range collapses to 0 so the logic never trips)."""
    if not isinstance(combined_rating, bool) and isinstance(combined_rating, int):
        return max(0, min(100, combined_rating))
    return 0


def _crdp_read(rating: int, retired: bool, retired_known: bool) -> dict:
    """CRDP (§1414) eligibility read — restores waived retired pay at 50%+."""
    if not retired_known:
        status = "unknown"
        likely_fits = False
        headline = (
            "CRDP is only for military retirees. Tell us whether you receive military "
            "retired pay (in your profile) and we can read this for you."
        )
    elif not retired:
        status = "not_a_retiree"
        likely_fits = False
        headline = (
            "CRDP is for retirees who waive military retired pay to receive VA "
            "compensation — it doesn't apply unless you draw retired pay."
        )
    elif rating >= CRDP_MIN_RATING:
        status = "likely_eligible"
        likely_fits = True
        headline = (
            f"Based on what you've told us — retired pay and a {rating}% combined "
            "rating — CRDP likely applies to you. It is automatic; there is no "
            "application, and it is paid by DFAS, not the VA."
        )
    else:
        status = "below_rating_threshold"
        likely_fits = False
        headline = (
            f"CRDP restores waived retired pay once your VA combined rating is "
            f"{CRDP_MIN_RATING}% or more. Your current combined rating is {rating}%. "
            "Ratings can change as claims are decided — worth re-checking then."
        )
    return {
        "program": "CRDP",
        "full_name": "Concurrent Retirement and Disability Pay",
        "statute": CRDP_STATUTE,
        "who_its_for": (
            "Military retirees (20+ years, or a Chapter 61 medical retiree with 20+ "
            "years of service) who have a VA combined rating of 50% or more."
        ),
        "how_it_works": (
            "Normally you waive $1 of retired pay for every $1 of VA compensation. "
            "CRDP stops that waiver at a 50%+ rating, restoring your retired pay — you "
            "keep your full VA compensation AND your retired pay. Since the phase-in "
            "ended January 1, 2014, it is full concurrent receipt."
        ),
        "requires_application": False,
        "how_to_get_it": (
            "Automatic. When it applies, DFAS starts CRDP on your retired-pay account — "
            "there is nothing to file. Check your monthly Retiree Account Statement (RAS)."
        ),
        "taxable": True,
        "tax_note": "CRDP is taxable — it is restored retired pay.",
        "likely_fits": likely_fits,
        "status": status,
        "headline": headline,
    }


def _crsc_read(rating: int, retired: bool, retired_known: bool, combat: bool) -> dict:
    """CRSC (§1413a) eligibility read — tax-free pay for combat-related disability."""
    if not retired_known:
        status = "unknown"
        likely_fits = False
        headline = (
            "CRSC is only for military retirees. Tell us whether you receive military "
            "retired pay (in your profile) and we can read this for you."
        )
    elif not retired:
        status = "not_a_retiree"
        likely_fits = False
        headline = (
            "CRSC is for retirees who waive military retired pay to receive VA "
            "compensation — it doesn't apply unless you draw retired pay."
        )
    elif not combat:
        status = "needs_combat_related"
        likely_fits = False
        headline = (
            "CRSC only covers disabilities that are combat-related. You haven't marked "
            "any of yours as combat-related — if a disability came from armed conflict, "
            "hazardous duty, war-simulating training, or an instrumentality of war (or "
            "you hold a Purple Heart), CRSC may be worth applying for."
        )
    elif rating >= CRSC_MIN_RATING:
        status = "likely_eligible"
        likely_fits = True
        headline = (
            "Based on what you've told us — retired pay and a combat-related disability "
            "the VA compensates — CRSC likely fits. Unlike CRDP it is tax-free, and it "
            f"requires an application ({CRSC_FORM}) to your branch of service."
        )
    else:
        status = "below_rating_threshold"
        likely_fits = False
        headline = (
            f"CRSC covers combat-related disabilities the VA rates at "
            f"{CRSC_MIN_RATING}% or more. Your current combined rating is {rating}%."
        )
    return {
        "program": "CRSC",
        "full_name": "Combat-Related Special Compensation",
        "statute": CRSC_STATUTE,
        "who_its_for": (
            "Military retirees (including Chapter 61 medical retirees) with one or more "
            "combat-related disabilities the VA rates at 10% or more."
        ),
        "how_it_works": (
            "CRSC is a separate, tax-free payment that makes up for the retired pay you "
            "waive that is attributable to your COMBAT-RELATED disabilities. 'Combat-"
            "related' means the disability came from armed conflict, hazardous service, "
            "training that simulates war, or an instrumentality of war (a Purple Heart "
            "qualifies related disabilities)."
        ),
        "requires_application": True,
        "form": CRSC_FORM,
        "how_to_get_it": (
            f"Apply on {CRSC_FORM} to YOUR branch of service (Army, Navy, Air Force, "
            "Marine Corps, Coast Guard) — not the VA and not DFAS. Include the VA "
            "rating decisions and records that show each disability is combat-related."
        ),
        "taxable": False,
        "tax_note": "CRSC is tax-free.",
        "likely_fits": likely_fits,
        "status": status,
        "headline": headline,
    }


def screen_concurrent_pay(
    combined_rating: int | None,
    receives_retired_pay: bool | None,
    combat_related: bool | None,
) -> dict:
    """Deterministic CRDP (§1414) / CRSC (§1413a) eligibility read from the three
    facts the veteran gives us: their VA combined rating, whether they draw
    military retired pay, and whether any disability is combat-related.

    Returns an educational read for each program (likely_fits + a plain headline),
    plus the election point when both fit. NEVER an eligibility determination and
    NEVER a promise — DFAS and the branch decide. This is pure and side-effect-free;
    the router adds the (also deterministic) dollar estimate.
    """
    rating = _norm_rating(combined_rating)
    retired_known = receives_retired_pay is not None
    retired = bool(receives_retired_pay)
    combat = bool(combat_related)

    crdp = _crdp_read(rating, retired, retired_known)
    crsc = _crsc_read(rating, retired, retired_known, combat)

    both_fit = crdp["likely_fits"] and crsc["likely_fits"]
    election_note = (
        "You can't receive CRDP and CRSC at the same time. If both fit, you elect the "
        "one that pays you more — there's an annual open season to switch. CRSC is "
        "tax-free but only covers your combat-related disabilities; CRDP is taxable but "
        "restores your full VA waiver. Because CRSC needs an application and CRDP is "
        "automatic, applying for CRSC keeps the choice open — DFAS pays whichever is "
        "greater once both are on file."
    ) if both_fit else ""

    # Concrete next moves, tuned to what likely fits.
    what_to_do: list[str] = []
    if not retired_known:
        what_to_do.append(
            "Add whether you receive military retired pay to your profile so this read "
            "is accurate — concurrent pay only applies to military retirees."
        )
    elif not retired:
        what_to_do.append(
            "Concurrent-pay programs are for military retirees who waive retired pay. If "
            "you don't draw retired pay, neither CRDP nor CRSC applies to you today."
        )
    else:
        if crdp["likely_fits"]:
            what_to_do.append(
                "CRDP should be automatic — check your DFAS Retiree Account Statement to "
                "confirm your waived retired pay is being restored, and call DFAS if it "
                "isn't showing."
            )
        if crsc["likely_fits"]:
            what_to_do.append(
                f"Apply for CRSC on {CRSC_FORM} to your branch of service, with the VA "
                "rating decisions and records that tie each disability to combat."
            )
        elif crsc["status"] == "needs_combat_related":
            what_to_do.append(
                "If any of your disabilities are combat-related, mark that in your profile "
                f"and consider a {CRSC_FORM} application for tax-free CRSC."
            )
        if both_fit:
            what_to_do.append(
                "Compare the two amounts before you elect — a VSO or your branch's CRSC "
                "office can run both so you keep whichever pays more."
            )

    return {
        "combined_rating": rating,
        "receives_retired_pay": retired if retired_known else None,
        "retired_pay_known": retired_known,
        "combat_related": combat,
        "crdp": crdp,
        "crsc": crsc,
        "must_elect": both_fit,
        "election_note": election_note,
        "what_to_do": what_to_do,
    }


def crdp_restoration_estimate(monthly_va_waiver: float | None, crdp_fits: bool) -> dict | None:
    """A ROUGH, clearly-bounded estimate of the retired pay CRDP could restore.

    `monthly_va_waiver` is the veteran's full monthly VA compensation (single-
    veteran baseline) — the amount a retiree waives from retired pay, and the
    CEILING of what CRDP restores. The actual figure is capped at the length-of-
    service (longevity) portion of retired pay, which depends on years served and
    is DFAS's to calculate. None when we can't compute a base amount (no rating
    loaded, or a rate-year gap) — we show a gap, never a guessed number.

    Pure and deterministic: given the same waiver amount it always frames the same
    estimate. It is an estimate, not a promise — DFAS decides the amount.
    """
    if not crdp_fits or monthly_va_waiver is None or monthly_va_waiver <= 0:
        return None
    return {
        "monthly_ceiling": round(float(monthly_va_waiver), 2),
        "is_estimate": True,
        "basis": (
            "This is the full monthly VA compensation you currently waive from retired "
            "pay (single-veteran baseline; more with dependents). CRDP could restore up "
            "to about this much — but never more than the length-of-service portion of "
            "your retired pay, which DFAS calculates from your years of service. It is a "
            "rough estimate, not a promise: DFAS and your pay center decide the amount."
        ),
    }
