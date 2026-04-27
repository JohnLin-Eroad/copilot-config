# Trace: planning — 2026-W18

## Metadata
- Prompt ID: P2-multi-tenancy
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-04-27T12:19:25Z
- Duration: 1948.4s

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
Good start. Let me explore entities, migrations, and configuration:Perfect! NowPerfect! Now I have a comprehensive picture. Let me deliver a concise architect's map:

---

## **SOVEREIGN MULTI-TENANCY BASELINE AUDIT**

### **1. CURRENT DATA MODEL**

**Flyway Migration V1–V4 defines 12+ tables (PostgreSQL):**

| Entity (package: `com.sovereign.domain.entities.*`) | Table | PK | Tenant/Org/Fleet Column? |
|---|---|---|---|
| **execution/** TransformationExecutionRun | `execution_runs` | VARCHAR(255) `execution_run_id` | ❌ |
| WorkflowItem | `workflow_items` | VARCHAR(255) `workflow_item_id` | ❌ |
| LlmUsageRecord | `llm_usage_records` | BIGSERIAL `id` | ❌ |
| **audit/** AgentAuditLog | `agent_audit_log` | BIGSERIAL `id` | ❌ |
| **governance/** ImprovementWorkflowEntry | `improvement_workflow_entries` | VARCHAR(255) `recommendation_id` | ❌ |
| ExecutionDecision | `execution_decisions` | BIGSERIAL `id` | ❌ |
| EngineHealthSnapshot | `engine_health_snapshots` | BIGSERIAL `id` | ❌ |
| **operations/** OperationRecord | `operation_records` | BIGSERIAL `id` | ❌ |
| **studio/** StudioConversation | `studio_conversations` | UUID `id` | ❌ |
| StudioMessage | `studio_messages` | UUID `id` | ❌ |
| **analytics/** FactStudioUsage | `fact_studio_usage` | UUID `fact_id` | ❌ |
| CostAttribution | `cost_attributions` | BIGSERIAL `id` | ❌ |
| **catalog/** EroadDomain, EroadRepo, EroadTribe, EroadSquad, LocalRepo | (V2–V3) | (string PKs) | ❌ |
| **infrastructure/repository/** AgentJobLogEntity | `agent_job_log` | VARCHAR(255) `job_id` | ❌ |

**KEY:** No existing tenant/organisation/fleet isolation column. `userId` / `createdByUserId` exist only in StudioConversation & FactStudioUsage (isolated by user, not org).

---

### **2. DATABASE MIGRATION TOOLING**

- **Tool:** Flyway 10.10.0  
- **Config:** `/Users/johnlin/sovereign/api/web/src/main/resources/application.yml` line 17–19  
  ```yaml
  flyway:
    enabled: true
    locations: classpath:db/migration
  ```
- **Migration Files:** `/Users/johnlin/sovereign/api/infrastructure/src/main/resources/db/migration/`
- **Current Version:** V4__agent_job_log.sql (4 files total)
- **Worker:** Flyway disabled (`flyway.enabled: false` in worker config)

---

### **3. PERSISTENCE CONFIGURATION**

**DataSource (no custom bean):**  
- **Config:** `/Users/johnlin/sovereign/api/web/src/main/resources/application.yml` lines 4–8
- PostgreSQL driver, environment variables: `DATABASE_URL`, `DATABASE_USER`, `DATABASE_PASSWORD`
- ddl-auto: `validate` (Flyway manages schema)

**JPA/Hibernate:**  
- Spring Boot auto-configuration (no explicit `@Bean`)
- Dialect: `PostgreSQLDialect`
- **No Hibernate Interceptors** found  
- **No JPA Filters (@Filter/@FilterDef)** found  

**EntityScan & JpaRepositories:**  
- `/Users/johnlin/sovereign/api/web/src/main/java/com/sovereign/web/SovereignApplication.java` line 6–8:
  ```java
  @EntityScan(basePackages = "com.sovereign.domain.entities")
  @EnableJpaRepositories(basePackages = "com.sovereign.infrastructure.repository")
  ```

---

### **4. AUTHENTICATION & TENANT CONTEXT**

- **NO Spring Security dependency** (not in pom.xml)
- **NO JWT handling** (no JWT library imported)
- **NO SecurityContextHolder / RequestContextHolder** usage detected  
- **User fields** exist but unpopulated:
  - `StudioConversation.createdByUserId` (String, not enforced)
  - `FactStudioUsage.userId` (String, analytics only)
- **Controllers** accept no auth parameters (e.g., `StudioController.listConversations()`)  
- **Implication:** Tenant ID must come from **external gateway/JWT validation layer** or **new upstream interceptor** — not currently in Sovereign.

---

### **5. REPOSITORY PATTERNS**

**Direct JpaRepository usage (Spring Data):**
- 12 repositories in `/Users/johnlin/sovereign/api/infrastructure/src/main/java/com/sovereign/infrastructure/repository/`
- Example: `AgentJobLogRepository extends JpaRepository<AgentJobLogEntity, String>`
- **Port/Adapter Pattern** in **application layer**:
  - Ports defined in `/com/sovereign/application/{audit,catalog,ai,usecases}/` as interfaces (e.g., `AgentAuditPort`)
  - Adapters in `/com/sovereign/infrastructure/{audit,catalog,ai,worker}/` implement ports (e.g., `AgentAuditAdapter`)
  - Adapters directly inject repositories and save entities
  - **No additional abstraction between adapter and repository** (repositories used directly in adapters)

---

### **6. MULTI-MODULE LAYOUT**

```
/api/
├── pom.xml (parent, Spring Boot 3.4.0)
├── domain/                    # Entities only (no Spring, no @Repository)
│   └── entities/
│       ├── execution/
│       ├── audit/
│       ├── governance/
│       ├── operations/
│       ├── studio/
│       ├── analytics/
│       └── catalog/
├── application/               # Ports & services (Spring @Component, no @Repository)
│   └── {audit,catalog,ai,agents,usecases}/
├── infrastructure/            # Repositories & adapters (JPA, Flyway, AWS)
│   ├── repository/             # JpaRepository interfaces
│   ├── audit,catalog,ai,worker/ # Adapter implementations
│   └── src/main/resources/db/migration/
├── integrations/              # External (GitHub, Jira, Confluence, AWS)
└── web/                        # REST controllers, WebConfig, main app
    └── src/main/resources/
        ├── agents/             # 27 agent YAML files
        └── skills/
```

---

### **7. AGENTS & ROLES YAML**

- **Location:** `/Users/johnlin/sovereign/api/web/src/main/resources/agents/`
- **Count:** 27 agent YAML files  
- **Search Result:** ❌ **ZERO references** to `organisation`, `fleet`, or `tenant` in any `.yaml`
- **Sample agent structure** (e.g., `governance-agent.yaml`):
  ```yaml
  roleKey: governance-agent
  roleName: Governance Agent
  namespace: SOV
  status: active
  version: "1.0"
  enabled: true
  displayOrder: 17
  preferredModelKey: azure-claude-opus-4-6
  skillMapping: { governance, security, docs }
  ```
  → **No org/fleet/tenant awareness.**

---

### **MULTI-TENANCY READINESS SUMMARY**

| Dimension | Status | Notes |
|---|---|---|
| **DB isolation pattern** | ❌ Not present | No `tenant_id`/`org_id`/`fleet_id` columns. Full cross-org data exposure. |
| **Row-level filtering** | ❌ None | No Hibernate filters, JPA security, or query interception. |
| **Auth context** | ❌ Missing | No Spring Security, JWT, or tenant-to-context binding. |
| **Tenant extraction** | TBD | Would need upstream gateway or new servlet filter. |
| **Port/Adapter ready** | ✅ Yes | Can inject tenant interceptor into adapter layer. |
| **Flyway ready** | ✅ Yes | Can add V5 migration for `organisation_id` columns + FK constraints. |
| **Multi-module isolation** | ✅ Good | Domain/application/infrastructure separation allows clean tenant-aware adapter impl. |

**Recommended Next Steps:**  
1. Add `organisation_id` VARCHAR(255) + NOT NULL DEFAULT to all core tables in V5 migration  
2. Create `@JpaFilterDef` + `@Filter` for row-level security in entity layer  
3. Implement `TenantContext` ThreadLocal or Spring Cloud Context bean + servlet filter for tenant extraction  
4. Update adapters to enrich saves with tenant from context  
5. Audit controllers/agents for multi-tenant request routing

---● Explore Map current tenancy & data model
  │ Read pom.xml
  │   │ api/web/pom.xml
  │   └ L1:80 (61 lines read)
  └ View main application class (shell)
      │ head -30 /Users/johnlin/sovereign/api/web/src/main/java/com/sovereign/web/So
      │ vereignApplication.java
      └ 18 lines...

● Request failed due to a transient API error. Retrying...

Now let me verify the file was created correctly by checking the line count and confirming existence:✅ **File Created Successfully**

- **Path**: `/Users/johnlin/sovereign/docs/adr/ADR-0001-multi-tenancy.md`
- **Line Count**: 283 lines
- **Size**: 17 KB
- **Status**: File exists and is readable

The ADR document has been created with the exact content you provided, including all markdown formatting, decision architecture, migration phases, blast radius assessment, and acceptance criteria. The file is ready for review.● Task Create ADR file
  │ Create ADR-0001-multi-tenancy.md +284
  │   └ docs/adr/ADR-0001-multi-tenancy.md
  └ Verify file exists and show line count (shell)
      │ wc -l /Users/johnlin/sovereign/docs/adr/ADR-0001-multi-tenancy.md && ls -lh
      │ /Users/johnlin/sovereign/docs/adr/ADR-0001-multi-tenancy.md
      └ 3 lines...

# ADR-0001: Multi-Tenancy — Submitted for Review

**File**: `~/sovereign/docs/adr/ADR-0001-multi-tenancy.md` (283 lines)
**Status**: Proposed — **HIGH blast radius, requires human approval before implementation**

## TL;DR — Decision

**Discriminator-column multi-tenancy with PostgreSQL Row-Level Security (RLS) + Hibernate `@Filter` for defence in depth.** Tenant context flows: JWT → servlet filter → request-scoped `TenantContext` → `SET LOCAL app.current_tenant` GUC on every Hibernate connection.

## Why this pattern

- ✅ **DB-level isolation** (req #1): `FORCE ROW LEVEL SECURITY` on every tenant-scoped table — cannot be bypassed by app bugs or raw SQL.
- ✅ **Super-admin path** (req #2): `app.bypass_rls = 'on'` GUC, set only after JWT role validation; every cross-org read audited.
- ✅ **Existing Postgres** (req #3): no schema/DB split, no new infra.
- ✅ **Minimal perf hit** (req #4): mandatory org-leading composite indexes keep single-tenant p95 within 5%.
- ✅ **Zero-downtime migration** (req #5): 5-phase plan, every phase reversible.

## Migration — 5 phases, all reversible

| Phase | Migration | What | Reversible |
|---|---|---|---|
| 0 | V5–V6 | Create `organisations`/`users`, add nullable `organisation_id` + indexes | ✅ |
| 1 | V7 | Backfill to default org, idempotent, batched | ✅ |
| 2 | (code) | Dual-write release, JWT live, `tenancy.enforce=false` | ✅ |
| 3 | V8 | `NOT NULL` + FK | ✅ |
| 4 | V9 | Enable RLS + flip `tenancy.enforce=true` | ✅ |
| 5 | (code) | Remove transition flags | ✅ |

## Blast Radius: **HIGH**

Key risks called out in the ADR: worker module needs explicit `SystemTenantContext`; raw SQL bypasses the Hibernate filter (RLS still catches it, ArchUnit rule mandated); every integration test needs a `@WithTenant` extension; new `spring-boot-starter-security` dependency.

## Alternatives rejected

DB-per-tenant (operational tax), schema-per-tenant (Hibernate/Flyway awkward), app-filter-only (one missing `WHERE` leaks everything), RLS-only (no clear dev-time errors), per-tenant Postgres roles (pool fragmentation).

## Follow-up ADRs flagged

ADR-0002 JWT issuer · ADR-0003 worker tenant context · ADR-0004 frontend org-switcher · ADR-0005 tenant-aware observability.

**Per governance, no code has been written. Awaiting human review of ADR-0001 before any work package is decomposed.**

## Grading Reasoning
The plan is strong on architecture choice, migration sequencing, and blast-radius specificity, and it maps well to PostgreSQL/RLS constraints. It is weaker on strict fleet-vs-organisation domain modeling, full hexagonal purity, and clearly stated measurable acceptance tests.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Domain understanding | 15% | 68 | Strong tenant/org framing (e.g., "Add `organisation_id`... to all core tables" and "Super-admin path") and clear isolation intent, but it does not clearly model the Organisation–Fleet boundary as distinct domain concepts; it mostly uses organisation/tenant terminology. |
| Hexagonal architecture | 20% | 62 | It recognizes existing ports/adapters ("Port/Adapter Pattern ... adapters directly inject repositories") and routes tenant context via filter/context/adapter, but also proposes "@JpaFilterDef + @Filter for row-level security in entity layer," which pushes tenancy concerns into entities rather than keeping domain clean. |
| Blast radius assessment | 15% | 90 | Very specific and appropriately severe: "Status: Proposed — HIGH blast radius" plus concrete impacts like "worker module needs explicit SystemTenantContext," "raw SQL bypasses the Hibernate filter," "every integration test needs a @WithTenant extension," and new security dependency. |
| Edge cases | 15% | 78 | Covers several important edge cases: super-admin bypass/auditing ("app.bypass_rls = 'on'"), raw SQL bypass risk, worker tenant context, and reversibility across phases. However, it does not explicitly address connection pool exhaustion and only indirectly addresses cross-tenant query pitfalls. |
| Dependency ordering | 15% | 95 | Excellent phased sequencing with clear order and reversibility: "V5–V6 schema," "V7 backfill," "code dual-write," "V8 NOT NULL + FK," "V9 enable RLS," then cleanup. This matches schema-first to rollout/verification progression. |
| Acceptance criteria | 20% | 70 | Some measurable intent is present ("single-tenant p95 within 5%"), and requirement mapping is explicit (isolation + super-admin), but concrete testable acceptance criteria are not clearly enumerated in the visible output (e.g., explicit pass/fail checks like Fleet A cannot read Fleet B for named endpoints/queries). |

## Overall Score: 75.95/100
