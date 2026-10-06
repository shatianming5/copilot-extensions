#!/usr/bin/env python3
"""Claude Code SessionStart adapter for agent-dispatch."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
os.environ["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
os.environ.setdefault("COPILOT_PLUGIN_ROOT", str(ROOT))


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
        chunks = []
        for name in ("emit-command-catalog.sh", "focus-guidance.sh"):
            script = ROOT / "scripts" / name
            if not script.is_file():
                continue
            completed = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env={**os.environ, "PYTHONPATH": ""},
            )
            text = _additional_context(completed.stdout)
            if text:
                chunks.append(text)
        sys.stdout.write("\n\n".join(chunks))
    except Exception:
        sys.stdout.write("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
