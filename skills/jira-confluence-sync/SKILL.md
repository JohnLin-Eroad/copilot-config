---
name: jira-confluence-sync
description: >
  Instructs agents how to create, read, and update Jira issues and Confluence pages
  using the Atlassian MCP server. Use this skill whenever you need to log work, update
  tickets, write specs, or sync knowledge to the external project management system.
---

# Jira + Confluence Sync

## Overview

You have access to the Atlassian MCP server. Use it to keep Jira tickets and Confluence
pages in sync with agent work. Always prefer updating an existing ticket/page over
creating a new one if it already exists for the same task.

---

## Jira

### Finding the right project
- Use `searchJiraIssuesUsingJql` or `getVisibleJiraProjects` to discover project keys
- Default to searching for existing tickets before creating new ones

### Creating a Jira ticket
When creating a ticket, always include:
- **Summary**: Short, action-oriented (e.g. "Implement device provisioning endpoint")
- **Issue type**: Story (feature), Task (technical work), Bug (defect)
- **Description**: Include context, acceptance criteria, and a link to the Confluence spec if it exists
- **Labels**: Add the agent name that created it (e.g. `agent-pm`, `agent-architect`)
- **Priority**: Default to Medium unless the task brief specifies otherwise

### Updating a ticket
- Add a comment when an agent completes work or flags an issue
- Use `transitionJiraIssue` to move tickets through the workflow (To Do → In Progress → Done)
- Link related tickets using `createIssueLink` with type "Relates"

### Ticket comment format
When adding a comment from an agent, prefix with the agent name:
```
[AGENT: architect] Architecture review complete. ADR written at: <Confluence link>.
Key decision: switched from REST to event-driven for device provisioning.
See TASK_CONTEXT.md §v3 for details.
```

---

## Confluence

### Finding existing pages
- Use `searchConfluenceUsingCql` with `title ~ "..."` to find existing pages before creating new ones
- Search within the relevant space first

### Creating a Confluence page
- **Title**: Descriptive and unique (e.g. "ADR-007: Device Provisioning Event Architecture")
- **Parent page**: Always nest under a logical parent (e.g. Architecture pages under an Architecture parent)
- **Body format**: Use `markdown` for simplicity
- **Tags/Labels**: Match the note type (architecture, decision, runbook, service, etc.)

### Page types and where to create them
| Content Type | Confluence Location |
|---|---|
| Product spec / user stories | Under "Product" or "Requirements" space |
| ADRs | Under "Architecture > Decisions" |
| Service documentation | Under "Services > <service name>" |
| Runbooks | Under "Operations > Runbooks" |
| QA test plans | Under "QA > Test Plans" |
| Security findings | Under "Security > Reviews" |

### Linking Confluence ↔ Jira
After creating a Confluence page, add its URL to the related Jira ticket description or as a remote link.

---

## Sync Rules

1. **Jira is the task tracker** — every piece of agent work should have a ticket
2. **Confluence is the knowledge store** — specs, ADRs, architecture, and runbooks live here
3. **The Brain (Obsidian vault) is the local knowledge cache** — always write to the brain AND Confluence for architectural/service knowledge
4. **Don't duplicate** — search before creating; update if it exists
