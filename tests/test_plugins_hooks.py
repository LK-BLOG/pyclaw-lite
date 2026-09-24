"""Plugin discovery, the hook protocol, and a real ponytail compatibility run."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from pyclaw import plugins as plugin_mod
from pyclaw.hooks import HookEngine, normalise_event


def write_plugin(root, name="demo", manifest=None, hooks=None, skill=True, tools=None):
    plugin_dir = root / name
    (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "version": "1.0.0", "description": "demo plugin",
               "skills": "./skills/", "hooks": "./hooks/hooks.json"}
    payload.update(manifest or {})
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    if skill:
        (plugin_dir / "skills" / "demo").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "skills" / "demo" / "SKILL.md").write_text(
            "---\ndescription: demo skill\n---\n\n# Demo\n", encoding="utf-8")
    if hooks is not None:
        (plugin_dir / "hooks").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "hooks" / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
    if tools:
        (plugin_dir / "tools.py").write_text(tools, encoding="utf-8")
    return plugin_dir


HOOK_SCRIPT = """
import json, sys
payload = json.load(sys.stdin)
print(json.dumps({"systemMessage": "HOOK:" + payload.get("hook_event_name", ""),
                  "hookSpecificOutput": {"hookEventName": payload.get("hook_event_name"),
                                         "additionalContext": "injected for " + payload.get("prompt", "")}}))
"""


def test_discover_reads_the_codex_manifest(tmp_path):
    write_plugin(tmp_path, hooks={"hooks": {}})
    found = plugin_mod.discover([tmp_path])
    assert [plugin.name for plugin in found] == ["demo"]
    assert found[0].skills and found[0].skills[0]["name"] == "demo:demo"
    assert found[0].errors == []


def test_plugin_tools_register_through_register_ctx(tmp_path):
    write_plugin(tmp_path, tools="""
def register(ctx):
    ctx.add_tool("shout", "Upper-case text", {"type": "object", "properties": {"text": {"type": "string"}}},
                 lambda args, context: str(args.get("text", "")).upper())
""")
    plugin = plugin_mod.discover([tmp_path])[0]
    assert [tool["function"]["name"] for tool in plugin.tools] == ["shout"]
    assert plugin.tools[0]["_handler"]({"text": "hi"}, {}) == "HI"


def test_broken_plugin_is_reported_not_fatal(tmp_path):
    write_plugin(tmp_path, tools="raise RuntimeError('nope')\n")
    plugin = plugin_mod.discover([tmp_path])[0]
    assert plugin.tools == [] and plugin.errors and "nope" in plugin.errors[0]


def test_repo_plugins_stay_off_until_listed(tmp_path):
    repo = tmp_path / "plugins"
    write_plugin(repo, name="demo", skill=False)
    assert plugin_mod.discover([repo])[0].enabled is False
    assert plugin_mod.discover([repo], enabled=["demo"])[0].enabled is True


def test_event_names_accept_camel_case():
    assert normalise_event("sessionStart") == "SessionStart"
    assert normalise_event("userPromptSubmitted") == "UserPromptSubmit"
    assert normalise_event("PreToolUse") == "PreToolUse"


def test_command_hook_injects_context(tmp_path):
    script = tmp_path / "hook.py"
    script.write_text(HOOK_SCRIPT, encoding="utf-8")
    engine = HookEngine({"hooks": {"UserPromptSubmit": [{"hooks": [
        {"type": "command", "command": f'"{_python()}" "{script}"', "timeout": 10}]}]}})
    result = engine.run("UserPromptSubmit", {"prompt": "hi"}, cwd=tmp_path)
    assert result.contexts == ["injected for hi"]
    assert result.messages == ["HOOK:UserPromptSubmit"]
    assert result.errors == []


def test_matcher_filters_handlers(tmp_path):
    script = tmp_path / "hook.py"
    script.write_text(HOOK_SCRIPT, encoding="utf-8")
    engine = HookEngine({"hooks": {"SessionStart": [
        {"matcher": "resume", "hooks": [{"type": "command", "command": f'"{_python()}" "{script}"'}]}]}})
    assert engine.run("SessionStart", {"source": "startup"}, cwd=tmp_path).contexts == []
    assert engine.run("SessionStart", {"source": "resume"}, cwd=tmp_path).contexts


def test_hooks_never_block_a_turn(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(5)", encoding="utf-8")
    engine = HookEngine({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": f'"{_python()}" "{script}"', "timeout": 0.3}]}]}})
    result = engine.run("SessionStart", {}, cwd=tmp_path)
    assert result.contexts == [] and result.errors and "timed out" in result.errors[0]


def test_missing_plugin_root_fails_softly(tmp_path):
    engine = HookEngine({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "definitely-not-a-real-binary"}]}]}})
    assert engine.run("SessionStart", {}, cwd=tmp_path).errors


def test_plugin_root_variable_is_expanded(tmp_path):
    script = tmp_path / "echo_root.py"
    script.write_text("import os, json; print(json.dumps({'hookSpecificOutput': {'additionalContext': "
                      "os.environ.get('CLAUDE_PLUGIN_ROOT', '')}}))", encoding="utf-8")
    engine = HookEngine({}, [{"name": "demo", "root": str(tmp_path), "hooks": {"hooks": {
        "SessionStart": [{"hooks": [{"type": "command",
                                     "command": f'"{_python()}" "${{CLAUDE_PLUGIN_ROOT}}/echo_root.py"'}]}]}}}])
    assert engine.run("SessionStart", {}, cwd=tmp_path).contexts == [str(tmp_path)]


def test_plan_and_agent_handler_types_use_the_model(workspace):
    calls = []
    engine = HookEngine({"hooks": {"UserPromptSubmit": [{"hooks": [
        {"type": "prompt", "prompt": "Summarize"}]}]}},
        model_call=lambda instruction, payload: calls.append(instruction) or "model context")
    result = engine.run("UserPromptSubmit", {"prompt": "x"})
    assert calls == ["Summarize"] and result.contexts == ["model context"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the ponytail hook")
def test_real_ponytail_hook_protocol(tmp_path):
    pony = pathlib.Path.home() / ".codex" / "plugins" / "cache" / "ponytail"
    candidates = list(pony.rglob("hooks/claude-codex-hooks.json")) if pony.exists() else []
    if not candidates:
        pytest.skip("ponytail is not installed")
    plugin_root = candidates[0].parent.parent
    hooks = json.loads(candidates[0].read_text(encoding="utf-8-sig"))
    data = tmp_path / "plugin-data"
    data.mkdir()
    engine = HookEngine(hooks, [{"name": "ponytail", "root": str(plugin_root), "hooks": hooks}],
                        data_dir=data)
    result = engine.run("SessionStart", {"source": "startup"}, cwd=plugin_root)
    assert result.errors == []
    assert result.contexts and len(result.contexts[0]) > 200
    assert any("PONYTAIL" in message for message in result.messages)
    assert (data / ".ponytail-active").exists()


def _python():
    import sys

    return sys.executable
