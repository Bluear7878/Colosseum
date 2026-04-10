---
name: update-docs
description: Update all project documentation (README, specs, architecture docs) to reflect the current codebase state. Run this before or after creating a PR to keep docs in sync with code changes.
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Agent]
version: 1.0.0
---

# Documentation Update Skill

Analyze the current codebase and update all project documentation to reflect the latest state. This ensures docs stay in sync with code changes across PRs.

---

## Documents to Update

The following documents must be checked and updated if stale:

1. **`README.md`** — Product overview, CLI commands, API endpoints, features, repository layout
2. **`docs/colosseum_spec.md`** — Specification index and feature area listing
3. **`docs/architecture/overview.md`** — Layered architecture, services, invariants, extension points
4. **`docs/architecture/design-philosophy.md`** — Design principles (update only if new principles emerge)
5. **`docs/specs/runtime-protocol.md`** — Run lifecycle, streaming phases, depth profiles, export formats
6. **`docs/specs/agent-governance.md`** — Agent/persona/provider schema and rules
7. **`docs/specs/persona-authoring.md`** — Persona file formats and validation

---

## Step 1: Gather Current State

Read the following to understand what has changed:

```bash
# Recent commits since last doc update
git log --oneline -20

# Current CLI commands docstring
head -25 src/colosseum/cli.py

# All API endpoints
grep -rn '@router\.' src/colosseum/api/ | grep -E '\.(get|post|put|delete)\('
```

Also read:
- `src/colosseum/core/models.py` — for new/changed domain types
- `src/colosseum/core/config.py` — for new config values, review phases, depth profiles
- `src/colosseum/api/routes_setup.py` — for new setup/discovery endpoints
- `src/colosseum/api/routes_runs.py` — for new run management endpoints
- `src/colosseum/services/` — list files to check for new services

---

## Step 2: Identify Gaps

Compare the current codebase state against each document. Look for:

- **New CLI commands** not documented in README
- **New API endpoints** not in the API Reference
- **New services** not in the architecture overview
- **New features** (e.g., new provider types, new review phases, new export formats) not mentioned
- **Changed behavior** (e.g., renamed endpoints, new required fields, removed features)
- **New files/modules** not in the repository layout

---

## Step 3: Update Documents

For each document with gaps:

1. Read the current document content
2. Apply targeted edits to add missing content or fix outdated content
3. Preserve the existing style, formatting, and structure
4. Do NOT remove content that is still accurate
5. Keep descriptions concise — match the existing tone

### Key Rules
- **README.md**: Keep it product-facing. CLI commands table must match the actual `cli.py` docstring. API Reference must match actual route decorators. Repository Layout must list all Python modules.
- **architecture/overview.md**: Must list every service module in the appropriate layer. Must document the artifact storage structure.
- **runtime-protocol.md**: Must list all SSE phases. Must document all run control actions. Must include depth profile table.
- **agent-governance.md**: Must match the actual `AgentConfig` and `ProviderConfig` fields in `models.py`.
- **persona-authoring.md**: Must match the actual frontmatter fields supported by `PersonaRegistry`.

---

## Step 4: Report Changes

After updating, output a summary of what was changed:

```
📝 Documentation Update Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

README.md:
  - Added: [list of additions]
  - Updated: [list of changes]

docs/architecture/overview.md:
  - Added: [list of additions]

(etc.)

No changes needed:
  - [list of docs that were already up to date]
```

---

## Guidelines

- Do NOT add speculative content about features that don't exist yet
- Do NOT change the documentation structure without good reason
- Do NOT add verbose explanations — match existing conciseness
- Always verify against actual source code, not assumptions
- If unsure whether something changed, read the relevant source file
