# Gotchas

A running log of subtle bugs and traps that have bitten this project, and the
guardrails we added so they don't bite us again. When you discover a new one,
add an entry here *and* a regression test in `tests/`. The entry should explain
**what looked fine, what actually went wrong, and how to spot the same shape of
bug elsewhere** — not just "we fixed X".

---

## 1. Agenda drift across debate rounds

**What it looked like**

A debate on `"현존 가장 똑똑한 AI 모델은 뭐지?"` (What is the smartest current
AI model?) opened on topic in round 1, then by round 2 every agent was arguing
about whether *Andrew Ng's "#1 on independent leaderboard" claim was sourced*,
and by round 3 the debate had nothing to do with the original question. Same
thing happened on `"누가 분야에 관계없이 최고의 팝가수인가?"` (Who is the best
pop singer regardless of genre?) — round 2 became a meta-debate about
"Subjectivity Of 'Best'" instead of singers.

**Why it happened**

Round N+1's agenda was generated from round N's `RoundSummary.key_disagreements`
and `unresolved_questions`. Those lists were populated directly from agents'
critique points with no topic filter, and `JudgeService._agenda_candidates()`
wrapped them in a generic `"Take a position on this issue and respond to peer
arguments directly: {text}"` template. So a stray meta-complaint such as
`"Claude (Opus 4.6) failed to provide any plan summary"` could *become* the
entire agenda for the next round, and the prompt no longer contained the
original task title in the agenda block. Once an agenda drifted, every
subsequent round inherited the drift.

Three things compounded the problem:
1. **No drift filter** at agenda generation time.
2. **No topic anchor** in the agenda question itself — the original task title
   only appeared in the run header, not in the per-round agenda block.
3. **No drift telemetry** — the judge's `adjudicate_round` only flagged
   missing-evidence claims, not off-topic claims, so users couldn't see the
   problem until they read the full transcript.

**The fix (PR — see git log)**

- New `services/topic_guard.py` with `topic_token_set`, `topic_overlap`,
  `is_drifting`, `has_meta_drift_marker`, and `anchor_question`. The token set
  is built from `task.title + problem_statement + success_criteria + constraints
  + plan summaries`, minus a small `_PROCESS_NOISE_TOKENS` stoplist.
- `JudgeService._select_agenda` and `_agenda_candidates` now skip drifting
  candidates and reframe survivors with `anchor_question(...)`. The fallback
  agenda always names the topic.
- `JudgeService._ai_decide` post-processing rejects an AI-judge agenda that
  itself drifts and falls back to the deterministic on-topic suggestion.
- `JudgeService.adjudicate_round` populates a new `RoundAdjudication.drift_flags`
  list and filters off-topic items out of `unresolved_points`.
- `DebateEngine._build_prompt` injects a `TOPIC ANCHOR:` block whenever an
  agenda is supplied, telling the agent to reframe to the original topic if the
  agenda question itself wandered.
- `DebateEngine._focus_hint` now drops drifting items before falling back to
  the topic title.
- Drift flags surface in `report_synthesizer` highlights and the web report.
- Regression tests in `tests/test_topic_drift.py`.

**How to spot the same shape of bug elsewhere**

Whenever you see code that uses **round-N output as round-N+1 input**
(`run.debate_rounds[-1].summary.*`, `judge_trace[-1].focus_areas`, anything
that mutates a candidate based on the *previous* iteration), assume drift will
happen unless you can point to:

1. A topic-anchor check that the new item is still about the *original* task.
2. A reframing step that re-states the topic in the new prompt or agenda.
3. A detector / flag emitted to the judge so the drift can be corrected mid-run.

If two of those three are missing, file an issue.

**Related danger zones (audit before touching)**

- `JudgeService._focus_areas` — currently pulls from
  `latest.key_disagreements[:4]`. The drift filter sits in
  `_filter_drifting_items` and `_focus_hint`; if you add a new caller of
  `key_disagreements`, route it through the filter.
- `DebateEngine._summarize_round` — does *not* itself filter drift. The judge
  filters at consumption time. If you ever add a writer that persists summary
  bullets to disk and replays them later, add a topic filter at write time too.
- `DebateEngine._build_debate_transcript` — feeds previous rounds back to the
  agents verbatim. That's intentional (so they can rebut specific points), but
  if you change the prompt to derive *agenda* material from the transcript, run
  it through `is_drifting` first.

---

## 2. Short / vague task titles amplify drift risk

**What it looks like**

Runs with titles like `"테스트"` (test) or `"UI QA smoke battle"` produce a
`topic_token_set` of only 2–4 tokens, so almost any sentence scores below the
`TOPIC_OVERLAP_DRIFT_THRESHOLD` (0.15) and the meta-marker fallback ends up
doing all the work.

**How to spot it**

If `len(topic_token_set(run)) < ~6` you're in the danger zone. The fix isn't to
lower the threshold — that just lets real drift through. The fix is to
surface a warning at run creation time ("your task title is too short for
robust topic anchoring") and to encourage users to write a real
`problem_statement`.

This isn't fixed yet — track as a follow-up. When you add the warning,
extend `tests/test_topic_drift.py` with a fixture that has a 1-word title.

---

## 3. Auto-generated round summaries can re-promote drift

**What it looks like**

`RoundSummary.unresolved_questions` is populated from
`message.critique_points` in `DebateEngine._summarize_round` with no topic
filter. The judge filters at consumption time, but the persisted summary on
disk still contains drifting items. If you re-render an old run, those items
re-appear in the UI.

**How to spot it**

Open a saved `round-N.json` and look for `key_disagreements` /
`unresolved_questions` that contain `"failed to provide"`, `"제공하지 않"`, etc.
The persisted summary is the source of truth for replay; the runtime filter
does not retroactively clean it.

**Mitigations available right now**

- The judge always re-filters at consumption, so the *next round's* prompt is
  clean even if the persisted summary is dirty.
- The web report renders adjudication `drift_flags` so the reader sees the
  warning even if the summary text is contaminated.

**If you change the writer**, you should *also* re-filter on write so persisted
artifacts match what the runtime sees. Don't do this in a single PR with the
runtime change — the filter logic can evolve, and you don't want old runs to
silently lose data.

---

## 4. Meta-marker list is intentionally substring-based, not regex

`META_DRIFT_MARKERS` in `topic_guard.py` is a tuple of plain substrings that
get checked against the lowercased text. Don't "improve" it into a regex
unless you also handle Korean Unicode ranges. The Korean entries
(`"제공하지 않"`, `"플랜이 없"`, etc.) are substring fragments because Korean
verb conjugation produces many surface forms (`않았다`, `않는다`, `않으며`, …)
and a substring catches all of them in one entry. A naive `\b...\b` regex
will silently miss those because Korean words don't have `\b` boundaries.

When adding a new language, check the pattern with the actual conjugations
you expect to see.

---

## How to use this file

- **Reading**: skim before designing anything that touches the judge, agenda,
  or round prompt construction. The patterns above are easy to recreate.
- **Writing**: when you find a new gotcha, add a numbered section with the
  same `What it looked like / Why it happened / The fix / How to spot the
  same shape of bug elsewhere` structure. Link to the regression test.
- **Pruning**: don't delete entries when the bug is fixed. The point of this
  file is to remember the *shape* of the trap so we don't fall into a
  cousin of it later.
