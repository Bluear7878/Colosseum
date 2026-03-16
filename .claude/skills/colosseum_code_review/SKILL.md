---
name: colosseum_code_review
description: Run a Colosseum multi-phase code review via interactive interview. Collects project directory, files, reviewer models, review phases, and options through guided prompts, then executes `colosseum review`.
allowed-tools: [Bash, AskUserQuestion, Glob, Read]
version: 2.0.0
---

# Colosseum Code Review Wizard

Guide the user through an interactive interview to configure and launch a multi-phase code review. Ask questions one at a time, show available options where relevant, then build and run the `colosseum review` command.

The review runs up to 6 review phases (selectable):
- **Phase A**: 프로젝트 룰 준수 체크
- **Phase B**: 기능 구현 정확성 체크
- **Phase C**: 아키텍처 및 설계 리뷰
- **Phase D**: 보안, 메모리, 성능 최적화 리뷰
- **Phase E**: Test coverage 리뷰
- **Phase F**: Red Team / 적대적 공격 시뮬레이션 (옵트인)

각 Phase마다 에이전트들이 해당 관점에 대해 토론(mini-debate)을 진행하고, 결과를 종합한 리뷰 리포트를 생성한다.

---

## Step 1: Show Available Models

Before interviewing, list available models so the user can make informed choices:

```bash
colosseum models
```

Show the output to the user so they can see what's available.

---

## Step 2: Interview (ask one question at a time)

### Q1 — Review Target

Ask:
> 무엇을 리뷰할까요? 리뷰 대상을 설명해주세요.
> (예: "OAuth 인증 기능 구현 리뷰", "결제 모듈 보안 리뷰", "새 API 엔드포인트 코드 리뷰")

Store as `topic`.

---

### Q2 — Project Directory

Ask:
> 리뷰할 프로젝트 디렉터리 경로를 입력해주세요. (없으면 엔터)

- If provided, verify the path exists:
  ```bash
  ls "{dir_path}" 2>/dev/null | head -5
  ```
  If it doesn't exist, warn the user and ask again.
- Store as `dir_path` (empty string if skipped).

---

### Q3 — Specific Files

Ask:
> 리뷰할 특정 파일이 있나요? 파일 경로를 공백으로 구분해서 입력하세요. (없으면 엔터)

- If provided, validate each file exists.
- Store as `file_paths` list (empty if skipped).

---

### Q4 — Git Diff

Ask:
> 최근 git diff(HEAD~1)를 리뷰 컨텍스트에 포함할까요? (y/n, 기본: n)

- Store as `include_diff` (boolean).

---

### Q5 — Review Phases

Show the phase options and ask:
> 어떤 리뷰 단계를 실행할까요?
>
> - `A` 프로젝트 룰 준수 (코딩 컨벤션, 네이밍, 린터 규칙)
> - `B` 구현 정확성 (기능 구현, 에지 케이스, 에러 처리)
> - `C` 아키텍처/설계 (설계 패턴, 모듈 분리, 의존성, 확장성)
> - `D` 보안/성능 (취약점, 메모리 누수, 성능 병목, 동시성)
> - `E` 테스트 커버리지 (유닛 테스트, 통합 테스트, 테스트 구조)
> - `F` Red Team (적대적 입력, 인증 우회, 정보 유출, 권한 상승) ⚠️ 옵트인
>
> 원하는 단계를 공백으로 구분해 입력하세요. (기본: A B C D E)
> F(Red Team)는 명시적으로 포함해야 실행됩니다.

- Parse input: split by spaces, uppercase.
- Validate each letter is A-F.
- Default: `A B C D E` if user presses Enter (F is opt-in).
- Store as `phases` list (e.g. `["A", "B", "C"]`).

---

### Q6 — Reviewers (Gladiator Models)

Show the available model list from Step 1 again as a reference. Ask:
> 리뷰에 참가할 에이전트(모델)를 최소 2개 지정해주세요.
> 형식: `provider:model` (예: `claude:claude-sonnet-4-6`, `gemini:gemini-2.5-flash`)
> 쉼표 또는 공백으로 구분해서 입력하세요.

- Parse input: split by commas and/or spaces, strip whitespace.
- Validate at least 2 are specified.
- Store as `gladiators` list.

---

### Q7 — Judge Model (optional)

Ask:
> 재판장(Judge) 모델을 지정할까요?
> - AI 재판장: `provider:model` 형식으로 입력 (예: `claude:claude-opus-4-6`)
> - 자동 재판장: 엔터 (규칙 기반 자동 판정)

- Store as `judge_spec` (empty string if automated).

---

### Q8 — Depth per Phase

