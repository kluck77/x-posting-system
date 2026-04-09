# TELEGRAM DEDUP DATA MODEL SPEC

이 문서는 텔레그램 발행 경로의 **중복 발행 방지(dedup)** 기준선이다.
`BREAKING_NOW` (상시 속보) 와 `05:00 Top5` (일일 정기) 두 경로가 **같은 dedup 모델** 을 공유한다.
채팅방 메모리 / 운영자 기억 / 로컬 실험 스크립트는 기준이 아니다. 이 문서가 기준이다.

---

## 1. 목적

- `BREAKING_NOW` 와 `05:00 Top5` 가 **같은 이슈를 중복 발행하지 않도록** 하는 데이터 모델을 단일 문서로 고정한다.
- 두 경로는 트리거 / 컷라인 / 카피 톤은 다르지만 **"같은 이슈냐"** 의 판정은 하나의 규칙으로만 한다.
- dedup 단위 / 정규화 규칙 / 윈도우 / 후속 보도 판정을 흐리지 않고 운영 가능한 형태로 박제한다.
- 향후 dedup 관련 패치/회귀 발생 시 본 문서의 섹션 번호로 인용 가능하게 한다.

## 2. 적용 범위

**적용 대상**
- `BREAKING_NOW` : 속보 트리거로 발생하는 즉시 발행 카드
- `05:00 Top5` : 매일 KST 05:00 시점 상위 5개 이슈 정기 카드
- 텔레그램 승인 카드 / 보류 카드 / 최종 발행 카드 전 단계

**미적용 대상**
- Reviewer / DraftWriter 단의 텍스트 유사도 산출 자체 (별개 레이어)
- 대시보드 읽기 전용 뷰
- 운영자 수동 발행 (수동 발행은 본 spec 을 참조는 하되 강제 대상 아님)
- 한국어 원문 계정 방향성 (`docs/ACCOUNT_CONSTITUTION.md` 가 기준)

## 3. 핵심 원칙

1. **두 경로 공용 단일 모델.** `BREAKING_NOW` 와 `05:00 Top5` 가 dedup 키 / 윈도우 / 판정 규칙을 공유한다. 경로별 분기 금지.
2. **URL 단위가 아니라 이슈 단위.** 같은 사건의 다른 기사는 같은 `issue_key` 로 수렴한다.
3. **제목 정규화 후 비교.** 원제목 그대로의 문자열 비교 금지. 반드시 `title_normalized` 를 사용한다.
4. **dedup 은 게이트, 점수는 별도.** 점수가 높아도 이미 발행된 이슈면 차단. 점수 레이어와 dedup 레이어를 섞지 않는다.
5. **시간 윈도우는 경로별 다름.** 모델은 하나지만 윈도우 길이는 §8 에서 경로별 명시한다.
6. **후속 보도(follow-up)는 별개 판정.** 재발행이 아니라 **후속** 임이 명시되면 허용. 기준은 §9.
7. **모호하면 차단.** dedup 판정이 모호하면 기본값은 **차단(hold)**, 발행 아님.

## 4. dedup 단위 정의

dedup 의 최소 단위는 **이슈(issue)** 이다. 기사가 아니다.

- **이슈** : 동일 사건 / 동일 발표 / 동일 자산 뉴스 코어
- **기사** : 이슈를 보도하는 개별 URL
- **카드** : 텔레그램에 실제로 나가는 승인/발행 단위

관계 :
- `1 issue : N articles : M cards`
- dedup 은 **issue 레벨** 에서 판정
- 같은 issue 를 서로 다른 경로(`BREAKING_NOW`, `05:00 Top5`)에서 발행하려 해도 §8 윈도우 내면 차단
- 한 issue 가 여러 자산(예: BTC + ETH 동시 영향) 에 걸치는 경우는 §7.4 참조

## 5. 기본 데이터 필드

dedup 판정에 사용하는 최소 필드 세트. 누락 금지.

