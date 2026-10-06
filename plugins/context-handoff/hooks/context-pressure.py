#!/usr/bin/env python3
"""Claude Code PostToolUse hook: the extension's context-pressure nudge.

Copilot's context-handoff extension watches session.usage_info and nudges the
agent at the soft and hard thresholds (thresholds.mjs). Claude Code has no
extension, so this hook reads the input tokens of the latest main-thread
assistant turn from the transcript and sends the same nudge, once per level;
dropping back below the soft threshold (after /compact) re-arms both.

Hooks are not told the context window: CONTEXT_HANDOFF_TOKEN_LIMIT, else
Claude Code's CLAUDE_CODE_MAX_CONTEXT_TOKENS, else 1M for a ``[1m]`` model id
and 200k otherwise.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SOFT_PERCENT, HARD_PERCENT = 55, 70  # extensions/context-handoff/thresholds.mjs
STATE_DIR = Path.home() / ".cache" / "context-handoff" / "claude-pressure"


def context_tokens(transcript: str) -> tuple[int, str]:
    with open(transcript, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 2_000_000))
        lines = f.read().splitlines()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        msg = entry.get("message") if isinstance(entry, dict) else None
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if entry.get("type") != "assistant" or entry.get("isSidechain") or not usage:
            continue
        tokens = sum(int(usage.get(k) or 0) for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        return tokens, str(msg.get("model") or "")
    return 0, ""


def nudge(payload: dict) -> str:
    transcript = payload.get("transcript_path") or ""
    if not os.path.isfile(transcript):
        return ""
    tokens, model = context_tokens(transcript)
    limit = int(os.environ.get("CONTEXT_HANDOFF_TOKEN_LIMIT")
                or os.environ.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS")
                or (1_000_000 if "[1m]" in model else 200_000))
    percent = tokens * 100 / limit
    level = "hard" if percent >= HARD_PERCENT else "soft" if percent >= SOFT_PERCENT else ""
    state = STATE_DIR / str(payload.get("session_id") or "unknown")
    sent = state.read_text().strip() if state.is_file() else ""
    if level == sent or (sent == "hard" and level == "soft"):
        return ""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state.write_text(level)
    if not level:
        return ""
    usage = f"{round(percent)}% ({tokens:,} / {limit:,} tokens)"
    if level == "hard":
        return (f"[Context Handoff -- automated] Context utilization is {usage}. The "
                "configured hard threshold was reached; auto-compaction triggers soon. "
                "Invoke the context-handoff skill now: compose the baton, store it with "
                "save_handoff_prompt, then call continue_handoff with its HANDOFF_SEED; "
                "do not pause to ask the user first.")
    return (f"[Context Handoff -- automated] Context utilization is {usage}. The "
            "configured soft threshold was reached. At the next clean boundary, invoke "
            "the context-handoff skill and store a baton early with save_handoff_prompt.")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        message = nudge(payload)
    except Exception:  # a hook must never break the session
        return 0
    if message:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": message}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
