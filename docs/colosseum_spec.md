# Colosseum Product Specification

## Product definition

**Project name**: Colosseum  
**Initial task/topic**: Codebase-aware provider abstraction redesign for an existing AI application  
**Codebase/context source**: Local repository snapshots, inline briefs, architecture docs, and URL references frozen into a shared bundle  
**Preferred stack or constraints**: Python 3.11+, FastAPI, file-backed artifacts, provider-neutral orchestration

Colosseum is a planning and arbitration platform that runs the same task through multiple model agents, freezes the shared context package for fairness, orchestrates a bounded multi-round evidence-first debate, and produces a final winning or synthesized plan with traceable evidence and budget reporting.

### Primary users

- Product and engineering leads comparing implementation strategies
- Researchers comparing model reasoning on design or codebase tasks
- Teams that want a human-judge fallback instead of opaque automated selection

### Product goals

- Make independent multi-model planning comparable and auditable
- Improve result quality through bounded structured debate instead of open-ended chat
- Force debate quality to come from objective evidence and explicit uncertainty, not rhetoric
- Keep cost predictable through explicit budgets, summaries, and stop rules
- Support both codebase-driven and research/design task types

### Non-goals for the MVP

- Full workflow execution beyond planning, debate, and synthesis
- Automatic browsing and ingestion of arbitrary external websites
- Long-term experiment analytics dashboards
- Heavyweight database infrastructure before the product shape is proven

## Architecture

### Top-level services

- **API layer**: accepts run creation, artifact inspection, and human judge actions
- **Web UI**: lightweight local dashboard for run creation, comparison, and human judging
- **Context bundle service**: freezes the exact input package and hashes it for fairness
- **Provider abstraction layer**: executes independent model calls behind a shared contract
- **Orchestrator**: owns the run state machine from intake through verdict
- **Debate engine**: runs round-based critique, rebuttal, synthesis, and targeted revision loops
- **Judge service**: evaluates plans, decides whether more rounds are worthwhile, and issues final verdicts
- **Artifact repository**: persists task state, plans, rounds, and verdicts as JSON

### Architectural decisions

- **File-backed artifact store first**: simpler than adding a DB while preserving traceability
- **Provider-neutral interface**: debate and judge logic never depend on a specific vendor SDK
- **Summary-based memory**: later rounds consume compact summaries, not full transcripts
- **Judge as controller**: the judge owns stop/go decisions based on disagreement, novelty, and budget
- **Evidence-first premise**: unsupported claims are treated as lower-value than explicit source-backed claims or clearly labeled inference

### Core modules and responsibilities

- `core/models.py`: typed schemas for every major artifact
- `providers/base.py`: provider contract
- `providers/mock.py`: deterministic local provider for tests and demos
- `providers/command.py`: subprocess-backed integration for CLI agents or wrappers
- `services/context_bundle.py`: freezing and rendering shared context
- `services/debate.py`: debate-round execution and novelty scoring
- `services/judge.py`: plan evaluation, stop rules, human packets, verdict logic
- `services/orchestrator.py`: run lifecycle and state transitions
- `services/repository.py`: artifact persistence
- `api/routes.py`: HTTP surface

### Provider abstraction layer

Provider contract:

- Input: `operation`, `instructions`, `metadata`
- Output: normalized `content`, optional structured `json_payload`, and `usage`

Provider implementations in the MVP:

- `mock`: deterministic structured outputs for local development
- `command`: subprocess integration for local CLIs, wrappers, or model runners

Planned next providers:

- OpenAI/API-backed provider
- Anthropic/API-backed provider
- Gemini/API-backed provider
- Batch/offline provider for asynchronous runs

## Workflow

### 1. Task intake

- Accept task title, problem statement, success criteria, constraints, judge mode, budget policy, and agent list.
- Validate that each agent has a provider configuration.
- Create a run artifact immediately so partial failures are still traceable.

### 2. Context loading and freezing

- Resolve each context source.
- For inline text: store exact text.
- For local files: read and hash content.
- For local directories: collect a bounded manifest and selected file excerpts.
- For URLs: freeze metadata or pre-snapshotted content if supplied upstream.
- Produce a bundle checksum and summary.

