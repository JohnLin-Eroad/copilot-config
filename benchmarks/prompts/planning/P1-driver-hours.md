# Prompt P1: Driver Hours Compliance

## Prompt

```
Add a "driver hours compliance" feature to the EROAD sovereign platform.

Drivers must not exceed 13 hours of continuous driving. When a driver approaches 11 hours,
send them a warning notification. When they hit 13 hours, send a critical alert to the
fleet manager and log a compliance event.

Produce a detailed implementation plan.
```

## Expected Behavior

A complete plan that:
- Names domain entities: DrivingSession, ComplianceThreshold, ComplianceEvent
- Puts business rule (13h limit) in domain layer as value/policy object
- Identifies NotificationPort in application layer
- Notes DB migration for compliance_events table
- Lists edge cases: timezone, multi-fleet, clock sync, midnight crossing
- Has ordered todos with explicit dependencies
- Has testable acceptance criteria

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Domain understanding | 15% | No domain entities named | Identifies driver and hours | Correctly models DrivingSession, ComplianceThreshold, ComplianceEvent |
| Hexagonal architecture | 20% | Ignores architecture | Mentions layers | Correct placement: domain model, use case in application, notification via port |
| Blast radius assessment | 15% | None | Vague "medium impact" | Specific: DB migration, new API endpoint, notification service dependency |
| Edge cases | 15% | None identified | 1-2 edge cases | ≥4: clock drift, midnight crossing, multi-fleet, timezone handling |
| Dependency ordering | 15% | Unordered | Mostly ordered | Correct topo sort: model → port → use case → adapter → API → test |
| Acceptance criteria | 20% | None | Vague "it should work" | Measurable: "Given driver has driven 11h, When event processed, Then notification sent within 30s" |

**Score = weighted average of dimensions (0-100)**
