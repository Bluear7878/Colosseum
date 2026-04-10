---
name: colosseum_qa
description: Run a Colosseum QA ensemble via interactive interview. Multiple AI gladiators (each as a real Claude Code subprocess or mediated executor) run the target project's `.claude/skills/qa` skill in parallel on disjoint GPU slices, then a judge synthesizes their findings into one canonical, deduplicated, severity-ranked QA report. Triggers on "colosseum QA", "/colosseum_qa", "QA ensemble", "run qa team in colosseum".
allowed-tools: [Bash, AskUserQuestion, Glob, Read]
version: 1.0.0
---

# Colosseum QA Wizard

Guide the user through an interactive interview to configure and launch a
**QA ensemble** run. Ask one question at a time, validate answers, then
build and run the `colosseum qa` command.

This is **not** a debate. Multiple gladiators run the **same** QA pass against
the same target project in parallel. Each gladiator gets a disjoint slice of
GPUs (so they never collide) and uses the target's own `.claude/skills/qa/`
skill. After all gladiators finish, a judge synthesizes the union of their
findings into one canonical, deduplicated, REPRODUCED-only QA report.

The goal is **QA quality**, not picking a winner. More diverse gladiators
catch more bugs.

> **Live monitoring (tmux)**: when invoked from inside a tmux session,
> `colosseum qa` automatically splits the current pane into one watcher pane
> per gladiator and tails its event stream live (default: on). Pass
> `--no-monitor` to disable. Outside of tmux this is a no-op.

---

## Step 0: Confirm `colosseum qa` is available

```bash
colosseum qa --help 2>&1 | head -40
```

If the command is missing:
- Tell the user to activate the venv: `source /workspace/side_project/Colosseum/.venv/bin/activate`
- Or run `colosseum setup` first.

---

## Step 1: Show available models

```bash
colosseum models
```

Show the output. Claude models run as **real Claude Code subprocesses** with
native subagent spawning. Non-Claude models (Gemini, Codex) run via the
**mediated executor**, which is more limited (Layer 1-3 only — no native
subagents).

---

## Step 2: Interview (one question at a time)

### Q1 — Target project path

Ask:
> 어떤 프로젝트를 QA할까요? `.claude/skills/qa/SKILL.md`가 있는 프로젝트의 절대 경로를 입력하세요.
> (예: `/path/to/your/target-project`)

Validate:
```bash
test -f "{target}/.claude/skills/qa/SKILL.md" && echo OK || echo MISSING
```
If `MISSING`, warn the user that mediated and Claude executors both need this
file and ask again.

Store as `target`.

---

### Q2 — QA target description (one-line)

Ask:
> 이번 QA 실행을 한 줄로 설명해주세요. (리포트 제목이 됩니다)
> (예: "결제 모듈 회귀 테스트", "API 인증 풀 패스")

Store as `topic`.

---

### Q3 — QA scope args

Ask:
> 타겟의 `/qa` 스킬에 전달할 인자를 입력하세요. 비워두면 스킬이 자동 감지합니다.
> 인자 형식은 타겟 프로젝트의 QA skill 정의에 따라 다릅니다 — `target/.claude/skills/qa/SKILL.md`를
> 먼저 읽어보고 어떤 scope keyword를 받는지 확인하세요. 일반적인 예시:
>   - `pr` — 현재 PR diff 범위만 테스트
>   - `full` — 전체 회귀 테스트
>   - 빈 문자열 — 스킬이 git diff 등으로 자동 감지

Store as `qa_args` (empty string allowed).

---

### Q4 — Gladiators

Ask:
> QA에 참가할 gladiator(에이전트)를 최소 1개 지정해주세요. 형식은 `provider:model`.
> 다양성이 높을수록 더 많은 버그가 잡힙니다 — 같은 family라도 size를 섞는 것을 추천합니다.
> 예시:
>   - `claude:claude-opus-4-6 claude:claude-sonnet-4-6`
>   - `claude:claude-opus-4-6 claude:claude-sonnet-4-6 claude:claude-haiku-4-5-20251001`
>   - `claude:claude-sonnet-4-6 gemini:gemini-2.5-pro` (Gemini는 mediated executor)

Validate:
- 최소 1개 이상
- 각 spec이 `provider:model` 형식인지

Store as `gladiators` list.

---

### Q5 — Judge model

Ask:
> 결과를 합성할 judge 모델을 지정하세요. (필수 아님 — 비우면 heuristic으로 합성)
> 추천: `claude:claude-opus-4-6` (긴 컨텍스트, 가장 정확한 dedup)
> 형식: `provider:model`

Store as `judge_spec` (empty string allowed).

---

### Q6 — GPU strategy

Ask:
> GPU를 어떻게 분배할까요?
>   1. `auto` — Colosseum이 nvidia-smi로 사용 가능한 GPU를 자동 감지 (기본값)
>   2. `force <indices>` — 특정 GPU만 사용 (예: `force 0,1,2,3`)
>   3. `sequential` — gladiator를 순차 실행 (GPU가 부족할 때)

Parse:
- 입력이 비어있으면 `mode=auto`, `forced=None`
- `force 0,1,2,3` 형태이면 `mode=auto`, `forced="0,1,2,3"`
- `sequential` 이면 `mode=sequential`

