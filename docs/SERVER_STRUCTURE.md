# SERVER STRUCTURE

서버 본체의 물리적 구조와 배포 규칙을 기록한다.
**이 문서가 없으면 매 세션마다 서버 상태를 처음부터 조사해야 한다.**

최종 갱신 : 2026-04-10 KST (네이버 자동수집 파이프라인 검증 — 구조 분리 확인)

---

## 1. 서버 개요

| 항목 | 값 |
|---|---|
| 호스팅 | Vultr VPS |
| OS | Ubuntu 24.04.4 LTS (GNU/Linux 6.8.0-101-generic x86_64) |
| IP | 107.191.61.190 |
| 디스크 | 8.82 GB (사용 53.4%) |
| 앱 루트 | `/root/x-posting-system/` |
| Python venv | `/root/x-posting-system/venv/` |
| Python 실행 | `/root/x-posting-system/venv/bin/python` |
| 엔트리포인트 | `/root/x-posting-system/run.py` |

---

## 2. systemd 서비스

| 항목 | 값 |
|---|---|
| 유닛명 | `xdashboard.service` |
| 유닛 파일 | `/etc/systemd/system/xdashboard.service` |
| 설명 | X Posting System (dashboard + telegram + scheduler) |
| 실행 명령 | `/root/x-posting-system/venv/bin/python /root/x-posting-system/run.py` |
| 메모리 피크 | ~70 MB |

**주의 : 유닛명은 `x-posting` 이 아니라 `xdashboard` 이다.**

```bash
# 상태 확인
systemctl status xdashboard --no-pager

# 재시작
systemctl restart xdashboard

# 로그 (최근 50줄)
journalctl -u xdashboard -n 50 --no-pager

# 프로세스 확인
ps -ef | grep -E 'python|uvicorn|gunicorn' | grep -v grep
```

---

## 3. 서버 HEAD vs 작업 브랜치

서버와 GitHub 작업 브랜치는 **별개의 코드 베이스**다. 전체 pull / 전체 checkout 금지.

| 항목 | 서버 (2026-04-09 기준) | 작업 브랜치 |
|---|---|---|
| 브랜치 | `temp/phase8a-observe-bypass-20260408-042459` | `claude/x-posting-ops-review-7hlxK` |
| HEAD | `58f89b05` | `2413a71` |
| orchestrator.py | 745줄 (고급 기능 + Step 1.5/1.5b/1.6/1.7 삽입) | 417줄 (Phase H 포함) |

### 서버에만 있는 orchestrator 기능 (브랜치에 없음)

- `_build_criteria_context()` 헬퍼 (TrendHunter / Gemini / Perplexity 신호 → 프롬프트)
- Step 4.5 : 5-Criteria 품질 필터 (`score_5criteria`, `REGEN_THRESHOLD`)
- Step 5.5 : Reviewer regenerate 루프 (`MAX_REGEN_ATTEMPTS=2`)
- Layer 2 : `operator_hints` → DraftWriter 주입
- Layer 2 : `research.interpretation_gaps` → `enriched_source`
- `classify_community_risk` / `build_community_warning` (커뮤니티 입력 리스크)
- `business_classifier` 전체 블록 (premium / b2b / email 자동 분류)
- `prediction_service` / `predict_publish_time`
- `get_trending_topics()` (TrendHunter / Grok)

### 서버에만 있는 import (브랜치에 없음)

```python
from datetime import datetime, timezone
from app.services.classifier import classify_community_risk, build_community_warning
from app.services.prediction_service import predict_publish_time
from app.services.quality_scorer import (
    score_draft, score_5criteria, format_5criteria_report,
    should_regenerate, REGEN_THRESHOLD,
)
from app.providers.base import FactCheckResult, TrendResult
```

