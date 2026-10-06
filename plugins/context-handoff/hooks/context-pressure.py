#!/usr/bin/env python3
"""Claude Code PostToolUse hook: the extension's context-pressure nudge.

Copilot's context-handoff extension watches session.usage_info and nudges the
agent at the soft and hard thresholds (thresholds.mjs). Claude Code has no
extension, so this hook reads the input tokens of the latest main-thread
assistant turn from the transcript and sends the same nudge, once per level;
dropping back below the soft threshold (after /compact) re-arms both.

Thresholds are the repository's .context-handoff/config.yaml (read through
config.mjs) or the thresholds.mjs defaults. Hooks are not told the context
window: CONTEXT_HANDOFF_TOKEN_LIMIT, else Claude Code's
CLAUDE_CODE_MAX_CONTEXT_TOKENS, else the model's window per Claude Code's
catalog (200k for the families below, 1M for the rest and for ``[1m]`` ids).
Grok's hook payload has no transcript, so this is a no-op there.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SOFT_PERCENT, HARD_PERCENT = 55, 70  # extensions/context-handoff/thresholds.mjs
STATE_DIR = Path.home() / ".cache" / "context-handoff" / "claude-pressure"
CONFIG_MJS = Path(__file__).resolve().parents[1] / "extensions" / "context-handoff" / "config.mjs"
LOAD_THRESHOLDS = """
const { pathToFileURL } = await import("node:url");
const [config, cwd] = process.argv.slice(1);
const { loadContextHandoffConfig } = await import(pathToFileURL(config).href);
console.log(JSON.stringify(loadContextHandoffConfig(cwd).thresholds));
"""
# Model ids Claude Code's catalog gives a 200k window; its other models are 1M.
WINDOW_200K = ("claude-3", "claude-haiku", "claude-sonnet-4", "claude-opus-4-0",
               "claude-opus-4-1", "claude-opus-4-2025", "claude-opus-4-5", "claude-opus-4-6")


def window(model: str) -> int:
    """The context window to measure against, in tokens."""
    for name in ("CONTEXT_HANDOFF_TOKEN_LIMIT", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"):
        if os.environ.get(name):
            return int(os.environ[name])
    model = model.lower()
    if "[1m]" not in model and (os.environ.get("CLAUDE_CODE_DISABLE_1M_CONTEXT")
                                or model.startswith(WINDOW_200K)):
        return 200_000
    return 1_000_000


def thresholds(cwd: str) -> tuple[int, int]:
    """(soft, hard) percent: the repository's config.yaml when one exists."""
    here = Path(cwd or ".").resolve()
    if not any((d / ".context-handoff" / "config.yaml").is_file() for d in (here, *here.parents)):
        return SOFT_PERCENT, HARD_PERCENT
    try:
        out = subprocess.run(["node", "--input-type=module", "-e", LOAD_THRESHOLDS,
                              str(CONFIG_MJS), str(here)],
                             capture_output=True, text=True, timeout=5, check=True).stdout
        t = json.loads(out)
        return int(t["softPercent"]), int(t["hardPercent"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return SOFT_PERCENT, HARD_PERCENT


def context_tokens(transcript: str) -> tuple[int, str]:
    """Input tokens of the latest main-thread assistant turn, and its model."""
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
    """The nudge text due for this PostToolUse, or "" (also records the level)."""
    transcript = payload.get("transcript_path") or ""
    if not os.path.isfile(transcript):
        return ""
    tokens, model = context_tokens(transcript)
    limit = window(model)
    soft, hard = thresholds(payload.get("cwd") or "")
    percent = tokens * 100 / limit
    level = "hard" if percent >= hard else "soft" if percent >= soft else ""
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
    """Hook entry point: Claude PostToolUse payload on stdin."""
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
