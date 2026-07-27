"""Pure, deterministic reconciliation for deep-dive findings.

No model participates here.  Every finding remains in the result for audit;
overlapping lanes are annotated, never silently discarded.  Rating arithmetic is
delegated exclusively to :mod:`app.rating.engine`.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..analysis.mapping import tier_percents
from ..rating.engine import RatingEntry, combined_rating
from ..strategy.rating_rules import find_pyramiding_cautions
from .base import Finding

_EXCLUSIONS_PATH = Path(__file__).parents[1] / "kb" / "data" / "vendor" / "dc_exclusions.csv"


@dataclass
class ResolveResult:
    findings: list[Finding]
    projected_combined: int
    notes: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _exclusions() -> dict[frozenset[str], dict[str, str]]:
    try:
        with _EXCLUSIONS_PATH.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except (FileNotFoundError, OSError, csv.Error):
        return {}
    out: dict[frozenset[str], dict[str, str]] = {}
    for row in rows:
        a = str(row.get("dc_a") or "").strip()
        b = str(row.get("dc_b") or "").strip()
        if a and b and a != b:
            out[frozenset((a, b))] = {
                "cfr_cite": str(row.get("cfr_cite") or "38 CFR §4.14").strip(),
                "reason": str(row.get("reason") or "Mutually exclusive rating lanes.").strip(),
            }
    return out


def _dc(finding: Finding) -> str:
    return str(finding.seed.get("diagnostic_code") or "").strip()


def _allowed_percent(finding: Finding) -> int | None:
    """Projection percent only when the seed proves it came from the card."""
    value = finding.seed.get("rating_percent")
    try:
        percent = int(value)
    except (TypeError, ValueError):
        return None
    allowed: set[int] = set()
    for raw in finding.seed.get("tier_percents") or []:
        try:
            allowed.add(int(raw))
        except (TypeError, ValueError):
            continue
    # Compatibility with expert/test seeds that preserve the retrieved card data.
    allowed |= tier_percents(finding.seed.get("rating_card_data"))
    return percent if 0 <= percent <= 100 and percent in allowed else None


def _comparison_value(finding: Finding) -> int:
    """Grounded value for choosing between conflicts, never for projection."""
    projected = _allowed_percent(finding)
    if projected is not None:
        return projected
    allowed: set[int] = set()
    for raw in finding.seed.get("tier_percents") or []:
        try:
            allowed.add(int(raw))
        except (TypeError, ValueError):
            continue
    try:
        ceiling = int(finding.seed.get("max_tier_percent"))
    except (TypeError, ValueError):
        ceiling = -1
    return ceiling if ceiling in allowed else -1


def _comparison_rank(finding: Finding) -> tuple[int, int, str]:
    return (
        _comparison_value(finding),
        1 if _allowed_percent(finding) is not None else 0,
        finding.key,
    )


def _winner(left: Finding, right: Finding) -> tuple[Finding, Finding]:
    # A veteran-set/current tier wins; otherwise compare card-authored ceilings.
    # Stable key is only the final deterministic tie-break.
    lkey = _comparison_rank(left)
    rkey = _comparison_rank(right)
    return (left, right) if lkey >= rkey else (right, left)


def _mark_loser(loser: Finding, winner: Finding, *, field: str, reason: str, cite: str) -> None:
    # A stricter exclusion wins over a general pyramiding supersession.
    if field == "superseded_by" and loser.seed.get("excluded_by"):
        return
    loser.seed[field] = winner.key
    loser.seed["conflict_reason"] = reason
    loser.seed["conflict_cfr"] = cite
    loser.seed["active"] = False


def _same_site(left: Finding, right: Finding) -> bool:
    """Conservative identity check for the same joint/organ."""
    lref = str(left.seed.get("source_ref") or "").strip()
    rref = str(right.seed.get("source_ref") or "").strip()
    if lref and rref:
        return lref == rref
    lgroup = str(left.seed.get("group") or "").strip().casefold()
    rgroup = str(right.seed.get("group") or "").strip().casefold()
    if lgroup and rgroup:
        return lgroup == rgroup
    return False


def _apply_pyramiding(findings: list[Finding], notes: list[str]) -> None:
    """Run the established §4.14 finder over candidate-shaped conditions."""
    marker_to_finding: dict[str, Finding] = {}
    synthetic: list[dict] = []
    for index, finding in enumerate(findings):
        dc = _dc(finding)
        if not dc:
            continue
        marker = f"{finding.title} [deep-dive-{index}]"
        marker_to_finding[marker] = finding
        synthetic.append(
            {
                "name": marker,
                "diagnostic_code": dc,
                "status": "considering",
                "va_status": "unknown",
            }
        )

    for caution in find_pyramiding_cautions(synthetic):
        members = [marker_to_finding[n] for n in caution.get("conditions") or [] if n in marker_to_finding]
        if len(members) < 2:
            continue
        winner = max(members, key=_comparison_rank)
        for loser in members:
            if loser is winner:
                continue
            _mark_loser(
                loser,
                winner,
                field="superseded_by",
                reason=str(caution.get("body") or "These lanes compensate overlapping impairment."),
                cite=str(caution.get("reg") or "38 CFR §4.14"),
            )
        notes.append(
            f"Pyramiding review ({caution.get('reg') or '38 CFR §4.14'}): "
            f"kept {winner.title} as the higher grounded lane; overlapping findings remain visible."
        )


def _apply_same_code_lanes(findings: list[Finding], notes: list[str]) -> None:
    """One condition cannot contribute the same DC twice under two origins."""
    grouped: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        dc = _dc(finding)
        source_ref = str(finding.seed.get("source_ref") or "").strip()
        if dc and source_ref:
            grouped.setdefault((dc, source_ref), []).append(finding)
    for (dc, _), members in grouped.items():
        if len(members) < 2:
            continue
        winner = max(members, key=_comparison_rank)
        changed = False
        for loser in members:
            if loser is winner:
                continue
            _mark_loser(
                loser,
                winner,
                field="superseded_by",
                reason=(
                    f"These are alternative review origins for the same DC {dc} and "
                    "source condition; they cannot contribute two evaluations for the same impairment."
                ),
                cite="38 CFR §4.14",
            )
            changed = True
        if changed:
            notes.append(
                f"Same-code review (38 CFR §4.14): kept {winner.title} once under its "
                "higher grounded lane; the alternative origin remains visible."
            )


def _apply_exclusions(findings: list[Finding], notes: list[str]) -> None:
    rules = _exclusions()
    for index, left in enumerate(findings):
        for right in findings[index + 1 :]:
            rule = rules.get(frozenset((_dc(left), _dc(right))))
            if not rule or not _same_site(left, right):
                continue
            winner, loser = _winner(left, right)
            _mark_loser(
                loser,
                winner,
                field="excluded_by",
                reason=rule["reason"],
                cite=rule["cfr_cite"],
            )
            notes.append(
                f"Mutual-exclusivity review ({rule['cfr_cite']}): {loser.title} is shown "
                f"as excluded by the higher grounded {winner.title} lane for the same site."
            )


_LEFT_RE = re.compile(r"\bleft\b", re.IGNORECASE)
_RIGHT_RE = re.compile(r"\bright\b", re.IGNORECASE)


def _side(label: str, explicit) -> str | None:
    value = str(explicit or "").strip().lower()
    if value in ("left", "right"):
        return value
    if _LEFT_RE.search(label) and not _RIGHT_RE.search(label):
        return "left"
    if _RIGHT_RE.search(label) and not _LEFT_RE.search(label):
        return "right"
    return None


def _projection_entries(
    findings: list[Finding], dossier
) -> tuple[list[RatingEntry], bool, int]:
    """Build engine inputs without replacing an incomplete authoritative baseline.

    Returns ``(entries, baseline_mismatch, skipped_replacements)``. When the
    itemized current ratings reproduce the profile's combined rating, exact-DC
    candidates can safely replace their source entries. If they do not, the
    profile combined is kept as one engine baseline and only genuinely new DCs
    are added; an increase cannot be backed out of a rounded combined value.
    """
    entries: dict[str, RatingEntry] = {}
    condition_dc: dict[str, str] = {}
    for condition in dossier.conditions:
        percent = condition.get("current_rating")
        if (
            not isinstance(percent, int)
            or not 0 <= percent <= 100
            or str(condition.get("va_status") or "").lower() == "denied"
        ):
            continue
        ref = str(condition.get("id") or condition.get("diagnostic_code") or condition.get("name") or "")
        condition_dc[ref] = str(condition.get("diagnostic_code") or "").strip()
        label = str(condition.get("name") or condition.get("diagnostic_code") or "Current rating")
        entries[ref] = RatingEntry(
            label=label,
            percent=percent,
            side=_side(label, condition.get("side")),
            group=(str(condition.get("group")) if condition.get("group") else None),
        )

    profile_current = (
        dossier.current_combined if isinstance(dossier.current_combined, int) else None
    )
    itemized_current = combined_rating(list(entries.values())).combined
    baseline_mismatch = (
        profile_current is not None and itemized_current != profile_current
    )
    if baseline_mismatch:
        entries = {
            "__baseline__": RatingEntry(
                label="Current combined rating baseline",
                percent=profile_current,
            )
        }

    skipped_replacements = 0
    for finding in findings:
        if finding.seed.get("active") is False:
            continue
        percent = _allowed_percent(finding)
        if percent is None:
            continue
        source_ref = str(finding.seed.get("source_ref") or "").strip()
        dc = _dc(finding)
        if baseline_mismatch and source_ref and condition_dc.get(source_ref) == dc:
            skipped_replacements += 1
            continue
        # The candidate for a condition's existing DC replaces that condition's
        # baseline. A distinct, separately ratable DC at the same site remains a
        # separate engine entry (unless reconciliation marked it inactive).
        key = (
            source_ref
            if source_ref and condition_dc.get(source_ref) == dc
            else f"{source_ref or finding.key}:{dc}:{finding.seed.get('origin') or finding.kind}"
        )
        entries[key] = RatingEntry(
            label=finding.title,
            percent=percent,
            side=_side(finding.title, finding.seed.get("side")),
            group=(str(finding.seed.get("group")) if finding.seed.get("group") else None),
        )

    # No itemized data at all: retain the known profile baseline.
    if not entries and profile_current is not None:
        entries["__baseline__"] = RatingEntry(
            label="Current combined rating baseline",
            percent=profile_current,
        )
    return list(entries.values()), baseline_mismatch, skipped_replacements


def resolve_conflicts(findings: list[Finding], dossier) -> ResolveResult:
    """Annotate conflicts and project the surviving, grounded rating lanes."""
    notes: list[str] = []
    for finding in findings:
        finding.seed.pop("superseded_by", None)
        finding.seed.pop("excluded_by", None)
        finding.seed.pop("conflict_reason", None)
        finding.seed.pop("conflict_cfr", None)
        finding.seed["active"] = True

    _apply_same_code_lanes(findings, notes)
    _apply_pyramiding(findings, notes)
    _apply_exclusions(findings, notes)

    entries, baseline_mismatch, skipped_replacements = _projection_entries(
        findings, dossier
    )
    result = combined_rating(entries)
    if baseline_mismatch:
        notes.append(
            "The itemized current ratings do not reproduce the combined rating in the profile, "
            "so the projection preserves that recorded baseline and adds only new, separately "
            "grounded DCs."
        )
    if skipped_replacements:
        notes.append(
            f"{skipped_replacements} increase/replacement lane(s) are shown for review but not "
            "put into the numeric projection because the rounded baseline cannot be safely "
            "decomposed."
        )
    if result.bilateral_factor_applied:
        notes.append("The projection applies the bilateral factor under 38 CFR §4.26.")
    current = dossier.current_combined if isinstance(dossier.current_combined, int) else 0
    delta = result.combined - current
    notes.append(
        f"38 CFR §4.25 projection: {result.combined}% ({delta:+d} points versus the "
        "current combined rating). This is arithmetic on grounded planning inputs, not a VA outcome prediction."
    )
    return ResolveResult(findings=findings, projected_combined=result.combined, notes=notes)
