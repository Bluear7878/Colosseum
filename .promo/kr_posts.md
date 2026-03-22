# Colosseum 한국 프로모션 콘텐츠

## 1. GeekNews 게시글

### 제목
여러 AI 모델이 동시에 토론하는 오픈소스 아레나 - Colosseum

### 본문
ChatGPT, Claude, Gemini를 같은 주제로 동시에 토론시킬 수 있다면? Colosseum은 멀티 에이전트 AI 디베이트 플랫폼으로, 여러 AI 모델이 근거 기반의 논쟁을 벌입니다. 혁신가 페르소나 20+개(일론 머스크, 앤드류 응 등)로 개성 있는 토론을 만들고, 심판(자동/AI/인간)이 주장의 증거 품질을 평가합니다.

로컬 오픈소스 모델(Ollama, HuggingFace GGUF)도 지원해 완전히 무료로 실행 가능합니다. Python & FastAPI 기반, MIT 라이선스.

```bash
colosseum debate -t "AI의 미래" -g claude:claude-sonnet-4-6 codex:o4-mini ollama:llama3.3
```

GitHub: https://github.com/Bluear7878/Colosseum

---

## 2. Disquiet 게시글

### 제목
"AI들이 싸우면 더 나은 답이 나온다" - 개발자가 만든 멀티에이전트 토론 플랫폼

### 본문
처음 이 프로젝트를 시작한 이유는 단순했습니다. ChatGPT, Claude, Gemini는 각각 다른 방식으로 생각하는데, 이들이 함께 토론하면 어떨까?

Colosseum은 AI 모델들이 근거 있는 주장을 하도록 강제하고, 심판(AI 또는 사람)이 어느 쪽 논리가 더 타당한지 평가합니다. 페르소나 시스템으로 일론 머스크처럼, 앤드류 응처럼 생각하는 AI들을 만들 수 있죠.

개발자라면 코드 리뷰도 흥미롭습니다. AI 여러 명이 코드를 6단계 구조로 비판하니까요. 토론 결과는 PDF나 마크다운으로 다운로드할 수 있고, 로컬 모델도 완벽하게 지원됩니다. 웹 UI도 있고 CLI도 있습니다.

GitHub: https://github.com/Bluear7878/Colosseum

---

## 3. 개발자 커뮤니티 블로그 (velog/tistory)

### 제목
[튜토리얼] Python으로 10분 안에 AI 디베이트 시스템 구축하기 - Colosseum

### 본문

AI 여러 개가 한 주제로 토론하는 모습을 보고 싶다면? 오픈소스 프로젝트 **Colosseum**으로 할 수 있습니다. 단계별로 따라해봅시다.

#### 1단계: 설치
```bash
git clone https://github.com/Bluear7878/Colosseum.git
cd Colosseum
python -m pip install -e .
```

#### 2단계: 프로바이더 인증 (선택사항)
```bash
colosseum setup  # 대화형 가이드로 Claude, Codex, Gemini CLI 인증
```
로컬 모델(Ollama)만 사용할 거면 이 단계를 건너뛰어도 됩니다.

#### 3단계: 첫 번째 디베이트 실행
```bash
colosseum debate \
  -t "AI가 인류를 도울까, 위협할까?" \
  -g claude:claude-sonnet-4-6 codex:o4-mini
```

#### 4단계: 결과 확인
`~/.colosseum/runs/<run_id>/` 디렉토리에 결과가 저장됩니다. `colosseum show <run_id>`로 확인하거나, 웹 UI에서 리포트를 PDF/마크다운으로 다운로드할 수 있습니다.

**핵심 특징**: 20+ 페르소나(일론 머스크, 카르파시 등), 증거 품질 추적, 코드 리뷰 모드, 로컬 모델 완벽 지원(Ollama, HuggingFace), MIT 라이선스.

처음엔 간단한 2-3개 모델로 시작해서, 점차 페르소나를 더하거나 복잡한 주제로 확장해보세요. 커뮤니티 포크도 대환영입니다! 🚀

GitHub: https://github.com/Bluear7878/Colosseum

