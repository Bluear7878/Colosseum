<div align="center">

# ⚔️ Colosseum

**Multi-Agent Debate Arena — Let AI Models Fight It Out**

*Run the same task through multiple model agents, freeze a shared context bundle,*
*generate independent plans, run an evidence-first debate, and produce a judge-backed verdict.*

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

---

🏛️ **Fair** · 🔍 **Traceable** · 💰 **Cost-Controlled** · 📊 **Evidence-First** · 🔌 **Extensible**

</div>

<br>

## 🎯 Why Colosseum?

> Not just another chatbot UI — Colosseum is a **structured debate platform** designed for real workflows.

| Problem | Colosseum's Answer |
|---|---|
| "Which model gives a better plan?" | Run them side by side on the **same frozen context** |
| "How do I compare fairly?" | Independent plan generation — no agent sees another's plan first |
| "Debates go in circles forever" | Bounded rounds with **novelty checks**, convergence detection, and budget limits |
| "I can't trace how a decision was made" | Full artifact trail: plans, rounds, judge agendas, adopted arguments, verdicts |
| "I want control over judging" | Choose **automated**, **AI judge**, or **human judge** mode |
| "I need a code review, not just a debate" | Multi-phase **code review** with 6 configurable review phases |

---

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

### 🧊 Frozen Context Bundles
Every agent gets the exact same input — text, files, directories, URLs, and images — frozen before planning begins.

### 🤖 Multi-Provider Support
Claude · Codex · Gemini · Ollama · Custom CLIs
Mix and match providers in the same debate.

### 🎭 Persona System
20+ built-in personas (Karpathy, Andrew Ng, Elon Musk, and more), generate personas from surveys, or write custom ones.

### 📝 Multi-Phase Code Review
6 configurable review phases: project rules, implementation, architecture, security/performance, test coverage, and red team adversarial testing.

</td>
<td width="50%" valign="top">

### ⚖️ Three Judge Modes
**Automated** heuristic judge, **AI-powered** judge (any model), or **human** judge with pause/resume flow.

### 📈 Evidence-First Debate
Claims must be grounded. Unsupported assertions are penalized. The judge tracks evidence quality per round.

### 💎 Executive Reports
AI-synthesized final reports with key conclusions, verdict explanations, and debate highlights. Export to **PDF** or **Markdown**.

### 💰 Token & Cost Tracking
Real token counts from provider output with per-agent cost breakdown. Always-on cost display in CLI results.

### 📺 Live Monitoring
tmux-based live monitor panel for watching debates in real time.

</td>
</tr>
</table>

---

## 🧭 Documentation Map

The README is the product-facing overview. The canonical engineering docs live in `docs/`.

| Document | Description |
|---|---|
| [`docs/colosseum_spec.md`](docs/colosseum_spec.md) | Specification index and entry point |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | Layered architectural model |
| [`docs/architecture/design-philosophy.md`](docs/architecture/design-philosophy.md) | Core design principles and non-goals |
| [`docs/specs/runtime-protocol.md`](docs/specs/runtime-protocol.md) | Run lifecycle, streaming contract, cost tracking |
| [`docs/specs/agent-governance.md`](docs/specs/agent-governance.md) | Agent, persona, and provider boundaries |
| [`docs/specs/persona-authoring.md`](docs/specs/persona-authoring.md) | Persona file formats and validation |

---

## 🚀 Quickstart

### Installation

```bash
# Install in editable mode
python -m pip install -e .

# With dev tools
python -m pip install -e '.[dev]'
```

### Provider Setup

```bash
# Interactive setup — install & authenticate all supported CLI providers
colosseum setup

# Set up specific providers only
colosseum setup claude codex

# Verify installed tools
colosseum check
```

### Launch the Web UI

```bash
colosseum serve
```

Open **http://127.0.0.1:8000/** and you're ready to go.

### Run a Debate from CLI

```bash
# Quick mock debate (no real providers needed)
colosseum debate --topic "Should we refactor the provider layer?" --mock --depth 1

# Real multi-model debate
colosseum debate \
  --topic "Best migration strategy for a vendor-neutral provider layer" \
  -g claude:claude-sonnet-4-6 codex:o3 ollama:llama3.3

# With an AI judge and live monitoring
colosseum debate \
  --topic "Monolithic vs microservices" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -j claude:claude-opus-4-6 --monitor

# With human judge
colosseum debate \
  --topic "Database migration strategy" \
  -g claude:claude-sonnet-4-6 codex:o4-mini \
  -j human
```

