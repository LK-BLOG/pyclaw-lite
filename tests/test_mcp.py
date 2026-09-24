"""A real stdio MCP server round-trip through the management layer."""

from __future__ import annotations

import json
import sys

from pyclaw.mcp import MCPManager, qualify, split_qualified

SERVER = '''
import json, sys
TOOLS = [{"name": "echo", "description": "Echo text back",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        reply = {"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake"}}}
    elif method == "tools/list":
        reply = {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": TOOLS}}
    elif method == "tools/call":
        text = message["params"]["arguments"].get("text", "")
        reply = {"jsonrpc": "2.0", "id": message["id"],
                 "result": {"content": [{"type": "text", "text": "echo:" + text}]}}
    elif "id" in message:
        reply = {"jsonrpc": "2.0", "id": message["id"], "error": {"message": "unsupported"}}
    else:
        continue
    sys.stdout.write(json.dumps(reply) + "\\n")
    sys.stdout.flush()
'''


def test_qualified_names_round_trip():
    assert qualify("files", "read") == "mcp__files__read"
    assert split_qualified("mcp__files__read") == ("files", "read")
    assert split_qualified("exec") == (None, None)


def test_stdio_server_lists_and_calls_tools(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    manager = MCPManager([{"name": "fake", "command": [sys.executable, str(script)]}], cwd=tmp_path)
    schemas = manager.tool_schemas()
    assert [row["function"]["name"] for row in schemas] == ["mcp__fake__echo"]
    assert schemas[0]["function"]["parameters"]["properties"]["text"]["type"] == "string"
    assert manager.call("mcp__fake__echo", {"text": "hi"}) == "echo:hi"
    manager.close()


def test_arguments_may_arrive_as_a_json_string(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    manager = MCPManager([{"name": "fake", "command": [sys.executable, str(script)]}], cwd=tmp_path)
    assert manager.call("mcp__fake__echo", json.dumps({"text": "x"})) == "echo:x"
    manager.close()


def test_broken_server_is_reported_not_fatal(tmp_path):
    manager = MCPManager([{"name": "dead", "command": [sys.executable, "-c", "raise SystemExit(1)"]}],
                         cwd=tmp_path)
    assert manager.tool_schemas() == []
    assert manager.errors
    assert "mcp error" in manager.call("mcp__dead__x", {})
    manager.close()


def test_unknown_server_returns_a_tool_error(tmp_path):
    manager = MCPManager([], cwd=tmp_path)
    assert "unknown server" in manager.call("mcp__nope__x", {})
