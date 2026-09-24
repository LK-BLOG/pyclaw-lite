"""Minimal MCP client: stdio and HTTP, tools exposed as mcp__<server>__<tool>."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30.0
CLIENT = {"name": "pyclaw-lite", "version": "0.0.1-beta.2"}


def qualify(server, tool):
    return f"mcp__{server}__{tool}"


def split_qualified(name):
    parts = str(name or "").split("__")
    return (parts[1], "__".join(parts[2:])) if len(parts) >= 3 and parts[0] == "mcp" else (None, None)


class MCPError(Exception):
    pass


class _StdioTransport:
    def __init__(self, name, command, env=None, cwd=None):
        self.name = name
        self.argv = command if isinstance(command, list) else _split(command)
        self.env = dict(os.environ)
        self.env.update({str(k): str(v) for k, v in (env or {}).items()})
        self.cwd = cwd
        self.proc = None
        self.lock = threading.Lock()
        self.next_id = 1

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        if not self.argv:
            raise MCPError(f"{self.name}: empty command")
        try:
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                         errors="replace", bufsize=1, cwd=self.cwd, env=self.env)
        except OSError as exc:
            raise MCPError(f"{self.name}: cannot start {self.argv[0]}: {exc}") from exc

    def request(self, method, params=None, timeout=DEFAULT_TIMEOUT):
        with self.lock:
            self.start()
            rid = self.next_id
            self.next_id += 1
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            while True:
                message = self._read(timeout)
                if message is None:
                    raise MCPError(f"{self.name}: no response to {method}")
                if message.get("id") == rid:
                    if "error" in message:
                        raise MCPError(f"{self.name}: {message['error'].get('message', message['error'])}")
                    return message.get("result", {})

    def notify(self, method, params=None):
        with self.lock:
            self.start()
            self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _send(self, payload):
        assert self.proc and self.proc.stdin
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise MCPError(f"{self.name}: server closed the pipe") from exc

    def _read(self, timeout):
        assert self.proc and self.proc.stdout
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.daemon = True
        timer.start()
        try:
            while not deadline.is_set():
                line = self.proc.stdout.readline()
                if not line:
                    if self.proc.poll() is not None:
                        return None
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
            return None
        finally:
            timer.cancel()

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class _HttpTransport:
    def __init__(self, name, url, headers=None, timeout=DEFAULT_TIMEOUT):
        self.name = name
        self.url = url
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.headers.update({str(k): str(v) for k, v in (headers or {}).items()})
        self.timeout = timeout
        self.next_id = 1
        self.session_id = ""

    def request(self, method, params=None, timeout=None):
        rid = self.next_id
        self.next_id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                          ensure_ascii=False).encode("utf-8")
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                if resp.headers.get("Mcp-Session-Id"):
                    self.session_id = resp.headers["Mcp-Session-Id"]
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise MCPError(f"{self.name}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise MCPError(f"{self.name}: {exc}") from exc
        payload = _parse_http_body(raw, rid)
        if payload is None:
            raise MCPError(f"{self.name}: malformed response")
        if "error" in payload:
            raise MCPError(f"{self.name}: {payload['error'].get('message', payload['error'])}")
        return payload.get("result", {})

    def notify(self, method, params=None):
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}},
                          ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=dict(self.headers), method="POST")
        try:
            urllib.request.urlopen(req, timeout=self.timeout).close()
        except (urllib.error.URLError, OSError):
            pass

    def close(self):
        return None


def _parse_http_body(raw, rid):
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                payload = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if payload.get("id") in (rid, None):
                return payload
    return None


def _split(command):
    out, buf, quote = [], [], ""
    for ch in command or "":
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
        elif ch in "'\"":
            quote = ch
        elif ch.isspace():
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


class MCPServer:
    def __init__(self, spec, cwd=None):
        self.spec = dict(spec or {})
        self.name = str(self.spec.get("name") or "server")
        transport = str(self.spec.get("transport") or ("http" if self.spec.get("url") else "stdio"))
        if transport == "http":
            self.transport = _HttpTransport(self.name, str(self.spec.get("url", "")),
                                            self.spec.get("headers"), float(self.spec.get("timeout", DEFAULT_TIMEOUT)))
        else:
            self.transport = _StdioTransport(self.name, self.spec.get("command") or [],
                                             self.spec.get("env"), self.spec.get("cwd") or cwd)
        self.tools = []
        self.error = ""
        self.ready = False

    def connect(self):
        if self.ready:
            return True
        try:
            self.transport.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": CLIENT,
            })
            self.transport.notify("notifications/initialized", {})
            self.tools = list((self.transport.request("tools/list", {}) or {}).get("tools", []))
            self.ready = True
            self.error = ""
            return True
        except MCPError as exc:
            self.error = str(exc)
            return False

    def schemas(self):
        rows = []
        for tool in self.tools:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            rows.append({"type": "function", "function": {
                "name": qualify(self.name, tool["name"]),
                "description": (tool.get("description") or "")[:1024],
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            }})
        return rows

    def call(self, tool, arguments):
        result = self.transport.request("tools/call", {"name": tool, "arguments": arguments or {}})
        chunks = []
        for block in result.get("content", []) or []:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    chunks.append(str(block.get("text", "")))
                else:
                    chunks.append(json.dumps(block, ensure_ascii=False))
        text = "\n".join(chunk for chunk in chunks if chunk)
        if result.get("isError"):
            text = f"[mcp error] {text}"
        return text or "(no output)"

    def close(self):
        self.transport.close()


class MCPManager:
    """Lazily connects servers; anything broken is reported, never fatal."""

    def __init__(self, specs=None, cwd=None):
        self.servers = {}
        self.errors = []
        for spec in specs or []:
            if not isinstance(spec, dict) or spec.get("enabled") is False:
                continue
            server = MCPServer(spec, cwd)
            self.servers[server.name] = server

    def tool_schemas(self):
        rows = []
        for server in self.servers.values():
            if server.connect():
                rows.extend(server.schemas())
            elif server.error:
                self.errors.append(f"{server.name}: {server.error}")
        return rows

    def names(self):
        return [tool["function"]["name"] for tool in self.tool_schemas()]

    def call(self, qualified, arguments):
        server_name, tool_name = split_qualified(qualified)
        server = self.servers.get(server_name or "")
        if not server:
            return f"[mcp error] unknown server for {qualified}"
        if not server.ready and not server.connect():
            return f"[mcp error] {server.error or server.name + ' is unavailable'}"
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        try:
            return server.call(tool_name, arguments)
        except MCPError as exc:
            return f"[mcp error] {exc}"

    def close(self):
        for server in self.servers.values():
            server.close()


def specs_from_config(config, plugin_hooks=None):
    specs = list(config.get("MCP_SERVERS") or [])
    for entry in plugin_hooks or []:
        for spec in entry.get("mcp") or []:
            if isinstance(spec, dict):
                spec = dict(spec, name=spec.get("name") or entry.get("name", "plugin"))
                specs.append(spec)
    return [spec for spec in specs if isinstance(spec, dict)]


def cache_dir(root):
    path = pathlib.Path(root) / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path
