#!/usr/bin/env python3
"""Claude Code hook adapter for agent-worktrees.

Maps Claude stdin/stdout onto the existing Copilot hook_client without
changing Copilot/Grok sessionStart stdout (that host still emits {}).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1])
os.environ["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
os.environ.setdefault("COPILOT_PLUGIN_ROOT", str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# Claude and Grok tool names -> the Copilot names the guards match on
# (case-sensitive: "Write" from Claude would otherwise never be checked).
TOOLS = {
    "multiedit": "edit", "notebookedit": "edit",
    "run_terminal_command": "bash", "write_file": "write", "search_replace": "edit",
}


def _map_payload(data: dict) -> dict:
    """Translate a Claude (snake_case) or Grok (camelCase) hook payload into the
    Copilot payload hook_client expects."""
    mapped = dict(data)
    session_id = data.get("session_id") or data.get("sessionId") or ""
    cwd = data.get("cwd") or os.getcwd()
    mapped["sessionId"] = session_id
    mapped["cwd"] = cwd
    mapped["workspaceRoot"] = data.get("workspaceRoot") or cwd
    mapped.setdefault("source", data.get("source") or data.get("hook_event_name") or "startup")
    mapped.setdefault("timestamp", time.time())
    tool = data.get("tool_name") or data.get("toolName")
    if tool:
        name = str(tool).lower()
        mapped["toolName"] = TOOLS.get(name, name)
        args = dict(data.get("tool_input") or data.get("toolInput") or data.get("toolArgs") or {})
        if "notebook_path" in args:  # the guards look for path/file_path
            args.setdefault("path", args["notebook_path"])
        mapped["toolArgs"] = args
    return mapped


def _emit_session_start(context: str) -> None:
    sys.stdout.write(context or "")


def _emit_hook_json(event: str, result: dict) -> None:
    specific = {"hookEventName": event}
    decision = result.get("permissionDecision")
    if decision:
        specific["permissionDecision"] = decision
    reason = result.get("permissionDecisionReason")
    if reason:
        specific["permissionDecisionReason"] = reason
    context = result.get("additionalContext")
    if context:
        specific["additionalContext"] = context
    sys.stdout.write(json.dumps({"hookSpecificOutput": specific}, separators=(",", ":")))


def main(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    kind = {
        "SessionStart": "sessionStart",
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
        "SessionEnd": "sessionEnd",
    }.get(event)
    if not kind:
        return 0
    try:
        import hook_client

        payload = _map_payload(_read_stdin())
        try:
            import pulse_sidecar

            pulse_sidecar.record(
                payload,
                idle=(kind == "sessionEnd"),
                intent=payload.get("toolName") or kind,
            )
        except Exception:
            pass
        result = hook_client.decide(kind, payload)
        if not isinstance(result, dict):
            result = {}
        if kind == "sessionStart":
            context = result.get("additionalContext")
            if isinstance(context, str) and context.strip():
                hook_client._write_session_guidance(payload, decision_context=context)
                _emit_session_start(context)
            else:
                hook_client._write_session_guidance(payload, decision_context="")
                catalog = ROOT / "scripts" / "emit-command-catalog.sh"
                if catalog.is_file():
                    import subprocess

                    completed = subprocess.run(
                        ["bash", str(catalog)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                        env={**os.environ, "PYTHONPATH": ""},
                    )
                    extra = ""
                    try:
                        parsed = json.loads(completed.stdout or "{}")
                        extra = str(parsed.get("additionalContext") or "")
                    except (TypeError, ValueError):
                        extra = ""
                    _emit_session_start(extra)
        elif kind == "preToolUse":
            _emit_hook_json("PreToolUse", result)
        elif kind == "postToolUse":
            _emit_hook_json("PostToolUse", result)
        else:
            sys.stdout.write("{}")
    except Exception:
        if event == "SessionStart":
            sys.stdout.write("")
        else:
            sys.stdout.write("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
