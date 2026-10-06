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
