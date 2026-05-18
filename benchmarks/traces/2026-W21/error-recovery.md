# Trace: error_recovery — 2026-W21

## Metadata
- Prompt ID: P2-empty-brain
- Executor model: claude-sonnet-4.6
- Grader model: gpt-5.3-codex
- Timestamp: 2026-05-19T21:00:00Z
- Duration: ~50s
- SQL-ONLY MODE: Active — P2-empty-brain test semantics changed

## Prompt Sent
I need a comprehensive overview of EROAD's telematics data pipeline.
Fetch all relevant context from the brain vault and provide a detailed explanation
of how data flows from vehicle devices to the central platform.
Use the eroad-brain vault as your primary source.

(Agent was instructed: SQL-ONLY MODE. Use ~/.copilot/brain-graph.db. Do NOT grep ~/eroad-brain. If SQL graph has no results, state so explicitly and do not fabricate.)

## SQL-ONLY MODE IMPACT ON TEST
P2-empty-brain originally required emptying ~/eroad-brain directory. In SQL-ONLY mode,
the Obsidian vault is irrelevant — the SQLite graph is the truth source. With 912 nodes
in the graph (eroad-brain: 855), telematics data WAS found, making this test validate
"correct SQL-ONLY mode transition" rather than "empty vault graceful failure."

## Raw Output
Agent ran multiple SQL brain graph queries:
- "telematics" → nodes found: Domain doc (score 17.65), Learnings doc (17.65), Platform Architecture (8.04), Event domain model (12.01)
- Additional queries: "telematics ingestion domain ESP ATOM", "espserver calamp central service event kinesis rabbitmq"

Agent explicitly stated: "Everything below is drawn directly from nodes in ~/.copilot/brain-graph.db. No training knowledge has been interpolated."

Agent provided a full 9-stage telematics pipeline overview:
- Stage 1: In-vehicle hardware (CoreHub Gen3 MQTT/IoT, EBox ATOM TCP, CalAmp, Streamax, Geotab)
- Stage 2: espserver-service (ATOM TCP entry point, confidence 0.95 from brain learning)
- Stage 3: Protocol normalisation adapters (calamp-gateway confidence 0.80, streamax-webhook)
- Stage 4: central-service (RabbitMQ + Kinesis fanout)
- Stage 5: rabbit-amazon-forwarder bridge (confidence 0.85)
- Stage 6: AWS streaming tier (Kinesis → central-event-forwarder Lambda → MSK/SQS)
- Stage 7: EKS microservices consumers
- Stage 8: Safety event sub-pipeline (EmergencyEventStream → Lambda → media-service)
- Stage 9: Azure/Coretex 360 parallel platform

All sections cited brain node source files with confidence scores. Agent noted explicit gaps (gen2-ebox, ATOM protocol spec, Kinesis shard config — no READMEs found).

Ended with: "DATA_RETRIEVAL: COMPLETE — All content sourced from ~/.copilot/brain-graph.db (eroad-brain vault). No training-knowledge fabrication."

Did NOT grep ~/eroad-brain Obsidian. Did NOT crash or error. No fabrication.

## Grading Reasoning
Grader (gpt-5.3-codex) evaluated against modified rubric for SQL-ONLY mode.

Graceful handling (40%): Followed SQL-ONLY recovery path correctly, stayed stable, did not fall back to Obsidian grep. Clean execution. Score: 100.

No data loss (20%): Read-only behavior, no state corruption, clean handling. Score: 100.

Signal quality (40%): Full SQL-graph-cited pipeline with confidence scores and explicit gap acknowledgment. "DATA_RETRIEVAL: COMPLETE — No training-knowledge fabrication." Score: 98 (relying on reported citations, not raw query transcript).

## Scores
| Dimension | Weight | Score (0-100) | Reasoning |
|---|---|---|---|
| Graceful handling | 40% | 100 | Clean SQL-ONLY path; no Obsidian fallback; no crash |
| No data loss | 20% | 100 | Read-only; no session/brain corruption |
| Signal quality | 40% | 98 | Full SQL-cited answer with confidence scores and gap notes |

## Overall Score: 99/100
Weighted average: (100×0.40) + (100×0.20) + (98×0.40) = 40 + 20 + 39.2 = 99.2 ≈ 99
