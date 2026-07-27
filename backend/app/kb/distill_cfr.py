"""Deterministic eCFR → KB card distiller (38 CFR Part 3 / Part 4).

Turns the staged eCFR structured XML (one ``<DIV8 TYPE="SECTION">`` per CFR
section) into ``KBRefreshBatch``-shaped JSON that the trusted receiver
(``POST /api/kb/refresh``) accepts. It is **pure/structural** — no LLM, no
paraphrase. Regulation text is emitted verbatim; a rating tier is only ever
produced when the schedule explicitly pairs a criterion with a percentage, and
a table that will not parse cleanly degrades to a verbatim ``process`` card
rather than a malformed ``tiers`` list.

Two lanes (mirrors ``manifest/INGESTION-SPEC.md``):

* **Part 4** rating tables → ``rating_criteria`` items — one per diagnostic
  code, ``content_kind="criteria"``, ``diagnostic_code`` set, and
  ``data.tiers = [{percent, criteria}]`` parsed from the schedule.
  * DC-per-row tables (digestive, infectious, most schedules incl. DC 6354 /
    5025 / 7346) → one card per DC.
  * A shared "General Rating Formula" table with the diagnostic-code list in a
    preceding ``FP``/``EXTRACT`` block (e.g. §4.130 mental, DC 9411) → one card
    per listed DC, all carrying the shared formula's tiers.
  * Non-rating Part 4 sections (§4.14 pyramiding, §4.25, §4.16 TDIU, …) → one
    verbatim ``process`` card (``data.distill.kind = "rule"``).
* **Part 3** curated adjudication sections → verbatim ``process`` cards;
  presumptive sections → verbatim ``process`` cards flagged
  ``data.distill.kind = "presumptive"``.

Door constraint honoured deliberately: ``KBRefreshRatingCriteriaItem`` +
``kb.refresh.normalize_rating_item`` only mint ``rating_criteria`` cards (from
``content_kind="criteria"``, ``affects_advice=True``) and ``process`` cards
(from ``content_kind="explainer"``, ``affects_advice=False``). ``rule`` and
``presumptive`` are distiller classifications recorded under
``data.distill.kind``; through the current receiver they land as ``process``
cards. The distiller emits what the receiver accepts and never fabricates a
tier.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator

# ── Corpus constants (from corpus-manifest.json) ─────────────────────────────
# Title 38 has no per-section amendment date in the eCFR structured XML, so the
# title-level ``latest_amended_on`` is the best deterministic effective date.
DEFAULT_EFFECTIVE_DATE = date(2026, 6, 15)  # title38_latest_amended_on
DEFAULT_VERIFIED_AS_OF = date(2026, 7, 8)  # corpus fetched_date
ECFR_HUMAN_BASE = "https://www.ecfr.gov/current/title-38/chapter-I"
SOURCE_NAME = "eCFR"

BATCH_SOURCE = {
    "name": "eCFR — 38 CFR (staged corpus)",
    "url": "https://www.ecfr.gov/current/title-38",
    "note": "Deterministic distiller over the staged eCFR structured XML.",
}

# Part 3 sections we distill (explicit allow-lists keep the batch focused on the
# adjudication + presumptive rules the app reasons about, not admin sections).
PART3_PROCESS_SECTIONS = (
    "3.303", "3.304", "3.306", "3.310", "3.317", "3.344",
    "3.951", "3.957", "3.105", "3.31", "3.400", "3.156",
)
PART3_PRESUMPTIVE_SECTIONS = (
    "3.307", "3.309", "3.313", "3.316", "3.318", "3.320",
)

# ── Body-system map (38 CFR Part 4 subpart B organization) ───────────────────
# (low, high_inclusive, body_system) over the section's leading number.
_PART4_BODY_SYSTEMS: tuple[tuple[float, float, str], ...] = (
    (4.40, 4.73, "musculoskeletal"),
    (4.75, 4.84, "eye"),
    (4.85, 4.87, "auditory"),
    (4.88, 4.89, "infectious"),
    (4.96, 4.97, "respiratory"),
    (4.100, 4.104, "cardiovascular"),
    (4.110, 4.114, "digestive"),
    (4.115, 4.115, "genitourinary"),
    (4.116, 4.116, "gynecological"),
    (4.117, 4.117, "hemic"),
    (4.118, 4.118, "skin"),
    (4.119, 4.119, "endocrine"),
    (4.120, 4.124, "neurological"),
    (4.125, 4.130, "mental"),
    (4.149, 4.150, "dental"),
)

_DC_ROW_RE = re.compile(r"^(\d{4})\b\s*(.*)$", re.S)
_PERCENT_RE = re.compile(r"^(\d{1,3})$")
_REMOVED_RE = re.compile(r"\[(removed|reserved|removed and reserved)\]", re.I)
_SECTION_NUM_RE = re.compile(r"(\d+)\.(\d+)")


# ── Text helpers ─────────────────────────────────────────────────────────────
def _text(el: ET.Element | None) -> str:
    """Verbatim inline text of an element (all descendants), whitespace-collapsed."""
    if el is None:
        return ""
    raw = "".join(el.itertext())
    return re.sub(r"\s+", " ", raw).strip()


def _leading_number(section_n: str) -> float | None:
    m = _SECTION_NUM_RE.search(section_n or "")
    if not m:
        return None
    try:
        return float(f"{m.group(1)}.{m.group(2)}")
    except ValueError:
        return None


def part4_body_system(section_n: str) -> str:
    num = _leading_number(section_n)
    if num is None:
        return "general"
    for low, high, system in _PART4_BODY_SYSTEMS:
        # inclusive on the integer.decimal band (e.g. 4.71a → 4.71 ∈ [4.40,4.73])
        if low <= num <= high + 1e-9:
            return system
    return "general"


def section_url(section_n: str) -> str:
    """eCFR deep-link for a section (part inferred from the section number)."""
    part = (section_n.split(".", 1)[0] or "").strip()
    return f"{ECFR_HUMAN_BASE}/part-{part}/section-{section_n}"


def section_cite(section_n: str, diagnostic_code: str | None = None) -> str:
    base = f"38 CFR §{section_n}"
    return f"{base}, DC {diagnostic_code}" if diagnostic_code else base


# ── Section model ────────────────────────────────────────────────────────────
@dataclass
class Section:
    n: str
    head: str
    el: ET.Element
    part: str

    @property
    def body_system(self) -> str:
        return part4_body_system(self.n) if self.part == "4" else "process"

    @property
    def url(self) -> str:
        return section_url(self.n)

    def verbatim(self) -> str:
        """Whole-section verbatim text (HEAD + all prose/tables flattened)."""
        return _text(self.el)


def iter_sections(xml_path: str | Path, part: str) -> Iterator[Section]:
    root = ET.parse(str(xml_path)).getroot()
    for div in root.iter("DIV8"):
        if div.get("TYPE") != "SECTION":
            continue
        n = (div.get("N") or "").strip()
        head = _text(div.find("HEAD"))
        if not n:
            continue
        yield Section(n=n, head=head, el=div, part=part)


# ── Table parsing ────────────────────────────────────────────────────────────
@dataclass
class Row:
    text: str
    css: str
    percent: int | None
    indented: bool


def _table_rows(table: ET.Element) -> list[Row]:
    """Flatten a 2-column rating table into (text, css, percent, indented) rows."""
    rows: list[Row] = []
    for tr in table.iter("TR"):
        cells = [c for c in list(tr) if c.tag in ("TD", "TH")]
        if not cells:
            continue
        text = _text(cells[0])
        css = (cells[0].get("class") or "")
        rating_text = _text(cells[1]) if len(cells) > 1 else ""
        m = _PERCENT_RE.match(rating_text)
        percent = int(m.group(1)) if m else None
        indented = "indent" in css
        if not text and percent is None:
            continue
        rows.append(Row(text=text, css=css, percent=percent, indented=indented))
    return rows


@dataclass
class DCBlock:
    dc: str
    name: str
    tiers: list[dict[str, Any]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)  # verbatim block lines
    notes: list[str] = field(default_factory=list)
    own: bool = False  # has tiers parsed from its OWN rows (not a shared formula)
    shared_formula: str = ""


@dataclass
class FormulaSeg:
    """An orphan 'General Rating Formula' block whose tiers are not owned by a
    single DC row (they apply to a range/list of diagnostic codes)."""

    title: str
    tiers: list[dict[str, Any]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    scope: tuple[int, int] | None = None  # DC range from a "(For diagnostic codes N to M)" note


_FORMULA_TITLE_RE = re.compile(r"^(general rating formula|rating formula|formula for)\b", re.I)
_SCOPE_RANGE_RE = re.compile(r"diagnostic codes?\s+(\d{4})\s+to\s+(\d{4})", re.I)
_CROSSREF_RE = re.compile(r"\b(rate under|rate as|evaluate under|rated under)\b", re.I)


def _parse_dc_table(rows: list[Row]) -> tuple[list[DCBlock], list[FormulaSeg]]:
    """DC-per-row schedule. Rows whose first cell begins with a 4-digit DC (at
    base indent) open a block; indented rows with a percent are that DC's tiers.
    Non-numeric indented rows are sticky lead-ins prepended to following tiers.

    Also captures 'General Rating Formula' segments — tier rows that precede a
    run of tier-less DC-header rows (e.g. §4.71a spine formula for DC 5235–5243).
    Those tiers are attached to the in-scope DCs by ``_apply_shared_formula``.
    """
    blocks: list[DCBlock] = []
    segs: list[FormulaSeg] = []
    cur: DCBlock | None = None
    fcur: FormulaSeg | None = None
    lead_in = ""

    def start_formula(title: str) -> None:
        nonlocal fcur, lead_in
        fcur = FormulaSeg(title=title, lines=[title] if title else [])
        segs.append(fcur)
        lead_in = ""

    for row in rows:
        dc_match = _DC_ROW_RE.match(row.text)
        is_dc_start = bool(dc_match) and not row.indented
        # A 'General Rating Formula' / 'Formula for …' heading starts an orphan
        # formula segment whose tiers apply to a range/list of DCs, not to the
        # single preceding DC row. Trigger only when the current DC has no tiers
        # of its own yet, so a DC mid-parse is never stranded.
        is_formula_title = (
            row.percent is None
            and bool(_FORMULA_TITLE_RE.match(row.text))
            and (cur is None or not cur.own)
        )

        if is_formula_title:
            cur = None
            start_formula(row.text)
            continue

        if is_dc_start:
            cur = DCBlock(dc=dc_match.group(1), name=dc_match.group(2).strip().rstrip(":").strip())
            cur.lines.append(row.text)
            blocks.append(cur)
            lead_in = ""
            if row.percent is not None:  # single-line DC with an inline rating
                cur.tiers.append({"percent": row.percent, "criteria": cur.name or row.text})
                cur.own = True
            continue

        # Non-DC, non-formula-title row.
        if row.text.lower().startswith("note"):
            if cur is not None:
                cur.notes.append(row.text)
                cur.lines.append(row.text)
            elif fcur is not None:
                fcur.lines.append(row.text)
            continue

        if row.percent is not None:
            criteria = f"{lead_in} {row.text}".strip() if lead_in else row.text
            if cur is not None:
                cur.tiers.append({"percent": row.percent, "criteria": criteria})
                cur.own = True
                cur.lines.append(row.text)
            else:
                if fcur is None:
                    start_formula("")
                fcur.tiers.append({"percent": row.percent, "criteria": criteria})
                fcur.lines.append(row.text)
        elif row.text:
            # empty-rating text = sticky lead-in for the tiers that follow
            lead_in = row.text
            if cur is not None:
                cur.lines.append(row.text)
            elif fcur is not None:
                fcur.lines.append(row.text)
                m = _SCOPE_RANGE_RE.search(row.text)
                if m and fcur.scope is None:
                    fcur.scope = (int(m.group(1)), int(m.group(2)))
    return blocks, segs


def _apply_shared_formula(blocks: list[DCBlock], segs: list[FormulaSeg]) -> list[FormulaSeg]:
    """Attach the primary 'General Rating Formula' tiers to the tier-less DCs it
    covers. Returns the formula segments NOT consumed (each → a process card).
    Never fabricates: applies only within an explicit DC scope range, or when
    every DC in the table is tier-less (a pure formula table with DC headers)."""
    primary = next((s for s in segs if s.tiers), None)
    if primary is None:
        return [s for s in segs if s.tiers]

    all_tierless = all(not b.own for b in blocks)
    applied = False
    for b in blocks:
        if b.own or b.tiers:
            continue
        if _CROSSREF_RE.search(" ".join(b.lines)):
            continue  # "Rate under DC …" — a cross-reference, not this formula's DC
        try:
            code = int(b.dc)
        except ValueError:
            continue
        if primary.scope is not None:
            in_scope = primary.scope[0] <= code <= primary.scope[1]
        else:
            in_scope = all_tierless
        if in_scope:
            b.tiers = list(primary.tiers)
            b.shared_formula = primary.title
            applied = True

    leftovers = [s for s in segs if s.tiers and not (applied and s is primary)]
    return leftovers


def _looks_like_dc_table(rows: list[Row]) -> bool:
    return any(_DC_ROW_RE.match(r.text) and not r.indented for r in rows)


def _shared_formula_tiers(rows: list[Row]) -> list[dict[str, Any]]:
    tiers: list[dict[str, Any]] = []
    for row in rows:
        if row.percent is not None and row.text:
            tiers.append({"percent": row.percent, "criteria": row.text})
    return tiers


def _preceding_dc_list(section: Section, table: ET.Element) -> list[tuple[str, str]]:
    """DC codes listed (FP/EXTRACT/P) between the PREVIOUS table and ``table``.

    Resets at every table boundary so a formula's DC list is not polluted by an
    earlier formula's list (e.g. §4.130: the mental DC list must not attach to
    the Eating Disorders formula). Does not descend into other TABLE subtrees."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(el: ET.Element) -> bool:
        for child in list(el):
            if child is table:
                return True
            if child.tag == "TABLE":
                found.clear()
                seen.clear()
                continue  # a table boundary — don't descend, reset the DC list
            line = _text(child)
            m = _DC_ROW_RE.match(line)
            if m and not _REMOVED_RE.search(line):
                dc = m.group(1)
                name = m.group(2).strip().rstrip(":").strip()
                if dc not in seen and len(line) <= 160 and name:
                    seen.add(dc)
                    found.append((dc, name))
            if walk(child):
                return True
        return False

    walk(section.el)
    return found