### Run a Code Review

```bash
# Multi-phase code review with default phases (A-E)
colosseum review \
  -t "OAuth implementation review" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  --dir ./src

# Include red team phase and specific files
colosseum review \
  -t "Payment module security review" \
  -g claude:claude-sonnet-4-6 codex:o3 \
  --phases A B C D E F \
  -f src/payment.py src/auth.py
```

---

## 🖥️ CLI Commands

```
colosseum setup [providers...]       Install & authenticate CLI providers
colosseum serve                      Start the web UI server
colosseum debate                     Run a debate from the terminal
colosseum review                     Run a multi-phase code review
colosseum monitor [run_id]           Open live tmux monitor for an active debate
colosseum models                     List available models across all providers
colosseum personas                   List available personas
colosseum history                    List past battles
colosseum show <run_id>              Show a past battle result
colosseum delete <run_id|all>        Delete battle run(s)
colosseum check                      Verify CLI tool availability
colosseum local-runtime status       Inspect managed local-model runtime state
```

### Debate Options

| Flag | Description |
|---|---|
| `-t`, `--topic` | Debate topic (required) |
| `-g` | Gladiators in `provider:model` format (min 2) |
| `-j`, `--judge` | Judge model (`provider:model` or `human`) |
| `-d`, `--depth` | Debate depth 1-5 (default: 3) |
| `--dir` | Project directory for context |
| `-f` | Specific files for context |
| `--mock` | Use mock providers (free, for testing) |
| `--monitor` | Launch tmux monitor panel |
| `--timeout` | Per-phase timeout in seconds |

### Review Options

| Flag | Description |
|---|---|
| `-t`, `--topic` | Review target description (required) |
| `-g` | Reviewer agents in `provider:model` format (min 2) |
| `--phases` | Review phases to run (default: `A B C D E`) |
| `-j`, `--judge` | Judge model |
| `-d`, `--depth` | Per-phase debate depth (default: 2) |
| `--dir` | Project directory to review |
| `-f` | Specific files to review |
| `--diff` | Include recent git diff as context |
| `--lang` | Response language (`ko`, `en`, `ja`, etc.) |
| `--rules` | Path to project rules file |
| `--timeout` | Per-phase timeout in seconds |

---

## 🏗️ How a Run Works

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  📋 Task    │───▶│  🧊 Freeze  │───▶│  📝 Plan    │───▶│  ⭐ Score   │
│  Intake     │    │  Context    │    │  Generation │    │  Plans     │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                               │
        ┌──────────────────────────────────────────────────────┘
        ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  🎯 Judge   │───▶│  💬 Debate  │───▶│  ⚖️ Adopt   │───▶│  🏆 Verdict │
│  Agenda     │    │  Round      │    │  Arguments  │    │  & Report  │
└──────┬──────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                                      │
       └──────── 🔄 Next issue ◀──────────────┘
