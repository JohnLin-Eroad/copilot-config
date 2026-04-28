# Trace: planning — 2026-W18

## Metadata
- Prompt ID: P2-multi-tenancy
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-04-28T00:00:53Z
- Duration: 820.5s

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
I'll explore the codebase systematically, starting with the structure and then drilling into each area. Let me make efficient use of targeted searches.Now let me check for key domain entities and look at auth, database, and controller structures:Let me continue checking the database schema and look for auth configuration and controllers:Let me look at the API structure more systematically and check for security config and controllers:Now let me examine key files - look at a repository, a controller, and check for Spring Security config:Let me check web app config and look for pom.xml to see dependencies:Let me check the application.yml and look for any User/Auth entities in the domain:Let me check for a base entity class and look at the frontend:Let me look at a domain entity and check the web frontend app structure:Let me see the rest of the database schema migrations and check for any context/scope beans:Let me check one more controller to see how context is handled and check the JPA configuration:Let me check the web module's pom and see if there's any Spring Security or auth config:Perfect! I now have enough information to provide a comprehensive report. Let me compile the findings:

---

## **Multi-Tenancy Readiness Report: Sovereign Codebase**

### **1. DOMAIN MODEL** 
**Current state:** No multi-tenancy concepts exist.
- **Key entities found (api/domain/src/main/java/com/sovereign/domain/entities/):**
  - `TransformationExecutionRun` – Execution workflow runs (execution/TransformationExecutionRun.java)
  - `WorkflowItem` – Individual workflow steps (execution/WorkflowItem.java)
  - `StudioConversation` – AI conversation sessions (studio/StudioConversation.java:14)
  - `StudioMessage` – Chat messages (studio/StudioMessage.java)
  - `LlmUsageRecord` – LLM token tracking (execution/LlmUsageRecord.java)
  - `AgentAuditLog` – Audit trail (audit/AgentAuditLog.java)
  - `GovernanceRule` – Policy rules (governance/GovernanceRule.java)
  - `EroadRepo`, `EroadDomain`, `EroadSquad`, `EroadTribe` – Catalog entities (catalog/*)
- **Missing:** No `Organisation`, `Tenant`, `Fleet`, or `Account` aggregate roots

---

### **2. DATABASE**
**PostgreSQL 16** (docker-compose.yml:3)
- **Schema tables:** 12 core tables in V1__initial_schema.sql (188 lines)
  - execution_runs, workflow_items, llm_usage_records, improvement_workflow_entries, execution_decisions, engine_health_snapshots, operation_records, studio_conversations, studio_messages, fact_studio_usage, agent_audit_log, cost_attributions
- **Multi-tenancy columns:** NONE found
  - ❌ No `organisation_id`, `tenant_id`, `org_id`, or `account_id` columns
  - User reference exists only as `created_by_user_id` VARCHAR(255) in studio_conversations (V1:line 114)
- **Migrations:** Flyway (4 files: V1–V4) – api/infrastructure/src/main/resources/db/migration/ (lines 17–19 in application.yml)

---

### **3. AUTHENTICATION & AUTHORIZATION**
**Current state:** No auth framework implemented.
- **Spring Security:** ❌ NOT included in web/pom.xml (checked lines 14–43)
- **JWT/OAuth:** ❌ NOT found
- **User/Principal model:** 
  - Minimal user tracking: `created_by_user_id` VARCHAR(255) in studio_conversations (V1:line 114)
  - No `User`, `Principal`, or `UserDetails` entity
- **SecurityContext:** ❌ No filters, interceptors, or SecurityContext setup found
- **Controllers access users:** ❌ Controllers receive no user context (e.g., AgentExecutionController.java:17–24 shows no Principal injection)

---

### **4. PERSISTENCE LAYER**
**Simple, unfiltered JPA repositories:**
- **Repository pattern:** Standard Spring Data JpaRepository (20 files in api/infrastructure/repository/)
  - Example: `LlmUsageRecordRepository.java:10` – `extends JpaRepository<LlmUsageRecord, Long>`
  - No custom query methods beyond simple finders
- **Hibernate configuration:** 
  - DDL auto: `validate` (application.yml:11)
  - Dialect: PostgreSQL
- **Multi-tenancy interceptors:** ❌ NONE
  - ❌ No `@Where` clauses
  - ❌ No Hibernate filters registered
  - ❌ No base entity class with tenant_id
- **Entity structure:** Entities use standard Lombok (@Data, @Builder) – StudioConversation.java:8–10 shows no base tenant field

---

### **5. REST LAYER**
**No user/tenant context extraction:**
- **Controller pattern:** Simple @RestController with no user/principal handling
  - Example: StudioController.java:28–42 – `listConversations()` takes no principal/context parameter
  - AgentExecutionController.java:17–24 – `execute()` takes only roleKey and request body
- **Request-scoped context:** ❌ NONE found
  - ❌ No @RequestScope beans
  - ❌ No ThreadLocal context holders
  - ❌ No filter/interceptor establishing context
- **No dependency injection of:** Principal, SecurityContext, UserDetails, or custom TenantContext

---

### **6. FRONTEND (~/sovereign/web)**
**No multi-org/tenant UI:**
- **Framework:** Next.js (next.config.ts, layout.tsx)
- **Route structure:** Single-org only (pages: studio/, repos/, domains/, tribes/, platform/, transformation/, discovery/)
  - No `/orgs/`, `/tenants/`, `/account/settings/` routes
- **Multi-tenancy code:** ❌ NONE
  - ❌ No org/tenant references found in .tsx/.ts files
  - ❌ No workspace switcher, org context, or auth state management
  - ❌ No user profile or account management UI

---

## **SUMMARY**

| Component | Status | Details |
|-----------|--------|---------|
| Domain Model | ❌ Not Started | No Tenant/Org/Account entities |
| Database Schema | ❌ Not Started | No tenant_id columns; single-tenant design |
| Auth/Authz | ❌ Not Started | No Spring Security; user_id only as string |
| Persistence | ❌ Not Started | Plain JPA, no Hibernate filters/interceptors |
| REST API | ❌ Not Started | No principal extraction or context beans |
| Frontend | ❌ Not Started | No org switching, single-app design |

**Conclusion:** Codebase is **single-tenant, no existing multi-tenancy infrastructure**. Complete redesign needed across all 6 layers.● Explore Explore current tenancy state
  │ List infrastructure directories (shell)
  │   │ ls -la /Users/johnlin/sovereign/api/infrastructure/src/main/java/com/soverei
  │   │ gn/infrastructure/ | head -20
  │   └ 10 lines...
  └ List infrastructure Java files (shell)
      │ find /Users/johnlin/sovereign/api/infrastructure -name "*.java" | wc -l &&
      │ find /Users/johnlin/sovereign/api/infrastructure/src/main/java -name
      │ "*.java" | head -20
      └ 22 lines...

● Request failed due to a transient API error. Retrying...

The directory exists. Here are the files:

- ADR-0001-multi-tenancy-fleet-isolation.md
- ADR-0001-multi-tenancy.md
- ADR-0002-multi-tenancy-implementation-plan.md

**Highest ADR number: 2**

The next ADR should be numbered **ADR-0003**.● Explore Check existing ADRs
  └ List files in docs/adr directory (shell)
      │ ls -1 /Users/johnlin/sovereign/docs/adr/ 2>&1
      └ 4 lines...

● General-purpose(claude-haiku-4.5) Write ADR-0003 file
  └ Create ADR-0003-multi-tenancy-rls.md +251
      └ docs/adr/ADR-0003-multi-tenancy-rls.md

ADR-0003 written to `~/sovereign/docs/adr/ADR-0003-multi-tenancy-rls.md`. Summary below.

## Decision: Shared schema + Postgres Row-Level Security (RLS)

**Why this over the alternatives**
- DB-per-tenant / schema-per-tenant → ops & migration cost too high for fleet SaaS scale.
- App-only Hibernate `@Filter` → not "DB-level isolation" as required; one bug leaks data.
- **Shared schema + `tenant_id` discriminator + RLS** → true DB enforcement, single migration stream, ~1–3% perf overhead, super-admin via `BYPASSRLS` role.

**Mechanism (hexagonal-clean)**
- `Organisation` aggregate + `OrganisationId` VO in **domain** (no Spring/JPA).
- `CurrentTenantPort` in **application**; `TenantAwareDataSource` adapter in **infrastructure** issues `SET LOCAL app.tenant_id` per transaction.
- `TenantResolutionFilter` in **web** reads JWT claims (`org_id`, `roles`); super-admin uses audited `X-Impersonate-Org`.
- Two Postgres roles: `app_tenant` (RLS forced) for the API pool, `app_admin` (`BYPASSRLS`) for Flyway.
- RLS policy uses `current_setting('app.tenant_id', true)` — unset = zero rows (fail-closed, not fail-open).

**Migration path** — 5 Flyway steps, reversible up to V9:
1. **V5** create `organisations`, insert legacy org `00000000-…-0001`.
2. **V6** add nullable `organisation_id` on all 12 tables.
3. **V7** chunked backfill to legacy org.
4. **V8** `NOT NULL` + FK + composite indexes `(organisation_id, hot_col)`.
5. **App Release A** — ship filter + datasource wrapper, all traffic stamped to legacy org.
6. **V9 + Release B** — enable + force RLS, install policies. Behaviour unchanged for legacy users; isolation now enforced.
7. **Release C/D** — super-admin UI, org switcher, onboarding.

**Blast radius: HIGH** (12 tables altered, new filter/datasource, transaction-required everywhere). Reversible until V9; mitigated by feature-flagged policies, ArchUnit + schema-assertion CI gates, and a Testcontainers cross-tenant integration test.

**Open follow-up ADRs**: 0004 user↔org mapping, 0005 cross-tenant analytics, 0006 split tenant vs platform audit logs. Auth provider (JWT issuer) is assumed and tracked separately.

## Grading Reasoning
This is a solid and mostly complete architecture/migration plan with strong hexagonal alignment and sequencing. The main weakness is insufficiently explicit, measurable acceptance criteria and incomplete treatment of some operational edge cases.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Domain understanding | 15% | 85 | Strong tenant-boundary modeling with evidence like 'Organisation aggregate + OrganisationId VO' and migration steps adding 'organisation_id on all 12 tables'. It addresses organisation-level isolation well, but does not deeply model Fleet-specific domain semantics beyond treating organisation as tenant. |
| Hexagonal architecture | 20% | 92 | Excellent separation of concerns: 'Organisation aggregate ... in domain (no Spring/JPA)', 'CurrentTenantPort in application', 'TenantAwareDataSource adapter in infrastructure', and 'TenantResolutionFilter in web'. This keeps tenancy resolution outside core domain logic. |
| Blast radius assessment | 15% | 82 | Clearly classified as 'Blast radius: HIGH' with concrete impacts: '12 tables altered, new filter/datasource, transaction-required everywhere'. Good mitigations are listed, but it is less explicit on connection-pool behavior and downtime windows than a top score would require. |
| Edge cases | 15% | 72 | Covers multiple edge conditions: super-admin ('BYPASSRLS' + 'X-Impersonate-Org'), fail-closed behavior ('unset = zero rows'), and rollback boundary ('Reversible until V9'). It only partially addresses cross-tenant analytics (deferred to follow-up ADR) and does not explicitly cover connection pool exhaustion. |
| Dependency ordering | 15% | 90 | Very strong phased sequencing: 'V5 create organisations' → 'V6 add nullable organisation_id' → 'V7 backfill' → 'V8 NOT NULL + FK + indexes' → app releases → 'V9 ... enable + force RLS'. This is clear, dependency-aware, and operationally sensible. |
| Acceptance criteria | 20% | 58 | Some test intent appears ('Testcontainers cross-tenant integration test') and qualitative targets are implied ('~1–3% perf overhead'), but explicit measurable acceptance criteria are missing (e.g., concrete pass/fail checks like 'Fleet A cannot see Fleet B' and strict latency SLO thresholds). |

## Overall Score: 79.35/100
