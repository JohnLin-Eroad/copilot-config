# Prompt P5: Violation Detection + Refactor

**Difficulty tier: 3 (Expert)** — source: tasks/code-generation.md Variant F

## Prompt

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

## Expected Behavior

Agent identifies all 5 violations: (1) field injection via @Autowired, (2) direct EntityManager in controller (persistence in adapter), (3) business logic (overdue calc) in controller, (4) domain object / internal flag leaking via Map, (5) missing input validation / transaction in controller. Then produces refactored code split across domain / application (use case + ports) / infrastructure (web adapter + persistence adapter).

## Grading Rubric

| Dimension | Weight | 0 | 50 | 100 |
|---|---|---|---|---|
| Violation identification | 25% | ≤2 named | 3–4 named | All 5 named correctly |
| Violation explanations | 15% | None | Brief | Each tied to hexagonal principle |
| Correct layer placement | 25% | Wrong layers | Minor placement issue | Controller → InboundPort → UseCase → OutboundPort → Adapter; no leakage |
| DTO / response model | 10% | Raw Map / domain object | Partial DTO | Dedicated response DTO |
| Input validation | 10% | None | Manual null check only | Jakarta validation or guard clauses |
| No new business logic | 15% | Significant new logic | One minor addition | Pure structural refactor |

**Score = weighted average (0–100)**

## Auto-Checks

```yaml
- name: identifies-field-injection
  must_contain_any: ["field injection", "@Autowired on field", "constructor injection"]
  case_insensitive: true
- name: identifies-persistence-in-controller
  must_contain_any: ["EntityManager", "persistence", "repository", "adapter"]
  case_insensitive: true
- name: identifies-business-logic-leak
  must_contain_any: ["business logic", "domain logic", "use case", "overdue"]
  case_insensitive: true
- name: identifies-dto-leak
  must_contain_any: ["DTO", "response model", "leaking", "raw Map"]
  case_insensitive: true
- name: identifies-validation-gap
  must_contain_any: ["validation", "@Valid", "guard"]
  case_insensitive: true
- name: produces-refactor
  must_contain_all: ["class", "public"]
  must_contain_any: ["UseCase", "Service", "Port"]
```

## Ground Truth

Expected hexagonal structure:
- Domain: `Vehicle` aggregate with `isServiceOverdue()` behaviour
- Application: `GetVehicleStatusUseCase`, `RecordServiceUseCase`, `VehicleRepository` port
- Infrastructure/web: `VehicleController` thin adapter; `VehicleStatusResponse` DTO; `@Valid` on request body
- Infrastructure/persistence: JPA-backed `VehicleRepository` impl with transactional boundary
