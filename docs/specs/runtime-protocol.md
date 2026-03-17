# Runtime Protocol Specification

## Run Lifecycle

States:
- `pending`
- `planning`
- `debating`
- `awaiting_human_judge`
- `completed`
- `failed`

Allowed transitions:
- `pending -> planning`
- `planning -> awaiting_human_judge`
- `planning -> debating`
- `planning -> completed`
- `debating -> awaiting_human_judge`
- `debating -> completed`
- `* -> failed`

## Streaming API Contract

The `/runs/stream` endpoint emits Server-Sent Events with a stable `phase` field.

Primary phases:
- `init`
- `context`
- `planning`
- `agent_planning`
- `plan_ready`
- `plan_failed`
- `plans_ready`
- `human_required`
- `judge_decision`
- `debate_round`
- `agent_thinking`
- `agent_message`
- `round_skipped`
- `round_cancelled`
- `round_complete`
- `judging`
- `synthesizing_report`
- `complete`
- `cancelled`
- `error`

Wire-format shaping is centralized in `colosseum.api.sse`. Internal refactors must preserve event names and ordering unless the UI protocol is explicitly versioned.

### Cost Tracking in Streams

The `complete` event payload includes `estimated_cost_usd` with per-actor and total cost breakdowns. Cost data is derived from real token counts (when available from CLI output) or from `len//4` estimation as fallback.

Per-agent `UsageMetrics` include:
- `prompt_tokens`
- `completion_tokens`
- `estimated_cost_usd`

## Context Bundle Rules

- Binary attachments are preserved in the bundle but omitted from text prompts.
- Prompt rendering may truncate fragments for budget control (max 28,000 characters).
- Checksums are used for traceability, not for cryptographic trust guarantees.

## Run Control Actions

### Skip Round

`POST /runs/{run_id}/skip-round` — Signals the orchestrator to skip the current debate round and advance to the next stage.

### Cancel Run

`POST /runs/{run_id}/cancel` — Cancels an active debate run. The run transitions to a terminal state and no further rounds are executed.

## Human Judge Protocol

Actions:
- `request_round`
- `select_winner`
- `merge_plans`
- `request_revision`

Validation:
- `select_winner` requires at least one plan id.
- `merge_plans` requires at least two plan ids.
- `request_round` and `request_revision` may carry free-form instructions.

## Quota and Fallback Rules

- Paid provider selection can be blocked before execution.
- Runtime exhaustion may fail, switch to free fallback, or wait for reset depending on `PaidProviderPolicy` (`fail`, `switch_to_free`, `wait_for_reset`).
- Runtime events are appended to the run artifact for auditability.

## Report Export

Completed runs can be exported in multiple formats:
- `GET /runs/{run_id}/pdf` — PDF report download.
- `GET /runs/{run_id}/markdown` — Markdown report download.

Reports include: task description, agent plans, debate round summaries, adopted arguments, judge verdict, and final synthesized report.

## Depth Profiles

The debate depth controls round behavior and stop criteria:

| Depth | Novelty Threshold | Convergence | Min Rounds | Notes |
|:---:|:---:|:---:|:---:|---|
| 1 | 5% | 40% | — | Eager finalization |
| 2 | 10% | 55% | — | |
| 3 | 18% | 75% | — | Default |
| 4 | 25% | 85% | 2 | |
| 5 | 30% | 92% | 2 | Hard stop enabled |

Minimum evidence support to finalize: 0.6. Low evidence threshold: 0.45.
