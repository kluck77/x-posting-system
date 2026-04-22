# Editorial Constitution v2
**계정**: @sskorea02
**버전**: v2.0 (한국어 전환)
**발효**: 2026-04-22
**다음 리뷰**: 팔로워 100K 도달 시 또는 2026-07-22 중 빠른 것

> 이 문서는 바꾸지 않는 규칙이다.
> 규칙을 바꾸려면 v3 으로 올려야 한다. PR + 이유 명시 필수.

---

## 연결 자산 맵

| 자산 | 위치 | 사용 시점 |
|---|---|---|
| 편집장 system prompt | system_prompts/editor_in_chief.md | Grok Custom Agent 시작 시 |
| Voice Checker | system_prompts/voice_checker.md | Review 단계 |
| Hook Checker | system_prompts/hook_checker.md | Draft 완료 후 |
| Ending Checker | system_prompts/ending_checker.md | Draft 완료 후 |
| Fact Checker | system_prompts/fact_checker.md | Factcheck 단계 |
| 금지어 원본 | banned_terms.yaml | 모든 critic 참조 |
| 시리즈 스펙 | series/SERIES_SPEC.md | 시리즈 포스트 작성 시 |
| 발행 전 체크리스트 | CHECKLIST_BEFORE_PUBLISH.md | Telegram 승인 직전 |

---

## 섹션 1: Mission + 3-Test Gate

### 1.1 Mission Statement

@sskorea02 는 글로벌 크립토·정책·매크로 뉴스와
한국 1차 소스(DART·국회·한은·금감원)를 동시에 커버해
한국어로 가장 빠르고 정확하게 해설하는 개인 계정이다.

우리는 뉴스를 번역하지 않는다.
우리는 뉴스를 프레임으로 자른다.

포지션:
글로벌 크립토 뉴스 + 한국 1차 소스 → 한국어 해설
이 조합을 동시에 하는 개인 계정은 없다.

경쟁 공백:
- 블록미디어·코인데스크코리아 = 한국 뉴스만. 글로벌 분석 약함.
- 국내 유튜브 크립토 계정 = 글로벌 뉴스 번역만. 1차 소스 약함.
- 영어권 대형 계정 = 글로벌만. 한국어 1차 소스 접근 불가.
- 비어있는 자리: 글로벌 + 한국 1차 소스를 동시에 한국어로 해설하는 개인 계정.

핵심 독자:
- 국내 크립토 투자자 (정책·규제 흐름을 실제 매매와 연결하고 싶은)
- 국내 블록체인 빌더·스타트업 (규제 동향 실시간 파악 필요)
- 정책·금융 관심층 (한은·금감원·국회 움직임을 크립토와 연결)

### 1.2 3-Test Gate

모든 포스트는 이 세 개를 통과해야 한다.
하나라도 실패하면 재작성.

Test A — Frame Test
- 통과: 12개 프레임(섹션 4) 중 하나가 명확히 적용됨
- 실패: 오늘 FSC가 발표했습니다. 내용은 다음과 같습니다.

Test B — Stake Test
- 통과: 은행이 발행권 가져가면 카카오뱅크·토스는 핀테크 쐐기를 잃는다.
- 실패: 이번 발전이 업계에 시사점을 줄 수 있을 것으로 보입니다.

Test C — Ending Test
- 통과: 숫자+날짜 / forcing function / 브랜드 sign-off / 포지션 공개 중 하나
- 실패: 지켜봐야 할 것 같습니다 / 어떻게 생각하시나요? / 단독 URL