### Phase B/C 서버 반영 완료 (2026-04-09 07:17 UTC)

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/services/breaking_classifier.py` | Phase B: `git show` 배치 | ✅ sha256 `16086c70...` |
| `app/services/breaking_alert_service.py` | Phase B: `git show` 배치 | ✅ sha256 `a808e815...` |
| `app/orchestrator.py` Step 1.5/1.6 | Phase C: `patch -p1` 삽입 (+37줄) | ✅ 643→680줄, py_compile OK |

### Phase D+E 서버 반영 완료 (2026-04-09 ~09:30 UTC)

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/services/top5_briefing_service.py` | Phase D: `git show` 배치 | ✅ sha256 `6a71367c...` |
| `app/orchestrator.py` Step 1.5b | Phase E: Python 삽입 스크립트 (+17줄) | ✅ CANDIDATE record_candidate() |
| `app/orchestrator.py` Step 1.6 내부 | Phase E: Python 삽입 스크립트 (+10줄) | ✅ BREAKING_NOW record_breaking_sent() |

- orchestrator.py: 680 → 707줄 (+27)
- 롤백: `cp /tmp/orchestrator.py.bak.phase_e app/orchestrator.py && systemctl restart xdashboard`

### Phase F 서버 반영 완료 (2026-04-09 20:28 UTC) — 실측 재확인 2026-04-09 23:19 UTC

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/main.py` | Phase F: `git show` 전체 교체 | ✅ 서버 반영 완료 (실측 재확인) |

- `_top5_scheduler_loop()` : 매일 05:00 KST `run_top5_briefing()` 자동 실행
- `asyncio.create_task()` 로 기존 이벤트루프에 합류 (외부 패키지 불필요)
- 반영: `git fetch origin claude/x-posting-ops-review-7hlxK` → `git show origin/...:app/main.py > app/main.py`
- 롤백: `cp /tmp/main.py.bak.phase_f app/main.py && systemctl restart xdashboard`
- 실측 근거 (2026-04-09 23:19 UTC):
  - 서버 main.py: `_top5_scheduler_loop` line 23, `create_task` line 82 확인
  - server.log: `[top5-scheduler] 05:00 KST 자동 실행 등록` + `다음 실행: 2026-04-11T05:00:00+09:00`
  - xdashboard: active (running), PID 210696

### KO-only 분기 미동작 수정 — 서버 반영 완료 (2026-04-09 22:31 UTC)

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/services/breaking_classifier.py` | `git show` 전체 교체 | ✅ 서버 반영 완료 |

- Root Cause: MIN_BODY_CHARS=80 가드 → 짧은 본문 HOLD → topic_domain="none" → KO-only 실패
- Fix: 제목에 STRONG 키워드 있으면 CANDIDATE 구제 (+7줄)
- smoke test: 금융 + 크립토 2건 모두 KO-only 라우팅 성공
- 롤백: `cp /tmp/breaking_classifier.py.bak app/services/breaking_classifier.py && systemctl restart xdashboard`

### /ingest 응답 문구 정합성 수정 — 서버 반영 완료 (2026-04-09 22:07 UTC)

| 파일 | 변경 내용 | 상태 |
|---|---|---|
| `app/orchestrator.py` | full_pipeline() 응답 메시지를 처리 경로별 조건 분기로 교체 + docstring | ✅ 서버 반영 완료 |
| `app/api/admin.py` | /ingest endpoint docstring 수정 | ✅ 서버 반영 완료 |

- orchestrator.py: 764 → 775줄 (+11, 메시지 분기 블록)
- 변경 전: 모든 경로에서 `"초안 생성 완료! 텔레그램에서 승인해주세요."` 고정
- 변경 후: BREAKING_NOW KO-only / CANDIDATE KO-only / approval 전송 / approval 미전송 4가지 분기
- smoke test: 일반 기사 → `"초안 생성 완료. 텔레그램에서 승인해주세요."` (approval 정상)
- 롤백: `cp /tmp/orchestrator.py.bak.ingest_msg app/orchestrator.py && cp /tmp/admin.py.bak.ingest_msg app/api/admin.py && systemctl restart xdashboard`

### 실기사 통합 검증 (2026-04-09 23:19 UTC)

- 입력: "4월 금통위 기준금리 동결 결정 — 시장 예상 부합" (금융, 본문 5문장, URL 포함)
- 결과:
  - classification=CANDIDATE, topic_domain=금융, draft_id=23
  - KO-only 라우팅 정상: `[1.7/6] English draft skipped: CANDIDATE domain=금융`
  - 응답: "한국어 전용 라인으로 처리되었습니다. 영어 승인 초안은 생성하지 않았습니다."
  - telegram_sent=false, 영어 approval 카드 0건
  - DB candidate_pool_entries id=5 적재 확인
