# Trace: pipeline-compliance — 2026-W25

## Metadata
- Prompt ID: P2-architecture-task
- Executor model: claude-opus-4.7
- Grader model: gpt-5.3-codex
- Timestamp: 2026-06-14T21:57:27Z
- Duration: 659.5s
- Estimated cost (USD): 0.6245
- Executor tokens (est.): prompt=46 / completion=7927 / total=7973
- Grader tokens (est.):   prompt=4324 / completion=514 / total=4838
- Tool calls (heuristic): 0

## Prompt Sent
We need to add multi-tenancy support to the sovereign platform. Fleet organisations must be
isolated at the database level. What is the recommended approach and what is the blast radius?

## Raw Output
**STM Path:**
```
/Users/johnlin/.copilot/stm/2026-06-15-we-need-to-add-multi-tenancy-support-to-/short-term-memory.md
```

**STM File Contents:**

The STM file exists and contains:

- **Task:** "we-need-to-add-multi-tenancy-support-to-"
- **Created:** 2026-06-14T21:46:35Z
- **Task Brief:** Add multi-tenancy support to the sovereign platform with database-level isolation for fleet organisations. Requesting recommended approach and blast radius assessment.
- **Classification:**
  - Domain: eroad
  - Type: question
  - Blast: LOW
  - Pipeline: minimal
  - BRAIN_TYPE: eroad

The file has placeholder sections for:
- Fetch Manifest (empty)
- Brain Data (empty)
- Negative Context (empty)
- Retrieval Log (empty)
- Agent Contributions (empty)

This is a freshly initialized STM for a multi-tenancy support task on the sovereign platform.● Task(claude-haiku-4.5) Read STM path and contents
  └ Read STM path and contents (shell)
      │ cat /Users/johnlin/.copilot/session-state/abd98e59-2a3a-4aed-b298-315cc8d02c
      │ f9/stm-path.txt 2>/dev/null && echo "---STM CONTENTS---" && cat $(cat
      │ /Users/johnlin/.copilot/session-state/abd98e59-2a3a-4aed-b298-315cc8d02cf9/s
      │ tm-path.txt) 2>/dev/null
      └ 46 lines...

The heuristic mis-classified this. Multi-tenancy with DB-level isolation is architecture work with HIGH/CRITICAL blast radius (schema change, every service affected, security boundary). Reclassifying and starting the proper pipeline.

I'll fetch relevant data from the SQL brain graph for multi-tenancy architecture decisions. Let me start by reading the STM, then search systematically.Good, the STM is initialized. BRAIN_TYPE is `eroad`, so I'll use the eroad-brain vault. Now I'll systematically search for multi-tenancy, architecture, and tenant-related concepts using the brain-graph-query.py tool. Let me run multiple searches in parallel to maximize efficiency.**Result:**
```
[write-stm] ✅ Written to STM: orchestrator @ 2026-06-14T21:47:12Z
```

The script successfully wrote the multi-tenancy architecture classification to the short-term memory file. The entry has been recorded with timestamp `2026-06-14T21:47:12Z` under the `orchestrator` agent context, classifying this as a HIGH blast radius architectural change with the full rationale about DB-level fleet isolation and its foundational impact across the system.● Task(claude-haiku-4.5) Reclassify STM
  └ Run write-stm.sh script with multi-tenancy architecture classification (shell)
      │ bash ~/.copilot/scripts/write-stm.sh "/Users/johnlin/.copilot/stm/2026-06-
      │ 15-we-need-to-add-multi-tenancy-support-to-/short-term-memory.md"
      │ orchestrator "RECLASSIFY: Domain=eroad Type=architecture Blast=HIGH
      │ Pipeline=full-transformation BRAIN_TYPE=eroad. Rationale: Multi-tenancy
      │ with DB-level fleet isolation is a foundational architecture change …
      └ 6 lines...

## Search Results Summary

All 5 searches returned **0 results** with low confidence matches. The brain-graph database at ~/.copilot/brain-graph.db appears to be empty or not properly indexed for the eroad vault.

**Search Results Breakdown:**

1. **"multi-tenancy OR multi-tenant OR multitenancy"** 
   - Results: 0
   - FTS hits: 0, LIKE hits: 0

2. **"tenant isolation database schema"**
   - Results: 0
   - FTS hits: 0, LIKE hits: 0

3. **"row-level security RLS PostgreSQL"**
   - Results: 0
   - FTS hits: 0, LIKE hits: 0

4. **"fleet organisation customer"**
   - Results: 0
   - FTS hits: 0, LIKE hits: 0

