# HANDOFF.md — 새 Claude 세션이 repo 를 맡으면 **먼저 이 파일부터** 읽는다

> 이 문서 목적: 다음 세션이 브랜치 / 서버 상태 / 진행 중인 작업 / 운영 원칙을 **1분 안에 파악**하게 함. 상황이 바뀔 때마다 갱신한다.

---

## 1. 지금의 trunk (활성 작업선)

**활성 브랜치:** `post-linter-labels`
**서버 배포 브랜치:** `strategy-os-phase-c-advisory`
**마지막 서버 배포 시점:** Phase C (2026-04-19)
**다음 배포 예정 브랜치:** `post-linter-labels` (UX + 한국어 Pack 규칙 + Post Linter 전부 포함)

운영선(운영자가 참조하는 실제 최신)은 `origin/claude/review-handoff-document-UoyuK`
이지만, 거기로는 **직접 커밋하지 않는다.** 모든 작업은 위 활성 브랜치에서 분기.

---

## 2. Strategy OS 브랜치 스택 (Phase A → B+)

```
origin/claude/review-handoff-document-UoyuK  9803612   # 실제 운영 trunk
  └─ strategy-os-phase-a-v2                 81d6788   # A: 읽기 전용 탭
       └─ strategy-os-phase-b-edit          5605e52   # A+B: JSON 인라인 편집
            └─ strategy-os-phase-c-advisory 2990a86   # A+B+C: orchestrator advisory inject
                 └─ strategy-os-phase-bplus-ux        # A+B+C + UX 개편 + grok-handoff 한국어
                      └─ post-linter-labels           # 위 전부 + Post Linter(라벨러) ← 현재
```

**원칙:**
- 브랜치 **스택 유지** — revert 지점으로 남겨둠. 삭제하지 말 것.
- 새 작업은 최상단(= 활성 브랜치) 위에서 분기.
- main 머지는 `strategy-os-phase-bplus-ux` 위에서 며칠 관찰 후 단일 squash merge 예정.
- main 머지 완료되면 A/B/C/B+ 브랜치 일괄 삭제 + 이 파일의 "trunk" 재정의.

**Deprecated:**
- `claude/live-validation-checklist-weAP0` (8ff160c) — 잘못된 base 위에서 만들어진 사산아.
  참조/머지/자동화 대상 아님. 손대지 말 것.

---

## 3. Strategy OS 가 뭔지 30초

`runtime_x/strategy/strategy_os.json` 한 파일에 콘텐츠 차별화 자산을 고정한다.

필드 (스키마는 `app/services/strategy_os.py::default_strategy_os()` 가 단일 소스):
- `positioning` : `{one_liner, do_not_do[], lenses[]}`
- `content_pillars[]`, `series[]`, `hook_library[]`, `rt_trigger_rules[]`,
  `banned_style[]`, `good_examples[]`, `bad_examples[]`, `weekly_review_checklist[]`

노출 경로:
- 대시보드 **Strategy OS 탭** (`static/dashboard.html`) — 읽기/폼 편집/JSON 고급 편집
- API `GET /control/strategy-os` — 항상 default 병합해서 반환 (실패해도 200)
- API `POST /control/strategy-os` — 검증 + 백업 1세대 + atomic save
- orchestrator `_build_strategy_os_advisory()` 가 DraftWriter/Reviewer 프롬프트에
  advisory 블록으로 주입 (fail-open, Layer 1 무영향)

---

## 4. 건드리지 말 것 (이번 Strategy OS 작업 전체의 scope)

- `app/providers/*` — provider 인터페이스 / 프롬프트 템플릿 / SDK 연결. **0 변경.**
- `app/telegram_bot.py`, `app/services/telegram_service.py` — 승인 플로우.
- DB 스키마 (`app/models/content.py`).
- Pack Chain, pulse, scoring/routing 로직.
- `app/api/admin.py` — static mount / `/` 라우트 (이미 기존 버전에 설정돼 있음).

