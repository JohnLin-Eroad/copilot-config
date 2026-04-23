# Parallel Decomposition Protocol — v3 FINAL

> Round 3 adversarial collaboration output. Addresses all Critical (🔴) and Major (🟠) findings.
> This is the **implementation-ready** specification.

---

## ROUND 3 FIXES — CONCRETE DECISIONS

---

### Fix for #1 🔴 — Replace grep-based DI validation with executable Spring context smoke test

- **Delete** all grep-based `@Autowired`/`@Qualifier`/constructor-injection scanning logic. It is unreliable and gives false confidence.
- **Replace with** a real `ApplicationContext` load test per modified module. The integration-owner agent runs:
  ```
  mvn -pl <module> test -Dtest=SmokeContextTest -Dspring.profiles.active=test -q
  ```
  where `SmokeContextTest` is a pre-existing `@SpringBootTest(classes = {...})` that loads the module's `@Configuration` classes and asserts all beans resolve.
- **If no `SmokeContextTest` exists** for the module, the agent **creates one** as part of its integration work — loading the module's root config class with `@SpringBootTest` and `@TestPropertySource` pointing to test defaults. This is a gate: the unit cannot be marked INTEGRATED without a passing context smoke test.
- **Timeout for context load**: 60 seconds. Failure = INTEGRATION_FAIL, triggers the module-specific retry path (not full re-plan).

---

### Fix for #2 🔴 — Recalibrate budget model with elastic overrun

**New base caps by complexity tier:**

| Complexity Score | Base Tool Calls | Max Agent Spawn | Notes |
|---|---|---|---|
| ≤150 (trivial) | 15 | 0 | Single-agent, no delegation |
| 151–300 (low) | 30 | 2 | Was 8 — catastrophically low |
| 301–500 (medium) | 60 | 4 | Standard parallel decomposition |
| 501–800 (high) | 100 | 6 | Full pipeline |
| 801+ (extreme) | 150 | 6 | Hard cap stays at 6 agents |

**Global session cap**: 50 → **120 tool calls** (sum of all agents). Rationale: a 4-unit parallel decomposition with compile+test per unit legitimately needs 80–100 calls.

**Elastic overrun rules:**
1. Any agent may request a **+25% budget extension** by writing `BUDGET_EXTEND_REQUEST` to STM with a justification string (e.g., "compile discovered 3 cascading type errors, need 8 more calls to fix").
2. The orchestrator auto-approves extensions **once per agent** if the agent has made measurable progress (≥1 file written or test passing). No human in the loop.
3. Second extension request from the same agent = **denied**. Agent must complete with what it has or mark the unit BLOCKED.
4. Global cap is a **hard ceiling** — no elastic overrun on the session total. If an agent's extension would exceed the global cap, it's denied.

**Budget ledger format in STM:**
```
## [STM] Budget Ledger
| Agent       | Base | Extended | Used | Remaining |
|-------------|------|----------|------|-----------|
| unit-auth   | 30   | +8       | 25   | 13        |
| unit-fleet  | 30   | 0        | 30   | 0         |
| integration | 30   | 0        | 12   | 18        |
| GLOBAL      | 120  | —        | 67   | 53        |
```

---

### Fix for #3 🟠 — Add risk factors to complexity formula

**Current formula (flawed):**
```
complexity = (imports × 2) + (lines / 10) + (method_count × 1.5)
```

**New formula:**
```
complexity = base_structural + risk_multiplier

base_structural = (unique_imports × 1) + (lines / 15) + (method_count × 1)

risk_factors (additive):
  +40  if file is a @Configuration class
  +30  if file touches a shared DTO/entity used by ≥2 other units
  +50  if file modifies a DB migration (Flyway/Liquibase)
  +50  if file changes a public REST/gRPC API contract
  +25  if file modifies application.yml / application.properties
  +20  per framework annotation beyond standard (@ConditionalOn*, @Profile, @Transactional propagation)
  +15  if file is touched by ≥2 units in the current decomposition (shared-file penalty)
```

