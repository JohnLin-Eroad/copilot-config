# Trace: planning — 2026-W26

## Metadata
- Prompt ID: P2-multi-tenancy
- Executor agent: orchestrator
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-06-24T09:47:27+12:00
- Duration: ~280s executor + ~50s grader

## Prompt Sent
```
Design multi-tenancy support for the sovereign platform. Fleet organisations must be isolated at
the database level. Requirements: each fleet org sees only its own data; a super-admin can see all;
must work with existing PostgreSQL; minimal performance impact for single-tenant queries; migration
path from current shared-tenant model defined. Produce a detailed implementation plan with
architecture decisions, blast radius assessment, and migration strategy.
```

## Raw Output
# Multi-Tenancy Implementation Plan — Sovereign Platform

**Author:** Orchestrator (architecture brief)
**Date:** 2026-06-24
**Status:** Proposal — pending architect + security + compliance review
**Blast radius:** **HIGH** (touches every repository, every query, every fleet org, all production data)

---

## 1. Architecture Decision

### 1.1 Options evaluated

| Option | Isolation | Ops cost | Perf | Migration cost | Cross-tenant queries | Per-tenant backup/restore |
|---|---|---|---|---|---|---|
| **A. Separate databases per tenant** | Strongest (physical) | Very high — N PG instances/databases, N migrations, N connection pools | Best per-tenant; worst aggregate (connection pool blow-up) | Very high — data must be split per org | Hard — requires app-side fan-out or FDW | Trivial |
| **B. Schema-per-tenant (same DB)** | Strong (logical, namespace) | High — N schemas, Flyway must run per schema, search_path juggling | Good; one connection pool, schema switch is cheap | High — every table copied per tenant; data redistribution | Hard — needs UNION across schemas | Good (pg_dump -n) |
| **C. Row-Level Security (RLS) — shared schema, `tenant_id` column** | Logical (enforced by PG `CREATE POLICY`) | Low — single schema, single migration path | Excellent if `tenant_id` is the leading index column; one pool | Lowest — add column, backfill, attach policies | Easy — bypass policy as super-admin role | Logical (filtered dump) |
| **D. Hybrid: RLS + dedicated DB for top 1–2 anchor tenants** | Strong for VIPs, logical for the rest | Medium | Excellent | Medium | Medium | Good |

### 1.2 Chosen approach — **Option C: PostgreSQL Row-Level Security (RLS) with a `tenant_id` (BIGINT, NOT NULL) column on every tenant-owned table**

**Rationale**

1. **DB-level isolation is the requirement, not physical isolation.** RLS is enforced by PostgreSQL itself — even a SQL-injection vulnerability or a developer forgetting a `WHERE` clause cannot leak data across tenants, because the planner injects the policy predicate. This satisfies "isolated at the database level".
2. **Single PostgreSQL cluster + single connection pool** — minimal ops change vs the existing Sovereign setup. HikariCP pool sizing remains the same; we do not multiply connections by N tenants (which would happen with schema-per-tenant via Hibernate `SCHEMA` strategy, because Hibernate caches one pool per tenant identifier).
3. **Performance** — with `tenant_id` as the leading column on every composite index, a single-tenant query is functionally identical to today's query plus an equality predicate that is already implied by the index. Expected overhead: **< 5% p99 latency**, well inside the "minimal" requirement.
4. **Migration path is the cheapest of the four** — additive column + backfill + attach policy + flip a feature flag. No data redistribution across schemas/databases.
5. **Super-admin** is a first-class concept in RLS — a Postgres role with `BYPASSRLS`, or a session variable check inside the policy predicate. Both are standard patterns.
6. **NZ/AU regulatory considerations** (RUCUS, HOS data, NZTA) — RLS gives an auditable, DB-enforced control surface that maps cleanly to compliance evidence (one `pg_policies` query lists every enforcement rule).

**What we explicitly give up by not choosing B or A**

- Per-tenant `pg_dump` is slightly harder (must filter by `tenant_id`).
- We cannot give a customer their own DB credentials. That is not a stated requirement.
- A "noisy neighbour" tenant can still consume shared resources (mitigation in §6 — per-tenant statement_timeout + connection quotas via pgbouncer or `pg_stat_statements` monitoring).

---

## 2. Hexagonal Architecture — Where Tenancy Lives

