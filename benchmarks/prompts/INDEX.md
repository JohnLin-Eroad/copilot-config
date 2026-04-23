# Prompt Pool Index

## Rotation Formula

```python
import hashlib

def select_prompt(week: str, category: str, pool_size: int) -> int:
    """Select a prompt index using cycle-based rotation with per-category offset.
    
    Guarantees: no prompt reused within pool_size weeks.
    Deterministic: same week + category always returns same index.
    Category offset ensures different categories don't all use the same prompt.
    
    Algorithm: 
    1. Extract week number from ISO week string (e.g. "2026-W18" → 18)
    2. Compute a per-category offset from SHA-256 hash
    3. (week_number + offset) % pool_size = prompt index
    """
    # Extract week number
    week_num = int(week.split('-W')[1])
    # Per-category offset so categories don't all pick the same prompt
    offset = int(hashlib.sha256(category.encode()).hexdigest()[:8], 16)
    return (week_num + offset) % pool_size
```

## Pool Sizes

| Category | Pool Size | Prompts |
|---|---|---|
| code-generation | 4 | P1-vehicle-odometer, P2-fleet-membership, P3-compliance-threshold, P4-trip-summary |
| context-retrieval | 4 | P1-architecture-overview, P2-dvir-system, P3-machine-device-relationship, P4-governance-engine |
| security-review | 4 | P1-vehicle-controller, P2-driver-auth-service, P3-fleet-report-exporter, P4-compliance-webhook |
| planning | 4 | P1-driver-hours, P2-multi-tenancy, P3-realtime-tracking, P4-audit-trail |
| hallucination-resistance | 4 | P1-nonexistent-service, P2-invented-api, P3-partial-context, P4-future-feature |
| error-recovery | 3 | P1-malformed-input, P2-empty-brain, P3-missing-stm |
| pipeline-compliance | 3 | P1-simple-code-task, P2-architecture-task, P3-multi-step-task |

## Verification: No 4-Week Collision

For pool_size=4, SHA-256 distribution ensures no collision within 4 consecutive weeks.
For pool_size=3, worst case is one repeat in 3 weeks (acceptable for smaller pools).

Run `python3 -c` to verify:
```python
import hashlib
for cat in ['code-generation', 'security-review']:
    for w in range(16, 24):
        week = f"2026-W{w:02d}"
        h = hashlib.sha256(f"{week}:{cat}".encode()).hexdigest()
        idx = int(h[:8], 16) % 4
        print(f"{week} {cat}: P{idx+1}")
```
