# Prompt P3: Compliance Threshold Policy

## Prompt

```
Write a Java 21 Spring Boot 3.4 implementation for the following:

Domain: A `ComplianceThreshold` policy object in the domain layer that:
- Represents configurable driving time limits per jurisdiction
- Has fields: jurisdiction (String, e.g. "NZ", "AU"), warningHours (int), criticalHours (int), restPeriodHours (int)
- Uses the Builder pattern for construction
- Validates on build: warningHours < criticalHours, all values > 0, restPeriodHours >= 7
- Has methods:
  - `isWarning(Duration drivingTime)` — true if driving time >= warningHours
  - `isCritical(Duration drivingTime)` — true if driving time >= criticalHours
  - `isCompliant(Duration drivingTime)` — true if driving time < warningHours
  - `requiredRest()` — returns Duration of required rest period
- Is immutable (final fields, no setters)
- Includes Javadoc on all public methods

Then write a factory class `ComplianceThresholdDefaults` that provides:
- `newZealand()` — returns threshold with warning=11, critical=13, rest=10
- `australia()` — returns threshold with warning=12, critical=14, rest=7

Then write JUnit 5 tests covering: builder validation (all constraint violations), isWarning/isCritical/isCompliant boundary conditions, and factory defaults.
```

## Expected Behavior

Agent produces:
1. `ComplianceThreshold.java` — Immutable policy with builder, validation, duration checks
2. `ComplianceThresholdDefaults.java` — Static factory with NZ/AU defaults
3. `ComplianceThresholdTest.java` — Boundary tests and validation tests

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Correctness | 20% | Builder allows invalid state | Most validation works | All constraints enforced, boundary conditions exact |
| Hexagonal compliance | 25% | Uses framework annotations in domain | Minor violation | Pure domain: no Spring imports, no infra dependencies |
| Java 21 idioms | 20% | Lombok or pre-Java 16 patterns | Mostly modern | Builder with private constructor, Duration API, Optional where appropriate |
| Javadoc completeness | 15% | Missing | Partial | Complete with @param/@return/@throws, builder methods documented |
| Test quality | 20% | Only happy path | Most cases | Boundary tests: exactly at warning/critical hours, builder constraint violations |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

Key boundary conditions:
- `isWarning(Duration.ofHours(11))` for NZ → true (exactly at threshold)
- `isWarning(Duration.ofHours(10).plusMinutes(59))` for NZ → false (just below)
- `isCritical(Duration.ofHours(13))` for NZ → true
- Builder with warningHours >= criticalHours → IllegalArgumentException
- Builder with restPeriodHours < 7 → IllegalArgumentException