| 필드 | 타입 | 설명 | 비고 |
|---|---|---|---|
| `issue_key` | string | §7 규칙으로 생성한 이슈 식별자 | **dedup 의 1차 키** |
| `title_raw` | string | 기사 원제목 | 정규화 전 원본 보존용 |
| `title_normalized` | string | §6 규칙 적용 결과 | 비교 대상은 항상 이것 |
| `source_url` | string | 원 기사 URL | 동일 이슈의 여러 기사 허용 |
| `source_domain` | string | URL 의 호스트 | 출처 다양성 체크용 |
| `published_at_utc` | datetime | 기사 발행 시각 (UTC) | 윈도우 계산 기준 |
| `ingested_at_utc` | datetime | 파이프라인 수신 시각 | 운영 모니터링용 |
| `channel` | enum | `BREAKING_NOW` / `TOP5_0500` | 발행 경로 구분 |
| `card_status` | enum | §10 의 상태값 | dedup 상태 기계 |
| `issue_first_seen_utc` | datetime | 이 `issue_key` 가 처음 관측된 UTC 시각 | 윈도우 시작점 |
| `issue_last_published_utc` | datetime nullable | 이 `issue_key` 가 마지막으로 발행된 UTC 시각 | 재발행 차단 기준 |
| `followup_of` | string nullable | 후속 보도인 경우 원 `issue_key` 참조 | §9 |

## 6. title_normalized 규칙

정규화는 **결정적(deterministic)** 해야 한다. 같은 입력 → 항상 같은 출력.

순서 고정 :

1. **Unicode NFKC** 정규화
2. **소문자화** (ASCII 범위 한정, 한글은 변화 없음)
3. 선행/후행 공백 strip, 연속 공백 1개로 압축
4. **구두점 제거 단계** : `「」『』"'“”‘’.,!?…·~\-—()[]{}<>` 및 전각 대응 기호 제거
5. **흔한 브래킷 태그 제거** : `[속보]`, `[단독]`, `[종합]`, `[1보]`, `[2보]`, `[영상]`, `[사진]`, `(종합)` 등 선행 태그
6. **언론사 꼬리표 제거** : `- 연합뉴스`, `| 한국경제`, `- 블룸버그` 같은 꼬리 패턴
7. **숫자 정규화** : 전각 숫자 → 반각 숫자, `1,200` → `1200` (쉼표 기반 천 단위 구분자만)
8. **화폐 기호 정규화** : `＄` → `$`, `￦` → `원` (기호는 유지하되 표기 고정)
9. **공백 기준 토큰 재결합** : 공백 1개로 join

주의 :
- 한글 조사/어미는 **제거하지 않는다**. 의미 손상 위험 > dedup 이점.
- 영문 stemming / lemmatization 은 **하지 않는다**. 결정성과 테스트 비용 고려.
- 이모지는 **제거**. 정규화 단계 4 직후에 일괄 제거.
- 본 규칙의 변경은 반드시 `RUNNER_RULES` §10 의 "운영 원칙이 바뀔 때만 갱신" 기준으로 commit 박제.

## 7. issue_key 생성 원칙

`issue_key` 는 **사람이 읽을 수 있는 slug + 결정적 해시** 의 조합이다.

### 7.1 형식

```
<coarse_bucket>:<entity_slug>:<topic_slug>:<hash8>
```

- `coarse_bucket` : `crypto` / `stock` / `macro` / `policy` / `corp` / `other` 중 하나
- `entity_slug` : 주체가 되는 자산/기업/기관의 고정 slug (예: `btc`, `nvda`, `fomc`, `kospi`)
- `topic_slug` : 이슈의 동작어 slug (예: `etf-approval`, `rate-decision`, `earnings-beat`, `hack`)
- `hash8` : `title_normalized` + `coarse_bucket` + `entity_slug` + `topic_slug` 의 SHA-256 앞 8자

### 7.2 결정 순서

1. `title_normalized` 에서 엔티티 추출 → `entity_slug`
2. 동작어 추출 → `topic_slug`
3. 매핑 테이블로 `coarse_bucket` 결정
4. 위 3개 + `title_normalized` 로 `hash8` 계산
5. 4개 조합으로 `issue_key` 확정

