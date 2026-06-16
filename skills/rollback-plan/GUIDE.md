# Rollback Plan — Execution Guide

## Step 1 — Enumerate All Changes

List every discrete change. Each file edit, schema change, config update, and dependency change is a separate item.

```
Changes being made:
  1. Add column `last_heartbeat_at` to `devices` table (V43 migration)
  2. Update DeviceRepository to query new column
  3. Update DeviceService to write new column on heartbeat
  4. Add new SQS queue `device-heartbeat-dlq` to docker-compose
```

## Step 2 — Write Exact Undo Steps

For each change, write the **exact** undo procedure — not "revert the migration".

**Format:**
```
### Step N: Undo <change name>
Command: <exact shell command, SQL, or procedure>
Precondition: <state that must be true before this step can run>
Irreversible: yes / no
Rollback time: <estimate>
```

**Examples by change type:**

*Database migration:*
```sql
-- Undo V43: remove last_heartbeat_at column
ALTER TABLE devices DROP COLUMN IF EXISTS last_heartbeat_at;
```

*Git revert:*
```bash
git revert <commit-sha> --no-commit
git commit -m "Revert: DeviceRepository new column query"
```

*Infrastructure (Docker):*
```bash
docker-compose down
git checkout HEAD~1 -- docker-compose.yml
docker-compose up -d
```

*Dependency:*
```xml
<!-- Restore previous version in pom.xml -->
<version>2.3.1</version>  <!-- was 2.4.0 -->
```

## Step 3 — Flag Irreversible Changes

Common irreversible change types:
- **Data migrations that delete/transform data** — original data is gone
- **Published API contract changes** — external consumers may have adapted
- **Email / notification sends** — cannot be unsent
- **External system state changes** — our rollback doesn't undo their state

```
⚠️ IRREVERSIBLE: <change name>
Reason: <why it cannot be undone>
Pre-condition required before proceeding: <what must be confirmed>
```

## Step 4 — Estimate Total Rollback

- **Time to execute** all steps end-to-end
- **Downtime required** — yes/no + estimated duration
- **Complexity** — LOW / MEDIUM / HIGH

## Step 5 — Write to STM

Append the full rollback plan to STM **before** any change is applied:

```bash
cat >> "$STM_PATH" << 'EOF'

### Rollback Plan — <task name> — <ISO timestamp>
<full plan here>
EOF
```
