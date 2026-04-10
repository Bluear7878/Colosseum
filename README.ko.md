<div align="center">

# ⚔️ AI Colosseum debate

**멀티 에이전트 토론 아레나 — AI 모델들을 맞붙게 하라**

*동일한 과제를 여러 모델 에이전트에 돌리고, 공유 컨텍스트 번들을 동결하고,*
*독립된 플랜을 생성하고, 근거 기반 토론을 수행하고, 판사가 뒷받침하는 판결을 만들어낸다.*

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

**🌐 Language / 언어 / 语言:** [English](README.md) · **한국어** · [中文](README.zh.md)

---

🏛️ **공정** · 🔍 **추적 가능** · 💰 **비용 통제** · 📊 **근거 우선** · 🔌 **확장 가능**

</div>

<br>

## 🎯 왜 Colosseum인가?

> 또 하나의 챗봇 UI가 아닙니다 — Colosseum은 실제 업무 흐름을 위해 설계된 **구조화된 토론 플랫폼**입니다.

| 문제 | AI Colosseum debate의 답 |
|---|---|
| "어느 모델이 더 나은 플랜을 줄까?" | **동일한 동결 컨텍스트** 위에서 나란히 실행 |
| "공정하게 비교하려면?" | 독립적인 플랜 생성 — 어느 에이전트도 다른 에이전트의 플랜을 먼저 보지 못함 |
| "토론이 끝없이 맴돈다" | **새로움 검사**, 수렴 감지, 예산 한도가 있는 제한된 라운드 |
| "결정이 어떻게 내려졌는지 추적할 수 없다" | 플랜, 라운드, 판사 아젠다, 채택된 주장, 판결까지의 전체 아티팩트 추적 |
| "판정 방식을 제어하고 싶다" | **자동 판사**, **AI 판사**, **사람 판사** 세 가지 모드 선택 |
| "단순 토론이 아니라 코드 리뷰가 필요하다" | 6개의 설정 가능한 리뷰 단계를 가진 다단계 **코드 리뷰** |
| "여러 AI가 병렬로 내 프로젝트를 QA했으면 한다" | **QA 앙상블 모드** — 검투사들이 disjoint GPU 슬라이스에서 병렬 실행, 판사가 발견을 합집합으로 dedup해서 단일 canonical 리포트 생성 |

---

## ✨ 주요 기능

<table>
<tr>
<td width="50%" valign="top">

### 🧊 동결 컨텍스트 번들
모든 에이전트가 동일한 입력을 받습니다 — 텍스트, 파일, 디렉토리, URL, 이미지까지 플래닝 시작 전에 동결됩니다.

### 🤖 멀티 프로바이더 지원
Claude · Codex · Gemini · Ollama · 커스텀 CLI
같은 토론에서 여러 프로바이더를 섞어 쓸 수 있습니다.

### 🎭 페르소나 시스템
20개 이상의 내장 페르소나(Karpathy, Andrew Ng, Elon Musk 등), 설문으로 페르소나 생성, 또는 직접 작성.

### 📝 다단계 코드 리뷰
6개의 설정 가능한 리뷰 단계: 프로젝트 규칙, 구현, 아키텍처, 보안/성능, 테스트 커버리지, 레드팀 적대적 테스트.

### 🧪 QA 앙상블 모드
여러 검투사가 **타겟 프로젝트의 자체 `/qa` 스킬**을 **disjoint GPU 슬라이스**에서 병렬 실행. 판사가 발견을 합집합으로 dedup해서 하나의 canonical, REPRODUCED-only QA 리포트로 합성. 협력적이고 승자 없음.

</td>
<td width="50%" valign="top">

### ⚖️ 세 가지 판사 모드
**자동 휴리스틱** 판사, **AI 기반** 판사(임의 모델), 또는 **사람 판사**(일시정지/재개 흐름).

### 📈 근거 우선 토론
주장에는 근거가 있어야 합니다. 근거 없는 단언은 감점됩니다. 판사는 라운드별로 근거 품질을 추적합니다.

### 💎 실행 요약 리포트
AI가 합성한 최종 리포트 — 핵심 결론, 판결 설명, 토론 하이라이트 포함. **PDF** 또는 **Markdown** 내보내기.

