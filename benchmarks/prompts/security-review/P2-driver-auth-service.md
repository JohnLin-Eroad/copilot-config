# Prompt P2: Driver Auth Service

## Prompt

```
Review the following Java REST controller for security vulnerabilities.
Focus on OWASP Top 10. Report what you find with severity levels.

@RestController
@RequestMapping("/api/drivers")
public class DriverAuthController {

    private final DriverRepository driverRepository;
    private final JwtTokenProvider tokenProvider;

    public DriverAuthController(DriverRepository driverRepository, JwtTokenProvider tokenProvider) {
        this.driverRepository = driverRepository;
        this.tokenProvider = tokenProvider;
    }

    @PostMapping("/login")
    public ResponseEntity<Map<String, String>> login(@RequestBody LoginRequest request) {
        Driver driver = driverRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new RuntimeException("Driver not found"));

        if (driver.getPasswordHash().equals(hashPassword(request.getPassword()))) {
            String token = tokenProvider.generateToken(driver.getId(), driver.getRole());
            return ResponseEntity.ok(Map.of("token", token));
        }
        return ResponseEntity.status(401).body(Map.of("error", "Invalid credentials"));
    }

    @PostMapping("/update-role")
    public ResponseEntity<String> updateRole(@RequestBody RoleUpdateRequest request,
                                              @RequestHeader("Authorization") String authHeader) {
        String token = authHeader.replace("Bearer ", "");
        Claims claims = tokenProvider.parseToken(token);

        Driver driver = driverRepository.findById(request.getDriverId())
                .orElseThrow(() -> new RuntimeException("Driver not found"));
        driver.setRole(request.getNewRole());
        driverRepository.save(driver);

        return ResponseEntity.ok("Role updated to " + request.getNewRole());
    }

    @GetMapping("/verify")
    public ResponseEntity<Map<String, Object>> verifyToken(@RequestHeader("Authorization") String authHeader) {
        String token = authHeader.replace("Bearer ", "");
        Claims claims = tokenProvider.parseToken(token);
        return ResponseEntity.ok(Map.of(
                "driverId", claims.getSubject(),
                "role", claims.get("role"),
                "valid", true
        ));
    }

    private String hashPassword(String password) {
        return org.apache.commons.codec.digest.DigestUtils.sha256Hex(password);
    }
}
```

## Planted Vulnerabilities (GRADER ONLY)

1. **Broken Authentication — No JWT Expiry Check (OWASP A07)** — `tokenProvider.parseToken(token)` is called but there's no evidence of expiry validation. The `generateToken` method is not shown, so there's no guarantee tokens expire. The `/verify` endpoint trusts any parseable token indefinitely.
2. **Privilege Escalation via Role Parameter (OWASP A01)** — `/update-role` accepts `request.getNewRole()` directly without checking if the caller has permission to assign that role. Any authenticated user can set any driver's role to ADMIN.
3. **Weak Password Hashing (OWASP A02)** — Uses `sha256Hex` instead of bcrypt/scrypt/argon2. SHA-256 is fast and unsalted, making it vulnerable to rainbow tables and brute force.

## Grading Rubric

| Dimension | Weight | How to score |
|---|---|---|
| Recall | 40% | (planted vulns found) / 3 × 100 |
| Precision | 30% | (true positives) / (total issues flagged) × 100 |
| Severity accuracy | 30% | Were found vulns correctly classified? (per-vuln pass/fail, averaged) |

**Score = weighted average (0-100)**

## Ground Truth

- No JWT expiry: HIGH severity (persistent access tokens)
- Privilege escalation: CRITICAL severity (any user → admin)
- Weak password hashing: HIGH severity (offline attack vector)
- Bonus (not required): timing-safe comparison not used for password check
