#!/usr/bin/env bash
# mcp.sh — toggle MCP servers on/off without hand-editing JSON.
# Default state: all OFF (token-cost optimization). Enable per-task as needed.
#
# Usage:
#   mcp list                 # show enabled vs disabled
#   mcp enable <name>        # turn on a server
#   mcp disable <name>       # turn off a server
#   mcp enable-all
#   mcp disable-all
#   mcp status               # alias for list
#
# After enable/disable: restart Copilot CLI for changes to take effect
# (MCP servers register at process startup).

set -euo pipefail

CFG="${MCP_CONFIG:-$HOME/.copilot/mcp-config.json}"
[[ -f "$CFG" ]] || { echo "error: $CFG not found" >&2; exit 1; }
command -v jq >/dev/null || { echo "error: jq required" >&2; exit 1; }

cmd="${1:-list}"
name="${2:-}"

write_atomic() {
  local tmp; tmp=$(mktemp)
  cat > "$tmp"
  mv "$tmp" "$CFG"
}

case "$cmd" in
  list|status)
    echo "Enabled MCP servers:"
    enabled_count=$(jq '.mcpServers | length' "$CFG")
    if [[ "$enabled_count" -eq 0 ]]; then
      echo "  (none)"
    else
      jq -r '.mcpServers | keys[] | "  ✓ \(.)"' "$CFG"
    fi
    echo
    echo "Disabled MCP servers:"
    disabled_count=$(jq '._disabled | length' "$CFG")
    if [[ "$disabled_count" -eq 0 ]]; then
      echo "  (none)"
    else
      jq -r '._disabled | keys[] | "  ✗ \(.)"' "$CFG"
    fi
    ;;

  enable)
    [[ -n "$name" ]] || { echo "usage: mcp enable <name>" >&2; exit 2; }
    exists=$(jq --arg n "$name" '._disabled | has($n)' "$CFG")
    if [[ "$exists" != "true" ]]; then
      already=$(jq --arg n "$name" '.mcpServers | has($n)' "$CFG")
      if [[ "$already" == "true" ]]; then
        echo "already enabled: $name"; exit 0
      fi
      echo "error: unknown server '$name'. Run 'mcp list'." >&2; exit 3
    fi
    jq --arg n "$name" '
      .mcpServers[$n] = ._disabled[$n] |
      del(._disabled[$n])
    ' "$CFG" | write_atomic
    echo "✓ enabled: $name"
    echo "→ restart Copilot CLI for it to register"
    ;;

  disable)
    [[ -n "$name" ]] || { echo "usage: mcp disable <name>" >&2; exit 2; }
    exists=$(jq --arg n "$name" '.mcpServers | has($n)' "$CFG")
    if [[ "$exists" != "true" ]]; then
      echo "not enabled: $name"; exit 0
    fi
    jq --arg n "$name" '
      ._disabled[$n] = .mcpServers[$n] |
      del(.mcpServers[$n])
    ' "$CFG" | write_atomic
    echo "✗ disabled: $name"
    echo "→ restart Copilot CLI to unload"
    ;;

  enable-all)
    jq '
      .mcpServers = (.mcpServers + (._disabled // {})) |
      ._disabled = {}
    ' "$CFG" | write_atomic
    echo "✓ all servers enabled"
    echo "→ restart Copilot CLI (warning: ~15-20k tok/session overhead)"
    ;;

  disable-all)
    jq '
      ._disabled = ((._disabled // {}) + .mcpServers) |
      .mcpServers = {}
    ' "$CFG" | write_atomic
    echo "✗ all servers disabled"
    echo "→ restart Copilot CLI to unload"
    ;;

  -h|--help|help)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    ;;

  *)
    echo "unknown command: $cmd" >&2
    echo "try: mcp {list|enable <name>|disable <name>|enable-all|disable-all}" >&2
    exit 2
    ;;
esac
