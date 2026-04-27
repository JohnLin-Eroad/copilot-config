# Benchmark Task 1: Code Generation

## Purpose

Tests the developer agent's ability to generate correct, idiomatic, hexagonally-compliant Java code. Prompts rotate weekly via the prompt pool system (see `prompts/INDEX.md`).

## Prompt Pool

Prompts are in `prompts/code-generation/P1-P4.md`. Each prompt file includes its own rubric, expected behavior, and ground truth. The benchmark-runner selects the prompt using the rotation formula — do NOT select manually.
## General Scoring Dimensions

Each prompt file (`P1-P4`) defines its own rubric. All rubrics score these common dimensions (0-100 per dimension, weighted average for final score):

- **Correctness** — Does the code compile and work as specified?
- **Hexagonal compliance** — Are classes placed in the correct layers (domain, application, infrastructure)?
- **Java 21 idioms** — Records, sealed classes, pattern matching, constructor injection, Optional
- **Test quality** — Coverage of happy path, edge cases, and boundary conditions
- **Design justification** — Clear rationale for layer placement and design decisions

## Grader Notes for benchmark-runner

1. Read the selected prompt file — it contains the specific rubric, expected behavior, and ground truth
2. Score each dimension in the prompt's rubric with explicit reasoning
3. Calculate weighted average for the final score (0-100)
4. Write trace to `traces/$WEEK/code-generation.md` including the prompt ID, all dimension scores, and reasoning

---

## Future Prompt Candidates (Tier 3 — Expert)

These are not yet in the active prompt pool. Add them as P5/P6 when the pool needs fresh challenges.

### Variant F — Violation Detection + Refactor

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
        Vehicle v = entityManager.find(Vehicle.class, id);
        if (v == null) return ResponseEntity.notFound().build();

        boolean overdue = v.getLastServiceDate()
            .isBefore(LocalDate.now().minusDays(90));
        String status = overdue ? "OVERDUE" : "OK";

        Map<String, Object> result = new HashMap<>();
        result.put("vehicleId", id);
        result.put("status", status);
        result.put("lastService", v.getLastServiceDate().toString());
        result.put("internalFlag", v.isInternalMaintenanceFlag());
        return ResponseEntity.ok(result);
    }

    @PostMapping("/{id}/service")
    public void recordService(@PathVariable String id, @RequestBody Map<String, String> body) {
        Vehicle v = entityManager.find(Vehicle.class, id);
        v.setLastServiceDate(LocalDate.parse(body.get("date")));
        entityManager.merge(v);
    }
}
```

Name each violation and explain why it is a violation. Then produce corrected
classes in the correct hexagonal layers (domain, application, infrastructure/web).
```

**Rubric (Variant F):** Violation identification (all 5), violation explanations, correct layer placement, DTO/response model, input validation, no new business logic.

### Variant G — Event-Sourced Aggregate

```
Implement a DrivingSessionAggregate in Java 21 using the event-sourcing pattern.

The aggregate must:
1. Commands: StartSession, RecordSpeedReading, EndSession
2. Events: DrivingSessionStarted, SpeedReadingRecorded, DrivingSessionEnded
3. Reconstitutable from past events via apply(List<DomainEvent> history)
4. Guards: no end before start, no readings after end (IllegalStateException)

Write a JUnit 5 round-trip test: create → record 3 readings → end → serialise events → reconstitute from events → assert state matches.
```

**Rubric (Variant G):** Command→Event separation, reconstitution correctness, guard enforcement, event completeness, domain purity, test quality.