- 검증 범위: classifier → KO-only 분기 → DB 적재 → 응답 문구 전체 정상

### 네이버 자동수집 파이프라인 검증 (2026-04-10 00:15 UTC)

- **결론: news_monitor와 full_pipeline은 별도 시스템 (연결 없음)**
- news_monitor (`app/services/news_monitor.py`):
  - APScheduler 1분 간격 → RSS + Naver API 수집 → 교차 확인(4+출처) → 텔레그램 직접 발송
  - `_ingest_article()` = 클러스터 추가 함수, full_pipeline 미호출
  - 현재 중단: APScheduler 초기화 코드 코드베이스에 없음 (`grep add_job|AsyncIOScheduler` 0건)
  - 마지막 실행: 2026-04-09 08:29 UTC
- /ingest → full_pipeline:
  - breaking_classifier → BREAKING_NOW/CANDIDATE/HOLD/REJECT → KO-only/approval
  - 수동 입력 전용 (현재)
- DB 경로: `/root/x-posting-system/x_poster.db` (`data/xposting.db` 아님)
- DB 테이블: source_items, drafts, post_logs, cta_copies, breaking_dedup_entries, candidate_pool_entries, breaking_sent_keys
- candidate_pool_entries 5건: 전부 수동 /ingest 테스트

### 운영 관측성 수정 (서버 반영 대기)

| 파일 | 변경 내용 | 상태 |
|---|---|---|
| `app/api/admin.py` | `db.execute("SELECT 1")` → `db.execute(text("SELECT 1"))` | ⏳ 서버 반영 대기 |
| `app/utils/logging_config.py` | `StreamHandler(sys.stdout)` → `StreamHandler(sys.stderr)` | ⏳ 서버 반영 대기 |

- database_ok=false 원인: SQLAlchemy 2.x 에서 bare string SQL 은 `text()` 래핑 필수
- journalctl 로그 미출력 원인: stdout 은 systemd 파이프에서 full buffering, stderr 는 unbuffered
- 롤백: `cp /tmp/admin.py.bak app/api/admin.py && cp /tmp/logging_config.py.bak app/utils/logging_config.py && systemctl restart xdashboard`

### 주간 고점수 CANDIDATE 즉시 알림 (서버 반영 대기)

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/services/daytime_alert_service.py` | `git show` 신규 배치 | ⏳ 서버 반영 대기 |
| `app/orchestrator.py` Step 1.5c | 수술식 삽입 (~15줄, Step 1.5b 직후) | ⏳ 서버 반영 대기 |

- 조건: 주간 05:00~22:00 KST + matched_keywords >= 4 + score >= 55 + 수집 후 2h 이내
- `score_candidate()` 재사용, `[주간 주목]` 카드 형식
- fail-open, Top5/BREAKING_NOW 무간섭
- 롤백: `rm app/services/daytime_alert_service.py && cp /tmp/orchestrator.py.bak.daytime app/orchestrator.py && systemctl restart xdashboard`

### Phase H 서버 반영 완료 (2026-04-09 11:00 UTC)

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/orchestrator.py` Step 1.7 | Phase H: base64 Python 스크립트, 수술식 삽입 (+31줄) | ✅ |
| `app/orchestrator.py` full_pipeline | Phase H: 1줄→6줄 교체 (+5줄) | ✅ |
| `app/orchestrator.py` _handle_regenerate | Phase H: 1줄→3줄 교체 (+2줄) | ✅ |

- orchestrator.py: 707 → 745줄 (+38)
- Step 1.7: BREAKING_NOW/CANDIDATE + 금융/투자/크립토/주식 → 영어 초안 + 승인 카드 우회
- full_pipeline / _handle_regenerate: `_skip_approval_card` 플래그로 `send_for_approval()` 조건부 생략
- HOLD/REJECT/비대상 도메인 → 기존 파이프라인 100% 유지
- fail-open: 판정 실패 시 기존 영어 파이프라인 그대로 실행
- 롤백: `cp /tmp/orchestrator.py.bak.phase_h app/orchestrator.py && systemctl restart xdashboard`

### 브랜치에만 있는 파일 (서버에 없음)

- `app/services/candidate_filter.py`
- `app/services/daytime_alert_service.py` (서버 반영 대기)

---

