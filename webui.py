#!/usr/bin/env python3
"""PyClaw Lite WebUI - HTTP interface using shared core from main.py."""

import json, re, sys, secrets, uuid, threading, types
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from main import (HERE, cli, model, skill_list, TOOLS, build_sysp,
                  ts, extract_text_cmd, run_cmd)

cfg = json.loads((HERE / "pyclaw.json").read_text(encoding="utf-8-sig"))
PORT = cfg.get("WEBUI_PORT", 8765)
HOST = cfg.get("WEBUI_HOST", "127.0.0.1")
TOKEN = (cfg.get("WEBUI_TOKEN") or "").strip()
LOOPBACK = ("127.0.0.1", "::1")

if HOST not in LOOPBACK and not TOKEN:
    print(f"FATAL: WEBUI_HOST={HOST} is not loopback but WEBUI_TOKEN is empty.")
    sys.exit(1)

# --- exec blocked patterns ---
_blocked_extra = cfg.get("WEBUI_EXEC_BLOCKED", [])
if isinstance(_blocked_extra, str): _blocked_extra = [_blocked_extra]
BLOCKED_EXTRA = [str(x).lower() for x in _blocked_extra]
BLOCKED_PATTERNS = [
    r"\brm\s+(-[a-z]*\s+)*-(r|rf|fr)\s+(/|/\*|/\.)(\s|$)",
    r"\brm\s+(-[a-z]*\s+)*-(r|rf|fr)\s+/(bin|boot|dev|etc|home|lib|lib64|proc|root|sbin|sys|usr|var)(/|\s|$)",
    r"\brm\s+(-[a-z]*\s+)*-rf?\s+[a-zA-Z]:[\\/](windows|system32|program\s*files)([\\/]|\s|$)",
    r"\b(del|erase|rd|rmdir)\s+(/(f|s|q)|\s)+[a-zA-Z]:[\\/]",
    r"\bformat\s+[a-zA-Z]:",
    r"\bmkfs(\.\w+)?\s+",
    r"\bdd\s+if=.*of=/(dev/(sd|hd|nvme)|[a-zA-Z]:)",
    r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b|\binit\s+0\b",
    r":\(\)\s*\{", r"%0\s*\|\s*%0", r"\bdiskpart\b",
]

def check_blocked(cmd):
    low = cmd.lower()
    return any(re.search(p, low) for p in BLOCKED_PATTERNS) or any(x and x in low for x in BLOCKED_EXTRA)

# --- confirm gate ---
CONFIRM_TIMEOUT = int(cfg.get("WEBUI_CONFIRM_TIMEOUT", 120))
PENDING_CONFIRM = {}
_confirm_lock = threading.Lock()

def confirm_or_run(cmd, sse):
    cid = uuid.uuid4().hex
    ev = threading.Event()
    with _confirm_lock:
        PENDING_CONFIRM[cid] = {"event": ev, "allow": False}
    sse({"type": "confirm_request", "id": cid, "command": cmd})
    ev.wait(timeout=CONFIRM_TIMEOUT)
    with _confirm_lock:
        entry = PENDING_CONFIRM.pop(cid, None)
    return run_cmd(cmd) if entry and entry["allow"] else f"[denied] user did not approve: {cmd}"

HTML = (HERE / "webui" / "index.html").read_text(encoding="utf-8").replace("__MODEL__", model).replace("__SKILLS__", skill_list)

# --- chat loop (extracted from Handler) ---
def handle_chat(user_msgs, sse):
    """Run the agent loop, streaming SSE events."""
    msgs = [{"role": "system", "content": build_sysp(webui=True)}] + user_msgs
    try:
        while True:
            r = cli.chat.completions.create(model=model, messages=msgs, tools=TOOLS)
            m = r.choices[0].message
            msgs.append(m)
            tool_calls = list(m.tool_calls or [])

            if not tool_calls:
                text = m.content or ""
                tcall = extract_text_cmd(text)
                if tcall:
                    tcmd, trc = tcall
                    pre = text.split("<tool_calls>")[0].strip()
                    if pre: sse({"type": "assistant", "text": pre})
                    m.content = pre or ""
                    tool_calls = [types.SimpleNamespace(
                        id="txt" + uuid.uuid4().hex[:8],
                        function=types.SimpleNamespace(name="exec",
                            arguments=json.dumps({"command": tcmd, "requires_confirmation": trc})))]
                else:
                    if not text.strip():
                        m = cli.chat.completions.create(model=model, messages=msgs).choices[0].message
                        text = m.content or "(no response)"
                        msgs.append(m)
                    for chunk in cli.chat.completions.create(model=model, messages=msgs, stream=True):
                        if chunk.choices and chunk.choices[0].delta.content:
                            sse({"type": "delta", "text": chunk.choices[0].delta.content})
                    sse({"type": "assistant", "text": text})
                    sse({"type": "done"})
                    return

            for tc in tool_calls:
                try:
                    cmd = json.loads(tc.function.arguments)["command"]
                except Exception:
                    cmd = tc.function.arguments
                sse({"type": "tool_call", "command": cmd})
                needs_confirm = check_blocked(cmd) or bool(json.loads(tc.function.arguments).get("requires_confirmation") if tc.function.arguments.startswith("{") else False)
                out = confirm_or_run(cmd, sse) if needs_confirm else run_cmd(cmd)
                sse({"type": "tool_result", "text": out})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
    except Exception as e:
        sse({"type": "error", "text": str(e)})
        sse({"type": "done"})

class Handler(BaseHTTPRequestHandler):
    def _authed(self):
        if not TOKEN: return self.client_address[0] in LOOPBACK
        return secrets.compare_digest(self.headers.get("X-Auth-Token", ""), TOKEN)

    def _deny(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"unauthorized"}')

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.replace("__SYSP_RAW__",
                json.dumps(build_sysp(webui=True), ensure_ascii=False)).encode("utf-8"))

    def do_POST(self):
        if not self._authed(): return self._deny()
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

        if self.path == "/api/confirm":
            with _confirm_lock:
                entry = PENDING_CONFIRM.get(body.get("id", ""))
                if entry:
                    entry["allow"] = bool(body.get("allow", False))
                    entry["event"].set()
            self.send_response(200 if entry else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}' if entry else b'{"ok":false}')
            return

        if self.path == "/api/chat":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            def sse(data):
                self.wfile.write(("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            handle_chat(body.get("messages", []), sse)

    def log_message(self, format, *args): pass

class ThreadedServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    server = ThreadedServer((HOST, PORT), Handler)
    print(f"PyClaw Lite WebUI  http://{HOST}:{PORT}  |  model: {model}  |  skills: [{skill_list}]")
    try: server.serve_forever()
    except KeyboardInterrupt:
        print("\nPyClaw Lite WebUI stopped.")
        server.shutdown()
        server.server_close()

