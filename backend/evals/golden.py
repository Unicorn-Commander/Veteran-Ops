"""Run the deterministic, de-identified golden release evaluation suite."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

from app.analysis.case import alias_key, aggregate_mentions
from app.analysis.gaps import analyze_gaps
from app.analysis.mapping import validate_selection
from app.analysis.presumptives import match_presumptives
from app.deadlines import compute_deadlines
from app.evidence_rationale import (
    citation_quote_from_chunk,
    evidence_query_terms,
    page_for_char_offset,
    rank_chunk_rows,
)
from app.intake.crossread import compare_page
from app.rating.engine import RatingEntry, combined_rating

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden_cases.json"
REQUIRED_DOMAINS = frozenset(
    {
        "ocr",
        "evidence",
        "rating",
        "deadline",
        "citation",
        "abstention",
        "presumptive",
        "alias",
    }
)


def _evaluate(case: dict[str, Any]) -> Any:
    domain = case["domain"]
    values = case["input"]

    if domain == "ocr":
        result = compare_page(values["page"], values["ocr"], values["vision"])
        return {
            "flagged": result.flagged,
            "confidence": round(result.ocr_confidence, 4),
            "disputed_fields": [delta["field"] for delta in result.deltas],
        }

    if domain == "evidence":
        gaps = analyze_gaps(values["condition"], values["evidence"])
        return {
            "gap_kinds": [gap["kind"] for gap in gaps],
            "all_gaps_cited": bool(gaps) and all(bool(gap.get("source")) for gap in gaps),
        }

    if domain == "rating":
        entries = [RatingEntry(**entry) for entry in values["entries"]]
        result = combined_rating(entries)
        return {
            "combined": result.combined,
            "raw": result.raw,
            "bilateral_factor_applied": result.bilateral_factor_applied,
            "bilateral_value": result.bilateral_value,
        }

    if domain == "deadline":
        deadlines = compute_deadlines(
            itf_records=values["itf_records"],
            decodes=values["decodes"],
            dependents=values["dependents"],
            today=date.fromisoformat(values["today"]),
        )
        return [
            {
                "kind": item.kind,
                "due_date": item.due_date,
                "days_left": item.days_left,
                "urgency": item.urgency,
            }
            for item in deadlines
        ]

    if domain == "citation":
        terms = evidence_query_terms(values["condition_name"], values["kind"])
        ranked = rank_chunk_rows(values["chunks"], terms, k=1)
        if not ranked:
            return None
        chunk = ranked[0]
        return {
            "chunk_index": chunk["chunk_index"],
            "page": page_for_char_offset(values["page_offsets"], chunk["char_start"]),
            "quote": citation_quote_from_chunk(chunk["content"]),
        }

    if domain == "abstention":
        card_index, percent, rationale = validate_selection(values["answer"], values["cards"])
        return {
            "card_index": card_index,
            "suggested_tier_percent": percent,
            "rationale": rationale,
        }

    if domain == "presumptive":
        matches = match_presumptives(
            values.get("profile"),
            values.get("cards") or [],
            today=date.fromisoformat(values["today"]) if values.get("today") else None,
            condition_names=values.get("condition_names"),
        )
        return {
            "programs": sorted({m["program"] for m in matches}),
            "pow_conditions": next(
                (list(m["conditions"]) for m in matches if m["program"] == "pow"),
                [],
            ),
        }

    if domain == "alias":
        # Pure alias-key collapse — no documents/DB needed for the key map.
        keys = sorted({alias_key(n) for n in values.get("names") or [] if alias_key(n)})
        # Optional document-shaped aggregation path for mention counts.
        if values.get("documents"):
            class _Doc:
                def __init__(self, doc_id: str, mentions: list[dict]):
                    self.id = doc_id
                    self.extracted = {"conditions_mentioned": mentions}

            docs = [
                _Doc(d["id"], d.get("mentions") or [])
                for d in values["documents"]
            ]
            agg = aggregate_mentions(docs)
            groups = [
                {
                    "name": row["name"],
                    "count": row["count"],
                    "alias_count": len(row.get("aliases") or []),
                }
                for row in agg
            ]
            groups.sort(key=lambda g: (-int(g["count"]), str(g["name"])))
            return {"keys": keys, "groups": groups}
        return {"keys": keys}

    raise ValueError(f"unknown golden evaluation domain: {domain}")


def run_golden(fixture_path: Path = FIXTURE_PATH) -> dict[str, Any]:
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if payload.get("deidentified") is not True:
        raise ValueError("golden fixtures must be marked deidentified")

    cases = payload.get("cases") or []
    domains = {case.get("domain") for case in cases}
    if domains != REQUIRED_DOMAINS:
        missing = sorted(REQUIRED_DOMAINS - domains)
        unexpected = sorted(domains - REQUIRED_DOMAINS)
        raise ValueError(f"golden domains mismatch; missing={missing}, unexpected={unexpected}")

    case_ids = [case.get("id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("golden case ids must be unique")

    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            actual = _evaluate(case)
            passed = actual == case["expected"]
            error = None
        except Exception as exc:  # The report must identify a broken evaluator.
            actual = None
            passed = False
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "id": case["id"],
                "domain": case["domain"],
                "passed": passed,
                "expected": case["expected"],
                "actual": actual,
                "error": error,
            }
        )

    passed_count = sum(result["passed"] for result in results)
    return {
        "ok": passed_count == len(results),
        "version": payload["version"],
        "passed": passed_count,
        "total": len(results),
        "failures": [result["id"] for result in results if not result["passed"]],
        "results": results,
    }


def main() -> int:
    report = run_golden()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
