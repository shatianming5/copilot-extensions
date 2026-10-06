#!/usr/bin/env bash
# Default / normalized session setup script for repos.
#
# Used by agent-worktrees as the normalized launcher. Prepends any
# repo-provided session PATH directories, runs an optional repo setup hook
# (vault / MCP; context passed by argument, not ambient env), displays a brief
# welcome banner, and launches Copilot, Grok or Claude for the current host.
#
# A repo opts into this normalized flow by declaring a setup_hook in its
# .agent-worktrees/config.yaml. When absent, this script is still used as the
# fallback launcher for repos without their own tools/setup/setup.sh.
#
# The launcher (launch-session.sh) sets the working directory before calling
# this script. Context (project) resolves from CWD, git-like -- no ambient
# WORKTREE_PROJECT is required.

set -euo pipefail

MACHINE="${HOSTNAME:-$(hostname)}"
RECOVERY=false
SETUP_HOOK=""
SESSION_PATH=""
ENV_SCRIPT=""
COPILOT_PATH_OVERRIDE=""
CONFIG_ROOT=""
RUNTIME_PYTHON=""
COPILOT_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --machine)      MACHINE="$2"; shift 2 ;;
        --recovery)     RECOVERY=true; shift ;;
        --setup-hook)   SETUP_HOOK="$2"; shift 2 ;;
        --session-path) SESSION_PATH="$2"; shift 2 ;;
        --env-script)   ENV_SCRIPT="$2"; shift 2 ;;
        --copilot-path) COPILOT_PATH_OVERRIDE="$2"; shift 2 ;;
        --config-root)  CONFIG_ROOT="$2"; shift 2 ;;
        --runtime-python) RUNTIME_PYTHON="$2"; shift 2 ;;
        *)              COPILOT_ARGS+=("$1"); shift ;;
    esac
done

# In --stdio (ACP) mode, stdout is the JSON-RPC channel; keep all human-facing
# output (banner, hook output) off it. `say` and the hook redirect to stderr.
STDIO=false
for _a in "${COPILOT_ARGS[@]:-}"; do
    [[ "$_a" == "--stdio" ]] && STDIO=true
done
say() { if $STDIO; then echo "$@" >&2; else echo "$@"; fi; }

# -- Runtime --------------------------------------------------------------
_awresolve="$HOME/.agent-worktrees/bin/resolve-runtime.sh"
[ -f "$_awresolve" ] && . "$_awresolve"
_AW_PY="${RUNTIME_PYTHON:-${AW_PY:-}}"