**Principle:** the domain knows nothing about tenants. Tenancy is an infrastructure concern resolved at the edge (HTTP/gRPC/SQS) and propagated implicitly via thread-local context → JDBC session variable. The domain layer (entities, aggregates, services) operates as if it lived in a single-tenant world.

### 2.1 Layer-by-layer placement

```
┌────────────────────────────────────────────────────────────────────┐
│ Adapter-in (HTTP / SQS / gRPC)                                     │
│   • TenantResolutionFilter — extracts tenant from JWT / SQS attr   │
│   • Sets TenantContext (ThreadLocal / Reactor Context)              │
│   • Rejects request if tenant cannot be resolved (401/403)         │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Application (use cases) — NO tenant code                           │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Domain (entities, aggregates, ports) — NO tenant code              │
│   • Entities do NOT expose tenantId publicly                       │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Adapter-out (JPA / JDBC)                                           │
│   • TenantAwareDataSource (delegate around HikariCP)                │
│   • On every connection checkout: SET LOCAL app.tenant_id = ?       │
│   •                              SET LOCAL app.is_super_admin = ?   │
│   • RLS policies read these GUCs                                    │
│   • Hibernate MultiTenantConnectionProvider sets the GUC            │
│   • CurrentTenantIdentifierResolver reads TenantContext             │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 Key contracts

```java
// Domain — pure, no tenant
public interface VehicleRepository {
    Optional<Vehicle> findById(VehicleId id);
    List<Vehicle> findActive();
}

// Infrastructure — tenant resolution
public final class TenantContext {
    private static final ThreadLocal<TenantId> CURRENT = new ThreadLocal<>();
    private static final ThreadLocal<Boolean> SUPER_ADMIN = ThreadLocal.withInitial(() -> false);
    // get/set/clear; clear() MUST run in a finally block in every filter
}

// Adapter-in
@Component
public class TenantResolutionFilter extends OncePerRequestFilter {
    @Override protected void doFilterInternal(...) {
        try {
            TenantId t = jwtClaims.get("tenant_id");
            boolean superAdmin = jwtClaims.getRoles().contains("PLATFORM_SUPER_ADMIN");
            TenantContext.set(t, superAdmin);
            chain.doFilter(req, res);
        } finally {
            TenantContext.clear(); // CRITICAL — prevents leak across pooled threads
        }
    }
}
```

The domain never imports `TenantContext`. Any PR that does is rejected at code review.

---

## 3. Hibernate / JPA Multi-Tenancy Configuration

We are NOT using Hibernate's `SCHEMA` or `DATABASE` multi-tenancy strategies (they assume schema-per-tenant or DB-per-tenant). We use the **`DISCRIMINATOR` strategy** introduced in Hibernate 6.0, combined with PostgreSQL RLS — this is the cleanest fit for option C.

### 3.1 Configuration

```yaml
spring:
  jpa:
    properties:
      hibernate:
        multiTenancy: DISCRIMINATOR
        tenant_identifier_resolver: com.eroad.sovereign.infra.tenancy.SovereignTenantResolver
        multi_tenant_connection_provider: com.eroad.sovereign.infra.tenancy.SovereignTenantConnectionProvider
```

### 3.2 The two SPI implementations

```java
public class SovereignTenantResolver implements CurrentTenantIdentifierResolver<String> {
    @Override public String resolveCurrentTenantIdentifier() {
        TenantId t = TenantContext.current();
        return t == null ? "__none__" : t.value().toString();
    }
    @Override public boolean validateExistingCurrentSessions() { return true; }
}

