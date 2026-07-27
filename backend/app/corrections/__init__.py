"""Military records corrections (Wave 10) — the first Valor-Ops capability beyond
VA disability ratings.

Correcting a military record (a discharge upgrade, a wrong narrative reason, an
error on the DD-214, an unfair medical-separation rating) is a DIFFERENT process
from a VA claim: it goes to a MILITARY DEPARTMENT board (DRB / BCMR / PDBR), not the
VA. This module deterministically routes the veteran to the right board + form for
their situation and assembles the application packet — educational self-help, never
legal representation. Discharge-upgrade cases especially route to free legal aid.
"""