**Implementation**: The complexity scorer reads the file list + git diff for each unit. Risk factors are computed by pattern matching on file paths and annotation scanning (this *is* a valid use of grep — we're scanning for risk signals, not validating wiring).

**Shared-file penalty** is critical: if `VehicleDTO.java` is modified by both `unit-location` and `unit-compliance`, each unit gets +15 AND the file is flagged for ordered merge (integration-owner handles it).

---

### Fix for #4 🟠 — Versioned contract refresh checkpoints

**Replace "read contracts once" with a checkpoint protocol:**

1. At spawn time, each agent receives the contract payload as before (this is **v0**).
2. At any point, an agent may read the STM section `## [STM] Contract Evolution` to check for updates. This costs 1 tool call against the agent's budget.
3. **Only the orchestrator may write contract updates.** An agent that discovers a contract must change (e.g., method signature needs a new parameter) writes:
   ```
   CONTRACT_CHANGE_REQUEST: unit-auth
   File: AuthService.java
   Change: addUser(String name) → addUser(String name, String tenantId)
   Reason: tenant isolation requires tenantId propagation
   Affected units: unit-auth, unit-fleet
   ```
4. The orchestrator **validates the change doesn't break the DAG**, bumps the version, and writes to STM:
   ```
   ## [STM] Contract Evolution
   ### v1 (approved by orchestrator, T+45s)
   AuthService.addUser: added tenantId:String param
   Affected: unit-auth, unit-fleet
   ```
5. Affected agents receive a `CONTRACT_REFRESH: v1` signal on their next STM read. They must acknowledge it before continuing. Non-affected agents are not interrupted.
6. **Max 3 contract revisions per session.** If a 4th is requested, the orchestrator halts parallel work and falls back to sequential completion — the decomposition was too unstable.

---

### Fix for #5 🟠 — Adaptive file limits and overflow contract chunks

**File limits — replace fixed ceiling with adaptive:**

| Complexity Tier | Max Files/Unit | Rationale |
|---|---|---|
| ≤150 (trivial) | 3 | Single concern |
| 151–300 (low) | 5 | Small slice |
| 301–500 (medium) | 7 | Standard unit |
| 501–800 (high) | 10 | Large unit, likely has DTOs + config |
| 801+ (extreme) | 12 | Consider re-decomposing instead |

**If a unit exceeds its tier's limit**, the orchestrator must either:
- Re-decompose the unit into 2 smaller units, OR
- Explicitly approve an override with justification in STM (one-time, no cascading)

**Contract payload — replace fixed 500-char with structured format:**

```yaml
contract:
  unit: unit-auth
  version: v0
  interfaces:          # max 3 interface blocks
    - class: AuthService
      package: com.eroad.auth.domain.service
      methods:
        - sig: "UserResult addUser(AddUserCommand cmd)"
          notes: "cmd contains tenantId, validated upstream"
        - sig: "void removeUser(UserId id)"
    - class: AuthPort
      package: com.eroad.auth.domain.port.outbound
      methods:
        - sig: "User findByTenantAndEmail(TenantId t, Email e)"
  shared_types:        # types this unit exposes to others
    - "AddUserCommand(String name, TenantId tenantId, Email email)"
    - "UserResult(UserId id, Instant createdAt)"
  config_keys:         # spring config this unit owns
    - "eroad.auth.jwt.issuer"
    - "eroad.auth.token-ttl-seconds"
```

- **No char limit.** Instead: max **3 interface blocks**, max **8 method signatures** per block, max **6 shared types**. This is a structural cap, not a byte cap.
- Generic types are preserved in full: `Optional<List<VehicleDTO>>` is never truncated.
- Annotations that affect contract semantics (`@Nullable`, `@Valid`, `@Transactional(propagation=REQUIRES_NEW)`) are included in `notes`.

---

### Fix for #6 🟠 — Phase-aware timeout

**Replace flat 90s timeout with phase-based:**

| Agent Phase | Timeout | Detection |
|---|---|---|
| PLANNING (reading files, building approach) | 45s | No file writes yet |
| CODING (writing/editing files) | 60s since last file write | ≥1 file written |
| COMPILING (`mvn compile` running) | 120s | Detected by process name or STM phase marker |
| TESTING (`mvn test` running) | 180s | Detected by process name or STM phase marker |
| IDLE (no tool calls) | 30s | 0 tool calls in window |

**How it works:**
- Each agent writes its current phase to STM: `PHASE: unit-auth = COMPILING`
- The orchestrator's watchdog checks phase before applying timeout.
- If an agent exceeds its phase timeout, the orchestrator sends `TIMEOUT_WARNING` first. The agent has 15s to respond with a progress signal. No response = kill.
- **Compile/test phases get a generous 120s/180s** because `mvn test` on a Spring module legitimately takes 60–90s.

---

### Fix for #7 🟠 — Require runnable integration test per changed use-case path

**Gate definition:**

For each use-case path modified in the decomposition, the integration phase must produce **at least one** of:
1. A `@SpringBootTest` that exercises the path end-to-end (controller → service → repository/port), OR
2. A `@Testcontainers`-based test that validates the path against real infrastructure (Postgres, SQS, S3), OR
3. If neither is feasible within budget, an `@WebMvcTest` / `@DataJpaTest` slice test that covers the modified layer + a manual verification note in STM.

**Concrete protocol:**
- The integration-owner writes to STM: `INTEGRATION_TEST: use-case=addUser test=AddUserIntegrationTest.java status=PASS`
- If any use-case path lacks a corresponding test entry, the orchestrator blocks the DONE transition.
- **Pre-existing integration tests count.** If `AddUserIntegrationTest` already exists and passes after the changes, that satisfies the gate. The agent doesn't need to write a new one.
- **Budget allocation**: Integration testing gets its own budget slice (20 tool calls from the global pool), separate from the integration-owner's wiring budget.

---

### Fix for #8 🟠 — Split integration ownership by file class

**Replace single integration-owner with 3 deterministic merge lanes:**

| Lane | Owns | Merge Order | Agent |
|---|---|---|---|
| **CONFIG lane** | `@Configuration`, `application*.yml`, `*Properties.java` | Merges FIRST | `integration-config` (or orchestrator if only 1–2 config files) |
| **DTO/ENTITY lane** | Shared DTOs, JPA entities, command/event objects | Merges SECOND | `integration-dto` |
| **WIRING lane** | DI assembly, port-adapter bindings, module entry points | Merges LAST (after config + DTO stable) | `integration-wiring` |

**Rules:**
- Each lane runs **sequentially** in the order above (CONFIG → DTO → WIRING). No parallelism between lanes — each builds on the previous.
- Within a lane, files are merged in **alphabetical order by fully-qualified class name** — deterministic, no conflicts.
- If a unit has ≤2 files in a lane, the orchestrator handles that lane directly (no agent spawn overhead).
- The WIRING lane runs the `SmokeContextTest` (from Fix #1) as its exit gate.
- **Total integration agents: max 3.** These count against the 6-agent global cap, so only 3 unit agents can run in parallel if all 3 lanes need dedicated agents.

**Merge conflict resolution:**
- If two units modified the same file, the LATER unit's changes are applied as a patch on top of the EARLIER unit's version (unit ordering is determined by DAG topological sort).
- If the patch fails to apply cleanly, the file is flagged for manual reconciliation by the wiring lane agent, which has full context of both units' contracts.

---

### Fix for #9 🟠 — Circuit breaker recovery with degraded mode

**Current problem:** Circuit breaker trips → all parallel work stops → deadlock.

**New protocol — Degraded Sequential Completion (DSC):**

1. **Circuit breaker triggers** when: ≥2 agents fail within 30s window, OR global budget drops below 15% with >50% of units still incomplete.

2. **On trip, the orchestrator:**
   a. Immediately kills all running unit agents (saves budget).
   b. Ranks remaining incomplete units by **value score**:
      ```
      value = (downstream_dependents × 3) + (files_already_written × 2) + (tests_passing × 5)
      ```
      Higher value = complete this one first.
   c. Writes to STM: `CIRCUIT_BREAKER: TRIPPED → DEGRADED_SEQUENTIAL`

3. **Emergency budget tranche:**
   - The global cap gets a one-time **+30 tool call extension** (hard, non-renewable).
   - This extension is ONLY available in DSC mode. It cannot be pre-spent in normal mode.

4. **Sequential completion:**
   - Units are completed one at a time, highest value first.
   - Each unit gets `min(remaining_global_budget / remaining_units, 25)` tool calls.
   - If a unit fails in DSC mode, it is marked `ABANDONED` with a structured explanation and the next unit proceeds.

5. **Exit conditions:**
   - All units DONE or ABANDONED → proceed to integration (skipping ABANDONED units).
   - Global budget exhausted → halt, output partial results + structured gap report.
   - **ABANDONED units are documented** in the final output: what was planned, what was completed, what remains.

6. **No re-entry to parallel mode.** Once DSC activates, the session stays sequential. The decomposition has proven too unstable for parallelism.

---

## FINAL EXECUTION FLOW — COMPLETE END-TO-END PROTOCOL

Incorporates all decisions from Rounds 1, 2, and 3.

```
═══════════════════════════════════════════════════════════════
 PHASE 0: TASK INTAKE & CLASSIFICATION
═══════════════════════════════════════════════════════════════

 0.1  Receive task brief from user
 0.2  Create STM file (append-only, flock-guarded)
 0.3  Run brain-data-retrieval → populate STM Brain Data section
 0.4  Classify: domain, type, blast radius, brain type

═══════════════════════════════════════════════════════════════
 PHASE 1: ANALYSIS & DECOMPOSITION
═══════════════════════════════════════════════════════════════

 1.1  Read all affected files (discovery agent or direct)
 1.2  Identify use-case slices — one capability boundary per unit
 1.3  For each candidate unit, compute COMPLEXITY SCORE:
        base_structural = (unique_imports) + (lines/15) + (methods)
        + risk_factors:
          +40 @Configuration class
          +30 shared DTO/entity (used by ≥2 units)
          +50 DB migration file
          +50 public API contract change
          +25 application.yml change
          +20 per exotic framework annotation
          +15 per shared-file cross-unit touch
 1.4  Assign complexity tier → derive file limit + budget per unit
 1.5  Build unit DAG — check for cycles (reject if cyclic)
 1.6  Identify shared files → flag for ordered merge (Fix #3, #8)
 1.7  Validate: each unit ≤ tier file limit. If exceeded → re-split
        or explicit override with justification

═══════════════════════════════════════════════════════════════
 PHASE 2: CONTRACT GENERATION
═══════════════════════════════════════════════════════════════

 2.1  For each unit, produce structured contract (Fix #5):
        - Up to 3 interface blocks, 8 methods each
        - Shared types with full generic signatures
        - Config keys owned
        - Semantic annotations preserved
 2.2  Write contracts to STM as v0
 2.3  Initialize budget ledger in STM (Fix #2):
        - Per-agent base from complexity tier
        - Global cap = 120 tool calls
        - Extension allowance = +25% once per agent

═══════════════════════════════════════════════════════════════
 PHASE 3: PARALLEL UNIT EXECUTION
═══════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────┐
  │  For each unit (max 6 agents, DAG-respecting order) │
  │                                                     │
  │  3.1  Spawn agent with:                             │
  │       - Full contract payload (v0)                  │
  │       - File list + boundaries                      │
  │       - Budget allocation                           │
  │       - Tier-specific timeout schedule              │
  │                                                     │
  │  3.2  Agent works through phases:                   │
  │       PLANNING → CODING → COMPILING → TESTING       │
  │       Writes phase to STM for watchdog              │
  │                                                     │
  │  3.3  Phase-aware timeouts (Fix #6):                │
  │       PLANNING=45s CODING=60s COMPILE=120s TEST=180s│
  │       IDLE=30s. Timeout warning → 15s grace → kill  │
  │                                                     │
  │  3.4  Per-unit compile check before DONE:           │
  │       mvn -pl <module> compile -q                   │
  │       Fail → retry with syntax-fix policy (max 2)   │
  │                                                     │
  │  3.5  Contract refresh checkpoint (Fix #4):         │
  │       Agent may read STM Contract Evolution section  │
  │       If version > agent's version → ack + adapt    │
  │       Max 3 revisions per session globally           │
  │                                                     │
  │  3.6  Budget tracking:                              │
  │       Each tool call decrements agent + global      │
  │       At 80% used → agent gets a warning            │
  │       Extension request: +25%, approved once if     │
  │       measurable progress (≥1 file or test)         │
  │                                                     │
  │  3.7  On agent completion:                          │
  │       Write to STM: files changed, tests written,   │
  │       contract change requests (if any)             │
  │       Mark unit: DONE / FAILED / BLOCKED            │
  └─────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────┐
  │  WATCHDOG (runs continuously during Phase 3)        │
  │                                                     │
  │  W.1  Monitor phase-aware timeouts per agent        │
  │  W.2  Monitor global budget burn rate               │
  │  W.3  Process CONTRACT_CHANGE_REQUESTs:             │
  │       - Validate against DAG                        │
  │       - Bump contract version                       │
  │       - Notify affected agents                      │
  │  W.4  CIRCUIT BREAKER check (Fix #9):               │
  │       IF ≥2 agents fail in 30s window               │
  │       OR budget < 15% AND > 50% units incomplete    │
  │       → TRIP → enter Degraded Sequential (Phase 3D) │
  └─────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────┐
  │  PHASE 3D: DEGRADED SEQUENTIAL (if circuit trips)   │
  │                                                     │
  │  3D.1  Kill all running agents                      │
  │  3D.2  Grant emergency +30 tool call tranche        │
  │  3D.3  Rank remaining units by value score:         │
  │         (downstream_deps×3)+(files_written×2)       │
  │         +(tests_passing×5)                          │
  │  3D.4  Complete units sequentially, highest first   │
  │         Budget per unit = remaining / units_left    │
  │         Max 25 calls per unit                       │
  │  3D.5  Unit fail in DSC → mark ABANDONED + doc why  │
  │  3D.6  No re-entry to parallel mode                 │
  └─────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════
 PHASE 4: INTEGRATION — 3-LANE MERGE (Fix #8)
═══════════════════════════════════════════════════════════════

 4.1  LANE 1 — CONFIG (merges first)
      - All @Configuration, application*.yml, *Properties.java
      - Files merged in alphabetical FQN order
      - Conflict: later unit patches on top of earlier (DAG order)
      - Exit gate: all config files compile

 4.2  LANE 2 — DTO/ENTITY (merges second, after config stable)
      - Shared DTOs, JPA entities, command/event objects
      - Same merge strategy: alphabetical FQN, DAG-ordered patches
      - Exit gate: all DTO/entity files compile

 4.3  LANE 3 — WIRING (merges last, after config + DTO stable)
      - DI assembly, port-adapter bindings, module entry points
      - Exit gate: SmokeContextTest passes (Fix #1)
        → mvn -pl <module> test -Dtest=SmokeContextTest -q
        → If no SmokeContextTest exists, agent creates one
        → 60s timeout for context load

 4.4  If ≤2 files in a lane → orchestrator handles directly (no spawn)

═══════════════════════════════════════════════════════════════
 PHASE 5: INTEGRATION TESTING (Fix #7)
═══════════════════════════════════════════════════════════════

 5.1  For each use-case path modified:
      - Run existing @SpringBootTest / @Testcontainers test
      - If none exists → agent writes one (budget: 20 tool calls)
      - Minimum: 1 integration test per modified use-case path
 5.2  Write to STM per test:
      INTEGRATION_TEST: use-case=X test=Y.java status=PASS/FAIL
 5.3  Gate: ALL use-case paths must have PASS entry
      - FAIL → retry with test-fix policy (max 2 attempts)
      - Still failing → mark use-case DEGRADED + document gap
 5.4  Run full module compile: mvn -pl <module> compile test -q
      - This is the final quality gate

═══════════════════════════════════════════════════════════════
 PHASE 6: FINALIZATION
═══════════════════════════════════════════════════════════════

 6.1  Compile final output:
      - All files changed (with paths)
      - All tests written/updated
      - Contract evolution log
      - Budget usage summary
      - ABANDONED units (if any) with gap documentation
 6.2  Write learnings to STM
 6.3  Invoke brain-consolidation if domain knowledge gained
 6.4  Return to user

═══════════════════════════════════════════════════════════════
```

---

## FAILURE-CLASS RETRY POLICY (carried from Round 1, unchanged)

| Failure Class | Detection | Retry Strategy | Max Retries |
|---|---|---|---|
| Syntax error | `mvn compile` fails with parse error | Agent self-fixes with compiler output | 2 |
| Test failure | `mvn test` fails, compile passes | Agent reads test output, adjusts logic | 2 |
| Integration/wiring | `SmokeContextTest` fails | Wiring lane agent re-examines bean graph | 1 |
| Timeout | Phase timeout exceeded | Kill → re-spawn with +50% timeout | 1 |
| Budget exhaustion | Agent budget = 0 | No retry — mark BLOCKED or ABANDONED | 0 |
| Contract conflict | Merge patch fails | Wiring lane agent manually reconciles | 1 |

---

## HARD CONSTRAINTS SUMMARY

| Constraint | Value | Elastic? |
|---|---|---|
| Max parallel agents | 6 | No |
| Max delegation depth | 2 tiers | No |
| Global tool call cap | 120 | No (hard) |
| Per-agent extension | +25% once | Yes (auto-approved with progress proof) |
| Emergency DSC tranche | +30 calls | One-time, only in DSC mode |
| Max contract revisions | 3 per session | No — 4th triggers sequential fallback |
| Max files per unit | Tier-dependent (3–12) | Override with justification |
| Integration test gate | 1 per use-case path | No |
| SmokeContextTest gate | Required per module | No |
| Merge order | CONFIG → DTO → WIRING | No |

---

## STATE MACHINE (unit lifecycle)

```
PLANNED → SPAWNED → CODING → COMPILING → TESTING → DONE
                                                      ↓
                 ←←← RETRY (max per class) ←←←←  FAILED
                                                      ↓
                                                  BLOCKED
                                                      ↓
                                              ABANDONED (DSC only)
```

Each transition is written to STM with timestamp. The orchestrator is the only
writer of terminal states (DONE, BLOCKED, ABANDONED). Agents propose transitions;
the orchestrator validates and commits.

---

*End of v3 final specification.*