public class SovereignTenantConnectionProvider
        implements MultiTenantConnectionProvider<String> {

    private final DataSource ds; // shared HikariCP

    @Override
    public Connection getConnection(String tenantId) throws SQLException {
        Connection c = ds.getConnection();
        try (Statement s = c.createStatement()) {
            if (TenantContext.isSuperAdmin()) {
                s.execute("SET LOCAL app.is_super_admin = 'true'");
                s.execute("SET LOCAL app.tenant_id = '0'");
            } else {
                s.execute("SET LOCAL app.is_super_admin = 'false'");
                s.execute(String.format("SET LOCAL app.tenant_id = '%s'",
                        Long.parseLong(tenantId))); // parseLong = injection-safe
            }
        }
        return c;
    }

    @Override
    public void releaseConnection(String tenantId, Connection c) throws SQLException {
        // SET LOCAL is auto-cleared at transaction end; nothing to do.
        c.close();
    }

    @Override public Connection getAnyConnection() { return ds.getConnection(); }
    @Override public boolean supportsAggressiveRelease() { return false; }
}
```

**Why `SET LOCAL`** (not `SET SESSION`): `SET LOCAL` lives for the transaction only. When HikariCP returns the connection to the pool, the next checkout starts with a clean GUC state. This is essential — it prevents the most dangerous failure mode (tenant A's GUC leaking into tenant B's request).

**Defence in depth**: also call `RESET app.tenant_id; RESET app.is_super_admin;` in `releaseConnection` for non-transactional paths (e.g. read-only queries on autocommit).

### 3.3 `@Filter` is NOT used

We deliberately do not use Hibernate `@Filter`/`@FilterDef`. Filters are easy to forget on a new entity and provide no defence against native queries, JDBC template, or jOOQ. RLS catches all of them.

### 3.4 Entities

Entities do **not** declare `@TenantId` publicly. The column exists in the table; JPA mapping puts it on a `@MappedSuperclass`:

```java
@MappedSuperclass
public abstract class TenantOwnedEntity {
    @Column(name = "tenant_id", nullable = false, updatable = false)
    @TenantId  // Hibernate 6 — auto-populated from CurrentTenantIdentifierResolver on INSERT
    private Long tenantId;
}
```

Insert path: Hibernate writes the resolved tenant_id. Read path: RLS filters. Update/delete path: RLS filters. Cross-cutting and safe.

---

## 4. PostgreSQL Schema, Policies, and Roles

### 4.1 Per-table additions

For every tenant-owned table (vehicle, driver, journey, hours_of_service_event, …):

```sql
ALTER TABLE vehicle ADD COLUMN tenant_id BIGINT;          -- step 1: nullable
-- backfill (step 2, see §6)
ALTER TABLE vehicle ALTER COLUMN tenant_id SET NOT NULL;  -- step 3
ALTER TABLE vehicle ADD CONSTRAINT fk_vehicle_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenant(id);

-- Replace every (col, ...) index with (tenant_id, col, ...) to keep single-tenant
-- queries on the same fast path. Drop old indexes AFTER the new ones are live.
CREATE INDEX CONCURRENTLY idx_vehicle_tenant_vin ON vehicle (tenant_id, vin);
DROP INDEX CONCURRENTLY idx_vehicle_vin;

ALTER TABLE vehicle ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicle FORCE ROW LEVEL SECURITY;  -- applies to table owner too