### 7.3 엔티티 미식별 fallback

- 엔티티를 식별 못하면 `entity_slug = unknown`, `coarse_bucket = other`
- 이 경우 `topic_slug` 는 정규화 제목의 앞 3 토큰을 `-` 로 이은 값
- fallback 이슈는 §10 의 `hold` 상태로 진입. 자동 발행 금지. 운영자 승인 필요.

### 7.4 다중 엔티티 이슈

- 한 뉴스가 `BTC` + `ETH` 에 동시에 해당하면 **주요 엔티티 1개만** `entity_slug` 로 설정
- 주요 엔티티 판정 : 정규화 제목에서 먼저 등장한 엔티티
- 부수 엔티티는 `secondary_entities` 필드(선택) 에 기록하되 dedup 키에는 포함하지 않음
- 이 규칙은 **dedup 폭주 방지** 가 목적. 세밀한 분리가 필요하면 §12 참조.

### 7.5 금지

- `issue_key` 에 시각 정보 포함 금지 (윈도우는 §8 에서 따로 계산)
- `issue_key` 에 `channel` 포함 금지 (경로 간 공유가 핵심)
- `issue_key` 에 점수 정보 포함 금지

## 8. dedup 윈도우 규칙

모델은 하나, 윈도우는 경로별 다름.

| 경로 | 기본 윈도우 | 재발행 차단 대상 | 비고 |
|---|---|---|---|
| `BREAKING_NOW` | **6시간** | 동일 `issue_key` 가 직전 6h 내 이미 발행된 경우 | 속보 성격 고려, 과발행 방지 |
| `TOP5_0500` | **24시간** | 직전 24h 내 `BREAKING_NOW` 또는 `TOP5_0500` 로 발행된 `issue_key` | 정기 슬롯이므로 일 단위 강 |
| 교차 차단 | **양방향** | `BREAKING_NOW` 로 나간 이슈는 당일 `TOP5_0500` 에서 차단 (단, §9 후속 보도 예외) | 핵심 원칙 |

윈도우 기준 시각 :
- `BREAKING_NOW` : 발행 시도 시각 UTC
- `TOP5_0500` : 해당일 KST 04:30 의 UTC 환산 시각 (스냅샷)

경계값 :
- 윈도우는 **closed-open** : `[start, start + window)`
- `issue_last_published_utc + window > now` 이면 차단

## 9. 후속 보도 판정

후속 보도(follow-up)는 **재발행이 아니라 새 카드** 로 취급한다. 단, 조건 충족 시에만.

### 9.1 허용 조건 (AND)

1. 원 이슈의 `issue_last_published_utc` 로부터 **최소 2시간** 경과
2. 새 기사의 정규화 제목에 **다음 중 1개 이상 신호** 포함
   - 수치 업데이트 (가격/거래량/규모/확률 등 구체 숫자의 유의미한 변화)
   - 공식 발표 출처 추가 (기관/기업 공식 계정 / 공식 보도자료)
   - 시장 반응 섹션 명시 (예: "지수 급락", "거래정지")
3. 운영자 사전 승인 (텔레그램 승인 카드) **또는** 자동 허용 화이트리스트에 포함된 topic
4. 본 카드의 `followup_of` 필드에 원 `issue_key` 명시

### 9.2 차단 조건 (OR)

- 위 4개 AND 중 하나라도 미충족
- 새 기사가 원 이슈 제목의 **재표현(rewording)** 에 불과
- 원 이슈 발행 후 2시간 미만 경과
- fallback 이슈 (§7.3) 는 후속 보도 판정 자체 금지

### 9.3 표기

- 후속 카드는 텔레그램 카드 머리에 `[후속]` 태그 노출
- `followup_of` 가 비어있는 카드에 `[후속]` 태그 부착 금지

## 10. 저장/상태 규칙

dedup 상태 기계는 카드 단위로 관리한다.

### 10.1 card_status enum

