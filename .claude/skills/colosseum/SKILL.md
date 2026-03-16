---
name: colosseum
description: Run a Colosseum AI debate via interactive interview. Collects project directory, files, gladiator models, judge model, and debate topic through guided prompts, then executes the debate.
allowed-tools: [Bash, AskUserQuestion, Glob, Read]
version: 1.0.0
---

# Colosseum Debate Wizard

Guide the user through an interactive interview to configure and launch a Colosseum debate. Ask questions one at a time, show available options where relevant, then build and run the `colosseum debate` command.

---

## Step 1: Show Available Models

Before interviewing, list available models so the user can make informed choices:

```bash
colosseum models
```

Show the output to the user so they can see what's available.

---

## Step 2: Interview (ask one question at a time)

### Q1 — Debate Topic

Ask:
> 어떤 주제로 토론할까요? (예: "monolithic vs microservices", "어떤 데이터베이스를 선택해야 하나")

Store as `topic`.

---

### Q2 — Project Directory

Ask:
> 분석할 프로젝트 디렉터리가 있나요? 있다면 경로를 입력해주세요. (없으면 엔터)

- If provided, verify the path exists:
  ```bash
  ls "{dir_path}" 2>/dev/null | head -5
  ```
  If it doesn't exist, warn the user and ask again.
- Store as `dir_path` (empty string if skipped).

---

### Q3 — Specific Files

Ask:
> 컨텍스트로 포함할 특정 파일이 있나요? 파일 경로를 공백으로 구분해서 입력하세요. (없으면 엔터)

- If provided, validate each file exists.
- Store as `file_paths` list (empty if skipped).

---

### Q4 — Gladiators (debating models)

Show the available model list from Step 1 again as a reference. Ask:
> 토론에 참가할 글래디에이터(모델)를 최소 2개 지정해주세요.
> 형식: `provider:model` (예: `claude:claude-sonnet-4-6`, `gemini:gemini-2.5-pro`, `ollama:llama3.3`)
> 쉼표 또는 공백으로 구분해서 입력하세요.

- Parse input: split by commas and/or spaces, strip whitespace.
- Validate at least 2 are specified.
- Store as `gladiators` list.

---

### Q5 — Judge Model

Ask:
> 재판장(Judge) 모델을 지정할까요?
> - AI 재판장: `provider:model` 형식으로 입력 (예: `claude:claude-opus-4-6`)
> - 자동 재판장: 엔터 (규칙 기반 자동 판정)

- Store as `judge_spec` (empty string if automated).

---

### Q6 — Debate Depth

Ask:
> 토론 깊이를 선택하세요:
> - `1` Quick    (빠른 판정, 최소 라운드)
> - `2` Brief    (간단한 토론)
> - `3` Standard (기본값, 균형잡힌 토론)
> - `4` Thorough (심층 분석)
> - `5` Deep     (최대 깊이, 오래 걸림)

Default: `3` if the user presses Enter.
Store as `depth`.

---

### Q7 — Timeout (optional)

Ask:
> 각 페이즈당 타임아웃(초)을 설정할까요? (없으면 엔터, 권장: 120~300)

Default: no timeout if skipped.
Store as `timeout` (0 if skipped).

---

## Step 3: Confirm

Show a summary before running:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COLOSSEUM 설정 확인
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  토론 주제:    {topic}
  프로젝트:     {dir_path or "없음"}
  파일:         {file_paths or "없음"}
  글래디에이터: {gladiators}
  재판장:       {judge_spec or "자동 (규칙 기반)"}
  깊이:         {depth}
  타임아웃:     {timeout or "없음"}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Ask: `이대로 시작할까요? (y/n)`

If `n`, go back to Q1 and restart the interview.

---

## Step 4: Build and Run the Command

Construct the command from collected inputs:

```
colosseum debate \
  -t "{topic}" \
  -g {gladiator1} {gladiator2} [...] \
  -d {depth} \
  [-j {judge_spec}] \
  [--dir "{dir_path}"] \
  [-f {file1} {file2} ...] \
  [--timeout {timeout}]
```

Rules:
- Always include `-t`, `-g`, `-d`
- Include `-j` only if `judge_spec` is non-empty
- Include `--dir` only if `dir_path` is non-empty
- Include `-f` only if `file_paths` is non-empty
- Include `--timeout` only if `timeout > 0`
- Quote paths that may contain spaces

Execute with the Bash tool. Stream output to the user in real time.

---

## Error Handling

- If `colosseum` is not found: tell the user to run `colosseum setup` first or activate the venv with `source /side_project/Colosseum/.venv/bin/activate`
- If a model spec is invalid (parse error): show the error, ask the user to re-enter that specific question only
- If fewer than 2 gladiators: ask Q4 again
- If a file path doesn't exist: warn and ask Q3 again

---

## Available Models Reference

| Short alias        | Provider | Model                        | Tier         |
|--------------------|----------|------------------------------|--------------|
| claude:claude-opus-4-6      | Claude   | claude-opus-4-6              | subscription |
| claude:claude-sonnet-4-6    | Claude   | claude-sonnet-4-6            | subscription |
| claude:claude-haiku-4-5-20251001 | Claude | claude-haiku-4-5-20251001  | subscription |
| gemini:gemini-2.5-pro       | Gemini   | gemini-2.5-pro               | subscription |
| gemini:gemini-2.5-flash     | Gemini   | gemini-2.5-flash             | subscription |
| codex:o4-mini               | Codex    | o4-mini                      | subscription |
| ollama:llama3.3             | Ollama   | llama3.3                     | free (local) |
| ollama:qwen2.5              | Ollama   | qwen2.5                      | free (local) |
| mock:a                      | Mock     | (test only)                  | free         |
