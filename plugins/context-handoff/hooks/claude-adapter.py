#!/usr/bin/env python3
"""Claude Code hook adapter for context-handoff: SessionStart guidance and
PostToolUse context-pressure nudges (the Copilot extension's usage_info monitor)."""
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


SOFT_PERCENT, HARD_PERCENT = 55, 70  # same defaults as extensions/.../thresholds.mjs


def _context_tokens(transcript: str) -> tuple[int, str]:
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


# Model ids Claude Code's catalog gives a 200k window; its other models are 1M.
WINDOW_200K = ("claude-3", "claude-haiku", "claude-sonnet-4", "claude-opus-4-0",
               "claude-opus-4-1", "claude-opus-4-2025", "claude-opus-4-5", "claude-opus-4-6")


def _window(model: str) -> int:
    """Hooks are not told the window: CONTEXT_HANDOFF_TOKEN_LIMIT, else Claude
    Code's CLAUDE_CODE_MAX_CONTEXT_TOKENS, else the model's catalog window."""
    for name in ("CONTEXT_HANDOFF_TOKEN_LIMIT", "CLAUDE_CODE_MAX_CONTEXT_TOKENS"):
        if os.environ.get(name):
            return int(os.environ[name])
    model = model.lower()
    if "[1m]" not in model and (os.environ.get("CLAUDE_CODE_DISABLE_1M_CONTEXT")
                                or model.startswith(WINDOW_200K)):
        return 200_000
    return 1_000_000


def _pressure(payload: dict) -> None:
    transcript = payload.get("transcript_path") or ""
    if not os.path.isfile(transcript):
        return
    tokens, model = _context_tokens(transcript)
    limit = _window(model)
    percent = tokens * 100 / limit
    level = "hard" if percent >= HARD_PERCENT else "soft" if percent >= SOFT_PERCENT else ""
    state_dir = Path.home() / ".cache" / "context-handoff" / "claude-pressure"
    state = state_dir / str(payload.get("session_id") or "unknown")
    sent = state.read_text().strip() if state.is_file() else ""
    if level == sent or (sent == "hard" and level == "soft"):
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    state.write_text(level)  # below soft (e.g. after /compact) re-arms both nudges
    if not level:
        return
    usage = f"{round(percent)}% ({tokens:,} / {limit:,} tokens)"
    msg = (
        f"[Context Handoff -- automated] Context utilization is {usage}. "
        "The configured hard threshold was reached; auto-compaction triggers soon. "
        "Invoke the context-handoff skill now to preserve continuity before context "
        "is lost. Compose/store the baton and then call trigger_handoff directly; "
        "do not pause to ask the user first."
    ) if level == "hard" else (
        f"[Context Handoff -- automated] Context utilization is {usage}. "
        "The configured soft threshold was reached. Invoke the context-handoff skill "
        "at the next clean boundary so you can compose/store a baton early and, if "
        "work still remains, trigger_handoff directly before the window gets tighter."
    )
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": msg}}))


def main(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    if event == "PostToolUse":
        try:
            _pressure(_read_stdin())
        except Exception:
            pass
        return 0
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