| 값 | 의미 | 다음 전이 |
|---|---|---|
| `pending` | 파이프라인이 후보 카드를 만든 직후. dedup 미판정 | → `approved_candidate` / `blocked_dedup` / `hold` |
| `approved_candidate` | dedup 통과, 텔레그램 승인 카드 대기 | → `published` / `rejected` / `expired` |
| `blocked_dedup` | §8 윈도우 또는 §7 규칙에 의해 차단됨 | 종결 (재진입 금지) |
| `hold` | fallback / 모호 판정 → 운영자 수동 검토 필요 | → `approved_candidate` / `rejected` |
| `published` | 실제 텔레그램 발행 완료 | `issue_last_published_utc` 갱신 |
| `rejected` | 운영자 거절 또는 자동 정책 거절 | 종결 |
| `expired` | 승인 대기 중 윈도우 경과 | 종결 |

### 10.2 기록 의무

- `blocked_dedup` 은 반드시 **차단 사유** 를 함께 기록 : `blocked_reason` (`window`, `duplicate_issue`, `fallback_hold`, `policy`)
- `hold` → `approved_candidate` 전이는 **운영자 ID + 시각** 기록
- `issue_last_published_utc` 는 오직 `published` 전이 시점에만 갱신. 다른 경로로 수정 금지.

### 10.3 보존

- `card_status` 이력은 **90일** 보존
- `issue_key` 색인은 **180일** 보존
- 보존 초과 데이터는 anonymize 후 집계용으로만 유지 (원문/제목 삭제)

## 11. 운영 예시

### 11.1 같은 이슈 → 차단

- 09:10 UTC `BREAKING_NOW` 로 `crypto:btc:etf-approval:ab12cd34` 발행
- 12:05 UTC 동일 issue_key 후보 재진입
- 윈도우 6h 내 → `card_status = blocked_dedup`, `blocked_reason = window`

### 11.2 교차 차단

- 09:10 UTC `BREAKING_NOW` 로 `crypto:eth:hack:77ee99aa` 발행
- 같은 날 20:00 UTC 스냅샷에서 `TOP5_0500` 후보로 동일 issue_key 진입
- 교차 차단 발동 → `blocked_dedup`, `blocked_reason = duplicate_issue`
- 단, §9 후속 보도 조건 충족 시 새 카드로 발행 가능

### 11.3 후속 보도 허용

- 06:00 UTC 원 이슈 발행
- 10:30 UTC 공식 발표 + 가격 12% 급등 수치 추가
- 운영자 승인 카드에서 `[후속]` 으로 명시 → `followup_of` 원 issue_key 기록 → 발행 허용

### 11.4 fallback 이슈

- 엔티티 미식별 → `issue_key = other:unknown:asian-market-tension:5f5f5f5f`
- 자동 `card_status = hold`
- 운영자 검토 후 `approved_candidate` 또는 `rejected` 로 전이

## 12. 운영 메모

- 본 spec 은 데이터 모델 규격이다. **구현 코드가 아니다.** 코드 반영은 별 P0 로 분리.
- `RUNNER_RULES` §5 (영구 보호 영역) 와 충돌하는 실구현 변경은 반드시 사전 승인.
- 본 spec 의 **dedup 키/윈도우/상태 enum** 변경은 HANDOFF_LOG 박제 필수. 텍스트 규칙(§6, §7 slug 매핑 등) 미세 조정은 본 문서 자체 갱신으로 충분.
- `docs/ACCOUNT_CONSTITUTION.md` 와 본 문서는 **레이어가 다르다.** 전자는 "무엇을 쓰느냐", 본 문서는 "같은 이슈를 두 번 쓰지 않느냐".
- 본 문서는 서버 적용 대상이 아니다. 서버는 구현 코드를 통해서만 영향을 받는다.
- 다중 엔티티 이슈 분리가 필요해지면 별 P0 로 `issue_key` v2 (compound entity) 검토.
- 후속 보도 화이트리스트(§9.1.3)는 본 문서에 나열하지 않는다. 운영자 설정 영역.
