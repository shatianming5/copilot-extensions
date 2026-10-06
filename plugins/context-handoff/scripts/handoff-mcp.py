#!/usr/bin/env python3
"""stdio MCP server exposing the handoff CLI to hosts without the extension.

Copilot gets the handoff tools from the context-handoff extension. Claude Code
(plugin .mcp.json) and Grok (config.toml mcp_servers) get the same store,
consume and cutover here, as tools over extensions/context-handoff/handoff-cli.mjs:

  save_handoff_prompt  -> handoff-cli save --no-task   (file store, prints the seed)
  consume_handoff      -> handoff-cli consume
  continue_handoff     -> handoff-cli continue --seed  (live cutover; a tmux/psmux
                          session relaunches on the calling host via
                          agent-worktrees, a Herdr pane cutover is Copilot-only)
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

TOOLS = [
    {
        "name": "save_handoff_prompt",
        "description": "Store a handoff brief (markdown you compose: objective, state, "
                       "decisions, next steps) without launching a successor. Returns "
                       "the HANDOFF_SEED a successor session starts from.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short topic"},
                "markdown": {"type": "string", "description": "Handoff brief"},
            },
            "required": ["title", "markdown"],
        },
    },
    {
        "name": "consume_handoff",
        "description": "Load a stored handoff once (marks it consumed) and return its brief.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handoff_id": {"type": "string"},
                "path": {"type": "string"},
            },
        },
    },
    {
        "name": "continue_handoff",
        "description": "Launch a successor session from a saved HANDOFF_SEED (live cutover).",
        "inputSchema": {
            "type": "object",
            "properties": {"seed": {"type": "string"}},
            "required": ["seed"],
        },
    },
]


def _session_id() -> str:
    for name in ("COPILOT_AGENT_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "GROK_SESSION_ID"):
        if os.environ.get(name):
            return os.environ[name]
    return ""


def _run_cli(args: list[str], stdin: str | None = None) -> str:
    cmd = ["node", str(CLI), *args, "--json"]
    if _session_id():
        cmd += ["--session-id", _session_id()]
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          timeout=90, check=False)
    text = (proc.stdout or "").strip() or (proc.stderr or "").strip() or f"exit {proc.returncode}"
    if proc.returncode != 0:
        raise RuntimeError(text)
    return text


def call(name: str, arguments: dict) -> str:
    if name == "save_handoff_prompt":
        markdown = str(arguments.get("markdown") or "")
        if not markdown.strip():
            raise ValueError("save_handoff_prompt needs markdown")
        return _run_cli(["save", "--no-task", "--title",
                         str(arguments.get("title") or "Continue the current work")], markdown)
    if name == "consume_handoff":
        if arguments.get("handoff_id"):
            return _run_cli(["consume", "--handoff-id", str(arguments["handoff_id"])])
        if arguments.get("path"):
            return _run_cli(["consume", "--path", str(arguments["path"])])
        raise ValueError("consume_handoff needs handoff_id or path")
    if name == "continue_handoff":
        if not arguments.get("seed"):
            raise ValueError("continue_handoff needs the HANDOFF_SEED from save_handoff_prompt")
        return _run_cli(["continue", "--seed", str(arguments["seed"])])
    raise ValueError(f"unknown tool {name}")


# Claude Code speaks newline-delimited JSON (MCP stdio spec); other hosts may
# use Content-Length framing. Reply in whichever framing the client used.
_LINE_MODE = False


def _read_message() -> dict | None:
    global _LINE_MODE
    headers: dict[bytes, bytes] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if not headers and line.lstrip().startswith(b"{"):
            _LINE_MODE = True
            return json.loads(line.decode("utf-8"))
        if line in (b"\r\n", b"\n"):
            if not headers:
                continue
            break
        key, _, value = line.partition(b":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get(b"content-length", b"0"))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def _write_message(payload: dict) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if _LINE_MODE:
        sys.stdout.buffer.write(raw + b"\n")
    else:
        sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    sys.stdout.buffer.flush()


def _result(req_id, text: str, error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": text}]}
    if error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def main() -> int:
    if not CLI.is_file():
        sys.stderr.write(f"handoff-mcp: missing CLI at {CLI}\n")
        return 1
    while (req := _read_message()) is not None:
        method, req_id = req.get("method"), req.get("id")
        if method == "initialize":
            _write_message({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "context-handoff", "version": "1"},
            }})
        elif method == "tools/list":
            _write_message({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            try:
                _write_message(_result(req_id, call(params.get("name"), params.get("arguments") or {})))
            except Exception as exc:  # report to the model, keep serving
                _write_message(_result(req_id, f"{type(exc).__name__}: {exc}", error=True))
        elif method == "ping":
            _write_message({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif req_id is not None:
            _write_message({"jsonrpc": "2.0", "id": req_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