```

The orchestrator uses **bounded debate** rather than open-ended chat. The judge can stop early if plans are already well separated, if novelty collapses, or if budget pressure is too high.

---

## ⚖️ Debate Protocol

Each round is **agenda-driven**, not open-ended:

| Step | Description |
|:---:|---|
| **1** | Judge selects one concrete issue |
| **2** | Every agent answers from its own plan |
| **3** | Agents must rebut or accept specific peer arguments |
| **4** | Judge adopts the strongest evidence-backed arguments |
| **5** | Judge either advances to the next issue or finalizes |

### Default Round Types

`critique` → `rebuttal` → `synthesis` → `final_comparison` → `targeted_revision`

Each round records: the judge's agenda, all agent messages, adopted arguments, and what remained unresolved.

### Depth Profiles

| Depth | Name | Novelty Threshold | Convergence | Notes |
|:---:|---|:---:|:---:|---|
| 1 | Quick | 5% | 40% | Eager finalization |
| 2 | Brief | 10% | 55% | |
| 3 | Standard | 18% | 75% | Default |
| 4 | Thorough | 25% | 85% | Min 2 rounds |
| 5 | Deep Dive | 30% | 92% | Min 2 rounds, hard stop |

### Judge Modes

| Mode | Description |
|---|---|
| 🤖 **Automated** | Heuristic judge with budget, novelty, convergence, and evidence checks |
| 🧠 **AI** | Provider-backed judge — choose any available model as the judge |
| 👤 **Human** | Pause after planning or after rounds; wait for explicit human action |

### Verdict Options

The final verdict can be: **one winning plan**, a **merged plan**, or a **targeted revision** request.

---

## 📝 Code Review Phases

| Phase | Name | Focus |
|:---:|---|---|
| **A** | Project Rules | Coding conventions, naming, linter/formatter rules |
| **B** | Implementation | Functional correctness, edge cases, error handling |
| **C** | Architecture | Design patterns, module separation, dependencies, extensibility |
| **D** | Security/Performance | Vulnerabilities, memory leaks, performance bottlenecks, concurrency |
| **E** | Test Coverage | Unit tests, integration tests, test structure |
| **F** | Red Team | Adversarial inputs, auth bypass, information leakage, privilege escalation (opt-in) |

Each phase runs a mini-debate among the reviewer agents. Results are aggregated into a comprehensive review report (Markdown export available).

---

## 🧊 Context Bundle Support

| Source Kind | Description |
|---|---|
| `inline_text` | Raw text passed directly |
| `local_file` | Single file from disk |
| `local_directory` | Entire directory snapshot |
| `external_reference` | URL frozen as metadata |
| `inline_image` | Base64-encoded image data |
| `local_image` | Image file from disk |

> Large text bundles are clipped to a prompt budget (28,000 chars max). Image bytes are preserved in the frozen bundle but not dumped into text prompts.

---

## 🔌 Provider Support

| Provider | Type | Notes |
|---|---|---|
| **Claude** | CLI wrapper | Requires `claude` CLI. Models: opus-4-6, sonnet-4-6, haiku-4-5 |
| **Codex** | CLI wrapper | Requires `codex` CLI. Models: gpt-5.4, o3, o4-mini |
| **Gemini** | CLI wrapper | Requires `gemini` CLI. Models: 2.5-pro, 3.1-pro, 3-flash |
| **Ollama** | Local | Requires `ollama` daemon. Auto-discovers installed models |
| **Mock** | Built-in | Deterministic outputs for tests |
| **Custom** | CLI command | Bring your own model/command |

Custom models can be marked as free or paid, tied into the persona flow, and participate in the same debate process as builtin agents.

### Local Runtime Management

Colosseum manages a local **Ollama** runtime with:
- GPU device detection (NVIDIA, AMD, CPU)
- Per-GPU model fit checking via `llmfit`
- Auto-start/stop daemon management
- Model download orchestration

```bash
colosseum local-runtime status
```

---

<details>
<summary><h2>🗂️ API Reference</h2></summary>

### Setup & Discovery

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/setup/status` | Provider install/auth status |
| `GET` | `/models` | List available models |
| `POST` | `/models/refresh` | Force model re-probe |
| `GET` | `/cli-versions` | CLI version info |
| `POST` | `/setup/auth/{tool_name}` | Launch provider login |
| `POST` | `/setup/install/{tool_name}` | Install a provider tool |

### Local Runtime

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/local-runtime/status` | Ollama/llmfit status (`?ensure_ready=false`) |
| `POST` | `/local-runtime/config` | Update local runtime settings |
| `POST` | `/local-models/download` | Download a local model |
| `GET` | `/local-models/fit-check` | llmfit hardware fit check (`?model=...`) |

### Run Management

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/runs` | Create a run (blocking) |
| `POST` | `/runs/stream` | Create a run (streaming SSE) |
| `GET` | `/runs` | List all runs |
| `GET` | `/runs/{run_id}` | Get run details |
| `POST` | `/runs/{run_id}/skip-round` | Skip current debate round |
| `POST` | `/runs/{run_id}/cancel` | Cancel active debate |
| `GET` | `/runs/{run_id}/pdf` | Download PDF report |
| `GET` | `/runs/{run_id}/markdown` | Download Markdown report |
| `POST` | `/runs/{run_id}/judge-actions` | Submit human judge action |

### Persona Management

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/personas` | List all personas |
| `POST` | `/personas/generate` | Generate from survey |
| `GET` | `/personas/{id}` | Get persona details |
| `POST` | `/personas` | Create custom persona |
| `DELETE` | `/personas/{id}` | Delete a persona |

### Quota Management

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/provider-quotas` | Get quota status |
| `PUT` | `/provider-quotas` | Update quotas |