### 💰 토큰 & 비용 추적
프로바이더 출력에서 실제 토큰 수를 가져오고 에이전트별 비용을 분해합니다. CLI 결과에서 항상 표시됩니다.

### 📺 실시간 모니터링
tmux 기반 라이브 모니터 패널로 토론과 QA 앙상블을 실시간 관찰. QA 모드는 검투사당 watcher pane을 자동으로 띄움.

### 🪄 번들 위저드 스킬
첫 실행 시 4개의 Claude Code 위저드 스킬이 `~/.claude/skills/` 아래 자동 설치: `/colosseum`, `/colosseum_code_review`, `/colosseum_qa`, `/update_docs`.

</td>
</tr>
</table>

---

## 🎬 동작 예시

### 1단계: 실제 아키텍처 결정에 Claude와 Gemini를 맞붙게

```bash
colosseum debate \
  -t "10인 스타트업은 마이크로서비스 vs 모놀리스, 어느 쪽을 택해야 하나?" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -j claude:claude-opus-4-6
```

> 두 모델 모두 **완전히 동일한 동결 컨텍스트**를 받고 서로의 작업을 보기 전에 독립된 플랜을 생성합니다. 판사는 라운드별로 새로움과 근거 품질을 추적 — 순환 토론 없음.

### 2단계: 로컬 모델로 실행 — API 키 불필요

```bash
colosseum debate \
  -t "실시간 분석에 가장 적합한 데이터베이스는?" \
  -g ollama:llama3.3 ollama:qwen2.5 \
  --depth 2
```

> Colosseum이 GPU를 자동 감지하고, `llmfit`으로 모델 적합성을 확인하며, Ollama 데몬을 관리합니다. 완전 오프라인, 완전 무료.

### 3단계: 시각적인 웹 아레나 열기

```bash
colosseum serve
```

> **http://127.0.0.1:8000/** 에서 열립니다 — 모델 선택, 페르소나 할당, 판사 모드 설정, SSE 실시간 스트리밍으로 토론이 펼쳐지는 것을 관찰.

### 4단계: `/qa` 스킬을 가진 프로젝트에 QA 앙상블 실행

```bash
colosseum qa \
  -t "릴리즈 전 회귀 스윕" \
  --target /path/to/your/target-project \
  -g claude:claude-opus-4-6 claude:claude-sonnet-4-6 \
  -j claude:claude-opus-4-6 \
  --gpus-per-gladiator 2
```

> 각 검투사가 자체 disjoint GPU 슬라이스를 가진 real `claude --print` 서브프로세스로 실행 (충돌 없음). 비-Claude 검투사는 mediated executor로 실행. 모두 끝나면 판사가 리포트를 합집합 dedup해서 하나의 canonical REPRODUCED-only QA 리포트 생성. tmux 안에서는 검투사당 watcher pane이 자동으로 뜸.

---

## 🌟 AI Colosseum debate가 다른 점

| 다른 도구들 | AI Colosseum debate |
|---|---|
| 모델이 서로의 출력을 보고 나서 응답 | **동결 컨텍스트** — 모든 에이전트가 같은 스냅샷에서 독립적으로 플래닝 |
| 누군가 포기할 때까지 토론이 계속 | 새로움 검사, 수렴 감지, 예산 한도가 있는 **제한된 라운드** |
| 판결이 "느낌" 기반 | **근거 우선 판정** — 근거 없는 주장은 감점, 채택된 주장은 기록 |
| 결과를 재현할 방법이 없음 | **전체 아티팩트 추적**: 플랜, 라운드 기록, 판사 아젠다, 채택된 주장, 판결 |
| 판사 하나, 모드 하나 | 세 가지 판사 모드: 휴리스틱 **자동**, 임의 모델 **AI 판사**, **사람 일시정지/재개** |
| QA 도구는 한 번에 한 에이전트만 순차 실행 | **QA 앙상블** — 검투사들이 disjoint GPU 슬라이스에서 병렬 실행, 판사가 발견을 한 리포트로 dedup |

