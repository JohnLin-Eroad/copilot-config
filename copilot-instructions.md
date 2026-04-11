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

## General Behaviour

- Always check `.github/copilot-instructions.md` in the current repo for project-specific instructions.
- Prefer surgical, minimal changes unless asked to do a broader refactor.
- When in doubt about scope, ask before implementing.
