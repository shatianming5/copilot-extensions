#!/usr/bin/env bash
# Open one Herdr Grok successor and submit the consume prompt for a saved baton.
set -euo pipefail

SID=""
CWD="${HANDOFF_CWD:-$PWD}"
TOKEN=""
PANE_BIN="${GROK_PANE_BIN:-$HOME/.local/bin/grok-pane}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session-id) SID=$2; shift 2 ;;
    --cwd) CWD=$2; shift 2 ;;
    --handoff-token) TOKEN=$2; shift 2 ;;
    *)
      printf 'grok-handoff continue: unknown argument %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

[[ -n "$SID" ]] || {
  printf 'grok-handoff continue: --session-id is required\n' >&2
  exit 2
}
[[ -n "$TOKEN" ]] || TOKEN="handoff-${SID}"
[[ "${HERDR_ENV:-}" == "1" && -n "${HERDR_PANE_ID:-}" ]] || {
  printf 'grok-handoff continue: run this inside the predecessor Herdr pane\n' >&2
  exit 2
}

STATE=$(python3 - "$CWD" <<'PY'
import os
import sys
from pathlib import Path
cwd = Path(sys.argv[1]).resolve()
home = Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok"))
print(home / "context-handoff" / "checkouts" / cwd.relative_to(cwd.anchor))
PY
)
FILE="$STATE/handoff/$TOKEN.json"
MARKER="$STATE/handoff/$TOKEN.launched"
[[ -f "$FILE" ]] || {
  printf 'grok-handoff continue: no saved handoff at %s\n' "$FILE" >&2
  exit 1
}
if [[ -f "$MARKER" ]]; then
  cat "$MARKER"
  exit 0
fi

mapfile -t claim < <(python3 - "$FILE" <<'PY'
import json
import sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
if record.get("consumed"):
    print("consumed")
    print(record.get("consumedBySession") or "")
else:
    print("open")
    print("")
PY
)
if [[ "${claim[0]}" == "consumed" ]]; then
  printf 'already_consumed=%s\n' "${claim[1]}"
  exit 0
fi

task=$(mktemp)
trap 'rm -f "$task"' EXIT
cat > "$task" <<EOF
/consume-handoff file:${TOKEN}

You are the handoff successor. Consume that locator and follow the stored brief. If the brief says the goal is paused, do not resume GPU work.
EOF

launch_out=$("$PANE_BIN" launch --role coordinator --cwd "$CWD" --host local --task-file "$task")
printf '%s\n' "$launch_out" | tee "$MARKER"
