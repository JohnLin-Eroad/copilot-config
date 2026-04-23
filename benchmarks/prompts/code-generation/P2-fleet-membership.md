# Prompt P2: Fleet Membership Aggregate

## Prompt

```
Write a Java 21 Spring Boot 3.4 implementation for the following:

Domain: A `FleetMembership` aggregate root in the domain layer that:
- Tracks which drivers belong to a fleet
- Has a `FleetId` (value object wrapping UUID) and a `Set<DriverId>` members
- Enforces invariant: a fleet can have at most 500 drivers
- Has methods:
  - `addDriver(DriverId driverId)` — throws if at capacity or already a member
  - `removeDriver(DriverId driverId)` — throws if not a member
  - `isMember(DriverId driverId)` — boolean check
  - `memberCount()` — returns current count
- Records domain events: `DriverAddedToFleet` and `DriverRemovedFromFleet`
- Is immutable-friendly: methods return new FleetMembership instances (or use event sourcing pattern)
- Includes Javadoc on all public methods

Then write a port interface `FleetMembershipRepository` in the application layer with:
- `save(FleetMembership membership)` — void
- `findByFleetId(FleetId fleetId)` — returns Optional<FleetMembership>
- Full Javadoc

Then write JUnit 5 tests covering: add driver, add duplicate rejection, remove driver, remove non-member rejection, capacity limit (500), and memberCount accuracy.
```

## Expected Behavior

Agent produces:
1. `FleetId.java` — Value object wrapping UUID
2. `DriverId.java` — Value object wrapping UUID (may already exist)
3. `FleetMembership.java` — Aggregate root with invariant enforcement
4. Domain events: `DriverAddedToFleet.java`, `DriverRemovedFromFleet.java`
5. `FleetMembershipRepository.java` — Port interface
6. `FleetMembershipTest.java` — Comprehensive JUnit 5 tests

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Correctness | 20% | Doesn't compile, invariant not enforced | Compiles, some invariants work | All methods correct, 500-limit enforced, events emitted |
| Hexagonal compliance | 25% | Aggregate imports infra | Minor layer violation | Perfect DDD: aggregate in domain, port in application, events in domain |
| Java 21 idioms | 20% | Mutable state everywhere | Mostly immutable | Records for VOs, sealed interfaces for events, unmodifiable collections |
| Javadoc completeness | 15% | Missing | Partial | All public methods + @param/@return/@throws |
| Test quality | 20% | Only tests happy path | Most cases covered | All 6 cases: add, duplicate, remove, non-member, capacity, count |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

Key invariants to verify:
- `addDriver` on a fleet with 500 members → `IllegalStateException`
- `addDriver` with existing member → `IllegalArgumentException`
- `removeDriver` with non-member → `IllegalArgumentException`
- Domain events correctly record fleet ID and driver ID
