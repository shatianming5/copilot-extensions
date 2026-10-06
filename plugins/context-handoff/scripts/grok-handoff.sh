#!/usr/bin/env bash
# Grok wrapper around the native-goal context-handoff CLI (extension-free).
set -euo pipefail

ROOT="${CONTEXT_HANDOFF_ROOT:-${CLAUDE_PLUGIN_ROOT:-${COPILOT_PLUGIN_ROOT:-${PLUGIN_ROOT:-${GROK_PLUGIN_ROOT:-}}}}}"
if [[ -z "$ROOT" || ! -f "$ROOT/plugin.json" ]]; then
  # This script's own plugin copy, not whichever host installed one elsewhere.
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
CLI="$ROOT/extensions/context-handoff/handoff-cli.mjs"
SID="${GROK_SESSION_ID:-${COPILOT_AGENT_SESSION_ID:-${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}}}"
CWD="${HANDOFF_CWD:-$PWD}"

if [[ ! -f "$CLI" ]]; then
  printf 'grok-handoff: missing CLI at %s\n' "$CLI" >&2
  exit 1
fi

cmd="${1:-help}"
shift || true
KIND="${HANDOFF_SUCCESSOR_KIND:-}"

need_sid() {
  if [[ -z "$SID" ]]; then
    printf 'grok-handoff: set GROK_SESSION_ID or COPILOT_AGENT_SESSION_ID, or pass --session-id\n' >&2
    exit 2
  fi
}

case "$cmd" in
  facts)
    exec node "$CLI" facts --json --session-id "${SID:-}" --cwd "$CWD" "$@"
    ;;
  save)
    need_sid
    # File-backed store is the Grok-safe default. Adopted agent-worktrees
    # task storage is opt-in via HANDOFF_PREFER_TASK=1 (do not pass --no-task).
    if [[ "${HANDOFF_PREFER_TASK:-}" == "1" ]]; then
      exec node "$CLI" save --json --session-id "$SID" --cwd "$CWD" "$@"
    fi
    exec node "$CLI" save --json --no-task --session-id "$SID" --cwd "$CWD" "$@"
    ;;
  trigger)
    need_sid
    if [[ "${HANDOFF_PREFER_TASK:-}" == "1" ]]; then
      exec node "$CLI" trigger --json --session-id "$SID" --cwd "$CWD" "$@"
    fi
    exec node "$CLI" trigger --json --no-task --session-id "$SID" --cwd "$CWD" "$@"
    ;;
  continue)
    extra=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --kind) KIND=$2; shift 2 ;;
        *) extra+=("$1"); shift ;;
      esac
    done
    if [[ -z "$KIND" ]]; then
      if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" || -n "${CLAUDE_SESSION_ID:-}" || -n "${CLAUDE_CODE_SESSION_ID:-}" ]]; then
        KIND=claude
      else
        KIND=grok
      fi
    fi
    if [[ "$KIND" == "claude" ]]; then
      token_set=0
      for ((i=0; i<${#extra[@]}; i++)); do
        if [[ "${extra[$i]}" == "--handoff-token" ]]; then
          token_set=1
          break
        fi
      done
      if [[ "$token_set" -eq 0 ]]; then
        need_sid
      fi
      exec bash "$ROOT/scripts/claude-handoff-continue.sh" --session-id "${SID:-}" --cwd "$CWD" "${extra[@]}"
    fi
    need_sid
    exec bash "$ROOT/scripts/grok-handoff-continue.sh" --session-id "$SID" --cwd "$CWD" "${extra[@]}"
    ;;
  consume)
    need_sid
    exec node "$CLI" consume --json --session-id "$SID" --cwd "$CWD" "$@"
    ;;
  help|-h|--help)
    cat <<EOF
grok-handoff — Grok entry to context-handoff CLI

  grok-handoff facts
  grok-handoff save --title <t> --prompt-file <f>
  grok-handoff trigger --title <t> --prompt-file <f>
  grok-handoff trigger --handoff-token <id>
  grok-handoff continue --handoff-token <id>
  grok-handoff continue --kind claude --handoff-token <id>
  grok-handoff consume --locator task:<id>|file:<id>

Session: GROK_SESSION_ID or COPILOT_AGENT_SESSION_ID
CLI: $CLI
EOF
    ;;
  *)
    printf 'grok-handoff: unknown command %s\n' "$cmd" >&2
    exit 2
    ;;
esac
