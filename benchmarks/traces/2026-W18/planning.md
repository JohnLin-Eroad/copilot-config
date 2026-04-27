# Trace: planning — 2026-W18

## Metadata
- Prompt ID: P2-multi-tenancy
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-04-27T22:15:03Z
- Duration: 400.2s

## Prompt Sent
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

## Raw Output
Now let me search for organization/tenant/account/fleet patterns and find migration files:Now I have enough information. Let me compile the comprehensive report:

---

## **MULTI-TENANCY CURRENT STATE ANALYSIS**

### **1. Organization/Tenant Concepts**
**Status: NONE EXIST** (single-tenant only)

- ✗ No `organisation`, `organization`, `tenant`, `fleet`, or `account` references found in Java code across `api/domain`, `api/application`, `api/infrastructure`, `api/web`
- ✗ No `org_id`, `tenant_id`, `fleet_id`, or `account_id` columns in any tables
- **Source:** `/Users/johnlin/sovereign/api/infrastructure/src/main/resources/db/migration/` (all 4 migrations are tenant-unaware)
- **Note:** ADR-0001-multi-tenancy.md confirms baseline audit: "there is no notion of an organisation, tenant, or fleet anywhere in the data model"

---

### **2. Database Migrations**

**Location:** `/Users/johnlin/sovereign/api/infrastructure/src/main/resources/db/migration/`

**Migration Files (Flyway 10.10.0):**
- **V1__initial_schema.sql** — 12 core execution/workflow/analytics tables
- **V2__eroad_catalog.sql** — Reference data: tribes, squads, domains, repos (no tenant scope)
- **V3__local_repos.sql** — Local repo clone tracking
- **V4__agent_job_log.sql** — Agent idempotency & audit (latest/HEAD)

---

### **3. JPA Entities & Tables**

**Entity Files Found:**
- `/Users/johnlin/sovereign/api/infrastructure/src/main/java/com/sovereign/infrastructure/repository/AgentJobLogEntity.java` (@Entity, @Table(name = "agent_job_log"))

**20 Tables Created (from migrations, **none tenant-scoped**):**

| Category | Tables |
|----------|--------|
| **Execution/Workflow** | `execution_runs`, `workflow_items`, `execution_decisions`, `improvement_workflow_entries` |
| **Analytics/Usage** | `llm_usage_records`, `cost_attributions`, `fact_studio_usage`, `engine_health_snapshots` |
| **Audit/Operations** | `agent_audit_log`, `agent_job_log`, `operation_records` |
| **Studio/Chat** | `studio_conversations`, `studio_messages` |
| **Reference/Catalog** | `eroad_tribes`, `eroad_squads`, `eroad_domains`, `eroad_domain_squads`, `eroad_repos` |
| **Local Repos** | `local_repos` |

**All 20 tables lack `organisation_id` or `tenant_id` column** — will need multi-tenancy retrofit.

---

### **4. Auth/Security Setup**

**Current State: NONE (completely open)**

- ✗ **No Spring Security** in pom.xml (checked all 7 modules)
- ✗ **No JWT** implementation (no `JwtAuthenticationFilter`, `Jwt*` classes found)
- ✗ **No `SecurityContextHolder`**, `UserDetails`, `Authentication` usage
- ✗ **Controllers have no auth parameters** — all endpoints accept unauthenticated requests
  - `/Users/johnlin/sovereign/api/web/src/main/java/com/sovereign/web/controllers/` — 7 controllers, all stateless, no principal extraction
- ✓ **CORS configured** but NOT for auth (`allowCredentials=false`)
  - `/Users/johnlin/sovereign/api/web/src/main/java/com/sovereign/web/WebConfig.java` — allows "Authorization" header (prep for future JWT, but unused)
- **External JWT Only:** `CopilotChatService` uses Bearer token for GitHub Copilot API (not internal auth)

**Implication:** Auth layer must be built from scratch; ADR-0001 proposes JWT → TenantContext → Postgres session var flow.

---

### **5. Hibernate Filters / PostgreSQL RLS / Tenant Resolver**

**Status: NONE FOUND**

