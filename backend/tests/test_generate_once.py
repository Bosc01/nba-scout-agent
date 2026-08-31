"""Test 8: _generate_once against a stubbed Anthropic client.

Seven tool_use blocks arrive at once: exactly five (MAX_TOOL_CALLS) run, the
extras receive budget-exhausted tool_results, one final forced no-tools call
produces the JSON, and a run that never returns text raises EmptyReportError
instead of producing a cacheable all-null report.
"""

import json

import pytest

from agents.scout import EmptyReportError, ScoutAgent


class _Block:
    def __init__(self, block_type: str, **attrs):
        self.type = block_type
        for key, value in attrs.items():
            setattr(self, key, value)


def _tool_use(i: int) -> _Block:
    return _Block("tool_use", id=f"tu_{i}", name="web_search", input={"query": f"query {i}"})


def _text(text: str) -> _Block:
    return _Block("text", text=text)


class _Response:
    def __init__(self, content):
        self.content = content


_VALID_REPORT = {
    "player_name": "Test Player",
    "confidence": 0.9,
    "stats": {"pts": 10.0},
    "strengths": ["scores"],
    "sources": [],
}


def _stubbed_agent(responses: list[_Response]) -> tuple[ScoutAgent, list, list]:
    agent = ScoutAgent()
    create_calls: list[dict] = []
    executed_tools: list[str] = []

    async def fake_create(**kwargs):
        create_calls.append(kwargs)
        return responses[len(create_calls) - 1]

    async def fake_run_tool_inner(tool_name: str, tool_input: dict):
        executed_tools.append(tool_name)
        agent.tool_call_counts["web_search"] += 1
        return [{"title": "t", "url": "https://www.espn.com/x", "snippet": "s"}]

    agent.client.messages.create = fake_create
    agent._run_tool_inner = fake_run_tool_inner
    return agent, create_calls, executed_tools


@pytest.mark.asyncio
async def test_budget_enforced_and_final_forced_call():
    agent, create_calls, executed_tools = _stubbed_agent(
        [
            _Response([_tool_use(i) for i in range(7)]),
            _Response([_text(json.dumps(_VALID_REPORT))]),
        ]
    )

    report = await agent._generate_once("Test Player")

    # Exactly MAX_TOOL_CALLS tools ran, and only two API calls happened.
    assert len(executed_tools) == ScoutAgent.MAX_TOOL_CALLS == 5
    assert len(create_calls) == 2

    # The final call forces JSON: no more tools allowed.
    assert create_calls[1]["tool_choice"] == {"type": "none"}

    # All 7 tool_use blocks got a tool_result; the 2 extras carry the
    # budget-exhausted error, and the nudge rides in the same user message.
    final_user_message = create_calls[1]["messages"][-1]
    assert final_user_message["role"] == "user"
    blocks = final_user_message["content"]
    tool_results = [b for b in blocks if b.get("type") == "tool_result"]
    text_blocks = [b for b in blocks if b.get("type") == "text"]
    assert len(tool_results) == 7
    exhausted = [b for b in tool_results if "budget exhausted" in b["content"].lower()]
    assert len(exhausted) == 2
    assert len(text_blocks) == 1
    assert "budget exhausted" in text_blocks[0]["text"].lower()

    # Executed tool results are wrapped as untrusted retrieved content.
    wrapped = [b for b in tool_results if "UNTRUSTED RETRIEVED CONTENT" in b["content"]]
    assert len(wrapped) == 5

    assert report["player_name"] == "Test Player"
    # No scraper returned stats, so confidence is capped at 0.5.
    assert report["confidence"] == 0.5


@pytest.mark.asyncio
async def test_no_text_output_raises_instead_of_null_report():
    agent, _, _ = _stubbed_agent(
        [
            _Response([_tool_use(i) for i in range(7)]),
            _Response([]),  # model never emits a text block
        ]
    )
    with pytest.raises(EmptyReportError):
        await agent._generate_once("Test Player")


@pytest.mark.asyncio
async def test_unparseable_output_raises_instead_of_null_report():
    agent, _, _ = _stubbed_agent(
        [
            _Response([_tool_use(i) for i in range(7)]),
            _Response([_text("Sorry, I could not produce the repo")]),  # truncated prose
        ]
    )
    with pytest.raises(EmptyReportError):
        await agent._generate_once("Test Player")
