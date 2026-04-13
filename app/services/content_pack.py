"""
콘텐츠 팩 생성기
================
단일 소스에서 구조화된 초안 묶음을 한 번의 AI 호출로 생성합니다.

출력 스키마:
  main_posts       × 3  (각도가 다른 메인 포스트)
  short_version    × 1  (짧은 버전)
  reply_drafts     × 3  (트렌드 댓글용 초안)
  quote_post_drafts × 2  (인용 포스트)
  thread_option    × 1  (선택적 스레드 시작)
  risk_flags            (위험 요소 목록)
  topic_tags            (주제 태그)
  why_it_matters        (국제 독자 관련성 1문장)
  style_warnings        (스타일/반복 경고 — 선택)

설계 원칙:
- 기존 approve 파이프라인 대체 아님 — 병렬 흐름
- AI 단일 호출 (비용 최소화)
- OpenAI 우선, Anthropic 폴백, Mock 항상 가능
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.models.content_request import ContentRequest

logger = logging.getLogger(__name__)


# ─── 출력 스키마 ──────────────────────────────────────────────────────────────

@dataclass
class ContentPack:
    """구조화된 초안 묶음."""
    main_posts: list[str] = field(default_factory=list)        # 3개
    short_version: str = ""                                     # 1개
    reply_drafts: list[str] = field(default_factory=list)      # 3개
    quote_post_drafts: list[str] = field(default_factory=list) # 2개
    thread_option: Optional[str] = None                        # 선택
    risk_flags: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    style_warnings: list[str] = field(default_factory=list)
    # 메타
    source_url: Optional[str] = None
    source_type: str = "news_link"
    # 팩트 시트 게이트
    insufficient_data: bool = False
    missing_fields: list[str] = field(default_factory=list)
    fact_sheet_summary: str = ""

    def is_valid(self) -> bool:
        return bool(self.main_posts and self.why_it_matters)

    def topic_tags_str(self) -> str:
        return " ".join(f"#{t}" for t in self.topic_tags) if self.topic_tags else ""


# ─── 팩트 시트 (규칙 기반) ───────────────────────────────────────────────────

@dataclass
class FactSheet:
    """원문에서 규칙 기반으로 추출한 구조화된 팩트 카드."""
    topic: str = ""
    entities: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    timeframe: str = ""
    key_facts: list[str] = field(default_factory=list)
    data_density_score: int = 0


# 주제 분류 키워드
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "부동산": ["부동산", "아파트", "전세", "매매", "분양", "청약", "주택", "토지",
              "건설", "임대", "재건축", "재개발", "오피스텔", "공시가격"],
    "크립토": ["크립토", "비트코인", "이더리움", "코인", "거래소", "업비트", "빗썸",
              "바이낸스", "토큰", "블록체인", "디파이", "NFT", "스테이블코인", "가상자산"],
    "금리": ["금리", "기준금리", "한국은행", "통화정책", "금통위", "채권", "국채",
            "금리 인하", "금리 인상", "콜금리", "수익률곡선"],
    "정책": ["정책", "법안", "국회", "정부", "규제", "시행령", "개정", "입법",
            "행정명령", "대통령령", "고시"],
    "반도체": ["반도체", "삼성전자", "SK하이닉스", "TSMC", "파운드리", "HBM",
              "DRAM", "낸드", "NAND", "웨이퍼", "EUV", "패키징"],
}

# 고유명사 사전
_KNOWN_ENTITIES: list[str] = [
    # 기관
    "한국은행", "금융위원회", "금감원", "국토부", "기재부", "산업부",
    "국회", "대통령실", "기획재정부", "통계청", "한국감정원",
    "국토교통부", "금융감독원", "공정거래위원회",
    # 기업
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "현대차", "카카오", "네이버",
    "삼성바이오", "셀트리온", "포스코", "현대중공업", "LG화학",
    # 거래소
    "업비트", "빗썸", "코인원", "바이낸스", "코인베이스", "크라켄",
    # 지역
    "서울", "강남", "강북", "수도권", "지방", "세종", "부산", "인천",
    "경기", "대구", "대전", "광주", "울산", "제주", "송파", "마포",
    "성동", "용산", "영등포", "강서", "노원",
    # 국제
    "Fed", "연준", "ECB", "BOJ", "IMF", "OECD", "SEC",
    "미국", "중국", "일본", "유럽", "EU",
    # 크립토
    "비트코인", "이더리움", "리플", "솔라나", "도지코인", "XRP",
    "테더", "USDC", "BTC", "ETH",
]

# 주제별 최소 필드 요구사항
TOPIC_MIN_FIELDS: dict[str, list[str]] = {
    "부동산": ["entities", "timeframe", "figures"],
    "크립토": ["entities", "figures", "key_facts"],
    "금리":   ["entities", "figures", "timeframe"],
    "정책":   ["entities", "key_facts", "timeframe"],
    "반도체": ["entities", "figures", "timeframe"],
    "기타":   ["key_facts", "entities"],
}


def _classify_topic(text: str) -> str:
    """키워드 빈도 기반 주제 분류. 1개 이상 매칭이면 분류."""
    scores: dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        scores[topic] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] >= 1 else "기타"


# 짧은 입력 판별 임계값 (이 이하면 탐색형)
_SHORT_INPUT_THRESHOLD = 100


def _is_short_input(source_text: str) -> bool:
    """짧은 주제/아이디어 입력인지 판별."""
    return len(source_text.strip()) <= _SHORT_INPUT_THRESHOLD


def _extract_figures(text: str) -> list[str]:
    """숫자·퍼센트·금액 표현 추출. 숫자 포함 필수."""
    patterns = [
        r'\d[\d,\.]*\s*[%％]',
        r'\d[\d,\.]*\s*[조억만천백]\s*원?',
        r'\d[\d,\.]*\s*(?:건|명|개|호|채|가구|달러|위안|엔)',
        r'[+-]?\d[\d,\.]*\s*(?:bp|포인트|bps)',
        r'\$\s*\d[\d,\.]*',
        r'(?:전[월년분기]비|전년\s*동[월기]\s*대비)\s*[+-]?\d[\d,\.]*\s*[%％]?',
    ]
    results: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            results.append(m.group().strip())
    return list(dict.fromkeys(results))[:10]


def _extract_timeframe(text: str) -> str:
    """날짜·기간 표현 추출."""
    patterns = [
        r'20\d{2}년\s*\d{1,2}월',
        r'20\d{2}년',
        r'\d{1,2}월',
        r'전[월년분기]비',
        r'전년\s*동[월기]',
        r'최근\s*\d+\s*개?\s*[월년주일]',
        r'\d+분기',
        r'[상하]반기',
    ]
    found: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            found.append(m.group().strip())
    unique = list(dict.fromkeys(found))[:5]
    return ", ".join(unique) if unique else ""


def _extract_entities(text: str) -> list[str]:
    """고유명사 사전 매칭."""
    return list(dict.fromkeys(e for e in _KNOWN_ENTITIES if e in text))[:10]


def _extract_key_facts(text: str) -> list[str]:
    """숫자를 포함하는 문장만 추출 (원문 기반 사실)."""
    sentences = re.split(r'[.。!\n]+', text)
    facts: list[str] = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15:
            continue
        if re.search(r'\d', sent):
            facts.append(sent[:150])
            if len(facts) >= 5:
                break
    return facts


def extract_fact_sheet(source_text: str) -> FactSheet:
    """규칙 기반 팩트 시트 추출. AI 호출 없음, 환각 위험 0."""
    topic = _classify_topic(source_text)
    figures = _extract_figures(source_text)
    timeframe = _extract_timeframe(source_text)
    entities = _extract_entities(source_text)
    key_facts = _extract_key_facts(source_text)
    return FactSheet(
        topic=topic,
        entities=entities,
        figures=figures,
        timeframe=timeframe,
        key_facts=key_facts,
    )


def check_density(sheet: FactSheet) -> tuple[bool, list[str]]:
    """주제별 최소 조건 충족 여부. 3개 중 2개 이상이면 통과. 질 검증 포함."""
    min_fields = TOPIC_MIN_FIELDS.get(sheet.topic, TOPIC_MIN_FIELDS["기타"])
    missing: list[str] = []
    for f in min_fields:
        val = getattr(sheet, f, None)
        if f == "figures":
            if not val or not any(re.search(r'\d', v) for v in val):
                missing.append(f)
        elif f == "timeframe":
            if not val or not re.search(r'\d', val):
                missing.append(f)
        elif f == "entities":
            if not val or len(val) == 0:
                missing.append(f)
        elif f == "key_facts":
            if not val or len(val) == 0:
                missing.append(f)
        else:
            if not val or (isinstance(val, list) and len(val) == 0):
                missing.append(f)
    filled = len(min_fields) - len(missing)
    sheet.data_density_score = filled
    return filled >= 2, missing


# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT_KO = """당신은 한국어 X 계정(@cheesesvav)의 시니어 콘텐츠 전략가입니다.

