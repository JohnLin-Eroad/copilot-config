# Config Health Checklist

## Purpose

Pass/fail system health checks that run ALONGSIDE scored benchmarks but are NOT weighted into the overall score. These verify that the Copilot infrastructure is correctly configured.

**This is NOT a benchmark.** It does not test agent capability. It checks that files exist, configs parse, and services run.

## Checks

### Agent Configuration (6 checks)

| ID | Check | How to verify |
|---|---|---|
| `agent-files-exist` | All agents in `~/.copilot/agents/` have `.agent.md` extension | `ls ~/.copilot/agents/*.agent.md \| wc -l` ≥ 30 |
| `agent-structure` | Each agent has: name, description, model, tools sections | Parse first 50 lines of each agent file |
| `agent-donot` | Each agent has a `## DO NOT` section | `grep -l "DO NOT" ~/.copilot/agents/*.agent.md` |
| `agent-dispatch` | All agents in copilot-instructions.md dispatch table exist as files | Cross-reference dispatch table with file listing |
| `skill-files-exist` | All skills in dispatch table have `SKILL.md` files | Check `~/.copilot/skills/*/SKILL.md` |
| `skill-dispatch` | Skills in copilot-instructions.md match skill directories | Cross-reference |

### Governance (3 checks)

| ID | Check | How to verify |
|---|---|---|
| `governance-parse` | `governance-rules.json` parses as valid JSON | `python3 -c "import json; json.load(open(...))"` |
| `governance-count` | ≥ 16 rules in governance-rules.json | Count rules array length |
| `governance-security` | Security rules sec-001 through sec-004 all present | Check rule IDs |

### Infrastructure (4 checks)

| ID | Check | How to verify |
|---|---|---|
| `dashboard-running` | Agent dashboard responds on port 8765 | `curl -s http://localhost:8765/health` returns 200 |
| `launchd-loaded` | Dashboard plist loaded in launchctl | `launchctl list \| grep agent-dashboard` |
| `no-zombies` | Zero zombie stm-dashboard.py processes | `pgrep -f stm-dashboard.py \| wc -l` = 0 |
| `brain-health` | brain-health-audit.sh exists and is executable | `test -x ~/.copilot/scripts/brain-health-audit.sh` |

### Brain Vault (3 checks)

| ID | Check | How to verify |
|---|---|---|
| `eroad-brain-exists` | `~/eroad-brain/` directory exists with content | `ls ~/eroad-brain/ \| wc -l` ≥ 5 |
| `john-brain-exists` | `~/john-brain/` directory exists with content | `ls ~/john-brain/ \| wc -l` ≥ 3 |
| `learnings-exist` | `~/.copilot/learnings.md` exists | `test -f ~/.copilot/learnings.md` |

## Output Format

```json
{
  "week": "YYYY-WXX",
  "timestamp": "ISO 8601",
  "checks": [
    {
      "id": "agent-files-exist",
      "category": "agent-config",
      "status": "PASS",
      "detail": "42 agent files found"
    },
    {
      "id": "governance-parse",
      "category": "governance",
      "status": "FAIL",
      "detail": "JSON parse error on line 47: unexpected comma"
    }
  ],
  "summary": {
    "total": 16,
    "passed": 15,
    "failed": 1,
    "pass_rate": 93.75
  }
}
```

## Interpretation

- **16/16 PASS**: Infrastructure healthy, proceed with confidence
- **≥ 14 PASS**: Minor issues, note in report
- **< 14 PASS**: Significant infrastructure problems — may affect benchmark scores. Flag prominently in report.
- **Dashboard not running**: WARNING — benchmark runner should still complete but note reduced observability

## Integration with Benchmark Runner

The benchmark runner runs config health checks AFTER all scored categories, as a separate appendix section. Config health results are saved to `traces/YYYY-WXX/config-health.json` and included in the weekly report but do NOT affect the overall weighted score.
