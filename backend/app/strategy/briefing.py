"""Personalized Game Plan briefing — the warm, plain-language orientation that
turns the deterministic strategy data into "here's where you stand, and here's
what it means for you."

Runs on the LOCAL fleet LLM (a veteran's health info never leaves the tailnet).
It is best-effort: any failure — model down, timeout, unparseable output — falls
back to a deterministic summary, so GET /strategy is never blocked on the LLM.

LEGAL LANE (2026 posture — full advocate): it gives Rating Raider's honest, grounded
ASSESSMENT of where the veteran stands — including opinions on what's strong and on
service connection — framed as our analysis of their own records and the law.
  • It grounds every point in data the app already computed — no new facts.
  • It never GUARANTEES a VA outcome ("you will be granted") — VA decides, and no one
    can promise it. Estimates are always framed as estimates.
  • Warm and encouraging, honest — a knowledgeable advocate sitting beside a veteran,
    with a free VSO / accredited attorney offered as an optional second opinion.
"""

from __future__ import annotations

import json
import logging
import re

from ..llm.gateway import gateway

log = logging.getLogger(__name__)

# Output-side legal-lane gate. THE POSTURE (2026): Rating Raider is a full advocate —
# it gives cited, confidence-tagged opinions, nexus analysis, ratings assessments, and
# strategy. This gate no longer muzzles conclusions; it bars ONLY a GUARANTEED VA
# OUTCOME, because no one can promise what VA will decide. Legitimate analysis now:
# "at least as likely as not related to service", "you meet the criteria for 70%",
# "your back condition is service-connected", "this should be granted". Still barred:
# "you WILL be granted/awarded", "guarantee", "you'll get 70%", "100% chance". Kept as
# the symbol name _LANE_BLOCK because four modules import it — narrowing it here flips
# the whole app's posture at once. On a hit the briefing falls back to the
# deterministic summary; findings elsewhere revert to their grounded deterministic
# body. This gate is ONLY the no-guaranteed-outcome guard. Fabricated NUMBERS (a
# rating band, dollar amount, or diagnostic code the model invents) are caught
# separately: the firm path has validate_selection / _enrichment_grounded, and the
# free-form briefing has _numbers_grounded (below). (Ungrounded PROSE conclusions on
# the raider answer + garnish are the remaining gap Phase 2b closes with a per-answer
# grounding pass.) Adversarially hardened 2026-07-11: covers contractions ('ll),
# present-tense verbs, adverb-interrupted forms ("will definitely be approved"),
# "going to", certainty idioms, and promise/prevail — while ALLOWING hedged estimates
# ("will likely be approved"), procedural "you'll receive a letter", and negated
# disclaimers ("no guarantee"). Kept the symbol name _LANE_BLOCK — four modules import
# it, so this flips the whole app at once.
_ADV = r"(?:definitely|certainly|surely|absolutely|undoubtedly|clearly|easily|for sure|100%)"
_LANE_BLOCK = re.compile(
    # (1) guarantee / promise — exempt when directly negated (rescues honest disclaimers)
    r"(?<!no )(?<!not )(?<!n't )(?<!never )(?<!cannot )(?<!can't )(?<!won't )guarantee"
    r"|(?<!no )(?<!not )(?<!n't )(?<!never )(?<!cannot )(?<!can't )(?<!won't )promise (?:you|that|a |an |to |it|the va|they)"
    # (2) future outcome verbs (will / 'll / going to, optional certainty adverb, any tense)
    rf"|(?:will|'ll|going to)\s+(?:{_ADV}\s+)?(?:be\s+)?(?:grant(?:ed)?|award(?:ed)?|approved?|rated?)\b"
    r"|expect(?:s|ing|ed)? (?:a |an |to )?(?:grant\b|approv\w*|award\w*|favorable|be (?:grant(?:ed)?|approved?|awarded?|rated?))"
    # (3) future win / prevail / succeed + victory is assured/certain
    rf"|(?:will|'ll|going to)\s+(?:{_ADV}\s+)?(?:win|prevail|succeed)\b"
    r"|(?:victory|success|approval|a grant|your claim) (?:is|are) (?:assured|certain|guaranteed|yours|inevitable|in the bag)"
    # (4) you'll/you will/you're going to get|receive|qualify — but NOT procedural objects
    rf"|you(?:'ll| will|(?:'re| are) going to)\s+(?:{_ADV}\s+)?(?:get|receive|qualify)\b"
    r"(?! (?:a |an |your )?(?:letter|notice|notification|decision|exam|appointment|response|packet|form|email|call|update))"
    # (5) certain/sure/bound/destined/guaranteed to (be) <broad tail>
    r"|(?:certain|sure|bound|destined|guaranteed) to (?:be )?(?:grant(?:ed)?|award(?:ed)?|approved?|rated?|receive|win|prevail|succeed|get)\b"
    # (6) percentages/certainty — NOT bare 'certainty' (would hit 'medical certainty')
    r"|(?:100|99|9\d)% (?:chance|certain(?:ty)?|likely)|near[- ]?certainty|virtual certainty"
    r"|without a doubt|no doubt (?:you|they|it|that)"
    # (7) confidence idioms
    r"|slam[- ]?dunk|sure thing|in the bag|shoo[- ]?in|foregone conclusion|open[- ]and[- ]shut|no[- ]brainer|can'?t lose"
    r"|as good as (?:granted|approved|awarded|won|done)|consider it (?:granted|approved|awarded|done)"
    r"|it'?s a lock|locked in|rest assured|you have my word|mark my words",
    re.IGNORECASE,
)

