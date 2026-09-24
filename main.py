#!/usr/bin/env python3
"""PyClaw Lite entry point: CLI by default, WebUI with --webui."""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from pyclaw import VERSION            # noqa: E402
from pyclaw.agent import build_agent  # noqa: E402
from pyclaw.cli import CLI            # noqa: E402
from pyclaw.config import Config      # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pyclaw", description="PyClaw Lite - one tool, built to stay small")
    parser.add_argument("--plain", action="store_true", help="use the plain line-based CLI instead of the TUI")
    parser.add_argument("--continue", dest="resume", action="store_true", help="resume the most recent session")
    parser.add_argument("--session", help="open a specific session id")
    parser.add_argument("--model", help="override the model for this run")
    parser.add_argument("--host", help="WebUI bind address")
    parser.add_argument("--port", type=int, help="WebUI port")
    parser.add_argument("--version", action="version", version=f"PyClaw Lite {VERSION}")
    args = parser.parse_args(argv)

    config = Config()
    overrides = {}
    if args.model:
        overrides["MODEL"] = args.model
    if overrides:
        config.update(overrides)

    agent = build_agent(config, session_id=args.session, resume=args.resume or bool(args.session))
    if not args.plain:
        from pyclaw.tui import TUI

        return TUI(config, agent).run() or 0
    return CLI(config, agent).run() or 0


if __name__ == "__main__":
    raise SystemExit(main())
