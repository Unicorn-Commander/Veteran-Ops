"""Knowledge base package — the citable grounding layer for every AI answer.

`store` loads the authored card corpus (backend/app/kb/data/*.json) and provides
retrieval (pgvector cosine when embeddings are configured, ILIKE fallback when
not). `seed` populates the kb_cards table idempotently at startup.
"""

from .freshness import KB_VERIFIED_AS_OF  # noqa: F401
from .store import (  # noqa: F401
    load_cards,
    load_contention_map,
    load_dbq_catalog,
    load_max_ratings,
    load_secondary_map,
)
