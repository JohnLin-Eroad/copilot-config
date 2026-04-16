# Benchmark Task 3: Security Review

## Purpose
Tests the security agent's ability to identify planted OWASP vulnerabilities with high recall (finds real issues) and high precision (doesn't invent false ones).

## Test Code — Planted Vulnerabilities

The following Java snippet has exactly **3 planted vulnerabilities**. The grader knows what they are (see below). The agent must find them.

```java
@RestController
@RequestMapping("/api/vehicles")
public class VehicleController {

    private final DataSource dataSource;

    public VehicleController(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    // Vulnerability 1 is here
    @GetMapping("/search")
    public List<Map<String, Object>> searchVehicles(@RequestParam String query) throws Exception {
        Connection conn = dataSource.getConnection();
        Statement stmt = conn.createStatement();
        ResultSet rs = stmt.executeQuery("SELECT * FROM vehicles WHERE plate_number = '" + query + "'");
        List<Map<String, Object>> results = new ArrayList<>();
        while (rs.next()) {
            Map<String, Object> row = new HashMap<>();
            row.put("id", rs.getString("id"));
            row.put("plate", rs.getString("plate_number"));
            row.put("owner_email", rs.getString("owner_email"));  // Vulnerability 2 is here
            row.put("fleet_id", rs.getString("fleet_id"));
            results.add(row);
        }
        return results;
    }

    // Vulnerability 3 is here
    @PostMapping("/auth")
    public ResponseEntity<String> authenticate(@RequestBody AuthRequest request) {
        String expectedPassword = System.getenv("VEHICLE_API_PASSWORD");
        if (request.getPassword().equals(expectedPassword)) {
            return ResponseEntity.ok("authenticated");
        }
        return ResponseEntity.status(401).body("wrong password: " + request.getPassword());  
    }
}
```

## The 3 Planted Vulnerabilities (GRADER ONLY — do not include in prompt to agent)

1. **SQL Injection (OWASP A03)** — `"SELECT * FROM vehicles WHERE plate_number = '" + query + "'"` — string concatenation in raw SQL query
2. **Sensitive Data Exposure (OWASP A02)** — `owner_email` returned in the API response without any access control or data masking
3. **Information Exposure in Error Response (OWASP A09)** — `"wrong password: " + request.getPassword()` — reflects the submitted password back in the error response

## Input Prompt to Agent

```
Review the following Java REST controller for security vulnerabilities. 
Focus on OWASP Top 10. Report what you find with severity levels.

[paste the code above WITHOUT the vulnerability annotations]
```

## Scoring

| Metric | Formula | Notes |
|---|---|---|
| **Recall** | (vulnerabilities found) / 3 | 0.33, 0.67, or 1.0 |
| **Precision** | (true vulnerabilities) / (total issues flagged) | Penalises false positives |
| **Severity accuracy** | Were all 3 correctly classified as HIGH or CRITICAL? | Pass/Fail per found vuln |

**Final score** = (Recall × 0.5) + (Precision × 0.3) + (Severity accuracy × 0.2) × 5

**Target:** Recall = 1.0 (finds all 3), Precision ≥ 0.75 (no more than 1 false positive)

## Grader Notes for benchmark-runner

List each finding the security agent produced. Map each to: TRUE_POSITIVE (matches one of the 3 planted vulns), FALSE_POSITIVE (not a real vulnerability), or DUPLICATE (same vuln flagged twice). Calculate recall and precision from this mapping.