5. **"database per tenant schema per tenant"**
   - Results: 0
   - FTS hits: 0, LIKE hits: 0

**Status:** The database queries completed successfully but found no indexed content matching any of the multi-tenancy architecture search patterns. The vault may require reindexing or the architecture documentation may not be stored in the brain-graph database.The initial searches returned no results. Let me try broader searches on core Sovereign architecture and tenant concepts that should be foundational:## Search Results Summary

**All 5 searches returned NO results:**

| Search Query | Result Count | Status | Notes |
|---|---|---|---|
| "Sovereign platform architecture hexagonal" | 0 | **NO RESULTS** | FTS: 0, Graph: 0 |
| "fleet organisation tenant" | 0 | **NO RESULTS** | FTS: 0, Graph: 0 |
| "customer data isolation" | 0 | **NO RESULTS** | FTS: 0, Graph: 0 |
| "PostgreSQL schema migration Flyway" | 0 | **NO RESULTS** | FTS: 0, Graph: 0 |
| "EROAD organisation fleet" | 0 | **NO RESULTS** | FTS: 0, Graph: 0 |

### Negative Context for Brain-Graph
All searches came back with:
- `low_confidence: true`
- `fts_hits: 0` (no full-text search matches)
- `like_hits: 0` (no pattern matches)
- `graph_expanded: 0` (no graph expansion results)

**Interpretation:** The brain-graph database for the `eroad` vault appears to be either:
1. Empty or not populated with these foundational concepts
2. Contains documentation using different terminology/phrasing
3. Not properly indexed for these multi-word compound queries

**Recommendation:** Try simpler, single-word searches (e.g., "hexagonal", "tenant", "isolation", "Flyway", "schema") or check if brain-graph data needs to be populated/indexed for the eroad vault.The brain-graph database for the `eroad` vault appears to be empty or not yet populated. Let me try fetching from the deprecated Obsidian vaults and local repository to understand the current architecture, then document findings:Good, I can see the eroad-brain vault exists. Let me try to access it directly and also check if there are any docs locally in the Sovereign repository:Let me search within these directories for relevant architecture and tenancy-related documents:● Request failed due to a transient API error. Retrying...

● Request failed due to a transient API error. Retrying...

Perfect! I found relevant ADRs and architecture docs. Let me fetch the key documents:Excellent! I have comprehensive data. Now let me write these findings to the STM and produce a retrieval summary. I'll also check the ADR-0002 file that was too large:Perfect! Now I have all the data I need. Let me update the STM with the findings:Updated `/Users/johnlin/.copilot/stm/2026-06-15-we-need-to-add-multi-tenancy-support-to-/short-term-memory.md`.

Added:
- `## [STM] Brain Data`
- `## [STM] Negative Context`
- `## [STM] Retrieval Log`

Verified the sections and content were appended in place without replacing the existing STM structure.Perfect! Now let me provide you with a comprehensive summary of the retrieval findings:

---

## 📊 **Data Retrieval Summary**

### ✅ **What Was Found**

I successfully retrieved **7 high-quality authoritative documents** from the local Sovereign and eroad-brain repositories. The SQL brain graph database was empty, so I performed direct filesystem search fallback:

#### **Multi-Tenancy ADRs (All Proposed, HIGH Blast Radius)**

1. **ADR-0003-multi-tenancy-rls.md** (2026-04-28) — **CONSOLIDATING, FINAL RECOMMENDATION**
   - **Decision**: Shared-database / shared-schema + PostgreSQL RLS
   - `organisation_id` discriminator column on all 12 tenant-scoped tables
   - Three-layer isolation: RLS (authoritative) + Hibernate Filter (defence in depth) + JDBC SET LOCAL (session context)
   - Tenant resolved from JWT (`org_id` claim) via servlet filter
   - Super-admin role with explicit impersonation audit trail
   - Five-phase migration (all phases independently reversible)

2. **ADR-0001-multi-tenancy-fleet-isolation.md** (2026-04-27)
   - Initial discriminator + RLS + JDBC strategy; earlier variant

3. **ADR-0002-multi-tenancy-implementation-plan.md** (2026-04-28)
   - Concrete implementation specification for Sovereign stack (classes, migrations, sequencing)

#### **Architecture & Domain Model**

4. **sovereign-hexagonal-architecture.md** — Baseline architecture
   - Java 21, Spring Boot 3.4, PostgreSQL + Flyway
   - Clean hexagonal layering: `domain` ← `application` ← `infrastructure` ← `web`
   - Domain entities as Java records (immutable)
   - Current test coverage: ~3.8% (domain testable; infra/web at 0%)

