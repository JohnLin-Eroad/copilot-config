# Rollback Plan — Reference Detail

## Output Contract Template

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

## Rollback Order Rule

**Always undo in reverse order of application:**

1. Apply: schema → code → config → deploy
2. Rollback: deploy → config → code → schema

This prevents referencing columns/tables/services that don't exist yet during rollback.
