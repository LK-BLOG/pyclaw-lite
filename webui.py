#!/usr/bin/env python3
"""PyClaw Lite WebUI - HTTP interface using shared core from main.py."""

import json, subprocess, sys, datetime, pathlib, re, secrets, uuid, threading, types
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from main import HERE, cli, model, skill_list, TOOLS, build_sysp, ts, extract_text_cmd

cfg = json.loads((HERE / "pyclaw.json").read_text(encoding="utf-8-sig"))
PORT = cfg.get("WEBUI_PORT", 8765)
HOST = cfg.get("WEBUI_HOST", "127.0.0.1")
TOKEN = (cfg.get("WEBUI_TOKEN") or "").strip()

# --- 认证策略：配了 token 就校验；没配则只允许本机来源；对外暴露必须显式配 token ---
LOOPBACK = ("127.0.0.1", "::1")
if HOST not in LOOPBACK and not TOKEN:
    print("FATAL: WEBUI_HOST={} is not loopback but WEBUI_TOKEN is empty.".format(HOST))
    print("Refusing to expose an unauthenticated remote shell. Set WEBUI_TOKEN in pyclaw.json.")
    sys.exit(1)

# --- exec 安全网：挡掉常见的毁灭性命令（只挡根/系统级目标，不挡正常项目操作）---
_blocked_extra = cfg.get("WEBUI_EXEC_BLOCKED", [])
if isinstance(_blocked_extra, str):
    _blocked_extra = [_blocked_extra]
BLOCKED_EXTRA = [str(x).lower() for x in _blocked_extra]
BLOCKED_PATTERNS = [
    r"\brm\s+(-[a-z]*\s+)*-(r|rf|fr)\s+(/|/\*|/\.)(\s|$)",                   # rm -rf /、rm -fr / 或 /*
    r"\brm\s+(-[a-z]*\s+)*-(r|rf|fr)\s+/(bin|boot|dev|etc|home|lib|lib64|proc|root|sbin|sys|usr|var)(/|\s|$)",  # 删系统目录
    r"\brm\s+(-[a-z]*\s+)*-rf?\s+[a-zA-Z]:[\\/](windows|system32|program\s*files)([\\/]|\s|$)",
    r"\b(del|erase|rd|rmdir)\s+(/(f|s|q)|\s)+[a-zA-Z]:[\\/]",                # Windows 删盘/系统目录
    r"\bformat\s+[a-zA-Z]:",                                                   # 格式化磁盘
    r"\bmkfs(\.\w+)?\s+",                                                    # 建文件系统
    r"\bdd\s+if=.*of=/(dev/(sd|hd|nvme)|[a-zA-Z]:)",                           # 写裸设备/盘
    r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b|\binit\s+0\b",    # 关机/重启
    r":\(\)\s*\{",                                                          # fork bomb
    r"%0\s*\|\s*%0",                                                         # windows fork bomb
    r"\bdiskpart\b",
]
def check_blocked(cmd):
    low = cmd.lower()
    if any(re.search(pat, low) for pat in BLOCKED_PATTERNS):
        return True
    return any(x and x in low for x in BLOCKED_EXTRA)


# --- 危险命令确认闸门：命中黑名单不直接执行，等用户在 WebUI 里放行 ---
CONFIRM_TIMEOUT = int(cfg.get("WEBUI_CONFIRM_TIMEOUT", 120))
PENDING_CONFIRM = {}  # id -> {"event": threading.Event(), "allow": bool}
_confirm_lock = threading.Lock()


def _run_cmd(cmd):
    """Execute a shell command, return output text."""
    try:
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        out_lines = []
        while True:
            line = proc.stdout.readline()
            if not line: break
            out_lines.append(line)
        proc.wait(timeout=300)
        return "[exit {}] {}".format(proc.returncode, "".join(out_lines).strip())
    except subprocess.TimeoutExpired:
        return "[timeout 300s]"
    except Exception as e:
        return "[error: {}]".format(e)


def _confirm_or_run(cmd, sse):
    """Blacklist hit -> ask user to approve; otherwise run directly."""
    cid = uuid.uuid4().hex
    ev = threading.Event()
    with _confirm_lock:
        PENDING_CONFIRM[cid] = {"event": ev, "allow": False}
    sse({"type": "confirm_request", "id": cid, "command": cmd})
    ev.wait(timeout=CONFIRM_TIMEOUT)
    with _confirm_lock:
        entry = PENDING_CONFIRM.pop(cid, None)
    if entry and entry["allow"]:
        return _run_cmd(cmd)
    return "[denied] user did not approve: {}".format(cmd)

