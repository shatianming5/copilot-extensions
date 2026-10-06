#!/usr/bin/env bash
set -euo pipefail
ROOT="${CLAUDE_PLUGIN_ROOT:-${COPILOT_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}}"
exec python3 "$ROOT/scripts/handoff-mcp.py"
