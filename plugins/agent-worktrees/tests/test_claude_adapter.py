"""The Claude hook bridge (hooks/claude-adapter.py): one file, shipped by every
plugin with a Claude layer, folding Copilot hook answers into Claude's."""
import runpy
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[2]
COPIES = [PLUGINS / p / "hooks" / "claude-adapter.py"
          for p in ("agent-worktrees", "agent-dispatch", "context-handoff")]


def test_bridge_folds_copilot_answers():
    runpy.run_path(str(COPIES[0]))["self_test"]()


def test_bridge_copies_are_identical():
    assert len({copy.read_bytes() for copy in COPIES}) == 1