HTML = (HERE / "webui" / "index.html").read_text(encoding="utf-8")
HTML = HTML.replace("__MODEL__", model)
HTML = HTML.replace("__SKILLS__", skill_list)


class Handler(BaseHTTPRequestHandler):
    def _authed(self):
        # 没配 token：只认本机来源；配了 token：必须带对
        if not TOKEN:
            return self.client_address[0] in LOOPBACK
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
            html = HTML.replace("__SYSP_RAW__", json.dumps(build_sysp(webui=True), ensure_ascii=False))
            self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        if self.path == "/api/confirm":
            if not self._authed():
                self._deny()
                return
            body_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(body_len))
            cid = body.get("id", "")
            allow = bool(body.get("allow", False))
            with _confirm_lock:
                entry = PENDING_CONFIRM.get(cid)
                if entry:
                    entry["allow"] = allow
                    entry["event"].set()
            self.send_response(200 if entry else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}' if entry else b'{"ok":false}')
            return
        if self.path == "/api/chat":
            if not self._authed():
                self._deny()
                return
            body_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(body_len))
            user_msgs = body.get("messages", [])
            msgs = [{"role": "system", "content": build_sysp(webui=True)}] + user_msgs

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            def sse(data):
                payload = "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()

            try:
                while True:
                    r = cli.chat.completions.create(model=model, messages=msgs, tools=TOOLS)
                    m = r.choices[0].message
                    msgs.append(m)

                    tool_calls = list(m.tool_calls or [])
                    if not tool_calls:
                        # 兜底：部分模型/网关不做真 function calling，把工具调用输出成
                        # <tool_calls><invoke name="exec">... 文本，解析出来当真工具执行
                        text = m.content or ""
                        tcall = extract_text_cmd(text)
                        if tcall is not None:
                            print("[webui] parsed text tool-call:", tcall[0][:80], flush=True)
                            tcmd, trc = tcall
                            pre = re.split(r"<tool_calls>", text)[0].strip()
                            if pre:
                                sse({"type": "assistant", "text": pre})
                            m.content = pre or ""
                            tool_calls = [types.SimpleNamespace(
                                id="txt" + uuid.uuid4().hex[:8],
                                function=types.SimpleNamespace(
                                    name="exec",
                                    arguments=json.dumps({"command": tcmd, "requires_confirmation": trc}),
                                ),
                            )]
                        else:
                            if not text.strip():
                                r2 = cli.chat.completions.create(model=model, messages=msgs)
                                m = r2.choices[0].message
                                text = m.content or "(no response)"
                                msgs.append(m)

                            stream = cli.chat.completions.create(
                                model=model, messages=msgs, stream=True
                            )
                            full = ""
                            for chunk in stream:
                                if chunk.choices and chunk.choices[0].delta.content:
                                    t = chunk.choices[0].delta.content
                                    full += t
                                    sse({"type": "delta", "text": t})
                            sse({"type": "assistant", "text": full})
                            sse({"type": "done"})
                            break

                    for tc in tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                            cmd = args["command"]
                        except Exception:
                            args = {}
                            cmd = tc.function.arguments
                        sse({"type": "tool_call", "command": cmd})
                        if check_blocked(cmd) or bool(args.get("requires_confirmation")):
                            out = _confirm_or_run(cmd, sse)
                        else:
                            out = _run_cmd(cmd)
                        sse({"type": "tool_result", "text": out})
                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            except Exception as e:
                sse({"type": "error", "text": str(e)})
                sse({"type": "done"})

    def log_message(self, format, *args):
        pass


class ThreadedServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True  # Ctrl+C 后不等待挂着的请求线程，进程能直接退出


if __name__ == "__main__":
    server = ThreadedServer((HOST, PORT), Handler)
    print("PyClaw Lite WebUI  http://{}:{}  |  model: {}  |  skills: [{}]".format(HOST, PORT, model, skill_list))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPyClaw Lite WebUI stopped.")
        server.shutdown()
        server.server_close()
