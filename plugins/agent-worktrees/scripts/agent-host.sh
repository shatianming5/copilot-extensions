# shellcheck shell=bash
# Sourced by bin/launch-session.sh and scripts/default-setup.sh.
#
# _agent_host prints which agent CLI a mux session should run: grok, claude or
# copilot. The nearest agent process among our ancestors wins, because host
# markers leak: a pane opened by grok-pane keeps GROK_PANE=1 even when Claude
# runs in it, and CLAUDECODE=1 survives into anything Claude spawns. Without
# an agent ancestor (the tmux server running default-setup, a plain terminal),
# an explicit AGENT_WORKTREES_HOST decides, then the Grok and Claude markers.
_agent_host() {
    local pid=$$ ppid comm i
    for ((i = 0; i < 32 && pid > 1; i++)); do
        read -r ppid comm < <(ps -o ppid=,comm= -p "$pid" 2>/dev/null) || break
        case "${comm##*/}" in
            claude) echo claude; return ;;
            grok) echo grok; return ;;
            copilot) echo copilot; return ;;
        esac
        pid=$ppid
    done
    case "${AGENT_WORKTREES_HOST:-}" in
        claude|grok|copilot) echo "$AGENT_WORKTREES_HOST"; return ;;
    esac
    if [[ -n "${GROK_SESSION_ID:-}" || "${GROK_PANE:-}" == "1" ]]; then
        echo grok
    elif [[ "${CLAUDECODE:-}" == "1" ]]; then
        echo claude
    else
        echo copilot
    fi
}