```bash
grep -r "@Filter\|@FilterDef\|CurrentTenantIdentifierResolver\|RowLevel" /api → (no matches)
```

- ✗ No `@Filter` or `@FilterDef` annotations
- ✗ No `CurrentTenantIdentifierResolver` implementation
- ✗ No Postgres RLS policies configured
- ✗ No Hibernate interceptors or custom `EntityManager` wiring

**All must be implemented as part of multi-tenancy retrofit.**

---

### **6. Architecture Documentation (ADRs)**

**Location:** `/Users/johnlin/sovereign/docs/adr/`

**Existing ADRs:**
- `ADR-0001-multi-tenancy-fleet-isolation.md` (27 Apr, v1 — superseded)
- `ADR-0001-multi-tenancy.md` (28 Apr, CURRENT — **Status: Proposed**)

**Next ADR Number:** `ADR-0002-*`

**Key ADR-0001 Decision:** Shared database, shared schema, discriminator column (`organisation_id`) + PostgreSQL RLS + Hibernate `@Filter` for defence-in-depth. JWT → TenantContext servlet filter → `SET LOCAL app.current_tenant`.

---

### **7. Spring Boot / Dependencies**

**Parent POM:** `/Users/johnlin/sovereign/api/pom.xml`

```
Spring Boot:              3.4.0
Java:                     21
Flyway:                   10.10.0
PostgreSQL driver:        (included, runtime scope)
Hibernate:                (via spring-boot-starter-data-jpa, no explicit version override)
Spring Security:          ✗ NOT PRESENT
```

**Module Dependencies:**
- `api/infrastructure/pom.xml` → `spring-boot-starter-data-jpa`, `flyway-core`, `postgresql`
- `api/web/pom.xml` → `spring-boot-starter-web`, `spring-boot-starter-actuator` (no security)
- `api/application/pom.xml` → `spring-boot-starter` only
- `api/domain/pom.xml` → `jakarta.persistence-api` only

**Multi-Tenancy Dependencies: NONE** (will need to add `spring-security-web`, `jjwt` or similar, potentially `hibernate-core` with explicit filter/interceptor wiring).

---

## **SUMMARY**

| Aspect | Status | Notes |
|--------|--------|-------|
| **Multi-Tenancy** | ❌ None | Single-tenant only; ADR-0001 proposed but not implemented |
| **Auth Layer** | ❌ None | No Spring Security; all endpoints open; JWT planned |
| **Isolation** | ❌ None | No org/tenant column, no RLS, no Hibernate filters |
| **Migrations** | ✓ Present | 4 Flyway migrations (V1–V4); all table-creation, no org support |
| **Entities** | Minimal | Only 1 explicit @Entity found; repositories likely use Spring Data projections or ad-hoc queries |
| **Documentation** | ✓ ADR exists | ADR-0001-multi-tenancy.md ready (Proposed); next ADR = 0002 |
| **Spring Boot** | ✓ 3.4.0 | No multi-tenancy libraries installed; clean slate for retrofit |

**Blast Radius for Multi-Tenancy Retrofit: HIGH** — all 20 tables need org_id column; all repositories need filtering; auth layer must be built.● Explore Survey current tenancy model
  │ Check second migration for catalog tables (shell)
  │   │ cat /Users/johnlin/sovereign/api/infrastructure/src/main/resources/db/migrat
  │   │ ion/V2__eroad_catalog.sql | head -40
  │   └ 41 lines...
  └ Check third migration (shell)
      │ cat /Users/johnlin/sovereign/api/infrastructure/src/main/resources/db/migrat
      │ ion/V3__local_repos.sql
      └ 18 lines...

✗ Read ADR-0001-multi-tenancy.md
  │ docs/adr/ADR-0001-multi-tenancy.md
  └ Tool 'view' does not exist.

● General-purpose(claude-opus-4.7) Author ADR-0002 implementation plan
  │ Read ADR-0001-multi-tenancy.md
  │   │ docs/adr/ADR-0001-multi-tenancy.md
  │   └ 283 lines read
  └ Create ADR-0002-multi-tenancy-implementation-plan.md +463
      └ docs/adr/ADR-0002-multi-tenancy-implementation-plan.md

