#!/usr/bin/env python3
"""Claude Code SessionStart adapter for context-handoff: emits the owned
continuity guidance and writes the session-guidance file. The context-pressure
nudge is hooks/context-pressure.mjs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
os.environ["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
os.environ.setdefault("COPILOT_PLUGIN_ROOT", str(ROOT))


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _additional_context(stdout: str) -> str:
    try:
        value = json.loads(stdout or "{}")
    except (TypeError, ValueError):
        return ""
    context = value.get("additionalContext") if isinstance(value, dict) else None
    return context.strip() if isinstance(context, str) else ""


def main(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    if event != "SessionStart":
        sys.stdout.write("{}")
        return 0
    try:
        payload = json.dumps(_read_stdin())
        script = ROOT / "scripts" / "emit-guidance.sh"
        if not script.is_file():
            return 0
        completed = subprocess.run(
            ["bash", str(script), "--own-only"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            env={**os.environ, "PYTHONPATH": ""},
        )
        sys.stdout.write(_additional_context(completed.stdout))
        writer = ROOT / "scripts" / "write_session_guidance.py"
        if writer.is_file():
            subprocess.run(
                [sys.executable, str(writer)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                env={**os.environ, "PYTHONPATH": ""},
            )
    except Exception:
        sys.stdout.write("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
