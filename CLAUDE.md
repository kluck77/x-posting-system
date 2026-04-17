# CLAUDE.md — 운영/배포 규칙

새 Claude 세션이 이 repo 를 맡게 되면 **반드시 먼저 이 문서를 읽고** 운영
규칙을 지킬 것. 사용자는 휴대폰에서 터미널 명령만 복붙해 실행하는 방식으로
일한다. 명령어는 한 줄로 합쳐서 주는 게 원칙.

## 배포 표준 (단 하나의 공식 명령)

서버(`/root/x-posting-system`)에 코드 배포할 때는 **항상** 다음을 사용한다:

```bash
bash /root/x-posting-system/scripts/deploy.sh                 # 기본 브랜치
bash /root/x-posting-system/scripts/deploy.sh main            # main 배포
bash /root/x-posting-system/scripts/deploy.sh <브랜치명>      # 임의 브랜치
```

또는 서버에 alias `deploy-x` 가 박혀있으면:

```bash
deploy-x
deploy-x main
```

이 스크립트가 자동으로 하는 것:
1. `[0/6]` `xdashboard.service` 부활 감지 → 즉시 `disable --now`
2. `[1/6]` systemd 관리 밖 수동 `python run.py` 프로세스 전부 kill (SIGTERM → SIGKILL)
3. `[2/6]` `git pull origin <브랜치>`
4. `[3/6]` `systemctl restart x-posting-bot`
5. `[4/6]` 5초 후 서비스 상태 확인
6. `[5/6]` 30초 동안 `Conflict` 에러 감시
7. `[6/6]` 판정: Conflict 카운트 0 이면 `✅ 배포 성공`, 아니면 `🚨 + exit 1`

## 절대 하지 말 것

- 서버에서 직접 `python run.py` 수동 실행 금지. 무조건 systemd 를 통해서만.
  (수동 실행은 systemd 봇과 동시 polling 해서 Telegram `Conflict: terminated
  by other getUpdates request` 에러를 유발한다.)
- `xdashboard.service` 를 `enable` 하지 말 것. 이 유닛은 같은 `run.py` 를
  중복 실행시키는 레거시 유닛. 살리면 Conflict 즉시 터진다.
- `systemctl restart x-posting-bot` 만 단독 실행하지 말 것. 가능한 한
  `deploy.sh` 전체 흐름을 타라 (프로세스 정리 + git pull + Conflict 감시).

## Conflict 발생 시 진단 순서

`deploy.sh` 가 `🚨 Conflict 발생` 으로 끝나면:

1. 이 서버 내부는 이미 정리됨 (스크립트 `[1/6]` 에서 수행).
2. 즉 **외부 머신**(로컬 노트북, 다른 서버, 혹은 과거 배포된 VM)에서
   같은 봇 토큰으로 polling 중이라는 뜻.
3. 해결: 텔레그램 `@BotFather` 에서 `/revoke` → 새 토큰 발급 →
   `/root/x-posting-system/.env` 의 `TELEGRAM_BOT_TOKEN` 갱신 →
   `deploy-x` 재실행.

## 아키텍처 요점 (라우터 v1)

- 5 AI 역할 분리: Perplexity(factcheck) / Gemini(slots) / OpenAI(finalize)
  / Grok(X sense 평가) / Claude(편집 + 리뷰).
- 기사 라우터 (`app/services/content_pack.py`):
  - `route_article_mode(card)` → `EXPLAIN` / `JUDGMENT` / `VERIFY`
  - `certainty_level` 기준: `확정→EXPLAIN`, `상충→JUDGMENT`,
    `미확인/기본→VERIFY` (보수).
  - mode 별로 Gemini 슬롯 지시 + OpenAI finalize 지시가 분기됨.
  - VERIFY 모드는 **장기 해석 / 의도 추정 / "본심" / "노림수" / 정치적
    계산 / 체제 양보 / 질서 재편 등 확정 어휘 전면 금지**.
- 텔레그램 UI 에 mode 라벨 표시 (`telegram_bot.py:~1720`): 📊 EXPLAIN /
  ⚖️ JUDGMENT / 🔎 VERIFY.
- 최종 마감 타임아웃: **180초** (gate 재생성 1회 + 3 AI 체인 여유).
  `telegram_bot.py:1680` 참조.

## 수정 원칙

- 최소 수정. broad refactor 금지. 모델 역할 재배치 금지.
- 승인형 흐름(슬롯 선택 → 마감) 유지. top5_briefing / DB / 공급자 스키마
  건드리지 말 것.
- 카드용 문장(압축 UI) 과 게시용 문장(본문 AI 출력) 은 완전 분리 유지.
- 테스트: `pytest tests/test_content_pack.py` 로 전체 통과 확인 후 커밋.
