---
name: tdd-workflow
description: >
  Enforces test-first development by generating failing test stubs from acceptance
  criteria before any implementation code is written. Guides the agent through the
  Red → Green → Refactor cycle. Use whenever a developer or qa-engineer is about to
  write implementation code and acceptance criteria exist.
---

# Skill: TDD Workflow

## Purpose

Enforce the **Red → Green → Refactor** cycle. No implementation code is written until a failing test exists that justifies it. This skill prevents test-after habits, ensures coverage is driven by requirements, and produces tests that are provably meaningful (they failed before the code existed).

---

## When to Trigger

Trigger this skill when **any** of these are true:
- A `developer` or `qa-engineer` agent is about to write implementation code **and** acceptance criteria exist in the spec
- The user says "write this test-first", "use TDD", or "red-green-refactor"
- A feature has a product spec with numbered acceptance criteria and no tests yet exist
- A bug fix needs a regression test before the fix is applied

Do **not** trigger if:
- Only infrastructure, config, or migration files are being written (no behaviour to assert)
- Tests already exist and are failing — skip to step 4

---

## How to Use

### Step 1 — Read the Acceptance Criteria
Read the product spec, TASK_CONTEXT.md, or user brief. Extract every acceptance criterion as a numbered list. If none exist, **stop and request them** before proceeding.

```
Example:
  AC1: The endpoint returns HTTP 200 with a JSON body when the device ID is valid.
  AC2: The endpoint returns HTTP 404 when the device ID does not exist.
  AC3: The endpoint returns HTTP 401 when no auth token is provided.
```

### Step 2 — Write Failing Test Stubs (one per AC)
Write a test stub for **each acceptance criterion**. Tests must:
- Have a descriptive name that maps 1:1 to the AC (e.g. `shouldReturn200WhenDeviceIdIsValid`)
- Contain a meaningful assertion (not just `assertTrue(true)`)
- Be syntactically complete and runnable
- **Not** contain any implementation or call production code yet (use `fail("not implemented")` or equivalent)

Do **not** write any production code in this step.

### Step 3 — Confirm Tests Fail (Red)
Run the test suite. **Every stub must fail.** If a stub passes without implementation, it is not testing anything — rewrite it until it fails for the right reason.

```bash
# Java/Maven example
mvn test -pl <module> -Dtest=<TestClass>

# Report: list each test and its failure reason
```

Output the failure report before proceeding.

### Step 4 — Implement Minimal Code to Make Tests Pass (Green)
Write **only** the production code needed to make the failing tests pass. Do not add features, optimisations, or code that isn't required by a test. Work test-by-test — make one test green before moving to the next.

After each implementation increment, re-run the suite to verify:
- The target test is now green
- No previously passing tests have regressed

### Step 5 — Refactor (only after all tests are green)
With all tests green, refactor the production code for clarity, duplication removal, or performance. Run the full suite after every refactor step to ensure nothing breaks. Do **not** add new behaviour during refactor — that requires a new test first.

---

## Output Contract

After completing this skill, report:

```
## TDD Workflow Report

### Acceptance Criteria Mapped
| AC | Test Method | Status |
|----|-------------|--------|
| AC1: <description> | `<testMethodName>` | ✅ Green |
| AC2: <description> | `<testMethodName>` | ✅ Green |
| AC3: <description> | `<testMethodName>` | ✅ Green |

### Test Files Written
- `<path/to/TestClass.java>`

### Red Phase
All stubs failed as expected: yes / no
Failure reasons: <list per test>

### Green Phase
All tests passing: yes / no
Regressions introduced: none / <list>

### Refactor Phase
Changes made: <list or "none">
Suite still green: yes / no
```

---

## Comparison

| Skill | Use when |
|---|---|
| `tdd-workflow` | Writing new features or bug fixes — enforce test-first from the start |
| `blast-radius` | Assessing impact before making a change — how much could break? |
| `rollback-plan` | Documenting undo paths before applying a MEDIUM+ blast change |
| `critical-thinker` | Evaluating a plan or architecture before committing |
