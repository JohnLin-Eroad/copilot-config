#!/usr/bin/env bash
# governance-audit.sh — preToolUse hook
#
# Three responsibilities:
#   1. SECURITY — block prompt injection, exfiltration, metadata endpoints
#   2. GOVERNANCE — enforce blast radius rules (BLOCK / LOG)
#   3. AUDIT — write every tool call to ~/.copilot/logs/audit.jsonl

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName')
AUDIT_LOG="$HOME/.copilot/logs/audit.jsonl"
mkdir -p "$(dirname "$AUDIT_LOG")"

# ── Output helpers ─────────────────────────────────────────────────────────────

deny() {
  local reason="$1" blast="${2:-CRITICAL}" category="${3:-governance}"
  jq -n \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg tool "$TOOL_NAME" \
    --arg blast "$blast" \
    --arg cat "$category" \
    --arg reason "$reason" \
    '{timestamp:$ts,tool:$tool,decision:"BLOCK",blastRadius:$blast,category:$cat,reason:$reason}' \
    >> "$AUDIT_LOG"
  jq -n --arg r "🛡 Governance BLOCK: $reason" \
    '{permissionDecision:"deny",permissionDecisionReason:$r}'
  exit 0
}

audit() {
  local decision="$1" blast="${2:-LOW}" category="${3:-general}" note="${4:-}"
  jq -n \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg tool "$TOOL_NAME" \
    --arg d "$decision" \
    --arg blast "$blast" \
    --arg cat "$category" \
    --arg note "$note" \
    '{timestamp:$ts,tool:$tool,decision:$d,blastRadius:$blast,category:$cat,note:$note}' \
    >> "$AUDIT_LOG"
}

# ── bash tool ──────────────────────────────────────────────────────────────────