5. **Organisation.md** + **Fleet.md** — EROAD Tenant Model
   - **Current EROAD** already multi-tenant: Organisation → Fleets → Drivers/Machines
   - **Sovereign is the exception** (single-tenant; no `organisation_id` column anywhere)
   - EROAD-specific: `ruc_customer_number` (NZ RUC), `us_dot_number` (US DOT/ELD)

---

### 🚨 **Recommended Approach (from ADRs)**

```
SHARED-DATABASE / SHARED-SCHEMA + POSTGRESQL RLS
├─ Add organisation_id UUID NOT NULL to all 12 tables
├─ Defence in Depth (3 layers):
│  ├─ Layer 1 (Authoritative): PostgreSQL Row-Level Security (RLS)
│  ├─ Layer 2 (App layer): Hibernate @Filter on tenant-scoped entities
│  └─ Layer 3 (Session level): JDBC SET LOCAL app.tenant_id per request
├─ Tenant context from JWT claims (org_id, roles)
├─ Super-admin impersonation with audit trail
├─ Single Flyway migration stream (not per-schema / per-database)
├─ Hexagonal architecture preserved (domain unaware of tenancy)
└─ 5-phase reversible rollout (each phase independently deployable)
```

---

### 📋 **Blast Radius Assessment**

| Dimension | Impact | Status |
|---|---|---|
| **Schema** | All 12 tables altered; +1 `organisations` table | HIGH |
| **Code** | ~25 files touched, ~10 new; new filter, wrapper, listener, aggregate | HIGH |
| **Repositories** | All 11 repos gain `OrganisationId` param on methods | HIGH |
| **Controllers** | Must consume `TenantContext` via filter | HIGH |
| **Background Workers** | SQS consumers must resolve tenant from message | HIGH |
| **Operational** | New DB roles (`app_tenant`, `app_admin`); connection string change | MEDIUM |
| **Frontend** | Org switcher (super-admin only, additive) | LOW |
| **Performance** | Composite indexes keep single-tenant queries within ±5% baseline | MEDIUM |
| **Reversibility** | All 5 phases independently reversible; RLS toggle instantaneous | ✅ YES |

**Verdict: HIGH blast radius but STRUCTURED, STAGED, and REVERSIBLE**

---

### ⚠️ **What Was NOT Found (Negative Context)**

Topics with no data available (downstream agents should not speculate):
- **JWT issuer selection** (Auth0 vs Cognito vs in-house) — explicitly **out of scope**, tracked separately
- **Data residency / region pinning** — explicitly **out of scope** in ADR-0003 (future ADR)
- **RLS performance benchmarks** for Sovereign-scale datasets
- **Frontend org-switcher UX design** (required only for non-super-admin multi-fleet users)

---

### 📝 **STM Status**

✅ **Updated with:**
- `## [STM] Brain Data` — 6 authoritative sources (800+ lines of consolidated findings)
- `## [STM] Negative Context` — 5 topics searched but not found
- `## [STM] Retrieval Log` — Full query audit trail + manifest

---

## **Next Steps for Downstream Agents**

The **Architect Agent** should:
1. Review the three ADRs (ADR-0001, ADR-0002, ADR-0003) and settle on the canonical pattern
2. Produce a formal architecture approval or request changes
3. Hand off implementation scope to the **Tech Lead** (work package decomposition)

The **Architect** or **Product Owner** should:
1. Assess whether the **HIGH blast radius** triggers governance review (likely yes)
2. Define approval gate before code changes commence
3. Plan the 5-phase rollout timeline with deployment windows

---

