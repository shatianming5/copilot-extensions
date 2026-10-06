"""hooks/claude-adapter.py maps Claude and Grok hook payloads onto the Copilot
payload hook_client and its case-sensitive guards expect."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "claude_adapter", Path(__file__).resolve().parents[1] / "hooks" / "claude-adapter.py")
adapter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(adapter)


def test_claude_tool_names_reach_the_guards_lowercased():
    p = adapter._map_payload({"session_id": "s", "cwd": "/w", "tool_name": "Write",
                              "tool_input": {"file_path": "/w/a"}})
    assert (p["sessionId"], p["toolName"], p["toolArgs"]) == ("s", "write", {"file_path": "/w/a"})
    assert adapter._map_payload({"tool_name": "MultiEdit"})["toolName"] == "edit"


def test_notebook_path_and_grok_payloads():
    n = adapter._map_payload({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/w/n"}})
    assert (n["toolName"], n["toolArgs"]["path"]) == ("edit", "/w/n")
    g = adapter._map_payload({"sessionId": "g", "cwd": "/w", "toolName": "run_terminal_command",
                              "toolInput": {"command": "ls"}})
    assert (g["sessionId"], g["toolName"], g["toolArgs"]) == ("g", "bash", {"command": "ls"})
