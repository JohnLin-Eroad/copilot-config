---
name: blast-radius
description: >
  Performs a structured blast radius assessment before any HIGH or CRITICAL change.
  Returns a severity verdict (LOW / MEDIUM / HIGH / CRITICAL) with explicit reasoning
  and a list of what could break. Run this before touching shared interfaces, APIs,
  database schemas, or any change crossing service boundaries.
---

# Skill: Blast Radius

## Purpose

Before making any significant change, assess how far the blast can spread if something goes wrong. This skill produces a **structured impact report** with a severity verdict, explicit reasoning, and a list of at-risk components — giving the team the information needed to decide whether to proceed, add mitigations, or escalate for review.

A blast radius assessment is not a blocker — it is a decision-support tool.

---

## When to Trigger

Trigger this skill when **any** of these are true:
- The change touches **more than 2 files**
- The change **crosses service boundaries** (e.g. modifies code consumed by another service)
- The change modifies a **shared interface or API** (REST endpoint, event schema, database table, shared library)
- The change modifies a **database schema** (DDL, migration, index)
- The change modifies **infrastructure** (Docker, CI/CD, environment config)
- The `governance` agent or `orchestrator` requests a blast assessment
- Blast radius is listed as UNKNOWN and the change is non-trivial

Do **not** trigger for:
- Single-file cosmetic changes with no consumers
- Test-only changes that don't touch production code
- Documentation-only changes

---

## How to Use

### Step 1 — List Directly Changed Files/Services/Modules
Enumerate every file, service, module, or schema that will be directly modified by this change. Be exhaustive — include config files, migrations, and infrastructure files.

```
Directly changed:
  - src/main/java/com/eroad/location/LocationService.java
  - src/main/resources/db/migration/V42__add_location_index.sql
  - application.yml (dev profile)
```

### Step 2 — Map All Consumers
For each directly changed item, identify everything that imports, calls, extends, or depends on it. Use grep, dependency trees, or known service maps.

```bash
# Find all Java files that import the changed class
grep -r --include="*.java" "import com.eroad.location.LocationService" .

# Find all services that call a REST endpoint
grep -r --include="*.java" "/api/v1/location" .
```

List every consumer found. If a consumer is in a different service or repo, flag it explicitly as a **cross-service dependency**.

### Step 3 — Identify Side Effects
Beyond direct consumers, identify indirect effects:
- **API contract changes** — will existing callers break? Are they versioned?
- **Database changes** — could the migration lock a table? Cause data loss? Break existing queries?
- **Event schema changes** — will existing consumers of the event still deserialise it correctly?
- **Config changes** — will other environments be affected?
- **Infrastructure changes** — will other services in the same Docker network / cluster be affected?

### Step 4 — Assign Blast Radius Verdict

| Verdict | Criteria |
|---------|----------|
| **LOW** | 1–2 files, no cross-service consumers, no schema change, easily reversible |
| **MEDIUM** | Multi-file, limited consumers (same service), minor schema change, reversible |
| **HIGH** | Shared interface/API modified, cross-service consumers, migration with table lock risk |
| **CRITICAL** | Irreversible change, multi-system impact, published API contract broken, data loss risk |

### Step 5 — Output the Verdict
Write the assessment in the Output Contract format below and append it to TASK_CONTEXT.md or STM Agent Contributions.

---

## Output Contract

```
Blast radius: {LOW | MEDIUM | HIGH | CRITICAL}
Reason: {1-2 sentence explanation of why this verdict was assigned}

Directly changed:
  - {file or service}
  - {file or service}

At risk (consumers & side effects):
  - {consumer or side effect} — {why it's at risk}
  - {consumer or side effect} — {why it's at risk}

Cross-service dependencies: {yes / no}
  - {service name} — {nature of dependency}

Irreversible elements: {yes / no}
  - {element} — {why it cannot be undone}

Mitigation:
  1. {concrete mitigation step}
  2. {concrete mitigation step}

Recommended next skill: {rollback-plan | dual-critique | proceed}
```

---

## Comparison

| Skill | Use when |
|---|---|
| `blast-radius` | Before any change — assess impact scope |
| `rollback-plan` | After blast-radius returns MEDIUM+ — document the undo path |
| `dual-critique` | HIGH or CRITICAL verdict — pressure-test the approach adversarially |
| `critical-thinker` | Evaluating a plan or architecture holistically — risks and strengths |
| `tdd-workflow` | Writing implementation code — ensure tests exist before code |
