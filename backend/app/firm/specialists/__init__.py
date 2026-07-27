"""The firm roster: graduated deterministic seeds + optional theory layer.

Each specialist wraps a PURE seed into the `Specialist` interface. Most are
deterministic-only (their seed note is carefully lane-worded); secondaries and
theory may enrich or originate under gates. Underrating (Esteban) is already
seeded by PyramidingSpecialist via find_underrating_opportunities — no separate
roster entry.
"""

from __future__ import annotations

from .cp_exam import CpExamSpecialist
from .nexus_evidence import NexusEvidenceSpecialist
from .presumptives import PresumptivesSpecialist
from .pyramiding import PyramidingSpecialist
from .secondaries import SecondariesSpecialist
from .smc import SmcSpecialist
from .tdiu import TdiuSpecialist
from .theory import TheorySpecialist

#: The firm roster, in a stable order (the orchestrator ranks the flattened
#: findings afterward, so this order only affects tie-broken fan-out). The
#: TheorySpecialist originates theories ABOVE the floor; it is inert (emits
#: nothing) unless settings.theory_origination_enabled is on.
ROSTER = [
    SecondariesSpecialist(),
    PyramidingSpecialist(),
    TdiuSpecialist(),
    SmcSpecialist(),
    PresumptivesSpecialist(),
    NexusEvidenceSpecialist(),
    CpExamSpecialist(),
    TheorySpecialist(),
]

__all__ = [
    "ROSTER",
    "SecondariesSpecialist",
    "PyramidingSpecialist",
    "TdiuSpecialist",
    "SmcSpecialist",
    "PresumptivesSpecialist",
    "NexusEvidenceSpecialist",
    "CpExamSpecialist",
    "TheorySpecialist",
]
