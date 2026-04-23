# Prompt P1: Vehicle Odometer

## Prompt

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

## Expected Behavior

Agent produces 3 files:
1. `VehicleOdometer.java` — Java record in domain layer, immutable, factory method with validation
2. `OdometerRepository.java` — Port interface in application layer, no infrastructure imports
3. `VehicleOdometerTest.java` — JUnit 5 tests covering all 4 cases

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Correctness | 20% | Doesn't compile or has logic bugs | Compiles, minor issues | All methods correct, edge cases handled |
| Hexagonal compliance | 25% | Domain imports infra or wrong layer placement | Minor violation | Perfect: record in domain, interface in application, no cross-layer imports |
| Java 21 idioms | 20% | Uses class where record fits, @Autowired fields | Mostly correct | Records, constructor injection, Optional used correctly |
| Javadoc completeness | 15% | Missing or empty | Partial (some methods) | All public methods documented, @param and @return present |
| Test quality | 20% | Tests trivial getters only | Covers happy path | Covers happy path + all edge cases (zero, negative, addition) |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

```java
public record VehicleOdometer(int kilometres) {
    public static VehicleOdometer of(int km) {
        if (km < 0) throw new IllegalArgumentException("Odometer cannot be negative: " + km);
        return new VehicleOdometer(km);
    }
    public VehicleOdometer plus(VehicleOdometer other) {
        return new VehicleOdometer(this.kilometres + other.kilometres);
    }
}
```
