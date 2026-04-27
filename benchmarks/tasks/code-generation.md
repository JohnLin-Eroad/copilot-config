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

1. Identify which variant was run (A–G), note the **difficulty tier** (1=baseline, 2=intermediate, 3=expert)
2. Score each of the rubric dimensions for the active variant with explicit reasoning
3. Average the dimension scores for the final score
4. Update "Active Variant" to the next variant for next week

---

**Final score** = average of 5 dimensions (1–100)

<details>
<summary>Variant A — Prompt (FuelEfficiencyUseCase)</summary>

```
Write a FuelEfficiencyUseCase in Java 21 for the EROAD sovereign platform.

The use case should:
- Accept a VehicleId and a distance driven (in km) and fuel used (in litres)
- Calculate fuel efficiency in litres per 100km
- If efficiency is worse than 10 L/100km, store a FuelEfficiencyWarning domain event
- Return a result object containing the calculated efficiency and whether a warning was raised

Use hexagonal architecture. Domain must not import infrastructure.
Write unit tests with JUnit 5 + Mockito covering the happy path and the warning threshold.
```
</details>

<details>
<summary>Variant B — Prompt (FuelConsumptionUseCase)</summary>

```
Write a FuelConsumptionUseCase in Java 21 for the EROAD sovereign platform.

The use case should:
- Accept a VehicleId, trip distance (km), and fuel consumed (litres)
- Compute consumption rate (L/100km) and classify it: EFFICIENT (<8), NORMAL (8–12), EXCESSIVE (>12)
- If EXCESSIVE, publish a ConsumptionAlertEvent on a domain event port
- Return a FuelConsumptionResult containing the rate and classification

Use hexagonal architecture. Provide JUnit 5 tests for all three classifications.
```
</details>

<details>
<summary>Variant C — Prompt (SpeedingIncidentUseCase)</summary>

```
Write a SpeedingIncidentUseCase in Java 21 for the EROAD sovereign platform.

The use case should:
- Accept a VehicleId, observed speed (km/h), and zone speed limit (km/h)
- Calculate excess speed and classify: MINOR (1–10 over), MODERATE (11–20 over), SEVERE (>20 over)
- Record a SpeedingIncidentEvent with severity via a domain event port
- Return a SpeedingResult with the classification and excess amount

Use hexagonal architecture. Write JUnit 5 unit tests for each severity band and the edge case of exactly at the limit.
```
</details>

<details>
<summary>Variant D — Prompt (VehicleOdometer value object)</summary>

```
Write a VehicleOdometer value object in Java 21:
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
</details>

---

## Tier 3 Variants (Expert — F, G)

### Variant F — Violation Detection + Refactor

**Difficulty tier: 3 (Expert)**

```
The following controller class has 5 distinct architectural violations in a
hexagonal Java 21 Spring Boot project. Identify ALL 5 violations by name and
location, then produce a fully corrected refactored version of the class.
Do NOT add new business logic — only fix the violations.

```java
@RestController
@RequestMapping("/api/vehicles")
public class VehicleController {

    @Autowired  // violation?
    private EntityManager entityManager;

    @GetMapping("/{id}/status")
    public ResponseEntity<Map<String, Object>> getStatus(@PathVariable String id) {
        // direct persistence query in controller
        Vehicle v = entityManager.find(Vehicle.class, id);
        if (v == null) return ResponseEntity.notFound().build();

        // business logic embedded in controller
        boolean overdue = v.getLastServiceDate()
            .isBefore(LocalDate.now().minusDays(90));
        String status = overdue ? "OVERDUE" : "OK";

        // domain object returned as raw map (leaking internal model)
        Map<String, Object> result = new HashMap<>();
        result.put("vehicleId", id);
        result.put("status", status);
        result.put("lastService", v.getLastServiceDate().toString());
        result.put("internalFlag", v.isInternalMaintenanceFlag()); // leaking internal
        return ResponseEntity.ok(result);
    }

    @PostMapping("/{id}/service")
    public void recordService(@PathVariable String id, @RequestBody Map<String, String> body) {
        // no input validation
        Vehicle v = entityManager.find(Vehicle.class, id);
        v.setLastServiceDate(LocalDate.parse(body.get("date")));
        entityManager.merge(v); // transaction management in controller
    }
}
```

Name each violation and explain why it is a violation. Then produce corrected
classes in the correct hexagonal layers (domain, application, infrastructure/web).
```

**Scoring Rubric (Variant F)**

| Dimension | 5 | 3 | 1 |
|---|---|---|---|
| **Violation identification** | All 5 named correctly (field injection, direct EntityManager, business logic in controller, domain model leaking, no input validation) | 3–4 named | ≤2 named |
| **Violation explanations** | Each violation explained with reference to hexagonal principle violated | Brief explanations | No explanations |
| **Correct layer placement** | Controller → InboundPort → UseCase → OutboundPort → Adapter; no leakage | Minor placement issue | Wrong layers used |
| **DTO / response model** | Dedicated response DTO returned (no domain object or raw Map) | Partial DTO | Raw Map or domain object returned |
| **Input validation** | Jakarta validation annotations or guard clauses present | Manual null check only | No validation |
| **No new business logic** | Refactor is pure structural — no new behaviour added | One minor addition | Significant new logic added |

---

### Variant G — Event-Sourced Aggregate

**Difficulty tier: 3 (Expert)**

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

**Scoring Rubric (Variant G)**

| Dimension | 5 | 3 | 1 |
|---|---|---|---|
| **Command → Event separation** | Commands are void/throw; state changes only via `apply(event)` methods | Mixed (some state set in command handlers) | State mutated directly in command handlers |
| **Reconstitution correctness** | `apply(List<DomainEvent>)` rebuilds identical state — test passes | Partial reconstitution (some fields wrong) | Reconstitution not implemented or fails |
| **Guard enforcement** | Both guards implemented with descriptive messages; test covers them | One guard missing or no test | Guards absent |
| **Event completeness** | All 3 event types produced with correct fields; `DrivingSessionEnded` computes duration + maxSpeed from state | 2 event types | 1 or 0 event types |
| **Domain purity** | Aggregate has zero framework annotations or infra imports | Minor infra leakage | Spring/JPA annotations on aggregate |
| **Test quality** | Full round-trip test: create → events → reconstitute → assert; covers both guard paths | Happy path only | Trivial or incomplete test |


