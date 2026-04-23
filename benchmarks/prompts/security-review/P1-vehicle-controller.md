# Prompt P1: Vehicle Controller

## Prompt

```
Review the following Java REST controller for security vulnerabilities.
Focus on OWASP Top 10. Report what you find with severity levels.

@RestController
@RequestMapping("/api/vehicles")
public class VehicleController {

    private final DataSource dataSource;

    public VehicleController(DataSource dataSource) {
        this.dataSource = dataSource;
    }

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
            row.put("owner_email", rs.getString("owner_email"));
            row.put("fleet_id", rs.getString("fleet_id"));
            results.add(row);
        }
        return results;
    }

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

## Planted Vulnerabilities (GRADER ONLY)

1. **SQL Injection (OWASP A03)** — `"SELECT * FROM vehicles WHERE plate_number = '" + query + "'"` — string concatenation in raw SQL
2. **Sensitive Data Exposure (OWASP A02)** — `owner_email` returned in API response without access control or masking
3. **Information Exposure in Error Response (OWASP A09)** — `"wrong password: " + request.getPassword()` — reflects password in response

## Grading Rubric

| Dimension | Weight | How to score |
|---|---|---|
| Recall | 40% | (planted vulns found) / 3 × 100 |
| Precision | 30% | (true positives) / (total issues flagged) × 100 |
| Severity accuracy | 30% | Were found vulns correctly classified as HIGH or CRITICAL? (per-vuln pass/fail, averaged) |

**Score = weighted average (0-100)**

## Ground Truth

- SQL Injection: CRITICAL severity
- Sensitive Data Exposure: HIGH severity
- Password Reflection: HIGH severity
- Bonus (not required): resource leak (Connection/Statement not closed) — code quality, not security