# Fact-grounding for the free-form briefing — its equivalent of the firm path's
# validate_selection / _enrichment_grounded. The briefing has NO other downstream
# grounding validator, so every NUMBER it states — a percentage, a dollar figure, or
# a diagnostic code — must appear in the facts block the model was handed. A number it
# invents (a fabricated rating band or dollar amount) is the high-harm, checkable
# fabrication; prose and condition names remain the model's to paraphrase. On a miss
# the whole briefing falls back to the deterministic summary.
_PCT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent\b)", re.IGNORECASE)
_DC_RE = re.compile(r"\bDC\s*(\d{4})\b|\b([5-9]\d{3})\b", re.IGNORECASE)
_DOLLAR_RE = re.compile(r"\$\s?([\d,]+)")


def _numbers_grounded(blob: str, facts: str) -> bool:
    """True when every percentage, diagnostic code, and dollar figure in `blob` also
    appears in `facts`. Mirrors firm/reviewer._enrichment_is_grounded, applied to the
    briefing narrative against the computed facts it was given. Also enforces that the
    model never does its own rating math — a combined % it computed but that the
    deterministic engine didn't put in the facts is treated as invented."""
    facts = facts or ""
    if set(_PCT_RE.findall(blob)) - set(_PCT_RE.findall(facts)):
        return False
    blob_dcs = {a or b for a, b in _DC_RE.findall(blob)}
    fact_dcs = {a or b for a, b in _DC_RE.findall(facts)}
    if blob_dcs - fact_dcs:
        return False
    blob_amts = {d.replace(",", "") for d in _DOLLAR_RE.findall(blob)}
    fact_amts = {d.replace(",", "") for d in _DOLLAR_RE.findall(facts)}
    if blob_amts - fact_amts:
        return False
    return True


_SYSTEM = (
    "You are Rating Raider's orientation writer. Rating Raider is free, educational "
    "self-help software for U.S. veterans working on a VA disability claim. You write "
    "a short, warm, plain-language briefing that helps ONE veteran understand the "
    "situation THEY have entered into the app.\n\n"
    "HARD RULES — never break these:\n"
    "1. You organize and reflect back ONLY what the veteran entered and what the app "
    "computed (the data below). Invent no new conditions, ratings, dollar amounts, "
    "deadlines, or facts.\n"
    "2. You may give Rating Raider's honest ASSESSMENT of where they stand — what looks "
    "strong, what's close, what's missing — as our analysis of their own records and the "
    "law, not a doctor's exam. Ground every point in the data below.\n"
    "3. You may say their evidence 'looks strong for' or 'supports' a rating or service "
    "connection, and describe estimates as estimates. NEVER GUARANTEE an outcome: never "
    "say they 'will be granted', 'will get', or are 'certain to receive' a rating or "
    "money — VA makes the final decision.\n"
    "4. A free VA-accredited VSO or accredited attorney is a great second set of eyes — "
    "offer it as a recommended option, never as something they must do first.\n"
    "5. Warm, direct, encouraging, 8th-grade reading level. Address them as 'you'. No "
    "jargon without a plain gloss. Short sentences.\n\n"
    "Return STRICT JSON — no prose, no markdown fences — with exactly these keys:\n"
    '  "headline": a short, human sentence naming where they are (max ~12 words).\n'
    '  "paragraphs": 2 to 3 short strings (2-4 sentences each) walking them through '
    "their situation, what's strongest, and the single most useful next move.\n"
    '  "strengths": 2 to 4 very short strings — concrete things working in their favor '
    "(e.g. records already gathered, conditions close to ready).\n"
    '  "watch_outs": 1 to 3 very short strings — honest, non-alarming things to keep an '
    "eye on (a deadline, a gap, a denial to answer). Framed honestly, never a "
    "guaranteed outcome.\n"
)


