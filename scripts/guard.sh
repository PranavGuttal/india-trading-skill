#!/usr/bin/env bash
# PreToolUse guard for Groww MCP tools (plugin hook). Uses the first Python
# that can import the toolkit's packages and runs the live guard. If none can,
# it DENIES the call (fail closed): read-only Groww tools then also wait
# until `scripts/india.py --setup` has been run.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "$INDIA_TRADING_VENV" ]; then UV="$INDIA_TRADING_VENV"
elif [ -n "$LOCALAPPDATA" ]; then UV="$LOCALAPPDATA/india-trading/venv"
else UV="${XDG_DATA_HOME:-$HOME/.local/share}/india-trading/venv"; fi
for PY in python python3 "$UV/Scripts/python.exe" "$UV/bin/python" "$ROOT/.venv/Scripts/python.exe" "$ROOT/.venv/bin/python"; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c "import numpy, pandas, pydantic, yaml" >/dev/null 2>&1; then
    exec "$PY" "$ROOT/scripts/india.py" --guard
  fi
done
echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"live guard: no Python with the toolkit packages found; Groww tool call blocked. Run scripts/india.py --setup"}}'
