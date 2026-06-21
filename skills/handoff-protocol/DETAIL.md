# Handoff Protocol — Full Reference (Tier 3)

Orchestrator-specific: how to construct targeted handoffs, checkpoint protocol, and user commands.

---

## Constructing a Targeted Handoff

The orchestrator builds a handoff for each agent transition. **Include only what the receiving agent needs.**

### Handoff Template

```markdown
# Handoff → {Agent Name}

## Task Brief
<Original user request — always include this>

## Your Job
<Specific instructions for this agent — what to produce, constraints, scope>

## Context from Prior Agents
<Only the outputs relevant to this agent's work. Summarise, don't dump.>

## STM Path
<Path to the STM file if the agent needs to look up more context>

## Constraints
- <Any decisions already made that this agent must respect>
- <Negative constraints: what NOT to do>
```

### What to Include Per Agent Role

| Agent | Include in handoff | Exclude |
|-------|-------------------|---------|
| **Product Manager** | User request, domain context from brain | Everything else |
| **Architect** | Task brief, product spec | PM's reasoning process |
| **Developer** | Task brief, architecture decisions, file paths | PM spec, security review details |
| **Security** | Architecture/code to review, threat context | PM spec, unrelated decisions |
| **QA Engineer** | Acceptance criteria, implementation summary, file paths | Architecture rationale, security details |
| **Code Reviewer** | Diff/file paths, architecture decisions | Full PM spec, QA results |
| **DevOps** | Deployment-relevant changes, infra decisions | Business logic, PM spec |

**Rule of thumb:** If removing a section from the handoff wouldn't change the agent's output, don't include it.

---

## Checkpoint Protocol

After **key agents complete** (not necessarily every agent), the orchestrator:
1. Writes agent output to STM
2. Presents a brief summary to the user
3. **Waits for user approval** before proceeding

### Checkpoint Summary Format

```
✅ {Agent Name} complete.

Summary: {2-3 sentences}
Key outputs: {bullet list}
Issues: {any flags, or "None"}

Next up: {Next Agent} — {what it will do}

Reply `continue`, `change: <instruction>`, `redo: <agent>`, `skip: <agent>`, or `stop`.
```

### User Commands at Checkpoint

| Command | Action |
|---|---|
| `continue` | Proceed to next agent |
| `change: <instruction>` | Amend context, re-run affected agent if needed |
| `redo: <agent>` | Re-invoke agent from scratch |
| `skip: <agent>` | Skip next agent, proceed to the one after |
| `stop` | Halt pipeline, save progress to STM |
| `status` | Show current pipeline state and STM summary |

---

## Mid-Pipeline Data Requests

When an agent signals `PIPELINE_SIGNAL: NEED_DATA`:

1. Read the agent's TOPIC and REASON
2. Invoke `brain-data-retrieval` with the specific topic
3. Inject the retrieved data into the agent's context
4. Resume the agent from where it stopped

**Do not re-run the agent from scratch** — append the new data and let it continue.

---

## Pushback Routing

When an agent signals `PIPELINE_SIGNAL: PUSHBACK`:

1. Read the pushback details (TARGET, SEVERITY, ISSUE)
2. Construct a handoff to the target agent containing:
   - The original handoff they received
   - The pushback details
   - Instruction to revise their output
3. Re-invoke the target agent
4. When resolved (`PIPELINE_SIGNAL: RESOLVED`), resume from the agent that raised the pushback
