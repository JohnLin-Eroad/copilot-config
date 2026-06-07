# Dual-Critique — Reference Detail

## Synthesis Output Format

After the loop completes, produce:

```markdown
## Dual-Critique Result

**Rounds taken:** N
**Convergence:** YES / PARTIAL (N unresolved issues)

### Final Plan
<the Planner's last output>

### Unresolved Issues (if any)
<any 🔴/🟠 findings the Planner did not fully address>
Human judgement required on these before proceeding.

### What Changed Between Rounds
- Round 1→2: <key changes driven by critique>
- Round 2→3: <key changes driven by critique>
```

---

## Practical Invocation

1. Write the brief to: `/tmp/dual-critique-<slug>/brief.md`
2. Run the loop using the **task** tool — spawn Planner and Critiquer as separate agents per round
3. Save each round's output to `/tmp/dual-critique-<slug>/round-N-plan.md` and `round-N-critique.md`
4. After loop completes, present the synthesised output to the user

**Token budget:**
- Each round: ~8–15k tokens (Opus plan + Codex critique)
- 3 rounds max: ~45k tokens total

---

## Example

```
User: "Refactor telematics ingestion from Kinesis to SQS FIFO"

Brief: Migrate espserver-service → ebox-service → central-event-forwarder chain
       from Kinesis to SQS FIFO. Constraints: zero downtime, no schema changes,
       2-week window. Convergence = no ordering or throughput risks unaddressed.

Round 1: Opus produces migration plan with blue-green cutover
Round 2: Codex flags FIFO throughput limit (3,000 msg/s) vs current Kinesis peak
Round 3: Opus revises with message batching + FIFO group IDs per vehicle
Critiquer: all remaining issues minor → CONVERGED
```
