"""CWO agent: tool registry integrity, the legal-lane final guard, and the PII
model-tier guard — the three things that must never regress."""
from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.raider import tools as rtools
from app.raider.agent import _lane_ok, bound_history


def test_bound_history_keeps_recent_within_char_budget():
    """Token-budget guard: long histories drop the oldest turns, never the latest."""
    history = [
        {"role": "user", "content": "old " * 200},
        {"role": "assistant", "content": "reply " * 200},
        {"role": "user", "content": "middle " * 200},
        {"role": "assistant", "content": "more " * 200},
        {"role": "user", "content": "latest question about my claim"},
    ]
    window = bound_history(history, max_messages=10, max_chars=400, max_message_chars=200)
    assert window
    assert window[-1]["content"].startswith("latest")
    assert sum(len(m["content"]) for m in window) <= 400
    # Individual messages are truncated when over max_message_chars.
    long_one = [{"role": "user", "content": "x" * 5000}]
    short = bound_history(long_one, max_message_chars=100)
    assert len(short) == 1
    assert len(short[0]["content"]) <= 100
    assert short[0]["content"].endswith("…")


def test_bound_history_respects_message_cap():
    history = [{"role": "user", "content": f"m{i}"} for i in range(40)]
    window = bound_history(history, max_messages=5, max_chars=100_000)
    assert len(window) == 5
    assert window[0]["content"] == "m35"
    assert window[-1]["content"] == "m39"


def test_tool_specs_are_valid_and_complete():
    specs = rtools.openai_tool_specs()
    assert len(specs) == len(rtools.TOOLS) >= 10
    for s in specs:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
    json.dumps(specs)  # must serialize for the chat API


def test_grounding_tools_that_read_the_record_are_marked_pii():
    # Any tool that returns the veteran's OWN record must be PII-marked so the agent
    # keeps that turn on the local model.
    for name in ("get_my_situation", "run_deep_dive", "check_readiness", "list_deadlines"):
        assert rtools.tool_touches_pii(name), f"{name} reads the record and must be PII-marked"
    # Public-corpus / static tools are not PII.
    for name in ("search_va_rulebook", "preview_form", "list_workflows"):
        assert not rtools.tool_touches_pii(name)


def test_model_tier_pii_guard_forces_local():
    s = Settings(llm_model="local-qwen", reasoning_model="frontier-gpt", privacy_mode=True)
    # Reasoning over findings/CFR (no PII) may use the bigger tier...
    assert s.model_for(tier="reasoning", touches_pii=False) == "frontier-gpt"
    # ...but a PII-touching call is forced back to the local model.
    assert s.model_for(tier="reasoning", touches_pii=True) == "local-qwen"
    assert s.model_for(tier="default") == "local-qwen"
    # Explicit consent lets PII use the tier (only when the operator sets it).
    s2 = Settings(llm_model="local-qwen", reasoning_model="frontier-gpt", privacy_mode=False)
    assert s2.model_for(tier="reasoning", touches_pii=True) == "frontier-gpt"


def test_lane_guard_detects_promissory_answers():
    bad = "Based on your record you will be granted a 70% rating and will receive back pay."
    assert not _lane_ok(bad)  # guaranteed outcome -> triggers a revision pass
    good = ("Your record shows the 70% criteria (occupational and social impairment in "
            "most areas) are at least as likely as not met; VA makes the final call.")
    assert _lane_ok(good)  # cited opinion — now allowed under the full-advocate posture


@pytest.mark.asyncio
async def test_run_tool_never_raises_on_unknown():
    class _Ctx:  # minimal
        db = None
        uid = "x"
        dossier = None
    out = await rtools.run_tool("does_not_exist", {}, _Ctx())
    assert "error" in out