### 3. Independent plan generation

- Build one shared planning packet from the task and frozen context.
- Send the same packet to every provider independently.
- Do not expose any peer plan during this phase.
- Normalize all outputs into the same `PlanDocument` schema.
- Require plans to provide an explicit `evidence_basis` section listing the strongest objective anchors from the frozen bundle.
- Score plans heuristically so the judge has an initial comparison baseline.

### 4. Debate rounds

- Judge determines whether debate is needed.
- If needed, debate runs in bounded rounds with a fixed purpose.
- Each agent gets its own plan, peer plan summaries, and compact memory from prior rounds.
- Each agent contributes at most one structured message per round in the MVP.
- Novelty is scored against previous content from the same agent and current round messages.
- Critique and defense claims are expected to carry evidence arrays; unsupported claims reduce judge confidence.

### 5. Judge decisions

- After planning and after every round, judge evaluates:
  - disagreement level
  - score separation
  - novelty
  - convergence
  - budget pressure
- Judge either finalizes, requests another round, or requests targeted revision.

### 6. Final synthesis

- Verdict can be a single winner, a merged plan, or a targeted revision request.
- Final output includes plan artifacts, debate artifacts, verdict reasoning, budget usage, and stop reason.

## Data model

### Task

- `TaskSpec`: title, problem statement, task type, success criteria, constraints, desired output

### Context sources

- `ContextSourceInput`: source metadata and ingest settings
- `FrozenContextSource`: resolved source, checksum, fragments, metadata
- `FrozenContextBundle`: bundle checksum, summary, frozen source list

### Plans

- `PlanDocument`: summary, evidence basis, assumptions, architecture, implementation strategy, risks, strengths, weaknesses, trade-offs, questions, usage
- `PlanEvaluation`: rubric scores and overall score for initial comparison

### Debate

- `AgentMessage`: structured critique, defense, concessions, hybrid suggestions, novelty score
- `DebateRound`: round purpose, messages, summary, usage
- `RoundSummary`: agreements, disagreements, strongest arguments, hybrid opportunities, unresolved questions

### Judge

- `JudgeDecision`: continue/finalize/revise decision with confidence and budget pressure
- `JudgeVerdict`: winner or merged plan, rationale, confidence, stop reason
- `HumanJudgePacket`: side-by-side plan cards and concise debate snapshot for human review

### Budgets and logs

- `BudgetPolicy`: max rounds, total token budget, per-round cap, novelty threshold, convergence threshold
- `BudgetLedger`: total, by actor, by round, exhaustion state
- `ExperimentRun`: top-level artifact that links every component and state transition

## Debate protocol

Round sequence in the MVP:

1. **Critique**
   - Goal: surface the most consequential weaknesses in each plan
   - Inputs: own plan, peer summaries, frozen context summary, no prior transcript replay
   - Output: critique claims, defense seed, concessions if any
2. **Rebuttal**
   - Goal: defend core choices, concede valid criticism, sharpen trade-offs
   - Output: strongest defenses and updated hybrid suggestions
3. **Synthesis**
   - Goal: propose merged solutions that retain strengths and reduce risk
   - Output: hybrid proposals and unresolved issues
4. **Final comparison**
   - Goal: state which plan or hybrid should win and why
   - Output: concise comparison arguments only
5. **Targeted revision** (conditional)
   - Goal: address one isolated unresolved issue without reopening the full debate

Protocol rules:

- One message per agent per round in the MVP
- Message budget bounded by provider or orchestrator settings
- Novelty checks penalize repeated points
- Evidence quality matters more than rhetorical force; agents should cite the frozen bundle or state uncertainty
- Round summaries become the only carried memory by default
- Judge can skip directly to synthesis or finalization if disagreement is already low

## Judge protocol

### Supported modes

- **Automated judge**: default heuristic controller
- **AI judge**: provider-backed judge using the same abstraction layer
- **Human judge**: user controls whether to continue, merge, revise, or finalize

### Automated judge decision inputs

