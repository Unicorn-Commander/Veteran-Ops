"""KB card corpus: file loaders + retrieval.

File loaders are pure (stdlib only) so analysis rules and tests can use them
without a database or an inference fleet. Retrieval prefers pgvector cosine
similarity over the seeded embeddings and degrades gracefully to ILIKE keyword
search when embeddings are unavailable (unset endpoint, outage, or an
un-embedded corpus).

NOTE: the LLM gateway is imported lazily inside functions — the loaders must be
importable in environments without the `openai` package (pure-function tests).
"""

from __future__ import annotations

import csv
import json
import logging
import re
import uuid
from functools import lru_cache
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import KBCard

log = logging.getLogger("veteran_ops.kb")

DATA_DIR = Path(__file__).parent / "data"
VENDOR_DIR = DATA_DIR / "vendor"

# Every data file is a JSON list of kb_cards EXCEPT secondary_map.json, which is
# the analysis-only secondary-condition suggestion map (not a card).
_NON_CARD_FILES = {"secondary_map.json"}


# ── Pure file loaders ────────────────────────────────────────────────────────
def load_cards() -> list[dict]:
    """All authored kb_cards from data/*.json (excluding the secondary map)."""
    cards: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        if path.name in _NON_CARD_FILES:
            continue
        try:
            loaded = json.loads(path.read_text())
        except Exception:  # noqa: BLE001 — a bad file must not sink the corpus
            log.exception("Failed to load KB data file %s", path.name)
            continue
        if isinstance(loaded, list):
            cards.extend(c for c in loaded if isinstance(c, dict))
        else:
            log.warning("KB data file %s is not a list — skipped.", path.name)
    return cards


def load_secondary_map() -> list[dict]:
    """The secondary-condition suggestion map (38 CFR §3.310 patterns).

    Returns the `map` list: [{primary_keywords: [...], secondaries: [
    {condition, rationale, dbq}, ...]}, ...]. Used by the analysis endpoints;
    NOT a kb_card.
    """
    path = DATA_DIR / "secondary_map.json"
    try:
        data = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        log.exception("Failed to load secondary_map.json")
        return []
    entries = data.get("map") if isinstance(data, dict) else None
    return [e for e in entries or [] if isinstance(e, dict)]


def dbq_catalog_source() -> str:
    """The cite string of the DBQ catalog card (returned with /kb/dbq lookups)."""
    path = DATA_DIR / "dbq.json"
    try:
        cards = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return "VA Disability Benefits Questionnaires (VA.gov/find-forms)"
    for card in cards if isinstance(cards, list) else []:
        if (card or {}).get("source"):
            return str(card["source"])
    return "VA Disability Benefits Questionnaires (VA.gov/find-forms)"


def load_dbq_catalog() -> list[dict]:
    """The DBQ catalog rows from dbq.json: [{condition, dbq, body_system}, ...]."""
    path = DATA_DIR / "dbq.json"
    try:
        cards = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        log.exception("Failed to load dbq.json")
        return []
    for card in cards if isinstance(cards, list) else []:
        catalog = ((card or {}).get("data") or {}).get("catalog")
        if isinstance(catalog, list):
            return [e for e in catalog if isinstance(e, dict)]
    return []


# ── Vendored VA open-data loaders (see data/vendor/README.md; all CC0) ──────
# Degradation contract: a missing/corrupt vendor file returns an EMPTY mapping
# with a WARNING — every consumer must treat "no data" as "feature quietly off".


