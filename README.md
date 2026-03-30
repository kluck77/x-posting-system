# X Posting System - Korean Affairs English Content

**한국 이슈를 해외 독자에게 영어로 전달하는 X(트위터) 포스팅 시스템**

AI가 초안을 만들고, 텔레그램에서 승인하면, X에 자동 게시됩니다.

---

## 이 프로젝트가 하는 것

1. 한국 관련 소스(뉴스, 이슈 등)를 입력합니다
2. AI가 영어 X 포스트 초안을 생성합니다
3. 텔레그램으로 승인 카드가 옵니다
4. Approve 버튼을 누르면 X에 게시됩니다
5. 모든 기록이 데이터베이스에 저장됩니다

## 이 프로젝트가 하지 않는 것

- 웹 대시보드 없음
- 이미지/영상 생성 없음
- 자동 좋아요/팔로우/DM/리플 없음
- 멀티 계정 관리 없음
- 스팸/조작 기능 없음
- 위험 콘텐츠 자동 게시 없음

---

## 사전 준비물

| 항목 | 필수? | 설명 |
|------|-------|------|
| Python 3.11+ | 필수 | 프로그래밍 언어 |
| pip | 필수 | Python 패키지 설치 도구 (Python과 함께 설치됨) |
| 텔레그램 봇 토큰 | 선택 | 없으면 Mock 모드로 실행 |
| X API 키 | 선택 | 없으면 Mock 모드로 실행 |
| OpenAI/Anthropic API 키 | 선택 | 없으면 Mock AI로 실행 |

**API 키가 하나도 없어도 시스템은 Mock 모드로 완전히 작동합니다!**

---

## Windows 설치 가이드 (처음부터 끝까지)

### Step 1: 프로젝트 폴더 열기

1. 파일 탐색기에서 이 프로젝트 폴더를 엽니다
2. 폴더 안의 빈 곳을 Shift + 마우스 우클릭
3. "여기에서 터미널 열기" 또는 "여기에서 PowerShell 열기" 클릭

또는:
```
cd C:\Users\gfeed\Desktop\x모델
```

### Step 2: 가상환경 만들기

가상환경은 이 프로젝트만의 독립된 Python 환경입니다.

```bash
python -m venv venv
```

> 만약 `python`이 안 되면 아래 명령어를 대신 사용하세요:
> ```
> "C:\Users\gfeed\AppData\Local\Python\bin\python.exe" -m venv venv
> ```

### Step 3: 가상환경 활성화

```bash
# PowerShell인 경우:
.\venv\Scripts\Activate.ps1

# CMD (명령 프롬프트)인 경우:
.\venv\Scripts\activate.bat

# Git Bash인 경우:
source venv/Scripts/activate
```

활성화되면 터미널 앞에 `(venv)`가 표시됩니다.

> **PowerShell에서 오류가 나는 경우:**
> ```
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> 를 먼저 실행한 후 다시 시도하세요.

### Step 4: Python 패키지 설치

```bash
pip install -r requirements.txt
```

성공하면 `Successfully installed ...` 메시지가 나옵니다.

### Step 5: 환경변수 설정

`.env.example` 파일을 복사해서 `.env`로 이름을 바꿉니다:

```bash
# PowerShell:
Copy-Item .env.example .env

