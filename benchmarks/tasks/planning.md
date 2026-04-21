# Benchmark Task 4: Planning Quality

## Purpose
Tests the orchestrator + architect agents' ability to produce a complete, well-structured plan from a **deliberately ambiguous, multi-service feature request** — including correct blast radius assessment, cross-cutting concerns, edge cases, and dependency ordering.

## Active Variant

> **Rotate this each week.** Pick the next variant from the list below.

**Current variant: B — Cross-service fleet analytics**

## Input Prompt (Variant B)

```
orchestrator: The business wants "real-time fleet efficiency reporting" in the EROAD sovereign platform.

Fleet managers should be able to see, on a live dashboard, which of their vehicles are currently
performing below the efficiency threshold. The data comes from trip events that are already being
published to SQS. The dashboard should refresh every 30 seconds.

Requirements are intentionally vague — you decide what's needed. Produce a detailed implementation plan.
```

## Scoring Rubric

Score each dimension 1–5:

| Dimension | 1 (poor) | 3 (adequate) | 5 (excellent) |
|---|---|---|---|
| **Domain modelling** | No mention of domain entities | Identifies vehicle/efficiency as concepts | Correctly models: `FleetEfficiencyReport`, `VehicleEfficiencySnapshot`, `EfficiencyThreshold` as domain objects |
| **Hexagonal architecture** | Plan ignores architecture | Mentions layers exist | Correctly places SQS consumer in infra, domain in domain, read model in application/infra with clear port |
| **Blast radius assessment** | None given | Vague ("medium impact") | Specific: names new SQS consumer, new read model table, new API endpoint, potential load on DB from 30s polling |
| **Ambiguity resolution** | Invents requirements without stating assumptions | Makes some assumptions explicit | Explicitly states ≥3 assumptions and flags them for product review |
| **Edge cases** | None identified | 1–2 edge cases | ≥4 edge cases: no trips yet (cold start), SQS message ordering, fleet with 0 vehicles, efficiency threshold changes mid-report |
| **Cross-cutting concerns** | Ignored | One mentioned | Identifies: auth (fleet manager scoping), caching strategy for 30s refresh, observability (metrics on lag) |
| **Dependency ordering** | Unordered or circular | Mostly ordered | Correct topo sort: domain model → SQS port → consumer adapter → read model → API → frontend |
| **Acceptance criteria** | None | Vague | Measurable: "Given trip event received, When processed, Then dashboard reflects updated efficiency within 35s" |

**Final score** = average of 8 dimensions (1.0–5.0)

## Variant Rotation

| Variant | Scenario | Complexity |
|---------|----------|------------|
| A | "Driver hours compliance" — single-service, clear requirements | Baseline |
| B | "Real-time fleet efficiency dashboard" — cross-service, vague, SQS involved | Multi-service |
| C | "Driver self-service portal" — new bounded context, auth, multi-tenant | New context |
| D | "Compliance report export to CSV/PDF" — read model, scheduled job, file storage | Scheduled + infra |

### Variant A Prompt (for reference)
```
orchestrator: Add a "driver hours compliance" feature to the EROAD sovereign platform.

Drivers must not exceed 13 hours of continuous driving. When a driver approaches 11 hours,
send them a warning notification. When they hit 13 hours, send a critical alert to the
fleet manager and log a compliance event.

Produce a detailed implementation plan.
```

## Grader Notes for benchmark-runner

1. Note which variant was run
2. Score all 8 dimensions with explicit reasoning
3. For **Ambiguity resolution**: count explicit assumption statements; ≥3 = 5, 2 = 4, 1 = 3, 0 = 1
4. For **Edge cases**: count distinct edge cases identified; ≥4 = 5, 3 = 4, 2 = 3, 1 = 2, 0 = 1
5. Average all 8 dimension scores for the final score
6. Update "Active Variant" for next week