## 4. 서버 app/services/ 파일 목록 (2026-04-09 Phase D 반영 후)

```
__init__.py
advisory.py
b2b_candidate_service.py
breaking_alert_service.py
breaking_classifier.py
brief_offer_service.py
business_classifier.py
classifier.py
content_fetcher.py
content_pack.py
cta_copy_service.py
draft_service.py
email_lead_service.py
growth/
morning_digest.py
naver_news.py
naver_usage.py
news_monitor.py
newsletter_routine_service.py
prediction_service.py
premium_candidate_service.py
quality_scorer.py
rate_limiter.py
repetition_guard.py
rss_fetcher.py
source_service.py
telegram_service.py
top5_briefing_service.py
topic_memory.py
vision_service.py
voice_guard.py
weekly_report_service.py
x_publisher.py
```

---

## 5. 배포 규칙 (RUNNER_RULES §6 보강)

### 5.1 절대 금지

- `git pull` / `git checkout <branch>` 전체 교체 금지.
- 브랜치의 orchestrator.py 를 서버에 전체 덮어쓰기 금지.
  (서버 고유 기능이 삭제된다.)

### 5.2 허용되는 반영 방식

1. **신규 파일** : `git show <sha>:<path> > <path>` 로 서버에 새 파일 배치.
   - 기존 파일과 이름이 겹치지 않으면 안전.
2. **기존 파일 수술식 수정** : `sed` / `patch` / 수동 편집으로 특정 블록만 삽입.
   - 삽입 전 반드시 `cp <file> /tmp/<file>.bak` 백업.
   - 삽입 후 `py_compile` + import smoke 필수.
3. **독립 서비스 파일** : 다른 모듈에서 import 하지 않는 파일은 배치만으로 무영향.
   orchestrator 등이 lazy import (try/except 내부) 하도록 설계되어 있어야 한다.

### 5.3 검증 순서

```bash
# 1) 문법
/root/x-posting-system/venv/bin/python -m py_compile <대상파일>

# 2) import smoke
/root/x-posting-system/venv/bin/python -c "from <module> import <symbol>; print('OK')"

# 3) 렌더/기능 smoke (실 발송 없이)
/root/x-posting-system/venv/bin/python -c "<테스트 코드>"

# 4) 서비스 재시작
systemctl restart xdashboard

# 5) 로그 관찰
journalctl -u xdashboard -n 30 --no-pager
```

### 5.4 롤백

```bash
cp /tmp/<file>.bak <원본 경로>
systemctl restart xdashboard
```

---

## 6. orchestrator.py 삽입 가이드

서버 orchestrator.py 에 새 기능 블록을 추가할 때의 원칙.

### 6.1 삽입 위치 결정

서버 orchestrator.py 의 `ingest_and_generate()` 내부 Step 순서 :

```
Step 0  : 일일 제한 확인
Step 1  : 소스 DB 저장                          ← 줄 153~155
Step 1.5: BREAKING 분류 (fail-open)             ← 줄 157~175 ✅ Phase C
Step 1.5b: CANDIDATE → record_candidate()       ← 줄 175~191 ✅ Phase E
Step 1.5c: 주간 고점수 CANDIDATE 즉시 알림       ← 줄 ~192 ⏳ 서버 반영 대기
Step 1.6: BREAKING_NOW 텔레그램 핸드오프         ← 줄 193~209 ✅ Phase C+E
          └ record_breaking_sent() (Top5 제외)   ← 줄 200~208 ✅ Phase E
Step 1.7: 한국어 전용 라인 분기 (early return)    ← ✅ Phase H (서버 반영 완료)
          └ BREAKING_NOW/CANDIDATE + 금융/투자/크립토/주식
            → 영어 초안 파이프라인 전체 우회
            → 최소 Draft 레코드 + _skip_approval_card=True
Step 2  : Researcher — 배경 리서치               ← 줄 221~
Step 3  : DraftWriter — 초안 생성
Step 4  : FactChecker — 팩트체크
Step 4.5: 5-Criteria 품질 필터 (서버 고유)
Step 5  : Reviewer — 최종 판단
Step 5.5: Reviewer regenerate 루프 (서버 고유)
Step 6  : 분류 & 위험도 확정
          (이후 community_risk / business_classifier / prediction_service)
```

