# MCP 서버 설정 가이드

이 프로젝트는 `.mcp.json`을 통해 5개의 MCP(Model Context Protocol) 서버를
Claude Code에 연결합니다. 최초 실행 시 Claude Code가 각 서버의 사용 승인을
요청합니다.

## 설치된 MCP 서버

| 서버 | 실행 방식 | 용도 |
|------|-----------|------|
| `sqlite` | `uvx mcp-server-sqlite --db-path ./x_poster.db` | DB 조회 (Drafts, ApprovalStatus, 사용량 등) |
| `fetch` | `uvx mcp-server-fetch` | FastAPI 엔드포인트/외부 URL HTTP 호출 |
| `context7` | `npx -y @upstash/context7-mcp` | 라이브러리 최신 문서 조회 (FastAPI, SQLAlchemy 2.x, PTB 21 등) |
| `playwright` | `npx -y @playwright/mcp@latest` | 브라우저 자동화 / 향후 admin UI 디자인 검증 |
| `sentry` | `npx -y @sentry/mcp-server` | Sentry 에러/이벤트 조회 (선택) |

## 사전 요구사항

- `uvx` (uv 패키지 매니저) — Python 기반 서버용. 없다면 `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `npx` (Node.js 18+) — JS 기반 서버용
- 인터넷 접속 (패키지 자동 다운로드)

## 환경변수

`sentry` 서버는 아래 환경변수가 있어야 인증됩니다 (없으면 기능 제한됨):

```bash
export SENTRY_AUTH_TOKEN="sntrys_..."
export SENTRY_HOST="https://sentry.io"   # self-hosted인 경우 URL 변경
```

현재 프로젝트는 Sentry를 적극 사용하지 않으므로, 토큰을 설정하지 않으면
`sentry` 서버는 연결 실패 상태로 남습니다. Claude Code의 다른 MCP 서버
동작에는 영향 없습니다.

다른 4개 서버(`sqlite`, `fetch`, `context7`, `playwright`)는 별도 키 불필요.

## 사용 예시 (Claude Code 세션)

- "드래프트 중 risk_level='high' 인 것 최근 10개 보여줘"
  → `sqlite` MCP가 `Draft` 테이블 쿼리
- "http://localhost:8000/usage 응답 확인해줘"
  → `fetch` MCP가 HTTP GET
- "python-telegram-bot 21.x의 CallbackQueryHandler 최신 시그니처 찾아줘"
  → `context7` MCP가 공식 문서 조회

## 제외한 MCP 서버 (중복이므로)

- **filesystem**: Claude Code 내장 Read/Write/Edit로 대체
- **github**: 이 세션에 이미 내장됨 (`mcp__github__*` 툴들)