Ask:
> 각 Phase당 토론 깊이를 선택하세요:
> - `1` Quick    (빠른 판정, 최소 라운드)
> - `2` Brief    (간단한 토론, 기본값)
> - `3` Standard (균형잡힌 토론)
> - `4` Thorough (심층 분석)
> - `5` Deep     (최대 깊이, 오래 걸림)
>
> Phase 수 × 깊이 = 전체 소요시간이므로, Phase가 많으면 낮은 깊이를 권장합니다.

Default: `2` if the user presses Enter.
Store as `depth`.

---

### Q9 — Timeout per Phase

Ask:
> 각 Phase당 시간 제한(초)을 설정할까요?
> - 숫자를 입력하면 해당 초 안에 각 Phase를 마무리합니다 (예: `120`, `300`)
> - 엔터: 시간 제한 없음 (기본값, 권장)
>
> 💡 깊이가 높거나 복잡한 코드 리뷰에는 시간 제한 없이 진행하는 것을 권장합니다.

Default: no timeout (empty) if skipped.
Store as `timeout` (0 if skipped, integer if provided).

---

### Q10 — Response Language

Ask:
> 리뷰 결과의 응답 언어를 지정할까요?
> - `ko` 한국어
> - `en` 영어
> - `ja` 일본어
> - 기타 언어 코드 입력 가능
> - 엔터: 자동 감지 (기본값)

Default: `auto` if the user presses Enter.
Store as `lang`.

---

### Q11 — Rules File (optional)

Ask:
> 프로젝트 룰 파일 경로가 있나요? (예: CLAUDE.md, .cursorrules)
> `--dir`이 설정된 경우 자동 탐지됩니다. 명시적으로 지정하려면 입력하세요. (없으면 엔터)

- If provided, verify the file exists.
- Store as `rules_path` (empty string if skipped).

---

## Step 3: Confirm

Show a summary before running:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COLOSSEUM CODE REVIEW 설정 확인
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  리뷰 대상:    {topic}
  프로젝트:     {dir_path or "없음"}
  파일:         {file_paths or "없음"}
  Git Diff:     {include_diff ? "포함" : "미포함"}
  리뷰 단계:    {phases} (총 {len(phases)}개)
  리뷰어:       {gladiators}
  재판장:       {judge_spec or "자동 (규칙 기반)"}
  깊이:         {depth}
  타임아웃:     {timeout or "없음 (무제한)"}
  응답 언어:    {lang or "자동 감지"}
  룰 파일:      {rules_path or "자동 탐지"}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Ask: `이대로 시작할까요? (y/n)`

If `n`, go back to Q1 and restart the interview.

---

## Step 4: Build and Run the Command

Construct the command from collected inputs:

```
colosseum review \
  -t "{topic}" \
  -g {gladiator1} {gladiator2} [...] \
  -d {depth} \
  --phases {phase1} {phase2} [...] \
  [-j {judge_spec}] \
  [--dir "{dir_path}"] \
  [-f {file1} {file2} ...] \
  [--diff] \
  [--timeout {timeout}] \
  [--lang {lang}] \
  [--rules "{rules_path}"]
```

Rules:
- Always include `-t`, `-g`, `-d`, `--phases`
- Include `-j` only if `judge_spec` is non-empty
- Include `--dir` only if `dir_path` is non-empty
- Include `-f` only if `file_paths` is non-empty
- Include `--diff` only if `include_diff` is true
- Include `--timeout` only if `timeout > 0`
- Include `--lang` only if `lang` is not "auto" and not empty
- Include `--rules` only if `rules_path` is non-empty
- Quote paths that may contain spaces

Execute with the Bash tool. Stream output to the user in real time.

---

## Error Handling

- If `colosseum` is not found: tell the user to run `colosseum setup` first or activate the venv with `source /side_project/Colosseum/.venv/bin/activate`
- If a model spec is invalid (parse error): show the error, ask the user to re-enter that specific question only
- If fewer than 2 gladiators: ask Q6 again
- If a file path doesn't exist: warn and ask Q3 again
- If an invalid phase letter is entered: warn and ask Q5 again

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

## Review Phases Reference

| Letter | Phase                 | Focus                                           | Default |
|--------|-----------------------|-------------------------------------------------|---------|
| A      | Project Rules         | 코딩 컨벤션, 네이밍, 린터/포매터 규칙 준수       | ✅      |
| B      | Implementation        | 기능 구현 정확성, 에지 케이스, 에러 처리          | ✅      |
| C      | Architecture          | 설계 패턴, 모듈 분리, 의존성 관리, 확장성         | ✅      |
| D      | Security/Performance  | 보안 취약점, 메모리, 성능 병목, 동시성            | ✅      |
| E      | Test Coverage         | 유닛 테스트, 통합 테스트, 테스트 구조             | ✅      |
| F      | Red Team              | 적대적 입력, 인증 우회, 정보 유출, 권한 상승, 공급망 공격 | ❌ (opt-in) |
