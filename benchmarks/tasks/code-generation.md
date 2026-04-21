# Benchmark Task 1: Code Generation

## Purpose
Tests the developer agent's ability to generate correct, idiomatic, hexagonally-compliant Java code from a **multi-file refactoring scenario** with deliberate ambiguity. This task rotates scenarios weekly to prevent Goodhart's Law (see Variant Rotation below).

## Active Variant

> **Rotate this each week.** Pick the next variant from the list below and update "Active Variant" to point to it.

**Current variant: B — Use Case + Port + Adapter**

## Input Prompt (Variant B)

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

## Scoring Rubric

Score each dimension 1–5, then average:

| Dimension | 1 (fail) | 3 (acceptable) | 5 (excellent) |
|---|---|---|---|
| **Correctness** | Logic errors or won't compile | Compiles, minor issues | Correct boundary math (10 L/100km), all paths correct |
| **Hexagonal compliance** | Domain imports infra; use case in wrong layer | Minor violation | Domain has zero infra imports; use case depends only on domain + port interface |
| **Java 21 idioms** | Uses class where record fits, field injection | Mostly correct | Records, sealed interfaces or enums for result, constructor injection, Optional |
| **Design quality** | Threshold hardcoded in use case or test | Threshold in use case | Threshold is a domain constant — business rule lives in domain layer |
| **Test quality** | Tests trivial getters only | Happy path covered | Boundary conditions (exactly 10.0), both outcomes, port interaction verified via mock |
| **Ambiguity handling** | Invents requirements not in spec | Implements spec literally | Asks about or explicitly documents one design decision (e.g., what "store" means) |

**Final score** = average of 6 dimensions (1.0–5.0)

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
