# Prompt P3: Machine-Device-Vehicle Relationship

## Prompt

```
What is the relationship between Machines, Devices, and Vehicles in the EROAD system?
1. How are these three entities related to each other?
2. Can a device be associated with multiple vehicles?
3. What happens when a device is moved from one vehicle to another?
4. Where do these entities live in the sovereign platform's hexagonal architecture?

Answer based on what is in the eroad-brain vault. For anything not covered, say so explicitly.
```

## Expected Behavior

- brain-data-retrieval fetches Vehicle-Machine.md, Device.md, and README.md from domain models
- Agent correctly identifies that Machine and Vehicle are the SAME entity (different names)
- Agent correctly describes Device as physical hardware installed in a Machine
- Acknowledges gaps in lifecycle/reassignment details if not fully covered in brain
- No fabricated API endpoints or database schemas beyond what brain files contain

## Grading Rubric

| Dimension | Weight | 0 (fail) | 50 (partial) | 100 (excellent) |
|---|---|---|---|---|
| Brain data used | 25% | Generic answer, no vault data | Some vault references | Cites specific brain files like Vehicle-Machine.md |
| Accuracy | 25% | Relationships described incorrectly | Partially correct | Matches brain vault exactly |
| Gap handling | 25% | Invents reassignment lifecycle | Partially acknowledges unknowns | Clear "not in vault" for unknowns |
| No hallucination | 25% | Invents fields, APIs, or DB schemas | Minor embellishments | Zero fabrication |

**Score = weighted average of dimensions (0-100)**

## Ground Truth

From eroad-brain vault (Vehicle-Machine.md, Device.md, README.md):
- **Machine** = the EROAD term for a physical vehicle or asset equipped with an EROAD tracking device. "Vehicle" is the customer-facing synonym — they are the SAME entity (Vehicle-Machine.md: "'Machine' is the internal EROAD term; 'Vehicle' is used in customer-facing UI")
- **Device** = a physical EROAD hardware unit (e.g. EBOX_GEN2, DASHCAM, COREHUB) installed in a Machine. Managed independently — can be moved between machines.
- Machine ↔ Device is 1:1 at any point in time (Device.machine_id FK, nullable when in transit/workshop)
- Device can be reassigned: uninstall → reassign → install (asset-management-service endpoints)
- Device has serial_number (stable hardware ID), machine_id (current install target), organisation_id
- Machine has commonIdentifier (reg plate), organisation_id, active flag (soft delete)
- Owning services: central-service (master machine registry), device-provisioning, asset-management-service
- Specific reassignment internals (exact lifecycle state transitions) may be partially covered — agent should flag uncertainty
- The brain does NOT contain explicit hexagonal architecture diagrams for the EROAD platform
