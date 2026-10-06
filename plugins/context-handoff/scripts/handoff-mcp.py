#!/usr/bin/env python3
"""stdio MCP server giving Claude Code and Grok the extension's handoff tools.

Copilot gets generate/save/consume/continue_handoff from the context-handoff
extension. Hosts without it (Claude Code via .claude-plugin/plugin.json, Grok
via the same manifest or config.toml) get the same four tools, with the same
names and arguments, so the context-handoff skill reads the same everywhere:

  generate_handoff_prompt  session facts (cwd, git state) to write the brief from
  save_handoff_prompt      handoff-cli save: agent-dispatch task, else file store
  consume_handoff          agent-dispatch consume (task_id) / handoff-cli consume
  continue_handoff         handoff-cli continue: live cutover. A tmux/psmux
                           session relaunches on the calling host through
                           agent-worktrees; a Herdr pane cutover is Copilot-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT")
    or os.environ.get("COPILOT_PLUGIN_ROOT")
    or Path(__file__).resolve().parents[1]
)
CLI = ROOT / "extensions" / "context-handoff" / "handoff-cli.mjs"


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


TOOLS = [
    {
        "name": "generate_handoff_prompt",
        "description": "Generate session facts (cwd, branch, git status, recent "
                       "commits) to compose a continuation handoff from.",
        "inputSchema": {"type": "object", "properties": {
            "summary": _string("Optional summary of what was accomplished."),
            "next_steps": _string("Optional description of what should happen next."),
        }},
    },
    {
        "name": "save_handoff_prompt",
        "description": "Store the composed handoff markdown (an agent-dispatch task "
                       "when available, else a one-time file) and return the "
                       "HANDOFF_SEED a successor starts from.",
        "inputSchema": {"type": "object", "properties": {
            "prompt_text": _string("The complete handoff markdown."),
            "title": _string("Short topic."),
            "prompt": _string("Alias of prompt_text."),
        }},
    },
    {
        "name": "consume_handoff",
        "description": "Consume a stored handoff exactly once: task_id for an "
                       "agent-dispatch handoff, handoff_id or path for a file one.",
        "inputSchema": {"type": "object", "properties": {
            "task_id": _string("agent-dispatch task id."),
            "handoff_id": _string("File-backed handoff id."),
            "path": _string("Explicit file-backed handoff JSON path."),
            "defer_complete": {"type": "boolean", "description":
                               "Task handoffs: complete the task only when the goal is reached."},
        }},
    },
    {
        "name": "continue_handoff",
        "description": "Live-cutover the current session to a successor seeded "
                       "with the HANDOFF_SEED from save_handoff_prompt.",
        "inputSchema": {"type": "object", "properties": {
            "seed": _string("The exact HANDOFF_SEED."),
        }, "required": ["seed"]},
    },
]


def _session_id() -> str:
    """The calling host's session id (Copilot, Claude Code or Grok)."""
    for name in ("COPILOT_AGENT_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "GROK_SESSION_ID"):
        if os.environ.get(name):
            return os.environ[name]
    return ""


def _run(cmd: list[str], stdin: str | None = None) -> str:
    """Run a command; its stdout on success, else raise with its output."""
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          timeout=90, check=False)
    text = (proc.stdout or "").strip() or (proc.stderr or "").strip() or f"exit {proc.returncode}"
    if proc.returncode != 0:
        raise RuntimeError(text)
    return text


def _handoff_cli(args: list[str], stdin: str | None = None) -> str:
    sid = ["--session-id", _session_id()] if _session_id() else []
    return _run(["node", str(CLI), *args, "--json", *sid], stdin)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              timeout=10, check=False).stdout.strip()
    except OSError:
        return ""


def call(name: str, arguments: dict) -> str:
    """Dispatch one tools/call to the handoff CLI or agent-dispatch."""
    if name == "generate_handoff_prompt":
        return json.dumps({
            "sessionId": _session_id(),
            "cwd": os.getcwd(),
            "branch": _git("branch", "--show-current"),
            "status": _git("status", "--short").splitlines()[:40],
            "recentCommits": _git("log", "--oneline", "-5").splitlines(),
            "summary": arguments.get("summary") or "",
            "nextSteps": arguments.get("next_steps") or "",
            "instructions": "Compose the handoff markdown (objective, state, decisions, "
                            "remaining work) from these facts and your own context, "
                            "then call save_handoff_prompt with prompt_text.",
        }, indent=2)
    if name == "save_handoff_prompt":
        text = str(arguments.get("prompt_text") or arguments.get("prompt") or "")
        if not text.strip():
            raise ValueError("save_handoff_prompt needs prompt_text")
        save = ["save", "--title", str(arguments.get("title") or "Continue the current work")]
        try:
            return _handoff_cli(save, text)
        except RuntimeError:  # no agent-dispatch task store here: one-time file
            return _handoff_cli([*save, "--no-task"], text)
    if name == "consume_handoff":
        if arguments.get("task_id"):
            defer = ["--defer-complete"] if arguments.get("defer_complete") else []
            return _run(["agent-dispatch", "consume", str(arguments["task_id"]), *defer])
        if arguments.get("handoff_id"):
            return _handoff_cli(["consume", "--handoff-id", str(arguments["handoff_id"])])
        if arguments.get("path"):
            return _handoff_cli(["consume", "--path", str(arguments["path"])])
        raise ValueError("consume_handoff needs task_id, handoff_id or path")
    if name == "continue_handoff":
        if not arguments.get("seed"):
            raise ValueError("continue_handoff needs the HANDOFF_SEED from save_handoff_prompt")
        return _handoff_cli(["continue", "--seed", str(arguments["seed"])])
    raise ValueError(f"unknown tool {name}")


def _reply(req_id, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
    sys.stdout.flush()


def main() -> int:
    """Serve newline-delimited JSON-RPC (MCP stdio) until stdin closes."""
    if not CLI.is_file():
        sys.stderr.write(f"handoff-mcp: missing CLI at {CLI}\n")
        return 1
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        method, req_id = req.get("method"), req.get("id")
        if method == "initialize":
            _reply(req_id, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                            "serverInfo": {"name": "context-handoff", "version": "1"}})
        elif method == "tools/list":
            _reply(req_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = req.get("params") or {}
            try:
                text, error = call(params.get("name"), params.get("arguments") or {}), False
            except Exception as exc:  # report to the model, keep serving
                text, error = f"{type(exc).__name__}: {exc}", True
            _reply(req_id, {"content": [{"type": "text", "text": text}], "isError": error})
        elif method == "ping":
            _reply(req_id, {})
        elif req_id is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {
                "code": -32601, "message": f"Method not found: {method}"}}) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
