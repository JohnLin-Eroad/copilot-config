#!/usr/bin/env bash
# check-stm-size.sh — warns when active STM exceeds 200KB
# Usage: check-stm-size.sh [stm_path]

STM_PATH="${1:-}"

# Auto-find most recent STM if not provided
if [ -z "$STM_PATH" ]; then
  STM_PATH=$(ls -t ~/.copilot/stm/*/short-term-memory.md 2>/dev/null | head -1)
fi

if [ -z "$STM_PATH" ] || [ ! -f "$STM_PATH" ]; then
  echo "No active STM found."
  exit 0
fi

SIZE_BYTES=$(wc -c < "$STM_PATH")
SIZE_KB=$(echo "scale=1; $SIZE_BYTES / 1024" | bc)
LIMIT_KB=200

echo "STM: $STM_PATH"
echo "Size: ${SIZE_KB}KB / ${LIMIT_KB}KB limit"

if [ "$SIZE_BYTES" -gt $((LIMIT_KB * 1024)) ]; then
  echo ""
  echo "⚠️  STM EXCEEDS ${LIMIT_KB}KB — invoke context-compression skill immediately"
  echo "   Run: skill context-compression"
  echo "   Target: reduce to <100KB before passing STM to next agent"
  exit 2
elif [ "$SIZE_BYTES" -gt $(( LIMIT_KB * 1024 * 75 / 100 )) ]; then
  echo "⚡ STM approaching limit (>75%) — consider compressing soon"
  exit 1
else
  echo "✅ STM size OK"
  exit 0
fi
