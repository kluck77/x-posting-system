# SERVER STRUCTURE

서버 본체의 물리적 구조와 배포 규칙을 기록한다.
**이 문서가 없으면 매 세션마다 서버 상태를 처음부터 조사해야 한다.**

최종 갱신 : 2026-04-09 21:00 KST (Phase G 서버 반영 완료)

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
| orchestrator.py | 707줄 (고급 기능 + Step 1.5/1.5b/1.6 삽입) | 349줄 (단순 기준선) |

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

### Phase F 구현 완료, 서버 반영 대기

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/main.py` | Phase F: `git show` 전체 교체 | ⏳ 서버 반영 대기 |

- `_top5_scheduler_loop()` : 매일 05:00 KST `run_top5_briefing()` 자동 실행
- `asyncio.create_task()` 로 기존 이벤트루프에 합류 (외부 패키지 불필요)
- 브랜치 main.py 와 서버 main.py 구조 동일 → 전체 교체 안전
- 롤백: `cp /tmp/main.py.bak.phase_f app/main.py && systemctl restart xdashboard`

### Phase H 구현 완료, 서버 반영 대기

| 파일 | 반영 방식 | 상태 |
|---|---|---|
| `app/orchestrator.py` Step 1.7 | Phase H: 수술식 삽입 (Step 1.6 후, Step 2 전) | ⏳ 서버 반영 대기 |
| `app/orchestrator.py` full_pipeline | Phase H: 2줄 조건문 삽입 | ⏳ 서버 반영 대기 |
| `app/orchestrator.py` _handle_regenerate | Phase H: 2줄 조건문 삽입 | ⏳ 서버 반영 대기 |

- Step 1.7: BREAKING_NOW/CANDIDATE + 금융/투자/크립토/주식 → 영어 초안 + 승인 카드 우회
- full_pipeline / _handle_regenerate: `_skip_approval_card` 플래그로 `send_for_approval()` 조건부 생략
- HOLD/REJECT/비대상 도메인 → 기존 파이프라인 100% 유지
- fail-open: 판정 실패 시 기존 영어 파이프라인 그대로 실행

### 브랜치에만 있는 파일 (서버에 없음)

- `app/services/candidate_filter.py`

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
Step 1.6: BREAKING_NOW 텔레그램 핸드오프         ← 줄 193~209 ✅ Phase C+E
          └ record_breaking_sent() (Top5 제외)   ← 줄 200~208 ✅ Phase E
Step 1.7: 한국어 전용 라인 분기 (early return)    ← ⏳ Phase H (브랜치 완료, 서버 대기)
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
