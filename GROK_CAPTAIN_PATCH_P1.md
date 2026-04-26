# Grok Captain 프롬프트 패치 — Phase 1 (BLOCK_RECOMMENDED 감지 + reject 강제)

> 이 파일은 **운영자용 수동 패치 노트**. Grok Custom Agent 슬롯 1번("Grok")의
> 프롬프트에 아래 블록을 직접 붙여넣어야 적용된다. 시스템 코드에서 자동
> 주입되지 않는다.

## 적용 시점

`handoff-quality-guard` 브랜치 배포 (또는 이 커밋 병합) 직후 즉시.
시스템은 `## ⚠️ 재료 품질 경고` 블록을 핸드오프 최상단에 삽입하기 시작함.
Grok Captain 프롬프트가 이 블록을 해석하지 못하면 **경고가 무시되고
Grok 이 평소처럼 편집을 시도**한다 — 그게 바로 우리가 피하려는 상태.

## 삽입 위치

Grok Captain 프롬프트의 `# HARD QA` 섹션 **바로 위**에 아래 블록을 삽입.

## 삽입할 블록 (그대로 복사)

```text
# BLOCK_RECOMMENDED 처리 (상류 재료 품질 가드 — 최우선 판정)

핸드오프 최상단에 "## ⚠️ 재료 품질 경고" 블록이 존재하면 다음 순서로 처리:

STEP 1. 블록 내 "**BLOCK_RECOMMENDED**" 문자열 존재 확인

STEP 2. BLOCK_RECOMMENDED 존재 시 (다른 모든 로직에 우선):
  - decision 을 강제로 "reject" 로 설정
  - HARD QA / SOFT QA / 2-PASS CRITIQUE 모두 스킵 (편집 시도하지 않음)
  - <POST> 블록 출력 생략
  - <OPERATOR_NOTES> 필수 3줄:
    • 판단 근거: "상류 재료 품질 경고 HIGH 플래그 다수 감지"
    • 잔존 리스크: "편집으로 해결 불가, 파이프라인 재실행 필요"
    • 다음 액션: "이 draft 폐기 후 Gemini/Perplexity 재호출 권장"
  - <DECISION> 의 failed_items 필드에 경고 블록에서 감지된 flag_id
    (angle_heuristic, facts_empty 등) 를 쉼표 구분으로 복사

STEP 3. 경고 블록은 있지만 BLOCK_RECOMMENDED 없음 (MEDIUM 플래그만):
  - 편집은 정상 진행
  - <OPERATOR_NOTES> 잔존 리스크 1줄에 경고 플래그 내용 반영
  - decision 은 HARD/SOFT QA 결과 기준 정상 판정

STEP 4. 경고 블록 자체가 없으면 기존 편집 플로우 그대로 진행

이 로직은 HARD QA 보다 우선한다. BLOCK_RECOMMENDED 감지 시 다른
모든 편집 로직을 건너뛰고 reject 출력.
```

## 시스템이 생성하는 flag_id 목록 (failed_items 매핑용)

| flag_id | severity | 의미 |
|---|---|---|
| `angle_heuristic` | HIGH | Gemini angle_pack 실패, heuristic fallback 사용 |
| `facts_empty` | HIGH | confirmed_facts 0~1 건, 서사 원료 부재 |
| `english_residue` | MEDIUM | core_tension / uncertainty 필드 영어 잔존 |
| `concept_translation_misuse` | MEDIUM | concept_translation 에 기사 요약 박힘 |

BLOCK_RECOMMENDED 는 HIGH 가 **2 개 이상** 감지될 때만 트리거.
HIGH 1 개 + MEDIUM 만이면 MEDIUM 경로 (STEP 3) 로 진행.

## 4,000자 한도 대응

이번 패치는 약 550자. Grok Captain 프롬프트 현재 길이가 4,000자에 근접하면
아래 중 하나를 압축해서 공간 확보:

1. regulatory_status stage 세부 목록 (한국/해외 5단계씩) → 1줄 요약
2. banned_style 중복 항목 제거
3. SOFT QA 체크리스트 중복 설명 문구 정리

**압축 내역은 이 패치 적용 커밋 메시지에 반드시 명시**.

## 롤백

이 블록만 프롬프트에서 제거하면 즉시 이전 동작 복귀. 시스템 쪽 handoff
는 여전히 경고 블록을 생성하지만, Grok 이 무시하므로 사실상 no-op.
