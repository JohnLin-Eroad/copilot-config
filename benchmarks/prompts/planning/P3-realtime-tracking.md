# Prompt P3: Real-Time Vehicle Tracking

## Prompt

```
Design a real-time vehicle tracking system for the sovereign platform.

Requirements:
- 5-second update frequency from each vehicle
- Support 10,000 concurrent vehicles
- Fleet managers see live vehicle positions on a map
- Historical trail data retained for 30 days
- Must integrate with existing EROAD device communication (ebox-service)

Produce a detailed implementation plan with technology choices, scalability analysis,
and data flow architecture.
```

## Expected Behavior

Plan addresses:
- Event-driven architecture (SQS/Kafka for position events)
- WebSocket or SSE for real-time frontend updates
- Time-series storage for historical trails (TimescaleDB, or partitioned PostgreSQL)
- Throughput analysis: 10,000 vehicles × 1 event/5s = 2,000 events/sec
- Integration point with ebox-service
- Hexagonal: position events in domain, WebSocket adapter in infrastructure
- Data retention/pruning strategy

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Domain understanding | 15% | No mention of Vehicle/Position entities | Basic mention | VehiclePosition VO, PositionEvent, TrailAggregate, fleet scoping |
| Hexagonal architecture | 20% | All in one layer | Partial separation | Domain events, application use cases, infrastructure adapters (WebSocket, SQS) |
| Blast radius assessment | 15% | None | Vague | Specific: new infrastructure (message broker, WebSocket server), DB load, network bandwidth |
| Edge cases | 15% | None | 1-2 | ≥4: GPS gaps, out-of-order events, vehicle offline, timezone, connection drops |
| Dependency ordering | 15% | Unordered | Partial | Phased: domain model → event processing → storage → real-time push → frontend |
| Acceptance criteria | 20% | None | Vague | Measurable: "Position visible within 2s of device report", "10k vehicles < 100ms p99 query" |

**Score = weighted average of dimensions (0-100)**
