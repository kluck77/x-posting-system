# X Posting System

**한국 이슈를 해외 독자에게 영어로 전달하는 X(트위터) 자동화 포스팅 시스템**

*Approval-based X posting pipeline: Korean source → AI draft → Telegram approval → publish.*

---

## 이 프로젝트가 하는 것 / 안 하는 것

**하는 것**
- 한국 뉴스·커뮤니티 소스를 입력하면 영어 X 포스트 초안을 AI가 생성합니다
- 텔레그램으로 승인 카드를 전송합니다 (Approve / Reject / Defer / Regenerate)
- Approve를 눌러야만 X에 게시됩니다
- 모든 기록이 SQLite DB에 저장됩니다

**안 하는 것**
- 승인 없이 자동 게시 없음
- 자동 좋아요 / 팔로우 / DM / 리플 없음
- 스팸·조작 기능 없음
- 위험 콘텐츠 자동 게시 없음

---

## AI 파이프라인

```
소스 입력
  └─▶ Gemini (Researcher)       — 배경 리서치 & 해석 갭 발굴
        └─▶ OpenAI (DraftWriter) — 영어 초안 생성
              └─▶ Perplexity (FactChecker) — 팩트 검증
                    └─▶ Claude (Reviewer)  — 품질·리스크 최종 판단
                          └─▶ 텔레그램 승인 카드
                                └─▶ [Approve] X 게시
별도: Grok (TrendHunter) — /trends 명령으로 트렌드 탐색
```

5-Criteria 품질 필터 (자동):
`expertise` / `marketability` / `consistency` / `follower_quality` / `repeat_consumption`
기준 미달 초안은 자동 재생성됩니다.

---

## 빠른 시작

**API 키가 하나도 없어도 Mock 모드로 전체 파이프라인이 동작합니다.**

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 입력 (없으면 Mock 모드로 자동 실행)

# 3. 실행
python run.py
# → FastAPI: http://localhost:8000/docs
# → 텔레그램 봇 자동 시작 (토큰이 있는 경우)

# 4. 샘플 데이터로 파이프라인 테스트
python scripts/ingest_sample.py

# 5. 테스트
pytest tests/ -v
```

Windows 상세 설치 → [docs/SETUP_WINDOWS.md](docs/SETUP_WINDOWS.md)

---

## Mock 모드

API 키 없이도 전체 파이프라인을 테스트할 수 있습니다.

| 기능 | Mock 모드에서 |
|------|--------------|
| AI 초안 | 미리 정의된 샘플 텍스트 반환 |
| 텔레그램 | 터미널 로그에만 출력 |
| X 게시 | `mock_1234567890` 가짜 ID 반환 |

---

## 텔레그램 봇 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/start` | 봇 소개 |
| `/status` | AI 프로바이더 상태 |
| `/pending` | 승인 대기 초안 목록 |
| `/trends [키워드]` | Grok 트렌드 탐색 |
| `/url [링크]` | URL 수집 후 포스팅 파이프라인 실행 |
| `/digest` | 아침 뉴스 다이제스트 |
| `/queue` | 게시 큐 현황 |
| `/report` | 주간 리포트 |

승인 카드 버튼: **Approve** · **Reject** · **Defer** · **Regenerate**

---

## 안전 규칙 (코드에서 강제)

- 승인 없이 절대 게시 안 됨
- politics / policy / economy / society 카테고리는 항상 승인 필요
- 동일 텍스트 중복 게시 방지
- 하루 최대 게시 3회

---

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 헬스 체크 |
| GET | `/status` | AI 프로바이더 상태 |
| POST | `/ingest` | 소스 입력 + 파이프라인 실행 |
| GET | `/drafts/pending` | 승인 대기 목록 |
| POST | `/drafts/{id}/approve` | 승인 + X 게시 |
| POST | `/drafts/{id}/reject` | 거절 |
| POST | `/drafts/{id}/retry` | 재시도 |
| GET | `/usage` | 일일 사용량 |

