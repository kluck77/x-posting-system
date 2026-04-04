# 환경변수(.env) 전체 참조

`.env.example`을 복사해서 `.env`로 이름을 바꾼 뒤, 아래 설명을 참고해 값을 채워 넣으세요.

**API 키가 없어도 됩니다.** 키가 없는 역할은 자동으로 Mock 모드로 전환됩니다.

---

## AI 프로바이더 (5개 역할)

| 변수 | 역할 | 어디서 받나 | 월 비용 |
|------|------|------------|--------|
| `OPENAI_API_KEY` | DraftWriter — 영어 초안 생성 | https://platform.openai.com/api-keys | ~$2 |
| `ANTHROPIC_API_KEY` | Reviewer — 품질·리스크 판단 | https://console.anthropic.com/settings/keys | ~$3 |
| `GEMINI_API_KEY` | Researcher — 배경 리서치 | https://aistudio.google.com/app/apikey | 무료 |
| `GROK_API_KEY` | TrendHunter — 트렌드 탐지 | https://console.x.ai/ | ~$1 |
| `PERPLEXITY_API_KEY` | FactChecker — 팩트 검증 | https://www.perplexity.ai/settings/api | ~$2 |

5개 모두 사용 시 약 **$8/월** (30 posts/day 기준).

### 프로바이더 선택 로직

```
ACTIVE_DRAFT_PROVIDER=   # 비워두면 자동: openai → anthropic → mock
```

나머지 역할은 키 보유 여부로 자동 선택됩니다:
- Reviewer: `anthropic` → `mock`
- Researcher: `gemini` → `mock`
- TrendHunter: `grok` → `mock`
- FactChecker: `perplexity` → `mock`

---

## 텔레그램

| 변수 | 설명 | 어디서 받나 |
|------|------|------------|
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 | 텔레그램 @BotFather → `/newbot` |
| `TELEGRAM_CHAT_ID` | 내 채팅 ID | `python scripts/get_telegram_chat_id.py` |

---

## X (트위터) API

| 변수 | 설명 |
|------|------|
| `X_API_KEY` | Consumer Key |
| `X_API_SECRET` | Consumer Secret |
| `X_ACCESS_TOKEN` | Access Token |
| `X_ACCESS_TOKEN_SECRET` | Access Token Secret |

발급: https://developer.x.com/en/portal/dashboard
(Free tier로 게시 가능, 월 500 posts 제한)

---

## 네이버 뉴스 API

| 변수 | 설명 |
|------|------|
| `NAVER_CLIENT_ID` | 네이버 앱 Client ID |
| `NAVER_CLIENT_SECRET` | 네이버 앱 Client Secret |

발급: https://developers.naver.com/apps/#/register (뉴스 검색 권한 선택)
무료, 일 25,000회.

---

## 뉴스 모니터 설정

```bash
MONITOR_ENABLED=true
MONITOR_INTERVAL_MINUTES=1       # 모니터링 주기 (분)
MONITOR_MAX_ALERTS_PER_RUN=3     # 한 사이클 최대 알림 수
CROSS_VERIFY_MIN_SOURCES=4       # 속보 전송 전 최소 교차 확인 출처 수
```

---

## 모닝 다이제스트

```bash
DIGEST_ENABLED=true
DIGEST_HOUR_KST=5                # 전송 시각 (KST, 기본 오전 5시)
DIGEST_TOP_N=5                   # 포함할 기사 수
```

---

## 일일 사용량 제한

```bash
DAILY_DRAFT_LIMIT=5              # AI 초안 생성 최대 횟수
DAILY_TELEGRAM_LIMIT=5           # 텔레그램 승인 카드 최대 횟수
DAILY_POST_LIMIT=3               # X 게시 최대 횟수
```

사용량 확인: http://localhost:8000/usage

---

## 자동 게시 (비활성 기본값)

```bash
ENABLE_AUTO_POST_LOW_RISK=false  # 기본값 유지 권장
```

> `true`로 바꿔도 `politics / policy / economy / society` 카테고리는 여전히 승인이 필요합니다.
> 현재 이 기능은 개발 중입니다.

---

## 기타

```bash
DATABASE_URL=sqlite:///./data/x_posting.db   # DB 경로
LOG_LEVEL=INFO                               # DEBUG / INFO / WARNING
DEFAULT_LANGUAGE=english                     # 초안 언어
```
