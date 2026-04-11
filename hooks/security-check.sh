#!/usr/bin/env bash
# security-check.sh — preToolUse hook
#
# Fires before every Copilot tool call. Blocks high-risk external operations
# and writes an audit log to ~/.copilot/logs/security-audit.jsonl
#
# Blocked patterns:
#   - pipe-to-shell downloads (curl | bash, wget | sh, etc.)
#   - POST requests referencing local credentials or config files
#   - Cloud metadata endpoint access (169.254.169.254)
#   - Downloads directly to executable/system paths
#   - Internal network access via the web-fetch tool
#
# Logged (allowed) patterns:
#   - curl/wget GET requests
#   - Package manager installs (npm, pip, brew, apt, gem, go)
#   - git clone
#   - docker pull
#   - web-fetch calls

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName')
AUDIT_LOG="$HOME/.copilot/logs/security-audit.jsonl"

mkdir -p "$(dirname "$AUDIT_LOG")"

# ── Helpers ───────────────────────────────────────────────────────────────────

deny() {
  local reason="$1"
  jq -n \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg tool "$TOOL_NAME" \
    --arg reason "$reason" \
    '{timestamp: $ts, tool: $tool, decision: "deny", reason: $reason}' \
    >> "$AUDIT_LOG"
  jq -n --arg r "$reason" '{permissionDecision: "deny", permissionDecisionReason: $r}'
  exit 0
}

audit_allow() {
  local note="$1"
  jq -n \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg tool "$TOOL_NAME" \
    --arg note "$note" \
    '{timestamp: $ts, tool: $tool, decision: "allow", note: $note}' \
    >> "$AUDIT_LOG"
}

# ── bash tool ─────────────────────────────────────────────────────────────────

if [ "$TOOL_NAME" = "bash" ]; then
  COMMAND=$(echo "$INPUT" | jq -r '.toolArgs | fromjson | .command // ""' 2>/dev/null) || COMMAND=""

  # 1. Pipe-to-shell: downloaded content piped directly into an interpreter
  if echo "$COMMAND" | grep -qE "(curl|wget)[^|#]*\|[^|]*(bash|sh|zsh|fish|python3?|node|ruby|perl|pwsh)"; then
    deny "Pipe-to-shell download blocked — executing downloaded scripts is a critical security risk"
  fi

  # 2. Exfiltration: POST request that references local credentials or config
  if echo "$COMMAND" | grep -qiE "curl[^#]*(--data |-d |--data-raw |--data-binary |-X POST)" && \
     echo "$COMMAND" | grep -qiE "(\.env|\.copilot|mcp.config|id_rsa|id_ed25519|\.ssh|GITHUB_TOKEN|GH_TOKEN|secret|api.key|api_key|password|token)"; then
    deny "Potential data exfiltration blocked — POST request references sensitive credentials or local config"
  fi

  # 3. Cloud/container metadata endpoint
  if echo "$COMMAND" | grep -qE "169\.254\.169\.254"; then
    deny "Cloud metadata endpoint access blocked (169.254.169.254)"
  fi

  # 4. Download direct to executable or system paths
  if echo "$COMMAND" | grep -qE "(curl|wget)[^|]*(--output |-o )[^|]*(\.sh|\.py|\.rb|/bin/|/usr/local/bin/|/usr/bin/|/etc/)"; then
    deny "Download to executable or system path blocked"
  fi

  # Audit log: external HTTP calls and package manager installs
  if echo "$COMMAND" | grep -qE "(curl|wget) "; then
    audit_allow "HTTP call: $(echo "$COMMAND" | grep -oE '(https?://[^ ]+)' | head -1)"
  elif echo "$COMMAND" | grep -qE "^(npm|yarn|pnpm) (install|add|ci)"; then
    audit_allow "npm/yarn install: $COMMAND"
  elif echo "$COMMAND" | grep -qE "^pip3? install"; then
    audit_allow "pip install: $COMMAND"
  elif echo "$COMMAND" | grep -qE "^brew install"; then
    audit_allow "brew install: $COMMAND"
  elif echo "$COMMAND" | grep -qE "^(apt-get|apt) install"; then
    audit_allow "apt install: $COMMAND"
  elif echo "$COMMAND" | grep -qE "^gem install|^go install|^cargo (install|add)"; then
    audit_allow "package install: $COMMAND"
  elif echo "$COMMAND" | grep -qE "^git clone"; then
    audit_allow "git clone: $COMMAND"
  elif echo "$COMMAND" | grep -qE "^docker pull"; then
    audit_allow "docker pull: $COMMAND"
  fi
fi

# ── web-fetch tool ────────────────────────────────────────────────────────────

if echo "$TOOL_NAME" | grep -qi "fetch"; then
  URL=$(echo "$INPUT" | jq -r '.toolArgs | fromjson | .url // ""' 2>/dev/null) || URL=""

  # Block internal/metadata endpoints
  if echo "$URL" | grep -qE "169\.254\.169\.254|^https?://localhost|^https?://127\.|^https?://\[::1\]"; then
    deny "Internal/metadata network access via web-fetch blocked: $URL"
  fi

  audit_allow "web-fetch: $URL"
fi

# Allow everything else
exit 0