전체 문서: http://localhost:8000/docs

---

## 프로젝트 구조

```
x-posting-system/
├── app/
│   ├── main.py                  # FastAPI + 텔레그램 봇 진입점
│   ├── config.py                # 설정 (.env 읽기)
│   ├── db.py                    # SQLite 연결
│   ├── orchestrator.py          # AI 파이프라인 오케스트레이터
│   ├── telegram_bot.py          # 텔레그램 봇 핸들러
│   ├── api/admin.py             # FastAPI 관리 API
│   ├── models/content.py        # DB 모델 + Pydantic 스키마
│   ├── providers/               # AI 프로바이더 (5개)
│   │   ├── base.py              # 추상 인터페이스
│   │   ├── ai_provider.py       # 프로바이더 팩토리
│   │   ├── openai_provider.py   # DraftWriter (ChatGPT)
│   │   ├── anthropic_provider.py # Reviewer (Claude)
│   │   ├── gemini_provider.py   # Researcher (Gemini)
│   │   ├── grok_provider.py     # TrendHunter (Grok)
│   │   ├── perplexity_provider.py # FactChecker (Perplexity)
│   │   └── mock_providers.py    # Mock AI (API 키 불필요)
│   └── services/
│       ├── classifier.py        # 카테고리·위험도 분류
│       ├── quality_scorer.py    # 5-Criteria 품질 채점
│       ├── content_fetcher.py   # URL 수집 (3단계 fallback)
│       ├── prediction_service.py # 게시 시간 예측
│       ├── telegram_service.py  # 승인 카드 전송
│       ├── x_publisher.py       # X 게시
│       ├── rate_limiter.py      # 일일 사용량 제한
│       ├── morning_digest.py    # 아침 뉴스 다이제스트
│       ├── news_monitor.py      # 뉴스 모니터링
│       ├── rss_fetcher.py       # RSS 수집
│       ├── naver_news.py        # 네이버 뉴스 API
│       ├── vision_service.py    # 이미지 분석
│       └── growth/              # 계정 성장 파이프라인
│           ├── post_queue.py    # 최적 시간대 게시 스케줄러
│           ├── comment_hunter.py # 트렌드 댓글 초안 생성
│           ├── reply_monitor.py # 멘션 모니터링
│           └── weekly_report.py # 주간 성과 리포트
├── tests/                       # 자동화 테스트
├── scripts/
│   ├── init_db.py               # DB 초기화
│   ├── ingest_sample.py         # 샘플 데이터 테스트
│   └── get_telegram_chat_id.py  # 텔레그램 Chat ID 확인
├── docs/
│   ├── SETUP_WINDOWS.md         # Windows 상세 설치 가이드
│   └── ENV_GUIDE.md             # .env 환경변수 전체 참조
├── .env.example                 # 환경변수 템플릿
├── requirements.txt
└── run.py                       # 실행 진입점
```

---

## 로드맵

| 단계 | 내용 | 상태 |
|------|------|------|
| v1 | Mock MVP — 전체 파이프라인 | 완료 |
| v2 | 실제 X API + OpenAI/Claude 연동 | 완료 |
| v3 | Gemini / Grok / Perplexity 연동 | 완료 |
| v4 | 5-Criteria 품질 프레임워크 | 완료 |
| v4 | URL 수집 3단계 fallback (Jina AI) | 완료 |
| v4 | Growth 파이프라인 (Queue/Hunter/Monitor) | 완료 |
| v5 | RSS 자동 수집 & 뉴스 모니터 | 진행 중 |
| v6 | 저위험 자동 게시 (feature flag) | 계획 중 |

---

## 상세 문서

- [Windows 설치 가이드](docs/SETUP_WINDOWS.md)
- [환경변수(.env) 전체 참조](docs/ENV_GUIDE.md)
- [프로젝트 현황](PROJECT_STATUS.md)