### UI Routes

| Route | Description |
|---|---|
| `GET /` | Arena / run setup screen |
| `GET /reports/{run_id}` | Battle report screen |

</details>

---

<details>
<summary><h2>📂 Repository Layout</h2></summary>

```
src/colosseum/
├── main.py                 # FastAPI app factory and server entry
├── cli.py                  # Terminal interface and live debate UX
├── monitor.py              # tmux-based live monitoring
├── bootstrap.py            # Dependency injection and app init
│
├── api/                    # FastAPI routes
│   ├── routes.py           # Router composition
│   ├── routes_runs.py      # Run CRUD, streaming, judge actions
│   ├── routes_setup.py     # Setup, discovery, local runtime
│   ├── routes_personas.py  # Persona CRUD and generation
│   ├── routes_quotas.py    # Provider quota management
│   ├── sse.py              # SSE payload serialization
│   ├── validation.py       # Shared request validation
│   └── signals.py          # Lifecycle signal registry
│
├── core/                   # Domain types and configuration
│   ├── models.py           # Typed runtime schemas and requests
│   └── config.py           # Enums, defaults, depth profiles, review phases
│
├── providers/              # Provider abstraction layer
│   ├── base.py             # Abstract provider interface
│   ├── factory.py          # Provider instantiation and pricing
│   ├── command.py          # Generic CLI command provider
│   ├── cli_wrapper.py      # CLI envelope parser and adapter
│   ├── cli_adapters.py     # Claude, Codex, Gemini CLI adapters
│   ├── mock.py             # Deterministic mock provider
│   └── presets.py          # Model presets
│
├── services/               # Core business logic
│   ├── orchestrator.py     # Run lifecycle composition
│   ├── debate.py           # Round execution and prompt assembly
│   ├── judge.py            # Plan scoring, agenda, adjudication, verdicts
│   ├── report_synthesizer.py # Final report generation
│   ├── review_orchestrator.py # Multi-phase code review workflow
│   ├── review_prompts.py   # Review phase prompt templates
│   ├── context_bundle.py   # Frozen context construction
│   ├── context_media.py    # Image extraction and summarization
│   ├── provider_runtime.py # Provider execution and quota
│   ├── local_runtime.py    # Managed Ollama/llmfit runtime
│   ├── repository.py       # File-backed run persistence
│   ├── budget.py           # Budget ledger tracking
│   ├── event_bus.py        # Event publishing
│   ├── normalizers.py      # Data normalization utilities
│   ├── prompt_contracts.py # Prompt asset contracts
│   ├── pdf_report.py       # PDF export
│   └── markdown_report.py  # Markdown report export
│
├── personas/               # Persona system
│   ├── registry.py         # Typed persona metadata and parsing
│   ├── loader.py           # Load, cache, resolve personas
│   ├── generator.py        # Generate personas from surveys
│   ├── prompting.py        # Persona prompt rendering
│   ├── builtin/            # 20 built-in personas
│   └── custom/             # User-created personas
│
└── web/                    # Static web UI assets
    ├── index.html          # Arena setup UI
    ├── report.html         # Battle report display
    ├── app.js              # Main UI logic
    ├── report.js           # Report rendering
    └── styles.css          # Styling

docs/
├── colosseum_spec.md       # Specification index
├── architecture/
│   ├── overview.md         # Layered architectural model
│   └── design-philosophy.md # Core design principles
└── specs/
    ├── runtime-protocol.md # Run lifecycle and streaming contract
    ├── agent-governance.md # Agent, persona, provider boundaries
    └── persona-authoring.md # Persona file formats and validation

examples/
└── demo_run.json           # Mock-provider smoke test payload

tests/                      # Test suite
```

</details>

---

## 🧪 Testing

```bash
# Run the full test suite
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q

# Quick syntax validation
python -m compileall src tests
```

---

## ⚠️ Known Limitations

- URL sources are metadata-only unless fetched upstream before run creation
- Paid quota tracking is local/manual, not provider-synchronized
- Builtin vendor CLI wrappers are thinner than full SDK integrations
- Image-aware debates are best supported through custom command providers
- Artifact persistence is file-based, not database-backed
- Token counting falls back to `len//4` estimation when real counts are unavailable

---

<div align="center">

**⚔️ Let the models fight. Let the evidence win. ⚔️**

*Built for people who want structured answers, not chat noise.*

</div>
