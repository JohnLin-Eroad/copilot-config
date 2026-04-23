# Copilot System Architecture Index

> **Last updated:** 2026-04-24  
> **Purpose:** Complete reference map of the copilot agent system — directories, components, data flows, and context budget.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Directory Layout](#directory-layout)
3. [Data Flow: Config Sync](#data-flow-config-sync)
4. [Agent Catalogue (43)](#agent-catalogue-43)
5. [Skill Catalogue (13)](#skill-catalogue-13)
6. [Script Catalogue (31)](#script-catalogue-31)
7. [Global Instructions Breakdown](#global-instructions-breakdown)
8. [Governance Rules (14)](#governance-rules-14)
9. [MCP Servers (7)](#mcp-servers-7)
10. [LaunchAgents (5)](#launchagents-5)
11. [Brain Vaults](#brain-vaults)
12. [Short-Term Memory (STM) System](#short-term-memory-stm-system)
13. [Session Infrastructure](#session-infrastructure)
14. [Context Budget Analysis](#context-budget-analysis)
15. [File Drift Report](#file-drift-report)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User (John)                                  │
│                            │                                        │
│                     gh copilot chat                                 │
│                            │                                        │
│                    ┌───────▼────────┐                               │
│                    │  CLI Agent     │ ◄── copilot-instructions.md   │
│                    │  (Orchestrator)│     (34KB, loaded every       │
│                    └───────┬────────┘      session)                 │
│                            │                                        │
│         ┌──────────────────┼──────────────────┐                     │
│         ▼                  ▼                  ▼                     │
│   ┌───────────┐    ┌───────────┐    ┌───────────────┐              │
│   │ Specialist │    │   Skills  │    │  MCP Servers  │              │
│   │  Agents   │    │  (13)     │    │  (7 external) │              │
│   │  (43)     │    └───────────┘    └───────────────┘              │
│   └─────┬─────┘          │                  │                       │
│         │                │         Atlassian │ Microsoft 365         │
│         ▼                ▼         Notion    │ Figma │ Slack        │
│   ┌───────────┐    ┌───────────┐                                    │
│   │  Scripts  │    │  Brain    │                                     │
│   │  (31)     │    │  Vaults   │                                    │
│   └───────────┘    │  (2)     │                                     │
│                    └───────────┘                                     │
│                                                                      │
│   ┌──────────────────────────────────────────────────┐              │
│   │  Background Services (5 LaunchAgents)            │              │
│   │  • Config file watcher (always-on)               │              │
│   │  • Agent dashboard server (always-on)            │              │
│   │  • AI learner (weekly)                           │              │
│   │  • Weekly experimenter (weekly)                  │              │
│   │  • Benchmark runner (weekly)                     │              │
│   └──────────────────────────────────────────────────┘              │
│                                                                      │
│   ┌──────────────────────────────────────────────────┐              │
│   │  Governance Layer                                │              │
│   │  • security-check.sh hook (every tool call)      │              │
│   │  • governance-rules.json (14 rules)              │              │
│   │  • Audit log → ~/.copilot/logs/audit.jsonl       │              │
│   └──────────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Layout

The system spans two main directories plus two brain vaults:

### `~/copilot-config/` — Git-tracked source of truth

This is a **git repository** pushed to GitHub. Contains the canonical versions of all configuration. Secrets are redacted before commit.

```
copilot-config/
├── ARCHITECTURE.md              ← this file
├── README.md                    ← repo README (233 lines)
├── copilot-instructions.md      ← global agent instructions (678 lines, 34KB)
├── governance-rules.json        ← 14 governance rules (4KB)
├── mcp-config.json              ← MCP server config (secrets redacted)
├── learnings.md                 ← seed learnings (16 lines — see drift note)
├── setup.sh                     ← bootstrap: copies config → ~/.copilot
├── agents/                      ← 43 agent definitions (286KB total)
├── skills/                      ← 13 skill directories (85KB total)
├── scripts/                     ← 19 scripts (278KB total)
├── hooks/
│   └── security-check.sh       ← preToolUse governance hook
├── benchmarks/                  ← benchmark system
│   ├── README.md
│   ├── baseline.json
│   ├── tasks/                  ← task definitions
│   ├── results/                ← weekly JSON results
│   ├── reports/                ← weekly markdown reports
│   ├── traces/                 ← execution traces
│   ├── prompts/                ← benchmark prompts
│   └── usage/                  ← usage tracking
├── experiments/                 ← weekly experiment logs
│   └── 2026-W17.md
├── plans/                       ← long-lived plans
│   └── parallel-decomposition-v3-final.md
├── brain/
│   └── brain.py                ← brain vault helper
├── harness-candidates/          ← benchmark harness candidates
└── *.plist                      ← 5 macOS LaunchAgent definitions
```

### `~/.copilot/` — Runtime directory (not git-tracked)

Contains live config with real secrets, runtime state, and files generated during sessions. **This is what Copilot actually reads.**

```
.copilot/
├── copilot-instructions.md      ← live instructions (659 lines, 32KB)
├── config.json                  ← Copilot CLI config (hooks registration)
├── mcp-config.json              ← MCP config (with real secrets)
├── learnings.md                 ← live learnings (399 lines — grows over time)
├── agents/                      ← 43 agent definitions (mirror of copilot-config)
├── skills/                      ← 13 skills (mirror)
├── scripts/                     ← 31 scripts (19 mirrored + 12 runtime-only)
├── hooks/
│   └── security-check.sh
├── logs/
│   └── audit.jsonl              ← governance audit trail
├── stm/                         ← Short-Term Memory dirs (38 active)
│   └── .active → <symlink>     ← points to current active STM
├── stm-archive/                 ← archived STMs (4)
├── session-state/               ← Copilot CLI session folders (61)
├── state/                       ← persistent state (empty)
├── templates/                   ← agent templates (1 file)
│   └── developer-parallel.md
├── mcp-oauth-config/            ← OAuth configs for MCP servers
├── notion-vault-state.json      ← Notion sync state
├── command-history-state.json   ← command history
├── ide/                         ← IDE integration
├── jb/                          ← JetBrains integration
├── restart/                     ← restart markers
└── run/                         ← runtime files
```

### `~/eroad-brain/` — EROAD knowledge vault (Obsidian)

```
eroad-brain/                     ← 29MB, 823 markdown files
├── 01 - Services/               ← EROAD service documentation
├── 02 - Domain Models/          ← domain entity maps
├── 03 - Architecture/           ← architecture decisions
├── 04 - Decisions/              ← ADRs
├── 06 - AI Agent Outputs/       ← outputs from agent runs
└── Brain/                       ← meta/config
```

### `~/john-brain/` — Personal knowledge vault (Obsidian)

```
john-brain/                      ← 1.5MB, 54 markdown files
├── 06 - AI Agent Outputs/
├── Research/
├── Learnings/
├── Sessions/
├── clusters/
└── index.md
```

---

## Data Flow: Config Sync

```
┌──────────────────┐    setup.sh (one-time)     ┌──────────────────┐
│  ~/copilot-config │ ──────────────────────────► │    ~/.copilot    │
│  (git repo)       │                             │  (runtime)       │
│                   │ ◄────────────────────────── │                  │
│                   │    sync-config.py           │                  │
│                   │    (on file change via      │                  │
│                   │     fswatch LaunchAgent)    │                  │
└──────────────────┘                              └──────────────────┘
```

**`setup.sh`** — one-time bootstrap. Copies agents, skills, scripts, hooks, instructions, and learnings from `copilot-config` → `.copilot`. Only overwrites if files don't exist (preserves live learnings).

**`sync-config.py`** — triggered by `fswatch` whenever files change in `~/.copilot/agents/`, `~/.copilot/skills/`, `~/.copilot/scripts/`, or `~/.copilot/mcp-config.json`. Redacts secrets, copies changes back to `copilot-config`, commits, and pushes to GitHub.

**Direction:** Edits during sessions go into `.copilot` → sync-config.py pushes them to `copilot-config`. Manual edits to `copilot-config` require re-running `setup.sh` to propagate to `.copilot`.

---

## Agent Catalogue (43)

### Summary

| Category | Count | Total Size |
|---|---|---|
| Pipeline / Orchestration | 5 | 79KB |
| Brain / Knowledge | 3 | 36KB |
| Engineering (core) | 10 | 56KB |
| EROAD Domain (ERD-*) | 10 | 36KB |
| Governance / Review | 5 | 27KB |
| Automation / Scheduled | 3 | 33KB |
| Product / Delivery | 4 | 18KB |
| Meta / Factory | 3 | 37KB |
| **Total** | **43** | **286KB** |

### Full Agent List (sorted by size descending)

| Agent | Category | Lines | Size | Description |
|---|---|---|---|---|
| `orchestrator` | Pipeline | 663 | 30KB | Top-level pipeline manager |
| `ai-master` | Meta | 368 | 24KB | AI/LLM strategy and tooling expert |
| `benchmark-runner` | Automation | 547 | 16KB | Weekly benchmark suite runner |
| `brain-data-retrieval` | Brain | 416 | 14KB | Fetches brain data into STM |
| `brain-consolidation` | Brain | 357 | 12KB | Writes session learnings back to brain |
| `brain-repo-sync` | Brain | 320 | 10KB | Nightly scan of EROAD GitHub repos |
| `security` | Governance | 234 | 9KB | OWASP, secrets, auth review |
| `weekly-experimenter` | Automation | 274 | 9KB | Weekly experiment branch creator |
| `ai-learner` | Automation | 255 | 9KB | Weekly AI research scanner |
| `developer` | Engineering | 203 | 8KB | Java/Spring Boot implementation |
| `senior-software-engineer` | Meta | 113 | 7KB | General deep-dive engineering |
| `migration-validator` | Governance | 173 | 7KB | DB migration safety checker |
| `architect` | Engineering | 158 | 6KB | ADRs, system design |
| `agent-factory` | Meta | 206 | 6KB | Creates new agents on demand |
| `discovery` | Engineering | 171 | 6KB | Codebase exploration |
| `qa-engineer` | Engineering | 165 | 6KB | Integration + E2E tests |
| `dependency-tracker` | Engineering | 165 | 6KB | Cross-service dependency maps |
| `code-reviewer` | Governance | 154 | 6KB | High-signal code review |
| `pr-analyst` | Governance | 154 | 6KB | PR triage and review queue |
| `retrospective` | Product | 158 | 5KB | Sprint/week retrospectives |
| `product-manager` | Product | 156 | 5KB | Specs, stories, Jira tickets |
| `testing` | Engineering | 154 | 5KB | Test plans, integration tests |
| `tech-lead` | Engineering | 120 | 5KB | Work decomposition for developers |
| `governance` | Governance | 144 | 5KB | Platform governance engine |
| `devops` | Engineering | 149 | 4KB | CI/CD, Docker, infrastructure |
| `data-migration` | Engineering | 136 | 4KB | Schema migrations, rollbacks |
| `performance` | Engineering | 133 | 4KB | Bottleneck profiling |
| `critical-thinker` | Engineering | 116 | 4KB | Plan/proposal evaluation |
| `compliance` | Engineering | 126 | 4KB | Regulatory compliance |
| `integration` | Engineering | 146 | 4KB | API contracts, event flows |
| `erd-customer` | ERD | 110 | 4KB | Customer voice / feedback |
| `documentation` | Product | 132 | 4KB | Technical docs, ADRs |
| `erd-data` | ERD | 118 | 4KB | Data architecture / governance |
| `product-owner` | Product | 119 | 4KB | Acceptance criteria validation |
| `erd-executive` | ERD | 116 | 4KB | C-suite / board perspective |
| `erd-marketing` | ERD | 107 | 4KB | Go-to-market alignment |
| `erd-strategy` | ERD | 112 | 4KB | Business strategy translation |
| `erd-hr` | ERD | 108 | 4KB | Workforce / change management |
| `erd-engineering` | ERD | 114 | 4KB | Engineering feasibility |
| `scrum-master` | Product | 132 | 4KB | Sprint ceremonies, backlog |
| `erd-finance` | ERD | 116 | 3KB | Cost-benefit analysis |
| `erd-operations` | ERD | 116 | 3KB | SLA / reliability |
| `erd-product` | ERD | 112 | 3KB | Product requirements |

---

## Skill Catalogue (13)

Skills are reusable instruction sets loaded via the `skill` tool. Each is a directory containing a SKILL.md.

| Skill | Lines | Size | Trigger Condition |
|---|---|---|---|
| `html-report` | 749 | 19KB | After research/analysis for visual summary |
| `handoff-protocol` | 286 | 8KB | Agent-to-agent pipeline handoffs |
| `brain-sync` | 258 | 8KB | Start of every task touching code |
| `session-summary` | 197 | 6KB | Session end or manual save |
| `context-compression` | 194 | 6KB | STM exceeds 200KB / ~50k tokens |
| `advisor` | 130 | 6KB | Directional/strategic decisions |
| `rollback-plan` | 181 | 6KB | After MEDIUM+ blast radius assessment |
| `dual-critique` | 173 | 6KB | HIGH blast radius architecture decisions |
| `blast-radius` | 122 | 5KB | Before HIGH/CRITICAL changes |
| `tdd-workflow` | 116 | 4KB | Before writing implementation code |
| `critical-thinker` | 76 | 3KB | After drafting plans touching >2 files |
| `jira-confluence-sync` | 80 | 3KB | Any Jira/Confluence interaction |
| `unstick` | 91 | 3KB | Same action failing 3x or 5+ calls with no progress |

**Total skill size:** ~85KB across 13 skills

---

## Script Catalogue (31)

### In `copilot-config` (19 scripts — git-tracked, canonical)

| Script | Lines | Size | Purpose |
|---|---|---|---|
| `agent-dashboard.py` | 2,261 | 96KB | Live HTML dashboard for agent/STM visibility |
| `usage-dashboard.py` | 749 | 33KB | Usage statistics web dashboard |
| `stm-dashboard.py` | 1,010 | 32KB | STM-specific live dashboard |
| `usage-stats.py` | 505 | 19KB | Token/cost usage analytics |
| `summarize-session.py` | 408 | 15KB | Post-session summary generator |
| `extract-service-data.sh` | 321 | 14KB | Extract service data from repos |
| `extract-submodule-data.sh` | 282 | 13KB | Extract submodule data |
| `enrich-service-node.sh` | 279 | 12KB | Enrich brain service nodes |
| `stm-init.py` | 288 | 9KB | Create STM + open dashboard |
| `create-submodule-node.sh` | 190 | 7KB | Create brain submodule entries |
| `enrich-monorepo.sh` | 152 | 6KB | Enrich brain monorepo entries |
| `weekly-branch.sh` | 160 | 6KB | Create weekly experiment branches |
| `sync-config.py` | 140 | 4KB | Config auto-sync with secret redaction |
| `notify-weekly-results.sh` | 104 | 4KB | Notify on weekly results |
| `audit-view.sh` | 69 | 2KB | View governance audit log |
| `add-learning.sh` | 89 | 2KB | Add learnings to .md files |
| `ai-learner.sh` | 35 | 1KB | AI learner runner wrapper |
| `benchmark-runner.sh` | 25 | 1KB | Benchmark runner wrapper |
| `watch-config.sh` | 21 | 1KB | fswatch file watcher for config sync |

### In `.copilot` only (12 additional runtime scripts — not in git)

| Script | Lines | Size | Purpose |
|---|---|---|---|
| `decompose-task.sh` | 436 | 16KB | Task decomposition for tech-lead |
| `run-integration-lanes.sh` | 342 | 12KB | Parallel integration test lanes |
| `reconcile.sh` | 276 | 11KB | Reconciliation checks |
| `update-budget-ledger.sh` | 266 | 11KB | Token budget tracking |
| `write-stm.sh` | 157 | 6KB | Write entries to STM |
| `enrich-one-service.sh` | 117 | 5KB | Enrich single brain service |
| `brain-health-audit.sh` | 67 | 3KB | Brain vault health check |
| `read-stm-state.sh` | 64 | 3KB | Read current STM state |
| `harness-snapshot.sh` | 55 | 2KB | Benchmark harness snapshots |
| `brain-repo-sync.sh` | 29 | 1KB | Brain repo sync wrapper |
| `check-stm-size.sh` | 36 | 1KB | Check STM file size |
| `brain-git-push.sh` | 30 | 1KB | Push brain vault to git |

---

## Global Instructions Breakdown

The file `copilot-instructions.md` is loaded into **every session** as part of the system prompt. This is the single largest per-session context cost.

### copilot-config version (678 lines, 34KB)

| Section | Lines | Size Est. | Content |
|---|---|---|---|
| Header + title | 1–6 | 6 lines | — |
| Thinking Depth & Reasoning Quality | 7–29 | 22 lines | Read-before-edit, plan-before-act rules |
| Autonomy Framework | 30–71 | 41 lines | Blast radius levels, proceed/ask rules |
| Iterative Learning System | 72–129 | 57 lines | Read/write learnings, brain consolidation |
| Governance | 130–171 | 41 lines | Rule summary table, audit trail, blast radius |
| STM-First Protocol | 172–218 | 46 lines | STM consumption rules, priority order |
| Context Engineering | 219–262 | 43 lines | 7 layers, 3 sub-skills, pre-flight check |
| Model Selection | 263–281 | 18 lines | Model routing table by task type |
| Test-First as Autonomy Enabler | 282–337 | 55 lines | Test coverage = autonomy multiplier |
| Orchestrator Pipeline | 338–464 | **126 lines** | Pipeline flow, brain routing, specialist table |
| When Stuck | 465–491 | 26 lines | Stuck detection, PIPELINE_SIGNAL, unstick |
| Know Your Limits | 492–524 | 32 lines | Jagged intelligence, bash for counting |
| Context Window Budget | 525–555 | 30 lines | STM size targets, compression thresholds |
| ACI Tool Documentation | 556–584 | 28 lines | Required tool doc format |
| Skill Dispatch Rules | 585–633 | 48 lines | When to invoke each skill |
| General Behaviour | 634–645 | 11 lines | Defaults and rules of thumb |
| Session End | 646–678 | 32 lines | Post-session syncs, auto-save |

### .copilot version (659 lines, 32KB)

Missing the **STM-First Protocol** section (46 lines) compared to the copilot-config version. All other sections present with minor line count differences.

---

## Governance Rules (14)

From `governance-rules.json`:

### Blocking Rules (BLOCK severity)

| ID | Name | Blast Radius | What it prevents |
|---|---|---|---|
| `sec-001` | No pipe-to-shell downloads | CRITICAL | `curl \| bash`, `wget \| sh` |
| `sec-002` | No credential exfiltration | CRITICAL | POST requests referencing local credentials |
| `sec-003` | No cloud metadata access | CRITICAL | `169.254.169.254` endpoint access |
| `sec-004` | No obfuscated shell expansion | CRITICAL | `${var@P}`, `${!var}` patterns |
| `gov-001` | Protect home directory | CRITICAL | `rm -rf ~` or `/Users/<user>` |
| `gov-002` | Protect critical directories | CRITICAL | Recursive delete of `.copilot`, `sovereign`, `copilot-config`, `eroad-brain`, `IdeaProjects` |
| `gov-003` | No force push | HIGH | `git push --force` |
| `gov-004` | No destructive DB operations | HIGH | `DROP TABLE`, `DROP DATABASE`, `TRUNCATE TABLE` |
| `gov-005` | No download to executable paths | HIGH | Download to `/bin`, `/usr/local/bin`, `.sh/.py` files |
| `gov-006` | No general-purpose fallback | — | `general-purpose` agent must not be routing fallback |

### Warning/Logging Rules

| ID | Name | Severity | What it logs |
|---|---|---|---|
| `sec-005` | Rate limit external APIs | WARN | >10 req/sec per domain |
| `sec-006` | Credential rotation reminder | WARN | Agent reads file containing API keys |
| `audit-001` | Log destructive file ops | LOG | `rm -rf` on non-critical paths |
| `audit-002` | Log all VCS writes | LOG | `git commit`, `push`, `rebase`, `reset` |
| `audit-003` | Log all DB queries | LOG | `psql`, `mysql`, `sqlite3` |
| `audit-004` | Log all file writes | LOG | `edit`/`create` tool calls |

---

## MCP Servers (7)

| Server | Protocol | Endpoint | Purpose |
|---|---|---|---|
| `atlassian` | npx mcp-remote | `https://mcp.atlassian.com/v1/mcp` | Jira + Confluence |
| `figma` | npx figma-mcp | local | Figma file access |
| `microsoft-teams` | HTTP | `agent365.svc.cloud.microsoft` | Teams messaging |
| `microsoft-mail` | HTTP | `agent365.svc.cloud.microsoft` | Outlook mail |
| `microsoft-calendar` | HTTP | `agent365.svc.cloud.microsoft` | Calendar + scheduling |
| `slack` | npx mcp-remote | `https://mcp.slack.com/mcp` | Slack messaging |
| `notion` | npx @notionhq/notion-mcp-server | local | Notion workspace |

**Note:** Microsoft servers all connect to the same tenant (`525d795f-...`). Figma and Notion use API tokens stored in `.copilot/mcp-config.json`.

---

## LaunchAgents (5)

macOS LaunchAgent plist files in `~/copilot-config/`, installed to `~/Library/LaunchAgents/`.

| LaunchAgent | Type | Schedule | What it runs |
|---|---|---|---|
| `com.johnlin.agent-dashboard` | KeepAlive | Always on | `agent-dashboard.py --port` — live HTML dashboard |
| `com.johnlin.copilot-config-sync` | KeepAlive | Always on | `watch-config.sh` — fswatch → sync-config.py |
| `com.johnlin.ai-learner` | Scheduled | Sun 09:00 | `ai-learner.sh` — weekly AI research scan |
| `com.johnlin.weekly-experimenter` | Scheduled | Mon 09:00 | `weekly-branch.sh` — weekly experiment branch |
| `com.johnlin.benchmark-runner` | Scheduled | Mon 09:00 | `benchmark-runner.sh` — weekly benchmark suite |

**Always-on (2):** Dashboard + config sync run continuously.  
**Weekly (3):** AI learner on Sunday, experimenter + benchmark on Monday morning.

---

## Brain Vaults

### `~/eroad-brain/` — EROAD domain knowledge

| Metric | Value |
|---|---|
| Size | 29 MB |
| Files | 823 markdown files |
| Structure | 01-Services / 02-Domain Models / 03-Architecture / 04-Decisions / 06-AI Agent Outputs |
| Updated by | `brain-consolidation` agent, `brain-repo-sync` agent |
| Used by | `brain-data-retrieval` agent, `brain-sync` skill |
| Pushed to | GitHub via `brain-git-push.sh` |

### `~/john-brain/` — Personal knowledge

| Metric | Value |
|---|---|
| Size | 1.5 MB |
| Files | 54 markdown files |
| Structure | Research / Learnings / Sessions / clusters / 06-AI Agent Outputs |
| Updated by | `brain-consolidation` agent (for personal/general tasks) |

### Brain routing rule

| Task domain | Brain used |
|---|---|
| EROAD services, Sovereign, company repos | `~/eroad-brain` |
| Copilot config, personal projects, AI learnings | `~/john-brain` |

---

## Short-Term Memory (STM) System

The STM is the per-task shared memory used by the orchestrator pipeline.

| Component | Location | Count |
|---|---|---|
| Active STMs | `~/.copilot/stm/` | 38 directories |
| Active symlink | `~/.copilot/stm/.active` | → current task |
| Archived STMs | `~/.copilot/stm-archive/` | 4 |

### STM lifecycle

1. **Created** by `stm-init.py` at task start
2. **Written to** by agents via `write-stm.sh`
3. **Read** by subsequent agents (STM-First Protocol)
4. **Monitored** by `stm-dashboard.py` (live HTML view)
5. **Size-checked** by `check-stm-size.sh` (target: <200KB)
6. **Compressed** by `context-compression` skill when >50k tokens
7. **Archived** to `stm-archive/` when no longer active

### STM structure (typical)

```
stm/<task-slug>/
├── TASK_CONTEXT.md          ← main STM file
└── (agent output files)
```

### Key STM sections

| Section | Purpose |
|---|---|
| Task Brief | Classification, restrictions, scope |
| Brain Data | Pre-fetched domain knowledge |
| Negative Context | Topics NOT in the brain — prevents hallucination |
| Agent Contributions | Prior agent outputs |
| Fetch Manifest | Files already retrieved |

---

## Session Infrastructure

| Component | Location | Count |
|---|---|---|
| Session state | `~/.copilot/session-state/` | 61 directories |
| Session summaries | Written by `summarize-session.py` to copilot-sessions Obsidian vault |
| Learnings (global) | `~/.copilot/learnings.md` | 399 lines |
| Learnings (per-repo) | `<repo>/.github/learnings.md` | varies |
| Templates | `~/.copilot/templates/` | 1 file |

---

## Context Budget Analysis

### What gets loaded every session

| Item | Size | Token Est. | Notes |
|---|---|---|---|
| `copilot-instructions.md` | 32KB | ~8,000 | Loaded as custom instructions |
| Copilot CLI system prompt | ~12KB | ~3,000 | Built-in (not configurable) |
| MCP tool schemas | ~30KB | ~7,500 | All 7 MCP servers' tool definitions |
| Agent tool schema | ~5KB | ~1,200 | Task/agent spawning tool |
| Built-in tool schemas | ~5KB | ~1,200 | grep, glob, view, edit, bash, etc. |
| **Base session context** | **~84KB** | **~21,000** | Before any task-specific content |

### What gets loaded per agent spawn

| Item | Size | Token Est. | Notes |
|---|---|---|---|
| Agent definition | 3–30KB | 800–7,500 | Varies by agent |
| STM content (if pipeline) | 0–200KB | 0–50,000 | Target <50k tokens |
| Brain data (fetched) | 0–50KB | 0–12,500 | Relevance-filtered |
| Skill (if invoked) | 3–19KB | 800–5,000 | Loaded on demand |

### Largest per-session context consumers (fixed cost)

1. `copilot-instructions.md` — 32KB (~8,000 tokens)
2. MCP tool schemas — ~30KB (~7,500 tokens)
3. Copilot CLI system prompt — ~12KB (~3,000 tokens)

---

## File Drift Report

Areas where `copilot-config` and `~/.copilot` have diverged:

### Instructions divergence

| File | copilot-config | .copilot | Delta |
|---|---|---|---|
| `copilot-instructions.md` | 678 lines (34KB) | 659 lines (32KB) | copilot-config has `STM-First Protocol` section (46 lines) not present in .copilot |

### Scripts not synced to copilot-config

12 scripts exist in `.copilot/scripts/` but not in `copilot-config/scripts/`:

| Script | Lines | Purpose |
|---|---|---|
| `decompose-task.sh` | 436 | Task decomposition |
| `run-integration-lanes.sh` | 342 | Parallel integration tests |
| `reconcile.sh` | 276 | Reconciliation checks |
| `update-budget-ledger.sh` | 266 | Token budget tracking |
| `write-stm.sh` | 157 | Write to STM |
| `enrich-one-service.sh` | 117 | Brain enrichment |
| `brain-health-audit.sh` | 67 | Brain health check |
| `read-stm-state.sh` | 64 | Read STM |
| `harness-snapshot.sh` | 55 | Benchmark harness |
| `brain-repo-sync.sh` | 29 | Brain sync wrapper |
| `check-stm-size.sh` | 36 | STM size check |
| `brain-git-push.sh` | 30 | Brain git push |

### Learnings divergence

| File | copilot-config | .copilot | Note |
|---|---|---|---|
| `learnings.md` | 16 lines | 399 lines | sync-config.py does not sync learnings back to repo |

### Backup files in .copilot only

- `copilot-instructions.md.bak`
- `scripts/agent-dashboard.py.bak`
- `scripts/stm-init.py.bak`

---

*Generated by Copilot CLI session. To regenerate, run the audit task described in the plan.*