바뀐 파일은 아래뿐:
- `app/services/strategy_os.py` (신규)
- `app/services/post_linter.py` (신규 — 라벨러, 재작성 0)
- `app/api/control_room.py` (import 1 + endpoint 2 추가)
- `app/orchestrator.py` (advisory helper 1 + 주입 2지점 + post_linter 훅 1)
- `app/services/grok_handoff.py` (출력 규칙 한국어로, 2줄)
- `static/dashboard.html` (탭 1개 + 버튼 1개 추가, UX 개편)
- `tests/test_strategy_os.py`, `tests/test_strategy_os_advisory.py`, `tests/test_post_linter.py` (신규)

---

## 5. 실패 정책 (Layer 2 = fail-open)

Strategy OS 경로의 어떤 실패도 파이프라인을 막지 않는다.

- 파일 손상 / 누락 → `load_strategy_os()` 가 default 반환
- 검증 실패 → `POST /control/strategy-os` 400, 기존 파일 무변화
- orchestrator advisory 실패 → `[STRATEGY_OS_ADVISORY_SKIP] ...` 로그 1줄 + 빈 블록
- post_linter 실패 → `[post_linter] 실패 (무시): ...` 로그 + `labels={}` 로 sidecar 저장 (기존 sidecar 필드 보존)

**Kill switch (코드 revert 불필요):**
```bash
echo '{}' > /root/x-posting-system/runtime_x/strategy/strategy_os.json
systemctl restart x-posting-bot
```

---

## 6. 운영 관찰 체크리스트 (며칠간)

Phase C 배포 후 운영자가 관찰 중인 포인트:
1. advisory 가 실제 draft 품질/차별화에 도움 되는지
2. `hook_library` 반영 후 첫 두 줄이 강해졌는지
3. `banned_style` 이 AI/기자체를 줄였는지
4. 글이 획일화되는 부작용은 없는지
5. RT/팔로우 유도 문장이 실제로 살아났는지

로그 grep 포인트:
```
[StrategyOS] DraftWriter 주입: NNN자   # DEBUG, 정상 주입
[StrategyOS] Reviewer 주입: NNN자      # DEBUG, 정상 주입
[STRATEGY_OS_ADVISORY_SKIP] ...        # WARNING, 스킵됨 (이유 뒤에 붙음)
```

---

## 7. 배포 (CLAUDE.md 원칙 그대로)

```bash
deploy-x post-linter-labels                # UX + 한국어 Pack + Post Linter 전부 (예정)
deploy-x strategy-os-phase-bplus-ux        # Post Linter 제외, UX + 한국어까지
deploy-x strategy-os-phase-c-advisory      # Phase C 로 롤백 (현재 배포선)
deploy-x strategy-os-phase-b-edit          # advisory 끔, 편집 UI 까지만
deploy-x strategy-os-phase-a-v2            # 읽기 전용까지만
```

`deploy.sh` 가 자동으로:
- 수동 `python run.py` 프로세스 정리
- `git pull origin <브랜치>`
- `systemctl restart x-posting-bot`
- 30초 Conflict 감시 → 통과 시 ✅

---

## 8. 새 세션 체크리스트

repo clone/pull 직후 다음 순서로 하면 끝:

```bash
cat HANDOFF.md                            # 이 파일
git log --oneline -10                      # 최근 커밋
git branch -a | grep -E 'strategy-os|post-linter'   # 스택 확인
pytest tests/test_strategy_os*.py tests/test_post_linter.py -v
# → strategy_os 38 + post_linter 30 = 68/68 PASS
```

알려진 pre-existing 실패 (Strategy OS 와 무관, 별도 task):
- `tests/test_config.py::TestSettings::test_default_settings`
- `tests/test_config.py::TestSettings::test_x_credentials`
- `tests/test_config.py::TestSettings::test_x_credentials_incomplete`
- `tests/test_e2e.py::TestEndToEnd::test_approve_and_publish_mock`

이 4개는 Strategy OS 머지 blocker 로 보지 않음.

---

## 9. 이 파일 갱신 규칙

- 활성 브랜치 바뀔 때 → 섹션 1 갱신
- 서버 배포 바뀔 때 → 섹션 1 갱신
- 새 Phase 진입할 때 → 섹션 2 / 섹션 4 갱신
- main 머지 완료 → 섹션 1 "trunk = main", 섹션 2 스택 접기
- 갱신은 작업 커밋과 같은 커밋에 포함시킬 것 (따로 커밋하지 말 것)