### 6.2 안전한 삽입 패턴

```python
# Step X.Y: 새 기능 (fail-open)
try:
    from app.services.new_module import new_function
    result = new_function(...)
    logger.info(f"[X.Y/6] ...")
except Exception as e:
    logger.warning(f"새 기능 실패 (fail-open, 파이프라인 계속): {e}")
```

- 반드시 `try/except` 로 감싸서 fail-open.
- import 는 함수 본문 내 lazy import (top-level 금지).
- 기존 Step 의 변수 (`source_item`, `research`, `draft_result` 등) 만 읽기 전용 참조.
- 새 변수를 기존 Step 에 주입하지 않는다 (runtime-only 속성은 예외).

---

## 7. 운영 메모

- 서버 디스크 53.4% 사용 중 (8.82 GB) — 대용량 파일 추가 주의.
- `System restart required` 경고 있음 (OS 커널 업데이트 대기).
- `.env.bak.*` 파일 다수 존재 (`.env.bak.approvalkr`, `.env.bak.krapproval2`, `.env.bak.promotetest`).
- `_baseline_20260408/` 디렉토리 존재 (이전 baseline 스냅샷).

---

## 8. 영속화 테이블 (서버 반영 대기)

Dedup/Candidate Pool 영속화를 위해 SQLite 에 3개 테이블 추가 예정.
`init_db()` 호출 시 `Base.metadata.create_all()` 로 자동 생성. ✅ 서버 반영 완료 (2026-04-09).

| 테이블 | 용도 | 핵심 컬럼 | 상태 |
|---|---|---|---|
| `breaking_dedup_entries` | BREAKING_NOW 전송 기록 (6h dedup) | issue_key, sent_at (epoch) | ✅ 생성 완료 |
| `candidate_pool_entries` | 야간 CANDIDATE 기사 풀 | title, body, topic_domain, matched_keywords_json, cycle_date | ✅ 생성 완료 |
| `breaking_sent_keys` | BREAKING_NOW→Top5 제외 키 | issue_key, cycle_date | ✅ 생성 완료 |

- 인메모리 1차 + DB write-through 구조 (fail-open)
- 시작 시 DB → 메모리 lazy-load 복원
- 05:00 브리핑 전송 후 현재 사이클 데이터 삭제
- `debug_*.txt` 파일 존재 (이전 디버깅 로그).
- `scripts/collect_debug_bundle.sh` 존재.
- `static/` 디렉토리에 AI 역할 아바타 이미지 존재.

---

## 9. AI 운영 구조 연결

AI 6축 운영 구조의 전체상은 `docs/AI_OPERATING_LAYER.md` 에 정리되어 있다.
서버와 관련된 핵심 연결점만 아래에 기록한다.

### 9.1 네이버 자동수집 (서버 전용 파일)

| 파일 | 역할 |
|------|------|
| `app/services/naver_news.py` | 네이버 뉴스 API 호출 |
| `app/services/naver_usage.py` | 네이버 API 할당량 추적 (25,000/일) |
| `app/services/news_monitor.py` | 폴링 오케스트레이션 |
| `app/services/rss_fetcher.py` | RSS 피드 수집 |
| `app/services/content_fetcher.py` | 기사 본문 추출 |

수집된 기사 → `SourceItemCreate` → `orchestrator.full_pipeline()` (수동 /ingest 와 동일 진입점).

### 9.2 서버 고유 AI 기능 (작업 브랜치에 없음)

| 기능 | Step | 관련 파일 |
|------|------|----------|
| 5-Criteria 품질 필터 | Step 4.5 | `quality_scorer.py` |
| Reviewer regenerate 루프 | Step 5.5 | orchestrator.py 내장 |
| community_risk 분류 | Step 6 이후 | `classifier.py` |
| business_classifier | Step 6 이후 | `business_classifier.py` |
| prediction_service | Step 6 이후 | `prediction_service.py` |
| Grok 트렌드 | 독립 | `get_trending_topics()` |

### 9.3 문서 참조

- AI 운영 전체상 : `docs/AI_OPERATING_LAYER.md`
- 계정 정체성 : `docs/ACCOUNT_CONSTITUTION.md`
- 역할 프롬프트 : `docs/AI_ROLE_PROMPTS.md`