- **vs ChatGPT Arena / lmsys**: 그쪽은 단일 프롬프트를 두 모델에 보내고 사람들이 투표하게 합니다. AI Colosseum debate는 당신이 정의한 주제에, 당신의 컨텍스트로, *구조화된 다중 라운드 토론*을 수행하고 근거가 있는 추적 가능한 판결을 만듭니다.
- **내장 페르소나**: 각 검투사에게 Karpathy, Andrew Ng, 보안 연구자, 또는 커스텀 페르소나를 할당하여 의미 있게 달라지는 논거 프레이밍을 얻습니다.
- **코드 리뷰 모드**: 6개의 설정 가능한 단계(컨벤션 → 구현 → 아키텍처 → 보안 → 테스트 → 레드팀)가 토론 엔진을 다중 리뷰어 코드 감사로 바꿉니다.
- **QA 앙상블 모드**: 어떤 프로젝트의 `.claude/skills/qa` 스킬이라도 N개 검투사에서 병렬로 구동하고 발견의 합집합을 dedup — 협력적, 비경쟁적. Claude 검투사는 native sub-agent dispatch, Gemini/Codex는 mediated executor로 동작.
- **내 인프라**: 클라우드 API와 로컬 Ollama 모델을 자유롭게 혼용. 클라우드 프로바이더를 선택하지 않는 한 데이터가 기기 밖으로 나가지 않습니다.

---

## 🤝 커뮤니티 & 지원

AI Colosseum debate가 도움이 되었다면 GitHub에서 ⭐가 큰 힘이 됩니다.

