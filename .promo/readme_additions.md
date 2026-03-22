# README Additions

These sections are meant to be **inserted into the existing README.md** — not to replace it.
Suggested placement: after `## ✨ Features` and before `## 🧭 Documentation Map`.

---

## 🎬 See It In Action

### Step 1: Pit Claude vs Gemini on a real architecture decision

```bash
colosseum debate \
  -t "Should we use microservices or monolith for a 10-person startup?" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -j claude:claude-opus-4-6
```

> Both models receive the **exact same frozen context** and generate independent plans before seeing each other's work. The judge tracks novelty and evidence quality per round — no circular debates.

---

### Step 2: Run with local models — no API keys needed

```bash
colosseum debate \
  -t "Best database for real-time analytics?" \
  -g ollama:llama3.3 ollama:qwen2.5 \
  --depth 2
```

> Colosseum auto-detects your GPU, checks model fit via `llmfit`, and manages the Ollama daemon. Fully offline, fully free.

---

### Step 3: Open the web arena for a visual experience

```bash
colosseum serve
```

> Opens at **http://127.0.0.1:8000/** — pick models, assign personas, set judge mode, and watch the debate unfold live with real-time SSE streaming.

---

## 🌟 What Makes Colosseum Different

| Other tools | Colosseum |
|---|---|
| Models see each other's output before responding | **Frozen context** — every agent plans independently from the same snapshot |
| Debates run until someone gives up | **Bounded rounds** with novelty checks, convergence detection, and budget limits |
| Verdicts are vibes-based | **Evidence-first judging** — unsupported assertions are penalized; adopted arguments are logged |
| No way to reproduce a result | **Full artifact trail**: plans, round transcripts, judge agendas, adopted arguments, verdict |
| One judge, one mode | Three judge modes: heuristic **automated**, any-model **AI judge**, or **human pause/resume** |

- **vs ChatGPT Arena / lmsys**: Those platforms route a single prompt to two models and ask humans to vote. Colosseum runs a *structured multi-round debate* on a topic you define, with your own context, and produces a traceable verdict with evidence.
- **Personas built-in**: Assign Karpathy, Andrew Ng, a security researcher, or your own custom persona to each gladiator — voices that meaningfully shift argument framing.
- **Code review mode**: Six configurable phases (conventions → implementation → architecture → security → tests → red team) turn the debate engine into a multi-reviewer code audit.
- **Your infra**: Use cloud APIs or local Ollama models interchangeably. No data leaves your machine unless you choose a cloud provider.

---

## 🤝 Community & Support

If Colosseum has been useful to you, a ⭐ on GitHub goes a long way.

- **Bug reports & feature requests** → [GitHub Issues](https://github.com/Bluear7878/Colosseum/issues)
- **Contributions welcome** — PRs for new provider adapters, personas, judge modes, and UI improvements are appreciated. Check [`docs/architecture/overview.md`](docs/architecture/overview.md) before diving in.

---

## 🎥 Demo Script (for screen recording / GIF)

> This sequence is designed to look impressive when recorded at terminal width ~120, with a tool like `vhs`, `asciinema`, or `terminalizer`.

```bash
# 0. Check everything is wired up
colosseum check

# 1. List available personas
colosseum personas

# 2. Start a debate with personas assigned
#    - Claude plays "Pragmatic Engineer" (ship-focused, practical)
#    - Gemini plays "Security Hardliner" (attacks surface area)
#    - Opus judges
colosseum debate \
  -t "Event-driven architecture vs REST for an internal microservices mesh" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -p pragmatic_engineer security_hardliner \
  -j claude:claude-opus-4-6 \
  --depth 2 \
  --monitor

# --- Expected output highlights ---
# ✦ Context frozen: 0 files, inline topic only
# ✦ Plans generated independently (no cross-contamination)
# ✦ Round 1 [critique]   — 2 arguments adopted by judge
# ✦ Round 2 [rebuttal]   — novelty 34%, continuing
# ✦ Round 3 [synthesis]  — convergence 81%, finalizing
# ✦ Verdict: MERGED_PLAN
#   "REST for synchronous control-plane calls; events for data-plane fanout"
# ✦ Cost: claude $0.0041 | gemini $0.0029 | judge $0.0063
# ✦ Report saved → ~/.colosseum/runs/<run_id>/

# 3. Export the report
colosseum show <run_id>
```

> **Tip for recording**: use `--depth 1` to keep the GIF under 60 seconds, then re-run with `--depth 3` for the real thing.
