# Benchmark Task 2: Context Retrieval

## Purpose
Tests whether the brain-data-retrieval agent correctly fetches relevant brain vault content and whether downstream agents actually use it (vs. hallucinating).

## Input Prompt

```
I need to understand the EROAD fleet management domain. Specifically:
1. What is the high-level architecture of EROAD's services?
2. What is the role of the sovereign platform in relation to EROAD?
3. What Java version and Spring Boot version does the sovereign codebase use?
4. What are the key domain entities in the EROAD system?

Answer based on what is in the eroad-brain vault. For anything not covered, say so explicitly.
```

## Evaluation Method

### Step 1 — Run brain-data-retrieval first
```bash
copilot agent run brain-data-retrieval --message "Fetch context for: EROAD fleet management architecture, sovereign platform role, Java/Spring version, domain entities"
```
Check the STM to see what was fetched.

### Step 2 — Run the answer agent with that STM
Provide the STM content and the input prompt.

### Step 3 — Score

| Dimension | Pass | Fail |
|---|---|---|
| **Brain data used** | Answer explicitly references brain vault content | Answer is generic with no vault-specific details |
| **Accuracy** | Facts match what's in the brain files | Facts contradict or don't appear in fetched content |
| **Explicit gaps** | Clearly states "not in vault" for missing items | Halluccinates answers for gaps |
| **No hallucination** | All claims traceable to fetched content | Claims made without source in STM |

**Scoring:**
- Brain data used: Pass=1, Fail=0
- Accuracy: 1–5 (5 = all facts correct, 1 = mostly wrong)
- Explicit gaps handled: Pass=1, Fail=0
- No hallucination: Pass=1, Fail=0

**Composite:** (accuracy/5 × 0.5) + (other 3 pass/fail × 0.167 each) → 0.0–1.0, then × 5 for 1–5 scale

## What Good Looks Like (Score 5)

- Brain data retrieval fetches ≥2 relevant files from eroad-brain
- Answer correctly names EROAD services from those files
- Correctly states Java 21 + Spring Boot 3.4 (from sovereign codebase docs)
- Explicitly says "not covered in vault" for anything absent
- Zero fabricated facts

## Grader Notes for benchmark-runner

Check the STM fetch manifest. Count how many files were fetched. For each answer claim, verify it appears in the fetched content. Score hallucinations as 0 for the no-hallucination dimension.