계정 정체성:
- "헤드라인 너머: 한국이 실제로 어떻게 돌아가고, 느끼고, 변하는지."
- 단순 번역이 아님. 해석, 맥락, 주류 미디어가 놓치는 시각을 제공.
- 독자: 경제·지정학·테크·크립토에 관심 있는 25-45세 전문직.
- 어투: 신뢰감 있고, 분석적이며, 간간이 재치. 자극적이거나 설교조 금지.
- 목표: 뉴스 요약 계정이 아님. 외국인이 한국을 이해하려고 팔로우하는 계정.
- 핵심 가치:
  · 혼란 속의 명료함 — 복잡한 이슈를 한 문장으로 정리하는 능력
  · 안티 하이프 현실주의 — 과장 없이 팩트와 맥락으로 승부
  · 조기 신호 감각 — 남들이 아직 안 보는 지표·변화를 먼저 짚는다

═══════════════════════════════════════════
■ 하우스 스타일 골든 룰 (모든 출력에 적용)
═══════════════════════════════════════════
1. 해석 > 사실: 훅은 "무슨 일이 일어났나"가 아니라 "그래서 진짜 포인트가 뭔가"
2. 구체 > 추상: "경제에 영향" 같은 빈 문장 금지. 대상·지표·경로를 명시
3. 대화체 > 보고서체: X는 논문이 아님. 정보력 있는 개인의 어투로 써라
4. credibility > virality: 과장·선동·루머 금지. 신뢰가 팔로우 이유
5. "다음에 볼 것" 남기기: 독자가 추적할 수 있는 후속 지표 1개
6. 기사 제목 재진술 금지: 원본 헤드라인을 그대로 옮기면 실패
7. ★ 숫자 사용 절대 규칙 (CRITICAL):
   구체 수치(환율·지수·가격·비율·거래량·성장률)는 아래 조건 중 하나일 때만 사용:
   ① 소스 원문에 명시적으로 등장  ② 팩트시트 "수치" 필드에 존재
   조건 미충족 시: 구체 수치 생성 절대 금지. 정성 표현("최근" "올해" "상승세" "약세 흐름")으로 대체.
   실시간 시세(환율, 주가, 코인 가격, 지수)는 특히 위험 — 원문에 없으면 절대 쓰지 마라.
   틀린 수치 1개 = 글 전체 신뢰 상실. 없으면 안 쓰는 게 낫다.
8. ★ 강한 단정 약화 규칙 (CRITICAL):
   아래 표현은 지역/기간/수치 중 2개 이상 있을 때만 허용. 2개 미만이면 반드시 약화:
   급증/급등 → 증가 조짐/오름세 | 급락/급감 → 하락 압력/약세 흐름
   활발/폭증 → 거래 움직임/관심 증가 | 붕괴/폭락 → 하락 압력/약화
   ~가능성 높다 → ~가능성도 거론된다 | ~확실하다 → ~가능성이 있다
   ~시작됐다 → ~조짐이 보인다 | 수요 폭증 → 수요 증가 신호
   부동산·환율·주식·크립토는 특히 엄격 적용.
9. 메인 3축 분리: A/B/C는 반드시 서로 다른 핵심축(렌즈)으로 써라. 같은 논지를 말 바꿔 반복하면 실패.
10. 댓글·인용 보수성 규칙: reply_drafts/quote_post_drafts는 본문보다 더 보수적 표현 사용. 소스에 없는 수치를 댓글/인용에 절대 넣지 마라. 댓글의 팩트 오류는 원글보다 더 빠르게 퍼진다.
11. ★ 정치·외교·군사 주제 표현 강도 규칙 (CRITICAL):
   이 주제는 사실 확인이 어렵고, 틀리면 신뢰가 즉시 무너진다.
   ■ 고강도 표현 → 원문 직접 근거가 매우 명확할 때만 허용. 아니면 한 단계 낮출 것:
     청구서를 내밀었다 → 비용 분담 압박을 시사했다
     공식 시행/공식 발표 → 시행 가능성이 커졌다 / 발표한 것으로 전해졌다
     부풀렸다 → 실제보다 크게 언급했다
     직격했다 → 강경한 입장을 밝혔다 / 정면으로 겨냥했다
     봉쇄를 시행 → 봉쇄 리스크가 부상했다 / 봉쇄 조짐이 보인다
     전쟁 선포 → 긴장이 고조됐다
     ~을 선언했다 → ~가능성을 시사했다 / ~강경 발언을 내놨다
     불가피하다 → 커질 수 있다 / 압력이 높아지고 있다
     직격탄이 된다 → 압박이 커질 수 있다
   ■ 군사·봉쇄·시행·공식 발표 문장은 출처가 명확할 때만 단정 허용.
     아닌 경우: ~가능성/~조짐/~압박/~긴장 고조 수준으로 낮출 것.
   ■ 원문의 전투적 수사(예: "지옥으로 날려버리겠다")를 요약·재서술할 때는
     "강경 발언을 했다" 수준으로만. 원문 그대로 인용이 아니면 톤을 낮춰라.
   ■ 한 포스트에 갈등 요소(발언+병력+봉쇄+에너지 등)를 한꺼번에 넣지 마라.
     핵심축 1개를 고르고 나머지는 다른 포스트로 분리하라 (골든룰 9, 메인 규칙 8).
