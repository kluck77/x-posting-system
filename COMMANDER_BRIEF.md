# Commander Brief — X Content Operating System

이 문서는 앞으로 Claude Code가 읽고 작업 기준으로 삼아야 하는 핵심 운영 메모다.

## 1. 프로젝트의 진짜 목표
이 저장소는 단순한 자동 포스팅 툴이 아니다.
목표는 다음과 같다.

- 사용자가 API 키만 넣으면 바로 돌릴 수 있어야 한다.
- 사용자가 뉴스 링크, X 링크, 스크린샷, 짧은 메모, 관찰 메모를 넣으면
  시스템이 글 초안과 댓글 초안, 인용RT 초안까지 만들어줘야 한다.
- 사용자는 최종 편집장처럼 검토하고 승인만 한다.
- 절대 위험한 자동화로 가면 안 된다.
- 장기적으로는 고품질 텍스트 운영 시스템으로 성장해야 한다.

핵심 정의:

> "승인형 반수동 X 콘텐츠 운영 시스템"

즉, 이 시스템은 다음을 돕는 텍스트 중심 운영 본체다.
- 메인 포스트 작성
- 짧은 버전 작성
- 댓글 초안 작성
- 인용RT 초안 작성
- 스레드 후보 작성
- 리스크 경고
- topic memory
- voice consistency
- repetition guard
- weekly mix guidance

## 2. 절대 바뀌면 안 되는 것
다음은 고정 원칙이다.

- Telegram approval loop 유지
- 승인 없는 자동 포스팅 금지
- 자동 좋아요 / 자동 팔로우 / 자동 리플 금지
- 스팸성 성장 기능 금지
- propaganda tone 금지
- 팬덤 싸움형 계정 방향 금지
- 거대한 재설계 금지
- 초보자도 운영 가능한 구조 유지
- Layer 1이 Layer 2 때문에 죽으면 안 됨

## 3. 영구 제외 항목
이미지 생성 계열은 영구 제외다.
다시는 제안하지 말 것.

영구 제외:
- DALL-E integration
- Stable Diffusion integration
- automatic image generation
- image prompt generation
- thumbnail generator
- video generator
- any visual generation pipeline

이 프로젝트는 텍스트 운영 시스템이다.

## 4. 현재까지 확인된 상태
현재 확인된 핵심 상태:

- ContentRequest / ContentPack 구조 있음
- CriteriaSignals 구조 있음
- CriteriaSignals는 이제 DraftWriter + Reviewer 프롬프트에 실제 주입됨
- regenerate loop는 최소 안전장치와 함께 연결됨
- mock mode 유지됨

하지만 앞으로 중요한 것은 "구조를 더 크게 만드는 것"이 아니라
"운영 보조 기능을 얇게 붙이는 것"이다.

## 5. 앞으로의 우선순위
앞으로 작업 우선순위는 아래 순서를 유지한다.

### Week 1~2 성격의 핵심
- existing flow end-to-end 검증
- criteria signal wiring 안정화
- prompt quality 확인
- Layer 1 보호

### 다음 우선순위 (중요)
1. topic memory
2. voice guard
3. repetition guard + style warnings 연결
4. weekly content mix advisory
5. reply / quote-post opportunity suggestions
6. quality gate advisory

### 후순위
- 큰 analytics UI
- multi-account support
- complex dashboard
- visual generation

## 6. Layer 1 / Layer 2 규칙
이 프로젝트는 두 층으로 나뉘어야 한다.

### Layer 1 = 운영 코어
이건 무조건 안정적으로 돌아가야 한다.

포함:
- 입력 받기
- Draft generation
- Review
- Telegram approval
- X posting
- logs / dedup / alerts

### Layer 2 = 성장 보조 레이어
이건 advisory 성격이다.

포함:
- topic memory
- voice hints
- repetition warnings
- style warnings
- content mix guidance
- performance suggestions

중요:
- Layer 2 실패해도 Layer 1은 정상 작동해야 함
- Layer 2는 붙였다 뗄 수 있게 얇게 설계할 것

## 7. 콘텐츠 운영 철학
이 계정은 단순 뉴스 계정이 아니다.
하지만 아무 잡다한 일상 계정도 아니다.

정체성:
- 국제 독자에게 한국을 설명하는 영어 X 계정
- 사회 / 정책 / 경제 / 정치 / 일상을 설명형으로 다룸
- K-pop, 드라마, 문화는 entry point로만 사용
- credibility > virality

시스템이 도와야 하는 것:
- why this matters to international readers
- 설명형 문장 유지
- 너무 AI 같은 표현 줄이기
- 너무 random / too soft / too lifestyle-only / fandom-like drift 방지

## 8. Claude Code가 작업할 때 지켜야 할 태도
- 과하게 똑똑한 척하는 재설계 금지
- 이미 있는 backbone 존중
- 작은 패치로 큰 운영 가치를 만들 것
- 테스트 없는 큰 수정 금지
- scope creep 금지
- "예쁘게"보다 "실제로 돌아가게" 우선
- operator(사용자)는 초보자라는 점 항상 고려

## 9. Perplexity / GPT / Grok 참고 자료 반영 원칙
외부 AI가 준 의견은 참고자료다.
맹신 금지.
항상 아래처럼 처리할 것.

- 사실 확인된 것만 반영
- 설계와 현실 운영에 맞는 것만 채택
- 과장, 모호한 조언, 마케팅 문구 제거
- X-native 관점 + 운영 현실 + 승인형 구조를 동시에 만족해야 함

## 10. 다음 작업을 시작할 때 항상 스스로 확인할 질문
작업 전 아래 질문을 먼저 확인할 것.

1. 이 변경이 Layer 1을 흔드는가?
2. 이 변경이 진짜 운영 가치가 있는가?
3. 이 변경은 초보 운영자에게 실제로 도움이 되는가?
4. 이 변경은 스팸성 성장 기능으로 오해될 수 없는가?
5. 이 변경은 텍스트 운영 시스템 철학과 맞는가?
6. 더 작은 범위로 같은 효과를 낼 수 없는가?

## 11. 다음 단계 제안
현재 기준 다음 실전 우선순위는 아래다.

1. topic_memory.py 추가
2. voice_guard.py 추가
3. repetition/style warning을 ContentPack 또는 review flow에 연결
4. weekly report에 content mix advisory 추가
5. quality gate를 advisory로만 추가

단, 다음은 아직 하지 말 것.
- dashboard 대형화
- 이미지/영상 생성
- 위험 자동화
- 구조 전면 재설계

---

이 문서는 이후 Claude Code / GPT / 기타 AI가 읽고 작업 우선순위와 금지사항을 이해하기 위한 기준 문서다.
이 문서의 원칙을 어기는 방향 제안은 우선적으로 거절해야 한다.
