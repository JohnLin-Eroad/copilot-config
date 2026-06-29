---
name: rollback-plan
description: >
  Invoke after blast-radius returns MEDIUM, HIGH, or CRITICAL. Produces a concrete,
  step-by-step undo path for every change — exact commands, SQL, and procedures. Flags
  irreversible changes explicitly for go/no-go decisions.
---

# Rollback Plan

Every change that could break something must have a documented undo path **before** it is applied. Not a vague "we could revert" — specific commands for each change.

If a rollback plan cannot be written (irreversible change), that must be stated explicitly and escalated.

---

## When to Trigger

- `blast-radius` returned **MEDIUM, HIGH, or CRITICAL**
- Any **database migration** (schema, data, index)
- Any **infrastructure change** (Docker, env vars, CI/CD)
- Any **dependency version change** (library upgrade/downgrade)
- Any **published API contract change** (endpoint path, request/response schema)
- `governance` agent requires a rollback plan

**Not for:** LOW blast-radius changes with no schema/infra/API involvement, or read-only investigations.

---

## 5-Step Process Overview

1. **Enumerate** all discrete changes being made
2. **Write exact undo steps** for each (SQL, shell commands, git reverts)
3. **Flag irreversible changes** explicitly with pre-conditions
4. **Estimate total rollback** time, downtime, complexity
5. **Write to STM** before any change is applied

---

## Gotchas

- **Write the plan BEFORE implementing** — a rollback plan written after the change is applied is a post-mortem, not a safety net
- **Each change gets its own undo step** — "revert the PR" is not a rollback plan; each file/schema/config is a separate step
- **Column drops are irreversible** — `ALTER TABLE DROP COLUMN` loses data; flag it, don't pretend you can roll it back
- **Order matters in rollback** — undo in reverse order of application; code first, then schema (opposite of apply order)
- **Don't forget transitive dependencies** — a library upgrade may have pulled in transitive changes that also need reverting
- **Docker volume state survives container restarts** — `docker-compose down` doesn't reset data volumes; use `-v` flag or document manual cleanup

---

## Progressive Loading

📘 **GUIDE.md** — Read when you're about to write the rollback plan. Contains step-by-step instructions with examples for each change type.

```bash
cat ~/.copilot/skills/rollback-plan/GUIDE.md
```

📖 **DETAIL.md** — Read when you need the exact output contract template or irreversible change flagging format.

```bash
cat ~/.copilot/skills/rollback-plan/DETAIL.md
```