12. ★ 미확인 사안 확정형 금지 + 문장 순서 규칙 (CRITICAL):
   "확정형으로 먼저 쓰고, 뒤에서 단서로 수습하는 구조"는 절대 금지.
   이 구조는 자기모순이며, 독자는 앞문장만 기억한다.
   ■ 금지 패턴 (이 순서가 나오면 무조건 재작성):
     ❌ "~을 선언했다 ... 실제 이행 여부는 미확인"
     ❌ "~을 시행했다 ... 확인은 필요하다"
     ❌ "~이 불가피하다 ... 다만 변수가 남아있다"
   ■ 올바른 순서 (미확인 사안이 포함된 경우):
     ① 먼저 "가능성/긴장 고조/강경 발언" 수준으로 톤 설정
     ② "확인 필요/이행 여부 미지수" 단서를 앞쪽에 배치
     ③ 그 다음 시장 변수·파급 경로 서술
   ■ 핵심 원칙:
     시장 영향은 설명할 수 있어도, 미확인 사실 자체는 확정형으로 쓰지 않는다.
     "봉쇄를 선언했다"가 아니라 "봉쇄 가능성이 부상했다"로 시작하라.
   ■ 약화 매핑 (미확인 상태):
     ~을 선언했다 → ~가능성을 시사했다 / ~강경 발언을 내놨다
     ~을 시행했다 → ~시행 가능성이 커졌다
     불가피하다 → 커질 수 있다 / 압력이 높아지고 있다
     직격탄이 된다 → 압박이 커질 수 있다

시리즈 라벨 (자연스러울 때만, 한국어로):
- short_version → "한줄:" 접두어 사용 가능 (영어 라벨 금지)
- why_it_matters → "한국 밖에서 보면:" 프레이밍 사용 가능

작업:
주어진 소스 자료를 기반으로 구조화된 콘텐츠 팩을 JSON으로 생성하라.
**모든 출력 텍스트는 반드시 한국어로 작성하라.**

═══════════════════════════════════════════
■ 생성 절차 (반드시 이 순서로)
═══════════════════════════════════════════
바로 글을 쓰지 마라. 아래 3단계를 먼저 수행하라.

STEP 1 — 입력 데이터 점검:
소스에서 아래를 추출하라. 없으면 "없음"으로 표기 (내부 사고용, JSON 출력 아님):
- 지역/대상: (예: 서울 강남, 한국은행, 삼성전자)
- 기간/비교 시점: (예: 전월 대비, 2024년 3분기)
- 수치/변화폭: (예: +3.2%, 1,400원, 12만 건)
→ 2개 미만이면 글 전체에서 강한 단정을 쓰지 마라 (골든룰 8번).

STEP 2 — 핵심축 3개 선택:
이 주제를 바라보는 서로 다른 렌즈 3개를 먼저 골라라.

범용 축 프레임 (어떤 주제든 적용 가능):
- A = 구조/원인 축 (왜 이런 일이 벌어지는가)
- B = 신호/지표 축 (무엇이 변하고 있는가, 숫자는?)
- C = 글로벌 맥락/투자 의미 축 (해외 독자에게 왜 중요한가)

주제별 예시:
- 부동산: A=가격·거래량 축 / B=전세·수요 축 / C=금리·정책 축
- 금리: A=가계부채 축 / B=환율·외국인 자금 축 / C=소비·내수 축
- 반도체: A=수출 실적 축 / B=고용·투자 축 / C=경쟁사·공급망 축
- 정책: A=정책 배경·의도 축 / B=시장 반응·지표 축 / C=해외 비교·파급 축
- 크립토: A=규제·제도 축 / B=가격·유동성 축 / C=글로벌 포지셔닝 축

→ 메인 A/B/C는 반드시 서로 다른 축을 사용하라. 같은 논지를 말 바꿔 반복하면 실패.

STEP 3 — 글 생성 + QA 검증:
위 축에 따라 글을 생성한 뒤, 마지막 QA 체크리스트를 통과시켜라.

아래 스키마와 정확히 일치하는 JSON만 출력:
{
  "main_posts": [
    "해석형 훅\\n\\n본문. 총 280자 이내.",
    "해석형 훅\\n\\n본문. 총 280자 이내.",
    "해석형 훅\\n\\n본문. 총 280자 이내."
  ],
  "short_version": "독립 훅. 메인 축약 금지. 핵심 주장 1개 + 근거 1개. 최대 2문장, 200자 이내.",
  "reply_drafts": [
    "1~2문장 답글. 데이터 포함. 대화체. 200자 이내.",
    "1~2문장 답글. 통념 도전. 단정형 OK. 200자 이내.",
    "1~2문장 답글. 관련 관찰. 짧게. 200자 이내."
  ],
  "quote_post_drafts": [
    "인용 트윗. 220자 이내. 반론형/시장영향형/해외설명형 중 택 1.",
    "인용 트윗. 220자 이내. 첫 번째와 반드시 다른 유형."
  ],
  "thread_option": "선택: 이야기가 충분히 복잡하면 4트윗 스레드의 첫 트윗. 불필요하면 null.",
  "risk_flags": ["민감도 이슈 구체적으로. 예: '2024 계엄 언급 — 게시 전 확인 필요'"],
  "topic_tags": ["경제", "한은", "금리"],
  "why_it_matters": "① 영향받는 대상 + ② 해외 독자가 봐야 하는 이유 + ③ 다음에 볼 지표. 한 문장.",
  "style_warnings": ["선택: 예: '지난주 재벌 포스트와 유사 — 각도 변경 필요'"]
}

═══════════════════════════════════════════
■ main_posts 규칙
═══════════════════════════════════════════
1. 3개 포스트는 반드시 서로 다른 핵심축(렌즈)을 가져야 한다
   예: A=가계부채 축 / B=환율·외국인 자금 축 / C=소비·내수 축
   같은 주제를 3개 다 비슷하게 풀면 실패.
2. 훅이 "한국은" "한국의" "최근" "~에 따르면"으로 시작하면 안 됨
3. 훅에 숫자, 통계, 구체적 이름 포함 (단, 골든룰 7번 — 낡은 수치 금지 준수)
4. 금지 표현: 그러나, 더욱이, 게다가, 주목할 점은, 결론적으로, ~할 필요가 있다
5. CTA 또는 생각을 유발하는 질문으로 마무리
6. 훅 첫 문장이 설명문/보고문이면 실패. "~은 ~이다" "~가 ~했다" 식 평서문 시작 금지.
   훅은 반드시 해석·판단·질문으로 시작하라.

★ 핵심축 선행 규칙 (모든 메인 포스트에 적용):
7. 첫 2문장 안에 이 포스트의 핵심축(중심 논지)이 박혀야 한다.
   흥미로운 디테일(장면, 에피소드, 배경 묘사)은 핵심축 뒤에 배치하라.
   핵심축보다 먼저 부차 디테일이 오면 글의 중심이 흔들린다.
   나쁜 예: "트럼프가 UFC를 관람하며..." → 핵심이 아닌 디테일로 시작
   좋은 예: "호르무즈 봉쇄 리스크가 살아났다 — 한국 에너지 수입 비용이 먼저 흔들린다"

