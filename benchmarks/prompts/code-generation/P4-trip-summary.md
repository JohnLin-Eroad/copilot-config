# Prompt P4: Trip Summary Read Model

## Prompt

```
Write a Java 21 Spring Boot 3.4 implementation for the following:

Domain: A `TripSummary` read model in the domain layer that:
- Represents a completed trip with: tripId (UUID), vehicleId (UUID), driverId (UUID), startTime (Instant), endTime (Instant), distanceKm (double), durationMinutes (long), averageSpeedKmh (double), fuelUsedLitres (Optional<Double>)
- Is immutable (use a Java record)
- Has computed methods:
  - `fuelEfficiency()` — returns Optional<Double> (litres per 100km), empty if no fuel data
  - `duration()` — returns Duration between start and end
  - `isLongHaul()` — true if distance > 200km or duration > 4 hours
- Has a static factory `from(TripStartedEvent start, TripCompletedEvent end, Optional<FuelRecord> fuel)` that projects the summary from events

Then write the event records:
- `TripStartedEvent(UUID tripId, UUID vehicleId, UUID driverId, Instant startTime)`
- `TripCompletedEvent(UUID tripId, Instant endTime, double distanceKm)`
- `FuelRecord(UUID tripId, double litresUsed)`

Then write a mapper class `TripSummaryMapper` that converts TripSummary to a DTO record `TripSummaryDto` suitable for API responses (all fields as strings/numbers, ISO 8601 timestamps, optional fuel as null).

Then write JUnit 5 tests covering: factory projection from events, computed methods (efficiency, duration, isLongHaul), edge cases (zero distance, no fuel data, exactly 200km boundary).
```

## Expected Behavior

Agent produces:
1. `TripSummary.java` — Record with computed methods and factory
2. `TripStartedEvent.java`, `TripCompletedEvent.java`, `FuelRecord.java` — Event records
3. `TripSummaryMapper.java` — Domain-to-DTO mapper
4. `TripSummaryDto.java` — DTO record
5. `TripSummaryTest.java` — Comprehensive tests

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Correctness | 20% | Factory or computations wrong | Mostly correct | All projections and computations accurate, Optional handled |
| Hexagonal compliance | 25% | Mapper in domain, DTO in domain | Mapper placement wrong | Domain pure, mapper in application/infra, DTO outside domain |
| Java 21 idioms | 20% | No records, mutable state | Partial records usage | Records everywhere, Optional API fluent usage, Duration API |
| Javadoc completeness | 15% | Missing | Partial | All public methods + events documented |
| Test quality | 20% | Missing edge cases | Happy path covered | Boundary: 200km exactly, zero distance, empty fuel, efficiency calculation |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

Key computations:
- `fuelEfficiency()` = (litresUsed / distanceKm) × 100, empty if no fuel or zero distance
- `isLongHaul()` = distanceKm > 200 OR Duration.between(start, end) > 4 hours
- Mapper must format Instant as ISO 8601 string, Optional<Double> as nullable
