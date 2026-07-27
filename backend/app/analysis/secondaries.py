"""Secondary-condition suggestions — deterministic keyword matching against the
KB secondary map (38 CFR §3.310 recognized patterns). The LLM may only add a
short personalized garnish sentence per suggestion at the router layer; the
match set itself is pure rules.
"""

from __future__ import annotations

SECONDARY_SOURCE = "38 CFR §3.310 (see rationale)"


def match_secondaries(names: list[str], secondary_map: list[dict]) -> list[dict]:
    """Match claimed/granted condition names against primary_keywords.

    names: the user's condition names (e.g. ["PTSD", "lumbar strain"]).
    secondary_map: load_secondary_map() output.

    Returns deduped suggestions:
      {primary, secondary, rationale, dbq, source}
    A suggestion is skipped when the suggested secondary is already one of the
    user's conditions (case-insensitive substring either way).
    """
    lowered = [(n, (n or "").lower()) for n in names or [] if (n or "").strip()]
    existing = [n_l for _, n_l in lowered]

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entry in secondary_map or []:
        keywords = [str(k).lower() for k in entry.get("primary_keywords") or []]
        for name, name_l in lowered:
            if not any(kw in name_l for kw in keywords):
                continue
            for sec in entry.get("secondaries") or []:
                sec_name = str(sec.get("condition") or "")
                sec_l = sec_name.lower()
                # Already claimed? (either direction of containment)
                if any(sec_l in ex or ex in sec_l for ex in existing if ex):
                    continue
                key = (name_l, sec_l)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "primary": name,
                        "secondary": sec_name,
                        "rationale": str(sec.get("rationale") or ""),
                        "dbq": sec.get("dbq"),
                        "source": SECONDARY_SOURCE,
                    }
                )
            break  # one map entry matches this name at most once
    return out