# -- Guarded setup configuration root ------------------------------------
# setup_hook is the supported cooperative writer boundary. Resolve its
# machine-local root, or validate an explicit caller-supplied root, before the
# hook gets a chance to execute.
if [[ -n "$SETUP_HOOK" && "$RECOVERY" != true ]]; then
    if [[ -n "$_AW_PY" && "$_AW_PY" != */* ]]; then
        _resolved_aw_py="$(command -v -- "$_AW_PY" 2>/dev/null || true)"
        [[ -n "$_resolved_aw_py" ]] && _AW_PY="$_resolved_aw_py"
    fi
    if [[ -z "$_AW_PY" || ! -x "$_AW_PY" ]]; then
        echo "ERROR: agent-worktrees runtime is unavailable; cannot validate the setup config root." >&2
        exit 3
    fi
    _config_root_args=(-m agent_worktrees config-root)
    if [[ -n "$CONFIG_ROOT" ]]; then
        _config_root_args+=(--destination "$CONFIG_ROOT")
    fi
    set +e
    _guarded_config_root="$(PYTHONPATH="" "$_AW_PY" -I "${_config_root_args[@]}")"
    _config_root_rc=$?
    set -e
    if [[ $_config_root_rc -ne 0 ]]; then
        exit "$_config_root_rc"
    fi
    if [[ -z "$_guarded_config_root" ]]; then
        echo "ERROR: agent-worktrees returned an empty setup config root." >&2
        exit 3
    fi
fi

# -- Session PATH prepend (generic; repo-provided dirs) -------------------
if [[ -n "$SESSION_PATH" ]]; then
    export PATH="${SESSION_PATH}:${PATH}"
fi

# -- Enlistment env priming (repo env_script) -----------------------------
# Source the repo's env-priming script so the vars it exports reach the Copilot
# exec below (UNLIKE the setup hook, which runs as a child and loses its env).
# `set -a` auto-exports; the script's own stdout is redirected to stderr to keep
# the ACP channel clean. Runs even in recovery -- the build env is always needed.
if [[ -n "$ENV_SCRIPT" ]]; then
    if [[ -f "$ENV_SCRIPT" ]]; then
        say "  Env:      $ENV_SCRIPT"
        set -a
        # shellcheck disable=SC1090
        . "$ENV_SCRIPT" >/dev/null 2>&1 || echo "  WARN: env_script exited non-zero; continuing." >&2
        set +a
    else
        echo "  WARN: env_script not found: $ENV_SCRIPT" >&2
    fi
fi

# -- Environment ----------------------------------------------------------
# Resolve the project from CWD (git-like); fall back to the directory name if
# the CLI is unavailable (e.g. recovery mode).
PROJECT=""
if [[ -x "$_AW_PY" ]]; then
    PROJECT="$(PYTHONPATH="" "$_AW_PY" -m agent_worktrees get project 2>/dev/null || true)"
fi
[[ -z "$PROJECT" ]] && PROJECT="$(basename "$PWD")"
export WORKTREE_MACHINE="$MACHINE"

# -- Repo setup hook (vault / MCP; repo-specific) -------------------------
# Runs before launch, context passed by argument. Skipped in recovery so a
# broken hook can never lock the operator out of a recovery session. A
# non-zero exit warns but does not abort the launch.
if [[ -n "$SETUP_HOOK" && "$RECOVERY" != true ]]; then
    export AGENT_WORKTREES_CONFIG_ROOT="$_guarded_config_root"
    if [[ -f "$SETUP_HOOK" ]]; then
        say "  Setup:    $SETUP_HOOK"
        if $STDIO; then
            # Keep the hook's stdout off the ACP channel.
            if ! bash "$SETUP_HOOK" --machine "$MACHINE" >&2; then
                echo "  WARN: setup hook exited non-zero; continuing to launch." >&2
            fi
        elif ! bash "$SETUP_HOOK" --machine "$MACHINE"; then
            echo "  WARN: setup hook exited non-zero; continuing to launch." >&2
        fi
    else
        echo "  WARN: setup hook not found: $SETUP_HOOK" >&2
    fi
fi

# -- Welcome banner -------------------------------------------------------
BRANCH=$(git branch --show-current 2>/dev/null || echo "(detached)")
# Guard against set -e: outside a git repo (e.g. Bare resume launches Copilot in
# ~/), `git status` exits 128 and would abort this launcher before `exec copilot`.
DIRTY=$(git status --porcelain 2>/dev/null || true)
STATUS="clean"
[[ -n "$DIRTY" ]] && STATUS="dirty"

say ""
say "  Project:  $PROJECT"
say "  Branch:   $BRANCH ($STATUS)"
say "  Machine:  $MACHINE"
say "  Path:     $PWD"
say ""

# -- Launch Copilot, Grok or Claude --------------------------------------
# shellcheck source=agent-host.sh
. "${BASH_SOURCE[0]%/*}/agent-host.sh"
AGENT_HOST="$(_agent_host)"
_is_grok_host() { [[ "$AGENT_HOST" == "grok" ]]; }

_resolve_grok_bin() {
    local override="${COPILOT_PATH_OVERRIDE:-}" base
    if [[ -n "$override" ]]; then
        base="${override##*/}"
        if [[ "$base" == "grok" && -x "$override" ]]; then
            printf '%s\n' "$override"
            return 0
        fi
    fi
    if [[ -n "${GROK_BIN:-}" && -x "$GROK_BIN" ]]; then
        printf '%s\n' "$GROK_BIN"
        return 0
    fi
    if [[ -x "$HOME/.grok/bin/grok" ]]; then
        printf '%s\n' "$HOME/.grok/bin/grok"
        return 0
    fi
    type -P grok 2>/dev/null || true
}