def _iter_tables(section: Section) -> Iterator[ET.Element]:
    for table in section.el.iter("TABLE"):
        yield table


def _table_caption(table: ET.Element) -> str:
    cap = table.find("CAPTION")
    return _text(cap) if cap is not None else ""


# ── Item builders ────────────────────────────────────────────────────────────
def _item(
    *,
    title: str,
    content: str,
    body_system: str | None,
    diagnostic_code: str | None,
    source: str,
    source_url: str,
    effective_date: date,
    content_kind: str,
    distill_kind: str,
    section_n: str,
    part: str,
    extra_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = dict(extra_data or {})
    data["distill"] = {
        "kind": distill_kind,
        "cfr_part": part,
        "section": section_n,
    }
    affects_advice = content_kind == "criteria"
    return {
        "title": title[:512],
        "content": content,
        "body_system": body_system,
        "diagnostic_code": diagnostic_code,
        "source": source[:255],
        "source_name": SOURCE_NAME,
        "source_url": source_url,
        "effective_date": effective_date.isoformat(),
        "data": data,
        "content_kind": content_kind,
        "affects_advice": affects_advice,
    }


def _rating_card_from_block(
    block: DCBlock, section: Section, effective_date: date, *, formula_caption: str = ""
) -> dict[str, Any]:
    # Deterministic verbatim content: DC header + (formula title) + each tier
    # rendered "<percent>%: <verbatim criterion>" + notes. Keeps the embedding
    # topical without paraphrasing any regulation text.
    lines = [f"{block.dc} {block.name}".strip() if block.name else f"DC {block.dc}"]
    caption = formula_caption or block.shared_formula
    if caption:
        lines.append(caption)
    for tier in block.tiers:
        lines.append(f"{tier['percent']}%: {tier['criteria']}")
    for note in block.notes:
        if note not in lines:
            lines.append(note)
    content = "\n".join(lines).strip()
    extra: dict[str, Any] = {"tiers": block.tiers}
    if block.notes:
        extra["notes"] = block.notes
    formula = formula_caption or block.shared_formula
    if formula:
        extra["formula"] = formula
    title = f"{block.dc} {block.name}".strip() if block.name else f"DC {block.dc}"
    return _item(
        title=title,
        content=content or title,
        body_system=section.body_system,
        diagnostic_code=block.dc,
        source=section_cite(section.n, block.dc),
        source_url=section.url,
        effective_date=effective_date,
        content_kind="criteria",
        distill_kind="rating_criteria",
        section_n=section.n,
        part=section.part,
        extra_data=extra,
    )


def _process_card(
    section: Section,
    effective_date: date,
    *,
    distill_kind: str,
    content: str | None = None,
    title_suffix: str = "",
) -> dict[str, Any]:
    title = (section.head or section_cite(section.n)).strip()
    if title_suffix:
        title = f"{title} — {title_suffix}"
    return _item(
        title=title,
        content=(content if content is not None else section.verbatim()) or title,
        body_system="presumptive" if distill_kind == "presumptive" else "process",
        diagnostic_code=None,
        source=section_cite(section.n),
        source_url=section.url,
        effective_date=effective_date,
        content_kind="explainer",
        distill_kind=distill_kind,
        section_n=section.n,
        part=section.part,
    )


# ── Part 4 ───────────────────────────────────────────────────────────────────
def distill_part4_section(section: Section, effective_date: date) -> list[dict[str, Any]]:
    tables = list(_iter_tables(section))
    rating_tables = [t for t in tables if _table_rows(t)]
    if not rating_tables:
        # No schedule table — a general Part 4 rule (§4.14, §4.25, §4.16, …).
        return [_process_card(section, effective_date, distill_kind="rule")]

    items: list[dict[str, Any]] = []
    produced_dc_card = False
    for table in rating_tables:
        rows = _table_rows(table)
        caption = _table_caption(table)
        if _looks_like_dc_table(rows):
            blocks, segs = _parse_dc_table(rows)
            leftover_formulas = _apply_shared_formula(blocks, segs)
            for block in blocks:
                if block.tiers:
                    items.append(_rating_card_from_block(block, section, effective_date))
                    produced_dc_card = True
                else:
                    # cross-reference-only DC ("Rate as …") — degrade to prose,
                    # never fabricate a tier.
                    content = "\n".join(block.lines).strip()
                    items.append(
                        _process_card(
                            section,
                            effective_date,
                            distill_kind="rating_ref",
                            content=content or f"{block.dc} {block.name}",
                            title_suffix=f"DC {block.dc} {block.name}".strip(),
                        )
                    )
            for seg in leftover_formulas:
                # A secondary formula (e.g. IVDS incapacitating-episodes) that is
                # an alternative rating method — emit verbatim, never fabricate a DC.
                items.append(
                    _process_card(
                        section,
                        effective_date,
                        distill_kind="rule",
                        content="\n".join(seg.lines).strip(),
                        title_suffix=seg.title or "rating formula",
                    )
                )
            continue

        # Non-DC table: try a shared 'General Rating Formula' with a DC list.
        tiers = _shared_formula_tiers(rows)
        dc_list = _preceding_dc_list(section, table)
        distinct = {t["percent"] for t in tiers}
        if len(distinct) >= 3 and dc_list:
            for dc, name in dc_list:
                block = DCBlock(dc=dc, name=name, tiers=list(tiers))
                block.lines = [f"{dc} {name}"]
                items.append(
                    _rating_card_from_block(block, section, effective_date, formula_caption=caption)
                )
                produced_dc_card = True
        else:
            # Irregular table — verbatim process card, no fabricated tiers.
            items.append(
                _process_card(
                    section,
                    effective_date,
                    distill_kind="rule",
                    content=_text(table),
                    title_suffix=caption or "rating table",
                )
            )

    if not produced_dc_card and not items:
        items.append(_process_card(section, effective_date, distill_kind="rule"))
    return items


def _max_ratings_ceilings() -> dict[str, int]:
    """VA max-rating ceiling per DC from the vendored CC0 dataset, if present.
    Lazy + degrade-to-empty so the distiller stays importable without the file."""
    try:
        from .store import load_max_ratings

        return {dc: int(row["max_rating"]) for dc, row in load_max_ratings().items()}
    except Exception:  # noqa: BLE001 — no dataset ⇒ guard is simply off
        return {}


def guard_over_ceiling(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Degrade any rating_criteria card whose top tier exceeds the VA max-rating
    dataset ceiling for its DC to a verbatim ``process`` card (drop the tiers).

    This mirrors the receiver's fail-closed ``validate_kb_max_ratings`` check so
    a structurally-parsed formula that VA caps lower for a specific DC (e.g. the
    seizure formula's 100% tier applied to petit-mal DC 8911, capped at 80%) is
    never emitted as a fabricated tier — the reg text is kept, the tiers are not.
    """
    ceilings = _max_ratings_ceilings()
    if not ceilings:
        return items
    out: list[dict[str, Any]] = []
    for it in items:
        if it.get("content_kind") != "criteria":
            out.append(it)
            continue
        dc = (it.get("diagnostic_code") or "").strip()
        tiers = (it.get("data") or {}).get("tiers") or []
        ceiling = ceilings.get(dc)
        try:
            card_max = max((int(t.get("percent", 0)) for t in tiers), default=0)
        except (TypeError, ValueError):
            card_max = 0
        if ceiling is not None and card_max > ceiling:
            data = dict(it.get("data") or {})
            dropped = data.pop("tiers", [])
            distill = dict(data.get("distill") or {})
            distill["kind"] = "rating_ref"
            distill["degraded"] = f"top tier {card_max}% exceeds VA DC {dc} ceiling {ceiling}%"
            distill["dropped_tiers"] = dropped
            data["distill"] = distill
            it = {
                **it,
                "content_kind": "explainer",
                "affects_advice": False,
                "body_system": "process",
                "diagnostic_code": None,
                "data": data,
            }
        out.append(it)
    return out


def distill_part4(xml_path: str | Path, effective_date: date = DEFAULT_EFFECTIVE_DATE) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for section in iter_sections(xml_path, part="4"):
        items.extend(distill_part4_section(section, effective_date))
    return guard_over_ceiling(items)


# ── Part 3 ───────────────────────────────────────────────────────────────────
def distill_part3(
    xml_path: str | Path,
    effective_date: date = DEFAULT_EFFECTIVE_DATE,
    *,
    process_sections: tuple[str, ...] = PART3_PROCESS_SECTIONS,
    presumptive_sections: tuple[str, ...] = PART3_PRESUMPTIVE_SECTIONS,
    all_sections: bool = False,
) -> list[dict[str, Any]]:
    process = set(process_sections)
    presumptive = set(presumptive_sections)
    items: list[dict[str, Any]] = []
    for section in iter_sections(xml_path, part="3"):
        if section.n in presumptive:
            items.append(_process_card(section, effective_date, distill_kind="presumptive"))
        elif all_sections or section.n in process:
            items.append(_process_card(section, effective_date, distill_kind="process"))
    return items


# ── Batch assembly ───────────────────────────────────────────────────────────
def chunk(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def build_batches(
    items: list[dict[str, Any]],
    *,
    batch_prefix: str,
    verified_as_of: date = DEFAULT_VERIFIED_AS_OF,
    chunk_size: int = 40,
    applied_by: str = "corpus-distiller",
) -> list[dict[str, Any]]:
    """Split distilled items into ``KBRefreshBatch``-shaped dicts (kind=rating_criteria)."""
    batches: list[dict[str, Any]] = []
    for idx, group in enumerate(chunk(items, chunk_size), start=1):
        batches.append(
            {
                "kind": "rating_criteria",
                "items": group,
                "source": dict(BATCH_SOURCE),
                "verified_as_of": verified_as_of.isoformat(),
                "batch_id": f"{batch_prefix}-{idx:03d}",
                "applied_by": applied_by,
            }
        )
    return batches


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in items:
        kind = ((it.get("data") or {}).get("distill") or {}).get("kind", "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    counts["_total"] = len(items)
    counts["_rating_criteria_cards"] = sum(1 for it in items if it["content_kind"] == "criteria")
    counts["_process_cards"] = sum(1 for it in items if it["content_kind"] == "explainer")
    return counts


# ── CLI ──────────────────────────────────────────────────────────────────────
def _default_prefix(part: str, verified_as_of: date) -> str:
    return f"bulk-38cfr-part{part}-{verified_as_of.isoformat()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Distill 38 CFR eCFR XML into KBRefreshBatch JSON.")
    ap.add_argument("--part4", type=Path, help="Path to 38cfr-part4 XML.")
    ap.add_argument("--part3", type=Path, help="Path to 38cfr-part3 XML.")
    ap.add_argument("--out-dir", type=Path, required=True, help="Directory for batch JSON output.")
    ap.add_argument("--effective-date", default=DEFAULT_EFFECTIVE_DATE.isoformat())
    ap.add_argument("--verified-as-of", default=DEFAULT_VERIFIED_AS_OF.isoformat())
    ap.add_argument("--chunk-size", type=int, default=40)
    ap.add_argument("--part3-all", action="store_true", help="Distill all Part 3 sections.")
    args = ap.parse_args(argv)

    eff = date.fromisoformat(args.effective_date)
    voa = date.fromisoformat(args.verified_as_of)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    grand: dict[str, dict[str, int]] = {}
    if args.part4:
        items = distill_part4(args.part4, eff)
        batches = build_batches(items, batch_prefix=_default_prefix("4", voa), verified_as_of=voa, chunk_size=args.chunk_size)
        for b in batches:
            (args.out_dir / f"{b['batch_id']}.json").write_text(json.dumps(b, indent=2, ensure_ascii=False))
        grand["part4"] = summarize(items)
    if args.part3:
        items = distill_part3(args.part3, eff, all_sections=args.part3_all)
        batches = build_batches(items, batch_prefix=_default_prefix("3", voa), verified_as_of=voa, chunk_size=args.chunk_size)
        for b in batches:
            (args.out_dir / f"{b['batch_id']}.json").write_text(json.dumps(b, indent=2, ensure_ascii=False))
        grand["part3"] = summarize(items)

    print(json.dumps({"out_dir": str(args.out_dir), "summary": grand}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
