#!/usr/bin/env python3
"""PyClaw Lite WebUI - HTTP interface using shared core from main.py."""

import json, subprocess, sys, datetime, pathlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from main import HERE, cli, model, skill_list, TOOLS, build_sysp, ts

cfg = json.loads((HERE / "pyclaw.json").read_text(encoding="utf-8-sig"))
PORT = cfg.get("WEBUI_PORT", 8765)

HTML = (HERE / "webui" / "index.html").read_text(encoding="utf-8")
HTML = HTML.replace("__MODEL__", model)
HTML = HTML.replace("__SKILLS__", skill_list)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = HTML.replace("__SYSP_RAW__", json.dumps(build_sysp(), ensure_ascii=False))
            self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        if self.path == "/api/chat":
            body_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(body_len))
            user_msgs = body.get("messages", [])
            msgs = [{"role": "system", "content": build_sysp()}] + user_msgs

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

                    if not m.tool_calls:
                        text = m.content or ""
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

                    for tc in m.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                            cmd = args["command"]
                        except Exception:
                            cmd = tc.function.arguments
                        sse({"type": "tool_call", "command": cmd})
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
                            out = "[exit {}] {}".format(proc.returncode, "".join(out_lines).strip())
                        except subprocess.TimeoutExpired:
                            out = "[timeout 300s]"
                        except Exception as e:
                            out = "[error: {}]".format(e)
                        sse({"type": "tool_result", "text": out})
                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            except Exception as e:
                sse({"type": "error", "text": str(e)})
                sse({"type": "done"})

    def log_message(self, format, *args):
        pass


class ThreadedServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print("PyClaw Lite WebUI  http://localhost:{}  |  model: {}  |  skills: [{}]".format(PORT, model, skill_list))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
