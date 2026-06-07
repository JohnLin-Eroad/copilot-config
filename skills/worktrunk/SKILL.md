---
name: worktrunk
description: >
  Use `wt` (Worktrunk) to manage Git worktrees for parallel work — especially
  for running multiple agent sessions, experiments, or branches concurrently
  without stomping on each other. Invoke whenever a task requires isolation
  from the current working tree, or when the user mentions worktree, parallel
  agents, stacked branches, or running multiple variants side-by-side.
---

# Skill: Worktrunk (`wt`)

## Purpose

[Worktrunk](https://worktrunk.dev) (`wt`) is a Git worktree manager built for **trunk-based development and parallel AI agent workflows**. It removes the friction of `git worktree` so you can spin up an isolated checkout per branch/experiment/agent in seconds, then clean up just as fast.

Use this skill whenever you need to:
- Run multiple agents or experiments **in parallel** on different branches without polluting the main checkout
- Isolate a risky refactor or migration in its own working tree
- Hop between feature branches without stashing/rebuilding
- Stack branches off trunk and merge them back cleanly

---

## When to Trigger

Trigger this skill when **any** of these are true:
- The user says "worktree", "wt", "worktrunk", "spin up a branch", "parallel agents", "stacked branches", or "run X in isolation"
- You're about to launch a background agent that will edit files in a repo that another agent (or the user) is also working in — use a worktree so they don't collide
- A task involves trying multiple variants of the same change (A/B experimentation)
- A long-running migration or refactor needs to proceed alongside normal work on `main`

Do **not** trigger if:
- The user just wants a normal `git checkout` on the current tree
- The repo doesn't exist yet (run `git init` / `git clone` first)

---

## Installation Check

Worktrunk is installed via Homebrew:

```bash
brew install worktrunk     # binary name is `wt`
wt --version               # verify
```

First-time setup on a machine (enables `cd`-on-switch and shell completions):

```bash
wt config shell install
```

If `wt` is missing, install it before continuing.

---

## Core Commands

| Command | What it does |
|---|---|
| `wt switch <branch>` | Switch to (or create) a worktree for `<branch>` |
| `wt switch --create <branch>` | Create a new branch + worktree off the default branch |
| `wt switch --create <branch> --base <base>` | Branch off `<base>` instead of trunk |
| `wt switch -x <cmd> --create <branch>` | Create worktree then launch `<cmd>` inside it (great for `claude`, `code`, `tmux`) |
| `wt list` | Show all worktrees + their status |
| `wt list --format json` | Machine-readable listing — parse this in scripts |
| `wt remove` | Remove the current worktree; auto-deletes branch if merged |
| `wt remove <branch>` | Remove a specific worktree |
| `wt remove -D <branch>` | Force-remove (drops unmerged branch) |
| `wt merge` | Squash + rebase current branch into trunk, fast-forward, remove the worktree |
| `wt merge <target>` | Merge into `<target>` instead of trunk |

Shortcuts accepted by `switch` / `--base`:
- `^` — default branch (e.g. `main`)
- `-` — previous worktree
- `@` — current branch
- `pr:123` — GitHub PR #123
- `mr:123` — GitLab MR #123

---

## How to Use

### Pattern 1 — Isolate a single task

```bash
cd /path/to/repo
wt switch --create fix/login-bug      # new worktree at ../repo-fix-login-bug
# ...do work, commit...
wt merge                              # squash + fast-forward into trunk, clean up
```

### Pattern 2 — Parallel agents on the same repo

When launching a background agent that will edit files, give it its own worktree so it can't collide with your foreground work:

```bash
wt switch --create agent/refactor-auth -x claude -- 'Refactor auth module per spec'
```

The agent runs inside its own checkout. You keep editing trunk in the original tree.

### Pattern 3 — Try multiple variants

```bash
wt switch --create experiment/approach-a
# implement approach A
wt switch --create experiment/approach-b --base ^
# implement approach B
wt list                               # compare; keep the winner, `wt remove -D` the rest
```

### Pattern 4 — Review a PR locally

```bash
wt switch pr:482                      # checks out PR #482 in its own worktree
# inspect, run tests
wt remove                             # done
```

---

## Discovery Workflow (when unsure of repo state)

```bash
wt list --format json                 # see existing worktrees + branches
git -C <path> status --porcelain      # check dirty state of a specific worktree
```

Use `wt list` *before* creating a new worktree to avoid duplicates.

---

## Cleanup Discipline

Worktrees accumulate. After a session:

```bash
wt list                               # audit
wt remove <branch>                    # remove merged work
wt remove -D <branch>                 # discard abandoned experiments
```

Default behaviour: `wt remove` deletes the branch **only if it's been merged**. Use `--no-delete-branch` to keep the branch, `-D` to force-delete unmerged work.

---

## Gotchas

- **Worktrees live as sibling directories** (e.g. `../repo-<branch>` by default). Don't `cd ..; rm -rf` blindly — use `wt remove`.
- **Shell integration is required for `cd`-on-switch** — if `wt switch` doesn't change your directory, run `wt config shell install` and restart your shell.
- **`wt merge` rewrites history** (squash + rebase). Don't run it on branches that others have pulled.
- **Hooks** (`wt hook`) can run automatically on switch/create/remove — check `wt config` for what's configured before running in a new repo.
- The CLI is `wt`, the project is `worktrunk`, the Homebrew formula is `worktrunk`. Don't confuse them.

---

## Output Contract

After using `wt` in a task, briefly report:

```
## Worktrunk Actions
- Created worktree: <branch> at <path>
- Switched to: <branch>
- Removed: <branch> (merged: yes/no)
- Remaining worktrees: <count> (run `wt list` to inspect)
```

---

## Comparison

| Tool / Skill | Use when |
|---|---|
| `worktrunk` (this skill) | You need isolated parallel checkouts of the same repo |
| Plain `git checkout` | Single-tree, sequential work |
| `git worktree` directly | You want full manual control (worktrunk wraps this with sensible defaults) |
| `tdd-workflow` | Inside a worktree, when implementing a feature test-first |
| `blast-radius` | Before merging a worktree back into trunk if the change is HIGH/CRITICAL |
