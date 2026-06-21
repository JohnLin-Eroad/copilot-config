#!/usr/bin/env python3
"""
Comprehensive end-to-end test suite for the brain graph system.
Tests: search, traverse, cache, fallback, content fetch, sync, latency.
"""
import sys, time, json
sys.path.insert(0, '/Users/johnlin/.copilot/scripts')
from brain_graph_query import query, traverse, clear_cache, fetch_content
from pathlib import Path

DB = Path.home() / ".copilot/brain-graph.db"
PASS = 0; FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} — {detail}")

clear_cache()

print("━━━ SEARCH ━━━")
r = query("eroad", "media-service")
check("Returns results", r["result_count"] > 0)
check("Tier 1", r.get("tier") == 1)
check("Has combined_score", all("combined_score" in x for x in r["results"]))
check("Sorted by score", all(r["results"][i]["combined_score"] >= r["results"][i+1]["combined_score"] for i in range(len(r["results"])-1)))

r = query("eroad", "SQS events", max_results=5)
check("Max results cap", r["result_count"] <= 5)

r = query("eroad", "blockchain Solidity Ethereum smart contracts")
check("Negative returns 0", r["result_count"] == 0, f"got {r['result_count']}")

# Cache
clear_cache()
query("eroad", "SQS events", max_results=5)
t0 = time.perf_counter()
r2 = query("eroad", "SQS events", max_results=5)
cache_ms = (time.perf_counter() - t0) * 1000
check("Cache hit flag", r2.get("cached") == True)
check("Cache <1ms", cache_ms < 1, f"{cache_ms:.2f}ms")

r = query("eroad", "auth login", mode="fts-only")
check("FTS-only tier 2", r.get("tier") == 2)

r = query("eroad", "media-service", db_path=Path("/tmp/nonexistent.db"))
check("Grep fallback tier 3", r.get("tier") == 3)

r = query("eroad", "media-service", manifest={"eroad/01 - Services/media-service"})
check("Manifest exclusion", all(x["id"] != "eroad/01 - Services/media-service" for x in r["results"]))

content = fetch_content(["eroad/01 - Services/media-service"], DB)
check("Content fetch", len(content) > 0 and any(len(v) > 50 for v in content.values()))

print("\n━━━ TRAVERSE ━━━")
r = traverse("01 - Services/media-service.md", vault="eroad", max_depth=1)
check("Finds start node", r.get("start_node") is not None)
check("Returns neighbors", r["result_count"] > 0)
check("Has depth field", all("depth" in x for x in r["results"]))

r = traverse("01 - Services/media-service.md", vault="eroad", max_depth=2, max_results=50)
d1 = sum(1 for x in r["results"] if x["depth"] == 1)
d2 = sum(1 for x in r["results"] if x["depth"] == 2)
check("Depth-1 results", d1 > 0)
check("Depth-2 results", d2 > 0, f"d1={d1}, d2={d2}")

r = traverse("01 - Services/media-service.md", vault="eroad", max_depth=1, filter_domain="service")
check("Domain filter", all(x["domain"] == "service" for x in r["results"]))

first = traverse("01 - Services/media-service.md", vault="eroad", max_depth=1, max_results=5)
exclude = {x["id"] for x in first["results"]}
second = traverse("01 - Services/media-service.md", vault="eroad", max_depth=1, max_results=10, exclude_visited=exclude)
check("Exclude prunes", second["pruned_count"] > 0)
check("No overlap", len({x["id"] for x in second["results"]} & exclude) == 0)

r = traverse("totally-fake-xyz", vault="eroad")
check("Missing node error", "error" in r)

r = traverse("configuration-core", vault="eroad")
check("Partial name resolve", r.get("start_node") is not None)

print("\n━━━ LATENCY ━━━")
clear_cache()
lats = []
for q in ["media-service", "SQS events", "hexagonal architecture", "RUCUS compliance", "driver login"]:
    t0 = time.perf_counter(); query("eroad", q); lats.append((time.perf_counter()-t0)*1000)
avg = sum(lats)/len(lats)
p95 = sorted(lats)[int(len(lats)*0.95)]
check(f"Avg <50ms ({avg:.1f}ms)", avg < 50)
check(f"P95 <100ms ({p95:.1f}ms)", p95 < 100)

print(f"\n{'═'*50}")
print(f"RESULTS: {PASS}/{PASS+FAIL} passed, {FAIL} failed")
if FAIL == 0:
    print("🎉 ALL E2E TESTS PASSED")
else:
    print(f"⚠️ {FAIL} FAILURES")
sys.exit(0 if FAIL == 0 else 1)
