# copilot-config

Personal GitHub Copilot CLI configuration — agents, skills, MCP servers, and session tooling.

## Structure

```
copilot-config/
├── agents/          # Custom specialist agents (.agent.md)
├── skills/          # Reusable skills (brain-sync, session-summary, etc.)
├── scripts/
│   └── summarize-session.py   # Auto-saves session logs to Obsidian + Notion
├── mcp-config.json  # MCP server connections (secrets redacted)
├── setup.sh         # Bootstrap script
└── README.md
```

## MCP Servers

| Server | Purpose |
|---|---|
| `atlassian` | Jira + Confluence via mcp-remote |
| `figma` | Figma file access |
| `microsoft-teams` | Teams messaging |
| `microsoft-mail` | Outlook mail |
| `microsoft-calendar` | Calendar + scheduling |
| `notion` | Notion workspace read/write |

## Agents

| Agent | Role |
|---|---|
| `orchestrator` | Top-level pipeline manager |
| `product-manager` | Specs, Jira tickets, acceptance criteria |
| `architect` | ADRs, system design, API contracts |
| `developer` | Java/Spring Boot + React/TypeScript implementation |
| `security` | OWASP reviews, secrets, auth |
| `qa-engineer` | Integration + E2E tests |
| `devops` | CI/CD, Docker, Terraform |
| `code-reviewer` | Final high-signal code review |
| `agent-factory` | Creates new agents on demand |
| `ai-master` | AI/LLM strategy and tooling |
| `senior-software-engineer` | General deep-dive engineering |

## Skills

| Skill | Purpose |
|---|---|
| `brain-sync` | Read/write Obsidian Brain vault |
| `session-summary` | Save session logs to copilot-sessions vault |
| `handoff-protocol` | Agent-to-agent context handoff via TASK_CONTEXT.md |
| `jira-confluence-sync` | Create/update Jira + Confluence via MCP |
| `critical-thinker` | Balanced critical evaluation of plans, proposals, and decisions |

## Learnings System

Agents automatically capture lessons learned during each task.

| File | Scope |
|---|---|
| `~/.copilot/learnings.md` | Global — cross-repo patterns, preferences, gotchas |
| `<repo>/.github/learnings.md` | Local — repo-specific findings (created on first use) |

At task start, agents read both files for context. At task end, they write new learnings using `add-learning.sh`:

```bash
# Write a global learning
~/.copilot/scripts/add-learning.sh --global "message"

# Write a local learning (must be inside a git repo)
~/.copilot/scripts/add-learning.sh --local "message"

# Auto-detect (local if in git repo, else global)
~/.copilot/scripts/add-learning.sh "message"
```

Instructions for agents are in `~/.copilot/copilot-instructions.md` (auto-loaded each session).


A `preToolUse` security hook fires before every tool call, blocking high-risk patterns and writing an audit log to `~/.copilot/logs/security-audit.jsonl`.

| Pattern | Action |
|---|---|
| `curl \| bash`, `wget \| sh` (pipe-to-shell) | 🚫 Denied |
| POST request referencing local credentials / config | 🚫 Denied |
| Cloud metadata endpoint (`169.254.169.254`) | 🚫 Denied |
| Download to executable/system path | 🚫 Denied |
| Internal network access via web-fetch | 🚫 Denied |
| `curl`/`wget` GET, `npm install`, `pip install`, `git clone`, etc. | ✅ Allowed + audited |

Hook is registered in `~/.copilot/config.json` under the `hooks.preToolUse` key.

## Config File Watcher

A macOS LaunchAgent (`com.johnlin.copilot-config-sync`) runs `fswatch` in the background and automatically syncs config changes to GitHub — no need to wait for a chat session to close.

**Watched paths:**
- `~/.copilot/agents/`
- `~/.copilot/skills/`
- `~/.copilot/scripts/`
- `~/.copilot/mcp-config.json`

Any change to these files triggers `sync-config.py` with a 2-second debounce.

**Logs:** `~/.copilot/logs/watch-config.log`

**Manual control:**
```bash
# Check status
launchctl list | grep copilot-config-sync

# Restart
launchctl unload ~/Library/LaunchAgents/com.johnlin.copilot-config-sync.plist
launchctl load ~/Library/LaunchAgents/com.johnlin.copilot-config-sync.plist
```

**Prerequisite:** `brew install fswatch`

---

## Session Summariser

After every `copilot chat` session, `summarize-session.py` automatically:
- Saves a Markdown session log to the Obsidian `copilot-sessions` vault
- Links notes chronologically (← prev / → next)
- Syncs extracted learnings (bullet points) to Notion vault, deduplicating against existing content

### zsh wrapper (add to `~/.zshrc`)

```zsh
copilot() {
  gh copilot "$@"

  # Only summarise after a chat session
  if [[ "$1" == "chat" ]]; then
    python3 ~/.copilot/scripts/summarize-session.py 2>/dev/null \
      && echo "✅ Session saved to copilot-sessions vault" \
      || echo "⚠️  Session save failed (check ~/.copilot/scripts/summarize-session.py)"
  fi
}
```

## Setup

```bash
git clone <this-repo> ~/copilot-config
cd ~/copilot-config
chmod +x setup.sh
./setup.sh
```

Then fill in secrets in `~/.copilot/mcp-config.json` and `~/.copilot/scripts/summarize-session.py`.

## Secrets

Never commit real tokens. All secrets in `mcp-config.json` and `summarize-session.py` use `YOUR_*` placeholders. Store real values only in `~/.copilot/` (which is not tracked by git).