# CMD:
copy .env.example .env
```

그 다음 `.env` 파일을 메모장으로 열어서 API 키를 입력합니다:

```bash
notepad .env
```

> **중요: .env 파일은 절대 GitHub에 올리면 안 됩니다!**

### Step 6: 데이터베이스 초기화

```bash
python scripts/init_db.py
```

`데이터베이스 초기화 완료!` 메시지가 나오면 성공입니다.

### Step 7: 시스템 실행

```bash
python run.py
```

이 명령 하나로:
- 데이터베이스 초기화
- FastAPI 서버 시작 (http://localhost:8000)
- 텔레그램 봇 시작 (설정된 경우)

**브라우저에서 http://localhost:8000/docs 를 열면 API 문서가 나옵니다.**

---

## .env 파일 설명

### 지금 당장 필요한 키

| 변수 | 설명 | 어디서 받나? |
|------|------|-------------|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | 텔레그램에서 @BotFather에게 `/newbot` |
| `TELEGRAM_CHAT_ID` | 내 채팅 ID | `python scripts/get_telegram_chat_id.py` 실행 |

### X에 게시하려면 필요한 키

| 변수 | 설명 | 어디서 받나? |
|------|------|-------------|
| `X_API_KEY` | X API Consumer Key | https://developer.x.com/en/portal/dashboard |
| `X_API_SECRET` | X API Consumer Secret | 위와 동일 |
| `X_ACCESS_TOKEN` | X Access Token | 위와 동일 |
| `X_ACCESS_TOKEN_SECRET` | X Access Token Secret | 위와 동일 |

### AI 초안 생성에 필요한 키 (선택)

| 변수 | 설명 | 어디서 받나? |
|------|------|-------------|
| `OPENAI_API_KEY` | ChatGPT API 키 | https://platform.openai.com/api-keys |
| `ANTHROPIC_API_KEY` | Claude API 키 | https://console.anthropic.com/settings/keys |

> AI 키를 넣었으면 `.env`에서 `ACTIVE_DRAFT_PROVIDER=openai` (또는 `anthropic`)으로 변경하세요.

### 선택 (나중에)

| 변수 | 설명 |
|------|------|
| `GEMINI_API_KEY` | Google AI 리서치 (미래) |
| `GROK_API_KEY` | xAI 트렌드 탐지 (미래) |
| `PERPLEXITY_API_KEY` | 팩트체크 (미래) |

---

## 텔레그램 승인은 어떻게 작동하나요?

1. 소스를 입력하면 AI가 초안을 생성합니다
2. 텔레그램으로 승인 카드가 옵니다 (훅, 본문, 카테고리, 위험도 표시)
3. 4개 버튼 중 하나를 누릅니다:
   - **Approve** = X에 바로 게시
   - **Reject** = 거절 (DB에 기록)
   - **Defer** = 나중에 다시 검토
   - **Regenerate** = AI가 다시 작성

### 텔레그램 봇 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 봇 소개 메시지 |
| `/status` | AI 프로바이더 상태 확인 |
| `/pending` | 대기 중인 초안 목록 |

---

## X 게시는 어떻게 작동하나요?

1. 텔레그램에서 **Approve** 버튼을 누릅니다
2. 시스템이 X API를 호출해서 포스트를 게시합니다
3. 게시 성공하면 텔레그램에 확인 메시지가 옵니다 (Post ID + URL)
4. DB에 게시 기록이 저장됩니다

**안전 규칙:**
- 승인 없이는 절대 게시되지 않습니다
- 동일한 텍스트는 중복 게시되지 않습니다
- 하루 최대 3회 게시로 제한됩니다

---

## Mock 모드란?

API 키가 없으면 시스템은 자동으로 Mock(가짜) 모드로 전환됩니다.

| 기능 | Mock 모드에서 |
|------|--------------|
| AI 초안 | 미리 만든 샘플 텍스트 반환 |
| 텔레그램 | 로그에만 출력 (실제 전송 안 함) |
| X 게시 | `mock_1234567890` 같은 가짜 ID 반환 |

Mock 모드에서도 전체 파이프라인이 정상 작동하므로 테스트에 유용합니다.

---

## 샘플 데이터로 테스트하기

API 키 없이도 테스트할 수 있습니다:

```bash
python scripts/ingest_sample.py
```

이 스크립트는:
1. 한국 출산율 기사와 반도체 수출 기사를 입력합니다
2. AI 파이프라인을 실행합니다 (Mock 모드)
3. 결과를 DB에 저장합니다

API 서버가 실행 중이라면 브라우저에서도 테스트 가능:
- http://localhost:8000/docs 에서 `/ingest` 엔드포인트 사용
- http://localhost:8000/drafts/pending 에서 대기 중인 초안 확인
- http://localhost:8000/usage 에서 오늘 사용량 확인

---

## 테스트 실행

```bash
pytest tests/ -v
```

현재 76개의 테스트가 있으며, 모든 핵심 기능을 검증합니다:
- 설정 로딩
- 카테고리/위험도 분류
- 승인 필수 로직
- 중복 방지 (URL + 텍스트)
- 일일 사용량 제한
- 텔레그램 콜백 파싱
- X 게시 서비스
- 전체 파이프라인 (E2E)

---

## 일일 사용 제한

월 $30 예산에 맞춘 기본 제한:

| 항목 | 하루 최대 |
|------|----------|
| AI 초안 생성 | 5회 |
| 텔레그램 승인 카드 | 5회 |
| X 게시 | 3회 |

사용량 확인: http://localhost:8000/usage

---

## 자주 발생하는 오류와 해결법

### `python` 명령이 안 될 때
Microsoft Store가 열리는 경우:
```bash
# 전체 경로로 실행
"C:\Users\gfeed\AppData\Local\Python\bin\python.exe" run.py
```

### `ModuleNotFoundError: No module named 'app'`
프로젝트 루트 폴더에서 실행하고 있는지 확인하세요:
```bash
cd C:\Users\gfeed\Desktop\x모델
python run.py
```

### `pip install` 실패
가상환경이 활성화되어 있는지 확인:
```bash
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 텔레그램 봇이 응답하지 않을 때
1. `.env`에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`가 정확한지 확인
2. 텔레그램에서 봇에게 먼저 메시지를 보낸 후 Chat ID 확인:
   ```bash
   python scripts/get_telegram_chat_id.py
   ```

### `ENABLE_AUTO_POST_LOW_RISK=true`로 바꿔도 되나요?
v1에서는 **바꾸지 마세요**. 이 기능은 아직 개발 중이며, 바꿔도 politics/policy/economy/society 카테고리는 여전히 승인이 필요합니다.

---

## GitHub에 안전하게 올리기

### 절대 올리면 안 되는 파일

| 파일 | 이유 |
|------|------|
| `.env` | API 키가 들어있음 |
| `*.db` | 개인 데이터가 들어있음 |
| `*.log` | 내부 로그 |

이 파일들은 `.gitignore`에 이미 등록되어 있어서 실수로 올라가지 않습니다.

### GitHub CLI로 올리기 (gh가 설치된 경우)

```bash
# 1. GitHub에 private 저장소 생성 + 코드 올리기
gh repo create x-posting-system --private --source=. --push

