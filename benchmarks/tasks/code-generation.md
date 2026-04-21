# Benchmark Task 1: Code Generation

## Purpose
Tests the developer agent's ability to generate correct, idiomatic, hexagonally-compliant Java code from a written specification.

## Input Prompt

```
Write a Java 21 Spring Boot 3.4 implementation for the following:

Domain: A `VehicleOdometer` value object in the domain layer that:
- Holds a reading in kilometres (positive integer)
- Is immutable (use a Java record)
- Has a factory method `of(int km)` that throws IllegalArgumentException if km < 0
- Has a method `plus(VehicleOdometer other)` that returns a new VehicleOdometer
- Includes Javadoc on all public methods

Then write a port interface `OdometerRepository` in the application layer with:
- `save(VehicleId vehicleId, VehicleOdometer reading)` — void
- `findLatest(VehicleId vehicleId)` — returns Optional<VehicleOdometer>
- Full Javadoc

Then write a JUnit 5 unit test for VehicleOdometer covering: valid creation, zero value, negative value rejection, and addition.
```

## Scoring Rubric

Score each dimension 1–5, then average:

| Dimension | 1 (fail) | 3 (acceptable) | 5 (excellent) |
|---|---|---|---|
| **Correctness** | Doesn't compile or has logic bugs | Compiles, minor issues | All methods correct, edge cases handled |
| **Hexagonal compliance** | Domain imports infra or wrong layer placement | Minor violation | Perfect: record in domain, interface in application, no cross-layer imports |
| **Java 21 idioms** | Uses class where record fits, @Autowired fields | Mostly correct | Records, constructor injection, Optional used correctly |
| **Javadoc completeness** | Missing or empty | Partial (some methods) | All public methods documented, @param and @return present |
| **Test quality** | Tests trivial getters only | Covers happy path | Covers happy path + all edge cases (zero, negative, addition) |

**Final score** = average of 5 dimensions (1–100)

## What Good Looks Like (Score 5)

```java
// domain layer
/** Immutable odometer reading in kilometres. */
public record VehicleOdometer(int kilometres) {
    /**
     * Creates a new odometer reading.
     * @param km reading in kilometres
     * @throws IllegalArgumentException if km is negative
     */
    public static VehicleOdometer of(int km) {
        if (km < 0) throw new IllegalArgumentException("Odometer cannot be negative: " + km);
        return new VehicleOdometer(km);
    }
    /** Returns a new reading that is the sum of this and other. */
    public VehicleOdometer plus(VehicleOdometer other) {
        return new VehicleOdometer(this.kilometres + other.kilometres);
    }
}
```

## Grader Notes for benchmark-runner

After generating the code, evaluate it against each dimension with explicit reasoning. Provide a score for each dimension and an overall average. Note any specific issues or standout qualities.