CREATE POLICY tenant_isolation ON vehicle
USING (
    current_setting('app.is_super_admin', true) = 'true'
    OR tenant_id = current_setting('app.tenant_id', true)::bigint
)
WITH CHECK (
    tenant_id = current_setting('app.tenant_id', true)::bigint
    OR current_setting('app.is_super_admin', true) = 'true'
);
```

`USING` clause filters SELECT/UPDATE/DELETE visibility. `WITH CHECK` prevents a tenant from inserting/updating a row to belong to a different tenant — closes a known RLS footgun.

### 4.2 Roles

- `sovereign_app` — used by every service. Does NOT have BYPASSRLS. RLS applies.
- `sovereign_migrator` — used by Flyway only. Has BYPASSRLS (so migrations can backfill across all tenants).
- `sovereign_super_admin_app` — used by the super-admin admin console service. Same as `sovereign_app` but `app.is_super_admin` is set to `true` via the connection provider. Does NOT have Postgres-level BYPASSRLS, so we still have an audit trail (every query is policy-evaluated).

Rationale for not granting BYPASSRLS to the super-admin app: revoking a single role's BYPASSRLS in an incident is irreversible without a deploy; flipping a GUC is reversible and per-request.

### 4.3 Non-tenant-owned tables

Reference tables (country, vehicle_make, ruc_rate_card) — no `tenant_id`, no RLS, no change.
Audit/event tables — `tenant_id` added, RLS enabled with the same policy.

---

## 5. Blast Radius Assessment

| Surface | Impact | Mitigation |
|---|---|---|
| **Every tenant-owned table** (~120 in sovereign, audit shows ~140 incl. event tables) | Schema change (add column, FK, indexes, enable RLS). Concurrent index rebuilds required. | Phased per-domain rollout (vehicle → driver → journey → HOS → …). `CREATE INDEX CONCURRENTLY` avoids locks. |
| **Every repository** (~JPA repos in sovereign + 5 jOOQ adapters) | No code change required for repositories — RLS is transparent. But `findAll()` semantics changed (now scoped). | Static analysis: grep for `nativeQuery = true` and review all native queries for `tenant_id` filters that became redundant; document removal. |
| **Every native query / jOOQ query / JdbcTemplate call** | RLS still applies, but `EXPLAIN` plans change. Some queries may regress if indexes weren't updated. | §6 Phase 1.5: capture top 50 query plans before/after on staging; require <5% p99 regression to promote. |
| **Connection pooling (HikariCP)** | None — single pool, single role. Per-connection `SET LOCAL` is O(µs). | Add a Micrometer metric for "connection checkout → first query" latency to detect regression. |
| **Cross-service messaging (SQS)** | Every message MUST carry `tenant_id` as a message attribute, set by the producer's `TenantContext`. Consumers set `TenantContext` before invoking the use case. | Update `common-messages` library: `TenantAwareMessageProducer` / `TenantAwareSqsListener` (already used pattern in other EROAD services). Audit: every `@SqsListener`. |
| **Async / scheduled jobs** | No HTTP request → no automatic `TenantContext`. | Two patterns: (a) "iterate all tenants" jobs run as super-admin and explicitly set `TenantContext` per tenant; (b) tenant-specific jobs read tenant from job payload. Both must `clear()` in `finally`. |
| **Reactive code paths** (WebFlux services: media-service, replay-service) | `ThreadLocal` does not propagate across reactor threads. | Use `Context.put("tenantId", …)` + a `TenantContextHolder` that reads from Reactor Context. Provided by infra module. |
| **Migration downtime** | Adding `NOT NULL` + FK + RLS to a 500M-row table (e.g. `journey_event`) without downtime requires the 3-step expand/contract pattern. | §6 covers this. Expected user-visible downtime: **zero**. Backfill window per large table: ~hours, online. |
| **Flyway migrations** | Migrations must run as `sovereign_migrator` (BYPASSRLS) — otherwise the migrator can't see existing rows to backfill. | Spring Boot profile `flyway.user = sovereign_migrator`; runtime uses `sovereign_app`. |
| **Connection pool exhaustion** | A super-admin "scan all tenants" query, or a missing `tenant_id` index, can monopolise connections. | `statement_timeout = 30s` at DB role level; pgbouncer per-database connection cap; alert on `pg_stat_activity` > 80%. |
| **Reporting / BI / Snowflake replication** | `dataanalyticsplatform-datasharing-360regionalreplication` replicates raw tables — `tenant_id` flows automatically. Snowflake-side ACLs must mirror tenant boundaries. | Out of scope of this plan; raise dependency ticket on the data team. |
| **Dev / staging environments** | Lower environments need representative tenant fixtures. | Update `local-development` compose to seed 3 tenants + 1 super-admin token. |

---

## 6. Phased Implementation — Strict Dependency Order

> Each phase has a Go/No-Go gate. No phase starts before the previous gate is signed off by architect + security + the domain owner.

### Phase 0 — Foundation (1 sprint)
- Create `tenant` table (id, name, status, created_at).
- Create `sovereign_app`, `sovereign_migrator`, `sovereign_super_admin_app` roles in PG (dev/staging/prod).
- Add `tenancy-core` library (TenantId, TenantContext, TenantResolutionFilter, SqsTenantPropagator, ReactorTenantContext).
- Feature flag: `tenancy.rls.enforced` (default `false` everywhere).
- **Gate:** library reviewed; RLS off in prod; tests in CI for context propagation including reactor + SQS round-trip.

### Phase 1 — Schema expand (one domain at a time, in this order)
Order chosen by blast radius (smallest first to de-risk the pattern):
1. `organisation-settings-service` (smallest tables, low traffic)
2. `vehicle-service`
3. `driver-login-service` + `driver`
4. `journey` + `historical-event-api`
5. `hours-of-service` + `eroad-hos-rulekit` (regulated — extra compliance review)
6. `myeroad-*` services
7. `billing-service`, `tax` services (financial — extra compliance review)

For each domain:
- 1a. Flyway: `ALTER TABLE … ADD COLUMN tenant_id BIGINT NULL` (additive, zero risk).
- 1b. Backfill job (idempotent, chunked 10k rows, `LIMIT … FOR UPDATE SKIP LOCKED`).
- 1c. Verify `SELECT COUNT(*) WHERE tenant_id IS NULL = 0`.
- 1d. Flyway: `SET NOT NULL`, add FK, create `(tenant_id, …)` indexes CONCURRENTLY, drop old indexes CONCURRENTLY.
- **Gate per domain:** zero NULL tenant_ids; new indexes used by EXPLAIN on top 10 queries; p99 latency regression <5%.

### Phase 2 — Application wiring (per domain, after that domain's Phase 1)
- Wire `TenantResolutionFilter` into adapter-in.
- Configure Hibernate `MultiTenancy = DISCRIMINATOR` + the two SPI beans.
- Hibernate sets tenant_id on INSERTs from `TenantContext` (RLS still off).
- Run shadow tests in staging: every existing integration test passes unchanged. Add new tests that verify tenant_id is populated on writes.
- **Gate:** 100% of writes carry correct tenant_id; 0 integration test regressions.

### Phase 3 — Enable RLS (per domain)
- Flyway: `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY` on each table in the domain.
- Flip `tenancy.rls.enforced = true` for that domain via feature flag.
- Canary: 1% traffic for 24h, monitor `pg_stat_statements` for plan regressions, error rate, p99 latency.
- Roll forward 10% → 50% → 100% over 3 days.
- **Gate:** zero RLS-related 500s; zero cross-tenant data observed in audit logs; latency within budget.

### Phase 4 — Super-admin path
- Stand up `sovereign_super_admin_app` role usage on the admin console service only.
- Super-admin JWT scope `PLATFORM_SUPER_ADMIN` flips `app.is_super_admin` GUC.
- Add audit log: every super-admin query writes `(user_id, tenant_scope='ALL', table, row_count)` to `super_admin_audit`.
- **Gate:** security review of audit completeness; penetration test on super-admin endpoint (attempt JWT forgery, attempt to set GUC from app code path).

### Phase 5 — Verification (production)
- Synthetic tenants T_canary_A and T_canary_B with known datasets.
- Automated daily job: log in as T_canary_A, attempt to read every endpoint, assert no T_canary_B rows ever appear. Alert on any leak.
- Compliance sign-off (RUCUS, NZTA data residency unchanged — still in-region).

### Phase 6 — Decommission shared-tenant assumptions
- Remove dead code paths that assumed single-tenant.
- Delete the `tenancy.rls.enforced` feature flag.
- Document in `engineering-docs/`.

---

## 7. Edge Cases (≥4, with concrete handling)

1. **Cross-tenant queries (admin reports across all fleets)**
   Must go through the super-admin app + `app.is_super_admin = true`. Domain code requesting cross-tenant data calls an explicit `CrossTenantAdminPort` (separate from regular repositories), which is only implemented in the super-admin service. Regular services do not depend on this port and physically cannot perform the query.

2. **Super-admin acting "as" a tenant for support**
   "Impersonation" sets `app.tenant_id = <target>` AND `app.is_super_admin = false`. This forces the support user through the same RLS path as the customer (so they cannot accidentally see cross-tenant data while debugging) and the audit log records both the support user identity and the impersonated tenant. `myeroad-impersonation-service` already exists — extend, do not reinvent.

3. **Migration rollback (mid-Phase-3)**
   Each Phase 3 migration is paired with a `down` script:
   `ALTER TABLE … DISABLE ROW LEVEL SECURITY; DROP POLICY tenant_isolation ON …;`
   The `tenant_id` column itself stays (additive, harmless). Feature flag flip-back is the first-line rollback (seconds); SQL rollback is the second-line (minutes).
   Rollback test runs in staging weekly against a prod-sized dataset.

4. **Connection pool exhaustion from a tenant-less request**
   If `TenantContext` is unset and the request reaches the connection provider, throw `MissingTenantException` (HTTP 500 with a typed error code). Do NOT default to `tenant_id = 0` or super-admin — fail closed. Alert fires on rate > 0.
   Set `statement_timeout = 30s` on `sovereign_app`, `60s` on `sovereign_super_admin_app`. pgbouncer per-database `pool_size` caps a runaway super-admin job to ≤25% of total connections.

5. **`ThreadLocal` leak across pooled threads (Tomcat / Reactor)**
   Mitigations: (a) `TenantResolutionFilter` clears in a `finally`; (b) startup self-test asserts `TenantContext.current() == null` at the beginning of every filter; (c) integration test sends back-to-back requests as tenant A then tenant B sharing a Tomcat thread and asserts B sees only B data; (d) for WebFlux services we use Reactor Context, not ThreadLocal.

6. **Schema migrations on huge tables (e.g. `journey_event`, ~500M rows)**
   Backfill is chunked (10k rows, `SKIP LOCKED`) and runs at ≤500 writes/sec to stay within replication budget. `SET NOT NULL` uses the PG14+ "validate constraint" two-step (`ADD CONSTRAINT … NOT VALID; VALIDATE CONSTRAINT …`) to avoid a full-table AccessExclusiveLock.

7. **A new developer writes a native SQL query and forgets `tenant_id`**
   Doesn't matter — RLS still filters. This is the whole point of choosing C over `@Filter`. However, we add an ArchUnit test that flags any `@Query(nativeQuery=true)` with the literal `WHERE tenant_id` (because it indicates the dev didn't trust RLS — educate or remove).

8. **SQS / Kafka message replay weeks later**
   Message attribute `tenant_id` must be set by the consumer's `TenantContext` before invoking the use case. If absent, send to DLQ — do not process under super-admin (would write rows with wrong tenant).

9. **Tenant deletion / GDPR right-to-erasure**
   Out of scope for this plan, but the `tenant_id` column + FK makes per-tenant deletion straightforward (`DELETE FROM … WHERE tenant_id = ?` with super-admin role). Raise a follow-up.

---

## 8. Acceptance Criteria (measurable, binary pass/fail)

| # | Criterion | How measured |
|---|---|---|
| AC1 | Fleet A cannot read Fleet B data via any HTTP endpoint | Automated test: 100 endpoints × 2 tenants × cross-fetch; 0 leaks |
| AC2 | Fleet A cannot read Fleet B data via SQL injection | Pen-test: 20 known injection payloads on top 10 endpoints; 0 leaks |
| AC3 | Fleet A cannot write a row owned by Fleet B | Hibernate test: setting tenant_id manually on entity is rejected by `WITH CHECK` policy → SQLException |
| AC4 | Super-admin can see all tenants | Integration test: super-admin token returns rows from all 3 seed tenants |
| AC5 | Super-admin actions are audited | `super_admin_audit` has 1 row per super-admin SELECT/UPDATE/DELETE |
| AC6 | Single-tenant read p99 latency regression ≤ 5% | k6 perf test, baseline vs post-RLS on top 20 endpoints |
| AC7 | Single-tenant read p99 latency absolute < 10ms for indexed lookups | k6, vehicle-by-id endpoint |
| AC8 | Zero rows with NULL tenant_id at end of Phase 1 per domain | `SELECT COUNT(*) … WHERE tenant_id IS NULL` = 0 |
| AC9 | All cross-service messages carry `tenant_id` attribute | Static analysis on `common-messages` producers; runtime metric `sqs.messages.without_tenant` = 0 |
| AC10 | No `TenantContext` leak across pooled threads | Soak test: 1M requests alternating tenants on a 50-thread pool; assertion holds |
| AC11 | Rollback path validated | Staging drill: enable RLS, then disable + drop policies, then run smoke suite — green |
| AC12 | Connection pool steady-state utilisation < 70% under prod load | Hikari `active_connections` metric, 7-day window |
| AC13 | Every tenant-owned table has RLS enabled + policy attached | `SELECT … FROM pg_class JOIN pg_policies` returns one policy per tenant-owned table |
| AC14 | No regression in existing test suites | All sovereign module CI suites green |

---

## 9. Rollback Plan

**Three layered rollback levels — fastest first:**

### Level 1 — Feature flag (seconds, no deploy)
- Flip `tenancy.rls.enforced = false` in the feature-flag service for the affected domain.
- Effect: app stops setting `app.tenant_id` GUC and the connection provider returns a vanilla connection. RLS policies still exist but the GUC is not set — for safety the policies are written `current_setting('app.tenant_id', true) IS NULL OR tenant_id = current_setting(...)::bigint` only if we explicitly want a "permissive" fallback. **We choose fail-closed by default**, so Level 1 actually escalates to Level 2 if RLS is enabled at DB level.
- Use case: app-level misbehaviour (filter bug, context leak) — flip flag, app reverts to legacy code path which doesn't depend on GUC.

### Level 2 — Disable RLS on affected tables (minutes, SQL only)
```sql
ALTER TABLE vehicle NO FORCE ROW LEVEL SECURITY;
ALTER TABLE vehicle DISABLE ROW LEVEL SECURITY;
```
- Reversible; data unchanged; column and indexes remain.
- Use case: a policy bug breaks legitimate queries in production.

### Level 3 — Full schema revert (hours, Flyway down migration)
- Drop policies, drop `tenant_id` FK, drop column. Recreate old indexes.
- Use case: catastrophic, unrecoverable plan regression or data corruption. Last resort.

**Rollback decision tree owned by on-call:**
```
Symptom: cross-tenant data leak             → Level 1 (kill switch) immediately
Symptom: app error rate spike on RLS errors → Level 1
Symptom: query latency P99 > 2× baseline    → Level 2 on affected tables
Symptom: DB CPU pinned, lock contention     → Level 2 on affected tables
Symptom: data integrity issue with tenant_id → Level 3 (with DBA + architect + security)
```

**Pre-rollback evidence to preserve** (so we can fix forward):
- `pg_stat_statements` dump of last 1h.
- `pg_locks` snapshot.
- App logs filtered by `tenancy.*` MDC keys.
- Tenant IDs of any affected requests.

---

## 10. Out of Scope / Follow-ups

- Per-tenant encryption keys (BYOK) — separate ADR.
- Tenant deletion / GDPR erasure runbook — separate ticket.
- Snowflake / BI tenant ACLs — owned by data platform team; raise dependency.
- Per-tenant rate limiting at API gateway — owned by platform team; raise dependency.
- Migration of legacy `360-*` repositories — those are pre-Sovereign; separate programme.

---

## 11. Summary

PostgreSQL Row-Level Security with a `tenant_id` column on every tenant-owned table, Hibernate 6 `DISCRIMINATOR` multi-tenancy, tenant resolved at the adapter-in layer and propagated via thread-local / Reactor context, super-admin modelled as a GUC (`app.is_super_admin`) rather than a Postgres BYPASSRLS privilege. Phased domain-by-domain rollout with expand/contract migrations, feature-flag-gated RLS enablement, three-level rollback. The domain layer remains tenancy-unaware; infrastructure carries the entire concern; PostgreSQL is the final enforcement point.
## Grading Reasoning
Excellent across all dimensions. Domain understanding: models fleet/org tenancy boundary, distinguishes tenant vs reference tables (minor: limited explicit Organisation-vs-Fleet aggregate distinction). Hexagonal: "DOMAIN knows nothing about tenants", tenancy resolved in adapter-in/out with an explicit guardrail against domain leakage (slight deduction for `@MappedSuperclass`/`@TenantId` potentially blurring boundary). Blast radius: table counts (~120–140), repository/native/jOOQ impacts, HikariCP, async/SQS/WebFlux, migration downtime, BI dependency. Edge cases: 9 concrete cases. Dependency ordering: clear phased sequence with Go/No-Go gates. Acceptance criteria: 14 measurable/binary criteria including p99 latency targets.

## Scores
| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Domain understanding | 15% | 98 | Models fleet/org tenant boundary; minor Organisation-vs-Fleet nuance. |
| Hexagonal architecture | 20% | 96 | Domain unaware of tenancy; tenancy in adapter layers. |
| Blast radius assessment | 15% | 100 | Specific: every repo/query, pooling, migration downtime. |
| Edge cases | 15% | 100 | 9 cases incl. cross-tenant, super-admin, rollback, pool exhaustion. |
| Dependency ordering | 15% | 100 | Phased schema → repo → API → migration → verification with gates. |
| Acceptance criteria | 20% | 100 | 14 measurable criteria incl. "Fleet A cannot see Fleet B", p99 < 10ms. |

Calculation: 98×0.15 + 96×0.20 + 100×0.15 + 100×0.15 + 100×0.15 + 100×0.20 = 14.7 + 19.2 + 15 + 15 + 15 + 20 = 98.9

## Overall Score: 98.9/100
