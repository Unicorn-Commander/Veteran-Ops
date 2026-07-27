"""VA rating-strategy intelligence — the regulatory reasoning the Game Plan needs
so it never hands a veteran advice that would *pyramid*, invite a *reduction*, or
miss *TDIU*.

Pure functions (no DB, no network), grounded in the regs the KB already cites:
  • §4.14 + Esteban v. Brown — the same manifestation can't be paid under two codes.
  • §4.130 — ALL mental-health diagnoses carry ONE combined rating, not stacked.
  • §4.16(a)/(b) — TDIU (100% pay below a 100% rating) and its schedular thresholds.
  • §3.344 / §3.951 / §3.957 — when an existing rating is protected vs reducible
    (the "poking the bear" risk of reopening a settled record).

EDUCATIONAL only. Every output is framed as something to CONSIDER and take to a
VSO — never "you don't qualify", never "you will be reduced", never a bar on
filing. The veteran always decides; this surfaces the trade-offs VA case law makes
real so the decision is informed.
"""

from __future__ import annotations

import re

# ── name normalization (mirrors va/reconcile._norm so matching is consistent) ──
_HISTORY_RE = re.compile(r"^\s*history of\s+", re.IGNORECASE)
_CLAIMED_AS_RE = re.compile(r"\s*\(claimed as[^)]*\)\s*$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _norm(name: str | None) -> str:
    n = (name or "").lower().strip()
    n = _CLAIMED_AS_RE.sub("", n)
    n = _HISTORY_RE.sub("", n)
    return _WS_RE.sub(" ", n).strip()


def _is_granted(c: dict) -> bool:
    return (c.get("va_status") or "unknown") == "service_connected"


def is_already_granted(c: dict) -> bool:
    """A condition VA has already service-connected, on a claim type that would
    RE-file it (direct/secondary/presumptive) rather than seek more. Such a
    condition should never appear as 'ready to file' — it is already granted.
    An `increase` claim on a granted condition is legitimate (and handled with a
    reduction caution), so it is NOT treated as already-granted here."""
    return _is_granted(c) and (c.get("claim_type") or "direct") != "increase"


# ── §4.14 / §4.130 overlap groups ─────────────────────────────────────────────
# Conservative, reg-grounded groups of conditions whose symptom pictures overlap
# so heavily that VA generally will not pay them under separate diagnostic codes.
# Matching is by normalized-name keyword OR diagnostic code. `ceiling` is the
# schedular max for the group's dominant code, used only to explain which member
# reaches higher — never to predict a rating.
_OVERLAP_GROUPS: tuple[dict, ...] = (
    # NOTE: CFS (DC 6354, §4.88b) and fibromyalgia (DC 5025, §4.71a) were REMOVED
    # from these pyramiding groups. They are different diagnostic codes in different
    # body systems and CAN be rated separately when distinct manifestations support
    # each — §4.14 bars only double-counting the SAME symptom, not the two diagnoses
    # (Esteban; BVA A22005355 granted both). Treating them as pyramiding was a false
    # positive that discouraged a separately compensable claim. The pairing now lives
    # in _SEPARATE_RATING_HINTS as an UNDER-RATING opportunity. Do not re-add here.
    {
        "key": "mental_health",
        "label": "mental-health conditions (one combined rating)",
        "reg": "38 CFR §4.130; §4.14",
        "keywords": (
            "ptsd", "post-traumatic", "anxiety", "depression", "depressive",
            "adjustment disorder", "mood disorder", "bipolar", "mdd",
            "mental health", "panic", "ocd", "insomnia disorder",
        ),
        "codes": ("9411", "9413", "9434", "9435", "9440"),
        "note": (
            "Under §4.130 the VA generally assigns ONE combined rating for ALL "
            "service-connected mental-health conditions together, no matter how many "
            "diagnoses are listed — PTSD, anxiety, and depression are usually rated as a "
            "single psychiatric disability, not stacked. Filing each separately usually "
            "does not raise the rating; what matters is the overall occupational and "
            "social impairment. (Narrow exception: where competent medical evidence "
            "clearly separates non-overlapping symptomatology, separate ratings can be "
            "possible — Amberman v. Shinseki, 570 F.3d 1377.) List them together as one "
            "claim, and a VSO can help frame it."
        ),
    },
)


def _matches_group(c: dict, group: dict) -> bool:
    name = _norm(c.get("name"))
    if any(kw in name for kw in group["keywords"]):
        return True
    dc = (c.get("diagnostic_code") or "").strip()
    return bool(dc) and dc in group["codes"]


def find_pyramiding_cautions(conditions: list[dict]) -> list[dict]:
    """Surface §4.14 / §4.130 overlaps: when two or more of the veteran's
    conditions fall in the same group, warn (educationally) that VA generally
    won't pay them twice. Highest urgency when a lower-ceiling member is being
    pursued while a group-mate is already granted."""
    cautions: list[dict] = []
    for group in _OVERLAP_GROUPS:
        members = [c for c in conditions if _matches_group(c, group)]
        if len(members) < 2:
            continue
        names = [m.get("name") or "" for m in members]
        granted = [m for m in members if _is_granted(m)]
        pursuing = [
            m for m in members
            if not _is_granted(m) and (m.get("status") not in ("filed", "decided"))
        ]
        # Only worth a caution if the veteran is (or could be) pursuing more than
        # what's already granted — otherwise it's just informational overlap.
        if granted and not pursuing:
            continue
        cautions.append({
            "key": f"pyramiding:{group['key']}",
            "kind": "pyramiding",
            "title": f"These may overlap: {', '.join(names)}",
            "body": group["note"],
            "reg": group["reg"],
            "conditions": names,
            "severity": "high" if granted and pursuing else "medium",
        })
    return cautions


def find_reduction_cautions(conditions: list[dict]) -> list[dict]:
    """The "poking the bear" caution: opening a claim — especially an increase or
    a reopening of a settled condition — invites VA to re-examine the record, and
    a rating not yet protected can be reduced if VA finds improvement. Emitted once
    (not per-condition) when the veteran holds or is pursuing an increase on a
    service-connected rating. Reg-accurate, never a prediction of reduction."""
    granted = [c for c in conditions if _is_granted(c)]
    increases = [c for c in conditions if (c.get("claim_type") or "") == "increase"]
    if not granted and not increases:
        return []
    return [{
        "key": "reduction_risk",
        "kind": "reduction",
        "title": "Filing can open your existing ratings to review",
        "body": (
            "When you file a new claim or ask for an increase, the VA can re-examine "
            "conditions you're already rated for. Ratings you've held for 20 years or "
            "more are protected from reduction except for fraud (§3.951), and service "
            "connection itself is protected after 10 years (§3.957). Newer ratings can "
            "be reduced if the VA finds sustained improvement (§3.344). This doesn't "
            "mean filing is a bad idea — most veterans have far more to gain — but it's "
            "worth weighing the upside of a new claim against the chance of a review, "
            "especially for a condition that has improved. A VSO can assess your "
            "specific exposure before you file."
        ),
        "reg": "38 CFR §3.344; §3.951; §3.957",
        "conditions": [c.get("name") or "" for c in granted],
        "severity": "medium",
    }]


def find_filing_tradeoff_cautions(conditions: list[dict]) -> list[dict]:
    """CFS vs fibromyalgia "poking the bear" coaching — NOT a pyramiding ban.

    When both CFS (6354) and fibromyalgia (5025) appear in the record, surface a
    trade-off: they CAN be separate when manifestations are distinct, but filing
    both (or reopening one while the other is granted) invites VA to re-examine
    the symptom picture. Educational only.
    """
    cfs = [
        c for c in conditions
        if _matches_any(c, ("chronic fatigue", "cfs", "myalgic encephalomyelitis", "me/cfs"), ("6354",))
    ]
    fibro = [
        c for c in conditions
        if _matches_any(c, ("fibromyalgia",), ("5025",))
    ]
    if not cfs or not fibro:
        return []
    names = (
        [c.get("name") or "CFS" for c in cfs]
        + [c.get("name") or "fibromyalgia" for c in fibro]
    )
    granted_either = any(_is_granted(c) for c in cfs + fibro)
    return [{
        "key": "filing_tradeoff:cfs_fibro",
        "kind": "filing_tradeoff",
        "title": "CFS and fibromyalgia: distinct ratings need distinct symptoms",
        "body": (
            "Chronic Fatigue Syndrome (DC 6354) and fibromyalgia (DC 5025) live in "
            "different body systems and can be rated separately when DISTINCT "
            "manifestations support each (post-exertional fatigue for CFS versus "
            "widespread tender-point pain for fibromyalgia). §4.14 only bars "
            "double-counting the SAME symptom. "
            + (
                "Because one is already service-connected, filing the other (or asking "
                "for an increase that reopens the record) can invite VA to re-examine "
                "how symptoms were sorted — protect the granted rating by keeping the "
                "symptom sets clearly separate in medical evidence. "
                if granted_either else
                "If you pursue both, bring medical evidence that separates the two "
                "pictures rather than treating them as one syndrome under two labels. "
            )
            + "A VSO can help frame this before you file."
        ),
        "reg": "38 CFR §4.14; §4.88b (DC 6354); §4.71a (DC 5025); Esteban v. Brown",
        "conditions": names,
        "severity": "high" if granted_either else "medium",
    }]


def find_tdiu_employment_caution(
    conditions: list[dict],
    tdiu: dict | None,
) -> list[dict]:
    """When TDIU is on the table, surface substantially-gainful-employment risk —
    side gigs, intermittent work, and federal/EEO framing. Educational only;
    never tells the veteran to stop working."""
    if not tdiu:
        return []
    granted_names = [c.get("name") or "" for c in conditions if _is_granted(c)]
    door = bool(tdiu.get("eligible_schedular"))
    return [{
        "key": "tdiu_employment",
        "kind": "tdiu_employment",
        "title": "TDIU turns on work history — side gigs and intermittent work matter",
        "body": (
            "TDIU pays at the 100% rate when service-connected disabilities keep you "
            "from substantially gainful employment (§4.16). VA looks hard at work "
            "history: why jobs ended, gaps, part-time or gig work, and whether any "
            "income is above the poverty threshold for marginal employment. "
            "Intermittent side gigs, federal employment (including intermittent or "
            "light-duty arrangements), and EEO/accommodation records can help OR "
            "hurt depending on how they are documented — they are facts to organize, "
            "not reasons to hide work. Build a clear work chronology (VA Form 21-8940 "
            "and employer statements 21-4192), and have a VSO review side income "
            "before you file. This is education about what VA weighs — never advice "
            "to quit a job or refuse work."
            + (
                " Your ratings already meet (or are at) the schedular door, so the "
                "employment record is the main remaining pillar."
                if door else
                " Your ratings are near the schedular threshold; extraschedular "
                "TDIU (§4.16(b)) still turns on the same employment story."
            )
        ),
        "reg": "38 CFR §4.16; VA Form 21-8940 / 21-4192",
        "conditions": granted_names,
        "severity": "high" if door else "medium",
    }]


def cautions_for(
    conditions: list[dict],
    tdiu: dict | None = None,
) -> list[dict]:
    """All rating-strategy cautions (poking the bear), highest severity first."""
    out = (
        find_pyramiding_cautions(conditions)
        + find_reduction_cautions(conditions)
        + find_filing_tradeoff_cautions(conditions)
        + find_tdiu_employment_caution(conditions, tdiu)
    )
    out.sort(key=lambda c: 0 if c["severity"] == "high" else 1)
    return out


# ── §4.16 TDIU screen ──────────────────────────────────────────────────────────
def screen_tdiu(conditions: list[dict], current_combined: int | None) -> dict | None:
    """Screen for Total Disability based on Individual Unemployability (§4.16) —
    100% pay without a 100% schedular rating when service-connected disabilities
    prevent substantially gainful employment.

    Returns an educational screen (never an eligibility determination) when the
    veteran plausibly meets the schedular door, or when a single rating is high
    enough that TDIU is worth knowing about. None when clearly not in range —
    though extraschedular TDIU (§4.16(b)) always exists, so the note says so.
    """
    granted = [c for c in conditions if _is_granted(c)]
    ratings = sorted(
        (c["current_rating"] for c in granted if isinstance(c.get("current_rating"), int) and c["current_rating"] > 0),
        reverse=True,
    )
    highest = ratings[0] if ratings else 0
    combined = current_combined if isinstance(current_combined, int) else 0

    # §4.16(a) schedular door: one disability at 60%+, OR combined 70%+ with at
    # least one at 40%+. (The one-disability rule also groups a common etiology or
    # the bilateral factor as one — we can't compute that here, so we flag the
    # simple cases and point to a VSO for the grouping.)
    meets_single = highest >= 60
    meets_combined = combined >= 70 and highest >= 40
    door = meets_single or meets_combined

    # Below the door but within reach (combined 60–69, or a 50% single) → still
    # worth surfacing, since extraschedular TDIU and near-threshold cases are real.
    near = (not door) and (combined >= 60 or highest >= 50)
    if not door and not near:
        return None

    if meets_single:
        why = (
            f"You have a single service-connected disability rated at {highest}%, which "
            "meets the schedular threshold for TDIU under §4.16(a) (one disability at "
            "60% or more)."
        )
    elif meets_combined:
        why = (
            f"Your combined rating is {combined}% with a disability at 40% or more, which "
            "meets the schedular threshold for TDIU under §4.16(a)."
        )
    else:
        why = (
            f"Your ratings ({combined}% combined) are close to the TDIU schedular "
            "threshold, and extraschedular TDIU (§4.16(b)) can apply below it. It's "
            "worth understanding whether your case fits."
        )

    return {
        "eligible_schedular": door,
        "why": why,
        "what_it_is": (
            "TDIU pays at the 100% rate even without a 100% schedular rating, when "
            "your service-connected conditions keep you from holding down "
            "substantially gainful employment."
        ),
        "evidence": [
            "VA Form 21-8940 (your application) and 21-4192 (employer statement)",
            "Your work history — dates, jobs, why each ended or became unsustainable",
            "A vocational assessment or opinion tying your inability to work to your conditions",
            "SSDI award records, if you have them",
            "Statements from you and people who know you about how symptoms limit work",
        ],
        "note": (
            "If you applied for TDIU before and were denied, a Supplemental Claim with "
            "new evidence — a vocational opinion, updated employer statements — is the "
            "usual next step, and filing within a year of the decision keeps your "
            "effective date. A VSO or a VA-accredited representative can build the "
            "unemployability record, which is what these claims turn on."
        ),
        "reg": "38 CFR §4.16",
        "form": "VA Form 21-8940",
    }


# ── §3.310 secondary-service-connection theories ───────────────────────────────
# Recognized cause→effect relationships the VA regularly service-connects on a
# SECONDARY theory (a service-connected primary CAUSES or AGGRAVATES a second
# condition, §3.310). The value here is catching a NEW theory of entitlement for a
# condition that was denied on a DIRECT theory or never claimed — the anxiety /
# ME-CFS case. Each still requires a medical nexus opinion; we surface the theory,
# never assert the link. Keywords match normalized names OR diagnostic codes.
_SECONDARY_LINKS: tuple[dict, ...] = (
    {
        "key": "mh_secondary_to_chronic_illness",
        "primary_label": "a chronic, disabling physical illness or chronic pain",
        "primary_keywords": (
            "chronic fatigue", "cfs", "myalgic encephalomyelitis", "me/cfs",
            "fibromyalgia", "chronic pain", "chronic multisymptom", "undiagnosed illness",
            "gulf war", "migraine", "back", "lumbar", "cervical", "arthritis",
            "degenerative", "amputation", "traumatic brain", "tbi",
        ),
        "primary_codes": ("6354", "5025", "8045", "8100"),
        "effect_label": "depression or anxiety",
        "effect_keywords": (
            "depression", "depressive", "anxiety", "adjustment disorder",
            "mood disorder", "mdd", "mental health",
        ),
        "effect_codes": ("9434", "9435", "9413", "9440"),
        "theory": (
            "Living with a chronic, disabling physical condition and ongoing pain is a "
            "well-recognized cause of secondary depression and anxiety (§3.310). Even if "
            "a mental-health claim was denied on a direct basis, secondary service "
            "connection is a DIFFERENT theory of entitlement — a new theory can support "
            "a Supplemental Claim. It turns on a medical opinion linking the mental-health "
            "condition to the service-connected physical one."
        ),
    },
    {
        "key": "osa_secondary_to_mh",
        "primary_label": "a service-connected mental-health condition (e.g. PTSD)",
        "primary_keywords": ("ptsd", "post-traumatic", "depression", "anxiety", "mental health"),
        "primary_codes": ("9411", "9434", "9435", "9413", "9440"),
        "effect_label": "sleep apnea",
        "effect_keywords": ("sleep apnea", "osa", "obstructive sleep"),
        "effect_codes": ("6847",),
        "theory": (
            "Sleep apnea is frequently claimed as secondary to a service-connected "
            "mental-health condition (and to weight gain from its medications) under "
            "§3.310. A sleep study plus a medical nexus opinion are what these claims "
            "turn on."
        ),
    },
    {
        "key": "gerd_secondary_to_pain_meds",
        "primary_label": "a service-connected musculoskeletal or pain condition treated with NSAIDs",
        "primary_keywords": (
            "arthritis", "back", "lumbar", "cervical", "knee", "joint",
            "fibromyalgia", "chronic pain", "degenerative",
        ),
        "primary_codes": ("5025", "5003"),
        "effect_label": "GERD or a gastrointestinal condition",
        "effect_keywords": ("gerd", "reflux", "gastroesophageal", "gastritis"),
        "effect_codes": ("7346",),
        "theory": (
            "GERD is commonly claimed as secondary to the long-term NSAID / pain-"
            "medication use required by a service-connected orthopedic or pain condition "
            "(§3.310). A medical opinion connecting the medication use to the reflux is "
            "the key evidence."
        ),
    },
    {
        "key": "radiculopathy_secondary_to_spine",
        "primary_label": "a service-connected spine condition",
        "primary_keywords": ("back", "lumbar", "cervical", "spine", "spondylosis", "disc"),
        "primary_codes": ("5237", "5238", "5239", "5242", "5243"),
        "effect_label": "radiculopathy or nerve pain in a limb",
        "effect_keywords": ("radiculopathy", "sciatica", "nerve", "numbness", "neuropathy"),
        "effect_codes": ("8520", "8620", "8720"),
        "theory": (
            "Radiating nerve pain, numbness, or weakness in a leg or arm is separately "
            "compensable as a neurologic abnormality associated with a service-connected "
            "spine condition (§4.71a, General Rating Formula Note 1; §3.310) — it is rated "
            "IN ADDITION to the spine, not folded into it."
        ),
    },
    {
        "key": "hypertension_secondary_to_mh",
        "primary_label": "a service-connected mental-health condition (e.g. PTSD)",
        "primary_keywords": ("ptsd", "post-traumatic", "anxiety", "depression", "mental health"),
        "primary_codes": ("9411", "9434", "9435", "9413", "9440"),
        "effect_label": "hypertension",
        "effect_keywords": ("hypertension", "high blood pressure", "htn"),
        "effect_codes": ("7101",),
        "theory": (
            "Hypertension is a recognized secondary theory to a service-connected "
            "mental-health condition — chronic hyperarousal and sympathetic activation are "
            "associated with elevated blood pressure (a large VA study of OEF/OIF veterans; "
            "§3.310). A medical opinion addressing causation OR aggravation is the key evidence."
        ),
    },
    {
        "key": "ed_secondary_to_diabetes_or_mh",
        "primary_label": "service-connected diabetes, a prostate condition, or a mental-health condition on medication",
        "primary_keywords": (
            "diabetes", "diabetic", "prostate", "ptsd", "post-traumatic", "depression", "anxiety",
        ),
        "primary_codes": ("7913", "7527", "7528", "9411", "9434"),
        "effect_label": "erectile dysfunction",
        "effect_keywords": ("erectile", "erectile dysfunction", "impotence"),
        "effect_codes": ("7522",),
        "theory": (
            "Erectile dysfunction is a recognized secondary to diabetes (vascular/neurologic), "
            "to prostate conditions and their treatment, and to SSRI/SNRI medication for a "
            "psychiatric condition (§3.310). Even at 0% (DC 7522) it opens Special Monthly "
            "Compensation (SMC-K) — a separate fixed payment often overlooked. A nexus opinion "
            "tying the ED to the service-connected condition is the key evidence."
        ),
    },
    {
        "key": "gerd_secondary_to_mh_meds",
        "primary_label": "a service-connected mental-health condition treated with SSRIs",
        "primary_keywords": ("ptsd", "post-traumatic", "anxiety", "depression", "mental health"),
        "primary_codes": ("9411", "9434", "9435", "9413", "9440"),
        "effect_label": "GERD",
        "effect_keywords": ("gerd", "reflux", "gastroesophageal", "gastritis"),
        "effect_codes": ("7346",),
        "theory": (
            "GERD is a recognized secondary to a service-connected mental-health condition — "
            "the chronic stress response and SSRI/SNRI medications (which reduce lower-"
            "esophageal-sphincter tone) are associated with reflux, most defensibly on an "
            "AGGRAVATION theory (§3.310). A medical opinion addressing the medication/stress "
            "link is the key evidence."
        ),
    },
)


def _matches_any(c: dict, keywords: tuple, codes: tuple) -> bool:
    name = _norm(c.get("name"))
    if any(kw in name for kw in keywords):
        return True
    dc = (c.get("diagnostic_code") or "").strip()
    return bool(dc) and dc in codes


def find_secondary_opportunities(conditions: list[dict]) -> list[dict]:
    """Catch newly-establishable SECONDARY theories: a service-connected primary +
    a second condition (ideally denied or unclaimed) the VA recognizes as secondary
    to it. Emits an educational opportunity, never an assertion of the link."""
    opps: list[dict] = []
    for link in _SECONDARY_LINKS:
        primaries = [
            c for c in conditions
            if _is_granted(c) and _matches_any(c, link["primary_keywords"], link["primary_codes"])
        ]
        if not primaries:
            continue
        for eff in conditions:
            if not _matches_any(eff, link["effect_keywords"], link["effect_codes"]):
                continue
            # Skip if the effect is already granted, or already claimed AS secondary
            # to this primary (nothing new to surface).
            if _is_granted(eff):
                continue
            if (eff.get("claim_type") or "") == "secondary" and eff.get("secondary_to"):
                continue
            primary_names = [p.get("name") or "" for p in primaries]
            eff_name = eff.get("name") or link["effect_label"]
            denied = (eff.get("va_status") or "") == "denied"
            # Denied on a prior (usually direct) basis + new secondary theory =
            # first-class RECLAIM card: supplemental path + attach checklist.
            if denied:
                opps.append({
                    "key": f"reclaim:secondary:{link['key']}:{_norm(eff_name)}",
                    "kind": "reclaim",
                    "title": (
                        f"Reclaim {eff_name} on a new secondary basis "
                        f"(to {primary_names[0]})"
                    ),
                    "body": link["theory"] + (
                        " Because this was denied before, a secondary theory is a NEW "
                        "theory of entitlement — typically a Supplemental Claim "
                        "(VA Form 20-0995) with new and relevant evidence, especially "
                        "a medical nexus opinion linking the condition to your "
                        f"service-connected {primary_names[0]}. Digitized service "
                        "treatment records, new treatment notes, and a provider brief "
                        "can all count as new evidence. This is a path to explore with "
                        "a VSO — not a prediction of a grant."
                    ),
                    "reg": "38 CFR §3.310; 38 U.S.C. §5108; VA Form 20-0995",
                    "primary": primary_names,
                    "secondary": eff_name,
                    "needs_nexus": True,
                    "severity": "high",
                    "pathway": "supplemental",
                    "form": "VA Form 20-0995",
                    "attach_checklist": [
                        f"Medical nexus opinion: {eff_name} secondary to "
                        f"{primary_names[0]} (§3.310; “at least as likely as not”)",
                        "Current diagnosis / treatment notes for the denied condition",
                        "Evidence of the service-connected primary (rating decision "
                        "or treatment for the granted condition)",
                        "Any newly digitized STRs or private records not in the prior "
                        "file (new and relevant under §5108)",
                        "Optional: buddy/lay statements on observable change since the "
                        "primary worsened",
                    ],
                })
            else:
                opps.append({
                    "key": f"secondary:{link['key']}",
                    "kind": "secondary",
                    "title": (
                        f"{eff_name} may be establishable as secondary to your "
                        f"{primary_names[0]}"
                    ),
                    "body": (
                        link["theory"]
                        + " If it isn't already on your claim, it can be added on a "
                        "secondary theory with a nexus opinion."
                    ),
                    "reg": "38 CFR §3.310",
                    "primary": primary_names,
                    "secondary": eff_name,
                    "needs_nexus": True,
                    "severity": "medium",
                    "pathway": None,
                    "form": None,
                    "attach_checklist": [],
                })
    return opps


# ── Esteban-positive under-rating finder (the inverse of pyramiding) ────────────
# Esteban v. Brown: distinct, non-overlapping symptomatology from a single disability
# CAN be rated separately. These are the well-settled separations where a veteran is
# commonly UNDER-rated because a companion element wasn't separately claimed. We
# surface the possibility for a granted condition; the veteran confirms the distinct
# symptom exists. Never a rating prediction.
_SEPARATE_RATING_HINTS: tuple[dict, ...] = (
    {
        "key": "knee_instability_and_motion",
        "match_keywords": ("knee",),
        "match_codes": ("5257", "5258", "5259", "5260", "5261", "5003"),
        "companion": "instability AND limitation of motion / arthritis",
        "reg": "38 CFR §4.14 (VAOPGCPREC 23-97, 9-98; Esteban v. Brown, 6 Vet. App. 259)",
        "note": (
            "A knee that is BOTH unstable (gives way) AND has painful limited motion or "
            "arthritis can carry TWO separate ratings — instability under DC 5257 and "
            "limitation of motion / arthritis under DC 5260/5261/5003 (VAOPGCPREC 23-97, "
            "9-98; Esteban). If you have both symptoms but only one is rated, you may be "
            "under-rated. Confirm with a VSO."
        ),
    },
    {
        "key": "scar_separate_from_condition",
        "match_keywords": ("scar", "surgery", "surgical", "post-surgical", "amputation"),
        "match_codes": ("7801", "7802", "7804", "7805"),
        "companion": "a painful, unstable, or motion-limiting scar",
        "reg": "38 CFR §4.118 (Esteban v. Brown, 6 Vet. App. 259)",
        "note": (
            "A surgical or injury scar that is painful, unstable, or limits motion is "
            "separately compensable (DC 7800–7805) IN ADDITION to the underlying "
            "condition (Esteban). Scars are often missed at rating time. If you have a "
            "painful or problematic scar, mention it."
        ),
    },
    {
        "key": "tbi_residuals_separate",
        "match_keywords": ("traumatic brain", "tbi", "head injury"),
        "match_codes": ("8045",),
        "companion": "distinct TBI residuals (migraines, a mood disorder)",
        "reg": "38 CFR §4.124a, DC 8045 (Note 1)",
        "note": (
            "Residuals of a TBI that are DISTINCT and separately diagnosable — migraine "
            "headaches (DC 8100), or a mood/mental-health disorder — are rated separately "
            "from the TBI itself (DC 8045; §4.124a) rather than folded into one number. "
            "If you have distinct residuals, they may add compensation."
        ),
    },
    {
        "key": "radiculopathy_separate_from_spine",
        "match_keywords": (
            "spine", "back", "lumbar", "lumbosacral", "cervical", "thoracic",
            "degenerative disc", "disc disease", "ivds", "intervertebral",
            "herniated disc", "spondylosis", "spinal stenosis", "neck",
        ),
        "match_codes": (
            "5235", "5236", "5237", "5238", "5239", "5240",
            "5241", "5242", "5243", "5010", "5003",
        ),
        "companion": "radiculopathy — nerve pain, numbness, or weakness radiating into a limb",
        "reg": "38 CFR §4.71a (General Rating Formula, Note 1); §4.124a",
        "note": (
            "For a service-connected back or neck condition, §4.71a (General Rating "
            "Formula, Note 1) directs the VA to rate any objective NEUROLOGIC abnormality "
            "— such as radiculopathy (nerve pain, numbness, tingling, or weakness running "
            "into an arm or leg) — SEPARATELY under §4.124a (e.g. DC 8520, sciatic nerve), "
            "IN ADDITION to the orthopedic spine rating. This is one of the most commonly "
            "missed separate ratings. If you have radiating symptoms, mention them to a VSO."
        ),
    },
    {
        "key": "diabetic_complications_separate",
        "match_keywords": ("diabetes", "diabetic", "type 2", "type ii", "type 1", "mellitus"),
        "match_codes": ("7913",),
        "companion": "diabetic complications — peripheral neuropathy in each limb, plus eye/kidney involvement",
        "reg": "38 CFR §4.119, DC 7913 (Note 1); §4.124a",
        "note": (
            "For service-connected diabetes (DC 7913), §4.119 (Note 1) allows each "
            "COMPENSABLE complication to be rated SEPARATELY — most often peripheral "
            "neuropathy, rated per affected extremity under §4.124a (e.g. DC 8520/8620/"
            "8720), plus diabetic retinopathy or nephropathy — unless a complication is "
            "already being used to support a 100% diabetes rating. Veterans are often rated "
            "for the diabetes alone. If you have neuropathy or other complications, a VSO "
            "can confirm which are separately ratable."
        ),
    },
    {
        "key": "tinnitus_separate_from_hearing_loss",
        "match_keywords": (
            "hearing loss", "hearing impairment", "acoustic trauma", "noise exposure",
        ),
        "match_codes": ("6100",),
        "companion": "tinnitus (ringing in the ears)",
        "reg": "38 CFR §4.87, DC 6260",
        "note": (
            "Tinnitus (ringing in the ears, DC 6260) is rated SEPARATELY from hearing loss "
            "(DC 6100) — a standalone 10% evaluation — and the same in-service noise "
            "exposure usually supports both. If tinnitus was never claimed alongside your "
            "granted hearing loss, it may add compensation. Mention any ringing to a VSO."
        ),
    },
    {
        "key": "wound_muscle_nerve_scar_separate",
        "match_keywords": (
            "gunshot", "shell fragment", "shrapnel", "frag wound", "fragment wound",
            "penetrating wound", "through and through", "through-and-through",
            "muscle injury", "muscle group", "blast injury", "shell frag",
        ),
        "match_codes": tuple(str(dc) for dc in range(5301, 5332)),  # §4.73 muscle DCs 5301–5331 (incl. 5330 rhabdo, 5331 compartment syndrome, added 2021)
        "companion": "distinct muscle, nerve, and scar damage from the same wound",
        "reg": "38 CFR §4.55, §4.56, §4.73 (Esteban v. Brown, 6 Vet. App. 259)",
        "note": (
            "A single penetrating wound (gunshot, shrapnel, shell fragment) can carry MORE "
            "THAN ONE rating: the muscle damage under §4.73, any associated nerve damage "
            "under §4.124a, and the scar under §4.118 can each be separately compensable "
            "when they are distinct disabilities (Esteban; §4.55, §4.56). Note that a muscle "
            "and a nerve rating for the SAME body part are combined only when they affect "
            "entirely different functions (§4.55(a)); a scar is generally its own separate "
            "rating. If a wound left you with nerve symptoms or a problematic scar on top of "
            "the muscle injury, a VSO can confirm what is separately ratable."
        ),
    },
    {
        "key": "erectile_dysfunction_smc_k",
        "match_keywords": ("erectile dysfunction", "erectile", "penile deformity"),
        "match_codes": ("7522",),
        "companion": "Special Monthly Compensation (SMC-K) on top of your ED rating",
        "reg": "38 U.S.C. 1114(k); 38 CFR §3.350(a)",
        "note": (
            "Erectile dysfunction / penile deformity (DC 7522) is rated 0%, but when it is "
            "connected to service it ALSO opens Special Monthly Compensation "
            "(SMC-K) under 38 U.S.C. 1114(k) / §3.350(a) — a separate FIXED monthly payment "
            "for loss of use of a creative organ, paid IN ADDITION to the regular rating. "
            "SMC-K is very commonly overlooked. If your granted ED is not already paying "
            "SMC-K, ask a VSO to check."
        ),
    },
    {
        "key": "cfs_and_fibromyalgia_separate",
        "match_keywords": (
            "chronic fatigue", "cfs", "myalgic encephalomyelitis", "me/cfs", "fibromyalgia",
        ),
        "match_codes": ("6354", "5025"),
        "companion": "the other of CFS (DC 6354) and fibromyalgia (DC 5025), when distinct symptoms support it",
        "reg": "38 CFR §4.14; §4.88b (DC 6354); §4.71a (DC 5025); Esteban v. Brown, 6 Vet. App. 259",
        "note": (
            "Chronic Fatigue Syndrome (DC 6354, up to 100% — an immune/infectious-system "
            "code under §4.88b) and fibromyalgia (DC 5025, up to 40% — a musculoskeletal "
            "code under §4.71a) are DIFFERENT diagnostic codes in different body systems, "
            "and can be rated SEPARATELY when DISTINCT symptoms support each — for example "
            "post-exertional fatigue for CFS versus widespread pain with tender points for "
            "fibromyalgia. §4.14 bars only counting the SAME symptom toward both, not the "
            "two diagnoses. If you have both diagnosed and only one is rated, ask a VSO "
            "whether distinct manifestations support a separate rating — you may be under-rated."
        ),
    },
)


def find_underrating_opportunities(conditions: list[dict]) -> list[dict]:
    """Esteban-positive: for a GRANTED condition, surface a companion element that
    is separately ratable and commonly missed. Educational; the veteran confirms the
    distinct symptom is present."""
    opps: list[dict] = []
    for hint in _SEPARATE_RATING_HINTS:
        matched = [
            c for c in conditions
            if _is_granted(c) and _matches_any(c, hint["match_keywords"], hint["match_codes"])
        ]
        if not matched:
            continue
        names = [c.get("name") or "" for c in matched]
        opps.append({
            "key": f"underrating:{hint['key']}",
            "kind": "underrating",
            "title": f"You may be under-rated: {hint['companion']}",
            "body": hint["note"],
            "reg": hint.get("reg", "38 CFR §4.14 (Esteban v. Brown, 6 Vet. App. 259)"),
            "primary": names,
            "secondary": hint["companion"],
            "needs_nexus": False,
            "severity": "medium",
        })
    return opps


def opportunities_for(conditions: list[dict]) -> list[dict]:
    """All 'you may be leaving compensation on the table' opportunities — secondary
    theories + Esteban-positive separate ratings — highest severity first."""
    out = find_secondary_opportunities(conditions) + find_underrating_opportunities(conditions)
    out.sort(key=lambda o: 0 if o["severity"] == "high" else 1)
    return out
