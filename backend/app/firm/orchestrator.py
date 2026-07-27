"""Firm orchestration — the fast roster and exhaustive candidate deep dive.

The firm's managing partner: it runs every specialist over the SAME dossier
concurrently, flattens and dedupes their findings, sends them through the
adversarial reviewer (dropping any that can't be made safe), and ranks the
survivors the way the Battle Plan ranks everything else — severity, then
confidence, then category. The result is a list of reviewed, ranked Findings the
router merges into the plan.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ..config import settings
from ..strategy.plan import _CATEGORY_RANK, _IMPACT_RANK
from .base import Finding
from .candidates import CandidateRating
from .deepdive import deep_dive_candidate
from .enumerate import enumerate_candidates
from .reviewer import review
from .resolve import resolve_conflicts
from .specialists import ROSTER

log = logging.getLogger("veteran_ops.firm")

# Category tie-break for the rank (mirrors plan._CATEGORY_RANK's intent — the
# highest-leverage compensation findings first).
_KIND_RANK = {
    "secondary": 0,
    "tdiu": 1,
    "smc_education": 2,
    "underrating": 3,
    "nexus_gap": 4,
    "pyramiding": 5,
    "presumptive": 6,
    "cp_exam_prep": 7,
}


def _rank_key(f: Finding):
    # severity asc-rank (high=0 first) → confidence desc → category.
    return (_IMPACT_RANK.get(f.severity, 1), -f.confidence, _KIND_RANK.get(f.kind, 9))


_DEEP_DIVE_CATEGORY = {
    "concurrent": "protect_backpay",
    "increase": "file",
    "direct": "file",
    "secondary": "add_condition",
    "presumptive": "add_condition",
}


def _deep_dive_rank_key(f: Finding):
    active = f.seed.get("active") is not False
    category = _DEEP_DIVE_CATEGORY.get(str(f.seed.get("origin") or f.kind), "add_condition")
    return (
        0 if active else 1,
        _IMPACT_RANK.get(f.severity, 1),
        -f.confidence,
        _CATEGORY_RANK.get(category, 9),
        f.key,
    )


def _finding_payload(finding: Finding) -> dict:
    """Serialized Finding plus auditable resolver annotations."""
    payload = finding.to_dict()
    seed = finding.seed
    for key in (
        "diagnostic_code",
        "origin",
        "rating_percent",
        "superseded_by",
        "excluded_by",
        "conflict_reason",
        "conflict_cfr",
        "active",
    ):
        payload[key] = seed.get(key)
    return payload


@dataclass
class DeepDiveResult:
    candidates: list[CandidateRating]
    findings: list[Finding]
    projected_combined: int
    current_combined: int | None = None
    notes: list[str] = field(default_factory=list)
    generated_at: str = ""

    @property
    def candidates_considered(self) -> int:
        return len(self.candidates)

    @property
    def delta(self) -> int:
        return self.projected_combined - (self.current_combined or 0)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "candidates": [asdict(candidate) for candidate in self.candidates],
            "candidates_considered": self.candidates_considered,
            "findings": [_finding_payload(finding) for finding in self.findings],
            "projected_combined": self.projected_combined,
            "current_combined": self.current_combined,
            "delta": self.delta,
            "notes": list(self.notes),
        }

    @classmethod
    def empty(cls, current_combined: int | None = None) -> "DeepDiveResult":
        return cls(
            candidates=[],
            findings=[],
            projected_combined=current_combined or 0,
            current_combined=current_combined,
            notes=[],
            generated_at="",
        )


def _dedupe_candidates(candidates: list[CandidateRating]) -> list[CandidateRating]:
    """Stable dedupe at the shared enumerator/orchestrator boundary."""
    seen: set[tuple[str, str, str | None]] = set()
    out: list[CandidateRating] = []
    for candidate in candidates:
        key = (candidate.diagnostic_code, candidate.origin, candidate.primary_dc)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


async def _run_candidates(db, dossier, candidates: list[CandidateRating]):
    """Bounded fan-out so a large candidate catalog cannot stampede the gateway."""
    limit = max(1, int(getattr(settings, "deep_dive_concurrency", 4)))
    semaphore = asyncio.Semaphore(limit)

    async def one(candidate: CandidateRating):
        async with semaphore:
            return await deep_dive_candidate(db, dossier, candidate)

    return await asyncio.gather(*(one(candidate) for candidate in candidates), return_exceptions=True)


async def deep_dive(db, dossier) -> DeepDiveResult:
    """Enumerate → expert fan-out → adversarial review → deterministic resolve."""
    candidates = _dedupe_candidates(list(enumerate_candidates(dossier)))
    results = await _run_candidates(db, dossier, candidates)

    findings: list[Finding] = []
    for candidate, result in zip(candidates, results):
        if isinstance(result, Exception):
            log.warning(
                "firm/deep-dive: candidate %s (%s) failed — skipped.",
                candidate.diagnostic_code,
                candidate.origin,
                exc_info=result,
            )
            continue
        if result is not None:
            findings.append(result)

    # Defensive key dedupe.  Candidate tuples are unique, but independently built
    # enumerators may intentionally converge on the same rendered finding.
    seen_keys: set[str] = set()
    unique_findings: list[Finding] = []
    for finding in findings:
        if not finding.key or finding.key in seen_keys:
            continue
        seen_keys.add(finding.key)
        unique_findings.append(finding)

    reviewed = await review(unique_findings, db)
    resolved = resolve_conflicts(reviewed, dossier)
    resolved.findings.sort(key=_deep_dive_rank_key)
    return DeepDiveResult(
        candidates=candidates,
        findings=resolved.findings,
        projected_combined=resolved.projected_combined,
        current_combined=dossier.current_combined,
        notes=resolved.notes,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


async def run_firm(dossier, db, only: list[str] | None = None) -> list[Finding]:
    """Run the firm over a dossier and return reviewed, ranked findings.

    only: restrict to a subset of specialist names (e.g. ["secondaries"]).
    Never raises — a failing specialist is logged and skipped; the reviewer
    degrades enrichment to the deterministic seed when the LLM is unavailable.
    """
    roster = ROSTER
    if only:
        wanted = set(only)
        roster = [s for s in ROSTER if s.name in wanted]

    results = await asyncio.gather(
        *(s.find(db, dossier) for s in roster), return_exceptions=True
    )

    findings: list[Finding] = []
    for sp, res in zip(roster, results):
        if isinstance(res, Exception):
            log.warning("firm/%s: find() failed — skipped.", sp.name, exc_info=res)
            continue
        findings.extend(res)

    # Dedupe by stable key (first wins — roster order is deterministic).
    seen: set[str] = set()
    deduped: list[Finding] = []
    for f in findings:
        if not f.key or f.key in seen:
            continue
        seen.add(f.key)
        deduped.append(f)

    reviewed = await review(deduped, db)
    reviewed.sort(key=_rank_key)
    return reviewed