- **버그 리포트 & 기능 요청** → [GitHub Issues](https://github.com/Bluear7878/AI-Colosseum-Debate/issues)
- **기여 환영** — 새로운 프로바이더 어댑터, 페르소나, 판사 모드, QA executor, UI 개선 PR을 환영합니다. 시작 전 [`docs/architecture/overview.md`](docs/architecture/overview.md)를 읽어주세요.

---

## 🧭 문서 맵

README는 제품 소개용 개요입니다. 공식 엔지니어링 문서는 `docs/`에 있습니다.

| 문서 | 설명 |
|---|---|
| [`docs/colosseum_spec.md`](docs/colosseum_spec.md) | 스펙 인덱스 및 진입점 |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | 계층형 아키텍처 모델 |
| [`docs/architecture/design-philosophy.md`](docs/architecture/design-philosophy.md) | 핵심 설계 원칙과 non-goals |
| [`docs/specs/runtime-protocol.md`](docs/specs/runtime-protocol.md) | 런 라이프사이클, 스트리밍 계약, 비용 추적 |
| [`docs/specs/agent-governance.md`](docs/specs/agent-governance.md) | 에이전트, 페르소나, 프로바이더 경계 |
| [`docs/specs/persona-authoring.md`](docs/specs/persona-authoring.md) | 페르소나 파일 포맷 및 검증 |

---

## 🚀 빠른 시작

### 설치

```bash
# 편집 가능 모드로 설치
python -m pip install -e .

# 개발 도구 포함
python -m pip install -e '.[dev]'
```

### 프로바이더 설정

```bash
# 대화형 설정 — 지원되는 모든 CLI 프로바이더 설치 및 인증
# 4개 번들 위저드 스킬도 ~/.claude/skills/에 자동 설치
colosseum setup

# 특정 프로바이더만 설정
colosseum setup claude codex

# 설치된 도구 확인
colosseum check
```

### 위저드 스킬 자동 설치

`colosseum` 명령을 처음 실행하면 4개의 Claude Code 위저드 스킬이 `~/.claude/skills/` 아래 silent 설치되어 어디서든 호출 가능합니다:

| 스킬 | 트리거 | 용도 |
|---|---|---|
| `/colosseum` | "colosseum debate" | 토론 위저드 |
| `/colosseum_code_review` | "colosseum code review" | 다단계 코드 리뷰 위저드 |
| `/colosseum_qa` | "colosseum qa" / "QA ensemble" | QA 앙상블 위저드 |
| `/update_docs` | "update docs" | 프로젝트 문서 갱신 위저드 |

새로 받거나 강제 덮어쓰려면:

```bash
colosseum install-skills            # 누락된 것만 설치
colosseum install-skills --force    # 사용자 커스터마이즈도 덮어쓰기
```

### 웹 UI 실행

```bash
colosseum serve
```

**http://127.0.0.1:8000/** 를 여시면 준비 완료.

### CLI에서 토론 실행

```bash
# 빠른 목 토론 (실제 프로바이더 불필요)
colosseum debate --topic "프로바이더 레이어를 리팩토링해야 할까?" --mock --depth 1

# 실제 멀티 모델 토론
colosseum debate \
  --topic "벤더 중립 프로바이더 레이어로의 최선의 마이그레이션 전략" \
  -g claude:claude-sonnet-4-6 codex:o3 ollama:llama3.3

# AI 판사 + 라이브 모니터링
colosseum debate \
  --topic "모놀리식 vs 마이크로서비스" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  -j claude:claude-opus-4-6 --monitor

# 사람 판사로
colosseum debate \
  --topic "데이터베이스 마이그레이션 전략" \
  -g claude:claude-sonnet-4-6 codex:o4-mini \
  -j human
```

### 코드 리뷰 실행

```bash
# 기본 단계(A-E)로 다단계 코드 리뷰
colosseum review \
  -t "OAuth 구현 리뷰" \
  -g claude:claude-sonnet-4-6 gemini:gemini-2.5-pro \
  --dir ./src

# 레드팀 단계 포함 + 특정 파일
colosseum review \
  -t "결제 모듈 보안 리뷰" \
  -g claude:claude-sonnet-4-6 codex:o3 \
  --phases A B C D E F \
  -f src/payment.py src/auth.py
```

### QA 앙상블 실행

타겟 프로젝트에 `.claude/skills/qa/SKILL.md`가 있어야 합니다 — 어떻게 QA 받고 싶은지를 그 스킬이 정의합니다. 각 검투사가 자체 GPU 슬라이스에서 그 스킬을 병렬 실행합니다.

```bash
# 2개의 Claude 검투사 + disjoint GPU 슬라이스, 판사가 합집합 dedup
colosseum qa \
  -t "릴리즈 전 회귀 스윕" \
  --target /path/to/your/target-project \
  -g claude:claude-opus-4-6 claude:claude-sonnet-4-6 \
  -j claude:claude-opus-4-6 \
  --gpus-per-gladiator 2

# Cross-vendor 앙상블: Claude (native subagent) + Gemini/Codex (mediated)
colosseum qa \
  -t "Cross-vendor QA 패스" \
  --target /path/to/your/target-project \
  -g claude:claude-opus-4-6 gemini:gemini-2.5-pro codex:gpt-5.4 \
  -j claude:claude-opus-4-6 \
  --gpus-per-gladiator 1

# Brief 모드 (코드 분석만, GPU 실행 없음)
colosseum qa -t "빠른 smoke" --target /path/to/target -g claude:claude-haiku-4-5-20251001 --brief
```

tmux 안에서는 검투사당 watcher pane이 자동으로 떠서 라이브 진행 상황을 보여줍니다. 합성된 canonical 리포트는 `.colosseum/qa/<run_id>/synthesized_report.md`에 저장됩니다.

---

## 🖥️ CLI 명령어

```
colosseum setup [providers...]       CLI 프로바이더 설치 및 인증 (위저드 스킬 자동 설치 포함)
colosseum install-skills [--force]   ~/.claude/skills/에 번들 위저드 스킬 설치
colosseum serve                      웹 UI 서버 시작
colosseum debate                     터미널에서 토론 실행
colosseum review                     다단계 코드 리뷰 실행
colosseum qa                         타겟 프로젝트에 QA 앙상블 실행
colosseum monitor [run_id]           활성 토론의 tmux 라이브 모니터 열기
colosseum models                     모든 프로바이더의 가용 모델 나열
colosseum personas                   가용 페르소나 나열
colosseum history                    과거 배틀 목록
colosseum show <run_id>              과거 배틀 결과 보기
colosseum delete <run_id|all>        배틀 런 삭제
colosseum check                      CLI 도구 가용성 검증
colosseum local-runtime status       관리되는 로컬 모델 런타임 상태 확인
```

### Debate 옵션

| 플래그 | 설명 |
|---|---|
| `-t`, `--topic` | 토론 주제 (필수) |
| `-g` | `provider:model` 포맷의 검투사 (최소 2) |
| `-j`, `--judge` | 판사 모델 (`provider:model` 또는 `human`) |
| `-d`, `--depth` | 토론 깊이 1-5 (기본: 3) |
| `--dir` | 컨텍스트용 프로젝트 디렉토리 |
| `-f` | 컨텍스트용 특정 파일 |
| `--mock` | 목 프로바이더 사용 (무료, 테스트용) |
| `--monitor` | tmux 모니터 패널 실행 |
| `--timeout` | 단계별 타임아웃 (초) |

### Review 옵션

| 플래그 | 설명 |
|---|---|
| `-t`, `--topic` | 리뷰 대상 설명 (필수) |
| `-g` | `provider:model` 포맷의 리뷰어 에이전트 (최소 2) |
| `--phases` | 실행할 리뷰 단계 (기본: `A B C D E`) |
| `-j`, `--judge` | 판사 모델 |
| `-d`, `--depth` | 단계별 토론 깊이 (기본: 2) |
| `--dir` | 리뷰할 프로젝트 디렉토리 |
| `-f` | 리뷰할 특정 파일 |
| `--diff` | 최근 git diff를 컨텍스트에 포함 |
| `--lang` | 응답 언어 (`ko`, `en`, `ja` 등) |
| `--rules` | 프로젝트 규칙 파일 경로 |
| `--timeout` | 단계별 타임아웃 (초) |

### QA 옵션

| 플래그 | 설명 |
|---|---|
| `-t`, `--topic` | QA 실행 한 줄 설명 (필수) |
| `--target` | 타겟 프로젝트 경로 (`.claude/skills/qa/SKILL.md` 필수) (필수) |
| `--qa-args` | 타겟의 `/qa` 스킬에 전달할 인자 |
| `-g` | `provider:model` 포맷의 검투사. Claude → real `claude --print` 서브프로세스, 비-Claude → mediated executor |
| `-j`, `--judge` | 검투사 발견을 합성할 판사 모델 |
| `--gpus` | 강제 사용할 GPU 인덱스 csv (기본: 자동 감지) |
| `--gpus-per-gladiator` | 검투사당 GPU 슬라이스 크기 (기본: 균등 분할) |
| `--sequential` | 병렬 disjoint 슬라이스 대신 순차 실행 |
| `--max-budget-usd` | 검투사당 강제 비용 cap (기본: $25) |
| `--max-gladiator-minutes` | 검투사당 soft 타임아웃 (기본: 90) |
| `--stall-timeout-minutes` | stall 감지 임계값 (기본: 10) |
| `--brief` | 코드 분석만, GPU 실행 없음 |
| `--monitor` / `--no-monitor` | tmux watcher pane 자동 spawn (tmux 안에서 기본 on) |
| `--spec` | `/qa` 스킬에 `--spec NAME` 전달 |
| `--lang` | 응답 언어 |
| `--allow-dirty-target` | dirty worktree 경고 스킵 |
| `--no-stash-safety` | git stash safety net 스킵 |

---

## 🏗️ 런의 동작 흐름

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  📋 과제    │───▶│  🧊 컨텍스트│───▶│  📝 플랜    │───▶│  ⭐ 플랜    │
│  접수       │    │  동결       │    │  생성       │    │  스코어링  │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                               │
        ┌──────────────────────────────────────────────────────┘
        ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  🎯 판사    │───▶│  💬 토론    │───▶│  ⚖️ 주장    │───▶│  🏆 판결    │
│  아젠다     │    │  라운드     │    │  채택       │    │  & 리포트  │
└──────┬──────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                                      │
       └──────── 🔄 다음 이슈 ◀───────────────┘
```

오케스트레이터는 열린 채팅 대신 **제한된 토론**을 사용합니다. 판사는 플랜이 이미 충분히 분리되었거나, 새로움이 붕괴되거나, 예산 압박이 너무 크면 조기에 중단할 수 있습니다.

---

## ⚖️ 토론 프로토콜

각 라운드는 열린 구조가 아닌 **아젠다 주도** 방식입니다:

| 단계 | 설명 |
|:---:|---|
| **1** | 판사가 하나의 구체적인 이슈를 선택 |
| **2** | 모든 에이전트가 자신의 플랜에서 답변 |
| **3** | 에이전트는 특정 동료 주장을 반박하거나 수용해야 함 |
| **4** | 판사가 가장 강한 근거 기반 주장을 채택 |
| **5** | 판사가 다음 이슈로 진행하거나 종결 |

### 기본 라운드 타입

`critique` → `rebuttal` → `synthesis` → `final_comparison` → `targeted_revision`

각 라운드는 판사 아젠다, 모든 에이전트 메시지, 채택된 주장, 미해결 항목을 기록합니다.

### Depth 프로필

| Depth | 이름 | 새로움 임계값 | 수렴 | 비고 |
|:---:|---|:---:|:---:|---|
| 1 | Quick | 5% | 40% | 적극적 조기 종결 |
| 2 | Brief | 10% | 55% | |
| 3 | Standard | 18% | 75% | 기본값 |
| 4 | Thorough | 25% | 85% | 최소 2 라운드 |
| 5 | Deep Dive | 30% | 92% | 최소 2 라운드, 하드 스톱 |

### 판사 모드

| 모드 | 설명 |
|---|---|
| 🤖 **Automated** | 예산, 새로움, 수렴, 근거 검사 포함 휴리스틱 판사 |
| 🧠 **AI** | 프로바이더 기반 판사 — 가용한 모델을 판사로 선택 |
| 👤 **Human** | 플래닝 후 또는 라운드 후 일시정지; 명시적인 사람의 액션을 대기 |

### 판결 옵션

최종 판결은 다음 중 하나가 될 수 있습니다: **승리 플랜 하나**, **병합된 플랜**, **특정 개정 요청**.

---

## 📝 코드 리뷰 단계

| 단계 | 이름 | 초점 |
|:---:|---|---|
| **A** | 프로젝트 규칙 | 코딩 컨벤션, 네이밍, 린터/포매터 규칙 |
| **B** | 구현 | 기능적 정확성, 엣지 케이스, 에러 처리 |
| **C** | 아키텍처 | 디자인 패턴, 모듈 분리, 의존성, 확장성 |
| **D** | 보안/성능 | 취약점, 메모리 누수, 성능 병목, 동시성 |
| **E** | 테스트 커버리지 | 단위 테스트, 통합 테스트, 테스트 구조 |
| **F** | 레드팀 | 적대적 입력, 인증 우회, 정보 유출, 권한 상승 (선택) |

각 단계는 리뷰어 에이전트들 사이의 미니 토론을 실행합니다. 결과는 종합 리뷰 리포트로 집계됩니다 (Markdown 내보내기 가능).

---

## 🧊 컨텍스트 번들 지원

| 소스 종류 | 설명 |
|---|---|
| `inline_text` | 직접 전달된 원시 텍스트 |
| `local_file` | 디스크상의 단일 파일 |
| `local_directory` | 디렉토리 전체 스냅샷 |
| `external_reference` | 메타데이터로 동결된 URL |
| `inline_image` | Base64 인코딩된 이미지 데이터 |
| `local_image` | 디스크상의 이미지 파일 |

> 큰 텍스트 번들은 프롬프트 예산(최대 28,000자)으로 잘립니다. 이미지 바이트는 동결 번들에 보존되지만 텍스트 프롬프트에는 투입되지 않습니다.

---

## 🔌 프로바이더 지원

| 프로바이더 | 타입 | 비고 |
|---|---|---|
| **Claude** | CLI 래퍼 | `claude` CLI 필요. 모델: opus-4-6, sonnet-4-6, haiku-4-5 |
| **Codex** | CLI 래퍼 | `codex` CLI 필요. 모델: gpt-5.4, o3, o4-mini |
| **Gemini** | CLI 래퍼 | `gemini` CLI 필요. 모델: 2.5-pro, 3.1-pro, 3-flash |
| **Ollama** | 로컬 | `ollama` 데몬 필요. 설치된 모델 자동 탐지 |
| **Mock** | 내장 | 테스트용 결정론적 출력 |
| **Custom** | CLI 명령어 | 직접 가져온 모델/명령어 |

커스텀 모델은 무료 또는 유료로 표시할 수 있고, 페르소나 흐름에 연결되며, 내장 에이전트와 동일한 토론 과정에 참여합니다.

### 로컬 런타임 관리

Colosseum은 다음 기능을 갖춘 로컬 **Ollama** 런타임을 관리합니다:
- GPU 장치 감지 (NVIDIA, AMD, CPU)
- `llmfit`을 통한 GPU별 모델 적합성 검사
- 데몬 자동 시작/중지 관리
- 모델 다운로드 오케스트레이션

```bash
colosseum local-runtime status
```

---

<details>
<summary><h2>🗂️ API 레퍼런스</h2></summary>

### 설정 & 탐색

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| `GET` | `/health` | 헬스 체크 |
| `GET` | `/setup/status` | 프로바이더 설치/인증 상태 |
| `GET` | `/models` | 가용 모델 나열 |
| `POST` | `/models/refresh` | 모델 재탐지 강제 |
| `GET` | `/cli-versions` | CLI 버전 정보 |
| `POST` | `/setup/auth/{tool_name}` | 프로바이더 로그인 실행 |
| `POST` | `/setup/install/{tool_name}` | 프로바이더 도구 설치 |

### 로컬 런타임

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| `GET` | `/local-runtime/status` | Ollama/llmfit 상태 (`?ensure_ready=false`) |
| `POST` | `/local-runtime/config` | 로컬 런타임 설정 업데이트 |
| `POST` | `/local-models/download` | 로컬 모델 다운로드 |
| `GET` | `/local-models/fit-check` | llmfit 하드웨어 적합성 검사 (`?model=...`) |

### 런 관리

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| `POST` | `/runs` | 런 생성 (블로킹) |
| `POST` | `/runs/stream` | 런 생성 (스트리밍 SSE) |
| `GET` | `/runs` | 모든 런 나열 |
| `GET` | `/runs/{run_id}` | 런 상세 조회 |
| `POST` | `/runs/{run_id}/skip-round` | 현재 토론 라운드 스킵 |
| `POST` | `/runs/{run_id}/cancel` | 활성 토론 취소 |
| `GET` | `/runs/{run_id}/pdf` | PDF 리포트 다운로드 |
| `GET` | `/runs/{run_id}/markdown` | Markdown 리포트 다운로드 |
| `POST` | `/runs/{run_id}/judge-actions` | 사람 판사 액션 제출 |

### 페르소나 관리

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| `GET` | `/personas` | 모든 페르소나 나열 |
| `POST` | `/personas/generate` | 설문으로부터 생성 |
| `GET` | `/personas/{id}` | 페르소나 상세 조회 |
| `POST` | `/personas` | 커스텀 페르소나 생성 |
| `DELETE` | `/personas/{id}` | 페르소나 삭제 |

### 쿼터 관리

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| `GET` | `/provider-quotas` | 쿼터 상태 조회 |
| `PUT` | `/provider-quotas` | 쿼터 업데이트 |

### UI 라우트

| 라우트 | 설명 |
|---|---|
| `GET /` | 아레나 / 런 설정 화면 |
| `GET /reports/{run_id}` | 배틀 리포트 화면 |

</details>

---

<details>
<summary><h2>📂 저장소 구조</h2></summary>

```
src/colosseum/
├── main.py                 # FastAPI 앱 팩토리 및 서버 진입점
├── cli.py                  # 터미널 인터페이스 및 라이브 토론 UX
├── monitor.py              # tmux 기반 라이브 모니터링
├── bootstrap.py            # 의존성 주입 및 앱 초기화
│
├── api/                    # FastAPI 라우트
│   ├── routes.py           # 라우터 조합
│   ├── routes_runs.py      # 런 CRUD, 스트리밍, 판사 액션
│   ├── routes_setup.py     # 설정, 탐색, 로컬 런타임
│   ├── routes_personas.py  # 페르소나 CRUD 및 생성
│   ├── routes_quotas.py    # 프로바이더 쿼터 관리
│   ├── sse.py              # SSE 페이로드 직렬화
│   ├── validation.py       # 공유 요청 검증
│   └── signals.py          # 라이프사이클 시그널 레지스트리
│
├── core/                   # 도메인 타입 및 설정
│   ├── models.py           # 타입 런타임 스키마 및 요청
│   └── config.py           # Enum, 기본값, depth 프로필, 리뷰 단계
│
├── providers/              # 프로바이더 추상화 레이어
│   ├── base.py             # 추상 프로바이더 인터페이스
│   ├── factory.py          # 프로바이더 인스턴스화 및 가격
│   ├── command.py          # 범용 CLI 커맨드 프로바이더
│   ├── cli_wrapper.py      # CLI 엔벨로프 파서 및 어댑터
│   ├── cli_adapters.py     # Claude, Codex, Gemini CLI 어댑터
│   ├── mock.py             # 결정론적 목 프로바이더
│   └── presets.py          # 모델 프리셋
│
├── services/               # 핵심 비즈니스 로직
│   ├── orchestrator.py     # 런 라이프사이클 구성
│   ├── debate.py           # 라운드 실행 및 프롬프트 조립
│   ├── judge.py            # 플랜 스코어링, 아젠다, 판정, 판결
│   ├── report_synthesizer.py # 최종 리포트 생성
│   ├── review_orchestrator.py # 다단계 코드 리뷰 워크플로우
│   ├── review_prompts.py   # 리뷰 단계 프롬프트 템플릿
│   ├── context_bundle.py   # 동결 컨텍스트 구성
│   ├── context_media.py    # 이미지 추출 및 요약
│   ├── provider_runtime.py # 프로바이더 실행 및 쿼터
│   ├── local_runtime.py    # 관리되는 Ollama/llmfit 런타임
│   ├── repository.py       # 파일 기반 런 퍼시스턴스
│   ├── budget.py           # 예산 원장 추적
│   ├── event_bus.py        # 이벤트 퍼블리싱
│   ├── normalizers.py      # 데이터 정규화 유틸
│   ├── prompt_contracts.py # 프롬프트 에셋 계약
│   ├── pdf_report.py       # PDF 내보내기
│   └── markdown_report.py  # Markdown 리포트 내보내기
│
├── personas/               # 페르소나 시스템
│   ├── registry.py         # 타입 페르소나 메타데이터 및 파싱
│   ├── loader.py           # 페르소나 로드, 캐시, 해석
│   ├── generator.py        # 설문으로부터 페르소나 생성
│   ├── prompting.py        # 페르소나 프롬프트 렌더링
│   ├── builtin/            # 20개의 내장 페르소나
│   └── custom/             # 사용자 생성 페르소나
│
└── web/                    # 정적 웹 UI 에셋
    ├── index.html          # 아레나 설정 UI
    ├── report.html         # 배틀 리포트 표시
    ├── app.js              # 메인 UI 로직
    ├── report.js           # 리포트 렌더링
    └── styles.css          # 스타일링

docs/
├── colosseum_spec.md       # 스펙 인덱스
├── architecture/
│   ├── overview.md         # 계층형 아키텍처 모델
│   └── design-philosophy.md # 핵심 설계 원칙
└── specs/
    ├── runtime-protocol.md # 런 라이프사이클 및 스트리밍 계약
    ├── agent-governance.md # 에이전트, 페르소나, 프로바이더 경계
    └── persona-authoring.md # 페르소나 파일 포맷 및 검증

examples/
└── demo_run.json           # 목 프로바이더 스모크 테스트 페이로드

tests/                      # 테스트 스위트
```

</details>

---

## 🧪 테스트

```bash
# 전체 테스트 스위트 실행
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q

# 빠른 문법 검증
python -m compileall src tests
```

---

## ⚠️ 알려진 제약

- URL 소스는 런 생성 전에 상위에서 가져오지 않으면 메타데이터만 유지됩니다
- 유료 쿼터 추적은 로컬/수동이며 프로바이더와 동기화되지 않습니다
- 내장 벤더 CLI 래퍼는 완전한 SDK 통합보다 얇습니다
- 이미지 인식 토론은 커스텀 커맨드 프로바이더를 통해 가장 잘 지원됩니다
- 아티팩트 퍼시스턴스는 파일 기반이며 데이터베이스 백엔드가 아닙니다
- 실제 토큰 카운트를 사용할 수 없을 때는 `len//4` 추정으로 폴백합니다

---

<div align="center">

**⚔️ 모델들을 싸우게 하라. 근거가 이기게 하라. ⚔️**

*채팅 노이즈가 아닌 구조화된 답을 원하는 사람들을 위해.*

</div>