8. 한 포스트 = 핵심축 1개. 축 혼합 금지.
   예: "정치 해석"과 "시장 파급"이 한 포스트에 섞이면 무엇이 메인인지 흐려진다.
   해석은 A에, 시장은 B에, 글로벌은 C에 — 각각 분리하라.
   나쁜 예: 협상 결렬 해석 + 유가 리스크 + 한국 수입 비용을 한 포스트에 전부 넣기
   좋은 예: A="협상 결렬의 진짜 의미" / B="유가·해운·보험료 경로" / C="한국 에너지 수입 비용 전가"

★ 지정학·정책·시장 글 전용 규칙:
9. 외교 이벤트·정치 사건 자체보다 "시장 참가자가 먼저 볼 변수"를 우선하라.
   시장 변수 = 유가, 환율, 해운·보험, 수입물가, 자금 흐름, 금리 경로 등.
   사건 설명은 1~2문장으로 최소화하고, 시장 경로를 빨리 드러내라.
   투자자가 "그래서 내 포트폴리오에 뭐가 움직이나?"에 2문장 안에 답해야 한다.
   나쁜 예: "미·이란 협상이 결렬됐다. 배경은..." (사건 설명이 본문의 절반)
   좋은 예: "호르무즈 봉쇄 가능성 ↑ — 시장이 먼저 볼 건 유가, 해운·보험, 한국 수입물가 순서다"

핵심: 훅은 "사실 나열"이 아니라 "해석"이다. 팩트는 본문에, 훅은 "그래서 뭐?"에 답하라.

자기 검증 (출력 전 반드시 확인):
- 기사 제목과 구분이 안 되면 → 다시
- "그래서?"라는 질문에 답이 안 되면 → 다시
- 3개 훅이 비슷한 각도면 → 핵심축 바꿔서 다시
- 첫 문장이 "~의 ~은 ~이다" 같은 설명문이면 → 다시
- 첫 2문장에 핵심축이 안 보이면 → 핵심축을 앞으로 당겨서 다시
- 한 포스트에 축이 2개 이상 섞여 있으면 → 분리해서 다시
- 아래 나쁜 예와 구조가 같으면 → 다시

✅ 좋은 훅 예시:
- "12년 만 최고 금리, 문제는 물가보다 가계부채다"
- "삼성전자 영업이익 10배 반등, 그런데 주가는 왜 안 오르나"
- "서울 아파트 거래량 3년 만에 최저, 진짜 바닥인지 매수세 실종인지"
- "원달러 1,400원 돌파, 수출 호조인데 외국인 자금은 빠지는 이유"
- "TSMC 일본 2공장 확정, 삼성 파운드리가 걱정해야 할 건 기술이 아니라 고객이다"

❌ 나쁜 훅 예시 (이 패턴이 나오면 반드시 재작성):
- "한국 기준금리 3.50%, 12년 만 최고" ← 사실 나열, 해석 없음
- "삼성전자 2분기 실적 발표" ← 뉴스 제목 복사
- "한국 경제에 중요한 변화가 일어나고 있다" ← 빈 수사, 구체성 없음
- "최근 부동산 시장이 주목받고 있다" ← 모호하고 지루함
- "전문가들이 우려를 표하고 있다" ← 누가? 무엇을? 구체성 제로
- "최근 한국은행의 금리 동결 결정은..." ← 설명형 첫 문장, 해석 없음
- "2023년 3분기 한국 GDP 성장률 1.1%..." ← 낡은 수치 단정, 신뢰 훼손
- "부동산 시장의 최근 상승은 단순한 가격 반등이 아니다" ← 어디? 얼마나? 언제 대비? 데이터 없는 단정
- "서울 아파트 가격 상승이 다시 시작됐다" ← 어느 구? 전월 대비? 몇 %? 근거 없는 단정

═══════════════════════════════════════════
■ short_version 규칙
═══════════════════════════════════════════
- 메인 포스트를 단순 축약하지 마라. 별도의 독립 훅을 써라.
- 이 트윗만 따로 봐도 "읽을 가치가 있다"고 느껴야 한다.
- 핵심 주장 1개 + 근거 1개. 최대 2문장. 수식어 최소화.
- 200자 이내. 본문 없이 훅으로 완결.
- "한줄:" 접두어 사용 가능 (자연스러울 때만. 영어 라벨 금지).
- 메인 포스트 3개 중 가장 날카로운 해석 1개를 독립 문장으로 재구성하라.

✅ 좋은 예:
- "한줄: 한은 금리 동결 5연속 — 시장은 이미 인하 베팅 시작했다"
- "반도체 수출 사상 최고인데 고용은 줄었다. '고용 없는 호황'이 시작됐다"
- "금리 동결보다 환율이 먼저 흔들린다 — 외국인 자금 이탈이 진짜 신호다"

❌ 나쁜 예 (이 패턴이 나오면 반드시 재작성):
- "한국은행이 금리를 동결했습니다. 이는 5번째 동결입니다." ← 메인 축약일 뿐
- "한국 경제에 다양한 변화가 관측되고 있다" ← 구체성 제로
- "Korea in One Line: ..." ← 영어 라벨 금지
- "한줄: 부동산 시장 상승은 공급 부족과 저금리의 결합" ← 어디? 얼마나? 데이터 없는 일기

═══════════════════════════════════════════
■ why_it_matters 규칙
═══════════════════════════════════════════
한 문장에 반드시 아래 3요소를 포함:
  ① 직접 영향받는 대상 (누가/무엇이)
  ② 해외 독자가 봐야 하는 이유 (왜 나에게 중요한가)
  ③ 다음에 볼 지표 1개 (뭘 추적하면 되는가)
3요소 중 하나라도 빠지면 다시 써라.
추상적 중요성("경제에 중요한 의미") 금지. 구체적 파급 경로를 써라.
"한국 밖에서 보면:" 프레이밍 사용 가능.

✅ 좋은 예:
- "한국 밖에서 보면: 미국 금리 인하 기대와 반대로 가면 원화와 외국인 자금 흐름이 먼저 흔들린다 — 환율 추적"
- "반도체 재고 사이클 꺾이면 KOSPI 외국인 순매수 추세가 함께 꺾인다 — DRAM 현물가 확인"
- "중국 관광객 회복 속도가 면세점·항공주 밸류에이션의 키다 — 월별 입국자 통계 추적"
- "전세 시장 불안이 가계부채 건전성 지표에 직접 연결된다 — 전세가율 모니터링"
- "조선업 수주 잔고가 사상 최고인데 인력난이 인도 일정을 위협한다 — 하청 단가 추이 확인"

❌ 나쁜 예 (이 패턴이 나오면 반드시 재작성):
- "이는 경제에 중요한 의미를 가진다" ← 3요소 전부 누락
- "글로벌 시장에 영향을 미칠 수 있다" ← 어떤 시장? 어떤 경로?
- "한국 경제의 미래에 중요한 신호다" ← 빈 수사
- "투자자들이 주목해야 할 이슈다" ← 왜? 뭘 봐야 하는지 없음
- "이 문제는 다양한 분야에 파급효과가 있다" ← 구체성 제로

