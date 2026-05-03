# Prompt P4: Governance Engine

## Prompt

```
How does the sovereign governance engine make intervention decisions?
1. What rules does it evaluate?
2. How are blast radius levels determined?
3. What happens when a CRITICAL blast radius change is proposed?
4. Where are governance rules stored and how are they structured?

Answer based on what is in the eroad-brain vault and the sovereign codebase. For anything not covered, say so explicitly.
```

## Expected Behavior

- brain-data-retrieval fetches governance-related brain files
- Agent describes the GovernanceEngine from actual vault/code content
- References governance-rules.json structure
- Clearly separates what it knows from vault vs what it's speculating about

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Brain data used | 25% | Generic governance description | Some vault content | Specific citations from brain + copilot-config |
| Accuracy | 25% | Wrong description of engine | Partially correct | Matches actual governance-rules.json structure |
| Gap handling | 25% | Invents rules or processes | Partial acknowledgment | Clear gaps flagged |
| No hallucination | 25% | Fabricates API endpoints or decision trees | Minor guesses | Zero fabrication, all claims sourced |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

From copilot-config/governance-rules.json:
- 16+ rules with IDs like sec-001, gov-001, audit-001
- Severity levels: BLOCK, WARN, and LOG
- Rules cover: pipe-to-shell downloads, credential exfiltration, metadata access, rm -rf, force push, DROP TABLE, etc.
- Blast radius levels: LOW, MEDIUM, HIGH, CRITICAL (defined in copilot-instructions.md)
- CRITICAL requires explicit human approval
