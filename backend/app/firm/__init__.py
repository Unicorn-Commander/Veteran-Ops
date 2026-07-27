"""Rating Raider's specialist firm — the deterministic rating-strategy seeds,
graduated into grounded, reviewed specialist findings that feed the Battle Plan.

Public surface:
    Finding, Specialist   — the framework (base.py)
    VeteranDossier, build_dossier  — the canonical read (context.py)
    run_firm              — fan-out + review + rank (orchestrator.py)
"""

from __future__ import annotations

from .base import Finding, Specialist
from .candidates import CandidateRating
from .context import VeteranDossier, build_dossier
from .orchestrator import DeepDiveResult, deep_dive, run_firm

__all__ = [
    "CandidateRating",
    "DeepDiveResult",
    "Finding",
    "Specialist",
    "VeteranDossier",
    "build_dossier",
    "deep_dive",
    "run_firm",
]