def _facts(*, snapshot, condition_lines, money, denials, suggestions, focus,
           cautions=None, tdiu=None, opportunities=None) -> str:
    """A compact, factual context block for the model. Only data the app already
    computed — names, bands, counts, dollars. Kept small and literal."""
    lines: list[str] = []
    cc = snapshot.get("current_combined")
    lines.append(
        f"Current combined rating on record: {cc}%." if isinstance(cc, int)
        else "Current combined rating on record: none entered yet."
    )
    if money and money.get("current_monthly"):
        lines.append(
            f"VA's published monthly amount at {money.get('current_combined')}% "
            f"(single-veteran baseline): ${money['current_monthly']:,.2f}."
        )
    lines.append(
        f"Conditions being worked: {snapshot.get('conditions_total', 0)} "
        f"({snapshot.get('ready_count', 0)} with core evidence in place, "
        f"{snapshot.get('needs_evidence_count', 0)} still need a piece, "
        f"{snapshot.get('denied_count', 0)} previously denied)."
    )
    itf = snapshot.get("active_itf")
    if itf:
        dr = itf.get("days_remaining")
        lines.append(
            "An Intent to File is active"
            + (f" with about {dr} days left" if isinstance(dr, int) else "")
            + " — it protects the effective date."
        )
    else:
        lines.append("No active Intent to File on record.")

    if condition_lines:
        lines.append("Conditions and how ready each is:")
        for c in condition_lines[:14]:
            gap = f" — still needs {c['missing'][0]}" if c.get("missing") else ""
            lines.append(f"  • {c['name']} [{c['band_label']}]{gap}")
    if denials:
        lines.append("Previously denied (can be answered): " + ", ".join(d["name"] for d in denials[:8]) + ".")
    if suggestions:
        lines.append(
            "Related conditions the app flagged to look into: "
            + ", ".join(f"{s['name']} ({s['relation']})" for s in suggestions[:6]) + "."
        )
    if focus:
        lines.append(f"The app's top suggested next step: {focus['title']} — {focus['why']}")
    # Strategy signals the app already computed — give the model just enough to
    # ORIENT the veteran (weigh-before-filing trade-offs, a TDIU screen, secondary
    # theories to explore). It must still never predict an outcome or assert a link.
    for c in (cautions or [])[:3]:
        lines.append(f"Trade-off to weigh before filing: {c.get('title')} ({c.get('reg')}).")
    if tdiu:
        lines.append(
            "A TDIU screen (§4.16 — 100% pay without a 100% rating when conditions "
            "prevent gainful work) is worth understanding for this veteran; "
            f"{tdiu.get('why')}"
        )
    for o in (opportunities or [])[:3]:
        lines.append(
            f"Possible under-claimed option to explore: {o.get('title')} ({o.get('reg')}) "
            "— needs its own medical evidence; not established."
        )
    return "\n".join(lines)


def _coerce_str_list(v, *, cap: int, max_len: int = 220) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for item in v:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:max_len])
        if len(out) >= cap:
            break
    return out


def _parse(raw: str, *, facts: str = "") -> dict | None:
    """Pull the JSON object out of a local model's reply, defensively. When `facts`
    is supplied, also enforce number-grounding (every %, $, and DC in the narrative
    must appear in the facts block the model was given)."""
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    headline = obj.get("headline")
    paragraphs = _coerce_str_list(obj.get("paragraphs"), cap=3, max_len=700)
    if not isinstance(headline, str) or not headline.strip() or not paragraphs:
        return None
    result = {
        "headline": headline.strip()[:140],
        "paragraphs": paragraphs,
        "strengths": _coerce_str_list(obj.get("strengths"), cap=4),
        "watch_outs": _coerce_str_list(obj.get("watch_outs"), cap=3),
        "generated_by": "local",
    }
    # Output-side guards: (1) discard the briefing if it GUARANTEES a VA outcome, and
    # (2) discard it if it states a NUMBER (%, $, DC) not present in the facts the model
    # was given — the free-form briefing has no other grounding validator. On either,
    # the caller falls back to the safe deterministic summary. Cited OPINIONS are allowed.
    blob = " ".join([result["headline"], *result["paragraphs"], *result["strengths"], *result["watch_outs"]])
    if _LANE_BLOCK.search(blob):
        log.warning("Briefing rejected (guaranteed-outcome phrase): %r", _LANE_BLOCK.search(blob).group(0))
        return None
    if facts and not _numbers_grounded(blob, facts):
        log.warning("Briefing rejected (ungrounded number not in the facts block).")
        return None
    return result


