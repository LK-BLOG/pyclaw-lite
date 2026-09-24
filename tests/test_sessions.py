"""Session log, replay flattening, search, archive and legacy migration."""

from __future__ import annotations

import json

from pyclaw.sessions import SessionStore, parse_title, title_prompt


def make_store(tmp_path):
    return SessionStore(tmp_path / "sessions", tmp_path)


def test_append_and_replay_flattens_tool_traffic(tmp_path):
    store = make_store(tmp_path)
    session = store.create()
    session.append({"type": "user", "content": "do it"})
    session.append({"type": "assistant", "content": "running"})
    session.append({"type": "tool", "name": "exec", "command": "ls", "content": "[exit 0] a b"})
    session.append({"type": "tool", "name": "exec", "command": "pwd", "content": "[exit 0] /tmp"})
    session.append({"type": "assistant", "content": "done"})
    messages = session.messages()
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert '<tool name="exec">' in messages[2]["content"]
    assert "ls" in messages[2]["content"] and "pwd" in messages[2]["content"]


def test_tool_call_ids_never_leak_into_replay(tmp_path):
    store = make_store(tmp_path)
    session = store.create()
    session.append({"type": "assistant", "content": "x"})
    session.append({"type": "tool", "name": "exec", "command": "ls", "content": "out", "tool_call_id": "abc"})
    assert all("tool_call_id" not in message for message in session.messages())


def test_compact_event_replaces_history(tmp_path):
    store = make_store(tmp_path)
    session = store.create()
    session.append({"type": "user", "content": "old"})
    session.append({"type": "compact", "checkpoint": "CHECKPOINT", "tokens_before": 900})
    session.append({"type": "user", "content": "new"})
    messages = session.messages()
    assert messages[0]["content"] == "CHECKPOINT" and messages[1]["content"] == "new"


def test_search_matches_title_and_body(tmp_path):
    store = make_store(tmp_path)
    session = store.create()
    session.set(title="部署脚本")
    session.append({"type": "user", "content": "检查 nginx 配置"})
    assert [row["id"] for row in store.list(query="部署")] == [session.id]
    assert [row["id"] for row in store.list(query="nginx")] == [session.id]
    assert store.list(query="absent") == []


def test_archive_hides_from_default_listing(tmp_path):
    store = make_store(tmp_path)
    session = store.create()
    session.set(archived=True)
    assert store.list() == [] and len(store.list(include_archived=True)) == 1


def test_rename_and_delete(tmp_path):
    store = make_store(tmp_path)
    session = store.create()
    session.set(title="新名字")
    assert store.get(session.id).title == "新名字"
    store.delete(session.id)
    assert store.get(session.id) is None
    assert not (tmp_path / "sessions" / f"{session.id}.jsonl").exists()


def test_legacy_files_are_migrated(tmp_path):
    legacy = tmp_path / "session_20260101_120000.jsonl"
    legacy.write_text("\n".join([
        json.dumps({"role": "user", "content": "老会话", "ts": "2026-01-01 12:00"}),
        json.dumps({"role": "exec", "content": "ls", "ts": "2026-01-01 12:00"}),
        json.dumps({"role": "tool", "content": "[exit 0] ok", "ts": "2026-01-01 12:00"}),
        json.dumps({"role": "assistant", "content": "完成", "ts": "2026-01-01 12:00"}),
    ]), encoding="utf-8")
    store = make_store(tmp_path)
    rows = store.list(include_archived=True)
    assert len(rows) == 1
    assert store.get(rows[0]["id"]).messages()[0]["content"] == "老会话"


def test_title_parsing_prefers_the_code_block():
    assert parse_title("```text\n部署脚本\n```", "ignored") == "部署脚本"
    assert parse_title("```\n修复登录\n```", "ignored") == "修复登录"


def test_title_falls_back_to_the_first_message():
    title = parse_title("", "帮我 修一下登录页面的错误提示")
    assert title and len(title) <= 12 and title.startswith("修")


def test_title_prompt_says_five_characters():
    assert "5-character" in title_prompt("hello")[0]["content"]
