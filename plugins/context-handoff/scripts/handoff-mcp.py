#!/usr/bin/env python3
"""stdio MCP server exposing Copilot-compatible context-handoff tools.

Used by Claude Code (.claude-plugin/plugin.json mcpServers) and Grok CLI (config.toml mcp_servers).
Wraps handoff-cli.mjs plus grok-handoff.sh continue --kind grok|claude.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT")
    or os.environ.get("COPILOT_PLUGIN_ROOT")
    or Path(__file__).resolve().parents[1]
)
CLI = ROOT / "extensions" / "context-handoff" / "handoff-cli.mjs"
CONTINUE = ROOT / "scripts" / "grok-handoff.sh"

TOOLS = [
    {
        "name": "generate_handoff_prompt",
        "description": "Collect extension-free handoff facts (git, cwd, session) as JSON.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "save_handoff_prompt",
        "description": "Store a handoff brief without launching a successor. Returns HANDOFF_SEED and HANDOFF_TOKEN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown": {"type": "string", "description": "Handoff markdown brief"},
                "prompt": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "consume_handoff",
        "description": "Consume a stored handoff once. Pass locator task:<id> or file:<id>.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "locator": {"type": "string"},
                "task_id": {"type": "string"},
                "handoff_id": {"type": "string"},
            },
        },
    },
    {
        "name": "trigger_handoff",
        "description": "Store (if needed) and signal pickup for a saved baton. Native-goal batons should use continue_handoff instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown": {"type": "string"},
                "handoff_token": {"type": "string"},
            },
        },
    },
    {
        "name": "continue_handoff",
        "description": "Freeze the saved baton and launch a successor. Pass the exact HANDOFF_SEED from save. Claude launches --kind claude; Grok uses grok-pane.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "seed": {"type": "string"},
                "kind": {"type": "string", "enum": ["claude", "grok"]},
            },
            "required": ["seed"],
        },
    },
    {
        "name": "retry_handoff_cutover",
        "description": "Retry the existing saved handoff identity without creating another baton.",
        "inputSchema": {
            "type": "object",
            "properties": {"seed": {"type": "string"}},
        },
    },
]


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
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if _LINE_MODE:
        sys.stdout.buffer.write(raw + b"\n")
    else:
        sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def _ok(req_id, text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}]},
    }


def _err(req_id, text: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": text}],
            "isError": True,
        },
    }


def _session_id() -> str:
    return (
        os.environ.get("GROK_SESSION_ID")
        or os.environ.get("COPILOT_AGENT_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or ""
    )


def _run_cli(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["node", str(CLI), *args, "--json"]
    sid = _session_id()
    if sid and "--session-id" not in args:
        cmd.extend(["--session-id", sid])
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=os.environ.get("PWD") or os.getcwd(),
        env=env,
    )


def _successor_kind(explicit: str | None) -> str:
    if explicit in ("claude", "grok"):
        return explicit
    if os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    return "grok"


def _token_from_seed(seed: str) -> tuple[str, str]:
    text = (seed or "").strip()
    match = re.search(r"Recovery:\s*context-handoff\s+(file|task):([A-Za-z0-9._-]+)", text)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r"HANDOFF_TOKEN:\s*([A-Za-z0-9._-]+)", text)
    if match:
        return "file", match.group(1)
    match = re.match(r"(file|task):([A-Za-z0-9._-]+)\s*$", text)
    if match:
        return match.group(1), match.group(2)
    if re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return "file", text
    raise ValueError("could not parse HANDOFF_TOKEN / file:<id> / task:<id> from seed")


def _continue(seed: str, kind: str | None) -> subprocess.CompletedProcess:
    _kind, token = _token_from_seed(seed)
    cmd = ["bash", str(CONTINUE), "continue", "--kind", _successor_kind(kind), "--handoff-token", token]
    sid = _session_id()
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    if sid:
        env.setdefault("GROK_SESSION_ID", sid)
        env.setdefault("CLAUDE_SESSION_ID", sid)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        cwd=os.environ.get("PWD") or os.getcwd(),
        env=env,
    )


def _handle_call(name: str, arguments: dict) -> str:
    arguments = arguments or {}
    if name == "generate_handoff_prompt":
        proc = _run_cli(["facts"])
    elif name == "save_handoff_prompt":
        title = arguments.get("title") or "Continue the current work"
        markdown = arguments.get("markdown") or arguments.get("prompt") or ""
        if not str(markdown).strip():
            raise ValueError("save_handoff_prompt requires markdown/prompt")
        proc = _run_cli(["save", "--no-task", "--title", title], stdin=str(markdown))
    elif name == "consume_handoff":
        locator = arguments.get("locator")
        if not locator:
            if arguments.get("task_id"):
                locator = f"task:{arguments['task_id']}"
            elif arguments.get("handoff_id"):
                locator = f"file:{arguments['handoff_id']}"
        if not locator:
            raise ValueError("consume_handoff requires locator, task_id, or handoff_id")
        proc = _run_cli(["consume", "--locator", str(locator)])
    elif name == "trigger_handoff":
        args = ["trigger", "--no-task"]
        if arguments.get("title"):
            args.extend(["--title", str(arguments["title"])])
        if arguments.get("handoff_token"):
            args.extend(["--handoff-token", str(arguments["handoff_token"])])
            proc = _run_cli(args)
        else:
            markdown = arguments.get("markdown") or arguments.get("prompt") or ""
            if not str(markdown).strip():
                raise ValueError("trigger_handoff requires markdown or handoff_token")
            proc = _run_cli(args, stdin=str(markdown))
    elif name == "continue_handoff":
        proc = _continue(str(arguments.get("seed") or ""), arguments.get("kind"))
    elif name == "retry_handoff_cutover":
        seed = arguments.get("seed") or ""
        if not seed:
            raise ValueError("retry_handoff_cutover needs the existing seed")
        proc = _continue(str(seed), arguments.get("kind"))
    else:
        raise ValueError(f"unknown tool {name}")
    text = (proc.stdout or "").strip() or (proc.stderr or "").strip() or f"exit {proc.returncode}"
    if proc.returncode != 0:
        raise RuntimeError(text)
    return text


def main() -> int:
    if not CLI.is_file():
        sys.stderr.write(f"handoff-mcp: missing CLI at {CLI}\n")
        return 1
    while True:
        req = _read_message()
        if req is None:
            return 0
        method = req.get("method")
        req_id = req.get("id")
        if method == "initialize":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "context-handoff", "version": "0.1.1-dev16"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write_message({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                _write_message(_ok(req_id, _handle_call(name, arguments)))
            except Exception as exc:
                _write_message(_err(req_id, f"{type(exc).__name__}: {exc}"))
        elif method == "ping":
            _write_message({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif req_id is not None:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
