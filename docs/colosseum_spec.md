# Colosseum Specification Index

This file is the entry point for Colosseum's canonical documentation set.

## Read This First

- Product overview, quickstart, and CLI reference: [`README.md`](../README.md)
- Architecture overview: [`docs/architecture/overview.md`](./architecture/overview.md)
- Design philosophy: [`docs/architecture/design-philosophy.md`](./architecture/design-philosophy.md)

## Runtime Specifications

- Runtime protocol: [`docs/specs/runtime-protocol.md`](./specs/runtime-protocol.md) — Run lifecycle, streaming contract, cost tracking, depth profiles
- Agent governance: [`docs/specs/agent-governance.md`](./specs/agent-governance.md) — Agent, persona, and provider boundaries
- Persona authoring: [`docs/specs/persona-authoring.md`](./specs/persona-authoring.md) — Persona file formats and validation

## Feature Areas

- **Debate**: Bounded, agenda-driven debate with novelty/convergence/budget stop rules
- **Code Review**: Multi-phase review workflow (6 phases: A-F) with per-phase mini-debates
- **Local Runtime**: Managed Ollama daemon with GPU detection and llmfit fit-checking
- **Cost Tracking**: Real token counts from provider output, per-agent cost breakdown
- **Reports**: AI-synthesized final reports with PDF and Markdown export

## Canonical Ownership

- `README.md` explains what Colosseum is, how to start it, and documents all CLI commands and API endpoints.
- `docs/architecture/*` explains why the system is shaped the way it is.
- `docs/specs/*` defines the operational contracts contributors should preserve.

Do not add new runtime rules only to the README. Put them in the relevant spec and link them from there.