# 끝! 이것 하나면 됩니다.
```

### GitHub CLI 없이 올리기

1. https://github.com/new 에서 새 저장소 만들기
   - Repository name: `x-posting-system`
   - **Private** 선택 (중요!)
   - "Create repository" 클릭

2. 터미널에서:
```bash
git remote add origin https://github.com/YOUR_USERNAME/x-posting-system.git
git branch -M main
git push -u origin main
```

(`YOUR_USERNAME`을 본인 GitHub 아이디로 바꾸세요)

### 커밋하기

```bash
git add -A
git commit -m "설명 메시지"
git push
```

---

## 휴대폰에서 GitHub Mobile로 확인하기

1. 스마트폰에 **GitHub** 앱을 설치합니다
2. 로그인합니다
3. 저장소 목록에서 `x-posting-system`을 찾습니다
4. 할 수 있는 것:
   - 코드 파일 읽기
   - 커밋 이력 확인
   - README 보기
   - Issues 확인
   - Pull Request 확인

---

## 프로젝트 구조

```
x모델/
├── app/                         # 메인 애플리케이션
│   ├── main.py                  # 진입점 (FastAPI + 텔레그램 봇)
│   ├── config.py                # 설정 관리 (.env 읽기)
│   ├── db.py                    # 데이터베이스 연결
│   ├── orchestrator.py          # AI 파이프라인 오케스트레이터
│   ├── telegram_bot.py          # 텔레그램 봇 핸들러
│   ├── api/
│   │   └── admin.py             # FastAPI 관리 API
│   ├── models/
│   │   └── content.py           # DB 모델 + Pydantic 스키마
│   ├── providers/               # AI 프로바이더
│   │   ├── base.py              # 추상 인터페이스
│   │   ├── ai_provider.py       # 프로바이더 팩토리
│   │   ├── mock_providers.py    # Mock (가짜) AI
│   │   ├── openai_provider.py   # ChatGPT 연동
│   │   └── anthropic_provider.py # Claude 연동
│   ├── services/                # 비즈니스 로직
│   │   ├── classifier.py        # 카테고리/위험도 분류
│   │   ├── source_service.py    # 소스 수집
│   │   ├── draft_service.py     # 초안 관리
│   │   ├── telegram_service.py  # 텔레그램 카드 전송
│   │   ├── x_publisher.py       # X 게시
│   │   └── rate_limiter.py      # 일일 사용량 제한
│   └── utils/
│       └── logging_config.py    # 로깅 설정
├── tests/                       # 테스트 (76개)
├── scripts/                     # 유틸리티 스크립트
│   ├── init_db.py               # DB 초기화
│   ├── ingest_sample.py         # 샘플 데이터 입력
│   └── get_telegram_chat_id.py  # 텔레그램 Chat ID 확인
├── .env.example                 # 환경변수 템플릿
├── .gitignore                   # Git 무시 파일 목록
├── requirements.txt             # Python 패키지 목록
├── pytest.ini                   # 테스트 설정
├── run.py                       # 실행 스크립트
└── PROJECT_STATUS.md            # 프로젝트 현황
```

---

## 다음 업그레이드 경로

| 단계 | 내용 | 상태 |
|------|------|------|
| Phase 1 | Mock MVP (전체 파이프라인) | 완료 |
| Phase 2 | 실제 X API 연동 | 완료 (키 입력만 하면 됨) |
| Phase 3 | 실제 AI 연동 (OpenAI/Claude) | 완료 (키 입력만 하면 됨) |
| Phase 4 | Gemini 리서치 연동 | 미래 |
| Phase 5 | Grok 트렌드 탐지 | 미래 |
| Phase 6 | Perplexity 팩트체크 | 미래 |
| Phase 7 | RSS 자동 수집 | 미래 |
| Phase 8 | 저위험 자동 게시 (feature flag) | 미래 |