또한 묻기:
> 1 gladiator당 몇 개의 GPU를 할당할까요? (비워두면 균등 분할, 예: `2`)

Store as `gpus_per_gladiator` (int 또는 None).

---

### Q7 — Mode (brief vs full)

Ask:
> QA 모드:
>   - `full` — 타겟 프로젝트의 코드를 실제로 실행 (오래 걸리지만 진짜 런타임 버그를 찾음, 기본값)
>   - `brief` — 코드 분석만, 실행 없음 (빠르고 저렴, 런타임 버그는 못 찾음)

Store as `brief` (boolean).

---

### Q8 — Budget cap

Ask:
> gladiator당 최대 비용 (USD)을 설정하세요. (기본: `25`, 권장: 10-50)
> 이 cap을 넘으면 Claude이 자동으로 종료합니다. ensemble 전체 = N × cap.

Store as `max_budget_usd` (float).

---

### Q9 — Time limits

Ask:
> gladiator당 최대 실행 시간(분)을 설정하세요. (기본: `90`)
> stall 감지(이벤트 N분간 없으면 강제 종료)는 어떻게 할까요? (기본: `10`)

Store as `max_minutes` and `stall_minutes` (ints).

---

### Q10 — Spec / extras

Ask (optional):
> customer spec configs를 포함할까요? (`arm`, `all`, 또는 비움)
> 응답 언어는? (`ko`, `en`, `ja`, 비우면 자동)

Store as `spec` and `lang`.

---

## Step 3: Confirm

Show a summary table:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COLOSSEUM QA ENSEMBLE 설정 확인
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  타겟:           {target}
  설명:           {topic}
  QA args:        {qa_args or "(자동)"}
  Gladiators:     {gladiators}
  Judge:          {judge_spec or "heuristic"}
  GPU 전략:       {gpu_mode}
  GPU/gladiator:  {gpus_per_gladiator or "균등"}
  Brief:          {brief ? "yes (코드 분석만)" : "no (실제 실행)"}
  Max budget:     ${max_budget_usd}/gladiator
  Max minutes:    {max_minutes} (stall {stall_minutes}분)
  Spec:           {spec or "(없음)"}
  Lang:           {lang or "auto"}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  예상 ensemble 비용: 약 ${len(gladiators) * max_budget_usd} (cap 기준)
```

Ask: `이대로 시작할까요? (y/n)`

If `n`, restart from Q1.

---

## Step 4: Build and run

Construct the command:

```
colosseum qa \
  -t "{topic}" \
  --target "{target}" \
  --qa-args "{qa_args}" \
  -g {g1} {g2} [...] \
  [-j {judge_spec}] \
  [--gpus {forced}] \
  [--gpus-per-gladiator {n}] \
  [--sequential] \
  --max-budget-usd {max_budget_usd} \
  --max-gladiator-minutes {max_minutes} \
  --stall-timeout-minutes {stall_minutes} \
  [--brief] \
  [--spec {spec}] \
  [--lang {lang}] \
  [--no-monitor] \
  --yes
```

Rules:
- Always include `-t`, `--target`, `-g`, `--max-budget-usd`, `--max-gladiator-minutes`, `--stall-timeout-minutes`, `--yes`
- Include `--qa-args` only if non-empty (quote it!)
- Include `-j` only if `judge_spec` is non-empty
- Include `--gpus` only when forced indices were given
- Include `--gpus-per-gladiator` only when explicitly set
- Include `--sequential` only when sequential mode chosen
- Include `--brief` only when brief mode is on
- Include `--spec` / `--lang` only when non-empty
- Include `--no-monitor` ONLY if the user explicitly asked to disable the
  tmux watcher panes; otherwise omit (monitor is on by default inside tmux)
- Pass `--yes` so the wizard confirmation is enough — Colosseum won't ask again

Execute via the Bash tool. Stream output to the user in real time.

After the command starts (inside tmux), Colosseum will automatically split
the current pane into one watcher pane per gladiator showing live progress.
Tell the user where to find the final synthesized report:
`.colosseum/qa/<run_id>/synthesized_report.md`.

---

## Error handling

- If `colosseum qa --help` fails: ask the user to activate the venv first
- If a gladiator spec is invalid: re-ask Q4 with the parse error
- If `target/.claude/skills/qa/SKILL.md` is missing: re-ask Q1
- If allocation hard-errors with `more gladiators than GPUs`: suggest reducing
  gladiator count, freeing GPUs, or rerunning with `sequential` mode
- If `claude` binary is not on PATH and any gladiator is `claude:*`: ask the
  user to run `colosseum setup claude` first

---

## Notes for the agent running this skill

- This wizard targets Colosseum's `colosseum qa` subcommand. Do not invent
  flags — read `colosseum qa --help` if anything is unclear.
- The `/qa` skill being executed lives in the **target** project, not in
  Colosseum itself. Colosseum just spawns gladiators that invoke it.
- Each gladiator writes its raw report to
  `.colosseum/qa/<run_id>/gladiators/<gid>/report.md`. The synthesized report
  goes to `.colosseum/qa/<run_id>/synthesized_report.md`. Tell the user where
  to find it after the run.
- The judge's job is **not** to pick a winner. Tell the user this if asked —
  the metrics shown per gladiator (reproduced count, novel count, severity
  score) are diagnostic, not competitive.