ADR-0002 written: `/Users/johnlin/sovereign/docs/adr/ADR-0002-multi-tenancy-implementation-plan.md`

## Summary

**Decision (builds on ADR-0001):** Shared DB / shared schema with **three-layer defence-in-depth**:
1. `organisation_id` discriminator column on 14 tenant-scoped tables (5 EROAD reference tables excluded)
2. Postgres **Row-Level Security** policies, with app role losing `BYPASSRLS`
3. Hibernate `@Filter` for early-fail in tests + better query plans

**Tenant resolution:** JWT (`org`, `role` claims) → `JwtAuthenticationFilter` → `TenantContextFilter` (ThreadLocal) → transaction-scoped `SET LOCAL app.current_tenant = '<uuid>'`. HikariCP-safe because `SET LOCAL` resets at COMMIT.

**Super-admin:** sentinel `'SUPER_ADMIN'` value bypasses RLS via `OR current_setting(...) = 'SUPER_ADMIN'` and short-circuits the Hibernate filter; all actions audited with `acting_role` + `target_organisation_id` columns added to `agent_audit_log`.

**Migration — 5 feature-flagged stages, each independently rollback-able:**
- **V5** additive schema + backfill `DEFAULT_ORG` + composite `(organisation_id, id)` indexes
- Auth layer (Spring Security + jjwt 0.12.x)
- App-level enforcement
- **V6** RLS enable + remove `BYPASSRLS`
- Org onboarding endpoints

**Blast Radius: HIGH** — breaks all unauthenticated API consumers; mitigated by staged rollout, perf benchmark gates, and explicit composite indexes to keep single-tenant query latency within 5% of baseline.

**Rejected alternatives:** DB-per-tenant (ops cost), schema-per-tenant (migration fan-out), app-filter-only (single missed `WHERE` = data leak), RLS-only (debuggability), Citus (overkill).

## Grading Reasoning
This is a strong, implementation-oriented plan with clear architecture choices, high-quality blast-radius analysis, and a practical phased migration strategy. The main gap is tighter, explicit acceptance criteria and more direct articulation of hexagonal boundary guarantees.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| domain_understanding | 15% | 90 | Strong tenant-boundary modeling: "organisation_id discriminator column on 14 tenant-scoped tables" and "Each fleet organisation sees only its own data" is addressed via org-scoped design plus super-admin override. It consistently frames isolation around organisations/fleets rather than generic users. |
| hexagonal_architecture | 20% | 78 | Good infrastructure-oriented placement is shown by "JWT ... -> TenantContextFilter (ThreadLocal) -> SET LOCAL app.current_tenant" and "Postgres RLS"/"Hibernate @Filter". However, it does not explicitly state/enforce that domain remains tenancy-unaware, so architecture boundary handling is implied rather than fully articulated. |
| blast_radius_assessment | 15% | 92 | Clear and specific blast radius: "HIGH ... all 20 tables need org_id column; all repositories need filtering; auth layer must be built" and later "breaks all unauthenticated API consumers." It also touches operational concerns like connection behavior: "HikariCP-safe because SET LOCAL resets at COMMIT." |
| edge_cases | 15% | 80 | Multiple edge conditions are covered: super-admin bypass ("sentinel 'SUPER_ADMIN'"), rollbackability ("5 feature-flagged stages, each independently rollback-able"), connection/session safety ("HikariCP-safe"), and auditability ("acting_role + target_organisation_id"). Cross-tenant query validation is addressed indirectly via RLS/filter design, but not deeply enumerated as explicit scenarios. |
| dependency_ordering | 15% | 88 | Phasing is explicit and mostly well ordered: "V5 additive schema + backfill ... indexes" then "Auth layer" then "App-level enforcement" then "V6 RLS enable" then onboarding endpoints. This matches a practical schema-first rollout with gated enforcement. |
| acceptance_criteria | 20% | 68 | Some measurable signal exists ("single-tenant query latency within 5% of baseline"), and functional goals are implied (super-admin visibility, org isolation). But criteria are not consistently written as concrete pass/fail checks (e.g., explicit Fleet A vs Fleet B test cases, p99 targets, migration success metrics). |

## Overall Score: 81.7/100
