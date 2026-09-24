#!/usr/bin/env bash
# PyClaw Lite installer: dependencies, folders, optional plugins.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

echo "==> PyClaw Lite install"
echo "    root: $ROOT"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "!! python not found; install Python 3.10+ first" >&2
  exit 1
fi

echo "==> installing dependencies"
"$PY" -m pip install --quiet --upgrade openai pytest

echo "==> preparing directories"
mkdir -p "$ROOT/history/sessions" "$ROOT/history/tool" "$ROOT/history/cache" "$ROOT/memory/notes" "$ROOT/plugins"

if [ ! -f "$ROOT/pyclaw.json" ]; then
  echo "==> creating pyclaw.json from the example (no API key yet)"
  cp "$ROOT/pyclaw.json.example" "$ROOT/pyclaw.json"
fi

echo "==> checking sub-agent plugin host"
if [ -d "$HOME/.codex/plugins" ]; then
  echo "    found ~/.codex/plugins - installed plugins will be picked up automatically"
fi

cat <<'DONE'

Done. Next:
  ./install.sh                     # safe to re-run
  python main.py                   # TUI
  python main.py --plain           # plain line-based CLI
  python main.py --continue        # resume the last session

No API key yet? Start the WebUI and it walks you through setup.
DONE
