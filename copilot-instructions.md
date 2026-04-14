# Copilot Global Instructions

These instructions apply to every session and every agent.

---

## Learnings System

### At the START of every task

1. Check if `.github/learnings.md` exists in the current repo root. If it does, **read it in full** before starting work — it contains repo-specific patterns, gotchas, and past decisions that are directly relevant.
2. Check `~/.copilot/learnings.md` for any global learnings that may apply to the task at hand.

### At the END of every task

After completing a task, reflect on what was learned and write any meaningful insights using the script below. Be selective — only write learnings that would genuinely help future sessions.

**What counts as a learning:**
- A non-obvious pattern discovered in this codebase
- A gotcha, edge case, or footgun that wasn't obvious upfront
- A tool, command, or workflow that worked particularly well (or badly)
- A convention or standard unique to this repo or team
- A decision rationale that isn't captured elsewhere

**What does NOT count:**
- Things that are obvious from the code itself
- Restatements of what the task was
- Generic programming knowledge

### How to write a learning

Use the script:

```bash
# Repo-specific learning (must be run inside the git repo)
bash ~/.copilot/scripts/add-learning.sh --local "The auth service uses RS256 JWT — do not use HS256"

# Cross-repo / general learning
bash ~/.copilot/scripts/add-learning.sh --global "John prefers explicit error messages over silent fallbacks"

# Auto-detect (local if in a git repo, global otherwise)
bash ~/.copilot/scripts/add-learning.sh "Learned something worth remembering"
```

**Rule of thumb:** If the learning only makes sense in the context of this specific repo (its architecture, conventions, team decisions), use `--local`. If it applies broadly to how you should work with John or to general patterns, use `--global`.

### Creating .github/learnings.md

If a repo does not yet have `.github/learnings.md`, the script will create it automatically on first use. You do not need to create it manually.

---

## Sovereign Platform

John is building **Sovereign** — a local replica of EROAD's AI-governed transformation platform. Always be aware of this project when it's relevant.

### Key locations
- **Codebase**: `~/sovereign/` — Maven multi-module, Java 21, Spring Boot 3.4
- **Frontend**: `~/sovereign/web/` — Next.js 15 on `:3000`
- **API**: Spring Boot on `:8080`
- **Agent YAMLs**: `~/sovereign/api/web/src/main/resources/agents/`
- **Skills YAMLs**: `~/sovereign/api/web/src/main/resources/skills/`

### Starting services
```bash
# Infrastructure (LocalStack SQS/S3 + PostgreSQL)
cd ~/sovereign && docker compose up -d

# API (Java 21 required)
source ~/.sdkman/bin/sdkman-init.sh && sdk use java 21.0.7-zulu
cd ~/sovereign/api && mvn -pl web spring-boot:run > /tmp/sovereign-api.log 2>&1 &

# Frontend
cd ~/sovereign/web && npm run dev > /tmp/sovereign-web.log 2>&1 &
```

### Checking health
```bash
curl -s http://localhost:8080/health       # API
curl -s http://localhost:8080/roles        # agent roles
open http://localhost:3000                 # Web UI
```

### Architecture rule
The project uses strict hexagonal architecture. **Domain must never import Infrastructure.**
Module dependency order: `domain` ← `application` ← `infrastructure` ← `web`

### Copilot Agents
All agents live in `~/.copilot/agents/` (no `sov-` prefix). Specialist agents include:
`architect`, `developer`, `security`, `testing`, `devops`, `discovery`, `governance`,
`orchestrator`, `code-reviewer`, `documentation`, `product-owner`, `scrum-master`,
`compliance`, `integration`, `performance`, `data-migration`, `critical-thinker`,
`product-manager`, `qa-engineer`, `senior-software-engineer`, `ai-master`,
`brain-data-retrieval`, `brain-consolidation`, `brain-repo-sync`, `agent-factory`

**ERD agents**: `erd-strategy`, `erd-product`, `erd-engineering`, `erd-customer`, `erd-finance`,
`erd-hr`, `erd-operations`, `erd-data`, `erd-marketing`, `erd-executive`

---

## Orchestrator Pipeline

For **EROAD code tasks** (any task involving code changes, architecture decisions, or engineering work in an EROAD repository or the Sovereign platform), route through the orchestrator pipeline:

```
brain-data-retrieval → [specialist agents] → brain-consolidation
```

**Invoke the orchestrator when the task:**
- Involves writing or changing code in an EROAD repo (eroad/, sovereign/, or any `github.com/eroad/*` repo)
- Involves writing or changing code in the Sovereign platform (`~/sovereign/`)
- Requires an architectural decision or ADR
- Touches EROAD infrastructure, CI/CD, or deployments

**Do NOT invoke the orchestrator for:**
- General coding questions unrelated to EROAD (e.g. "how does X work in Python")
- Personal/non-work projects outside the eroad org
- Quick lookups, explanations, or questions that don't result in code changes

**How to trigger:** John will say *"orchestrator:"* at the start of a message, or otherwise make clear it's an EROAD engineering task. When in doubt, ask.

---

## General Behaviour

- Always check `.github/copilot-instructions.md` in the current repo for project-specific instructions.
- Prefer surgical, minimal changes unless asked to do a broader refactor.
- When in doubt about scope, ask before implementing.
