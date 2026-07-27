"""Analysis package — the deterministic 'brain' behind /analysis and /conditions/{id}/gaps.

Design rule (hard): the deterministic cores in gaps.py / presumptives.py /
secondaries.py are PURE functions over plain dicts — no DB, no LLM — so they are
unit-testable and their outputs are always grounded. The LLM (mapping.py, used
by the analysis router) only selects among retrieved KB cards and phrases
educational text; anything it says that is not present in the retrieved cards'
structured data is dropped.
"""

from .gaps import analyze_gaps, map_dbq  # noqa: F401
from .presumptives import match_presumptives  # noqa: F401
from .secondaries import match_secondaries  # noqa: F401