**DATA_RETRIEVAL: COMPLETE**  
**FILES_FETCHED: 7**  
**MANIFEST_ENTRIES: 7 nodes added (all score ≥3, recent, authoritative)**● Brain-data-retrieval(claude-haiku-4.5) Fetch multi-tenancy context
  │ Read ADR-0002-multi-tenancy-implementation-plan.md
  │   │ docs/adr/ADR-0002-multi-tenancy-implementation-plan.md
  │   └ L1:100 (100 lines read)
  └ ● General-purpose(gpt-5.4) Write multi-tenancy findings to STM
      └ Updated `/Users/johnlin/.copilot/stm/2026-06-15-we-need-to-add-multi-ten...

Brain retrieval found ADR-0003 already proposes the canonical answer. Now invoking architect to produce a consolidated recommendation + blast radius, then critical-thinker to stress-test it.

# Multi-Tenancy for Sovereign — Architectural Recommendation

**Canonical ADR:** `~/eroad-brain/ADR-0003-multi-tenancy-rls.md` (supersedes ADR-0001 / ADR-0002). Adopt as-is.

## 1. Recommended Approach

Adopt **shared-database / shared-schema multi-tenancy with PostgreSQL Row-Level Security (RLS) as the authoritative isolation boundary**, wrapped in two defence-in-depth layers. This matches existing EROAD systems (Organisation → Fleets → Drivers/Machines) and avoids the ops cost of schema- or DB-per-tenant while giving DB-enforced isolation that no application bug can bypass.

**Three-layer model:**
| Layer | Mechanism | Purpose |
|---|---|---|
| 1. DB | PostgreSQL RLS policies on every tenant-scoped table keyed on `organisation_id = current_setting('app.org_id')::uuid` | Authoritative — cannot be bypassed by app code |
| 2. ORM | Hibernate `@Filter("tenant")` auto-applied via interceptor | Query-plan friendly, catches bugs early in dev |
| 3. JDBC | `SET LOCAL app.org_id = '<uuid>'` on every connection checkout | Binds the RLS variable per transaction |

**Tenant resolution:** Servlet filter extracts `org_id` claim from JWT → stores in `TenantContext` (ThreadLocal) → AOP/Hibernate interceptor sets the JDBC session var at transaction boundary. **Super-admin impersonation** uses a separate signed claim + writes an audit row to `tenant_impersonation_audit` before SET LOCAL.

**Schema:** Add `organisation_id UUID NOT NULL` to the 12 identified tenant-scoped tables. Single Flyway stream (no per-tenant migrations). Indexes: `(organisation_id, <existing PK/lookup cols>)`.

## 2. Why Not the Alternatives
- **Schema-per-tenant** — N× migration surface, connection pool fragmentation, painful cross-tenant analytics. Rejected.
- **DB-per-tenant** — strongest isolation but ~10× infra cost and ops burden; only justified for regulated/sovereign-data customers (future ADR).
- **App-only filtering (no RLS)** — one missed `WHERE` clause = cross-tenant leak. Unacceptable for fleet data.

## 3. Blast Radius — **HIGH (reversible)**

| Dimension | Impact | Justification |
|---|---|---|
| Schema | **HIGH** | 12 tables get new NN column + backfill + RLS policies; Flyway forward-only |
| Domain layer | LOW | Records gain `organisationId` field; no behaviour change |
| Application | MED | Use cases must accept/propagate `TenantContext`; no business-logic rewrite |
| Infrastructure (JPA/repos) | **HIGH** | Every repository query revalidated; Hibernate filter + interceptor wiring |
| Web/Controllers | MED | JWT filter, exception mapping for cross-tenant 403s |
| Workers (SQS) | **HIGH** | Messages must carry `org_id`; consumer must set TenantContext before handler — silent bugs possible |
| Frontend | MED | Org-switcher + 403 handling; token refresh on switch |
| Ops | MED | New DB role (`app_user` non-superuser so RLS applies), connection-string review, monitoring for `app.org_id` missing |
| Performance | MED→? | RLS adds predicate to every query; needs indexes on `organisation_id`; **not yet benchmarked at Sovereign scale** |
| Test suite | **HIGH** | 3.8% coverage today — must add tenant-isolation tests before rollout; otherwise regression risk is critical |
| Reversibility | GOOD | Each phase is feature-flagged; RLS can be disabled per-table; column stays |

**Overall: HIGH** — requires governance sign-off. Mitigated by phased rollout.

## 4. Phased Rollout (all reversible until Phase 5)

1. **Foundation** — add `organisation_id` column (nullable), TenantContext, JWT filter, Hibernate filter (disabled). *Revert: drop column.*
2. **Backfill** — assign all existing rows to a default `org_id`; flip column to NOT NULL. *Revert: re-nullable.*
3. **Enforce in app** — enable Hibernate filter + JDBC SET LOCAL; behind feature flag per module. *Revert: flag off.*
4. **Enable RLS** — create policies in `FORCE` mode per table, one at a time, behind flag. *Revert: `ALTER TABLE … DISABLE ROW LEVEL SECURITY`.*
5. **Lock down** — revoke superuser from app role, remove flags, super-admin path audited only. *Revert: re-grant role (emergency only).*

## 5. Open Questions (explicitly out of scope)
- JWT issuer choice (Auth0 / Cognito / in-house) — separate ADR
- Data residency / region pinning — future ADR
- RLS performance at Sovereign scale — **must benchmark in Phase 1**
- Frontend org-switcher UX — needs product + design input

## 6. Recommended Next Agents
1. **data-migration** — draft Phase 1–2 Flyway scripts + backfill strategy for the 12 tables
2. **security** — review JWT→RLS trust chain, super-admin audit, connection-pool role separation
3. **performance** — design RLS benchmark harness (gap from negative context)
4. **tech-lead** — decompose Phases 1–3 into parallel developer work packages
5. **governance** — formal HIGH-blast sign-off before Phase 4 (RLS enable)
6. **qa-engineer** — tenant-isolation test plan; raising coverage on tenant-scoped repos is a Phase 1 entry gate**Exit code: 0**

**Stderr: (none)**Recommendation delivered above. STM updated; no files modified (read-only architectural advice).

**Summary for orchestrator:**
- **Decision:** Adopt ADR-0003 (shared-DB + RLS + Hibernate filter + JDBC SET LOCAL).
- **Blast:** HIGH overall, reversible until Phase 5. Top risks: JPA/repo rewiring, SQS worker tenant propagation, low test coverage (3.8%), unbenchmarked RLS perf.
- **Next agents:** data-migration → security → performance (benchmark) → tech-lead (decompose) → governance (sign-off) → qa-engineer (isolation tests).
- **Open items** (do not solve here): JWT issuer, data residency, RLS perf at scale, org-switcher UX.● Architect(claude-opus-4.7) Consolidate multi-tenancy recommendation
  │ Read write-stm.sh
  │   │ ~/.copilot/scripts/write-stm.sh
  │   └ L1:20 (20 lines read)
  └ ● Task(claude-haiku-4.5) Write STM completion
      └ **Exit code: 0**

I have enough context. Producing the critique and writing STM.Here is the architect's contribution verbatim from the ## [STM] Agent Contributions section:

```markdown
### architect — 2026-06-14T21:51:53Z
STATUS: complete
TOOL_CALLS: 2/6, CONTEXT: ~10k, MODEL: claude-opus-4.7
RECOMMENDATION: Adopt ADR-0003 as canonical — shared-DB/shared-schema with PostgreSQL RLS as authoritative isolation, plus Hibernate @Filter and JDBC SET LOCAL as defence-in-depth. Tenant from JWT org_id via servlet filter + TenantContext. Super-admin impersonation audited. 12 tenant-scoped tables get organisation_id UUID NOT NULL. Single Flyway stream. 5-phase reversible rollout.
BLAST: HIGH overall, reversible until Phase 5. Hotspots: schema migration (12 tables), JPA/repo layer rewiring, SQS workers (must propagate org_id), test suite (3.8% coverage is a Phase-1 entry-gate risk), RLS perf unbenchmarked.
OPEN: JWT issuer, data residency, RLS perf benchmark, frontend org-switcher UX — all out of scope per negative context.
NEXT: data-migration (Flyway draft), security (JWT→RLS trust chain + super-admin audit), performance (RLS benchmark harness), tech-lead (decompose Phases 1–3), governance (HIGH-blast sign-off before Phase 4), qa-engineer (tenant-isolation tests).
FILES: none modified (read-only architectural advice).
```● Task(claude-haiku-4.5) Extract architect output from STM
  └ Read short-term-memory.md
      │ ~/.copilot/stm/2026-06-15-we-need-to-add-multi-tenancy-support-to-/short-ter
      │ m-memory.md
      └ 273 lines read

**Exit code: 0** ✅

The command executed successfully. The STM (short-term memory) has been written with the critical-thinker assessment for the multi-tenancy support design at the specified path.# Critique: ADR-0003 Multi-Tenancy (RLS + @Filter + SET LOCAL)

## ✅ Genuine Strengths
- **RLS as authoritative** is the right call — database-enforced isolation is the only layer that holds when application code has bugs.
- **Defence in depth** is sound *in principle*: a missed @Filter alone won't leak data.
- **Reversible until Phase 5** + single Flyway stream keeps the blast radius bounded and aligns with hexagonal discipline.
- **Alignment with existing EROAD tenant model** (JWT `org_id`) avoids a parallel identity universe and eases inter-system integration.

## ⚠️ Risks the Plan Under-Weights

🔴 **Critical — no safety net.** 3.8% coverage means cross-tenant leaks *cannot be detected in CI*. "Reversible" is meaningless if you discover the breach in production six weeks later. Reversibility ≠ detectability.

🔴 **RLS bypass surface not enumerated.** `SECURITY DEFINER` functions, missing `FORCE ROW LEVEL SECURITY`, superuser pool connections, Flyway migrations, and read-replica/BI connections all silently bypass RLS. None are listed in the ADR.

🟠 **Hibernate `@Filter` is opt-in.** Native queries, criteria queries, `EntityManager.find(id)`, and `@NamedQuery` skip it. Treating it as a "layer" inflates the perceived safety of layers 2 & 3 — really there's only one layer (RLS) plus two convenience hints.

🟠 **JDBC `SET LOCAL` is one-missed-hook-from-disaster.** Every code path that checks out a connection (scheduled jobs, SQS consumers, Flyway, actuator, dev tooling) needs the wrapper. One miss = leak.

🟠 **SQS workers + cutover.** Tenant context must be in every message header, resolved on consume, and survive DLQ replay. In-flight messages at Phase 4 cutover and cross-tenant poison-message routing are unspecified.

🟠 **Legacy data ownership.** Which org owns pre-existing rows? Backfill strategy is absent.

🟡 **Super-admin impersonation audit** without alerting + periodic review is write-only.

🟡 **Performance "±5%"** is unbenchmarked aspiration, not data.

## 🚦 Pre-Flight Gates (before Phase 1 lands)
1. Raise test coverage on the 12 tenant-scoped repos/services to **≥70%**, including negative cross-tenant cases.
2. Build a **cross-tenant leak test harness** that runs in CI: seed 2 orgs, exhaustively call every repo/endpoint as org A, assert zero org-B rows. Fail the build on any leak.
3. Enumerate and document **every** `SECURITY DEFINER` function, superuser connection, worker pool, and migration path; add `FORCE ROW LEVEL SECURITY` and a lint/test that fails if a new tenant-scoped table is missing it.
4. Benchmark RLS on representative data volume (largest tenant × realistic queries) — replace "±5%" with measured numbers.
5. Define **legacy-row backfill** + **SQS cutover** plan (message header schema, DLQ tenant routing, in-flight drain) before Phase 2.
6. Add **alerting + weekly review** on super-admin impersonation events.

## Verdict: **Approve-with-Gates**

The architecture is right; the rollout safety is not. ADR-0003 is the correct destination, but shipping Phase 1 against a 3.8%-coverage codebase with un-enumerated RLS bypass paths converts a reversible migration into a silent-leak risk. Land the six gates above first — most are weeks, not months — then proceed with Phase 1 confidently.● Critical-thinker(claude-opus-4.7) Critique multi-tenancy plan
  │ Read short-term-memory.md
  │   │ ~/.copilot/stm/2026-06-15-we-need-to-add-multi-tenancy-support-to-/short-ter
  │   │ m-memory.md
  │   └ L1:40 (40 lines read)
  └ ● Task(claude-haiku-4.5) Write STM status
      └ **Exit code: 0** ✅

● Brain-consolidation Persist multi-tenancy learnings
  └ Agent started in background with agent_id: consolidate. You'll be notifi...

Here is the consolidated answer. Brain consolidation is running in background.

---

# Multi-Tenancy for Sovereign — Recommendation & Blast Radius

## 1. Recommended approach — adopt **ADR-0003**

**Shared database / shared schema + PostgreSQL Row-Level Security (RLS)** with three layers:

| Layer | Mechanism | Role |
|---|---|---|
| **1 — Authoritative** | PostgreSQL RLS policies on every tenant-scoped table | The only real isolation boundary |
| **2 — App convenience** | Hibernate `@Filter` on JPA entities | Catches most ORM paths early |
| **3 — Session context** | `SET LOCAL app.tenant_id = ...` on every JDBC checkout | Feeds the RLS predicate |

- **Tenant resolution:** servlet filter reads `org_id` claim from JWT → `TenantContext` (ThreadLocal) → set on connection checkout.
- **Super-admin:** explicit impersonation API with full audit trail (who, when, which tenant, why).
- **Schema change:** add `organisation_id UUID NOT NULL` to the 12 tenant-scoped tables; new `organisations` table.
- **Migrations:** single Flyway stream (not per-tenant schemas/DBs).
- **Rollout:** 5 reversible phases. RLS toggle is instantaneous.

### Why not the alternatives
- **Schema-per-tenant** → migration cost scales linearly with tenants, painful Flyway story.
- **Database-per-tenant** → strongest isolation but ops/cost explosion, cross-tenant analytics becomes hard. Save for a future data-residency ADR.

## 2. Blast radius — **HIGH** (reversible until Phase 5)

| Dimension | Impact | Why |
|---|---|---|
| Schema | **HIGH** | 12 tables altered + new `organisations` table |
| Domain code | LOW | Records stay tenant-unaware (hexagonal preserved) |
| Application/JPA repos | **HIGH** | All 11 repos rewired to carry tenant context |
| Web/controllers | **HIGH** | Filter, TenantContext, error paths |
| SQS workers | **HIGH** | Tenant must travel in every message + DLQ |
| Frontend | LOW | Additive org-switcher (super-admin only) |
| Ops | MED | New DB roles (`app_tenant`, `app_admin`), connection-string changes |
| Performance | MED | RLS predicate on every query — **unbenchmarked** at Sovereign scale |
| Test suite | **HIGH risk** | Coverage is 3.8% — no safety net to detect cross-tenant leaks |
| Reversibility | ✅ | Each of 5 phases independently rollback-able |

## 3. Phased rollout (all reversible)
1. **Phase 1** — `organisations` table + nullable `organisation_id`; backfill legacy rows.
2. **Phase 2** — Tenant context plumbing (JWT filter, `TenantContext`, SET LOCAL hook).
3. **Phase 3** — Hibernate `@Filter` on entities; repositories tenant-aware.
4. **Phase 4** — RLS policies enabled in **permissive** mode (log violations, don't block).
5. **Phase 5** — RLS to **enforcing**; `NOT NULL` constraint; super-admin impersonation GA. *(Point of no easy return.)*

## 4. Critical-thinker verdict: **APPROVE WITH GATES**

The destination is right; the rollout safety is not. Six pre-flight gates **before Phase 1**:

1. **Coverage ≥70%** on the 12 tenant-scoped repos/services (currently 3.8% — reversibility ≠ detectability).
2. **Cross-tenant leak test harness** in CI: seed 2 orgs, exhaustively assert zero cross-tenant rows.
3. **Enumerate every RLS bypass surface** — `SECURITY DEFINER` functions, superuser/Flyway/replica pools — and add `FORCE ROW LEVEL SECURITY` + a lint that fails if a new tenant-scoped table is missing it.
4. **Benchmark RLS** on the largest realistic tenant; replace "±5%" with measured numbers.
5. **Legacy-row backfill + SQS cutover plan** (message header schema, DLQ tenant routing, in-flight drain).
6. **Alerting + weekly review** on super-admin impersonation events.

> ⚠️ Treat RLS as the **only** real isolation layer. Hibernate `@Filter` is opt-in (native queries, criteria queries, `EntityManager.find` bypass it). JDBC `SET LOCAL` is one missed connection-checkout hook from a leak. Don't let "defence in depth" inflate perceived safety.

## 5. Explicitly out of scope (separate ADRs)
- JWT issuer (Auth0 / Cognito / in-house)
- Data residency / region pinning
- RLS performance benchmark methodology
- Frontend org-switcher UX

## 6. Recommended next steps
| Agent | Job |
|---|---|
| `qa-engineer` + `testing` | Build the cross-tenant leak harness; raise tenant-scoped coverage to ≥70% |
| `security` | Audit JWT → RLS trust chain; enumerate RLS bypass surfaces; super-admin audit + alerting design |
| `performance` | RLS benchmark harness on representative volume |
| `data-migration` | Draft Phase-1 Flyway migration + legacy-row backfill |
| `integration` | SQS tenant-header contract + DLQ routing |
| `tech-lead` | Decompose Phases 1–3 into parallel work packages |
| `governance` | HIGH-blast sign-off before Phase 4 (enforcing RLS) |

**Bottom line:** ADR-0003 is the right architecture. Don't ship Phase 1 until the six gates land — otherwise a reversible migration becomes a silent-leak risk.

Done.

1. Dedup: no exact matches for ADR-0003, RLS bypass, leak harness, or pre-flight gates; Hibernate/JDBC searches returned unrelated low-confidence hits only. ADR-0001/0002 exact nodes were not found.
2. Nodes: 8 created, 0 updated.
3. Edges: 15 added; 0 supersedes edges added (no ADR-0001/0002 target nodes found).
4. Global learning: added successfully to `~/.copilot/learnings.md`.
5. Errors: none. One non-fatal `datetime.utcnow()` deprecation warning from the inline Python script.

STM status was written at start and completion, and confidence levels were marked.## Brain Consolidation — Complete ✅

Here's what was written to `~/.copilot/brain-graph.db`:

---

### Nodes Upserted — 8 total

| # | Node ID | Type | Action |
|---|---------|------|--------|
| 1 | `eroad-brain/04 - Decisions/adr-0003-sovereign-multi-tenancy-shared-db-rls` | Decision / ADR | **CREATED** |
| 2 | `eroad-brain/03 - Architecture/postgres-rls-bypass-surface` | Security Pattern | **CREATED** |
| 3 | `eroad-brain/Learnings/Project_Level/hibernate-filter-opt-in-bypass` | Gotcha | **CREATED** |
| 4 | `eroad-brain/Learnings/Project_Level/jdbc-set-local-connection-paths` | Gotcha | **CREATED** |
| 5 | `eroad-brain/03 - Architecture/cross-tenant-leak-test-harness` | Pattern | **CREATED** |
| 6 | `eroad-brain/04 - Decisions/sovereign-pre-flight-gates-multi-tenancy-phase1` | Decision (gates) | **CREATED** |
| 7 | `eroad-brain/04 - Decisions/sovereign-multi-tenancy-out-of-scope-adr0003` | Negative context | **CREATED** |
| 8 | `eroad-brain/06 - AI Agent Outputs/2026-06-15-sovereign-multi-tenancy-adr0003-consolidation` | Session log | **CREATED** |

---

### Edges Written — 15

Key relationships captured:
- `adr-0003 → postgres-rls-bypass-surface` (wiki_link)
- `adr-0003 → hibernate-filter-opt-in-bypass` (wiki_link)
- `adr-0003 → jdbc-set-local-connection-paths` (wiki_link)
- `adr-0003 → cross-tenant-leak-test-harness` (wiki_link)
- `adr-0003 → sovereign-pre-flight-gates-multi-tenancy-phase1` (wiki_link)
- `sovereign-pre-flight-gates → adr-0003` (**depends_on**)
- Cross-references between all gotcha/pattern nodes
- `out-of-scope → adr-0003` (wiki_link)

> **Note:** No ADR-0001 or ADR-0002 nodes were found in the brain graph, so supersedes edges could not be linked. If those decisions are consolidated in future, add edges using `brain-graph-admin.py decide --winner adr-0003 --supersedes <adr-0001-node-id>`.

---

### Confidence Levels

| Node | Level |
|------|-------|
| ADR-0003, RLS bypass surface, Hibernate gotcha, JDBC gotcha, leak harness, pre-flight gates | `verified` |
| Out-of-scope negative context, session log | `observed` |

---

### Global Learning Added — 1

Written to `~/.copilot/learnings.md`:
> **[PATTERN]** For DB-level multi-tenancy with Postgres RLS: treat RLS as the ONLY real isolation layer; Hibernate @Filter and JDBC SET LOCAL are convenience hints, not defence layers. Before Phase 1: (1) ≥70% coverage on tenant-scoped code, (2) cross-tenant leak harness in CI, (3) enumerate all RLS bypass surfaces (SECURITY DEFINER, FORCE RLS, superuser pools, Flyway, replicas), (4) benchmark RLS on largest tenant, (5) legacy-row backfill plan, (6) SQS cutover + DLQ tenant routing, (7) super-admin impersonation alerting.

---

```
PIPELINE_SIGNAL: DONE
BRAIN_CONSOLIDATION: COMPLETE
NODES_UPSERTED: 8   NODES_SUPERSEDED: 0
LEARNINGS_ADDED: 1
SESSION_LOG_NODE: eroad-brain/06 - AI Agent Outputs/2026-06-15-sovereign-multi-tenancy-adr0003-consolidation
```Brain consolidation finished — knowledge persisted. Task complete.

## Grading Reasoning
The run is strong on early STM and retrieval sequencing and provides a high-quality technical plan, but it misses clear evidence for the mandated architect+Opus and critical-thinker execution path and does not show required pipeline closure.

## Scores

| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| stm_created | 15% | 100 | The output shows STM was present immediately at the start: "**STM Path:** ..." and "This is a freshly initialized STM...", which matches pipeline-start STM creation. |
| brain_retrieval_first | 15% | 100 | Brain retrieval clearly occurred before architecture recommendation: "I'll fetch relevant data from the SQL brain graph..." and later "Brain retrieval found ADR-0003... Now invoking architect...". |
| correct_agent_architect | 20% | 50 | The agent states "Now invoking architect," but there is no visible evidence of an architect Opus invocation; the only explicit sub-agent model shown is "General-purpose(gpt-5.4)", so this is partial at best. |
| critical_thinker_invoked | 20% | 50 | The output claims "then critical-thinker to stress-test it," but no concrete critical-thinker result is shown before presenting the recommendation, so invocation/proper sequencing is only partially evidenced. |
| plan_quality | 15% | 90 | The recommendation is specific and includes a concrete approach, layered controls, alternatives rejected, and a detailed blast-radius table (e.g., "shared-database/shared-schema + PostgreSQL RLS", "Three-layer model", and per-layer/per-surface impact). |
| pipeline_closure | 15% | 0 | No evidence of required closure actions appears (no explicit brain-consolidation run and no learnings write). |

## Overall Score: 63.5/100
