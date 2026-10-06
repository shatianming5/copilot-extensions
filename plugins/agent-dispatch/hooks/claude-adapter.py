#!/usr/bin/env python3
"""Run this plugin's Copilot ``hooks.json`` under Claude Code.

Claude Code calls ``claude-adapter.py <Event>`` (see claude-hooks.json). The
matching Copilot hooks run with a Copilot-shaped payload on stdin and the
plugin root in COPILOT_PLUGIN_ROOT, exactly as Copilot runs them, and their
JSON answers fold into one Claude answer: ``additionalContext`` is joined, and
the first ``deny`` (else ``ask``) ``permissionDecision`` wins. A hook that
fails, times out or prints nothing contributes nothing.

The same file ships in every plugin with a Claude layer; only the plugin root
differs. ``--self-test`` runs the check at the bottom.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])

EVENTS = {
    "SessionStart": "sessionStart",
    "SessionEnd": "sessionEnd",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "UserPromptSubmit": "userPromptSubmitted",
}

# Claude tool names -> the Copilot names the hook scripts match on.
TOOLS = {"multiedit": "edit", "notebookedit": "edit"}


def copilot_payload(data: dict) -> dict:
    cwd = data.get("cwd") or os.getcwd()
    payload = {
        "sessionId": data.get("session_id") or "",
        "cwd": cwd,
        "workspaceRoot": cwd,
        "timestamp": int(time.time() * 1000),
        "source": data.get("source") or "startup",
    }
    if "tool_name" in data:
        name = str(data["tool_name"]).lower()
        payload["toolName"] = TOOLS.get(name, name)
        payload["toolArgs"] = data.get("tool_input") or {}
    if "prompt" in data:
        payload["prompt"] = data["prompt"]
    return payload


def run_hooks(kind: str, payload: dict) -> list[dict]:
    try:
        spec = json.loads((ROOT / "hooks.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []
    env = {
        **os.environ,
        "COPILOT_PLUGIN_ROOT": str(ROOT),
        "PLUGIN_ROOT": str(ROOT),
        "COPILOT_PROJECT_DIR": payload["cwd"],
    }
    answers = []
    for hook in spec.get("hooks", {}).get(kind, []):
        command = hook.get("bash")
        if not command:
            continue
        try:
            done = subprocess.run(
                ["bash", "-c", command],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=hook.get("timeoutSec", 30),
                env=env,
                check=False,
            )
            answer = json.loads(done.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        if isinstance(answer, dict):
            answers.append(answer)
    return answers


def claude_answer(event: str, answers: list[dict]) -> dict:
    out: dict = {"hookEventName": event}
    context = "\n\n".join(
        a["additionalContext"].strip()
        for a in answers
        if isinstance(a.get("additionalContext"), str) and a["additionalContext"].strip()
    )
    if context:
        out["additionalContext"] = context
    for decision in ("deny", "ask"):
        hit = next((a for a in answers if a.get("permissionDecision") == decision), None)
        if hit:
            out["permissionDecision"] = decision
            out["permissionDecisionReason"] = hit.get("permissionDecisionReason", "")
            break
    return {"hookSpecificOutput": out} if len(out) > 1 else {}


def main(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    kind = EVENTS.get(event)
    if not kind:
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    answer = claude_answer(event, run_hooks(kind, copilot_payload(data)))
    if answer:
        sys.stdout.write(json.dumps(answer))
    return 0


def self_test() -> None:
    p = copilot_payload({"session_id": "s", "cwd": "/w", "tool_name": "MultiEdit",
                         "tool_input": {"file_path": "/w/a"}})
    assert p["toolName"] == "edit" and p["toolArgs"] == {"file_path": "/w/a"}
    assert claude_answer("PreToolUse", [{}, {"permissionDecision": "ask"},
                                        {"permissionDecision": "deny",
                                         "permissionDecisionReason": "r"}]) == {
        "hookSpecificOutput": {"hookEventName": "PreToolUse",
                               "permissionDecision": "deny",
                               "permissionDecisionReason": "r"}}
    assert claude_answer("SessionStart", [{"additionalContext": "a"}, {},
                                          {"additionalContext": " b "}]) == {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "a\n\nb"}}
    assert claude_answer("SessionEnd", [{}]) == {}
    print("claude-adapter self-test ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
