"""hooks/context-pressure.py: one nudge per threshold, re-armed below soft."""
import json
import runpy
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "context-pressure.py"


def test_nudges_once_per_level_and_rearms(tmp_path, monkeypatch):
    mod = runpy.run_path(str(HOOK))
    nudge = mod["nudge"]
    nudge.__globals__["STATE_DIR"] = tmp_path / "state"
    monkeypatch.setenv("CONTEXT_HANDOFF_TOKEN_LIMIT", "1000")
    transcript = tmp_path / "t.jsonl"

    def at(tokens):
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "model": "m", "usage": {"input_tokens": tokens}}}) + "\n")
        return nudge({"session_id": "s", "transcript_path": str(transcript)})

    assert at(100) == ""
    assert "soft threshold" in at(600)
    assert at(650) == ""
    assert "hard threshold" in at(800)
    assert at(600) == ""          # hard already covers soft
    assert at(100) == ""          # re-arm
    assert "soft threshold" in at(600)


def test_window_follows_env_then_model_catalog(monkeypatch):
    window = runpy.run_path(str(HOOK))["window"]
    for name in ("CONTEXT_HANDOFF_TOKEN_LIMIT", "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
                 "CLAUDE_CODE_DISABLE_1M_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    assert window("claude-opus-5-5") == 1_000_000
    assert window("claude-sonnet-4-6") == 200_000
    assert window("claude-sonnet-4-6[1m]") == 1_000_000
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONTEXT_TOKENS", "256000")
    assert window("claude-opus-5-5") == 256_000


def test_defaults_match_thresholds_mjs():
    mod = runpy.run_path(str(HOOK))
    text = (HOOK.parents[1] / "extensions" / "context-handoff" / "thresholds.mjs").read_text()
    assert f"SOFT_UTILIZATION_PERCENT = {mod['SOFT_PERCENT']};" in text
    assert f"HARD_UTILIZATION_PERCENT = {mod['HARD_PERCENT']};" in text


def test_repository_config_overrides_thresholds(tmp_path):
    thresholds = runpy.run_path(str(HOOK))["thresholds"]
    assert thresholds(str(tmp_path)) == (55, 70)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".context-handoff").mkdir()
    (tmp_path / ".context-handoff" / "config.yaml").write_text(
        "thresholds:\n  soft_percent: 40\n  hard_percent: 60\n")
    assert thresholds(str(tmp_path)) == (40, 60)
