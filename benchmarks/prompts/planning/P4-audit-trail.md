# Prompt P4: Compliance Audit Trail

## Prompt

```
Design a compliance event audit trail for the sovereign platform.

Requirements:
- All compliance events (driving hours, vehicle inspections, speed violations) must be logged
- 7-year retention for regulatory compliance (NZ Transport Agency requirements)
- Tamper-proof: once written, entries cannot be modified or deleted
- Queryable: fleet managers can search by date range, driver, vehicle, event type
- Must support export to CSV/PDF for regulatory submissions

Produce a detailed implementation plan with data model, storage strategy, and
tamper-proofing mechanism.
```

## Expected Behavior

Plan addresses:
- Append-only data model (no UPDATE/DELETE on audit entries)
- Tamper-proofing: hash chaining, digital signatures, or event sourcing
- Storage strategy: partitioned by date, archive to cold storage after 1 year
- Query interface: indexed by driver_id, vehicle_id, event_type, timestamp
- Export service for CSV/PDF generation
- Hexagonal placement: AuditEntry in domain, storage/export in infrastructure
- 7-year retention calculation and pruning strategy

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Domain understanding | 15% | No audit model | Basic logging | AuditEntry entity, ComplianceEventType enum, tamper-proof invariants in domain |
| Hexagonal architecture | 20% | All mixed together | Partial | Domain: AuditEntry, Application: AuditUseCase, Infrastructure: storage + export adapters |
| Blast radius assessment | 15% | None | Vague | Specific: storage costs, query performance at scale, migration from existing logs |
| Edge cases | 15% | None | 1-2 | ≥4: clock skew, hash chain recovery, concurrent writes, timezone, retention boundary |
| Dependency ordering | 15% | Unordered | Partial | Phased: domain model → storage → indexing → query API → export → migration |
| Acceptance criteria | 20% | None | Vague | Measurable: "Query 1M entries in < 500ms", "No entry modified after creation", "7-year data retrievable" |

**Score = weighted average of dimensions (0-100)**
