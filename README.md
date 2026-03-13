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
Generate personas from surveys, write custom ones, or use builtins. Attach different personas to different agents.

</td>
<td width="50%" valign="top">

### ⚖️ Three Judge Modes
**Automated** heuristic judge, **AI-powered** judge (any model), or **human** judge with pause/resume flow.

### 📈 Evidence-First Debate
Claims must be grounded. Unsupported assertions are penalized. The judge tracks evidence quality per round.

### 💎 Executive Reports
AI-synthesized final reports with key conclusions, verdict explanations, debate highlights, and recommendations.

</td>
</tr>
</table>

---

## 🚀 Quickstart

### Installation

```bash
# Install in editable mode
python -m pip install -e .

# With dev tools
python -m pip install -e '.[dev]'
```

### Launch the Web UI

```bash
colosseum serve
```

Open **http://127.0.0.1:8000/** and you're ready to go.

### Run from CLI

```bash
# Quick mock debate
colosseum debate --topic "Should we refactor the provider layer?" --mock --depth 1

# Real multi-model debate
colosseum debate \
  --topic "Best migration strategy for a vendor-neutral provider layer" \
  -g claude:claude-sonnet-4-6 codex:o3 ollama:llama3.3

# Inspect a past run
colosseum show <run_id>
```

<details>
<summary><b>📡 API Usage</b></summary>

```bash
# Create a run
curl -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d @examples/demo_run.json

# Fetch a run
curl http://127.0.0.1:8000/runs/<run_id>

# Stream a live run
curl -N -X POST http://127.0.0.1:8000/runs/stream \
  -H 'content-type: application/json' \
  -d @examples/demo_run.json
```

</details>

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

### Judge Modes

| Mode | Description |
|---|---|
| 🤖 **Automated** | Heuristic judge with budget, novelty, convergence, and evidence checks |
| 🧠 **AI** | Provider-backed judge — choose any available model as the judge |
| 👤 **Human** | Pause after planning or after rounds; wait for explicit human action |

### Verdict Options

The final verdict can be: **one winning plan**, a **merged plan**, or a **targeted revision** request.

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

> Large text bundles are clipped to a prompt budget. Image bytes are preserved in the frozen bundle and provider input package but not dumped into text prompts.

---

## 🔌 Provider Support

| Provider | Type | Notes |
|---|---|---|
| **Claude** | CLI wrapper | Requires `claude` CLI |
| **Codex** | CLI wrapper | Requires `codex` CLI |
| **Gemini** | CLI wrapper | Requires `gemini` CLI |
| **Ollama** | Local | Requires `ollama` daemon |
| **Mock** | Built-in | Deterministic outputs for tests |
| **Custom** | CLI command | Bring your own model/command |

Custom models can be marked as free or paid, tied into the persona flow, and participate in the same debate process as builtin agents.

---

<details>
<summary><h2>🗂️ API Reference</h2></summary>

### Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/setup/status` | Setup status |
| `POST` | `/setup/install/{tool}` | Install a provider tool |
| `GET` | `/models` | List available models |
| `POST` | `/runs` | Create a run (blocking) |
| `POST` | `/runs/stream` | Create a run (streaming) |
| `GET` | `/runs` | List all runs |
| `GET` | `/runs/{run_id}` | Get run details |
| `POST` | `/runs/{run_id}/judge-actions` | Submit judge action |
| `GET` | `/runs/{run_id}/report/pdf` | Download PDF report |

### Persona Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/personas` | List all personas |
| `POST` | `/personas` | Create custom persona |
| `POST` | `/personas/generate` | Generate from survey |
| `GET` | `/personas/{id}` | Get persona details |
| `DELETE` | `/personas/{id}` | Delete a persona |

### Quota Endpoints

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
├── api/            # FastAPI routes
├── core/           # Typed schemas and config
├── personas/       # Builtin and custom persona support
├── providers/      # Provider abstraction and wrappers
├── services/       # Orchestrator, judge, debate, context, repository
│   ├── debate.py
│   ├── judge.py
│   ├── orchestrator.py
│   ├── pdf_report.py
│   └── report_synthesizer.py
└── web/            # Static web UI assets

docs/
└── colosseum_spec.md

examples/
└── demo_run.json   # Mock-provider smoke test payload

tests/
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

---

<div align="center">

**⚔️ Let the models fight. Let the evidence win. ⚔️**

*Built for people who want structured answers, not chat noise.*

</div>
