# Prompt P5: Discovery from Raw Slack Transcript

**Difficulty tier: 3 (Expert)** — source: tasks/planning.md Variant F

## Prompt

```
No product spec has been written for this feature. All we have is this Slack thread
from last week. Extract the bounded context, identify what needs to be built, surface all
ambiguities and gaps, and produce an implementation plan — or explain what you'd need before
you can produce one.

--- SLACK THREAD START ---
@sarah.pm: hey team, fleet managers keep asking about the "overtime thing"
@dev.ali: yeah the compliance thing, drivers going over hours?
@sarah.pm: no its different, its more like… they want to see who's been doing too many shifts
@dev.ali: shifts? or hours within a single shift?
@sarah.pm: honestly not sure, I think both? Craig from the fleet side said something about weekly totals
@legal.team: just FYI there's a legal threshold but it depends on the employment agreement type
@dev.ali: so its per-employment-type?
@sarah.pm: I guess? Craig would know. Also it might need to show in the existing reporting thing
@dev.ali: the legacy reporting service? that hasn't been touched in 3 years
@sarah.pm: yeah probably that one
@dev.ali: ok so we're adding to legacy or building new?
@sarah.pm: up to you I think? just needs to work
@legal.team: don't forget the union rules also differ by region (NZ vs AU)
@dev.ali: 😬 ok I'll write something up
--- SLACK THREAD END ---

Produce a detailed implementation plan, or clearly articulate what must be answered first.
```

## Expected Behavior

A disciplined agent should refuse to produce a full plan, instead cataloguing the open questions (shifts vs hours, weekly vs daily, employment-type variants, NZ vs AU rules, build new vs extend legacy, what "too many" means), mapping stakeholders to each question, and proposing a discovery step.

## Grading Rubric

| Dimension | Weight | 0 | 50 | 100 |
|---|---|---|---|---|
| Ambiguity catalogue | 20% | ≤2 or just "unclear" | 3–5 ambiguities | ≥6 open questions itemised |
| Bounded context extraction | 15% | ≤2 or incorrect concepts | 3–4 concepts | driver, shift, employment agreement, compliance threshold, region named |
| Build vs extend decision | 10% | Ignored | Mentioned | Binary with pros/cons + recommendation |
| Stops before full plan | 20% | Full plan as if clear | Partial plan with caveats | Refuses; offers conditional plan / skeleton |
| Stakeholder mapping | 10% | None | Some attribution | Each question routed to Craig/legal/HR/Sarah |
| Region/legal awareness | 10% | Ignores legal | Mentions | Notes NZ vs AU as a domain modelling decision |
| Next step proposal | 5% | None | Vague meeting | Concrete discovery workshop / question list |
| Signal-to-noise | 10% | Significant hallucination | Some invention | Disciplined, no invented requirements |

**Score = weighted average (0–100)**

## Auto-Checks

```yaml
- name: refuses-premature-plan
  must_contain_any: ["clarif", "open question", "need to", "before", "ambigu"]
  case_insensitive: true
- name: catalogues-questions
  regex: "(?s)(question|clarif|unknown).{0,500}(question|clarif|unknown)"
  case_insensitive: true
- name: names-key-stakeholders
  must_contain_any: ["Craig", "Sarah", "legal", "HR"]
- name: flags-region-difference
  must_contain_any: ["NZ", "AU", "region", "Australia", "New Zealand"]
- name: flags-employment-type
  must_contain_any: ["employment", "agreement type", "union"]
  case_insensitive: true
- name: legacy-vs-new
  must_contain_any: ["legacy", "extend", "new service"]
  case_insensitive: true
```

## Ground Truth

Expected open questions (≥6): (1) shifts vs hours, (2) weekly vs daily window, (3) "too many" threshold definition, (4) employment-type-specific thresholds, (5) NZ vs AU union rule divergence, (6) build new service vs extend legacy reporting, (7) report surface / UX placement, (8) data source for shift totals.
