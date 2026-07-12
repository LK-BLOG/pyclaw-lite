#!/usr/bin/env python3
"""PyClaw Lite - one tool: exec"""

import json, subprocess, pathlib, sys, datetime, platform
sys.stdout.reconfigure(encoding="utf-8")

from openai import OpenAI
try:
    from rich.console import Console
    from rich.markdown import Markdown as RichMD
    _RICH = True
except ImportError:
    _RICH = False

HERE = pathlib.Path(__file__).parent
cfg = json.loads((HERE / "pyclaw.json").read_text(encoding="utf-8-sig"))
cli = OpenAI(api_key=cfg["API_KEY"], base_url=cfg["ENDPOINT"])
model = cfg.get("MODEL", "deepseek-v4-flash-free")

skills = []
for f in (HERE / "skills").iterdir():
    if f.suffix == ".py":
        skills.append(f.stem)
    elif f.is_dir() and (f / "SKILL.md").exists():
        skills.append(f.name)

# === memory ===
memory_dir = HERE / "memory"
memory_dir.mkdir(exist_ok=True)
(memory_dir / "notes").mkdir(exist_ok=True)
memory_blocks = []
for f in sorted(memory_dir.rglob("*")):
    if f.is_file() and f.suffix in (".md", ".txt", ".json", ".jsonl"):
        rel = f.relative_to(memory_dir)
        body = f.read_text(encoding="utf-8", errors="replace").strip()
        if body:
            memory_blocks.append(f"== {rel} ==\n{body}")
memory_block = ""
if memory_blocks:
    memory_block = "\n\n## Your Memory\n" + "\n\n".join(memory_blocks)

if _RICH:
    con = Console()
else:
    con = None

tools = [{"type":"function","function":{"name":"exec","description":"Run shell command, return output","parameters":{"type":"object","properties":{"command":{"type":"string","description":"Shell command to execute"}},"required":["command"]}}}]

skill_list = ", ".join(skills) or "none"
sysp = (
    f"You are PyClaw Lite. You have one tool: exec. Do everything through it \u2014 "
    f"install packages, write files, scrape, analyze. For complex or reusable logic, "
    f"save to skills/. Available skills: {skill_list}"
    f"\n\nYou have persistent memory in {HERE / 'memory'}/. Read files there to remember "
    f"past context. Write to them when you learn something about the user or the workspace. "
    f"Use exec with shell commands to read/write memory files at any time."
    f"{memory_block}"
)

ts = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
os_name = platform.system()

# === session ===
session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
history_dir = HERE / "history"
history_dir.mkdir(exist_ok=True)
history_file = history_dir / f"session_{session_id}.jsonl"

def log_msg(role, content):
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({"role":role,"content":content,"ts":ts()}, ensure_ascii=False)+"\n")

def save_and_exit():
    print(f"\nsession saved: {history_file}", flush=True)
    sys.exit(0)

print(f"PyClaw Lite  {session_id}  |  skills: [{skill_list}]", flush=True)
print(f"memory: {memory_dir}", flush=True)
print(f"history: {history_file}", flush=True)

msgs = [{"role":"system","content":sysp}]
while True:
    try:
        print(f"User {ts()} {os_name}")
        i = input("     > ")
    except (KeyboardInterrupt, EOFError):
        save_and_exit()
    if not i.strip():
        continue
    if i in ("exit","quit"):
        save_and_exit()
    log_msg("user", i)
    msgs.append({"role":"user","content":i})
    while True:
        r = cli.chat.completions.create(model=model, messages=msgs, tools=tools)
        m = r.choices[0].message
        if not m.tool_calls:
            text = m.content or ""
            if not text.strip():
                r2 = cli.chat.completions.create(model=model, messages=msgs)
                m = r2.choices[0].message
                text = m.content or "(no response)"
            log_msg("assistant", text)
            print(f"Agent {ts()}", flush=True)
            if _RICH:
                con.print(RichMD(text))
            else:
                print(f"     > {text}", flush=True)
            msgs.append(m); break
        msgs.append(m)
        for tc in m.tool_calls:
            cmd = json.loads(tc.function.arguments)["command"]
            log_msg("exec", cmd)
            print(f"Exec {ts()}\n     > {cmd}", flush=True)
            try:
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                out_lines = []
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    print(f"     > {line.rstrip()}", flush=True)
                    out_lines.append(line)
                proc.wait(timeout=300)
                out = "[exit {}]\n{}".format(proc.returncode, "".join(out_lines).strip())
            except subprocess.TimeoutExpired:
                proc.kill()
                out = "[timeout 300s]"
            except Exception as e:
                out = f"[error: {e}]"
            log_msg("tool", out)
            print(f"     > {out}", flush=True)
            msgs.append({"role":"tool","tool_call_id":tc.id,"content":out})
