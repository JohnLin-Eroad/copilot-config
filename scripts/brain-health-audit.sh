#!/usr/bin/env bash
# brain-health-audit.sh — audits john-brain and eroad-brain for coverage and health
# Usage: brain-health-audit.sh [eroad|personal|both]

MODE="${1:-both}"
PASS=0; WARN=0; FAIL=0

check() {
  local label="$1"; local path="$2"; local required="$3"
  if [ -f "$path" ] || [ -d "$path" ]; then
    echo "  ✅ $label"
    ((PASS++))
  elif [ "$required" = "required" ]; then
    echo "  ❌ MISSING (required): $label — $path"
    ((FAIL++))
  else
    echo "  ⚠️  MISSING (optional): $label — $path"
    ((WARN++))
  fi
}

if [[ "$MODE" == "personal" || "$MODE" == "both" ]]; then
  echo ""
  echo "=== john-brain health ==="
  JBRAIN=~/john-brain
  check "index.md"                        "$JBRAIN/index.md"                            required
  check "Global Learnings"               "$JBRAIN/Learnings/Global/Global Learnings.md" required
  check "Copilot Learnings"              "$JBRAIN/Learnings/Copilot/Copilot Learnings.md" required
  check "AI Agent Ecosystem Design"      "$JBRAIN/clusters/AI Agent Ecosystem Design.md" required
  check "Automation & Efficiency"        "$JBRAIN/clusters/Automation & Efficiency.md"   optional
  check "Sessions directory"             "$JBRAIN/Sessions"                              optional

  CLUSTER_COUNT=$(ls "$JBRAIN/clusters/" 2>/dev/null | wc -l | tr -d ' ')
  echo "  📊 Clusters: $CLUSTER_COUNT files"

  RECENT=$(find "$JBRAIN" -name "*.md" -newer "$JBRAIN/index.md" 2>/dev/null | wc -l | tr -d ' ')
  echo "  📅 Files updated since index: $RECENT"
fi

if [[ "$MODE" == "eroad" || "$MODE" == "both" ]]; then
  echo ""
  echo "=== eroad-brain health ==="
  EBRAIN=~/eroad-brain
  check "Architecture dir"     "$EBRAIN/03 - Architecture"              required
  check "Domain Models dir"    "$EBRAIN/02 - Domain Models"             required
  check "Tech Stack file"      "$EBRAIN/03 - Architecture/tech-stack.md" optional
  check "Platform architecture" "$EBRAIN/03 - Architecture/eroad-platform-architecture.md" required
  check "Sovereign V2 spec"    "$EBRAIN/03 - Architecture/sovereign-v2-spec.md" required

  FILE_COUNT=$(find "$EBRAIN" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  echo "  📊 Total brain files: $FILE_COUNT"
fi

echo ""
echo "=== Summary ==="
echo "  ✅ Pass: $PASS  ⚠️  Warn: $WARN  ❌ Fail: $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo "  🚨 CRITICAL gaps detected — brain coverage is degraded"
  exit 2
elif [ "$WARN" -gt 0 ]; then
  echo "  ⚡ Warnings present — consider filling gaps"
  exit 1
else
  echo "  �� Brain health: OK"
  exit 0
fi