- Initial plan evaluation scores
- Score gap between top plans
- Number and severity of unresolved disagreements
- Average novelty in the latest round
- Evidence support in plans and debate claims
- Convergence signal from agreements vs disagreements
- Remaining token budget and round budget

### Automated judge outputs

- Continue debate with next round purpose
- Finalize with one winner
- Finalize with merged plan
- Request targeted revision

### Human judge interaction flow

1. User creates a run in `human` judge mode.
2. System generates plans and pauses.
3. UI or client shows:
   - comparable plan cards
   - overall score hints
   - strongest arguments
   - unresolved disagreements
   - recommended next action
4. User chooses one action:
   - request another round
   - select winner
   - merge plans
   - request targeted revision
5. System updates the run and returns a refreshed human packet.

## Cost-control strategy

### Hard limits

- Maximum rounds
- Total token budget
- Per-round token budget
- One message per agent per round in the MVP

### Soft limits

- Novelty threshold
- Convergence threshold
- Judge confidence threshold for early stopping

### Efficiency mechanisms

- Summary-based memory between rounds
- Early stop when plans are already clearly separated
- Early stop when novelty collapses
- Early stop when budget pressure becomes too high
- Merged-plan finalization instead of additional rounds when top plans are close
- Targeted revision instead of full debate when the unresolved issue is narrow

## MVP implementation plan

### MVP scope

- Backend-only service
- Static local web UI on top of the API
- File-backed artifact persistence
- `mock` and `command` providers
- Automated judge plus human-judge API flow
- Structured plan and debate schemas
- Heuristic plan evaluation and judge logic

### Advanced path

- Add API-backed providers for external vendors
- Add asynchronous jobs and queue-backed execution
- Add richer context fetchers and snapshot storage
- Add a web UI for human judging
- Add experiment comparison dashboards and benchmark suites
- Add learned or rubric-driven quality evaluators

### Suggested tech stack

- **Python 3.11**: strong ecosystem for orchestration and AI tooling
- **FastAPI**: simple typed API surface
- **Pydantic v2**: shared runtime and persistence schemas
- **File-based JSON artifacts** for MVP traceability
- **uvicorn** for serving
- **pytest** for core service tests

### Pseudocode

```python
async def create_run(request):
    run = init_run(request)
    run.context_bundle = freeze_context(request.context_sources)
    run.plans = await gather(generate_plan(agent) for agent in run.agents)
    run.plan_evaluations = evaluate_plans(run.plans)

    if run.judge.mode == HUMAN:
        run.status = AWAITING_HUMAN_JUDGE
        run.human_packet = build_human_packet(run)
        save(run)
        return run

    while True:
        decision = judge.decide(run)
        run.judge_trace.append(decision)
        if decision.action == FINALIZE:
            run.verdict = judge.finalize(run, decision)
            run.status = COMPLETED
            save(run)
            return run

        if not budget.can_start_round(run):
            run.verdict = judge.finalize(run)
            run.status = COMPLETED
            save(run)
            return run

        debate_round = debate.run_round(run, decision.next_round_type)
        run.debate_rounds.append(debate_round)
        save(run)
```

## Risks and failure modes

- **Schema drift across providers**: command-backed agents may return poor structure
  - Mitigation: normalization layer and stricter schema validation later
- **Context overload**: directory bundles may become too large
  - Mitigation: bounded file counts, per-file truncation, later retrieval-based pruning
- **Heuristic judge bias**: automated scoring can overvalue format completeness
  - Mitigation: human judge mode, AI judge option, later benchmark calibration
- **Repetitive debate**: agents can restate the same claims
  - Mitigation: novelty score and summary-based memory
- **Cost estimate mismatch**: command providers may not return exact token usage
  - Mitigation: approximate token estimator and optional pricing metadata
- **Artifact sprawl**: many runs can create many JSON files
  - Mitigation: retention policies and pluggable storage backends later

## Suggested next steps

1. Add one real provider integration, preferably the provider already used by your team.
2. Add pytest coverage for context freezing, automated judge stopping rules, and human-judge actions.
3. Add a small web UI that consumes `HumanJudgePacket`.
4. Introduce background jobs for longer-running debates.
5. Build evaluation datasets comparing Colosseum vs single-model planning outcomes.
