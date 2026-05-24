# Prompt P6: Event-Sourced Aggregate

**Difficulty tier: 3 (Expert)** — source: tasks/code-generation.md Variant G

## Prompt

```
Implement a DrivingSessionAggregate in Java 21 using the event-sourcing pattern.

The aggregate must:
1. Support the following commands:
   - StartSession(driverId, vehicleId, startTime)
   - RecordSpeedReading(speed, timestamp)
   - EndSession(endTime)
2. Produce the following domain events:
   - DrivingSessionStarted(sessionId, driverId, vehicleId, startTime)
   - SpeedReadingRecorded(sessionId, speed, timestamp)
   - DrivingSessionEnded(sessionId, endTime, durationMinutes, maxSpeedKmh)
3. Be reconstitutable from a list of past events — i.e., `apply(List<DomainEvent> history)` must rebuild state correctly
4. Enforce: session cannot be ended before it is started; speed readings after session ended are rejected
5. Raise IllegalStateException with a descriptive message for guard violations

Write a JUnit 5 test that:
- Creates a new session via commands
- Records 3 speed readings
- Ends the session
- Serialises all produced events to a list
- Reconstitutes a second instance from that list
- Asserts that the reconstituted aggregate's state matches the original (max speed, duration, status)
```

## Expected Behavior

Agent produces a `DrivingSessionAggregate` class (Java 21, no Spring/JPA), event base type + 3 concrete event records, `apply(event)` methods (one per event type), command handlers that produce events without mutating state directly, and a JUnit 5 round-trip test that proves reconstitution equivalence.

## Grading Rubric

| Dimension | Weight | 0 | 50 | 100 |
|---|---|---|---|---|
| Command → Event separation | 20% | State mutated in command handlers | Mixed | Commands produce events; state changes only in `apply(event)` |
| Reconstitution correctness | 25% | Not implemented / fails | Partial (some fields wrong) | `apply(List<DomainEvent>)` rebuilds identical state |
| Guard enforcement | 15% | Guards absent | One guard or no test | Both guards with descriptive messages + tested |
| Event completeness | 15% | 0–1 event types | 2 event types | All 3 events; `DrivingSessionEnded` computes duration + maxSpeed |
| Domain purity | 15% | Spring/JPA annotations on aggregate | Minor infra leakage | Zero framework annotations or infra imports |
| Test quality | 10% | Trivial / incomplete | Happy path only | Full round-trip + both guard paths |

**Score = weighted average (0–100)**

## Auto-Checks

```yaml
- name: has-aggregate-class
  must_contain_any: ["class DrivingSessionAggregate", "record DrivingSessionAggregate"]
- name: has-three-events
  must_contain_all: ["DrivingSessionStarted", "SpeedReadingRecorded", "DrivingSessionEnded"]
- name: has-apply-method
  regex: "apply\\s*\\("
- name: has-guard-exception
  must_contain_any: ["IllegalStateException", "throw new"]
- name: has-junit-test
  must_contain_any: ["@Test", "org.junit"]
- name: no-spring-on-aggregate
  must_not_contain: ["@Entity", "@Component on DrivingSessionAggregate"]
```

## Ground Truth

Reference pattern: events are immutable records; aggregate holds private mutable state but exposes only `handle(Command) -> List<Event>` and `apply(Event)`; reconstitution constructor takes `List<DomainEvent>` and folds via `apply`. Aggregate must NOT depend on Spring, JPA, or any infrastructure framework.
