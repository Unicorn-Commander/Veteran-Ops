from __future__ import annotations

from ..analysis.presumptives import match_presumptives
from ..analysis.secondaries import match_secondaries
from ..kb.store import cached_max_ratings, classify_contention, load_cards, load_secondary_map
from .candidates import CandidateRating
from .context import VeteranDossier


def _normalize(text: str) -> str:
    return (text or "").casefold().strip()


# Canonical body systems, keyed to substrings that appear in EITHER the VA
# contention taxonomy ("Heart/Veins/Arteries", "Musculoskeletal - Knee") OR the
# max-ratings body_system ("The Cardiovascular System"), which use different
# vocabularies for the same system. A term is blocked from a DC only when both
# sides map to DIFFERENT known systems (Mental vs Musculoskeletal); anything
# unmappable is left unconstrained so we never drop a valid, novel match.
_CANON_SYSTEMS: dict[str, tuple[str, ...]] = {
    "mental": ("mental",),
    "cardiovascular": ("cardiovascular", "heart", "vein", "arter", "vascular"),
    "hemic": ("hemic", "lymphatic"),
    "respiratory": ("respiratory",),
    "digestive": ("digestive",),
    "genitourinary": ("genitourinary",),
    "musculoskeletal": ("musculoskeletal", "muscle"),
    "skin": ("skin", "dermat"),
    "neurological": ("neurolog", "nervous", "cranial", "peripheral nerve"),
    "endocrine": ("endocrine",),
    "eye": ("eye", "vision"),
    "ear": ("ear ", "hearing", "auditory"),
    "infectious": ("infectious", "immune", "nutritional"),
    "gynecological": ("gynecolog",),
    "dental": ("dental",),
}


def _canon_systems(text: str) -> set[str]:
    t = _normalize(text)
    return {name for name, kws in _CANON_SYSTEMS.items() if any(kw in t for kw in kws)}


def _resolve_dc(
    name: str,
    *,
    known_dc: str | None = None,
    max_ratings: dict[str, dict] | None = None,
) -> str | None:
    if known_dc:
        return known_dc
    if not name or max_ratings is None:
        return None
    name_l = _normalize(name)

    # The official VA contention taxonomy gives the correct BODY SYSTEM for
    # ambiguous lay terms, which stops the worst substring false positives:
    # "Depression" is a Mental Disorder (not DC 5302, whose muscle description
    # contains the words "depression of arm"); "Anemia" is Hemic and Lymphatic.
    # When the term classifies, only DCs in that system are eligible; if nothing
    # in-system matches we return None (unresolved) rather than a wrong code.
    cls = classify_contention(text=name)
    term_systems = _canon_systems((cls or {}).get("classification_name") or "")

    def _compatible(info: dict) -> bool:
        if not term_systems:
            return True  # term didn't map to a known system → don't constrain
        dc_systems = _canon_systems(info.get("body_system") or "")
        if not dc_systems:
            return True  # DC system unmappable → benefit of the doubt
        return bool(term_systems & dc_systems)  # block only on a known mismatch

    # Exact match wins; else the first DC whose name is a PREFIX relation of the
    # condition (the code named FOR it, e.g. "Anemia, hypochromic…" for "Anemia");
    # else the first plain substring match, preserving schedule order so a generic
    # term keeps its default code ("Anxiety Disorder" -> generalized anxiety, not a
    # specific variant that merely has a shorter name).
    prefix_hit: str | None = None
    contains_hit: str | None = None
    for dc, info in max_ratings.items():
        rin = _normalize(info.get("rated_issue_name") or "")
        if not rin or not _compatible(info):
            continue
        if rin == name_l:
            return dc
        if rin.startswith(name_l) or name_l.startswith(rin):
            prefix_hit = prefix_hit or dc
        elif name_l in rin or rin in name_l:
            contains_hit = contains_hit or dc
    return prefix_hit or contains_hit


def _title(dc: str | None, fallback: str, max_ratings: dict[str, dict]) -> str:
    if dc and dc in max_ratings:
        return max_ratings[dc].get("rated_issue_name") or fallback
    return fallback


def _body_system(dc: str | None, max_ratings: dict[str, dict]) -> str | None:
    if dc and dc in max_ratings:
        return max_ratings[dc].get("body_system") or None
    return None


def _profile_flag(profile: dict, *names: str) -> bool:
    exposures = profile.get("exposures") or {}
    return any(bool(profile.get(name)) or bool(exposures.get(name)) for name in names)


