"""Write agent-worktrees live-pulse sidecar (substatus.json) for Claude/Grok.

Copilot's extension.mjs writes the same shape into ~/.copilot/session-state/<sid>/.
This helper is used by Claude hooks (and optionally Grok) so the picker still
sees busy/idle without the Copilot SDK.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _dirs(session_id: str) -> list[Path]:
    home = Path.home()
    return [
        home / ".copilot" / "session-state" / session_id,
        home / ".claude" / "session-state" / session_id,
        home / ".grok" / "session-state" / session_id,
    ]


def record(payload: dict, *, idle: bool, intent: str | None = None) -> None:
    sid = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
    if not sid:
        return
    tool = payload.get("toolName") or payload.get("tool_name") or ""
    text = intent or (f"tool {tool}" if tool else "session")
    rest = "idle" if idle else "busy"
    body = {
        "sessionId": sid,
        "intent": text,
        "updatedAt": _now(),
        "idle": idle,
        "rest": rest,
        "restAt": _now(),
        "host": "claude" if os.environ.get("CLAUDE_PLUGIN_ROOT") else "grok",
    }
    raw = json.dumps(body)
    for folder in _dirs(sid):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "substatus.json").write_text(raw + "\n")
        except OSError:
            continue