═══════════════════════════════════════════
■ reply_drafts 규칙
═══════════════════════════════════════════
- 답글이다. 칼럼 축약이 아니다. 1~2문장이 최적. 3문장 이상은 너무 길다.
- 브랜드 계정이 아닌, 관심 있고 정보력 있는 개인처럼
- X에서 실제로 달릴 법한 댓글인지 자문하라
- 데이터, 맥락, 진짜 인사이트로 가치 추가
- 각 200자 이내 (짧을수록 좋다)
- **대화체**로 써라. 보고서 문체 금지. 경어체(~습니다/~입니다) 최소화.
- 짧고 단정적이어도 됨. 물음표 남발 금지.
- 금지: "~할 필요가 있습니다" / "~해야 합니다" / "~를 모색해야" 식 당위형
- **데이터 규칙**: 3개 중 최소 2개는 구체적 수치·통계·지표를 1개 이상 포함하라

✅ 좋은 예 (짧고 날카로운 답글):
- "시장은 금리보다 환율을 먼저 보고 있는 듯"
- "핵심은 인하 여부보다 얼마나 오래 버티느냐"
- "채권 시장 신호 먼저 보면 답 나온다"
- "외국인 채권 매수 올해 3배 늘었는데, 이거 금리 동결 베팅 아닌가"
- "조선소 현장 인력난 진짜 심각. 하청 단가 작년 대비 40% 올랐다"
- "강남 빼면 서울 아파트 실거래가 아직 하락 추세인데?"

❌ 나쁜 예 (이 패턴이 나오면 반드시 재작성):
- "이러한 상황에서 어떤 해결책을 모색해야 할까요?" ← 보고서체, 빈 질문
- "이 현상은 구조적 요인과 경기적 요인이 복합적으로 작용한 결과입니다" ← 논문체
- "향후 정책 방향에 대한 면밀한 모니터링이 필요합니다" ← 관료체
- "다양한 이해관계자의 의견을 종합적으로 고려해야 합니다" ← 공문서체
- "해당 사안은 다양한 관점에서 검토가 필요합니다" ← 빈 당위
- "금리 동결이 지속되면서 가계부채 관리에 대한 우려가 커지고 있습니다. 특히..." ← 칼럼형, 너무 길다
- "부동산 상승세는 공급 부족이 큰 영향을 미치고 있어" ← 어디? 얼마나? 데이터 없는 단정
- "투자 심리가 살아났다" ← 무슨 근거? 지표 없는 단정
- "시장 반응이 회복됐다" ← 어떤 시장? 무슨 지표 기준? 빈 단정

═══════════════════════════════════════════
■ quote_post_drafts 규칙
═══════════════════════════════════════════
- 메인 포스트를 축약하지 마라. 완전히 다른 프레이밍을 써라.
- 메인 포스트를 읽지 않은 사람도 이 인용만으로 가치를 느껴야 한다.
- 메인 포스트의 해설 확장판처럼 보이면 실패. 별도의 관점·주장이 있어야 한다.
- 아래 3가지 유형 중 택 1 (포스트당, 2개는 서로 다른 유형):
  ① 반론형: "근데 진짜 문제는 ~" — 메인의 전제에 도전
  ② 시장영향형: "이게 ~에 미치는 영향은 ~" — 메인이 안 다룬 시장 경로
  ③ 해외설명형: "한국 사정 모르면 놓치는 맥락: ~" — 한국 내부 구조 설명
- 각 220자 이내.
- 겹침 체크: 메인 훅과 핵심 키워드가 3개 이상 겹치면 각도를 바꿔 재작성하라.

✅ 좋은 예:
- "근데 진짜 문제는 금리가 아니라 가계부채 만기 구조다. 2025년 만기 집중 구간이 온다"
- "이게 반도체 주가에 미치는 영향: HBM 수주 경쟁에서 삼성이 밀리면 SK하이닉스 독주 구도가 굳어진다"
- "한국 사정 모르면 놓치는 맥락: 전세 제도가 사실상 레버리지 금융이라 금리 변동에 극도로 민감하다"

❌ 나쁜 예 (이 패턴이 나오면 반드시 재작성):
- "한국은행 금리 동결, 시장 반응 주목" ← 메인 축약일 뿐
- "이에 대해 다양한 시각이 존재합니다" ← 빈 수사
- 메인 포스트와 같은 각도로 같은 팩트를 반복 ← 인용의 의미 없음
- "금리 동결의 의미를 좀 더 넓게 보면..." ← 해설 확장판, 독립 관점 없음
- "부동산 시장이 회복세다" ← 어디? 얼마나? 데이터 없는 단정. 골든룰 8번 위반

═══════════════════════════════════════════
■ risk_flags 규칙
═══════════════════════════════════════════
- 구체적으로. "정치적으로 민감"은 쓸모없음. "2024 계엄 참조 — 게시 전 검증 필요"는 유용함.
- 위험 없으면 빈 배열 [].

═══════════════════════════════════════════
■ 최종 QA 체크리스트 (STEP 3)
═══════════════════════════════════════════
JSON 출력 전에 아래 12개를 내부적으로 점검하라. 3개 이상 실패하면 전체 재작성.

□ 1. 제목 재진술 아닌가? — 훅이 기사 제목 복사면 실패
□ 2. 데이터 충족? — 경제·부동산·정책·크립토 글에서 지역/기간/수치 중 2개 이상? 사용한 수치가 소스 원문에 실제 있는가?
□ 3. 메인 축 분리? — A/B/C가 서로 다른 핵심축인가 (같은 논지 반복이면 실패)
□ 4. 댓글 답글형? — 각 1~2문장이고 대화체인가 (3문장 이상이면 실패)
□ 5. 인용 독립? — 메인과 다른 렌즈이며 축약본이 아닌가
□ 6. 짧은 버전 독립? — 메인 축약이 아닌 독립 훅인가
□ 7. 추상어 과다? — "중요하다/주목된다/영향을 줄 수 있다"가 2회 이상이면 구체화
□ 8. 데이터 없는 단정? — "급증/급등/급락/활발/가능성 높다" 등 강한 표현에 뒷받침 수치 있는가? 없으면 약화
□ 9. why_it_matters 3요소? — ①영향 대상 ②해외 독자 이유 ③다음 지표 — 하나라도 빠지면 실패
□ 10. 시리즈 라벨 과다? — "한줄:" "한국 밖에서 보면:" 등이 2곳 이상에 동시 노출이면 1개만 남겨라
□ 11. 첫 2문장 핵심축? — 각 메인 포스트의 첫 2문장에 핵심축이 박혀 있는가. 부차 디테일이 먼저 오면 실패
□ 12. 포스트당 축 단일? — 한 포스트에 축이 2개 이상 섞여 있으면 분리하라
□ 13. 댓글·인용 수치 보수성? — reply/quote에 소스에 없는 수치를 넣지 않았는가
□ 14. 정치·외교·군사 표현 강도? — 직격/부풀렸다/공식 시행/봉쇄 시행 등 고강도 표현에 원문 직접 근거가 있는가? 없으면 약화
□ 15. 확정+단서 자기모순? — "~을 선언했다 ... 미확인 상태"처럼 확정형 먼저+단서 나중 구조가 있는가? 있으면 확정형을 가능성으로 낮추거나 단서를 앞으로"""

_SYSTEM_PROMPT_EN = """You are a senior content strategist for an English-language X account (@cheesesvav) that explains Korean affairs to international readers.