def load_max_ratings() -> dict[str, dict]:
    """VA max-ratings lookup: diagnostic code → schedular-ceiling row.

    Source: department-of-veterans-affairs/disability-max-ratings-api (CC0),
    vendored as data/vendor/max_ratings.csv. Returns
    {dc: {max_rating, body_system, category, cfr_reference, rated_issue_name,
    diagnostic_code}}. Pure (stdlib only); empty dict when the file is absent.
    """
    path = VENDOR_DIR / "max_ratings.csv"
    out: dict[str, dict] = {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                dc = (row.get("Diagnostic Code") or "").strip()
                mx = (row.get("Max Rating") or "").strip()
                if not dc or not mx.isdigit():
                    continue
                out[dc] = {
                    "diagnostic_code": dc,
                    "rated_issue_name": (row.get("Rated Issue Name") or "").strip() or None,
                    "max_rating": int(mx),
                    "body_system": (row.get("Body System") or "").strip() or None,
                    "category": (row.get("Category") or "").strip() or None,
                    "cfr_reference": (row.get("CFR Reference") or "").strip() or None,
                }
    except FileNotFoundError:
        log.warning(
            "Vendored max-ratings dataset missing (%s) — max-rating features off.", path
        )
    except Exception:  # noqa: BLE001 — a bad vendor file must not sink the app
        log.exception("Failed to load max_ratings.csv")
    return out


# Columns of contention_text_lookup.csv that hold matchable terms (mirrors the
# upstream app_config.yaml `input_key` list).
_CONTENTION_TERM_COLUMNS = (
    ["Main condition/term"]
    + [f"Synonym term {i}" for i in range(1, 5)]
    + [f"Legacy term {i}" for i in range(1, 8)]
    + [f"Autosuggestion term {i}" for i in range(1, 7)]
)

# Filler words stripped on the SECOND match attempt (subset of the upstream
# common-words list — laterality/severity words that don't change the condition).
_CONTENTION_FILLER = {
    "left", "right", "bilateral", "chronic", "recurrent", "severe", "mild",
    "moderate", "the", "my", "of", "in", "and", "a", "an", "condition",
}


def _norm_term(text: str) -> str:
    """Deterministic normalization: casefold, punctuation → space, collapse."""
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").casefold()).strip()


def _norm_collapse(text: str) -> str:
    return " ".join(_norm_term(text).split())


def load_contention_map() -> dict[str, dict]:
    """VA contention-classification lookup (official claim taxonomy).

    Source: department-of-veterans-affairs/contention-classification-api (CC0),
    vendored as data/vendor/contention_dc_lookup.csv (DC → classification) and
    contention_text_lookup.csv (taxonomy terms → classification; only rows whose
    'Active classification mapping' is Active). Returns
    {"by_dc": {dc: hit}, "by_text": {normalized term: hit}} where hit =
    {classification_code, classification_name}. Empty maps when files absent.
    """
    by_dc: dict[str, dict] = {}
    by_text: dict[str, dict] = {}

    dc_path = VENDOR_DIR / "contention_dc_lookup.csv"
    try:
        with dc_path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                dc = (row.get("DIAGNOSTIC_CODE") or "").strip()
                name = (row.get("CLASSIFICATION_TEXT") or "").strip()
                code = (row.get("CLASSIFICATION_CODE") or "").strip()
                if dc and name:
                    by_dc[dc] = {
                        "classification_code": int(code) if code.isdigit() else None,
                        "classification_name": name,
                    }
    except FileNotFoundError:
        log.warning(
            "Vendored contention DC lookup missing (%s) — DC classification off.", dc_path
        )
    except Exception:  # noqa: BLE001
        log.exception("Failed to load contention_dc_lookup.csv")

    text_path = VENDOR_DIR / "contention_text_lookup.csv"
    try:
        with text_path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if (row.get("Active classification mapping") or "").strip() != "Active":
                    continue
                name = (row.get("Classification Text") or "").strip()
                code = (row.get("Classification Code") or "").strip()
                if not name:
                    continue
                hit = {
                    "classification_code": int(code) if code.isdigit() else None,
                    "classification_name": name,
                }
                terms = [row.get(col) or "" for col in _CONTENTION_TERM_COLUMNS]
                # 'All synonyms' aggregates pipe-separated variants.
                terms.extend((row.get("All synonyms") or "").split("|"))
                for term in terms:
                    key = _norm_collapse(term)
                    if key:
                        by_text.setdefault(key, hit)
    except FileNotFoundError:
        log.warning(
            "Vendored contention text lookup missing (%s) — text classification off.",
            text_path,
        )
    except Exception:  # noqa: BLE001
        log.exception("Failed to load contention_text_lookup.csv")

    return {"by_dc": by_dc, "by_text": by_text}


@lru_cache(maxsize=1)
def cached_max_ratings() -> dict[str, dict]:
    """Process-lifetime cache of load_max_ratings() for hot paths (gaps, API).
    The vendor file is a build-time artifact, so caching an empty miss is fine."""
    return load_max_ratings()


@lru_cache(maxsize=1)
def cached_contention_map() -> dict[str, dict]:
    """Process-lifetime cache of load_contention_map() for hot paths."""
    return load_contention_map()


def classify_contention(
    text: str | None = None,
    diagnostic_code: str | None = None,
    cmap: dict | None = None,
) -> dict | None:
    """Deterministic official-taxonomy match (NO LLM): DC hit first, then exact
    normalized text, then text with laterality/severity filler removed. Returns
    {classification_code, classification_name, match: 'diagnostic_code'|'text'}
    or None. Pure given cmap; defaults to the cached vendored map."""
    cmap = cmap if cmap is not None else cached_contention_map()
    dc = (diagnostic_code or "").strip()
    if dc:
        hit = (cmap.get("by_dc") or {}).get(dc)
        if hit:
            return {**hit, "match": "diagnostic_code"}
    by_text = cmap.get("by_text") or {}
    key = _norm_collapse(text or "")
    if key:
        hit = by_text.get(key)
        if hit:
            return {**hit, "match": "text"}
        stripped = " ".join(w for w in key.split() if w not in _CONTENTION_FILLER)
        if stripped and stripped != key:
            hit = by_text.get(stripped)
            if hit:
                return {**hit, "match": "text"}
    return None


def validate_kb_max_ratings(cards: list[dict] | None = None) -> list[dict]:
    """KB QA (startup, non-fatal): flag any authored rating_criteria card whose
    tiers exceed the VA max-ratings dataset ceiling for its diagnostic code.
    Logs a WARNING per discrepancy and returns them (unit-testable).

    When `cards` is supplied, validates that proposed/current corpus instead of the
    authored file corpus. The refresh receiver uses this to fail closed before a
    curated batch can change live criteria."""
    max_map = load_max_ratings()
    issues: list[dict] = []
    if not max_map:
        return issues
    for card in cards if cards is not None else load_cards():
        if card.get("card_type") != "rating_criteria":
            continue
        dc = (card.get("diagnostic_code") or "").strip()
        tiers = (card.get("data") or {}).get("tiers") or []
        row = max_map.get(dc)
        if not row or not tiers:
            continue
        try:
            card_max = max(int(t.get("percent", 0)) for t in tiers if isinstance(t, dict))
        except (ValueError, TypeError):
            continue
        if card_max > int(row["max_rating"]):
            issue = {
                "diagnostic_code": dc,
                "title": card.get("title"),
                "card_max": card_max,
                "dataset_max": int(row["max_rating"]),
                "rated_issue_name": row.get("rated_issue_name"),
            }
            issues.append(issue)
            log.warning(
                "KB QA: rating_criteria card %r (DC %s) has a %d%% tier above the "
                "VA max-ratings dataset ceiling of %d%% for that code (%s) — "
                "verify the card against eCFR.",
                card.get("title"), dc, card_max, issue["dataset_max"],
                row.get("rated_issue_name"),
            )
    return issues


# ── Retrieval (DB) ───────────────────────────────────────────────────────────
_GENERIC_TERMS = {
    "chronic", "acute", "severe", "moderate", "mild", "bilateral", "left",
    "right", "condition", "conditions", "syndrome", "disorder", "disease",
    "pain", "the", "and", "with", "for",
}


def _card_text(card: KBCard) -> str:
    """Render a card for the cross-encoder: title + diagnostic code + a bounded
    slice of body (rerankers cap input; the discriminative text is up front)."""
    dc = f" (DC {card.diagnostic_code})" if card.diagnostic_code else ""
    return f"{card.title or ''}{dc}\n{(card.content or '')[:2000]}"


def _keyword_filter(query: str):
    """OR of ILIKE terms over title/content/diagnostic_code for each word."""
    terms = [w.strip() for w in query.split() if len(w.strip()) >= 3]
    if not terms:
        terms = [query.strip()] if query.strip() else []
    clauses = []
    for t in terms:
        pat = f"%{t}%"
        clauses.append(KBCard.title.ilike(pat))
        clauses.append(KBCard.content.ilike(pat))
        clauses.append(KBCard.diagnostic_code.ilike(pat))
    return or_(*clauses) if clauses else None


async def retrieve_cards(
    db: AsyncSession,
    query: str,
    *,
    k: int = 4,
    card_type: str | None = None,
    body_system: str | None = None,
) -> list[KBCard]:
    """Top-k cards for a query: cosine over embeddings when available, ILIKE
    keyword fallback otherwise. Never raises on retrieval-infrastructure failure."""
    if not query.strip():
        return []

    # Vector path — requires an embeddings endpoint AND embedded cards.
    qv: list[float] | None = None
    try:
        from ..llm.gateway import gateway  # lazy: keep loaders importable w/o openai

        vecs = await gateway.embed([query])
        qv = vecs[0] if vecs else None
    except Exception:  # noqa: BLE001 — degrade to keyword search
        qv = None

    if qv is not None:
        # Two-stage retrieval: widen the vector-recall net when a reranker is
        # configured, then let the cross-encoder pick the top-k for precision.
        from ..config import settings  # lazy: keep loaders importable w/o app config

        recall_k = max(k, settings.rerank_candidate_k) if settings.reranker_enabled else k
        stmt = select(KBCard).where(KBCard.embedding.is_not(None))
        if card_type:
            stmt = stmt.where(KBCard.card_type == card_type)
        if body_system:
            stmt = stmt.where(KBCard.body_system == body_system)
        stmt = stmt.order_by(KBCard.embedding.cosine_distance(qv)).limit(recall_k)
        rows = list((await db.execute(stmt)).scalars().all())
        if rows:
            if settings.reranker_enabled and len(rows) > k:
                from ..llm.gateway import gateway

                return await gateway.rerank_rows(query, rows, _card_text, k=k)
            return rows[:k]

    return await keyword_cards(db, query, k=k, card_type=card_type, body_system=body_system)


async def keyword_cards(
    db: AsyncSession,
    query: str,
    *,
    k: int = 4,
    card_type: str | None = None,
    body_system: str | None = None,
) -> list[KBCard]:
    """ILIKE keyword search — the no-embeddings fallback."""
    stmt = select(KBCard)
    if card_type:
        stmt = stmt.where(KBCard.card_type == card_type)
    if body_system:
        stmt = stmt.where(KBCard.body_system == body_system)
    flt = _keyword_filter(query)
    if flt is not None:
        stmt = stmt.where(flt)
    # Fetch a wider net, then rank in Python by how many query terms actually
    # hit (title hits weighted over content) — a bare OR with LIMIT returns
    # whatever seeded first, which made "chronic sinusitis" surface the IBS
    # card on the word "chronic" alone. Generic clinical words don't count.
    rows = (await db.execute(stmt.limit(max(k * 8, 32)))).scalars().all()
    terms = {
        w.strip().lower()
        for w in query.split()
        if len(w.strip()) >= 3 and w.strip().lower() not in _GENERIC_TERMS
    } or {query.strip().lower()}

    def score(card: KBCard) -> int:
        title = (card.title or "").lower()
        content = (card.content or "").lower()
        sc = 0
        for t in terms:
            if t in title:
                sc += 3
            elif t in content:
                sc += 1
            if card.diagnostic_code and t == str(card.diagnostic_code).lower():
                sc += 5
        return sc

    ranked = sorted(rows, key=score, reverse=True)
    ranked = [r for r in ranked if score(r) > 0]
    return ranked[:k]


async def cards_by_type(db: AsyncSession, card_type: str) -> list[KBCard]:
    stmt = select(KBCard).where(KBCard.card_type == card_type).order_by(KBCard.title)
    return list((await db.execute(stmt)).scalars().all())


async def card_by_diagnostic_code(
    db: AsyncSession, diagnostic_code: str, *, card_type: str = "rating_criteria"
) -> KBCard | None:
    """Exact rating-card lookup by diagnostic code — DETERMINISTIC, not embedding
    similarity. Rating cards cluster tightly by body system in vector space (knee
    DCs 5256-5261 sit next to each other), so a nearest-neighbour gate can miss the
    exact card and drop a valid candidate; this exact match is the correct gate."""
    dc = (diagnostic_code or "").strip()
    if not dc:
        return None
    stmt = (
        select(KBCard)
        .where(KBCard.card_type == card_type, KBCard.diagnostic_code == dc)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def cards_by_ids(db: AsyncSession, ids: list[str]) -> list[KBCard]:
    """Fetch KB cards by exact id — the reviewer's independent RE-RESOLUTION of a
    theory's law citations (never trust the finding's own card_ids list). Malformed
    ids are dropped; a requested id that has no row simply doesn't come back, so the
    caller can fail closed on any cited id that fails to resolve."""
    uuids: list[uuid.UUID] = []
    for i in ids or []:
        try:
            uuids.append(uuid.UUID(str(i)))
        except (ValueError, TypeError, AttributeError):
            continue
    if not uuids:
        return []
    return list((await db.execute(select(KBCard).where(KBCard.id.in_(uuids)))).scalars().all())
