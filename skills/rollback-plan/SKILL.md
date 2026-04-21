---
name: rollback-plan
description: >
  Produces a concrete, step-by-step rollback plan before any MEDIUM or above blast-radius
  change is applied. Ensures every change has a documented undo path. Flags irreversible
  changes explicitly so the team can make an informed go/no-go decision. Always run after
  blast-radius returns MEDIUM, HIGH, or CRITICAL.
---

# Skill: Rollback Plan

## Purpose

Every change that could break something must have a documented undo path **before** it is applied. This skill produces a concrete rollback plan — not a vague "we could revert" statement, but specific commands, SQL statements, and restore procedures for each change made.

If a rollback plan cannot be written (because the change is irreversible), that must be stated explicitly and escalated before proceeding.

---

## When to Trigger

Trigger this skill when **any** of these are true:
- The `blast-radius` skill returned **MEDIUM, HIGH, or CRITICAL**
- Any **database migration** is being applied (schema change, data migration, index creation)
- Any **infrastructure change** is being made (Docker config, environment variables, CI/CD pipeline)
- Any **dependency version is being changed** (library upgrade/downgrade, transitive dependency forced)
- Any **published API contract is being changed** (REST endpoint path, request/response schema)
- The `governance` agent requires a rollback plan as a condition of approval

Do **not** trigger for:
- LOW blast-radius changes with no schema, infrastructure, or API involvement
- Read-only investigations or documentation updates

---

## How to Use

### Step 1 — Enumerate All Changes
List every discrete change being made. Be specific — each file edit, schema change, config update, and dependency change is a separate item that needs its own rollback step.

```
Changes being made:
  1. Add column `last_heartbeat_at` to `devices` table (V43 migration)
  2. Update DeviceRepository to query new column
  3. Update DeviceService to write new column on heartbeat
  4. Add new SQS queue `device-heartbeat-dlq` to docker-compose
```

### Step 2 — Write Explicit Undo Steps for Each Change
For each change, write the **exact** undo procedure. Not "revert the migration" — write the actual SQL or command.

Format for each step:
```
### Step N: Undo <change name>
Command / Procedure:
  <exact shell command, SQL statement, or procedure>
Precondition:
  <any state that must be true before this rollback step can run>
Irreversible: yes / no
Rollback time estimate: <e.g. "< 1 min", "5–10 min", "requires downtime">
```

**Examples by change type:**

*Database migration rollback:*
```sql
-- Undo V43: remove last_heartbeat_at column
ALTER TABLE devices DROP COLUMN IF EXISTS last_heartbeat_at;
```

*Git revert (code change):*
```bash
git revert <commit-sha> --no-commit
git commit -m "Revert: DeviceRepository new column query"
```

*Infrastructure rollback (Docker):*
```bash
# Remove new SQS queue from docker-compose and restart
docker-compose down
# Restore previous docker-compose.yml from git
git checkout HEAD~1 -- docker-compose.yml
docker-compose up -d
```

*Dependency rollback:*
```xml
<!-- Restore previous version in pom.xml -->
<dependency>
  <groupId>com.example</groupId>
  <artifactId>library</artifactId>
  <version>2.3.1</version>  <!-- was 2.4.0 -->
</dependency>
```

### Step 3 — Flag Irreversible Changes
If any change **cannot** be rolled back, flag it explicitly:
- **Data migrations that delete or transform existing data** — the original data may be gone
- **Published API contract changes** — external consumers may have already adapted; reverting breaks them again
- **Email / notification sends** — cannot be unsent
- **External system state changes** — if a third-party system was updated, our rollback doesn't undo their state

For each irreversible change, write:
```
⚠️ IRREVERSIBLE: <change name>
Reason: <why it cannot be undone>
Pre-condition required before proceeding: <what must be confirmed before this change is applied>
```

### Step 4 — Estimate Total Rollback Time and Complexity
Give an overall rollback estimate:
- **Time to execute** all rollback steps end-to-end
- **Downtime required** (yes/no — and if yes, estimated duration)
- **Complexity** (LOW / MEDIUM / HIGH — based on number of steps, manual coordination required, data risk)

### Step 5 — Write to STM Before Proceeding
Append the full rollback plan to the STM Agent Contributions before any change is applied. The rollback plan must be written and acknowledged **before** implementation begins.

```bash
# Append to STM
cat >> "$STM_PATH" << 'EOF'

### Rollback Plan — <task name> — <ISO timestamp>
<full plan here>
EOF
```

---

## Output Contract

```markdown
## Rollback Plan — <change description>

**Blast radius verdict:** {MEDIUM | HIGH | CRITICAL}
**Total rollback time estimate:** {e.g. "10–15 min"}
**Downtime required:** {yes / no} — {estimate if yes}
**Rollback complexity:** {LOW | MEDIUM | HIGH}

---

### Step 1: Undo <change name>
Command:
```
{exact command or SQL}
```
Precondition: {any required state}
Irreversible: {yes / no}
Rollback time: {estimate}

### Step 2: Undo <change name>
Command:
```
{exact command or SQL}
```
Precondition: {any required state}
Irreversible: {yes / no}
Rollback time: {estimate}

---

### ⚠️ Irreversible Changes
- {change} — {reason} — Pre-condition: {what must be confirmed}

### ✅ Rollback Plan Status
Written to STM: yes
Acknowledged before implementation: {yes / pending}
```

---

## Comparison

| Skill | Use when |
|---|---|
| `blast-radius` | Before any change — assess how far impact spreads |
| `rollback-plan` | After MEDIUM+ blast verdict — document the undo path |
| `dual-critique` | HIGH/CRITICAL blast — pressure-test the approach adversarially |
| `tdd-workflow` | Writing implementation — ensure tests exist before code |
| `critical-thinker` | Holistic plan evaluation — risks and strengths |
```