def enumerate_candidates(dossier: VeteranDossier) -> list[CandidateRating]:
    max_ratings = cached_max_ratings()
    secondary_map = load_secondary_map()
    cards = [c for c in load_cards() if c.get("card_type") == "presumptive"]

    candidates: dict[tuple[str, str, str], CandidateRating] = {}

    def _add(
        dc: str,
        title: str,
        body_system: str | None,
        origin: str,
        signal: str,
        source_ref: str | None = None,
        primary_dc: str | None = None,
    ) -> None:
        key = (dc, origin, primary_dc or "")
        existing = candidates.get(key)
        if existing and len(signal) <= len(existing.seed_signal):
            return
        candidates[key] = CandidateRating(
            diagnostic_code=dc,
            title=title,
            body_system=body_system,
            origin=origin,
            seed_signal=signal,
            source_ref=source_ref,
            primary_dc=primary_dc,
        )

    for cond in dossier.conditions or []:
        name = (cond.get("name") or "").strip()
        if not name:
            continue
        cond_dc = cond.get("diagnostic_code") or None
        resolved_dc = _resolve_dc(name, known_dc=cond_dc, max_ratings=max_ratings)

        dc_val = resolved_dc or ""
        ttl = _title(resolved_dc, name, max_ratings)
        bs = _body_system(resolved_dc, max_ratings)

        if resolved_dc:
            signal = f"claimed/known condition '{name}'"
        else:
            signal = f"claimed/known condition '{name}' (unresolved DC)"

        # ONE direct candidate per condition — the veteran's own resolved code.
        # We deliberately do NOT fan out to "sibling" DCs in the same schedule
        # group: a veteran with knee bursitis does not thereby have osteomyelitis,
        # bone cancer, or every skeletal muscle group, and a veteran with anxiety
        # does not have schizophrenia or Alzheimer's. That expansion produced 100+
        # nonsensical, trust-destroying candidates on real records. Correct-coding
        # and genuinely-separate manifestations are handled by DC resolution, the
        # `increase` origin, and the Esteban/underrating specialist — not here.
        _add(
            dc=dc_val,
            title=ttl,
            body_system=bs,
            origin="direct",
            signal=signal,
            source_ref=cond.get("id"),
        )

    for cond in dossier.conditions or []:
        if cond.get("va_status") != "service_connected":
            continue
        cr = cond.get("current_rating")
        target = cond.get("target_rating")
        if not isinstance(cr, int) or not isinstance(target, int) or target <= cr:
            continue
        has_evidence = cond.get("has_have_evidence", False)
        if not has_evidence:
            continue
        name = (cond.get("name") or "").strip()
        cond_dc = cond.get("diagnostic_code") or None
        resolved_dc = _resolve_dc(name, known_dc=cond_dc, max_ratings=max_ratings)
        if not resolved_dc:
            continue
        ceiling = (max_ratings.get(resolved_dc) or {}).get("max_rating")
        if isinstance(ceiling, int) and target > ceiling:
            continue
        _add(
            dc=resolved_dc,
            title=_title(resolved_dc, name, max_ratings),
            body_system=_body_system(resolved_dc, max_ratings),
            origin="increase",
            signal=(
                f"rated at {cr}%; veteran-entered review target {target}% is higher "
                "and supporting evidence is marked on hand"
            ),
            source_ref=cond.get("id"),
        )

    names = [c.get("name", "") for c in (dossier.conditions or []) if c.get("name")]
    for m in match_secondaries(names, secondary_map):
        sec_name = (m.get("secondary") or "").strip()
        primary_name = (m.get("primary") or "").strip()
        if not sec_name or not primary_name:
            continue

        primary_cond = next(
            (
                c
                for c in (dossier.conditions or [])
                if _normalize(c.get("name", "")) == _normalize(primary_name)
            ),
            None,
        )
        primary_dc = primary_cond.get("diagnostic_code") if primary_cond else None
        if not primary_dc:
            primary_dc = _resolve_dc(primary_name, max_ratings=max_ratings)

        sec_dc = _resolve_dc(sec_name, max_ratings=max_ratings)
        _add(
            dc=sec_dc or "",
            title=_title(sec_dc, sec_name, max_ratings),
            body_system=_body_system(sec_dc, max_ratings),
            origin="secondary",
            signal=f"§3.310 secondary to '{primary_name}'",
            source_ref=None,
            primary_dc=primary_dc,
        )

    profile = dossier.profile or {}
    condition_names = [
        str(c.get("name") or "")
        for c in (dossier.conditions or [])
        if isinstance(c, dict)
    ]
    for pm in match_presumptives(profile, cards, condition_names=condition_names):
        matched_reason = pm.get("matched_reason", "")
        for cond_name in pm.get("conditions") or []:
            cond_name_s = (cond_name or "").strip()
            if not cond_name_s:
                continue
            cond_dc = _resolve_dc(cond_name_s, max_ratings=max_ratings)
            _add(
                dc=cond_dc or "",
                title=_title(cond_dc, cond_name_s, max_ratings),
                body_system=_body_system(cond_dc, max_ratings),
                origin="presumptive",
                signal=matched_reason,
                source_ref=None,
            )

    cc = dossier.current_combined
    receives_retired_pay = _profile_flag(
        profile,
        "military_retired",
        "receives_military_retired_pay",
        "receives_retired_pay",
    )
    combat_related_flag = _profile_flag(
        profile,
        "combat_related_disability",
        "crsc_flag",
    )
    concurrent_reasons: list[str] = []
    if receives_retired_pay and isinstance(cc, int) and cc >= 50:
        concurrent_reasons.append(
            f"profile explicitly records military retired pay and a {cc}% combined rating for CRDP review"
        )
    if receives_retired_pay and combat_related_flag:
        concurrent_reasons.append(
            "profile explicitly flags retired pay and a combat-related disability for CRSC review"
        )
    if concurrent_reasons:
        _add(
            dc="",
            title="Concurrent receipt (CRDP/CRSC)",
            body_system=None,
            origin="concurrent",
            signal="; ".join(concurrent_reasons),
            source_ref=None,
        )

    return list(candidates.values())
