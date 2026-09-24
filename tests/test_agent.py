"""The loop: tool calls, approval, spill, compaction and failure recovery."""

from __future__ import annotations

from conftest import make_agent, tool_call
from pyclaw.providers import ProviderError


def collect():
    events = []
    return events, events.append


def test_plain_answer_is_stored_and_emitted(workspace):
    agent = make_agent(workspace, [{"content": "hello", "reasoning": "thought", "tool_calls": [],
                                    "usage": {"prompt_tokens": 10}}])
    events, emit = collect()
    agent.run_turn("hi", emit)
    assert [event["type"] for event in events] == ["assistant", "usage", "done"]
    kinds = [event["type"] for event in agent.session.events()]
    assert kinds == ["user", "snapshot", "assistant"]  # no memory files yet, so policy only
    assert agent.session.events()[-1]["reasoning"] == "thought"


def test_tool_call_runs_through_exec_and_is_recorded(workspace):
    script = [
        {"content": "", "reasoning": "r", "tool_calls": [tool_call("echo hi")], "usage": {}},
        {"content": "did it", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script)
    events, emit = collect()
    agent.run_turn("run it", emit)
    kinds = [event["type"] for event in events]
    assert "tool_call" in kinds and "tool_result" in kinds
    tool_events = [event for event in agent.session.events() if event["type"] == "tool"]
    assert tool_events and "hi" in tool_events[0]["content"]


def test_reasoning_deltas_are_forwarded(workspace):
    agent = make_agent(workspace, [{"content": "a", "reasoning": "b", "tool_calls": [],
                                    "deltas": [("reasoning", "think"), ("text", "a")], "usage": {}}])
    events, emit = collect()
    agent.run_turn("hi", emit)
    assert [event["type"] for event in events[:2]] == ["reasoning", "text"]


def test_denied_approval_blocks_the_command(workspace):
    script = [
        {"content": "", "reasoning": "", "tool_calls": [tool_call("python cleanup.py")], "usage": {}},
        {"content": "ok", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script, APPROVAL_MODE="request")
    asked = []

    def confirm(command, verdict):
        asked.append(command)
        return False, None

    agent.run_turn("go", lambda event: None, confirm)
    assert asked == ["python cleanup.py"]
    tool_events = [event for event in agent.session.events() if event["type"] == "tool"]
    assert tool_events[0]["content"].startswith("[denied]")


def test_session_scope_approval_creates_a_rule(workspace):
    script = [
        {"content": "", "reasoning": "", "tool_calls": [tool_call("python build.py --fast")], "usage": {}},
        {"content": "", "reasoning": "", "tool_calls": [tool_call("python build.py --slow")], "usage": {}},
        {"content": "done", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script, APPROVAL_MODE="request")
    prompts = []

    def confirm(command, verdict):
        prompts.append(command)
        return True, "session"

    agent.run_turn("go", lambda event: None, confirm)
    assert prompts == ["python build.py --fast"]
    assert agent.policy.session_rules


def test_forbidden_command_never_runs(workspace):
    script = [
        {"content": "", "reasoning": "", "tool_calls": [tool_call("rm -rf /")], "usage": {}},
        {"content": "stopped", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script, APPROVAL_MODE="full")
    agent.run_turn("go", lambda event: None)
    tool_events = [event for event in agent.session.events() if event["type"] == "tool"]
    assert tool_events[0]["content"].startswith("[refused]")


def test_duplicate_command_in_one_turn_is_skipped(workspace):
    script = [
        {"content": "", "reasoning": "", "tool_calls": [tool_call("echo dup", "c1")], "usage": {}},
        {"content": "", "reasoning": "", "tool_calls": [tool_call("echo dup", "c2")], "usage": {}},
        {"content": "done", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script)
    agent.run_turn("go", lambda event: None)
    tool_events = [event for event in agent.session.events() if event["type"] == "tool"]
    assert tool_events[1]["content"].startswith("[skipped]")


def test_memory_snapshot_only_appends_when_content_changes(workspace):
    (workspace / "memory" / "notes" / "a.md").write_text("fact one", encoding="utf-8")
    agent = make_agent(workspace, [{"content": "x", "reasoning": "", "tool_calls": [], "usage": {}}])
    agent.base_messages()
    assert len([e for e in agent.session.events() if e.get("kind") == "memory"]) == 1
    agent.base_messages()
    assert len([e for e in agent.session.events() if e.get("kind") == "memory"]) == 1
    (workspace / "memory" / "notes" / "a.md").write_text("fact two", encoding="utf-8")
    agent.base_messages()
    assert len([e for e in agent.session.events() if e.get("kind") == "memory"]) == 2


def test_policy_snapshot_tracks_approval_mode(workspace):
    agent = make_agent(workspace, [{"content": "x", "reasoning": "", "tool_calls": [], "usage": {}}])
    agent.base_messages()
    assert agent.policy_snapshot().count("Approval mode: auto") == 1
    agent.session.set(approval="request")
    agent.base_messages()
    assert len([e for e in agent.session.events() if e.get("kind") == "policy"]) == 2


def test_compaction_fires_over_the_threshold(workspace):
    agent = make_agent(workspace, [
        {"content": "summary", "reasoning": "", "tool_calls": [], "usage": {}},
        {"content": "answer", "reasoning": "", "tool_calls": [], "usage": {}},
    ], CONTEXT_WINDOW=1000)
    agent.provider.context_window = 1000
    agent.last_usage = {"prompt_tokens": 900}
    messages = [{"role": "system", "content": "s"}] + [{"role": "user", "content": f"m{i}"} for i in range(40)]
    events, emit = collect()
    rebuilt = agent.compact(messages, [], emit)
    assert rebuilt[1]["content"].startswith("This is an automatically generated checkpoint")
    assert "<compacted-summary>" in rebuilt[1]["content"]
    assert any(event.get("type") == "compact" for event in agent.session.events())
    assert events[0]["type"] == "compact"


def test_compaction_falls_back_when_the_summary_call_fails(workspace):
    agent = make_agent(workspace, [
        ProviderError("server", "boom", retryable=True),
        ProviderError("server", "boom", retryable=True),
    ])
    messages = [{"role": "system", "content": "s"}] + [{"role": "user", "content": f"m{i}"} for i in range(20)]
    rebuilt = agent.compact(messages, [], lambda event: None)
    assert "dropped to free context" in rebuilt[1]["content"]


def test_overflow_error_forces_compaction_and_retries(workspace):
    script = [
        ProviderError("overflow", "context_length_exceeded", overflow=True),
        {"content": "recovered", "reasoning": "", "tool_calls": [], "__mark": "compaction summary"},
        {"content": "recovered", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script)
    events, emit = collect()
    agent.run_turn("go", emit)
    assert any(event["type"] == "compact" for event in events)
    assert agent.session.events()[-1]["content"] == "recovered"


def test_unsupported_effort_downgrades_and_retries(workspace):
    script = [
        ProviderError("unsupported_effort", "unsupported", unsupported_effort=True),
        {"content": "fine", "reasoning": "", "tool_calls": [], "usage": {}},
    ]
    agent = make_agent(workspace, script)
    events, emit = collect()
    agent.run_turn("go", emit)
    assert any(event["type"] == "notice" for event in events)
    assert agent.session.meta["effort"] == "high"
    assert agent.session.events()[-1]["content"] == "fine"


def test_provider_error_is_reported_without_crashing(workspace):
    agent = make_agent(workspace, [ProviderError("auth", "bad key")])
    events, emit = collect()
    agent.run_turn("go", emit)
    assert any(event["type"] == "error" and "auth" in event["text"] for event in events)


def test_system_prompt_stays_short_and_names_the_shell(workspace):
    agent = make_agent(workspace, [])
    prompt = agent.system_prompt()
    assert len(prompt) < 1200
    assert "exec" in prompt and "bash" in prompt
    assert "memory/" in prompt
