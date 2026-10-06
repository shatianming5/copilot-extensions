"""Native-goal handoff support for ``handoff-cutover`` (context-handoff fork).

context-handoff's native-source.mjs freezes the source's native goal into a
checkpoint and asks for a cutover with ``--native-handoff <checkpoint>
--native-launcher <native-launch.mjs>``. The successor then starts through that
payload-local launcher with no seed prompt; the source extension owns freeze
and admission, and the status monitor retires the predecessor only once the
native admission completed (``retire_ready``).
"""
from __future__ import annotations

import json
from pathlib import Path


def plan(args, session_id: str | None, headless: bool):
    """Validate the native arguments: ``(None, None)`` for a plain cutover,
    ``(native, None)`` for a frozen native handoff, else ``(None, failure)``."""
    checkpoint = getattr(args, "native_handoff", None)
    launcher = getattr(args, "native_launcher", None)
    if not checkpoint and not launcher:
        return None, None
    if not checkpoint or not launcher:
        return None, {"ok": False, "error": "Native handoff requires both checkpoint and launcher."}
    if headless:
        return None, {"ok": False, "error": "Native handoff needs a mux pane; --headless was given."}
    try:
        record = json.loads(Path(checkpoint).read_text(encoding="utf-8"))
        goal = record["nativeGoal"]
        if goal.get("permissionMode") != "allow-all":
            raise ValueError(
                f"Native handoff cannot preserve {goal.get('permissionMode')}; no pane was created."
            )
        if record["sessionId"] != session_id:
            raise ValueError("Native checkpoint source does not match the cutover owner.")
        if goal["phase"] != "frozen":
            raise ValueError("Native successor is already being prepared; do not replay.")
        successor = goal["successorSessionId"]
    except (OSError, ValueError, KeyError) as exc:
        return None, {"ok": False, "error": str(exc)}
    return {"checkpoint": checkpoint, "launcher": launcher, "successor": successor}, None


def wrap(native, launch_cmd: list[str]) -> list[str]:
    """Run the successor through the native launcher (unchanged when plain)."""
    if not native:
        return launch_cmd
    return [
        "node", native["launcher"], "--checkpoint", native["checkpoint"],
        "--cli", launch_cmd[0], "--", *launch_cmd[1:],
        "--session-id", native["successor"],
    ]


def marker(native, **extra) -> dict:
    """Fields that tag spawn events and results of a native cutover."""
    return {"native_handoff": native["checkpoint"], **extra} if native else {}


def retire_ready(spawn: dict, handoff, record, successor_session: str, read_request) -> bool:
    """A native predecessor may retire only after admission completed, the
    successor hydrated the goal, is linked as the handoff's successor, and
    owns the worktree head. Plain spawns are always ready."""
    if not spawn.get("native_handoff"):
        return True
    goal = (read_request(spawn["native_handoff"]) or {}).get("nativeGoal") or {}
    return bool(
        goal.get("admissionComplete")
        and goal.get("hydratedBySession") == successor_session
        and getattr(handoff, "successor", None) == successor_session
        and record.resolved_head_session == successor_session
    )
