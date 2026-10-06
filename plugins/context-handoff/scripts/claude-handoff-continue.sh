#!/usr/bin/env bash
# Open one Herdr Claude successor and submit the consume prompt for a saved baton.
# Outside Herdr, print the consume locator for a new Claude session or teammate.
set -euo pipefail

HERDR_BIN="${HERDR_BIN:-$HOME/.local/bin/herdr}"
SID=""
CWD="${HANDOFF_CWD:-$PWD}"
TOKEN=""
DRY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session-id) SID=$2; shift 2 ;;
    --cwd) CWD=$2; shift 2 ;;
    --handoff-token) TOKEN=$2; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *)
      printf 'claude-handoff continue: unknown argument %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

[[ -n "$TOKEN" ]] || TOKEN="handoff-${SID:-}"
[[ -n "$TOKEN" && "$TOKEN" != "handoff-" ]] || {
  printf 'claude-handoff continue: --handoff-token is required (or --session-id to derive it)\n' >&2
  exit 2
}

# Resolve the handoff dir with the same handoffDirFor the save/consume CLI uses.
CORE="$(cd "$(dirname "$0")/.." && pwd)/extensions/context-handoff/handoff-core.mjs"
DIR=$(node --input-type=module -e '
const { pathToFileURL } = await import("node:url");
const [core, cwd, sid] = process.argv.slice(1);
const { handoffDirFor } = await import(pathToFileURL(core).href);
const dir = handoffDirFor(cwd, sid || null);
if (!dir) process.exit(1);
console.log(dir);
' "$CORE" "$CWD" "$SID") || {
  printf 'claude-handoff continue: unable to resolve the handoff directory for %s\n' "$CWD" >&2
  exit 1
}
FILE="$DIR/$TOKEN.json"
MARKER="$DIR/$TOKEN.claude-launched"
[[ -f "$FILE" ]] || {
  printf 'claude-handoff continue: no saved handoff at %s\n' "$FILE" >&2
  exit 1
}

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

if [[ -f "$MARKER" ]]; then
  cat "$MARKER"
  exit 0
fi

PROMPT=$(printf '%s\n\n%s\n' \
  "/consume-handoff file:${TOKEN}" \
  "You are the handoff successor. Consume that locator and follow the stored brief. If the brief says the goal is paused, do not resume GPU work.")

if [[ "$DRY" -eq 1 ]]; then
  printf 'dry_run=1\n'
  printf 'kind=claude\n'
  printf 'handoff_token=%s\n' "$TOKEN"
  printf 'handoff_file=%s\n' "$FILE"
  printf 'herdr_start=herdr agent start --kind claude\n'
  printf 'consume_prompt_bytes=%s\n' "${#PROMPT}"
  if [[ "${HERDR_ENV:-}" == "1" && -n "${HERDR_PANE_ID:-}" ]]; then
    printf 'herdr_pane=1\nparent_pane=%s\n' "$HERDR_PANE_ID"
  else
    printf 'herdr_pane=0\n'
    printf 'fallback=new Claude session or teammate with /consume-handoff file:%s\n' "$TOKEN"
  fi
  exit 0
fi

if [[ "${HERDR_ENV:-}" != "1" || -z "${HERDR_PANE_ID:-}" ]]; then
  printf 'kind=claude\n'
  printf 'herdr_pane=0\n'
  printf 'handoff_token=%s\n' "$TOKEN"
  printf 'consume=/consume-handoff file:%s\n' "$TOKEN"
  printf 'cwd=%s\n' "$CWD"
  printf 'instruction=Open a new Claude Code session in cwd and run the consume line, or spawn a Claude teammate with that prompt. Do not grok-pane.\n'
  exit 0
fi

json_str() {
  python3 -c 'import json,sys
path=sys.argv[1]
value=json.load(sys.stdin)
for part in path.split("."):
    value=value[part]
if not isinstance(value,str) or not value:
    raise SystemExit(1)
print(value)' "$1"
}

direction=$( "$HERDR_BIN" pane layout --pane "$HERDR_PANE_ID" | python3 -c '
import json,sys
layout=json.load(sys.stdin)["result"]["layout"]
pane=next(p for p in layout["panes"] if p["pane_id"]==sys.argv[1])
rect=pane["rect"]
print("right" if rect["width"]>=160 and rect["width"]>=2*rect["height"] else "down")
' "$HERDR_PANE_ID")

split_response=$("$HERDR_BIN" pane split --current --direction "$direction" --cwd "$CWD" --no-focus) || {
  printf 'claude-handoff continue: unable to create a sibling pane\n' >&2
  exit 1
}
pane_id=$(printf '%s' "$split_response" | json_str 'result.pane.pane_id') || {
  printf 'claude-handoff continue: split response had no pane_id\n' >&2
  exit 1
}

cleanup() {
  "$HERDR_BIN" pane close "$pane_id" >/dev/null 2>&1 || true
}

"$HERDR_BIN" pane run "$pane_id" "printf '%s\n' CLAUDE_HANDOFF_SHELL_READY" >/dev/null || {
  cleanup
  printf 'claude-handoff continue: pane shell run failed\n' >&2
  exit 1
}
"$HERDR_BIN" pane wait-output "$pane_id" --match CLAUDE_HANDOFF_SHELL_READY --source recent --timeout 30000 >/dev/null || {
  cleanup
  printf 'claude-handoff continue: pane shell not ready\n' >&2
  exit 1
}

label=$(printf '%s' "$pane_id" | tr '[:upper:]' '[:lower:]' | tr ':' '-')
if ! agent_response=$("$HERDR_BIN" agent start "claude-handoff-${label}" --kind claude --pane "$pane_id" -- --dangerously-skip-permissions 2>&1); then
  printf '%s\n' "$agent_response" >&2
  cleanup
  printf 'claude-handoff continue: herdr agent start --kind claude failed\n' >&2
  exit 1
fi

kind=$(printf '%s' "$agent_response" | json_str 'result.agent.agent') || kind=""
if [[ "$kind" != "claude" ]]; then
  get_response=$("$HERDR_BIN" agent get "$pane_id") || true
  kind=$(printf '%s' "$get_response" | json_str 'result.agent.agent') || kind="$kind"
fi
if [[ "$kind" != "claude" ]]; then
  cleanup
  printf 'claude-handoff continue: pane hosts %s, expected claude\n' "${kind:-unknown}" >&2
  exit 1
fi

target=$(printf '%s' "$agent_response" | json_str 'result.agent.pane_id') || target="$pane_id"
"$HERDR_BIN" agent prompt "$target" "$PROMPT" >/dev/null || {
  cleanup
  printf 'claude-handoff continue: failed to submit consume prompt\n' >&2
  exit 1
}

{
  printf 'pane_handle=%s\n' "$pane_id"
  printf 'observed_process_kind=claude\n'
  printf 'handoff_token=%s\n' "$TOKEN"
  printf 'parent_pane=%s\n' "$HERDR_PANE_ID"
  printf 'consume=/consume-handoff file:%s\n' "$TOKEN"
} | tee "$MARKER"
