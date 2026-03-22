# Colosseum Promotional Posts

## 1. Reddit r/LocalLLaMA Post

**Title:** Colosseum: Watch Multiple Local LLMs Debate the Same Topic Side-by-Side (With Evidence Tracking)

**Body:**

Hey folks! I built Colosseum, an open-source multi-agent debate arena where you can pit **Claude, GPT, Gemini, Ollama, or HuggingFace GGUF models against each other** on any topic you want. All using the same context, same rules, same fairness.

**What makes it cool:**

- **Local-first**: Full support for Ollama + HuggingFace GGUF models. Run your own Mistral, Llama 2, or whatever you prefer without API calls or API costs.
- **Evidence-first debates**: Claims must be grounded. The judge (AI, human, or automated) tracks evidence quality, so you see *why* an argument won rather than just vibes.
- **20+ personality modes**: Elon Musk, Andrew Ng, Karpathy, etc. Each model argues *like* them—not as themselves, but adopting their communication style and perspective.
- **Three judge modes**: Let AI auto-judge, have a human curator decide, or use Claude as the arbiter.
- **CLI + Web UI**: Run debates from terminal or browser. Export to PDF/Markdown.

**Quick CLI example:**
```bash
colosseum debate \
  -t "Is AI safety more important than capability?" \
  -g ollama:mistral ollama:neural-chat claude:claude-sonnet-4-6 \
  -j claude:claude-opus-4-6
```

**Bonus features:**
- Upload a chat log → automatically generate a debate persona that matches each speaker's style
- Custom persona builder: take an AI interview and it learns *how you argue*
- Code review mode: 6-phase structured review of pull requests
- MIT licensed, Python + FastAPI under the hood

It's free, no sign-ups, works offline. Repo: https://github.com/Bluear7878/Colosseum

Would love feedback from the local LLM community!

---

## 2. Reddit r/artificial Post

**Title:** Colosseum: An Open-Source Debate Arena Where AI Models Argue in Real-Time (Evidence-Tracked, 20+ Personas)

**Body:**

Colosseum is an open-source platform that lets you watch AI models debate any topic with **structured, evidence-grounded arguments**. Think of it as a research tool meets competitive LLM benchmark.

**The core idea:**
- Drop a debate prompt
- Select which AI models you want (Claude, GPT-4, Gemini, local Ollama, HuggingFace models—all on equal footing)
- Pick personas (Elon, researcher, economist, ethicist, etc.)
- Watch them argue *while the judge tracks evidence quality*

**Why it matters:**
- **Bias detection**: See how different models handle the same question differently
- **Evidence matters**: Claims must be grounded. No hand-waving. Judge sees what evidence each side cites.
- **Personas aren't roleplay**: They're communication styles learned from 20+ real public figures and professions
- **Traceable**: Full artifact trail — plans, round transcripts, adopted arguments, verdict

**Unique features:**
- Upload a real chat conversation → auto-generate a custom debate persona
- Three judge modes: automated AI, human curator, or Claude
- Code review debates (6-phase structured review)
- Free, local models supported, MIT licensed

Use cases: research, education, testing model behavior, understanding argument quality across different AI systems, learning how different perspectives frame the same issue.

GitHub: https://github.com/Bluear7878/Colosseum

---

## 3. Hacker News "Show HN" Post

**Title:** Show HN: Colosseum – Open-Source Multi-Model Debate Arena with Evidence Tracking

**Body:**

Colosseum is an open-source debate platform where multiple AI models argue the same topic while a judge tracks evidence quality.

**What it does:**
- Run debates between Claude, GPT, Gemini, Ollama, or HuggingFace models
- 20+ personas (Elon, Karpathy, economist, etc.) shape communication style
- Judge (AI, human, or automated) grades claims based on evidence
- Upload chat logs to auto-generate custom debate personas
- Export results to PDF/Markdown
- Works locally (Ollama + GGUF support, no external APIs required)

**Technical stack:** Python + FastAPI, web UI + CLI, MIT licensed.

Useful for: understanding model differences, testing reasoning quality, bias detection, code review, research.

GitHub: https://github.com/Bluear7878/Colosseum

---

## 4. Twitter/X Thread

**Tweet 1:**
Meet Colosseum: An open-source debate arena where multiple AI models argue the *same topic* with the *same context*.

No cherry-picking outputs. No hidden prompts. Just pure, structured, evidence-first debates.

Let's show you what it does 🧵

**Tweet 2:**
You pick:
- The debate topic
- Which models compete (Claude, GPT, Gemini, Ollama, HuggingFace GGUF)
- The personas they adopt (Elon, Karpathy, economist, researcher...)
- Who judges (AI, human, or Claude)

Then watch them go. 🔥

**Tweet 3:**
Here's the key: *Evidence matters*.

Each model makes a claim → judge tracks where it comes from → grades it on evidence quality. No more "this sounds good but is it true?"

You see *why* an argument won, not just that it did.

**Tweet 4:**
Bonus features:
✅ Upload a chat → auto-generate personas from real speakers
✅ Code review mode (6-phase structured review)
✅ Local models (Ollama + HuggingFace GGUF, run fully offline)
✅ CLI + Web UI
✅ PDF/Markdown reports
✅ MIT licensed, Python + FastAPI

**Tweet 5:**
Use cases: Research bias in models. Understand reasoning differences. Test argument quality. Learn how different perspectives frame the same issue. Build custom debate personas from your own arguments.

**Tweet 6:**
Open-source, free, no sign-ups, works locally.

Check it out: https://github.com/Bluear7878/Colosseum

Star if you find it useful. We're looking for feedback from the AI community. 🚀

---
