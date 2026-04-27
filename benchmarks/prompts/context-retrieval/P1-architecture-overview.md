# Prompt P1: Architecture Overview

## Prompt

```
I need to understand the EROAD fleet management domain. Specifically:
1. What is the high-level architecture of EROAD's services?
2. What is the role of the sovereign platform in relation to EROAD?
3. What Java version and Spring Boot version does the sovereign codebase use?
4. What are the key domain entities in the EROAD system?

Answer based on what is in the eroad-brain vault. For anything not covered, say so explicitly.
```

## Expected Behavior

- brain-data-retrieval fetches ≥2 relevant files from eroad-brain
- Answer correctly names EROAD services from those files
- Correctly states Java 21 + Spring Boot 3.4
- Explicitly says "not covered in vault" for anything absent
- Zero fabricated facts

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Brain data used | 25% | Answer is generic, no vault references | References vault but vaguely | Explicitly cites specific brain files |
| Accuracy | 25% | Facts contradict vault content | Some facts correct | All facts traceable to fetched content |
| Gap handling | 25% | Hallucinates answers for missing info | Partially acknowledges gaps | Explicitly states "not in vault" for each gap |
| No hallucination | 25% | Invents services, APIs, or facts | Minor embellishments | Zero fabricated facts, every claim sourced |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

From eroad-brain vault:
- Architecture: microservices including espserver-service, ebox-service, dvir, location, safety, machine services
- Sovereign: local transformation platform for AI-governed migration
- Java 21 + Spring Boot 3.4 (from sovereign codebase)
- Domain entities: Driver, Vehicle/Machine (same entity — "Machine" internally, "Vehicle" customer-facing), Device, Fleet, Organisation, Trip, Event
- Java/Spring version lives in copilot-instructions.md or sovereign pom.xml, NOT in brain vault (gap expected)
