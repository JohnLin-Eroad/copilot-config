# Trace: Code Generation — 2026-W17

## Prompt Sent
Write a Python function that parses a CSV file and returns a list of dicts, skipping malformed rows.

## Raw Output
```python
import csv

def parse_csv(filepath):
    results = []
    with open(filepath, newline='') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            try:
                results.append(dict(row))
            except Exception as e:
                print(f"Skipping malformed row {i}: {e}")
    return results
```

## Failure Observations
- Score 4.2/5 — function catches exceptions but the only malformed row scenario for DictReader is mismatched column count, which it silently handles by filling None. The try/except never triggers for that case. Needs a validation step checking for None values in required fields.
