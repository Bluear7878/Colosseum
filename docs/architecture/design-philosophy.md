# Design Philosophy

## What Colosseum Optimizes For

Colosseum is not designed to be the fastest way to get a single model answer. It is designed to make high-stakes model comparison auditable, bounded, and operationally sane.

## Principles

### 1. Evidence before rhetoric

The system rewards grounded claims and explicit uncertainty. A fluent answer with weak support is a lower-quality artifact than a narrower answer that clearly states what is known and what is inferred.

### 2. Frozen shared context

All agents should receive the same task context for the same run. Fairness comes from equal context, not from post-hoc prompt tuning.

### 3. Bounded debate

Open-ended agent chat is hard to audit and easy to waste budget on. Colosseum uses agenda-driven rounds with explicit stop rules so every round has a cost and a purpose.

### 4. File-backed transparency first

The repository intentionally keeps run persistence simple and inspectable. JSON artifacts on disk are easier to debug and reason about than a database-heavy stack during product exploration.

### 5. Provider neutrality

Debate and judging logic should not care whether a response came from a mock provider, CLI wrapper, or a future hosted API integration.

### 6. Strict boundary between agent and persona

An agent is an execution unit with provider/runtime policy. A persona is a reusable reasoning style and prompt asset. Personas can grow quickly; runtime behavior should not depend on ad hoc Markdown parsing alone.

### 7. Defensive defaults

Validation should fail early on malformed requests, missing context paths, invalid judge actions, and impossible budget settings. Silent fallback is acceptable only when it is explicit and traceable.

### 8. Cost transparency

Token usage and estimated costs should be tracked and surfaced. Users should always know what a run cost. Real token counts are preferred over estimates; when unavailable, fall back to `len//4` with clear indication.

## Non-Goals

- Hidden magic that changes verdict logic without an artifact trail.
- Implicit browsing or memory filling when evidence is missing.
- Architecture that optimizes for speculative future scale at the cost of present clarity.

## Practical Consequences

- Add typed metadata when a free-form file format starts carrying operational meaning.
- Prefer a new helper module over another hundred lines inside a god file.
- Keep wire formats stable even when internal modules are reorganized.
- Add tests when introducing a new invariant or extension path.
