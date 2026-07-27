"""Adversarial hardening of the legal-lane gate + briefing fact-grounding (from the
Phase-2a review). The gate must catch guarantee phrasings the naive regex missed
(contractions, present-tense verbs, adverb-interrupts, idioms, promise/prevail) while
ALLOWING hedged estimates, negated disclaimers, and procedural 'you'll receive a
letter'. The free-form briefing must reject any NUMBER not present in its facts."""

from __future__ import annotations

import json

import pytest

from app.strategy.briefing import _LANE_BLOCK, _numbers_grounded, _parse


def _blocked(t: str) -> bool:
    return bool(_LANE_BLOCK.search(t))


@pytest.mark.parametrize("phrase", [
    "you'll be approved",                        # contraction
    "you'll be granted service connection",
    "the VA will grant your claim",              # present-tense verb
    "the VA will approve your claim",
    "the VA will award you 70%",
    "you will definitely be approved",           # adverb-interrupt
    "you will surely be granted",
    "you're going to be approved",               # going-to future
    "you are going to get 70%",
    "certain to be rated at 70%",                # broadened certain-to tail
    "sure to be approved",
    "this is a slam dunk",                       # idioms
    "it's a lock",
    "in the bag",
    "you'll prevail",                            # win/prevail
    "I promise you an approval",                 # promise family
    "victory is assured",
    "expect a grant",
])
def test_hardened_gate_blocks_previously_leaking_guarantees(phrase):
    assert _blocked(phrase), f"guarantee leaked past the gate: {phrase!r}"


@pytest.mark.parametrize("phrase", [
    "at least as likely as not related to service",   # the nexus standard
    "your evidence looks strong for a 70% rating",
    "this will likely be approved",                   # HEDGED estimate — allowed
    "you may qualify for an increase",
    "your back condition is service-connected",
    "you meet the criteria for 70%",
    "we can't guarantee an outcome",                  # negated disclaimer
    "there is no guarantee here",
    "you'll receive a decision letter",               # procedural — allowed
    "you will receive a notice about your C&P exam",
    "reasonable degree of medical certainty",         # nexus language, not a promise
])
def test_hardened_gate_allows_opinions_hedges_disclaimers_procedural(phrase):
    assert not _blocked(phrase), f"legitimate phrase wrongly blocked: {phrase!r}"


# ── briefing number-grounding ────────────────────────────────────────────────


def test_numbers_grounded_accepts_when_all_numbers_in_facts():
    facts = "Current combined rating on record: 60%. Monthly amount: $1,361.88. DC 5237."
    assert _numbers_grounded("You're at 60% now, about $1,361.88/mo under DC 5237.", facts)


def test_numbers_grounded_rejects_invented_percent():
    facts = "Current combined rating on record: 60%."
    assert not _numbers_grounded("Your evidence looks strong for 40%.", facts)


def test_numbers_grounded_rejects_invented_dollars_and_dc():
    facts = "Current combined rating: 60%."
    assert not _numbers_grounded("You could receive $3,500 per month.", facts)
    assert not _numbers_grounded("This falls under DC 9411.", facts)


def test_parse_rejects_ungrounded_number_when_facts_given():
    raw = json.dumps({
        "headline": "Where you stand",
        "paragraphs": ["Your lumbar strain looks strong for 40%."],   # 40% NOT in facts
        "strengths": ["records gathered"], "watch_outs": ["a deadline"],
    })
    facts = "Current combined rating on record: 60%."
    assert _parse(raw, facts=facts) is None          # ungrounded 40% → fall back to summary
    assert _parse(raw) is not None                   # no facts supplied → grounding skipped


# ── raider closing-answer grounding ──────────────────────────────────────────

from app.raider.agent import _answer_grounded  # noqa: E402


def test_answer_grounded_accepts_numbers_present_in_context():
    messages = [
        {"role": "system", "content": "You help veterans."},
        {"role": "tool", "content": '{"current_combined": 60, "monthly": "$1,361.88", "dc": "5237"}'},
    ]
    # the answer formats the same numbers with %/$/DC the raw JSON lacks — still grounded
    assert _answer_grounded("You're at 60% (DC 5237), about $1,361.88/mo.", messages)


def test_answer_grounded_rejects_fabricated_numbers():
    messages = [{"role": "tool", "content": '{"current_combined": 60}'}]
    assert not _answer_grounded("Your evidence supports 90%.", messages)   # 90 invented
    assert not _answer_grounded("This is DC 9411.", messages)             # 9411 invented
    assert not _answer_grounded("You could get $4,000/mo.", messages)     # 4000 invented


def test_answer_grounded_ignores_prose_without_numbers():
    messages = [{"role": "tool", "content": "{}"}]
    assert _answer_grounded(
        "Your back condition is at least as likely as not related to service.", messages)