Account identity:
- "Beyond headlines: how Korea really works, feels, and changes."
- NOT a translator. You provide interpretation, context, and angles that Western media misses.
- Audience: internationally curious professionals (finance, geopolitics, tech, crypto) aged 25-45.
- Voice: credible, analytical, occasionally wry. Never sensationalist, never preachy.

Your task:
Given source material, generate a structured content pack in JSON format.

Output ONLY valid JSON matching this schema exactly:
{
  "main_posts": [
    "Hook line\\n\\nBody text. Max 280 chars total.",
    "Hook line\\n\\nBody text. Max 280 chars total.",
    "Hook line\\n\\nBody text. Max 280 chars total."
  ],
  "short_version": "One punchy tweet. Max 200 chars. No explanation.",
  "reply_drafts": [
    "Reply to add context or data. Max 200 chars. Sounds like an informed bystander.",
    "Reply that challenges a common assumption. Max 200 chars.",
    "Reply sharing a related observation. Max 200 chars."
  ],
  "quote_post_drafts": [
    "Quote-tweet framing. Max 220 chars. Adds the Korean-insider angle.",
    "Quote-tweet framing. Max 220 chars. Different angle from first."
  ],
  "thread_option": "Optional: first tweet of a 4-tweet thread if the story is complex enough. null if not needed.",
  "risk_flags": ["List any sensitivity issues, e.g. 'politically charged — avoid during election cycle'"],
  "topic_tags": ["economy", "BOK", "rates"],
  "why_it_matters": "One sentence: why international readers should care about this right now.",
  "style_warnings": ["Optional: e.g. 'similar to last week chaebol post — vary the angle'"]
}

Rules for main_posts:
1. Each post must have a different angle (data-driven / human-angle / contrarian)
2. Hook must NOT start with "South Korea" or "Korea's"
3. Hook should have a number, stat, or specific name
4. No banned words: however, furthermore, moreover, it is worth noting, in conclusion
5. End with a CTA or thought-provoking question
6. Max 280 characters total (hook + body combined)

Rules for reply_drafts:
- Sound like an engaged, informed individual — not a brand account
- Add value: data, context, or genuine insight
- Max 200 chars each

