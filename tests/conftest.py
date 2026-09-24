"""Shared fixtures. Nothing here touches the network or a real API."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class FakeConfig(dict):
    """Config stand-in with the few methods the agent actually uses."""

    def __init__(self, **values):
        from pyclaw.config import DEFAULTS

        super().__init__(DEFAULTS)
        dict.update(self, values)
        self.saved = {}

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def update(self, patch):
        self.saved.update(patch)
        dict.update(self, patch)
        return patch


class FakeProvider:
    """Returns scripted turns and records what it was asked to send."""

    def __init__(self, script, context_window=100000, thinking_mode="deepseek"):
        self.script = list(script)
        self.context_window = context_window
        self.thinking_mode = thinking_mode
        self.model = "fake-model"
        self.endpoint = "http://localhost"
        self.sent = []

    def tiers(self):
        from pyclaw.providers import effort_tiers

        return effort_tiers(self.thinking_mode)

    def list_models(self):
        return ["fake-model"]

    def reload(self, config):
        self.model = config.get("MODEL", self.model)

    def chat_with_retry(self, messages, tools=None, effort="high", on_delta=None, signal=None, attempts=3):
        self.sent.append({"messages": messages, "tools": tools, "effort": effort})
        if not self.script:
            return {"content": "done", "reasoning": "", "tool_calls": [], "usage": {}}
        turn = self.script.pop(0)
        if isinstance(turn, Exception):
            raise turn
        for kind, text in turn.get("deltas", []):
            if on_delta:
                on_delta(kind, text)
        return turn


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "memory" / "notes").mkdir(parents=True)
    (tmp_path / "skills").mkdir()
    (tmp_path / "history").mkdir()
    return tmp_path


def tool_call(command, call_id="call_1", arguments=None):
    import json

    payload = arguments if arguments is not None else {"command": command}
    return {"id": call_id, "name": "exec", "arguments": json.dumps(payload)}


def make_agent(workspace, script, **config_values):
    from pyclaw.agent import Agent
    from pyclaw.context import Shell
    from pyclaw.sessions import SessionStore

    values = {"MODEL": "fake-model", "APPROVAL_MODE": "auto", "REASONING_EFFORT": "high"}
    values.update(config_values)
    config = FakeConfig(**values)
    store = SessionStore(workspace / "history" / "sessions", workspace / "history")
    session = store.create(model="fake-model", effort="high", approval=values["APPROVAL_MODE"])
    provider = FakeProvider(script)
    shell = Shell("bash", ["bash", "-lc"], str(workspace), "Use bash syntax.", False)
    return Agent(config, store, session, provider, shell, hooks=None, mcp=None, plugins=[], root=workspace)
