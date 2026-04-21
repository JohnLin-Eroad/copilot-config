# Benchmark Task 1: Code Generation

## Purpose
Tests the developer agent's ability to generate correct, idiomatic, hexagonally-compliant Java code from a **multi-file refactoring scenario** with deliberate ambiguity. This task rotates scenarios weekly to prevent Goodhart's Law (see Variant Rotation below).

## Active Variant

> **Rotate this each week.** Pick the next variant from the list below and update "Active Variant" to point to it.

**Current variant: E — TDD Red-Green (Tier 3)** ← *hardened W18*

## Input Prompt (Variant E — Active)

```
The following JUnit 5 tests are failing. Your job is to implement the production classes
that make ALL of them pass. Do not modify the tests.

```java
class FuelCardPolicyTest {

    @Test void card_is_blocked_when_monthly_spend_exceeds_limit() {
        var policy = new FuelCardPolicy(Money.of(500_00)); // $500 limit
        var card = new FuelCard("FC-001", policy);
        card.authorise(Money.of(300_00));
        card.authorise(Money.of(150_00));
        assertThrows(SpendLimitExceededException.class,
            () -> card.authorise(Money.of(100_00))); // $550 total > $500
    }

    @Test void card_resets_spend_at_start_of_new_month() {
        var policy = new FuelCardPolicy(Money.of(500_00));
        var card = new FuelCard("FC-001", policy);
        card.authorise(Money.of(400_00));
        card.resetMonthlySpend(); // simulates month rollover
        card.authorise(Money.of(400_00)); // should succeed — new month
        assertEquals(Money.of(400_00), card.currentMonthSpend());
    }

    @Test void authorise_raises_domain_event() {
        var policy = new FuelCardPolicy(Money.of(500_00));
        var card = new FuelCard("FC-001", policy);
        card.authorise(Money.of(100_00));
        var events = card.domainEvents();
        assertEquals(1, events.size());
        assertInstanceOf(FuelCardAuthorisedEvent.class, events.get(0));
    }

    @Test void money_of_rejects_negative_amounts() {
        assertThrows(IllegalArgumentException.class, () -> Money.of(-1));
    }

    @Test void money_of_accepts_zero() {
        assertDoesNotThrow(() -> Money.of(0));
    }

    @Test void spend_limit_exceeded_message_includes_amount() {
        var policy = new FuelCardPolicy(Money.of(100_00));
        var card = new FuelCard("FC-001", policy);
        var ex = assertThrows(SpendLimitExceededException.class,
            () -> card.authorise(Money.of(200_00)));
        assertTrue(ex.getMessage().contains("200"));
    }
}
```

Implement all required production classes in the correct hexagonal layers.
You may create as many classes as needed. Decide where each class belongs
(domain vs application) and justify your placement decisions in a comment block.
```

## Scoring Rubric (Variant E)

```
You are implementing a feature in the EROAD sovereign platform (Java 21, Spring Boot 3.4, hexagonal architecture).

The product team wants: "When a driver submits a trip, calculate whether it was fuel-efficient and store the result."

A trip has: driverId, distanceKm (positive double), fuelUsedLitres (positive double).
Fuel efficiency threshold: 10 L/100km is the cutoff. Below = efficient, above = inefficient.

Implement the following (you choose the exact class names and structure):
1. A domain value object representing fuel efficiency (with the threshold embedded as a domain constant)
2. A use case `SubmitTripUseCase` in the application layer that:
   - Accepts a trip input
   - Calculates efficiency
   - Persists via a port (you define the port interface)
   - Returns a result indicating efficient/inefficient
3. A JUnit 5 test for the domain value object (boundary conditions: exactly at threshold, above, below)
4. A JUnit 5 test for the use case (mock the port; test both efficient and inefficient outcomes)

Do NOT implement the infrastructure adapter. Only domain + application + tests.
```

## Scoring Rubric (Variant E)

Score each dimension 1–5, then average:

| Dimension | 1 (fail) | 3 (acceptable) | 5 (excellent) |
|---|---|---|---|
| **All tests pass** | >2 tests failing | 1–2 tests failing | All 6 tests pass exactly as written |
| **Hexagonal placement** | Everything in one package | Some separation | `Money`, `FuelCard`, `FuelCardPolicy`, `SpendLimitExceededException`, `FuelCardAuthorisedEvent` all in domain; no infra imports |
| **Domain event pattern** | Events not implemented or stored externally | Events stored on aggregate | `domainEvents()` returns immutable list; events accumulated on aggregate, not published directly |
| **Money value object** | Mutable class with public field | Immutable but no validation | Immutable record/class, cents-based (no floating point), factory method validates, `equals`/`hashCode` correct |
| **Invariant enforcement** | Limit check in wrong layer (e.g. controller) | Limit check in policy | `FuelCardPolicy` enforces the rule; `FuelCard` delegates — business rule in domain, not caller |
| **Design justification** | No comment on layer placement | Brief note | Clear written rationale for why each class is in domain vs application |

**Final score** = average of 6 dimensions (1.0–5.0)

**Why this is hard:** Agent must infer the full domain model from test behaviour alone — no spec given. The tests contain subtle traps: Money uses cents (integer), domain events must accumulate on the aggregate (not publish to a bus), and SpendLimitExceededException must include the amount in its message. A shallow implementation that makes most tests pass will fail on the domain event and Money precision tests.



## Variant Rotation

Rotate variants each benchmark week. This prevents prompt memorisation.

| Variant | Scenario | Focus |
|---------|----------|-------|
| A | `VehicleOdometer` value object + repository port + unit test | Value objects, Optional |
| B | `SubmitTripUseCase` + efficiency domain constant + mocked port tests | Use case, design quality |
| C | Refactor existing anemic `VehicleDto` into a proper domain aggregate with invariants | Refactoring, invariants |
| D | `ComplianceWindowPolicy` — domain service that decides if a driver is compliant given a list of events | Domain services, collections |

### Variant A Prompt (for reference)
```
Write a Java 21 Spring Boot 3.4 implementation for the following:

Domain: A `VehicleOdometer` value object in the domain layer that:
- Holds a reading in kilometres (positive integer), is immutable (use a Java record)
- Has a factory method `of(int km)` that throws IllegalArgumentException if km < 0
- Has a method `plus(VehicleOdometer other)` that returns a new VehicleOdometer
- Includes Javadoc on all public methods

Then write a port interface `OdometerRepository` in the application layer with:
- `save(VehicleId vehicleId, VehicleOdometer reading)` — void
- `findLatest(VehicleId vehicleId)` — returns Optional<VehicleOdometer>
- Full Javadoc

Then write a JUnit 5 unit test for VehicleOdometer covering: valid creation, zero value, negative value rejection, and addition.
```

## Grader Notes for benchmark-runner

1. Identify which variant was run (A, B, C, or D) and note it in the report
2. Score each of the 6 dimensions with explicit reasoning
3. For **Ambiguity handling**: check whether the agent documented any design decision it made — award 5 if it did, 3 if it just implemented without comment
4. Average the 6 dimension scores for the final score
5. Update "Active Variant" to the next variant for next week