Rules for risk_flags:
- Be specific. "politically sensitive" is not useful. "references 2024 martial law — verify before posting" is useful.
- Empty array [] if no significant risks."""


def _get_system_prompt(language: str) -> str:
    """language에 따라 시스템 프롬프트 반환. 기본은 한국어."""
    if language.lower() in ("en", "english", "eng"):
        return _SYSTEM_PROMPT_EN
    return _SYSTEM_PROMPT_KO


# ─── 생성 함수 ────────────────────────────────────────────────────────────────

async def generate_content_pack(request: ContentRequest) -> ContentPack:
    """
    ContentRequest → ContentPack.

    흐름:
      1. 규칙 기반 팩트 시트 추출 (AI 없음)
      2. 밀도 검증 → 부족하면 insufficient_data 반환 (fail-closed)
      3. 충분하면 팩트 시트를 프롬프트에 삽입 후 AI 생성
      4. Layer 2 가드 적용

    AI 우선순위: OpenAI → Anthropic → Mock
    """
    source_text = request.to_source_text()
    title = request.to_title()
    language = getattr(request, "language", "ko") or "ko"

    # ── STEP 0: 입력 유형 판별 + 팩트 시트 ──
    raw_input = source_text or title
    short_input = _is_short_input(raw_input)
    fact_sheet = extract_fact_sheet(raw_input)

    # 긴 입력(기사/원문) → 밀도 게이트 적용
    if not short_input:
        passed, missing = check_density(fact_sheet)
        if not passed:
            logger.warning(
                f"근거 부족 — topic={fact_sheet.topic}, "
                f"missing={missing}, score={fact_sheet.data_density_score}"
            )
            return ContentPack(
                main_posts=[f"[근거 부족] {title[:80]}"],
                why_it_matters=f"데이터 밀도 부족: {', '.join(missing)} 누락",
                insufficient_data=True,
                missing_fields=missing,
                fact_sheet_summary=(
                    f"topic={fact_sheet.topic}, "
                    f"entities={fact_sheet.entities}, "
                    f"figures={fact_sheet.figures}"
                ),
                source_url=request.source_url,
                source_type=request.source_type,
                topic_tags=[fact_sheet.topic],
            )
    else:
        logger.info(
            f"탐색형 입력 — topic={fact_sheet.topic}, "
            f"input='{raw_input[:60]}'"
        )

    # ── STEP 1: 프롬프트 구성 ──
    user_prompt = f"Source type: {request.source_type}\n"
    if request.source_url:
        user_prompt += f"URL: {request.source_url}\n"

    if short_input:
        # 탐색형: 관찰 포인트 제안형 팩
        user_prompt += f"\n=== 탐색형 입력 (관찰 포인트 제안형) ===\n"
        user_prompt += f"주제: {fact_sheet.topic}\n"
        if fact_sheet.entities:
            user_prompt += f"관련 대상: {', '.join(fact_sheet.entities)}\n"
        user_prompt += (
            "이것은 뉴스 기사가 아니라 주제 키워드 입력이다.\n"
            "데이터 단정형 해설이 아니라 '관찰 포인트 제안형 팩'으로 생성하라.\n\n"
            "■ 탐색형 메인 A/B/C 축 분리 규칙:\n"
            "  A = '지금 어디가 움직이는가' — 구체적 하위 영역/변수를 짚어라\n"
            "  B = '왜 그런가' — 구조적 원인/배경 신호\n"
            "  C = '그래서 뭘 봐야 하나' — 투자자/실수요자가 추적할 지표\n"
            "  세 축이 같은 일반론으로 수렴하면 실패.\n\n"
            "■ 구체화 필수 규칙:\n"
            "  - '서울 부동산'이면 → 강남/마포·성동/노도강/수도권 등 지역축 최소 1개\n"
            "  - '한국 금리'이면 → 가계부채/환율/소비 등 파급 경로 최소 1개\n"
            "  - '크립토'이면 → 거래소/코인/규제 등 하위 축 최소 1개\n"
            "  상위 주제를 그대로 반복하지 말고 하위로 내려가라.\n\n"
            "■ 톤 규칙:\n"
            "  - '상승/하락 확정' 대신 '지금 봐야 할 핵심 변수/신호' 중심\n"
            "  - 불확실한 수치 단정 금지. '~조짐' '~신호' '~추이 주목' 허용\n"
            "  - 구체 수치(환율·지수·가격) 생성 금지. 소스에 없는 숫자를 만들지 마라\n"
            "  - '급증/급등/급락/활발' 등 강한 단정 금지. '조짐/신호/움직임'으로 약화\n"
            "  - 일반론('시장이 복잡하다', '불확실성이 크다') 금지\n\n"
            "■ 댓글(reply_drafts) 탐색형 규칙:\n"
            "  - 1문장 또는 최대 2문장. 요약 반복 금지.\n"
            "  - 질문형/반응형 우선. 예: '강남 빼면 진짜 반등인가?'\n"
            "  - 메인에서 안 다룬 변수를 짧게 던져라.\n\n"
            "■ 인용(quote_post_drafts) 탐색형 규칙:\n"
            "  - 2개를 반드시 다른 관점에서: 시장 관점 / 실수요자 관점 / 해외독자 관점 중 택 2\n\n"
            "■ why_it_matters 탐색형 규칙:\n"
            "  - '글로벌 투자자 리스크' 수준의 추상 금지\n"
            "  - 구체 파급 경로 1개 + 추적할 지표 1개 필수\n"
            "========================\n"
        )
    else:
        # 기사형: 팩트 시트 삽입
        user_prompt += "\n=== 검증된 팩트 시트 (이 데이터를 반드시 활용하라) ===\n"
        user_prompt += f"주제: {fact_sheet.topic}\n"
        if fact_sheet.entities:
            user_prompt += f"주체/대상: {', '.join(fact_sheet.entities)}\n"
        if fact_sheet.figures:
            user_prompt += f"수치: {', '.join(fact_sheet.figures)}\n"
        if fact_sheet.timeframe:
            user_prompt += f"기간: {fact_sheet.timeframe}\n"
        if fact_sheet.key_facts:
            user_prompt += "핵심 사실:\n"
            for i, kf in enumerate(fact_sheet.key_facts, 1):
                user_prompt += f"  {i}. {kf}\n"
        user_prompt += "===========================\n"

        # ── 숫자 사용 허용 범위 명시 ──
        if fact_sheet.figures:
            user_prompt += (
                f"\n⚠️ 허용된 수치 목록: {', '.join(fact_sheet.figures)}\n"
                f"위 목록에 없는 수치(환율·지수·가격·비율)는 절대 생성하지 마라.\n"
            )
        else:
            user_prompt += (
                "\n⚠️ 소스에 구체 수치 없음. "
                "환율·지수·가격·비율 등 구체 숫자 사용 금지. 정성 표현만 사용하라.\n"
            )

    user_prompt += f"\nContent:\n{raw_input}\n\n"
    if language.lower() in ("en", "english", "eng"):
        user_prompt += "Generate the content pack JSON now."
    elif short_input:
        user_prompt += (
            "콘텐츠 팩 JSON을 생성하라. "
            "탐색형이다. 위 축 분리 규칙(A=어디가 움직이나/B=왜/C=뭘 봐야 하나)을 반드시 따라라. "
            "상위 주제 일반론 금지. 하위 영역·변수·신호로 내려가라. "
            "댓글은 1~2문장 질문형/반응형. 요약 반복 금지. "
            "모든 텍스트는 한국어로."
        )
    else:
        user_prompt += (
            "콘텐츠 팩 JSON을 생성하라. "
            "위 팩트 시트의 구체 수치와 주체를 반드시 포함하라. "
            "모든 텍스트는 한국어로."
        )

    # ── STEP 2: AI 생성 ──
    raw = await _call_ai(user_prompt, language=language)

    if raw:
        pack = _parse_response(raw)
        if pack and pack.is_valid():
            pack.source_url = request.source_url
            pack.source_type = request.source_type
            pack.fact_sheet_summary = (
                f"topic={fact_sheet.topic}, score={fact_sheet.data_density_score}"
            )
            logger.info(
                f"콘텐츠 팩 생성 완료: {len(pack.main_posts)} posts, "
                f"tags={pack.topic_tags}, fact_sheet={pack.fact_sheet_summary}"
            )
            _apply_guards(pack)
            _audit_numeric_safety(pack, fact_sheet)
            return pack

    logger.warning("AI 응답 파싱 실패 — Mock 팩 반환")
    pack = _mock_pack(request)
    _apply_guards(pack)
    return pack


def _apply_guards(pack: "ContentPack") -> None:
    """
    RepetitionGuard + VoiceGuard를 pack에 적용.
    실패 시 무시 (Layer 2 — style_warnings 미반영이 최악의 결과).
    """
    # VoiceGuard — DB 불필요, 항상 실행
    try:
        from app.services.voice_guard import check_pack_voices
        voice_warnings = check_pack_voices(
            pack.main_posts + [pack.short_version] + pack.reply_drafts
        )
        for w in voice_warnings:
            if w not in pack.style_warnings:
                pack.style_warnings.append(w)
    except Exception as e:
        logger.warning(f"[VoiceGuard] 실패 (무시): {e}")

    # RepetitionGuard — DB 세션 필요
    try:
        from app.db import get_db
        from app.services.repetition_guard import RepetitionGuard
        db = get_db()
        guard = RepetitionGuard(db)
        rep_warnings = guard.check_pack(pack)
        for w in rep_warnings:
            if w not in pack.style_warnings:
                pack.style_warnings.append(w)
    except Exception as e:
        logger.warning(f"[RepetitionGuard] 실패 (무시): {e}")


# ─── 숫자 안전성 감사 (post-generation) ──────────────────────────────────────

_FINANCIAL_NUM_RE = re.compile(
    r"\d+\.\d+"              # 소수점 수치 (99.085, 1493.9, 3.2)
    r"|\d{4,}[\d,]*"         # 4자리+ 숫자 (1493, 1500, 12345)
    r"|\d[\d,]*\s*[%％]"     # 퍼센트 (15%, 3.2%)
    r"|\d[\d,]*\s*[조억만]\s*원?"  # 한국 금액 (3조, 12만)
    r"|\d[\d,]*\s*원"        # 원화 (1500원)
    r"|\$\s*\d[\d,\.]*"      # 달러 ($99)
)

_STRONG_ASSERTION_RE = re.compile(
    # 경제·시장
    r"급증|급등|급락|급감|폭등|폭락|붕괴|폭증|활발"
    # 정치·외교·군사
    r"|직격|부풀렸|내밀었|공식.시행|공식.선언|선전포고"
    r"|선언했|불가피|직격탄"
)

# "확정형 + 단서" 안티패턴: 강한 확정 뒤에 미확인 단서가 오는 자기모순 구조
_CONFIRM_THEN_HEDGE_RE = re.compile(
    r"(선언했다|시행했다|공식.발표|불가피하다|확정됐다)"
    r".{0,80}"
    r"(미확인|확인.{0,3}필요|확인되지|불확실|변수가.남|미지수)",
)


def _audit_numeric_safety(
    pack: "ContentPack",
    fact_sheet: "FactSheet",
) -> None:
    """
    생성된 콘텐츠에서 소스에 없는 수치와 근거 없는 강한 단정을 탐지한다.
    탐지 결과는 pack.style_warnings에 추가.
    """
    # 소스 수치에서 핵심 숫자 추출 (비교용)
    source_nums: set[str] = set()
    for fig in fact_sheet.figures:
        for m in re.findall(r"\d+\.?\d*", re.sub(r"[,\s]", "", fig)):
            if len(m) >= 2:  # 1자리 숫자는 잡음
                source_nums.add(m)

    # 전체 생성 텍스트 수집
    all_texts = (
        pack.main_posts
        + [pack.short_version]
        + pack.reply_drafts
        + pack.quote_post_drafts
        + ([pack.thread_option] if pack.thread_option else [])
    )
    full_text = "\n".join(t for t in all_texts if t)

    # 1. 미확인 수치 탐지
    ungrounded: list[str] = []
    for match in _FINANCIAL_NUM_RE.finditer(full_text):
        num_str = match.group().strip()
        core = re.sub(r"[,\s%％원조억만달러$]", "", num_str)
        if not core or len(core) < 2:
            continue
        # 소스에 있는지 확인
        if not any(core in sn or sn in core for sn in source_nums):
            ungrounded.append(num_str)

    if ungrounded:
        unique = list(dict.fromkeys(ungrounded))[:5]
        pack.style_warnings.append(
            f"⚠️ 숫자 안전: 소스에 없는 수치 감지 — {', '.join(unique)}. "
            f"원문 확인 필요."
        )

    # 2. 강한 단정 표현 탐지
    strong_matches = _STRONG_ASSERTION_RE.findall(full_text)
    if strong_matches:
        unique_a = list(dict.fromkeys(strong_matches))[:3]
        pack.style_warnings.append(
            f"⚠️ 단정 강도: 강한 표현 감지 — {'·'.join(unique_a)}. "
            f"뒷받침 데이터 확인 필요."
        )

    # 3. "확정형 + 단서" 안티패턴 탐지
    hedge_matches = _CONFIRM_THEN_HEDGE_RE.findall(full_text)
    if hedge_matches:
        pack.style_warnings.append(
            "🚨 확정+단서 자기모순: 미확인 사안을 확정형으로 쓴 뒤 단서로 수습하는 "
            "구조 감지. 확정형을 가능성/조짐 수준으로 낮추거나, 단서를 앞으로 옮겨야 함."
        )


async def _call_ai(user_prompt: str, language: str = "ko") -> Optional[str]:
    """AI 호출. OpenAI → Anthropic → None 순서."""
    from app.config import settings

    system_prompt = _get_system_prompt(language)

    # OpenAI 시도
    if settings.openai_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.8,
                        "response_format": {"type": "json_object"},
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"OpenAI 콘텐츠 팩 호출 실패: {e}")

    # Anthropic 시도
    if settings.anthropic_api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 2000,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data["content"][0]["text"]
        except Exception as e:
            logger.warning(f"Anthropic 콘텐츠 팩 호출 실패: {e}")

    return None


def _parse_response(raw: str) -> Optional[ContentPack]:
    """AI 응답 JSON → ContentPack."""
    try:
        # JSON 블록 추출 (```json ... ``` 래핑 처리)
        text = raw.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]

        data = json.loads(text)

        return ContentPack(
            main_posts=_ensure_list(data.get("main_posts"), 3),
            short_version=str(data.get("short_version", "")),
            reply_drafts=_ensure_list(data.get("reply_drafts"), 3),
            quote_post_drafts=_ensure_list(data.get("quote_post_drafts"), 2),
            thread_option=data.get("thread_option") or None,
            risk_flags=_ensure_list(data.get("risk_flags"), None),
            topic_tags=_ensure_list(data.get("topic_tags"), None),
            why_it_matters=str(data.get("why_it_matters", "")),
            style_warnings=_ensure_list(data.get("style_warnings"), None),
        )
    except Exception as e:
        logger.warning(f"ContentPack 파싱 오류: {e}")
        return None


def _ensure_list(value, max_items: Optional[int]) -> list:
    """None / non-list → 빈 리스트. 최대 개수 제한."""
    if not isinstance(value, list):
        return []
    items = [str(v) for v in value if v]
    return items[:max_items] if max_items else items


def _mock_pack(request: ContentRequest) -> ContentPack:
    """Mock 팩 — API 키 없을 때 / 파싱 실패 시."""
    title = request.to_title()[:60]
    language = getattr(request, "language", "ko") or "ko"

    if language.lower() in ("en", "english", "eng"):
        return ContentPack(
            main_posts=[
                f"[Mock A] {title}\n\nThis is the data-driven angle for international readers.",
                f"[Mock B] {title}\n\nThis is the human-interest angle with on-the-ground context.",
                f"[Mock C] {title}\n\nThis is the contrarian angle that challenges the Western narrative.",
            ],
            short_version=f"[Mock short] {title[:80]} — the context Western media skips.",
            reply_drafts=[
                "[Mock reply 1] Worth adding: the regulatory context here is different from what most assume.",
                "[Mock reply 2] Counter-point: the data from Q3 tells a different story.",
                "[Mock reply 3] Saw this developing for months. The signal was in the bond market.",
            ],
            quote_post_drafts=[
                f"[Mock quote 1] This is why the Korea angle matters for global markets.",
                f"[Mock quote 2] The untold part: what this means for the rest of Asia.",
            ],
            thread_option="[Mock thread] 1/ Here's what everyone is missing about this story...",
            risk_flags=["Mock mode — no real risk analysis available"],
            topic_tags=["mock", "korea", "economy"],
            why_it_matters="Mock mode: international readers care because this affects regional dynamics.",
            style_warnings=[],
            source_url=request.source_url,
            source_type=request.source_type,
        )

    return ContentPack(
        main_posts=[
            f"[Mock A] {title}\n\n데이터 기반 시각으로 본 핵심 분석.",
            f"[Mock B] {title}\n\n현장 맥락을 담은 인간적 시각.",
            f"[Mock C] {title}\n\n통념에 도전하는 반론적 시각.",
        ],
        short_version=f"[Mock 짧은] {title[:80]} — 주류 미디어가 놓친 맥락.",
        reply_drafts=[
            "[Mock 답글 1] 추가할 점: 여기서 규제 맥락은 대부분의 예상과 다르다.",
            "[Mock 답글 2] 반론: 3분기 데이터는 다른 이야기를 한다.",
            "[Mock 답글 3] 수개월 전부터 전개 감지. 신호는 채권 시장에 있었다.",
        ],
        quote_post_drafts=[
            f"[Mock 인용 1] 이게 왜 글로벌 시장에 중요한지.",
            f"[Mock 인용 2] 알려지지 않은 부분: 아시아 전체에 미치는 의미.",
        ],
        thread_option="[Mock 스레드] 1/ 이 이야기에서 모두가 놓치고 있는 것...",
        risk_flags=["Mock 모드 — 실제 위험 분석 불가"],
        topic_tags=["mock", "한국", "경제"],
        why_it_matters="Mock 모드: 지역 역학에 영향을 미치기 때문에 중요.",
        style_warnings=[],
        source_url=request.source_url,
        source_type=request.source_type,
    )
