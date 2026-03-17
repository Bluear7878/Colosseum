# Architecture Overview

## Purpose

Colosseum is a provider-neutral orchestration runtime for running the same task through multiple agents, freezing a shared context bundle, and producing a traceable verdict through bounded debate.

This document is the canonical architectural overview. Product framing lives in [`README.md`](../../README.md); implementation contracts live under [`docs/specs/`](../specs/).

## Layered Model

1. Interface layer
- `colosseum.main`: FastAPI app factory and static asset mounting.
- `colosseum.api.*`: HTTP routes, streaming protocol, persona APIs, quota APIs.
- `colosseum.cli`: Terminal workflows, live debate/review execution UX, interactive interview wizards.
- `colosseum.monitor`: tmux-based live monitoring of active debates.

2. Application layer
- `colosseum.services.orchestrator.ColosseumOrchestrator`: run lifecycle composition.
- `colosseum.services.debate.DebateEngine`: round execution and prompt assembly.
- `colosseum.services.judge.JudgeService`: plan scoring, agenda selection, adjudication, verdicts.
- `colosseum.services.report_synthesizer.ReportSynthesizer`: final report generation.
- `colosseum.services.review_orchestrator.ReviewOrchestrator`: multi-phase code review workflow.

3. Domain model layer
- `colosseum.core.models`: typed runtime artifacts, requests, budgets, persona metadata, and lifecycle helpers.
- `colosseum.core.config`: depth profiles, review phase definitions, artifact paths, and system constraints.

4. Infrastructure layer
- `colosseum.services.repository.FileRunRepository`: file-backed persistence under `.colosseum/runs/`.
- `colosseum.services.provider_runtime.ProviderRuntimeService`: provider execution, fallback, and quota recovery.
- `colosseum.services.context_bundle.ContextBundleService`: frozen bundle construction and prompt rendering.
- `colosseum.services.local_runtime.LocalRuntimeService`: managed Ollama daemon and llmfit hardware fit-checking.
- `colosseum.services.budget.BudgetLedger`: token/cost budget tracking per run.
- `colosseum.services.event_bus.DebateEventBus`: event publishing for streaming and monitoring.
- `colosseum.services.context_media`: image extraction and prompt-safe summarization.
- `colosseum.services.normalizers`: data normalization utilities for debate payloads.

5. Report generation layer
- `colosseum.services.report_synthesizer.ReportSynthesizer`: AI-synthesized final reports.
- `colosseum.services.pdf_report`: PDF export from run artifacts.
- `colosseum.services.markdown_report`: Markdown report export.
- `colosseum.services.review_prompts`: prompt templates for code review phases.

6. Provider layer
- `colosseum.providers.base`: abstract provider interface (`BaseProvider`).
- `colosseum.providers.factory`: provider instantiation, pricing injection, model registry.
- `colosseum.providers.command.CommandProvider`: generic CLI command wrapper.
- `colosseum.providers.cli_wrapper.CliWrapperProvider`: CLI envelope parser with real token extraction.
- `colosseum.providers.cli_adapters`: Claude, Codex, and Gemini CLI adapters.
- `colosseum.providers.mock.MockProvider`: deterministic provider for testing.

## Core Invariants

- A run must have at least one unique agent.
- Planning only begins after a context bundle has been frozen.
- Debate only begins after plans exist.
- Human-judge actions must satisfy their own payload requirements before orchestration.
- Binary attachments remain out of text prompts and are only referenced through summarized metadata.
- Runtime status changes must refresh `updated_at`.
- Code review phases execute sequentially; each phase runs an independent mini-debate.

## Runtime Flow

### Debate Flow
1. `RunCreateRequest` enters through API or CLI.
2. The orchestrator validates provider selectability and judge configuration.
3. Context sources are frozen into a deterministic bundle with checksums.
4. Every agent generates an independent plan from the same bundle.
5. The judge either finalizes or schedules bounded rounds with an explicit agenda.
6. Debate rounds produce adjudication artifacts and update the budget ledger.
7. The judge finalizes a winner or merged plan and the report synthesizer emits the final report.
8. All artifacts are persisted under `.colosseum/runs/<run_id>/`.
9. Token usage and estimated costs are tracked per agent and displayed in results.

### Code Review Flow
1. `ReviewCreateRequest` enters through CLI.
2. The review orchestrator iterates through selected phases (A-F).
3. Each phase runs a mini-debate among reviewer agents with phase-specific prompts.
4. Phase results are aggregated into a comprehensive review report.
5. Reports can be exported as Markdown and saved to `.colosseum/reviews/`.

## Refactor Boundaries

The current codebase intentionally centralizes contracts and splits composition at the following seams:

- `api/validation.py`: shared request validation for blocking and streaming APIs.
- `api/signals.py`: lifecycle-safe skip/cancel signal registry.
- `api/sse.py`: streaming payload serialization with cost tracking.
- `personas/registry.py`: typed persona metadata, legacy Markdown parsing, optional frontmatter support.
- `services/context_media.py`: shared image extraction and prompt-safe summarization.
- `services/normalizers.py`: reusable data normalization for debate payloads.

## Extension Points

- Add new provider types by extending `ProviderType`, `ProviderConfig`, and `providers/factory.py`.
- Add new debate policy or judge heuristics in `JudgeService` and `DebateEngine` while keeping `RunCreateRequest` stable.
- Add new personas through the registry contract described in [`docs/specs/persona-authoring.md`](../specs/persona-authoring.md).
- Add agent governance fields by extending the models and the contract in [`docs/specs/agent-governance.md`](../specs/agent-governance.md).
- Add new code review phases by extending `ReviewPhase` in config and adding prompts in `review_prompts.py`.
- Add new report formats by following the pattern in `pdf_report.py` and `markdown_report.py`.
- Add local model backends by extending `LocalRuntimeService` and the provider factory.

## Artifact Storage

```
.colosseum/
├── runs/                # Debate run artifacts
│   └── <run_id>/
│       ├── run.json     # Full run state
│       ├── context_bundle.json
│       ├── task.json
│       ├── plans/
│       ├── debate/
│       └── judge/
├── reviews/             # Code review reports (Markdown)
└── state/               # Provider quotas, local runtime settings
    └── local_runtime.json
```
