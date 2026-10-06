"""A guard the calling session disabled stays disabled when the resident
service (which does not share the session's environment) made the decision."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hook_client_switches", Path(__file__).resolve().parents[1] / "scripts" / "hook_client.py")
hook_client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hook_client)

ANCHOR = {"permissionDecision": "deny", "permissionDecisionReason": "anchor-write-guard: 'x' ..."}
STATELESS = {"permissionDecision": "deny", "permissionDecisionReason": "stateless-harness guard: ..."}


def _decide(monkeypatch, remote, **env):
    for name in ("ANCHOR_WRITE_GUARD", "CROSS_REPO_GUARD"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(hook_client, "_request", lambda *a, **k: dict(remote))
    return hook_client.decide("preToolUse", {"toolName": "write"}, home=Path("/nonexistent"))


def test_resident_deny_stands_without_a_switch(monkeypatch):
    assert _decide(monkeypatch, ANCHOR)["permissionDecision"] == "deny"


def test_anchor_switch_drops_only_the_anchor_deny(monkeypatch):
    assert "permissionDecision" not in _decide(monkeypatch, ANCHOR, ANCHOR_WRITE_GUARD="off")
    assert _decide(monkeypatch, STATELESS, ANCHOR_WRITE_GUARD="off")["permissionDecision"] == "deny"


def test_cross_repo_switch_covers_the_write_routing_family(monkeypatch):
    assert "permissionDecision" not in _decide(monkeypatch, STATELESS, CROSS_REPO_GUARD="0")
