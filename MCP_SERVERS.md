# MCP 서버 설정 가이드

이 프로젝트는 `.mcp.json`을 통해 **11개**의 MCP(Model Context Protocol) 서버를
Claude Code에 연결합니다. 최초 실행 시 Claude Code가 각 서버의 사용 승인을
요청합니다.

---

## 1부. 기본 개발 도구 (키 불필요)

| 서버 | 실행 방식 | 용도 |
|------|-----------|------|
| `sqlite` | `uvx mcp-server-sqlite --db-path ./x_poster.db` | DB 조회 (Drafts, ApprovalStatus, 사용량) |
| `fetch` | `uvx mcp-server-fetch` | FastAPI 엔드포인트/외부 URL HTTP 호출 |
| `context7` | `npx -y @upstash/context7-mcp` | 라이브러리 최신 문서 조회 |
| `playwright` | `npx -y @playwright/mcp@latest` | 브라우저 자동화(Safari/WebKit 포함) — 대시보드 디자인 검증 |
| `time` | `uvx mcp-server-time --local-timezone=Asia/Seoul` | KST 기준 시각 계산 (X 게시 최적 시각 등) |

## 2부. GPT↔Claude 왕복 워크플로 최적화 (키 불필요)

현재 작업 방식이 **"GPT 답변 → Claude Code 복붙 → Claude 답변 → GPT 복붙"**
이라면 아래 두 서버가 가장 큰 효율을 냅니다.

| 서버 | 실행 방식 | 왜 중요한가 |
|------|-----------|------------|
| `memory` | `npx -y @modelcontextprotocol/server-memory` | **결정사항·제약·TODO를 영구 저장**. 세션이 달라져도 Claude가 기억함. GPT가 내린 결정을 Claude에게 매번 다시 설명할 필요 없음 |
| `sequential-thinking` | `npx -y @modelcontextprotocol/server-sequential-thinking` | 복잡한 작업을 자동 단계 분해. 초보가 지시를 애매하게 해도 Claude가 혼자 쪼개서 진행 |

### 실전 사용 예
- GPT가 "Task-03 리뷰어 프롬프트 교체하라"고 했을 때:
  → `memory` 서버에 "TASK-03 완료, anthropic_provider.py의 REVIEW_SYSTEM_PROMPT 교체됨" 저장
  → 다음 세션에서 "어제 뭐까지 했지?" 물으면 바로 답변
- "대시보드 만들어줘" 같은 큰 지시:
  → `sequential-thinking`이 자동으로 "1)라우팅 설계 → 2)DB 쿼리 → 3)UI 컴포넌트 → 4)인증" 단계 분해

## 3부. X 팔로워 성장·콘텐츠 품질 (키 필요)

100만 팔로워 목표에는 **트렌드 탐지 + 팩트체크**가 핵심입니다.

| 서버 | 패키지 | 필요 키 | 무료 플랜 |
|------|--------|---------|-----------|
| `brave-search` | `@modelcontextprotocol/server-brave-search` | `BRAVE_API_KEY` | 2000 쿼리/월 |
| `perplexity-ask` | `server-perplexity-ask` | `PERPLEXITY_API_KEY` | 유료 (소액) |

**용도 예시:**
- "오늘 한국에서 화제인 정책 이슈 찾아줘" → `brave-search`
- "이 통계 수치 정확한지 소스 포함해서 검증" → `perplexity-ask`
- 현재 프로젝트 `.env.example`에 `PERPLEXITY_API_KEY`가 이미 예정되어 있음

**키 받기:**
- Brave: https://brave.com/search/api/ (무료 가입)
- Perplexity: https://www.perplexity.ai/settings/api

## 4부. 대시보드·UI 생성 (키 필요)

| 서버 | 패키지 | 필요 키 | 용도 |
|------|--------|---------|------|
| `magic` | `@21st-dev/magic@latest` | `MAGIC_API_KEY` | 자연어 → React/Tailwind 컴포넌트 생성 (초보에게 강력). Safari 호환 |

**키 받기**: https://21st.dev/magic (무료 플랜 있음)

## 5부. 에러 모니터링 (선택)

| 서버 | 필요 키 | 비고 |
|------|---------|------|
| `sentry` | `SENTRY_AUTH_TOKEN` | 현재 프로젝트는 `logging`만 사용. Sentry 도입 전까지는 유휴 상태 OK |

---

## 환경변수 설정 방법

`.env` 파일(프로젝트 루트)에 아래와 같이 추가하면 Claude Code가 자동 인식합니다:

```bash
# 성장/콘텐츠 품질
BRAVE_API_KEY=BSAxxxxxxxxxxxxxx
PERPLEXITY_API_KEY=pplx-xxxxxxxx

# UI 생성
MAGIC_API_KEY=xxxxxxxx

# 에러 모니터링 (나중에)
SENTRY_AUTH_TOKEN=sntrys_xxxxxxxx
SENTRY_HOST=https://sentry.io
```

키가 없으면 해당 서버만 비활성 — 다른 MCP 서버 작동에는 영향 없습니다.

## 사전 요구사항

- `uvx` (uv) — Python 서버 3개(sqlite, fetch, time) 실행용
  - 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `npx` (Node.js 18+) — JS 서버 8개 실행용
- 인터넷 접속 (첫 실행 시 패키지 자동 다운로드)

## 실전 사용 예시 (Claude Code 세션)

```
"최근 7일간 승인 거절된 draft 카테고리별로 집계해줘"
 → sqlite MCP가 Draft 테이블 쿼리

"http://localhost:8000/usage 응답 확인해줘"
 → fetch MCP가 HTTP GET

"한국 정책 관련 오늘의 X 트렌드 찾아줘"
 → brave-search MCP가 실시간 검색

"이 수치 팩트체크해줘: '한국 출산율 0.72'"
 → perplexity-ask MCP가 소스 포함 검증

"FastAPI admin용 '오늘의 게시물' 카드 컴포넌트 만들어줘"
 → magic MCP가 React 코드 생성

"대시보드가 Safari에서 제대로 보이는지 확인해줘"
 → playwright MCP가 WebKit으로 스크린샷
```

## 제외한 MCP 서버

- **filesystem**: Claude Code 내장 Read/Write/Edit로 대체
- **github**: 이 세션에 이미 내장됨 (`mcp__github__*`)
