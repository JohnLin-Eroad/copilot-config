# Prompt P2: Multi-Tenancy Isolation

## Prompt

```
Design multi-tenancy support for the sovereign platform. Fleet organisations must be
isolated at the database level.

Requirements:
- Each fleet organisation sees only its own data
- A super-admin can see all organisations
- The solution must work with the existing PostgreSQL setup
- Performance impact should be minimal for single-tenant queries
- Migration path from current shared-tenant model must be defined

Produce a detailed implementation plan with architecture decisions, blast radius assessment,
and migration strategy.
```

## Expected Behavior

Plan addresses:
- Schema-per-tenant vs row-level security vs separate databases (with trade-offs)
- Concrete decision with rationale
- Hibernate/JPA multi-tenant configuration
- Migration strategy (data partitioning, tenant_id column addition)
- Performance considerations (connection pooling, query planning)
- Blast radius assessment (HIGH — affects every query)
- Rollback plan

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Domain understanding | 15% | No mention of organisations/fleets | Basic mention | Correctly models Organisation, Fleet, tenant boundary |
| Hexagonal architecture | 20% | Tenancy leaks into domain | Partial isolation | Tenant resolution in infrastructure, domain unaware of tenancy |
| Blast radius assessment | 15% | None | "It's big" | Specific: every repository, every query, connection pooling, migration downtime |
| Edge cases | 15% | None | 1-2 | ≥4: cross-tenant queries, super-admin, migration rollback, connection pool exhaustion |
| Dependency ordering | 15% | Unordered | Partial | Phased: schema first → repository changes → API changes → migration → verification |
| Acceptance criteria | 20% | None | Vague | Measurable: "Fleet A cannot see Fleet B data", "Super-admin sees all", "Query latency < 10ms p99" |

**Score = weighted average of dimensions (0-100)**
