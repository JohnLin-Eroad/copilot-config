# Copilot Global Learnings

Cross-repo patterns, preferences, and lessons learned — applied to all sessions.

---

- **[2026-04-11]** Skills MUST have YAML frontmatter (`name:` + `description:`) at the top of SKILL.md — without it, Copilot silently ignores the skill and it won't appear in the available skills list
- **[2026-04-11]** `--allow-tool shell` auto-approves ALL shell commands including destructive ones like `rm -rf` — too broad; John prefers to be prompted for shell commands individually
- **[2026-04-11]** Hook `permissionDecision` only supports `"deny"` — `"ask"` is defined in spec but not yet implemented; hooks can hard-block but cannot escalate to the user for approval
- **[2026-04-11]** `~/copilot-config` is the source of truth for all Copilot config; `~/.copilot/` is the deployed copy — changes to `~/copilot-config` must be copied or run via `setup.sh` to take effect
- **[2026-04-11]** John prefers explicit error messages over silent fallbacks
- **[2026-04-11]** John prefers security over convenience — when in doubt about auto-approving a broad permission, remove it and let the CLI prompt instead
- **[2026-04-11]** Local repo learnings live in `<repo>/.github/learnings.md`; global cross-repo learnings live in `~/.copilot/learnings.md` — use `add-learning.sh --local` or `--global` to write them
- **[2026-04-11]** Primary stack is Java/Spring Boot (backend) and React/TypeScript (frontend); EROAD is the organisation context
- **[2026-04-13]** Preferred pipeline for Jira implementation tasks: 1) Use the developer agent — have it fetch the Jira ticket via MCP, analyse the codebase, and produce a plan for user review before touching any code. 2) Before starting any coding, verify the Jira ticket has story points and other required fields filled in — if missing, prompt the user to fill them in, then use Atlassian MCP to transition the ticket to "In Progress". 3) Once plan is approved, developer agent implements changes locally. 4) Pass to QA agent if needed — QA should interrogate both the developer agent and the user on implementation details before signing off. 5) Once developer + QA are happy, push to a branch named after the Jira ticket number and open a PR. 6) Ask the user who to include as reviewers, but also recommend contributors who have recently touched the relevant code. 7) After the PR is created, use Atlassian MCP to transition the Jira ticket to "Code Review".
- **[2026-04-13]** Developer and QA agents should invoke the critical-thinker skill when making non-trivial decisions (type choices, schema design, API contracts, test coverage). Also: at the end of every session, scan the session learnings and update the critical-thinker SKILL.md if any generalizable critical-thinking patterns were discovered.
- **[2026-04-21]** `~/copilot-config` default branch is **`master`** not `main` — scripts doing `git push origin main` will fail. Auto-detect: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "master"`.
- **[2026-04-21]** The benchmark-runner agent computes traces and results entirely in-context — it **cannot write those files to disk itself**. The calling environment must capture and persist the output.
- **[2026-04-21]** Unstick escalation protocol is now standard for all 38 agents: 3x same failure OR 5+ calls no progress → `PIPELINE_SIGNAL: STUCK` → spawn `task` with `model: claude-opus-4.6` → concrete alternative → graceful stop. Every agent needs `task` in its tools list.
