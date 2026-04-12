# Copilot Global Learnings

Cross-repo patterns, preferences, and lessons learned — applied to all sessions.

---

- **[2026-04-11]** Skills MUST have YAML frontmatter (`name:` + `description:`) at the top of SKILL.md — without it, Copilot silently ignores the skill and it won't appear in the available skills list
- **[2026-04-11]** `--allow-tool shell` auto-approves ALL shell commands including destructive ones like `rm -rf` — too broad; John prefers to be prompted for shell commands individually
- **[2026-04-11]** Hook `permissionDecision` only supports `"deny"` — `"ask"` is defined in spec but not yet implemented; hooks can hard-block but cannot escalate to the user for approval
- **[2026-04-11]** `~/copilot-config` is the source of truth for all Copilot config; `~/.copilot/` is the deployed copy — changes to `~/copilot-config` must be copied or run via `setup.sh` to take effect
- **[2026-04-11]** John prefers explicit error messages over silent fallbacks
- **[2026-04-11]** John prefers security over convenience — when in doubt about auto-approving a broad permission, remove it and let the CLI prompt instead
- **[2026-04-11]** Local repo learnings live in `<repo>/.github/learnings.md`; global cross-repo learnings live in `~/.copilot/learnings.md` — use `add-learning.sh --local` or `--global` to write them
- **[2026-04-11]** Primary stack is Java/Spring Boot (backend) and React/TypeScript (frontend); EROAD is the organisation context
- **[2026-04-11]** Brain enrichment: `catalog-info.yaml` (Backstage) is the best source for submodule structure — 80/208 repos have it; `api.json` is source-of-truth for endpoints (22 repos have it, often at `*-client/api.json`)
- **[2026-04-11]** Brain enrichment: Swagger-gen files use `@RequestMapping(value="...", method=RequestMethod.GET)` where method is a separate attribute — requires DOTALL regex, not the same as `@GetMapping`
- **[2026-04-11]** Brain enrichment: Lambda trigger type detected from `implements RequestHandler<SQSEvent|KinesisEvent|S3Event|ScheduledEvent>` in handler class
- **[2026-04-11]** Brain cross-linking: strip `-api` suffix to resolve integration targets to brain node filenames (e.g. `data-retrieval-service-api` → `data-retrieval-service`)