_grok_cli_args() {
    GROK_ARGS=()
    local skip=0 arg
    for arg in "${COPILOT_ARGS[@]+"${COPILOT_ARGS[@]}"}"; do
        if [[ "$skip" == 1 ]]; then
            skip=0
            continue
        fi
        case "$arg" in
            --allow-all)
                GROK_ARGS+=(--always-approve)
                ;;
            --stdio|--acp|--experimental)
                ;;
            --ahp|--context|--mode|--name|--worker-selectors|--copilot-path|--plugin-dir)
                skip=1
                ;;
            --ahp=*|--context=*|--mode=*|--name=*|--worker-selectors=*|--copilot-path=*|--plugin-dir=*)
                ;;
            --resume=*)
                GROK_ARGS+=(--resume "${arg#--resume=}")
                ;;
            *)
                GROK_ARGS+=("$arg")
                ;;
        esac
    done
}

_is_claude_host() { [[ "$AGENT_HOST" == "claude" ]]; }

# Map the Copilot launch args onto Claude Code's CLI. Copilot session ids are
# not Claude ids, so a resume becomes --continue (latest session in this
# worktree's directory); a handoff seed (-i) becomes the initial prompt.
# Copilot-only flags are dropped.
_claude_cli_args() {
    CLAUDE_ARGS=()
    local prompt="" arg
    local -a rest=("${COPILOT_ARGS[@]+"${COPILOT_ARGS[@]}"}")
    local i=0 n=${#rest[@]}
    while (( i < n )); do
        arg="${rest[i]}"
        case "$arg" in
            --allow-all|--allow-all-tools|--yolo)
                CLAUDE_ARGS+=(--dangerously-skip-permissions) ;;
            --resume|--continue)
                CLAUDE_ARGS+=(--continue)
                if [[ "$arg" == "--resume" && $((i + 1)) -lt $n && "${rest[i+1]}" != -* ]]; then
                    i=$((i + 1))
                fi ;;
            --resume=*)
                CLAUDE_ARGS+=(--continue) ;;
            -i|--interactive|-p|--prompt)
                i=$((i + 1)); prompt="${rest[i]:-}" ;;
            --model|--add-dir)
                CLAUDE_ARGS+=("$arg" "${rest[i+1]:-}"); i=$((i + 1)) ;;
            --model=*|--add-dir=*)
                CLAUDE_ARGS+=("$arg") ;;
            --ahp|--context|--mode|--name|--worker-selectors|--copilot-path|--plugin-dir|--agent)
                i=$((i + 1)) ;;
            *) ;;
        esac
        i=$((i + 1))
    done
    if [[ -n "$prompt" ]]; then CLAUDE_ARGS+=("$prompt"); fi
    return 0
}

if _is_claude_host; then
    claude_bin="${CLAUDE_BIN:-$(type -P claude 2>/dev/null || true)}"
    if [[ -z "$claude_bin" || ! -x "$claude_bin" ]]; then
        echo "ERROR: Claude host mux needs an executable claude; Copilot was not started." >&2
        exit 2
    fi
    # The parent Claude Code's markers would make the new session look nested.
    unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION_ID
    export AGENT_WORKTREES_HOST=claude
    _claude_cli_args
    say "Launching Claude..."
    exec "$claude_bin" ${CLAUDE_ARGS[@]+"${CLAUDE_ARGS[@]}"}
fi

if _is_grok_host; then
    grok_bin=$(_resolve_grok_bin)
    if [[ -z "$grok_bin" || ! -x "$grok_bin" ]]; then
        echo "ERROR: Grok host mux needs an executable grok; Copilot was not started." >&2
        exit 2
    fi
    export GROK_HOME="${GROK_HOME:-$HOME/.grok}"
    export GROK_PANE=1
    export AGENT_WORKTREES_HOST=grok
    _grok_cli_args
    say "Launching Grok..."
    exec "$grok_bin" ${GROK_ARGS[@]+"${GROK_ARGS[@]}"}
fi
if [[ -n "$COPILOT_PATH_OVERRIDE" ]]; then
    if command -v "$COPILOT_PATH_OVERRIDE" &>/dev/null; then
        exec "$COPILOT_PATH_OVERRIDE" "${COPILOT_ARGS[@]}"
    else
        echo "ERROR: Configured Copilot executable not found: $COPILOT_PATH_OVERRIDE" >&2
        exit 1
    fi
elif command -v copilot &>/dev/null; then
    exec copilot "${COPILOT_ARGS[@]}"
elif command -v gh &>/dev/null; then
    exec gh copilot "${COPILOT_ARGS[@]}"
else
    echo "ERROR: Neither copilot nor gh found on PATH." >&2
    exit 1
fi
