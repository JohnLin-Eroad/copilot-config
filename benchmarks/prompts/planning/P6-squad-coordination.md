# Prompt P6: Cross-Team 3-Squad Coordination

**Difficulty tier: 3 (Expert)** — source: tasks/planning.md Variant G

## Prompt

```
Three engineering squads need to deliver a connected feature in the next sprint.

SQUAD A (Platform): Owns the driver-events SQS topic. Must add a new event type:
  ShiftCompletedEvent { driverId, vehicleId, shiftStartUtc, shiftEndUtc, totalDistanceKm }

SQUAD B (Compliance): Must consume ShiftCompletedEvent and evaluate whether the driver has
exceeded the weekly hours threshold (configurable per employment type). Must publish:
  ComplianceViolationEvent { driverId, violationType, severity, detectedAt }
  or
  CompliancePassedEvent { driverId, checkedAt }

SQUAD C (Reporting): Must consume both compliance events and update the fleet reporting
read model. Must expose a REST endpoint: GET /api/fleet/{fleetId}/compliance-summary

All three squads are working in parallel. They cannot wait for each other.

Produce an implementation plan that:
1. Defines the API contracts each squad must honour
2. Sequences the work so squads can develop in parallel
3. Specifies the rollback plan if Squad B's deployment fails after Squad A is live
4. Defines acceptance criteria per squad
```

## Expected Behavior

Agent produces contracts-first plan: schemas for all 3 SQS events + REST endpoint; explicit parallelism strategy (stubs/test doubles); per-squad rollback (especially graceful degradation if B is down while A continues publishing); ≥2 measurable acceptance criteria per squad; blast-radius assessment and integration test strategy.

## Grading Rubric

| Dimension | Weight | 0 | 50 | 100 |
|---|---|---|---|---|
| API contract definition | 20% | 0–1 schemas | 2 schemas | All 3 events + REST schema with fields & types |
| Parallel work enablement | 15% | None | Mentions parallelism | Contract-first; stubs/test doubles per squad |
| Squad A rollback | 10% | None | Vague | SQS schema versioning or dual-publish strategy |
| Squad B rollback | 10% | None | Mentions degraded | Specific: A continues, C degrades gracefully (stale + warn) |
| Squad C rollback | 10% | None | Partial | API versioning or feature flag; stale read model OK |
| Acceptance criteria | 15% | None | 1 per squad | ≥2 measurable AC per squad (G/W/T or equivalent) |
| Blast radius assessment | 10% | None | 1–2 risks | Names SQS lag, schema incompat, eventual-consistency window |
| Integration test strategy | 10% | None | Mentions testing | End-to-end: publish → assert ComplianceSummary updated within X seconds |

**Score = weighted average (0–100)**

## Auto-Checks

```yaml
- name: defines-all-three-events
  must_contain_all: ["ShiftCompletedEvent", "ComplianceViolationEvent", "CompliancePassedEvent"]
- name: defines-rest-endpoint
  must_contain_any: ["/api/fleet/", "compliance-summary"]
- name: rollback-strategy
  must_contain_any: ["rollback", "feature flag", "dual-publish", "versioning"]
  case_insensitive: true
- name: parallel-strategy
  must_contain_any: ["contract-first", "stub", "test double", "mock", "parallel"]
  case_insensitive: true
- name: acceptance-criteria
  must_contain_any: ["acceptance criteria", "Given", "When", "Then"]
  case_insensitive: true
- name: integration-test
  must_contain_any: ["integration test", "end-to-end", "e2e"]
  case_insensitive: true
- name: blast-radius
  must_contain_any: ["blast radius", "risk", "lag", "schema incompat", "eventual consistency"]
  case_insensitive: true
```

## Ground Truth

Reference contracts: SQS message schema versioned via `eventVersion` field; B publishes both Violation and Passed events to drive C deterministically; C's read model tolerates absent B output (shows "pending" state). Rollback chain: A → dual-publish for one sprint; B → consumer-disabled flag, A keeps publishing; C → endpoint behind feature flag, falls back to last-good snapshot.
