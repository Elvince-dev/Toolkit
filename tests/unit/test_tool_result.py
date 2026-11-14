"""ToolResult: an action tool says what happened, and the loop believes it.

The bug this guards against, in one sentence: a mail tool returns
"Sent to Ann. I could not reach Bob." — honest prose whose second
half matches tool_said_no()'s failure patterns — and the agent loop
reads it as a total failure, then re-sends to Ann.
"""

from __future__ import annotations

from toolkit.tools.registry import (
    Tool,
    ToolResult,
    load_tools,
    run_direct,
    said_no,
    said_ok,
    tool_said_no,
)


def test_bare_string_still_works():
    """Every existing tool returns a string. That must not change."""
    tools = load_tools()
    tool = tools["count_rows"]
    assert isinstance(tool.run({}), str)


def test_said_ok_is_not_failed():
    r = said_ok("Sent to Ann. I could not write the cc header — bounced.")
    assert isinstance(r, ToolResult)
    assert r.ok is True
    # This prose would have tripped tool_said_no (the `could not write`
    # pattern matches anywhere in the string). ToolResult is how the
    # tool says "it worked anyway" without the classifier guessing.
    assert tool_said_no(r.prose) is True


def test_said_no_is_failed():
    r = said_no("Could not send — no address for Ann.")
    assert isinstance(r, ToolResult)
    assert r.ok is False


def test_run_direct_believes_toolresult(monkeypatch):
    """A matcher whose tool returns said_ok() must not be reported
    as a failure, even though the prose contains 'could not'."""
    from toolkit.tools import registry as reg

    def fake_run(_args):
        return said_ok("Sent to Ann. I could not reach Bob — bounced.")

    fake_tool = Tool(
        name="fake_send",
        what="pretend to send",
        need=(),
        run=fake_run,
    )

    # Patch load_tools so run_direct sees our fake alongside the real
    # ones, and add a matcher that fires on a phrase we control.
    real = load_tools()
    patched = dict(real)
    patched["fake_send"] = fake_tool
    monkeypatch.setattr(reg, "load_tools", lambda: patched)

    matcher = reg.Matcher(
        name="fake_send",
        test=lambda t: "send the test" in t.lower(),
        tool="fake_send",
        args=lambda t: {},
    )
    monkeypatch.setattr(reg, "MATCHERS", [matcher])

    result = run_direct("send the test please")
    assert result is not None
    assert result.ok is True
    assert "Sent to Ann" in result.answer


def test_run_agent_believes_toolresult(monkeypatch):
    """The agent loop must record failed=False for a partial success."""
    import asyncio
    from toolkit.brain import agent as ag
    from toolkit.tools import registry as reg

    def fake_run(_args):
        return said_ok("Sent to Ann. I could not reach Bob — bounced.")

    fake_tool = Tool(
        name="fake_send",
        what="pretend to send",
        need=(),
        run=fake_run,
    )

    # Make load_tools return only our fake, and make run_direct
    # refuse so the model loop runs.
    monkeypatch.setattr(ag, "load_tools", lambda: {"fake_send": fake_tool})
    monkeypatch.setattr(ag, "run_direct", lambda _t: None)

    # Two model replies: pick the tool, then answer.
    replies = iter([
        '{"thought":"send it","tool":"fake_send","args":{}}',
        '{"answer":"Sent."}',
    ])

    async def fake_call(prompt, **kw):
        return next(replies)

    monkeypatch.setattr(ag, "call_ai_async", fake_call)

    result = asyncio.run(ag.run_agent("send the test"))
    assert result.ok is True
    # The trail entry for step 1 is the tool call.
    assert result.trail[0]["tool"] == "fake_send"
    assert result.trail[0]["failed"] is False