if [ "$TOOL_NAME" = "bash" ]; then
  CMD=$(echo "$INPUT" | jq -r '.toolArgs | fromjson | .command // ""' 2>/dev/null) || CMD=""

  # ── SECURITY: Obfuscated shell expansion (prompt injection) ──────────────
  if echo "$CMD" | grep -qE '\$\{[^}]+@[PQEUA]\}|\$\{![^}]+\}'; then
    deny "Obfuscated shell expansion — potential prompt injection" "CRITICAL" "security"
  fi

  # ── SECURITY: Pipe-to-shell download ─────────────────────────────────────
  if echo "$CMD" | grep -qE "(curl|wget)[^|#]*\|[^|]*(bash|sh|zsh|fish|python3?|node|ruby|perl|pwsh)"; then
    deny "Pipe-to-shell download blocked — executing downloaded scripts is a critical security risk" "CRITICAL" "security"
  fi

  # ── SECURITY: Credential exfiltration ────────────────────────────────────
  if echo "$CMD" | grep -qiE "curl[^#]*(--data |-d |-X POST)" && \
     echo "$CMD" | grep -qiE "(\.env|\.copilot|id_rsa|id_ed25519|GITHUB_TOKEN|GH_TOKEN|api_key|password|token)"; then
    deny "Potential credential exfiltration via POST request" "CRITICAL" "security"
  fi

  # ── SECURITY: Cloud metadata endpoint ────────────────────────────────────
  if echo "$CMD" | grep -qE "169\.254\.169\.254"; then
    deny "Cloud metadata endpoint access blocked" "CRITICAL" "security"
  fi

  # ── GOVERNANCE: Destroy home directory ───────────────────────────────────
  if echo "$CMD" | grep -qE "rm\s+-[rRf ]*f?[rR]?\s+(~|/Users/[^/]+\s*$|/home/[^/]+\s*$)"; then
    deny "Destroying home directory is not permitted" "CRITICAL" "governance"
  fi

  # ── GOVERNANCE: Destroy critical directories ──────────────────────────────
  for critical_dir in "\.copilot" "sovereign" "copilot-config" "eroad-brain" "IdeaProjects"; do
    if echo "$CMD" | grep -qE "rm\s+-[rRf]+.*/${critical_dir}(\s*$|\s+|/)"; then
      deny "Destroying critical directory '${critical_dir}' requires explicit approval" "CRITICAL" "governance"
    fi
  done

  # ── GOVERNANCE: git force push ────────────────────────────────────────────
  if echo "$CMD" | grep -qE "git\s+push\s+.*(-f\b|--force)"; then
    deny "git push --force is blocked — history rewrite requires explicit human approval" "HIGH" "governance"
  fi

  # ── GOVERNANCE: Destructive database operations ───────────────────────────
  if echo "$CMD" | grep -qiE "(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)"; then
    deny "Destructive DB operation (DROP/TRUNCATE) blocked — requires explicit approval" "HIGH" "governance"
  fi

  # ── GOVERNANCE: Download to executable paths ──────────────────────────────
  if echo "$CMD" | grep -qE "(curl|wget)[^|]*(--output |-o )[^|]*(\.sh|\.py|/bin/|/usr/local/bin/)"; then
    deny "Download to executable path blocked" "HIGH" "governance"
  fi

  # ── AUDIT: Classify and log ───────────────────────────────────────────────
  if echo "$CMD" | grep -qE "rm\s+-[rRf]"; then
    audit "ALLOW" "HIGH" "destructive" "$(echo "$CMD" | cut -c1-140)"
  elif echo "$CMD" | grep -qE "git\s+(commit|push|rebase|reset)"; then
    audit "ALLOW" "MEDIUM" "vcs" "$(echo "$CMD" | cut -c1-140)"
  elif echo "$CMD" | grep -qiE "(psql|mysql|sqlite3).*(-c\s|--command)"; then
    audit "ALLOW" "MEDIUM" "database" "$(echo "$CMD" | cut -c1-140)"
  elif echo "$CMD" | grep -qE "^(npm|yarn|pip3?|brew|apt|gem|go|cargo)\s+(install|add|ci)"; then
    audit "ALLOW" "LOW" "package-install" "$(echo "$CMD" | cut -c1-80)"
  elif echo "$CMD" | grep -qE "(curl|wget)\s"; then
    url=$(echo "$CMD" | grep -oE 'https?://[^ ]+' | head -1)
    audit "ALLOW" "LOW" "http" "$url"
  elif echo "$CMD" | grep -qE "^git\s+clone"; then
    audit "ALLOW" "LOW" "vcs" "$(echo "$CMD" | cut -c1-80)"
  elif echo "$CMD" | grep -qE "^(mvn|gradle|make|cargo build|go build)\s"; then
    audit "ALLOW" "LOW" "build" "$(echo "$CMD" | cut -c1-80)"
  else
    audit "ALLOW" "LOW" "bash" "$(echo "$CMD" | cut -c1-80)"
  fi
fi

# ── edit / create / write_file tools ─────────────────────────────────────────
if echo "$TOOL_NAME" | grep -qiE "^(edit|create)$"; then
  FILE_PATH=$(echo "$INPUT" | jq -r '.toolArgs | fromjson | (.path // .file_path // "unknown")' 2>/dev/null) || FILE_PATH="unknown"
  audit "ALLOW" "MEDIUM" "file-write" "$FILE_PATH"
fi

# ── web-fetch tool ────────────────────────────────────────────────────────────
if echo "$TOOL_NAME" | grep -qi "fetch"; then
  URL=$(echo "$INPUT" | jq -r '.toolArgs | fromjson | .url // ""' 2>/dev/null) || URL=""
  if echo "$URL" | grep -qE "169\.254\.169\.254|^https?://127\.|^https?://\[::1\]"; then
    deny "Internal/metadata endpoint access via web-fetch blocked" "CRITICAL" "security"
  fi
  audit "ALLOW" "LOW" "web-fetch" "$URL"
fi

exit 0
