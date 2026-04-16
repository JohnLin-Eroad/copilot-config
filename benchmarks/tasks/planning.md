# Benchmark Task 4: Planning Quality

## Purpose
Tests the orchestrator + architect agents' ability to produce a complete, well-structured plan from a vague feature request — including correct blast radius assessment, edge cases, and dependency ordering.

## Input Prompt

```
orchestrator: Add a "driver hours compliance" feature to the EROAD sovereign platform.

Drivers must not exceed 13 hours of continuous driving. When a driver approaches 11 hours,
send them a warning notification. When they hit 13 hours, send a critical alert to the
fleet manager and log a compliance event.

Produce a detailed implementation plan.
```

## Scoring Rubric

Score each dimension 1–5:

| Dimension | 1 (poor) | 3 (adequate) | 5 (excellent) |
|---|---|---|---|
| **Domain understanding** | No mention of domain entities | Identifies driver and hours as entities | Correctly models: Driver, DrivingSession, ComplianceEvent, Threshold value objects |
| **Hexagonal architecture** | Plan ignores architecture | Mentions layers exist | Correctly places: domain model in `domain`, use case in `application`, notification in `infrastructure` via port |
| **Blast radius assessment** | None given | Vague ("medium impact") | Specific: identifies DB migration needed, new API endpoint, new notification service dependency |
| **Edge cases** | None identified | 1–2 edge cases | ≥4 edge cases: clock drift, driver crossing midnight, driver in multiple fleets, timezone handling |
| **Dependency ordering** | Unordered or circular | Mostly ordered | Correct topo sort: domain model → port → use case → adapter → API → test |
| **Acceptance criteria** | None | Vague ("it should work") | Measurable: "Given driver has driven 11h, When event processed, Then notification sent within 30s" |

**Final score** = average of 6 dimensions (1.0–5.0)

## What Good Looks Like (Score 5)

A complete plan that:
- Names domain entities explicitly: `DrivingSession`, `ComplianceThreshold`, `ComplianceEvent`
- Puts business rule (13h limit) in the **domain layer** as a value or policy object
- Identifies a `NotificationPort` in the application layer
- Notes DB migration for `compliance_events` table
- Lists edge cases including timezone, multi-fleet, clock sync
- Has ordered todos with explicit dependencies
- Has testable acceptance criteria per story

## Grader Notes for benchmark-runner

Read the plan produced and evaluate each dimension with explicit reasoning. Count the number of edge cases identified. Check if todos have dependency ordering. Verify hexagonal placement is mentioned for each component. Average the 6 dimension scores.