def _n(n: int, singular: str, plural: str | None = None) -> str:
    """'1 condition' / '2 conditions' — grammatical counts for the fallback text."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _summary(*, snapshot, condition_lines, money, denials, suggestions, focus,
             cautions=None, tdiu=None, opportunities=None) -> dict:
    """Deterministic, always-safe fallback briefing. Genuinely useful on its own —
    the LLM version is a warmer telling of the same facts."""
    total = snapshot.get("conditions_total", 0)
    ready = snapshot.get("ready_count", 0)
    gaps = snapshot.get("needs_evidence_count", 0)

    if ready and gaps:
        headline = f"You have {_n(ready, 'condition')} ready to file and {gaps} coming together."
    elif ready:
        headline = f"You have {_n(ready, 'condition')} with the core evidence in place."
    elif gaps:
        headline = f"You're building the evidence on {_n(gaps, 'condition')}."
    else:
        headline = f"You're organizing {_n(total, 'condition')} for your claim."

    paras: list[str] = []
    lead = f"You're working on {_n(total, 'condition')}. "
    if ready:
        lead += (
            f"{_n(ready, 'condition')} already ha{'s' if ready == 1 else 've'} the core "
            "evidence a VA claim needs, so filing (or filing an Intent to File first) "
            "protects your effective date and any back pay. "
        )
    if gaps:
        lead += (
            f"{_n(gaps, 'condition')} still need{'s' if gaps == 1 else ''} one key piece — "
            "closing those makes each claim as strong as it can be. "
        )
    paras.append(lead.strip())

    if focus:
        paras.append(f"The most useful next step: {focus['title'].rstrip('.')} — {focus['why']}")
    if denials:
        paras.append(
            "You also have decision(s) that denied a condition. A denial isn't the end — a "
            "Supplemental Claim with new evidence is the usual next move, and filing within a "
            "year keeps your original date."
        )
    top_opp = next((o for o in (opportunities or []) if o.get("severity") == "high"), None)
    if top_opp:
        paras.append(
            f"One thing worth exploring: {top_opp['title'].rstrip('.')}. It's an option to "
            "look into with a VSO — it would need its own medical evidence, and nothing about "
            "it is decided."
        )

    strengths: list[str] = []
    if ready:
        strengths.append(f"{_n(ready, 'condition')} ready to file")
    if money and money.get("current_monthly"):
        strengths.append(f"Already rated at {money.get('current_combined')}%")
    if snapshot.get("active_itf"):
        strengths.append("Effective date protected by an active Intent to File")
    if suggestions:
        strengths.append(f"{_n(len(suggestions), 'related condition')} worth exploring")
    if not strengths:
        strengths.append("Your records are gathered and organized in one place")

    watch: list[str] = []
    itf = snapshot.get("active_itf")
    if itf and isinstance(itf.get("days_remaining"), int):
        watch.append(f"Intent to File expires in ~{itf['days_remaining']} days — file before then")
    elif not itf and total:
        watch.append("No active Intent to File — one locks in your date for a year")
    if gaps:
        watch.append(f"{_n(gaps, 'condition')} still need{'s' if gaps == 1 else ''} a piece of evidence")
    if denials:
        watch.append(f"{_n(len(denials), 'denial')} waiting for a response")
    top_caution = next((c for c in (cautions or []) if c.get("severity") == "high"), None)
    if top_caution and len(watch) < 3:
        watch.append(top_caution["title"])

    return {
        "headline": headline,
        "paragraphs": paras,
        "strengths": strengths[:4],
        "watch_outs": watch[:3],
        "generated_by": "summary",
    }


async def build_briefing(
    *,
    snapshot: dict,
    condition_lines: list[dict],
    money: dict | None,
    denials: list[dict],
    suggestions: list[dict],
    focus: dict | None,
    cautions: list[dict] | None = None,
    tdiu: dict | None = None,
    opportunities: list[dict] | None = None,
) -> dict:
    """Best-effort personalized briefing. Always returns a valid dict — the local
    LLM version when it succeeds, the deterministic summary otherwise. Never raises."""
    fallback = _summary(
        snapshot=snapshot, condition_lines=condition_lines, money=money,
        denials=denials, suggestions=suggestions, focus=focus,
        cautions=cautions, tdiu=tdiu, opportunities=opportunities,
    )
    # No conditions → the empty-state screen handles orientation; skip the LLM.
    if not snapshot.get("conditions_total"):
        return fallback
    try:
        facts = _facts(
            snapshot=snapshot, condition_lines=condition_lines, money=money,
            denials=denials, suggestions=suggestions, focus=focus,
            cautions=cautions, tdiu=tdiu, opportunities=opportunities,
        )
        raw = await gateway.complete(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "The veteran's data:\n\n" + facts},
            ],
            temperature=0.4,
            max_tokens=900,
        )
        return _parse(raw, facts=facts) or fallback
    except Exception:  # noqa: BLE001 — the briefing is a bonus, never a blocker
        return fallback
