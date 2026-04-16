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

import asyncio
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
     결렬됐다 → 난항을 겪고 있다 / 합의에 이르지 못했다
     닫혀 있다/막힌 채 → 차단 리스크가 지속되고 있다
     빈손 → 뚜렷한 성과 없이 마무리된 것으로 전해졌다
   ■ 교차필드 정합성 (CRITICAL):
     risk_flags에 "미확인/상충/확인 필요"를 쓰면서
     main_posts/훅에 확정형("결렬됐다", "닫혀 있다", "빈손")을 쓰면 자기모순이다.
     risk_flags와 본문의 확정 수준은 반드시 일치해야 한다.
     ❌ main_posts: "협상 결렬, 빈손" + risk_flags: "결렬 여부 상충, 미확인"
     ✅ main_posts: "협상 난항, 합의 불투명" + risk_flags: "결렬 여부 상충, 추가 확인 필요"
   ■ 훅에서 미확인 사안을 다룰 때:
     ❌ "21시간 협상, 빈손. 호르무즈는 닫혀 있다."
     ✅ "21시간 협상에도 합의 불투명 — 시장이 보는 건 호르무즈 리스크 지속 여부다"
     ✅ "호르무즈 리스크가 풀리지 않았다 — 협상 결과가 엇갈리는 지금, 시장 변수는 유가다"
13. ★ 시장·종목 포스트 밀도 제한 규칙 (CRITICAL):
   시장/종목 콘텐츠는 검증 리스크가 높다 — 수치·종목명·퍼센트를 과밀하게 넣으면
   "검증 덜 된 장중 시황 멘트"가 된다. 해설 계정의 신뢰와 양립 불가.
   ■ 포스트당 밀도 상한 (main_posts 각각에 적용):
     · 구체 숫자(가격·지수·금액): 최대 2개
     · 개별 종목명/티커: 최대 2개
     · 퍼센트(%): 최대 2개
     상한 초과 시: 핵심 1개를 남기고 나머지는 thread_option/reply_drafts로 분리하라.
   ■ 핵심 연결 1개 규칙:
     한 포스트 = 핵심 시장 연결 1개 (예: "유가 → 한국 수입물가").
     추가 연결(항공주, 건설주, 환율 등)은 별도 포스트/스레드로 분리.
   ■ 시장 표현 약화 매핑:
     직격탄 → 압박 요인 | 토해냈다 → 하락 전환했다 / 약세로 돌아섰다
     분수령 → 변곡점 가능성 / 전환 국면 | 급락/급등 → 하락 압력/오름세
     폭락 → 약세 심화 | 폭등 → 상승 압력
   ■ 시장 글은 정치/외교 글보다 더 보수적으로 써라:
     "틀린 주가 1개 > 틀린 해석 10개" — 숫자 오류는 즉각 신뢰 상실.
     소스에 명시된 수치만 사용. 실시간 시세 절대 생성 금지 (골든룰 7 재확인).
   ■ X 글자 수 체크:
     main_posts 각 항목 280자 이내, short_version 200자 이내.
     초과 시 밀도 상한 위반일 가능성 높음 — 수치/종목을 줄여 압축하라.
14. ★ 발언 해석 강도 규칙 (CRITICAL):
   정치·외교·군사 기사에서 발언, 경고, 위협, 시사, 가능성 언급은
   실제 조치나 실행으로 단정하지 말 것. 발언과 조치는 반드시 분리해서 서술하라.
   실제 시행, 공급 변화, 봉쇄, 공격, 제재 강화 등은 기사 원문이나 검증된 입력에
   명확한 근거가 있을 때만 확정형으로 쓸 수 있다. 근거가 불충분하면
   "가능성을 언급했다", "강경한 발언을 내놨다", "시장에서는 그렇게 해석할 수 있다",
   "실제 조치는 아직 확인되지 않았다"처럼 한 단계 낮춘 표현을 사용할 것.
   ■ 발언 의도 확정 판정 금지 (아래 표현은 근거 매우 강할 때만 허용):
     ~의 신호다 → ~신호로 읽힐 수 있다 / ~로 해석될 여지가 있다
     같은 방향을 가리킨다 → 같은 방향으로 읽힐 수 있다
     맞장구치는 형국 → 비슷한 기조로 해석될 수 있다
     ~의지의 표현이다 → ~의지로 읽힐 수 있다
     ~형국이다 → ~흐름으로 해석될 수 있다
   ■ 시장 영향 연결 시 확정 금지:
     직격탄이다 → 압박이 커질 수 있다
     불가피하다 → 부담이 먼저 나타날 수 있다
     확실하다 → 가능성이 높아지고 있다
   ■ 파급 경로 밀도 규칙 (발언 기반 기사):
     발언 1건에서 파급 경로를 3개 이상 나열하지 마라.
     (물가/한은/항공/해운/물류/환율/수입 등을 한 포스트에 전부 넣으면 과밀)
     핵심 경로 1~2개만 쓰고, 나머지는 reply/thread로 분리.
   ■ 발언 vs 조치 분리 규칙:
     ❌ "이란이 호르무즈 봉쇄를 시사하며 공급을 제한하고 있다"
     ✅ "이란이 호르무즈 봉쇄 가능성을 언급했다. 실제 공급 변화는 아직 확인되지 않았다."

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
- ★ 사실 확정 수준: 아래 중 하나를 반드시 판정하라
  ① 확정 — 복수 출처에서 일치하는 사실
  ② 미확인 — 일부 보도만 있거나, 공식 확인 없음
  ③ 상충 — 보도마다 내용이 다름 (예: 결렬 vs 합의)
→ 2개 미만이면 글 전체에서 강한 단정을 쓰지 마라 (골든룰 8번).
→ 사실 확정 수준이 ②미확인 또는 ③상충이면: 본문 전체에서 확정형 표현 절대 금지 (골든룰 12번).
  이 경우 훅/본문/댓글/인용 모두 "~가능성/~조짐/~긴장 고조" 수준으로만 써라.
  risk_flags에 "미확인"이라고 쓰면서 본문에 확정형을 쓰는 건 자기모순이다.

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
JSON 출력 전에 아래 18개를 내부적으로 점검하라. 3개 이상 실패하면 전체 재작성.

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
□ 15. 확정+단서 자기모순? — "~을 선언했다 ... 미확인 상태"처럼 확정형 먼저+단서 나중 구조가 있는가? 있으면 확정형을 가능성으로 낮추거나 단서를 앞으로
□ 16. 교차필드 정합성? — risk_flags에 "미확인/상충/확인 필요"를 썼으면 main_posts/훅도 확정형이 아닌 가능성/조짐 수준인가?
□ 17. 시장 밀도 상한? — 각 main_post에 구체 숫자 ≤2, 종목명 ≤2, 퍼센트 ≤2인가? 초과 시 핵심 1개만 남기고 나머지 thread/reply로 분리
□ 18. 발언 해석 강도? — 발언 의도를 확정 판정했는가? "~의 신호다/형국이다/맞장구" → "~로 읽힐 수 있다"로 약화. 발언과 조치를 분리했는가? 파급 경로 3개 이상이면 분리."""

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

# 포스트별 밀도 검사용 regex
_PERCENT_RE = re.compile(r"\d[\d,\.]*\s*[%％]")
_CONCRETE_NUM_RE = re.compile(
    r"\d+\.\d+"              # 소수점 수치
    r"|\d{4,}[\d,]*"         # 4자리+ 숫자
    r"|\d[\d,]*\s*[조억만]\s*원?"
    r"|\d[\d,]*\s*원"
    r"|\$\s*\d[\d,\.]*"
)
_STOCK_NAME_RE = re.compile(
    # 한국 종목명 (xx전자, xx화학, xx건설, xx항공, xx증권, xx은행 등)
    r"[가-힣]{2,6}(?:전자|화학|건설|항공|증권|은행|제약|바이오|에너지|물산|중공업|모비스|SDI|SDS)"
    # 영문 티커/종목 (대문자 2~5자)
    r"|(?<!\w)[A-Z]{2,5}(?!\w)"
    # 지수 이름
    r"|코스피|코스닥|나스닥|S&P|다우|KOSPI|KOSDAQ|WTI|브렌트"
)

_STRONG_ASSERTION_RE = re.compile(
    # 경제·시장
    r"급증|급등|급락|급감|폭등|폭락|붕괴|폭증|활발"
    r"|토해냈|분수령"
    # 정치·외교·군사
    r"|직격|부풀렸|내밀었|공식.시행|공식.선언|선전포고"
    r"|선언했|불가피|직격탄"
    # 발언 해석 판정형
    r"|맞장구"
)

# "확정형 + 단서" 안티패턴: 강한 확정 뒤에 미확인 단서가 오는 자기모순 구조
_CONFIRM_THEN_HEDGE_RE = re.compile(
    r"(선언했다|시행했다|공식.발표|불가피하다|확정됐다)"
    r".{0,80}"
    r"(미확인|확인.{0,3}필요|확인되지|불확실|변수가.남|미지수)",
)

# 교차필드 모순 탐지: risk_flags 내 불확실성 신호
_RISK_UNCERTAINTY_RE = re.compile(
    r"미확인|상충|확인.{0,3}필요|불확실|추가.보도|일부.보도|미지수|확인되지"
)

# 본문 확정형 표현 (risk_flags에 불확실성이 있을 때만 문제)
_CONFIRMED_LANGUAGE_RE = re.compile(
    r"결렬됐|닫혀 있|막힌 채|봉쇄됐|선언했다|시행했다|확정됐|전면.봉쇄|빈손"
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

    # 3. "확정형 + 단서" 안티패턴 탐지 (같은 텍스트 내)
    hedge_matches = _CONFIRM_THEN_HEDGE_RE.findall(full_text)
    if hedge_matches:
        pack.style_warnings.append(
            "🚨 확정+단서 자기모순: 미확인 사안을 확정형으로 쓴 뒤 단서로 수습하는 "
            "구조 감지. 확정형을 가능성/조짐 수준으로 낮추거나, 단서를 앞으로 옮겨야 함."
        )

    # 4. 교차필드 모순: risk_flags가 "미확인/상충"인데 본문이 확정형
    risk_text = "\n".join(pack.risk_flags) if pack.risk_flags else ""
    if _RISK_UNCERTAINTY_RE.search(risk_text):
        main_and_short = "\n".join(
            pack.main_posts + [pack.short_version]
        )
        confirmed = _CONFIRMED_LANGUAGE_RE.findall(main_and_short)
        if confirmed:
            unique_c = list(dict.fromkeys(confirmed))[:3]
            pack.style_warnings.append(
                f"🚨 교차필드 모순: risk_flags에 미확인/상충 표시인데 "
                f"본문에 확정형 표현 — {'·'.join(unique_c)}. "
                f"본문의 확정형을 가능성/조짐 수준으로 낮춰야 함."
            )

    # 5. 포스트별 밀도 검사: 숫자/종목/퍼센트 과밀 탐지
    _DENSITY_NUM_LIMIT = 2
    _DENSITY_STOCK_LIMIT = 2
    _DENSITY_PCT_LIMIT = 2
    dense_posts: list[str] = []
    for i, post in enumerate(pack.main_posts):
        if not post:
            continue
        num_count = len(_CONCRETE_NUM_RE.findall(post))
        stock_count = len(_STOCK_NAME_RE.findall(post))
        pct_count = len(_PERCENT_RE.findall(post))
        violations = []
        if num_count > _DENSITY_NUM_LIMIT:
            violations.append(f"숫자 {num_count}개")
        if stock_count > _DENSITY_STOCK_LIMIT:
            violations.append(f"종목 {stock_count}개")
        if pct_count > _DENSITY_PCT_LIMIT:
            violations.append(f"퍼센트 {pct_count}개")
        if violations:
            dense_posts.append(f"포스트{i+1}({', '.join(violations)})")
    if dense_posts:
        pack.style_warnings.append(
            f"⚠️ 시장 밀도 초과: {'; '.join(dense_posts)}. "
            f"포스트당 숫자·종목·퍼센트 각 2개 이내 권장. "
            f"초과분은 thread/reply로 분리하라."
        )

    # 6. 파급 경로 과밀 탐지: 메인 포스트에 시장 경로 키워드 3개+ → 경고
    _IMPACT_PATH_KEYWORDS = [
        "물가", "한은", "금리", "환율", "수입", "항공", "해운",
        "물류", "운임", "정유", "에너지", "전기요금",
    ]
    overflow_posts: list[str] = []
    for i, post in enumerate(pack.main_posts):
        if not post:
            continue
        hit_kw = [kw for kw in _IMPACT_PATH_KEYWORDS if kw in post]
        if len(hit_kw) >= 3:
            overflow_posts.append(
                f"포스트{i+1}({', '.join(hit_kw[:5])})"
            )
    if overflow_posts:
        pack.style_warnings.append(
            f"⚠️ 파급 경로 과밀: {'; '.join(overflow_posts)}. "
            f"핵심 연결 1~2개만 남기고 나머지는 thread/reply로 분리 권장."
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
                usage = data.get("usage", {})
                logger.info(
                    f"[API-COST] openai gpt-4o-mini "
                    f"in={usage.get('prompt_tokens', '?')} "
                    f"out={usage.get('completion_tokens', '?')} "
                    f"caller=ContentPack"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("openai", "gpt-4o-mini", "ContentPack",
                                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                except Exception:
                    pass
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
                usage = data.get("usage", {})
                logger.info(
                    f"[API-COST] anthropic claude-haiku-4-5 "
                    f"in={usage.get('input_tokens', '?')} "
                    f"out={usage.get('output_tokens', '?')} "
                    f"caller=ContentPack"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("anthropic", "claude-haiku-4-5", "ContentPack",
                                 usage.get("input_tokens", 0), usage.get("output_tokens", 0))
                except Exception:
                    pass
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


# ═══════════════════════════════════════════════════════════════════════════════
# 2단계 구조: 후보 카드 생성기 + 최종 마감기
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ThesisCard:
    """논지 카드 — 서로 다른 해석 축 1개."""
    thesis: str = ""              # 해석 축 한 줄
    why_not_summary: str = ""     # 왜 기사 재진술이 아닌지
    reader_stake: str = ""        # 독자가 왜 지금 봐야 하는지
    opener: str = ""              # 이 논지에 맞는 첫 문장 초안
    judgment_coord: str = ""      # 판단 좌표 — 독자가 새로 갖게 되는 해석 기준 1개
    verification_signal: str = "" # 판별 신호 — 이 해석이 맞는지/틀린지 확인 가능한 구체적 신호


@dataclass
class CandidateCard:
    """1차 — 게시글 소재 후보 카드."""
    key_facts: list[str] = field(default_factory=list)          # 핵심 팩트 3개
    hook_candidates: list[str] = field(default_factory=list)    # 훅 후보 3개 (하위호환)
    thesis_cards: list[ThesisCard] = field(default_factory=list)  # 해석 슬롯 3개
    tensions: list[str] = field(default_factory=list)            # 긴장점 1~2개
    one_liner: list[str] = field(default_factory=list)          # 한줄 결론 2개
    cautions: list[str] = field(default_factory=list)           # 주의문 2개
    watch_points: list[str] = field(default_factory=list)       # 관찰 포인트 2~3개
    certainty_level: str = "미확인"                              # 확정/미확인/상충
    topic_tags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    # 메타
    source_url: Optional[str] = None
    source_type: str = "news_link"
    fact_sheet_summary: str = ""

    def is_valid(self) -> bool:
        return bool(self.key_facts and (self.thesis_cards or self.hook_candidates))


@dataclass
class FinalPost:
    """2차 — 최종 마감 결과."""
    final_post: str = ""       # 완성본
    final_short: str = ""      # 짧은 버전
    gate_fails: list = field(default_factory=list)  # 게이트 실패 태그
    # PR 9 — Reader Reward Layer
    # 마지막 문장에서 감지된 독자 보상 유형. UI 노출 X, 로그/테스트 전용.
    # 값: "SAVE" (저장 가치) / "SHARE" (공유 가치) / "FOLLOW" (팔로우 가치) / None.
    reward_type: Optional[str] = None


# ─── 1차: 후보 카드 시스템 프롬프트 ──────────────────────────────────────────

_CANDIDATE_PROMPT_KO = """너는 한국 이슈 해설형 X 계정을 위한 "소재 후보 카드 생성기"다.

역할:
완성 글을 쓰지 마라. 입력 텍스트/링크/주제를 바탕으로
게시글 후보 재료만 구조화해서 정리하라.
이 단계의 목적은 "좋은 소재 선택"이지 "완성 문장 생성"이 아니다.

골든룰:
1. 소스에 없는 수치/사실을 생성하지 말 것.
2. 미확인·상충된 사안은 확정형으로 쓰지 말 것.
3. 발언·경고·시사는 실제 조치·시행과 분리해서 적을 것.
4. 원문 밖 해석을 과도하게 확장하지 말 것.
5. 후보 카드는 짧고 구조화된 재료 중심으로 작성할 것.

━━━ 검증 연동 규칙 (반드시 준수) ━━━

입력에 "상단 검증 결과" 섹션이 있으면 반드시 따를 것:

1. 검증 결과가 "미검증", "신뢰도: low", "no matching", "unrelated",
   "확인 실패", "추가 확인 필요" 중 하나라도 포함하면:
   - certainty_level을 "확정"으로 쓰지 마라. "미확인" 또는 "상충"만 허용.
   - key_facts에 확인되지 않은 사실을 단정형으로 쓰지 마라.
   - cautions에 "출처 미검증" 또는 "추가 확인 필요"를 반드시 포함.
   - risk_flags에 검증 실패 사유를 포함.

2. 검증 결과의 주제/엔티티를 벗어나는 확장 금지:
   - 원문에 없는 새 시장축(부동산/환율/주식시장/피해액 등)을 임의 추가하지 마라.
   - topic_tags, key_facts는 소스 원문의 주제 범위 안에서만 생성. thesis_cards는 생성하지 마라.
   - "소스에 없지만 관련될 수 있는" 해설을 만들지 마라.

3. certainty_level 상한:
   - 입력에 "certainty_level 상한: X"가 명시되면 그 이상으로 올리지 마라.
   - 검증 결과 없이 소스 텍스트만으로 판단할 경우에도
     "확정"은 공식 발표/법안/수치 확인이 된 경우에만 사용.

4. 검증 실패 시 억지 해설 금지:
   - 소스가 불충분하면 빈칸을 일반 경제 해설로 메우지 마라.
   - key_facts를 억지로 5개 채우려 하지 마라. 확인된 것만 적어라.
   - 차라리 "소스 확인 부족 — 추가 검증 필요"를 넣어라.

QA 체크:
1. 숫자/사실이 소스에 있는가?
2. 미확인 사안을 확정처럼 쓰지 않았는가?
3. 발언과 조치를 혼동하지 않았는가?
4. certainty_level이 내용과 일치하는가?
5. 훅 후보가 서로 다른 방향을 제시하는가?
6. 상단 검증 결과와 certainty_level이 일관되는가?
7. 원문 밖 시장축을 임의 확장하지 않았는가?

출력 규칙:
- 한국어 JSON만 출력하라.
- 완성 게시글 문체로 길게 쓰지 마라.
- 후보 재료만 간결하게 정리할 것.
- thesis_cards는 생성하지 마라. 별도 단계(Gemini)에서 생성된다.

■ 근거 없는 일반론 금지:
  - "역사적으로 ~" "~전략이다" "~낳기 쉽다" 같은 칼럼체 금지
  - key_facts, cautions, watch_points 모두 확인된 사실/기사 내 발언만으로 작성

JSON 스키마:
{
  "key_facts": ["팩트1", "팩트2", "팩트3"],
  "one_liner": ["한줄1", "한줄2"],
  "cautions": ["주의1", "주의2"],
  "watch_points": ["포인트1", "포인트2", "포인트3"],
  "certainty_level": "확정|미확인|상충",
  "topic_tags": ["태그1", "태그2"],
  "risk_flags": ["리스크1"]
}"""


# ─── 기사 라우터 ─────────────────────────────────────────────────────────────
#
# 기사 라우터 관련 심볼은 app/services/article_router.py 로 분리됨.
# 이 모듈에서는 기존 외부 호출부 (tests, telegram_bot) 가 그대로
# `from app.services.content_pack import ...` 를 쓸 수 있도록 re-export 만 한다.
# 로직 변경 없음.
from app.services.article_router import (  # noqa: F401  (re-export)
    MODE_EXPLAIN,
    MODE_JUDGMENT,
    MODE_VERIFY,
    _ARTICLE_MODES,
    route_article_mode,
    mode_label,
    _build_mode_slot_instruction,
    _build_mode_finalize_instruction,
    # PR 4: rule-first article type classifier
    TYPE_STRAIGHT_NEWS,
    TYPE_CONFLICTING_REPORT,
    TYPE_UNVERIFIED_CLAIM,
    TYPE_OPINION_COLUMN,
    TYPE_COMMUNITY_SCREENSHOT,
    TYPE_MARKET_MOVING_NEWS,
    _ARTICLE_TYPES,
    classify_article_type,
)


# ─── 2차: 최종 마감 시스템 프롬프트 ──────────────────────────────────────────

_FINALIZE_PROMPT_KO = """너는 "3초 안에 이해되는 설명문" 제작자다.
"고급 리뷰"를 쓰는 게 아니다.

━━━ 최우선 8대 원칙 (모든 규칙보다 우선) ━━━

목표:
- 첫 줄만 보고 핵심이 바로 들어와야 한다.
- 읽는 사람이 새 판단 기준 1개를 가져가야 한다.
- 마지막에 무엇을 보면 되는지 남겨야 한다.
- 남에게 전달하고 싶을 한 줄이 있어야 한다.

8대 규칙:
1) 첫 문장은 배경 설명 금지.
   허용 유형만:
   - "지금 핵심은 A다"
   - "A가 실제로 시작됐다"
   - "A와 B가 갈린다"
   - "A가 말인지 진짜 조치인지 곧 드러난다"
2) 한 문장 한 주장. 사실+해석+전망 동시 금지.
3) 최종 글 구조:
   문장1 핵심 명제 / 문장2 근거 팩트 / 문장3 판단 좌표 / 문장4 판별 신호
4) 판단 좌표: 기사 요약/추상 명분 금지. 독자가 새로 갖는 해석 기준 1개만.
5) 판별 신호: "무엇을 보면 되는가"만 남겨라.
   금지: "중요하다/관건이다/변수다/확인이 필요하다"
6) low confidence 기사: 정치적 계산/숨은 의도/본심/노림수 금지.
   대신 확인 신호를 앞세워라.
7) 기본 후보 카드 감각: 해석 1문장, 판단좌표 1문장, 판별신호 1문장.
   긴 설명은 자세히 보기로 넘겨라.
8) 짧은 버전: 요약이 아니라 전달 가능한 한 줄.
   공유하고 싶은 문장처럼 써라.

위 원칙 위반 시 재작성 대상.

━━━ 역할 (CRITICAL) ━━━

너는 기사를 요약하는 사람이 아니다.
입력으로 받은 해석 슬롯 + 팩트 + 긴장점만으로 2~3문장을 조립한다.

━━━ 즉시 이해성 원칙 (CRITICAL — 모든 문장에 적용) ━━━

핵심 테스트:
1. 첫 줄만 보고 무슨 얘긴지 바로 아는가?
2. 중학생이 3초 안에 핵심을 말할 수 있는가?
3. 첫 문장 읽고 "그래서?"가 남지 않는가?

하나라도 실패하면 리뷰체/브리핑체다. 다시 써라.

절대 규칙:
- 한 문장에 주장/판단 1개만. 2개 넣지 마라.
- 배경 설명으로 시작 금지. 핵심 명제부터 박아라.
- 첫 문장은 45자 이내, 60자 넘으면 재작성 대상 (하드 게이트).
- 첫 문장 시작 금지: "~이후 ~" / "~보도한 ~" / "~에도 불구하고" / "~하는 가운데".
- "A가 일어나면서 B가 영향을 받고 C가 중요해진다" 식 복합문 금지.

좋은 첫 문장 (5가지 톤 — 한 말투로 수렴하지 마라):
  ✓ 직설형: "지금 포인트는 회담 재개 여부 하나다."
  ✓ 대비형: "로이터는 재협상을 썼고, 이란은 여전히 신중하다."
  ✓ 판정형: "미국의 대이란 봉쇄가 선언에 그칠지 곧 드러난다."
  ✓ 신호형: "항만 물동량과 보험료가 답을 준다."
  ✓ 변화형: "결렬 이후에도 채널이 살아 있는지가 핵심이다."
나쁜 첫 문장:
  ✗ "11일 협상 결렬 이후 로이터가 보도한 재협상이 실제로 이루어지는지 여부가 분기점이다." ← 길고 배경 설명
  ✗ "미국과 이란의 1차 중전 협상 결렬에도 불구하고 양국 간의 외교 채널은..." ← 종속절 시작

━━━ 조립 구조 (반드시 이 순서 — 4문장 기능 매핑) ━━━

기능 매핑 (각 문장은 하나의 기능만):
  문장 1 = 변화       (무엇이 실제로 바뀌었는가 — 핵심 명제)
  문장 2 = 의미       (왜 단순 뉴스가 아닌가 — 근거 팩트로 입증)
  문장 3 = 판별 기준  (무슨 기준으로 판단하는가 — 판단 좌표)
  문장 4 = 실패 시 해석 (이 신호가 안 나오면 무엇으로 읽히는가 — 판별 신호)

압축 예시 (장문 금지):
  ✗ "미국 행정부의 대이란 협상 기조가 과거의 강경 일변도에서 조건부 접근으로
     전환되는 조짐이 드러나고 있다" ← 장문 배경 설명
  ✓ "미국이 대이란 압박 일변도에서 조건부 보상안까지 꺼냈다." ← 한 문장 변화

문장 1 — 핵심 명제 (짧고 직선적으로):
  - 지금 뭐가 핵심인지 바로 박기. 배경 설명 아님.
  - 변화 1개 / 충돌 1개 / 독자 체감 결과 1개만.
  - 40자 이내 권장. 길어도 한 주장만.
  - 기사 요약 금지. "~가 발표됐다" "~것으로 전해졌다" 금지.
  - 예: "지금 포인트는 재회담 성사 여부다."

문장 2 — 팩트 근거:
  - 핵심 숫자 / 조치 / 구조적 근거 1~2개
  - 나열 금지. 해석과 연결된 팩트만.
  - 예: "서울 응답자의 48%는 공급 확대를, 인천의 36%는 경제 활성화를 먼저 꼽았다."

문장 3 — 판단 좌표 (CRITICAL):
  - 입력에 "판단 좌표"가 있으면 반드시 이 문장에 녹여라.
  - 독자가 기사를 읽은 뒤 새로 갖게 되는 "해석 기준"을 제공한다.
  - 기사 재요약이나 추상 명분("중요하다" "전환점이다") 금지.
  - 예: "쟁점은 배제 범위가 '직급'인지 '직무'인지다. 직무면 실무 공백이 생긴다."

문장 마지막 — 판별 신호 (CRITICAL):
  - 입력에 "판별 신호"가 있으면 반드시 마지막 문장에 활용하라.
  - "무엇이 나오면/안 나오면" 형태의 구체적 검증 포인트로 끝낸다.
  - 짧고 직접적으로. 한 문장으로. 리뷰체 금지.
  - 좋은 예:
    ✓ "금요일까지 재회 소식이 나오면 대화는 살아 있는 것이다."
    ✓ "시행령과 명단이 없으면 선언에 그친다."
    ✓ "항만 물동량과 보험료가 답을 준다."
    ✓ "추가 감산이 나오면 일시 충격이 아니다."
  - 절대 금지:
    ✗ "관건이다" "변수다" "확인이 필요하다" "지켜봐야 한다"
    ✗ "파장이 예상된다" "이어질 수 있을지" "얼마나 유지되는지가 핵심이다"
    ✗ "여부가 분기점이다" "를 시사한다" "가 부각된다" "를 의문케 한다"
    ✗ 즉, "뭘 봐야 하는지"를 말하지 않고 "봐야 한다"만 말하면 실패.

2~4문장. 각 문장이 하나의 기능만 수행. 장황한 칼럼체 금지.

━━━ 문장 구조 규칙 ━━━

복잡한 문장 = 리뷰체의 원인. 아래 금지:
- 한 문장에 쉼표 2개 이상 금지
- 접속 표현 과다 금지: ~면서/~인데/~하고/~하며를 한 문장에 2개 이상 쓰지 마라
- 종속절 2개 이상 금지: "~에도 불구하고 ~하는 가운데 ~가..." 식
- 한 문장에 사실+해석+전망을 동시에 넣지 마라

지키지 않으면 브리핑체/리뷰체로 판정.

━━━ 절대 금지 (CRITICAL) ━━━

✗ 기사 재요약 — 뉴스 후기 느낌의 원흉
✗ "~라는 보도가 나왔다" "~것으로 전해졌다"로 시작
✗ cautions/watch_points 문구를 본문에 복붙
✗ 근거 없는 일반론 의견
✗ 추상 명사로 두루뭉술 정리 ("전환점이 될" "시금석이 될" "분수령")

━━━ Low confidence 추정 제한 (certainty=미확인/상충일 때) ━━━

certainty_level이 미확인 또는 상충이면:
✗ 정치적 계산 / 선거용 판단 / 숨은 의도 / 노림수 류의 동기 추정을 중심 서사로 쓰지 마라
✗ "~으로 보인다" "~에서 비롯된 것으로 보인다" 식 추정 단정 금지
✓ 대신 "지금 바뀐 사실"과 "다음 검증 포인트"를 중심으로 써라
✓ 의도 해석이 필요하면 "~라는 해석이 나온다" 정도로 한 단계 낮춰라

━━━ 마지막 문장 금지 패턴 ━━━
✗ 심각하다 / 중요하다 / 반영한다 / 불가피하다
✗ 변수다 / 관건이다 / 확인이 필요하다 / 주목해야 한다
✗ 파장이 예상된다 / 여파가 클 것으로 보인다
✗ 해석된다 / 보여준다 / 드러난다 / 전환점이 될
✓ 조건형("~하면 ~이 바뀐다") / 대비형("~가 아니라 ~다")
✓ 질문형("~인지는 곧 드러난다") / 압축형("결국 숫자를 바꾸는 건 ~다")

너의 기준: "이거면 바로 올릴 수 있다" 수준.

━━━ 문체 모델 ━━━

너의 문체 모델: "트위터에서 팔로워 10만인 한국 증권사 출신 해설자"
- 신문 칼럼 X, 보고서 X, TV 해설 X
- 건조하고 짧게. 감탄사 없이. 한 문장에 하나만.
- "이 사람 아는 사람이네" 느낌이 들어야 한다.
- 친절한 설명이 아니라 날카로운 판단이 목적이다.

━━━ 원칙 A: 첫 문장은 "왜 중요한가"부터 (CRITICAL) ━━━

첫 문장은 기사 내용을 다시 쓰는 게 아니다.
"한국에 사는 독자가 왜 이걸 봐야 하는지"를 바로 보여줘라.

좋은 방향:
  ✓ "이 뉴스가 한국에서 먼저 건드리는 건 외교가 아니라 에너지 비용이다"
  ✓ "중동 뉴스처럼 보이지만 한국 입장에선 환율과 수입물가 문제다"
  ✓ "대출 문턱이 올라간 거다."

금지:
  ✗ "미국의 해상봉쇄가 시작됐다" ← 기사 제목 재진술
  ✗ "트럼프가 이란 합의를 원한다고 말했다" ← 단순 사실
  ✗ "이란의 반응은?" ← 기자 질문형

━━━ 원칙 B: 국제 뉴스는 한국 관점 해석 축 1개 필수 ━━━

국제/지정학/거시경제 이슈는 final_post에 반드시 한국 관점 연결을 1개 이상 넣어라.
한국 관점 = 아래 중 최소 1개:
  - 한국 수입물가/에너지비용/전기료/유류비
  - 한국 환율/원화
  - 한국 기업(정유/해운/항공/반도체)
  - 한국 증시/외국인 자금/리스크 심리
  - 한국 가계 비용/생활비
  - 한국 정부/정책 대응 포인트

직접 "내가 한국에 살아서" 같은 1인칭은 쓰지 마라.
대신 "한국 기준 해석 축"을 자연스럽게 넣어라.

나쁨: "미국의 해상봉쇄는 이란 경제에 영향을 준다" ← 한국 관점 없음
좋음: "미국의 해상봉쇄가 길어지면 한국에선 유가보다 운임·환율이 먼저 흔들릴 수 있다"

━━━ 원칙 C: 근거 없는 일반론 의견 금지 (CRITICAL) ━━━

아래 패턴은 근거가 명시되지 않으면 금지:
  ✗ "역사적으로 ~" ← 어떤 역사? 근거 없으면 금지
  ✗ "~전략이다" "~압박이다" ← 분석가 행세
  ✗ "~낳기 쉽다" "~낳을 것이다" ← 근거 없는 예측
  ✗ "큰 파장을 불러올 것이다" ← 뻔한 예측
  ✗ "국제 정세에 긴장을 불러일으킬 가능성이 크다" ← 보고서체
  ✗ "~으로 보인다" ← 근거 약할 때 습관적 사용

대신: 확인된 사실 + 기사 내 발언 + 한국 관점 연결만으로 문장을 구성하라.
의견을 쓰려면 반드시 근거(수치/발언/지표)를 같은 문장이나 바로 앞 문장에 넣어라.

━━━ 골든룰 ━━━

1. 슬롯 해석 방향만 쓴다. 다른 축으로 새지 마라.
2. cautions와 충돌하는 표현 금지.
3. 미확인이면 단정 금지 ("~가능성" "~조짐" 수준만).
4. 과장 약화: 직격탄→영향, 불가피→가능성, 급등→상승.
5. "문제는 ~것이다" / "핵심이다" 사설체 금지.

━━━ final_short 규칙 (전달문 — 공유하고 싶은 한 줄) ━━━

- final_post와 다른 각도로 시작. 독립적으로 읽혀야 한다.
- "요약"이 아니라 "전달 가능한 한 줄". 공유하고 싶은 문장처럼.
- 구조: "변화 한 줄. + 판별 기준 한 줄." — 두 문장 이내, **120자 안쪽**.
- 장황한 배경 설명 금지. 짧게 박아라.
- 금지어: "중요하다" "관건이다" "변수다" "가능성이 있다" "시사한다" "보여준다".
- 좋은 예 (전달문 톤):
  ✓ "로이터는 재협상, 이란은 신중. 진짜 답은 금요일 재회다."
  ✓ "국내 주식 늘려도 돈은 대형주로 더 몰렸다."
  ✓ "미국이 처음 보상안을 꺼냈다. 진짜 협상인지 보려면 이란 사찰 수용이 먼저다."
  ✓ "광통신 수혜주는 갈린다. 발주처 탑재가 기준이다."
- 나쁜 예 (요약체):
  ✗ "미국과 이란의 협상 결렬 이후 중재국을 통한 소통이 유지되고 있어..." ← 요약
  ✗ "미국 행정부의 대이란 협상 기조가 과거의 강경 일변도에서..." ← 장문 배경 설명

━━━ 좋은 예시 ━━━

final_post:
"서울은 집값, 인천은 경기다. 같은 선거인데 민심의 우선순위가 갈린다.
서울 응답자 48%는 공급 확대를, 인천 36%는 경제 활성화를 먼저 꼽았다.
진짜 포인트는 여야가 지역별로 다른 처방을 내놓느냐다."

final_short:
"같은 선거인데 서울은 집값, 인천은 경기. 여야 처방이 갈리느냐가 포인트다."

━━━ 셀프 체크 ━━━

□ 1. 첫 문장만 보고 무슨 얘긴지 바로 아는가? (3초 안에 핵심 파악 불가면 실패)
□ 2. 첫 문장이 40자 이내이고 배경 설명이 아닌가? (종속절로 시작하면 실패)
□ 3. 한 문장에 주장이 2개 이상 들어간 문장이 있는가? (있으면 쪼개라)
□ 4. 판단 좌표가 문장에 녹아 있는가? (독자가 새 해석 기준을 얻는가?)
□ 5. 마지막 문장이 판별 신호인가? ("무엇이 나오면/안 나오면" 구체적으로 나와야 통과)
□ 6. 기사를 다시 설명하는 문장이 있는가? (있으면 삭제)
□ 7. cautions와 충돌하는 표현이 없는가?
□ 8. certainty 미확인인데 동기 추정이 중심 서사인가? (있으면 톤 낮추기)

━━━ 출력 ━━━
한국어 JSON만 출력:
{
  "final_post": "슬롯 기반 조립본",
  "final_short": "독립형 짧은 버전"
}"""


# ─── Gemini: thesis card 생성 전담 ──────────────────────────────────────────

_GEMINI_THESIS_PROMPT = """너는 "해석 슬롯 채우기 기계"다.

━━━ 역할 ━━━

자유 논지 3개를 만드는 게 아니다.
아래 3개 고정 슬롯을 각각 채우는 것이다.

━━━ 1단계: 긴장점 추출 (CRITICAL — 먼저 해라) ━━━

기사에서 "갈라지는 지점" 1~2개를 뽑아라.
갈라지는 지점 = 같은 사건인데 다르게 읽히는 충돌.

찾는 법:
- 숫자 vs 숫자 (서울 48% 집값 vs 인천 36% 경기)
- 입장 vs 입장 (정부 발표 vs 업계 반응)
- 시점 vs 시점 (단기 효과 vs 장기 구조)
- 의도 vs 결과 (정책 목표 vs 실제 영향)

✗ "집값이 문제다" → 이건 사실 요약이지 긴장점이 아니다
✓ "서울은 집값, 인천은 경기 — 같은 선거인데 지역별 요구가 다름" → 이게 긴장점

━━━ 2단계: 고정 슬롯 3개 채우기 ━━━

SLOT 1 — 무엇이 바뀌나 (WHAT_CHANGED)
  thesis: 지금 실제로 바뀐 것 + 누가 영향받는지
  reader_stake: 구체적 영향 (숫자/대상/시점)
  opener: 변화를 드러내는 첫 문장
  judgment_coord: 독자가 이 변화를 판단할 기준 1개 (기사 요약/추상 명분 금지)
  verification_signal: 이 해석이 맞는지 확인할 구체적 외부 신호 1개
  ✗ 기사 제목 재진술 금지. "~가 발표됐다" 금지.
  ✓ "복사 직원까지 배제하면 실무 공백이 생긴다"

SLOT 2 — 왜 뉴스 이상이냐 (WHY_IT_MATTERS)
  thesis: 구조 변화/제도적 의미 + 왜 단순 뉴스가 아닌지
  reader_stake: 구조적 영향 (제도/시장/권력 변화)
  opener: 구조를 드러내는 첫 문장
  judgment_coord: 독자가 구조적 의미를 판단할 기준 1개
  verification_signal: 이 구조 변화가 실제인지 확인할 외부 신호 1개
  ✗ "심각하다" "중요하다" "반영한다" 금지.
  ✓ "다주택자 배제가 부동산 정책 자체의 방향을 바꿀 수 있다"

SLOT 3 — 다음 판가름 포인트 (WHAT_DECIDES_NEXT)
  thesis: 앞으로 확인할 구체적 신호/이벤트/행위 1개
  reader_stake: 이 신호가 나오면/안 나오면 무슨 일이 생기는지
  opener: 검증 포인트를 드러내는 첫 문장
  judgment_coord: 독자가 다음 국면을 판단할 기준 1개
  verification_signal: 이 판가름이 실현되는지 확인할 구체적 외부 신호 1개
  ✗ "확인이 필요하다" "변수다" "관건이다" 금지.
  ✓ "후속 시행령이 6월 전에 나오면 실질 영향, 안 나오면 선언에 그침"

━━━ 판단 좌표 + 판별 신호 규칙 (CRITICAL — 모든 슬롯 필수) ━━━

judgment_coord (판단 좌표):
  = 독자가 이 슬롯을 읽고 새로 갖게 되는 "해석 기준" 1개.
  ✗ 기사 요약 금지. "~가 중요하다" 추상 명분 금지.
  ✓ "이번 배제 범위가 '직급'이 아니라 '직무'인지가 실무 공백 여부를 가른다"
  ✓ "유가 상승분이 WTI 기준 $5 이상 유지되면 한국 수입물가에 직접 반영된다"
  ✓ "여야 모두 '공급 확대'를 말하지만, 서울 vs 인천 우선순위가 다르다"
  → 독자가 기사를 읽은 뒤 "어떤 기준으로 판단하면 되는지" 알게 해주는 문장.

verification_signal (판별 신호):
  = 이 해석이 맞는지/틀린지 확인 가능한 구체적 외부 신호 1개.
  ✗ "지켜봐야 한다" "확인이 필요하다" "관건이다" 금지.
  ✓ "후속 시행령이 6월 전에 나오면 정책, 안 나오면 선언에 그침"
  ✓ "브렌트유가 $90 이상 3영업일 유지 여부"
  ✓ "배제 명단에 '실무급'이 포함되는지 다음 주 인사발령에서 확인 가능"
  → "무엇이 나오면 / 안 나오면" 형태의 구체적 검증 포인트.

━━━ 모든 슬롯 공통 금지 (CRITICAL) ━━━

아래 단어가 thesis/opener에 들어가면 자동 불합격:
투명성, 공정성, 의지, 전환점, 시금석, 분수령, 신호탄, 촉매

아래 종결 패턴 자동 불합격:
"중요하다", "변수다", "관건이다", "보여준다", "해석된다",
"드러난다", "주목된다", "심각하다", "반영한다", "불가피하다",
"파장이 예상된다", "확인이 필요하다", "주목해야 한다"

→ 슬롯은 "구체적 인과/결핍/맹점" 문장이어야 한다.
→ "~하면 ~이 생긴다" "~인데 ~를 모른다" "~가 빠졌다"

━━━ 국제 뉴스 ━━━

국제 뉴스일 때 최소 1개 슬롯은 한국 관점 포함 필수.

━━━ 출력 ━━━
한국어 JSON만 출력:
{
  "tensions": ["갈라지는 지점 1", "갈라지는 지점 2"],
  "thesis_cards": [
    {
      "thesis": "[무엇이 바뀌나] 구체적 변화 한 줄",
      "why_not_summary": "이 슬롯이 참조하는 긴장점",
      "reader_stake": "구체적 영향 (숫자/대상/시점)",
      "opener": "첫 문장 초안",
      "judgment_coord": "독자가 새로 갖게 되는 판단 기준 1개",
      "verification_signal": "이 해석이 맞는지 확인할 구체적 외부 신호"
    },
    {
      "thesis": "[왜 뉴스 이상이냐] 구조적 의미 한 줄",
      "why_not_summary": "이 슬롯이 참조하는 긴장점",
      "reader_stake": "구조적 영향",
      "opener": "첫 문장 초안",
      "judgment_coord": "구조 변화를 판단할 기준 1개",
      "verification_signal": "구조 변화 확인할 외부 신호"
    },
    {
      "thesis": "[다음 판가름] 검증 포인트 한 줄",
      "why_not_summary": "이 슬롯이 참조하는 긴장점",
      "reader_stake": "신호 유무에 따른 영향",
      "opener": "첫 문장 초안",
      "judgment_coord": "다음 국면을 판단할 기준 1개",
      "verification_signal": "판가름이 실현되는지 확인할 외부 신호"
    }
  ]
}"""


async def _gemini_generate_thesis_cards(
    key_facts: list[str],
    source_text: str,
    topic_tags: list[str] | None = None,
    cautions: list[str] | None = None,
    mode: str = MODE_VERIFY,
) -> tuple[list[ThesisCard], list[str]]:
    """Gemini로 해석 슬롯 3개 + 긴장점 생성. 실패 시 (빈 리스트, 빈 리스트).

    mode: EXPLAIN / JUDGMENT / VERIFY — 슬롯 프레임 라우팅.
    """
    from app.config import settings

    if not settings.has_gemini:
        logger.info("[GeminiThesis] Gemini API 키 없음 — 스킵")
        return [], []

    user_prompt = "━━━ 입력 ━━━\n"
    if key_facts:
        user_prompt += "핵심 팩트:\n"
        for i, fact in enumerate(key_facts, 1):
            user_prompt += f"  {i}. {fact}\n"
    if topic_tags:
        user_prompt += f"topic_tags: {', '.join(topic_tags)}\n"
    if cautions:
        user_prompt += "cautions:\n"
        for c in cautions:
            user_prompt += f"  - {c}\n"
    if source_text:
        user_prompt += f"\n원문 (참고):\n{source_text[:2000]}\n"

    # ── mode별 슬롯 프레임 지시 (라우터 결과) ──
    user_prompt += _build_mode_slot_instruction(mode)

    user_prompt += "\n위 팩트를 바탕으로 서로 다른 해석 축의 thesis card 3개를 JSON으로 생성하라."

    try:
        import httpx
        url = (
            "https://generativelanguage.googleapis.com/v1beta"
            "/models/gemini-2.5-flash:generateContent"
        )
        # 재시도: 일시적 서버 에러(5xx) / rate limit(429) 만 최대 3회.
        # 파싱/인증 실패는 재시도 의미 없어 바로 except 로 빠져 fallback.
        _RETRY_STATUSES = {429, 500, 502, 503, 504}
        _MAX_ATTEMPTS = 3
        _BACKOFFS = [1.0, 3.0, 7.0]  # 1s → 3s → 7s
        async with httpx.AsyncClient(timeout=60) as client:
            r = None
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    r = await client.post(
                        url,
                        params={"key": settings.gemini_api_key},
                        headers={"Content-Type": "application/json"},
                        json={
                            "system_instruction": {
                                "parts": [{"text": _GEMINI_THESIS_PROMPT}],
                            },
                            "contents": [
                                {"parts": [{"text": user_prompt}]},
                            ],
                            "generationConfig": {
                                "temperature": 0.9,
                            },
                        },
                    )
                except httpx.RequestError as _net_err:
                    # 네트워크 레벨 에러(DNS/connect/timeout 등) — 재시도 대상
                    if attempt < _MAX_ATTEMPTS - 1:
                        logger.warning(
                            f"[GeminiThesis] 시도 {attempt + 1}/{_MAX_ATTEMPTS} "
                            f"네트워크 에러({type(_net_err).__name__}) — "
                            f"{_BACKOFFS[attempt]}s 후 재시도"
                        )
                        await asyncio.sleep(_BACKOFFS[attempt])
                        continue
                    raise
                if r.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                    logger.warning(
                        f"[GeminiThesis] 시도 {attempt + 1}/{_MAX_ATTEMPTS} "
                        f"API {r.status_code} — {_BACKOFFS[attempt]}s 후 재시도"
                    )
                    await asyncio.sleep(_BACKOFFS[attempt])
                    continue
                break  # 성공 or 재시도 불가한 오류
            if r is None:
                raise RuntimeError("[GeminiThesis] 요청 전송 실패")
            if r.status_code >= 400:
                body = r.text
                if settings.gemini_api_key:
                    body = body.replace(settings.gemini_api_key, "***")
                logger.error(f"[GeminiThesis] API {r.status_code}: {body[:500]}")
                raise RuntimeError(f"[GeminiThesis] API {r.status_code}")
            data = r.json()
            usage = data.get("usageMetadata", {})
            logger.info(
                f"[API-COST] gemini gemini-2.5-flash "
                f"in={usage.get('promptTokenCount', '?')} "
                f"out={usage.get('candidatesTokenCount', '?')} "
                f"caller=GeminiThesisCards"
            )
            try:
                from app.services.api_cost_tracker import record_usage
                record_usage(
                    "gemini", "gemini-2.5-flash", "GeminiThesisCards",
                    usage.get("promptTokenCount", 0),
                    usage.get("candidatesTokenCount", 0),
                )
            except Exception:
                pass

            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            _t = raw_text.strip()
            if _t.startswith("```"):
                _t = _t.split("\n", 1)[1] if "\n" in _t else _t[3:]
                if _t.endswith("```"):
                    _t = _t[:-3]
                _t = _t.strip()
            parsed = json.loads(_t)

            # 긴장점 파싱
            tensions = []
            raw_tensions = parsed.get("tensions", [])
            if isinstance(raw_tensions, list):
                tensions = [str(t) for t in raw_tensions[:3] if t]

            raw_cards = parsed.get("thesis_cards", [])
            cards: list[ThesisCard] = []
            for tc in raw_cards[:3]:
                if isinstance(tc, dict):
                    cards.append(ThesisCard(
                        thesis=str(tc.get("thesis", "")),
                        why_not_summary=str(tc.get("why_not_summary", "")),
                        reader_stake=str(tc.get("reader_stake", "")),
                        opener=str(tc.get("opener", "")),
                        judgment_coord=str(tc.get("judgment_coord", "")),
                        verification_signal=str(tc.get("verification_signal", "")),
                    ))
            logger.info(
                f"[GeminiThesis] 슬롯 {len(cards)}개 + 긴장점 {len(tensions)}개 생성 완료"
            )
            return cards, tensions

    except Exception as e:
        safe_msg = str(e)
        if settings.gemini_api_key:
            safe_msg = safe_msg.replace(settings.gemini_api_key, "***")
        logger.warning(f"[GeminiThesis] 호출 실패: {safe_msg}")
        return [], []


# ─── 1차: 후보 카드 생성 ─────────────────────────────────────────────────────

async def generate_candidate_card(
    request: ContentRequest,
    verification_context: str = "",
) -> CandidateCard:
    """
    ContentRequest → CandidateCard (1차 후보 카드).

    Args:
        request: 소스 콘텐츠
        verification_context: 상단 분석(Gemini/Perplexity) 검증 결과 요약.
            예: "⚠️ 미검증 (신뢰도: low)\n수정사항: ..."

    흐름:
      1. 규칙 기반 팩트 시트 추출
      2. 짧은 프롬프트 + AI 호출
      3. 파싱 → CandidateCard
    """
    source_text = request.to_source_text()
    title = request.to_title()

    raw_input = source_text or title
    fact_sheet = extract_fact_sheet(raw_input)

    # 검증 결과에서 certainty 상한 결정
    verification_ceiling = _decide_certainty_ceiling(verification_context)

    # 프롬프트 구성
    user_prompt = f"Source type: {request.source_type}\n"
    if request.source_url:
        user_prompt += f"URL: {request.source_url}\n"

    # 검증 결과 삽입 (상단 분석이 있을 때)
    if verification_context:
        user_prompt += (
            f"\n=== 상단 검증 결과 (반드시 반영) ===\n"
            f"{verification_context}\n"
            f"⚠️ 위 검증 결과를 무시하고 자체 해설을 만들지 마라.\n"
            f"⚠️ certainty_level 상한: {verification_ceiling}\n"
            f"===\n"
        )

    # 팩트 시트 삽입
    user_prompt += "\n=== 팩트 시트 ===\n"
    user_prompt += f"주제: {fact_sheet.topic}\n"
    if fact_sheet.entities:
        user_prompt += f"주체/대상: {', '.join(fact_sheet.entities)}\n"
    if fact_sheet.figures:
        user_prompt += f"수치: {', '.join(fact_sheet.figures)}\n"
        user_prompt += f"⚠️ 위 수치만 사용 가능. 목록에 없는 수치 생성 금지.\n"
    else:
        user_prompt += "⚠️ 소스에 구체 수치 없음. 수치 생성 금지.\n"
    if fact_sheet.timeframe:
        user_prompt += f"기간: {fact_sheet.timeframe}\n"
    if fact_sheet.key_facts:
        user_prompt += "핵심 사실:\n"
        for i, kf in enumerate(fact_sheet.key_facts, 1):
            user_prompt += f"  {i}. {kf}\n"
    user_prompt += "===\n"

    user_prompt += f"\nContent:\n{raw_input[:3000]}\n\n"
    user_prompt += "후보 카드 JSON을 생성하라. 모든 텍스트는 한국어로."

    # AI 호출 (기존 _call_ai 재활용하되 프롬프트만 변경)
    raw = await _call_ai_with_prompt(_CANDIDATE_PROMPT_KO, user_prompt)

    if raw:
        card = _parse_candidate_card(raw, certainty_ceiling=verification_ceiling)
        if card and card.key_facts:
            card.source_url = request.source_url
            card.source_type = request.source_type
            card.fact_sheet_summary = (
                f"topic={fact_sheet.topic}, score={fact_sheet.data_density_score}"
            )

            # ── 기사 라우터: certainty_level → mode ──
            _mode = route_article_mode(card)
            logger.info(
                f"[ArticleMode] certainty={card.certainty_level} → {_mode}"
            )

            # ── Gemini: 해석 슬롯 3개 + 긴장점 생성 (mode 전달) ──
            thesis_cards, tensions = await _gemini_generate_thesis_cards(
                key_facts=card.key_facts,
                source_text=raw_input[:2000],
                topic_tags=card.topic_tags,
                cautions=card.cautions,
                mode=_mode,
            )
            if thesis_cards:
                card.thesis_cards = thesis_cards
                card.tensions = tensions
                card.hook_candidates = [tc.opener for tc in thesis_cards if tc.opener]
            else:
                # Gemini 실패 → key_facts로 fallback 슬롯 생성
                fallback_cards = []
                for i, kf in enumerate(card.key_facts[:3]):
                    fallback_cards.append(ThesisCard(
                        thesis=f"[Gemini실패] {kf[:70]}",
                        why_not_summary="Gemini 생성 실패 — 팩트 기반 폴백",
                        reader_stake="자동 생성 실패 — 수동 확인 필요",
                        opener=kf[:100],
                    ))
                if fallback_cards:
                    card.thesis_cards = fallback_cards
                    card.hook_candidates = [tc.opener for tc in fallback_cards if tc.opener]
                else:
                    card.hook_candidates = [f"[Gemini실패] {card.key_facts[0][:60]}"]

            # Low confidence 추정성 슬롯 감점/재정렬
            _reorder_slots_for_low_confidence(card)

            logger.info(
                f"후보 카드 생성 완료: facts={len(card.key_facts)}, "
                f"slots={len(card.thesis_cards)}, "
                f"tensions={len(card.tensions)}, "
                f"certainty={card.certainty_level}"
            )
            return card

    logger.warning("후보 카드 AI 응답 파싱 실패 — Mock 카드 반환")
    mock_fact = f"[Mock] {title[:60]}"
    mock_thesis = ThesisCard(
        thesis=f"[AI 실패] {title[:80]}",
        why_not_summary="AI 응답 실패 — 자동 생성 불가",
        reader_stake="수동 확인 필요",
        opener=mock_fact,
    )
    return CandidateCard(
        key_facts=[mock_fact],
        hook_candidates=[mock_fact],
        thesis_cards=[mock_thesis],
        one_liner=["[Mock] 한줄 결론 불가"],
        cautions=["Mock 모드 — 실제 분석 불가"],
        watch_points=["Mock 모드"],
        certainty_level="미확인",
        topic_tags=[fact_sheet.topic or "미분류"],
        risk_flags=["Mock 모드 — 실제 위험 분석 불가"],
        source_url=request.source_url,
        source_type=request.source_type,
    )


# ─── 헬퍼: 병렬 호출용 noop + 비교 로깅 ──────────────────────────────────────

async def _noop_async() -> None:
    """병렬 gather에서 조건 미충족 시 사용하는 빈 코루틴."""
    return None


def _log_draft_comparison(
    openai_draft: FinalPost,
    grok_eval: Optional["GrokEvalCard"],
    gemini_opinion: Optional["GeminiOpinionCard"] = None,
) -> None:
    """OpenAI 초안 + Grok 평가 로깅."""
    oa_first = openai_draft.final_post.split("\n")[0][:60] if openai_draft.final_post else "없음"
    gk_info = (
        f"score={grok_eval.score}/10 tags={grok_eval.fail_tags} "
        f"scope={grok_eval.rewrite_scope} "
        f"problem=\"{grok_eval.problem[:40]}\""
        if grok_eval else "없음"
    )

    logger.info(
        f"[초안+평가] OpenAI첫줄=\"{oa_first}\" | "
        f"Grok평가={gk_info}"
    )


# ─── 진행 상태 콜백 ─────────────────────────────────────────────────────────

# 모듈 레벨 콜백: generate_final_post 내부에서 단계 전환 시 호출
# telegram_bot.py에서 설정 → 메시지 edit으로 진행 표시
_progress_callback: Optional[object] = None  # async callable(str) or None


def set_progress_callback(cb) -> None:
    """진행 상태 콜백 등록. cb는 async def cb(stage: str) 형태."""
    global _progress_callback
    _progress_callback = cb


def clear_progress_callback() -> None:
    """진행 상태 콜백 해제."""
    global _progress_callback
    _progress_callback = None


async def _notify_progress(stage: str) -> None:
    """등록된 콜백이 있으면 호출."""
    if _progress_callback:
        try:
            await _progress_callback(stage)
        except Exception:
            pass


# ─── 2차: 최종 마감 ─────────────────────────────────────────────────────────

# 강한 실패 태그 — 자동 재생성 1회 대상
# 아래 4개만 재생성 트리거. 나머지(BRIEFING_SMELL / COMPLEX_SENTENCE /
# OPINION_LEAK)는 경고로만 유지.
_STRONG_FAIL_TAGS = frozenset({
    "WEAK_OPENER",
    "DEAD_ENDING",
    "STRUCTURE_COLUMN",
    "LOW_CONFIDENCE_OVERREACH",
})


def _has_strong_fail(tags: Optional[list]) -> bool:
    if not tags:
        return False
    return any(t in _STRONG_FAIL_TAGS for t in tags)


def _count_strong_fails(tags: Optional[list]) -> int:
    if not tags:
        return 0
    return sum(1 for t in tags if t in _STRONG_FAIL_TAGS)


def _build_retry_instruction(gate_fails: list) -> str:
    """남은 강한 실패 태그별 재생성 지시문. 논지 유지 + 표현 직선화."""
    hints = []
    if "WEAK_OPENER" in gate_fails:
        hints.append(
            "첫 문장: 45자 이내 핵심 명제부터 박아라. 배경 설명/접속 "
            "구조/'~이후'·'~보도한' 시작 금지."
        )
    if "DEAD_ENDING" in gate_fails:
        hints.append(
            "마지막 문장: '관건이다/변수다/여지가 드러났다/에 그칠 "
            "가능성이 있다' 금지. 그리고 '~뜻이다 / ~신호다 / ~의미한다 / "
            "~확인이다 / ~맞다 / ~보여준다 / ~시사한다' 같은 닫힌 판정 "
            "끝맺음 전부 금지 — endswith 까지 검사된다. '~이 나오면/안 "
            "나오면'으로 끝내되, 그 뒤에 '~뜻이다/~신호다' 를 붙이지 "
            "말고 동사 원형으로 맺어라. 예: '통상적 통행이 이어지면 "
            "상징에 그쳤다.' / '특사 파견이 포착되면 대화 채널이 "
            "살아 있다.' (뒤에 뜻이다/신호다 붙이지 말 것)"
        )
    if "STRUCTURE_COLUMN" in gate_fails:
        hints.append(
            "구조: 요약→의견→관건 3단 사설체 금지. 변화 / 의미 / 판별 "
            "기준 / 실패 시 해석 4문장으로 다시 조립."
        )
    if "LOW_CONFIDENCE_OVERREACH" in gate_fails:
        hints.append(
            "저신뢰(VERIFY) 기사: 정치적 계산/숨은 의도/노림수/본심 등 동기 "
            "추정, 그리고 '제3국 채널/외교 채널 복원/협상 의제 연동/긴장 "
            "수위 상승/구조적 의미/다음 국면을 결정/진짜 신호' 같은 구조 "
            "해석 확장 전부 제거. 최대 3문장: ①지금 나온 말 ②아직 확인 "
            "안 된 것 ③무엇이 나오면 진짜인지. 그 이상 쓰지 마라."
        )
    if not hints:
        return ""
    return (
        "\n\n━━━ 재생성 지시 (1회) ━━━\n"
        "직전 초안이 아래 태그로 실패했다. "
        "선택된 해석 슬롯/판단 좌표/판별 신호는 그대로 유지하라. "
        "새 논지 추가 금지. 표현만 더 직선적으로 다시 조립하라.\n"
        + "\n".join(f"  - {h}" for h in hints)
    )


# ─── 첫 줄 전용 rewrite 엔진 ─────────────────────────────────────────────────
#
# WEAK_OPENER 단독 실패(본문 다른 게이트는 통과)인 경우, 본문 전체를 다시
# 만들지 않고 첫 문장만 AI 로 교체한다. 이유:
#   1. 본문 전체 재생성은 판단 좌표/판별 신호를 재뽑기 때문에 논지 드리프트
#      위험이 있다.
#   2. WEAK_OPENER 는 사실상 "첫 문장이 너무 길거나 배경 설명" 문제라
#      전체 재생성까지 할 이유가 없다.
#   3. 토큰/지연 절감.
#
# 스플라이싱 규칙: 원본 post 의 첫 문장(마침표 기준)만 잘라내고 new_opener
# 로 교체. 뒷부분(본문)은 한 글자도 건드리지 않는다. 교체 후 다시 전체
# 검증을 돌려 다른 게이트가 새로 뜨면 호출자가 판단한다.

_OPENER_REWRITE_PROMPT_KO = """너는 "첫 문장만 다시 쓰는" 편집자다.

━━━ 절대 규칙 ━━━
1) 본문은 건드리지 마라. 너는 "첫 문장 한 줄" 만 낸다.
2) 새 사실 추가 금지. 본문에 이미 있는 주장을 한 줄로 압축만.
3) 선택된 해석 슬롯 / 판단 좌표 / 판별 신호는 바꾸지 마라. 표현만 직선화.
4) 길이: 45자 권장, 60자 초과 금지. 반드시 60자 안.
5) 금지 시작어: "~이후", "~보도한", "~보도된", "~전해진", "~알려진".
6) 금지 구조: "A인지 B인지 ~가 결정한다" 같은 이중 분기 수사.
7) 금지 마감: "관건이다/변수다/확인이 필요하다" 류로 첫 줄이 끝나면 안 됨.
8) VERIFY 기사라면 구조 해석("~라는 뜻이다", "진짜 신호", "국면을 결정",
   "채널이 살아 있다") 전부 금지. "지금 나온 주장" 한 줄로만.

━━━ 출력 ━━━
JSON 1개:
{"new_opener": "새 첫 문장 한 줄 (60자 이내, 마침표 포함 가능)"}
다른 필드, 설명, 마크다운 금지. JSON 만.
"""


# ─── 첫 줄 점수화 (PR 5) ────────────────────────────────────────────────────
#
# opener rewrite 는 "생성만 된다고 끝"이 아니다. 첫 줄 품질을 결정론적
# 규칙으로 점수화해서 임계 미달이면 한 번 더 돌리고, 그래도 미달이면
# full regen 으로 폴백한다. AI 호출 없이 길이/패턴/키워드만 본다.

# 변화 / 손익 / 판정선 / 충돌 — 첫 줄이 "센" 축으로 시작했다는 신호
_STRONG_OPENER_WORDS = (
    # 변화
    "바뀐", "바꿨", "전환", "뒤집혔", "뒤집었", "철회", "끊겼", "끊었",
    # 손익/숫자 체감
    "손실", "이익", "수익", "적자", "흑자", "영업익", "영업손실",
    # 판정선/갈림
    "기준은", "판단은", "갈린다", "갈림", "분기점", "관문은",
    # 충돌/맞섬
    "맞섰", "충돌", "반발", "거부", "결렬",
    # 단언형 핵심
    "핵심은", "포인트는", "쟁점은", "관건은",
)

# 첫 줄 점수 임계값 — 이 미만이면 재시도
_OPENER_MIN_SCORE = 60
# opener rewrite 최대 시도 횟수 (PR 5: 1→2)
_OPENER_REWRITE_MAX_ATTEMPTS = 2


def _score_opener(
    new_opener: str,
    *,
    mode: Optional[str] = None,
    certainty_level: Optional[str] = None,
) -> int:
    """첫 줄 품질 점수 (0~100). AI 호출 없음. 결정론.

    규칙 (출발 50, 60 통과, 0~100 clamp):
      - 빈 문자열            → 0 (즉시 폐기)
      - 60자 초과            → 0 (하드 캡)
      - 45자 이하            → +15
      - 46~55자              → +5
      - 배경 시작어(이후/보도된/전해진/알려진/보도한) in head[:20] → -30
      - 판가름/이중분기(이어질지/그칠지/판가름) → -25
      - 기사 재서술(_FACT_NARRATION_STARTS)         → -20
      - VERIFY/저신뢰 + _VERIFY_OVERREACH_PATTERNS   → -35
      - VERIFY/저신뢰 + _VERIFY_WEAK_OPENER_PATTERNS → -25
      - _STRONG_OPENER_WORDS 등장 1개+               → +10
      - 금지 마감(_BANNED_ENDINGS) 로 끝남           → -20

    출발점: 50점. 통과 임계값: 60점 (_OPENER_MIN_SCORE).
    """
    if not new_opener:
        return 0
    s = new_opener.strip()
    if not s:
        return 0

    # 마침표/물음표/느낌표 제거한 본문 길이로 본다 (하드캡 60자)
    length = len(s.rstrip(".!?"))
    if length > 60:
        return 0

    score = 50

    # 길이 가점
    if length <= 45:
        score += 15
    elif length <= 55:
        score += 5

    # 배경 시작어 — head 20자 안에 있으면 감점
    head = s[:20]
    _background_starts = ("이후 ", "보도한 ", "보도된 ", "전해진 ", "알려진 ")
    for bg in _background_starts:
        if bg in head:
            score -= 30
            break

    # 판가름/이중분기 수사 감점 (VERIFY 아니어도 밋밋함)
    for pat in ("이어질지", "그칠지", "판가름"):
        if pat in s:
            score -= 25
            break

    # 기사 재서술 패턴 감점
    for pat in _FACT_NARRATION_STARTS:
        if pat in s:
            score -= 20
            break

    # VERIFY / 저신뢰 — 구조 해석·이중분기 수사는 더 큰 감점
    low_conf = certainty_level in ("미확인", "상충") or mode == MODE_VERIFY
    if low_conf:
        for pat in _VERIFY_OVERREACH_PATTERNS:
            if pat in s:
                score -= 35
                break
        for pat in _VERIFY_WEAK_OPENER_PATTERNS:
            if pat in s:
                score -= 25
                break

    # 강한 키워드 가점 (변화/손익/판정선/충돌)
    for pat in _STRONG_OPENER_WORDS:
        if pat in s:
            score += 10
            break

    # 금지 마감 끝맺음 감점
    stripped_end = s.rstrip(".!?").rstrip()
    for banned in _BANNED_ENDINGS:
        if stripped_end.endswith(banned):
            score -= 20
            break

    return max(0, min(100, score))


def _splice_opener(post: str, new_opener: str) -> str:
    """post 의 첫 문장을 new_opener 로 교체. 본문은 유지."""
    if not post or not new_opener:
        return post
    new_opener = new_opener.strip()
    # 마침표가 없으면 붙인다
    if new_opener and new_opener[-1] not in ".!?":
        new_opener = new_opener + "."
    # 원본의 첫 문장을 제거 (마침표 또는 줄바꿈 기준)
    stripped = post.lstrip()
    leading_ws = post[: len(post) - len(stripped)]
    # 첫 마침표 또는 줄바꿈까지가 첫 문장
    first_end = None
    for i, ch in enumerate(stripped):
        if ch == "." or ch == "\n":
            first_end = i + 1
            break
    if first_end is None:
        # 문장 구분이 없으면 통째로 교체
        return leading_ws + new_opener
    rest = stripped[first_end:]
    # rest 선두 공백/개행 정리
    rest = rest.lstrip(" \t")
    if rest and not rest.startswith("\n"):
        rest = " " + rest
    return leading_ws + new_opener + rest


async def _rewrite_opener_only(
    card: "CandidateCard",
    draft: FinalPost,
    *,
    selected_hook: str = "",
    mode: Optional[str] = None,
) -> Optional[FinalPost]:
    """첫 문장만 AI 로 재작성. 실패 시 None 반환.

    WEAK_OPENER 가 유일한 강한 실패 태그일 때만 호출되도록 설계.
    본문은 한 글자도 바꾸지 않는다.
    """
    selected_thesis: Optional[ThesisCard] = None
    if card.thesis_cards:
        for tc in card.thesis_cards:
            if tc.opener == selected_hook:
                selected_thesis = tc
                break
        if not selected_thesis and card.thesis_cards:
            hook_idx = (
                card.hook_candidates.index(selected_hook)
                if selected_hook in card.hook_candidates
                else 0
            )
            if hook_idx < len(card.thesis_cards):
                selected_thesis = card.thesis_cards[hook_idx]

    user_prompt = "━━━ 현재 초안 ━━━\n"
    user_prompt += f"final_post (첫 문장만 바꿀 거다): {draft.final_post}\n\n"
    if selected_thesis:
        user_prompt += (
            "━━━ 선택된 해석 슬롯 (바꾸지 마라) ━━━\n"
            f"thesis: {selected_thesis.thesis}\n"
            f"reader_stake: {selected_thesis.reader_stake}\n"
        )
        if selected_thesis.judgment_coord:
            user_prompt += f"판단 좌표: {selected_thesis.judgment_coord}\n"
        if selected_thesis.verification_signal:
            user_prompt += f"판별 신호: {selected_thesis.verification_signal}\n"
        user_prompt += "\n"
    if mode:
        user_prompt += f"ARTICLE_MODE: {mode}\n"
    user_prompt += (
        f"certainty_level: {card.certainty_level}\n\n"
        "위 초안의 첫 문장이 길거나 배경 설명으로 시작해 걸렸다. "
        "본문은 그대로 두고 첫 문장만 핵심 명제 한 줄로 다시 써라. "
        "JSON 한 개만 출력."
    )

    raw = await _call_ai_with_prompt(
        _OPENER_REWRITE_PROMPT_KO, user_prompt, temperature=0.5
    )
    if not raw:
        logger.warning("[opener재작성] AI 응답 실패")
        return None

    try:
        text = raw.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
        data = json.loads(text)
        new_opener = str(data.get("new_opener", "")).strip()
    except Exception as e:
        logger.warning(f"[opener재작성] JSON 파싱 실패: {e}")
        return None

    if not new_opener:
        logger.warning("[opener재작성] new_opener 비어있음")
        return None

    # 점수화 (PR 5): 60자 하드 캡 + 배경어/판가름/재서술/VERIFY 금지어 + 강한 키워드
    score = _score_opener(
        new_opener,
        mode=mode,
        certainty_level=card.certainty_level,
    )
    opener_len = len(new_opener.rstrip(".!?"))
    logger.info(
        f"[opener점수] '{new_opener}' len={opener_len}자 score={score} "
        f"threshold={_OPENER_MIN_SCORE}"
    )
    if score < _OPENER_MIN_SCORE:
        logger.warning(
            f"[opener재작성] score {score} < {_OPENER_MIN_SCORE} — 폐기"
        )
        return None

    new_post = _splice_opener(draft.final_post, new_opener)

    # 재검증: 바뀐 post 로 전체 게이트 다시 확인
    post_v, short_v, warnings, gate_fails = _validate_final_post(
        new_post, draft.final_short,
        certainty_level=card.certainty_level,
        mode=mode,
    )
    for w in warnings:
        logger.info(f"[opener재작성-검증] {w}")
    logger.info(
        f"[opener재작성] 성공: '{new_opener}' "
        f"(before_gate_fails={draft.gate_fails}, "
        f"after_gate_fails={gate_fails})"
    )
    return FinalPost(
        final_post=post_v,
        final_short=short_v,
        gate_fails=gate_fails,
        reward_type=_resolve_reward_type(post_v, short_v),
    )


def _resolve_reward_type(post: str, short: str) -> Optional[str]:
    """FinalPost.reward_type 계산 — post 마지막 문장 우선, short 보조.

    _validate_last_line_reward 가 경고 판정에만 쓰이므로,
    reward_type 필드 주입은 이 헬퍼로 분리해 재사용한다.
    """
    last_sent = _extract_last_sentence(post)
    rt = _detect_reward_type(last_sent)
    if rt is not None:
        return rt
    if short:
        return _detect_reward_type(short)
    return None


async def generate_final_post(
    card: CandidateCard,
    hook_index: int,
    source_text: str = "",
) -> FinalPost:
    """
    CandidateCard + 선택된 훅 → FinalPost (2차 마감).
    """
    if hook_index < 0 or hook_index >= len(card.hook_candidates):
        hook_index = 0
    selected_hook = card.hook_candidates[hook_index]

    # thesis card context 추출 (있으면 사용, 없으면 hook만)
    selected_thesis: Optional[ThesisCard] = None
    if hook_index < len(card.thesis_cards):
        selected_thesis = card.thesis_cards[hook_index]

    # ── 슬롯형 입력: slot + tension + fact + cautions만 전달 ──
    user_prompt = "━━━ 입력 ━━━\n"
    if selected_thesis:
        user_prompt += (
            f"선택된 해석 슬롯: {selected_thesis.thesis}\n"
            f"긴장점: {selected_thesis.why_not_summary}\n"
            f"독자 영향: {selected_thesis.reader_stake}\n"
            f"첫 문장 초안: {selected_thesis.opener}\n"
        )
        if selected_thesis.judgment_coord:
            user_prompt += f"판단 좌표: {selected_thesis.judgment_coord}\n"
        if selected_thesis.verification_signal:
            user_prompt += f"판별 신호: {selected_thesis.verification_signal}\n"
    else:
        user_prompt += f"선택된 훅: {selected_hook}\n"

    # 긴장점 (Gemini 추출)
    if card.tensions:
        user_prompt += "\n갈라지는 지점:\n"
        for t in card.tensions[:2]:
            user_prompt += f"  - {t}\n"

    # 팩트 1~2개만 (전체 나열 금지)
    if card.key_facts:
        user_prompt += "\n근거 팩트 (이것만 써라):\n"
        for fact in card.key_facts[:2]:
            user_prompt += f"  - {fact}\n"

    user_prompt += f"\ncertainty_level: {card.certainty_level}\n"

    # cautions만 통제 조건으로 전달 (watch_points/one_liner/risk_flags 제거)
    if card.cautions:
        user_prompt += "\n⚠️ 통제 조건 (이 문구를 본문에 복붙하지 마라):\n"
        for c in card.cautions:
            user_prompt += f"  - {c}\n"

    # ━━━ 기사 원문 제거 — 요약 회귀 방지 ━━━
    # source_text를 주지 않는다. 슬롯 + 팩트만으로 쓰게 한다.

    # ── 기사 라우터: mode 결정 ──
    mode = route_article_mode(card)
    user_prompt += f"\nARTICLE_MODE: {mode}\n"

    # Low confidence 추정 경고 (VERIFY/JUDGMENT에서 모두 필요)
    _is_low_confidence = card.certainty_level in ("미확인", "상충")
    _speculation_guard = ""
    if _is_low_confidence:
        _speculation_guard = (
            "\n⚠️ LOW CONFIDENCE 기사: "
            "정치적 계산/숨은 의도/선거용 판단 같은 동기 추정을 중심 서사로 쓰지 마라. "
            "바뀐 사실과 검증 포인트 중심으로 써라.\n"
        )
    user_prompt += _speculation_guard

    # ── mode별 '지시' 블록 (EXPLAIN/JUDGMENT/VERIFY 분기) ──
    user_prompt += _build_mode_finalize_instruction(mode)

    # 공통 후행 지시 (mode 불문 동일)
    user_prompt += (
        "\n- 판단 좌표가 입력에 있으면 반드시 문장에 녹여라. 없으면 스스로 만들어라.\n"
        "- 판별 신호가 입력에 있으면 마지막 문장에 활용하라.\n"
        "- opener는 참고만. 그대로 복붙하지 마라.\n"
        "- 짧게 줄이기보다 해석 밀도를 우선하되, 칼럼체/신문해설 금지.\n"
        "- final_short: final_post와 다른 각도로 1문장.\n"
        "한국어로."
    )

    # ─ 내부 1 사이클: OpenAI 조립 → Grok 평가 → Claude 보정 ─
    # 강한 실패 재생성용으로 같은 흐름을 최대 2회 돌릴 수 있도록 추출.
    async def _run_cycle(extra_instruction: str = ""):
        """user_prompt + (옵션) 재생성 지시로 한 사이클 실행. (final, grok) 반환."""
        full_prompt = user_prompt + extra_instruction
        await _notify_progress("openai")
        _raw = await _call_ai_with_prompt(
            _FINALIZE_PROMPT_KO, full_prompt, temperature=0.9
        )
        if not _raw:
            return None, None
        _result = _parse_final_post(
            _raw, certainty_level=card.certainty_level, mode=mode
        )
        if not _result:
            return None, None

        await _notify_progress("grok")
        _grok = await _grok_eval(_result, card, selected_hook=selected_hook)
        if isinstance(_grok, Exception):
            logger.warning(f"[Grok평가] 실행 오류: {_grok}")
            _grok = None

        _log_draft_comparison(_result, _grok, None)

        _gate_1st = _result.gate_fails
        if _gate_1st:
            logger.warning(
                f"[품질게이트] 초안 실패: {_gate_1st} → Claude 보정 강제"
            )

        await _notify_progress("claude")
        _reviewed = await _claude_review_final(
            card, _result,
            selected_hook=selected_hook,
            gemini_opinion=None,
            grok_eval=_grok,
            gate_fails=_gate_1st,
            mode=mode,
        )
        _final = _reviewed if _reviewed else _result
        return _final, _grok

    # ── 1차 실행 ──
    final, grok_result = await _run_cycle()

    if final is None:
        logger.warning("최종 마감 AI 응답 실패 — 빈 결과 반환")
        return FinalPost(
            final_post=f"[마감 실패] {selected_hook}",
            final_short=f"[마감 실패] {selected_hook[:80]}",
        )

    # ── 강한 실패 잔존 시 자동 재생성 1회 ──
    if _has_strong_fail(final.gate_fails):
        strong_only = [t for t in final.gate_fails if t in _STRONG_FAIL_TAGS]
        # 첫 줄 전용 rewrite 경로:
        #   WEAK_OPENER 가 유일한 강한 실패 태그면 본문 전체 재생성 대신
        #   첫 문장만 교체한다. 판단 좌표/판별 신호 드리프트 방지.
        if strong_only == ["WEAK_OPENER"]:
            logger.warning(
                "[품질게이트] WEAK_OPENER 단독 잔존 — 첫 줄 rewrite 경로"
            )
            # PR 5: 점수 미달 시 최대 _OPENER_REWRITE_MAX_ATTEMPTS (=2) 회 재시도.
            # 모두 폐기되면 full regen 으로 폴백 (이 if/else 밖으로는 빠지지
            # 않고 여기서 마저 처리).
            rewritten = None
            for attempt in range(1, _OPENER_REWRITE_MAX_ATTEMPTS + 1):
                logger.info(
                    f"[opener재작성] 시도 {attempt}/"
                    f"{_OPENER_REWRITE_MAX_ATTEMPTS}"
                )
                candidate = await _rewrite_opener_only(
                    card, final, selected_hook=selected_hook, mode=mode
                )
                if candidate is not None:
                    rewritten = candidate
                    break

            if rewritten is not None:
                before = _count_strong_fails(final.gate_fails)
                after = _count_strong_fails(rewritten.gate_fails)
                logger.info(
                    f"[opener재작성] 강한 실패 개수: {before} → {after} "
                    f"(1차: {final.gate_fails}, "
                    f"재작성: {rewritten.gate_fails})"
                )
                if after <= before:
                    final = rewritten
            else:
                # 2회 시도 모두 점수 미달/파싱 실패 → full regen 폴백
                logger.warning(
                    f"[opener재작성] {_OPENER_REWRITE_MAX_ATTEMPTS}회 시도 "
                    "모두 폐기 — full regen 폴백"
                )
                retry_extra = _build_retry_instruction(final.gate_fails)
                retried, retried_grok = await _run_cycle(retry_extra)
                if retried is not None:
                    before = _count_strong_fails(final.gate_fails)
                    after = _count_strong_fails(retried.gate_fails)
                    logger.info(
                        f"[재생성-폴백] 강한 실패 개수: {before} → {after} "
                        f"(1차: {final.gate_fails}, "
                        f"재생성: {retried.gate_fails})"
                    )
                    if after <= before:
                        final = retried
                        grok_result = retried_grok
                else:
                    logger.warning("[재생성-폴백] AI 응답 실패 — 1차 결과 유지")
        else:
            logger.warning(
                f"[품질게이트] Claude 보정 후 강한 실패 잔존: "
                f"{final.gate_fails} → 자동 재생성 1회 시도"
            )
            retry_extra = _build_retry_instruction(final.gate_fails)
            retried, retried_grok = await _run_cycle(retry_extra)

            if retried is not None:
                before = _count_strong_fails(final.gate_fails)
                after = _count_strong_fails(retried.gate_fails)
                logger.info(
                    f"[재생성] 강한 실패 개수: {before} → {after} "
                    f"(1차: {final.gate_fails}, 재생성: {retried.gate_fails})"
                )
                # 재생성이 같거나 나으면 채택 (동률은 최신 버전 우선 — 표현 직선화 효과)
                if after <= before:
                    final = retried
                    grok_result = retried_grok
            else:
                logger.warning("[재생성] AI 응답 실패 — 1차 결과 유지")

        # 재생성 후에도 강한 실패가 남아 있으면 수동 확인 경고 강화
        if _has_strong_fail(final.gate_fails):
            if "RETRY_EXHAUSTED" not in final.gate_fails:
                final.gate_fails.append("RETRY_EXHAUSTED")
            logger.warning(
                f"[품질게이트] 재생성 후에도 강한 실패 잔존: {final.gate_fails} "
                "— 텔레그램에 '게시 전 수동 확인 필수' 경고 전달"
            )

    # PR 8/9: mode / reward_type 을 최종 요약 로그에 포함. 운영 grep 에서
    # mode / reward / gate_fails 분포를 한 줄로 얻을 수 있다 (로그 포인트
    # 추가 금지, 기존 라인 확장만).
    logger.info(
        f"최종 마감 완료: mode={mode} "
        f"certainty={card.certainty_level} "
        f"reward={final.reward_type} "
        f"post={len(final.final_post)}자, "
        f"short={len(final.final_short)}자, gate_fails={final.gate_fails}"
    )

    # 7대 검증 규칙 실행
    v_warnings = _run_all_validations(
        final.final_post,
        card=card,
        selected_thesis=selected_thesis,
        grok_eval=grok_result,
    )
    for vw in v_warnings:
        logger.warning(f"[7대검증] {vw}")

    return final


# ─── 3차: Claude 감수 / 리라이트 ─────────────────────────────────────────────

# Claude 호출 트리거 topic_tags
_SENSITIVE_TOPICS = {"정치", "외교", "안보", "군사", "부동산", "정책", "규제", "국방", "북한"}

# Claude 호출 트리거 + 검증용 뻔한 표현 목록 (final_post에 포함 시)
_WEAK_PATTERNS = [
    "추이를 봐야 한다",
    "추이를 지켜봐야",
    "영향이 커질 수 있다",
    "변수다",
    "중요한 시점이다",
    "주목해야 한다",
    "주목할 필요가",
    "지켜볼 필요가",
    "여파가 클 것으로",
    "영향을 미칠 것으로",
    "귀추가 주목",
    # 추가: 뻔한 전망문/사설체
    "영향을 미칠 수 있다",
    "여파가 예상된다",
    "가능성이 커졌다",
    "핵심은",
    "로 보인다",
    # 기자 질문형/해설 클리셰
    "시장 반응을 봐야 한다",
    "어떻게 될까",
    "향후 결과는",
    # 경고문/당위형 종결
    "핵심이다",
    "시급하다",
    "시급한 과제",
    "우려가 커지고 있다",
    "리스크가 커질 수 있다",
    "중요한 변수다",
    # 칼럼/사설체 구조
    "문제는",
    # 약한 일반화
    "피할 수 없다",
    "일으킬 수 있다",
    # thesis card dead patterns — 요약→의견→관건 구조
    "하려는 시도다",
    "의지를 보여준다",
    "로 해석된다",
    "의도가 드러난다",
    "가 관건이다",
    "에 달려 있다",
    "가 결정된다",
    # 추가 dead patterns — 스크린샷 분석
    "확인이 필요하다",
    "이어질 수 있을지",
    "실효성이 결정된다",
    "파장이 예상된다",
    "주목해야 할 대목이다",
    "실행될지",
    "전환점이 될",
    "보여준다",
    "드러난다",
    # 브리핑 장황체
    "타격을 입히기 시작했다",
    "영향을 미치고 있다",
    "를 발생시킨다",
    "를 발생시킬 수 있다",
    "로 이어진다",
    "로 이어질 수 있다",
    # 리뷰체/해설체 냄새
    "여부가 분기점이다",
    "를 판단하는 기준이다",
    "를 시사한다",
    "에 영향을 미친다",
    "가 부각된다",
    "를 의문케 한다",
    "가능성을 높인다",
    "를 판단할 수 있는",
    "가 중요해지고 있다",
    # 사용자 지정 추가 — "감 잡힘" 표현
    "여지가 드러났다",
    "여지가 열렸다",
    "여지가 생겼다",
    "에 그칠 가능성이 있다",
    "에 그칠 수 있다",
]


# ─── Low confidence 추정성 슬롯 감점 ────────────────────────────────────────

_SPECULATIVE_MOTIVE_PATTERNS = [
    "정치적 계산", "선거용", "선거를 앞둔", "중간선거",
    "숨은 의도", "숨은 계산", "본심", "노림수",
    "계산된 행동", "계산에서 비롯", "계산으로 보인다",
    "압박용", "제스처", "메시지용", "카드를 꺼낸",
    "showmanship", "쇼맨십", "정치적 동기",
    "의도가 깔려", "의도로 읽힌다", "의도로 풀이",
    "노린 것", "겨냥한 것", "포석", "밑그림",
    "정략적", "승부수", "도박",
]


# ─── VERIFY 모드 / 저신뢰 기사 전용 과해석 차단 ─────────────────────────────
#
# VERIFY / certainty 미확인·상충 기사에서 나오면 1개만 보여도 게이트 실패.
# "무슨 일이 벌어질 수 있다"가 아니라 "무엇이 아직 확인되지 않았다"만 남긴다.
# _SPECULATIVE_MOTIVE_PATTERNS 는 '동기 추정' 축, 이 리스트는 '구조 해석/
# 외교 시나리오 확장' 축. 두 축은 분리해서 운영한다.
_VERIFY_OVERREACH_PATTERNS = [
    "제3국을 통한 실질적 대화",
    "제3국 실질 채널",
    "실질적 대화 채널",
    "대화 채널로 이어",
    # NOTE (PR 8): "대화 채널이 살아" 는 VERIFY 템플릿 B 예시
    # ("특사 파견이 포착되면 대화 채널이 살아 있다") 와 충돌해 false positive
    # 를 일으켜 제거했다. 진짜 위험한 확장형 표현은 "대화 채널로 이어" 가
    # 여전히 잡는다. 단정형 "살아 있다" 만으로는 외교 시나리오 확장이 아님.
    "외교 채널 복원",
    "외교 채널을 복원",
    "협상 의제 연동",
    "협상 의제와 직접적으로 연동",
    "협상 의제'와 직접적으로 연동",
    "긴장 수위 상승",
    "긴장 수위를 한 단계 높이",
    "긴장 수위가 한 단계",
    "구조적 의미",
    "구조적으로 의미",
    "실효성 여부가 판가름",
    "다음 국면을 결정",
    "다음 국면이 결정",
    "국제질서 재편",
    "질서 재편",
    "진짜 신호",
    "진짜 신호는",
    # PR 6 — VERIFY 출력 스키마 축소 (설명문→검증문)
    # 이 계열은 "장기 해석 / 의도 추정 / 상징 해석 / 단정형 마감"
    # 을 본문에 다시 끌고 들어오는 통로였다. 본문 1개 등장만으로도
    # LOW_CONFIDENCE_OVERREACH. 저신뢰 기사는 '아직 확인 안 됨'만
    # 남기고 나머지는 전부 죽인다.
    "패러다임",
    "상징적 의미",
    "상징적으로 의미",
    "본심",
    "노림수",
    "를 시사한다",
    "을 시사한다",
    "라는 뜻이다",
    "이라는 뜻이다",
    # VERIFY 본문 전역에서도 이중분기 수사 차단
    # (_VERIFY_WEAK_OPENER_PATTERNS 는 첫 줄만 검사 → 본문 2~3문장에
    #  다시 들어오는 경로를 막는다)
    "이어질지",
    "그칠지",
    "판가름",
]


# VERIFY 첫 문장 금지 — 1문장 1주장만 허용
# "A인지 B인지 C가 결정한다" 식 이중 분기 수사 금지.
_VERIFY_WEAK_OPENER_PATTERNS = [
    "이어질지",          # "~이어질지 ~그칠지"
    "그칠지",            # "~에 그칠지가 ~"
    "판가름이다",        # "~가 판가름이다"
    "판가름한다",
    "을 결정한다",       # "A인지 B인지 ~을 결정한다"
    "를 결정한다",
    "단순 수사인지",
    "단순 압박인지",
    "실질 채널인지",
]


def _has_speculative_motive(text: str) -> bool:
    """텍스트에 추정성 정치 동기 해석이 포함되었는지 탐지."""
    lower = text.lower()
    return any(pat in lower for pat in _SPECULATIVE_MOTIVE_PATTERNS)


def _reorder_slots_for_low_confidence(card: CandidateCard) -> None:
    """
    Low confidence(미확인/상충)일 때 추정성 슬롯의 우선순위를 낮춘다.
    WHAT_CHANGED(0) → WHAT_DECIDES_NEXT(2) → WHY_IT_MATTERS(1) 순.
    추정성 동기 해석이 포함된 슬롯은 맨 뒤로 보낸다.
    """
    if card.certainty_level not in ("미확인", "상충"):
        return
    if len(card.thesis_cards) < 2:
        return

    speculative_indices = []
    safe_indices = []

    for i, tc in enumerate(card.thesis_cards):
        combined = f"{tc.thesis} {tc.opener} {tc.why_not_summary}"
        if _has_speculative_motive(combined):
            speculative_indices.append(i)
            logger.info(
                f"[SlotPenalty] 슬롯 {i} 추정성 감점: '{tc.thesis[:50]}'"
            )
        else:
            safe_indices.append(i)

    if not speculative_indices:
        return

    # 안전 슬롯 먼저, 추정성 슬롯 뒤로
    new_order = safe_indices + speculative_indices
    card.thesis_cards = [card.thesis_cards[i] for i in new_order]
    card.hook_candidates = [tc.opener for tc in card.thesis_cards if tc.opener]
    logger.info(
        f"[SlotPenalty] 슬롯 재정렬: {new_order} "
        f"(추정성 {len(speculative_indices)}개 후순위)"
    )


def _should_invoke_claude_review(card: CandidateCard, draft: FinalPost) -> bool:
    """Claude 감수를 호출할지 판단. True면 호출."""
    from app.config import settings
    if not settings.has_anthropic:
        return False

    reasons = []

    # 1. 민감 토픽
    if card.topic_tags:
        overlap = _SENSITIVE_TOPICS & set(card.topic_tags)
        if overlap:
            reasons.append(f"민감토픽: {overlap}")

    # 2. 미확인/상충
    if card.certainty_level in ("미확인", "상충"):
        reasons.append(f"certainty={card.certainty_level}")

    # 3. cautions 존재
    if card.cautions:
        reasons.append(f"cautions {len(card.cautions)}개")

    # 4. 뻔한 표현 감지
    for pat in _WEAK_PATTERNS:
        if pat in draft.final_post:
            reasons.append(f"뻔한표현: '{pat}'")
            break

    # 5. 첫 문장 사실나열 감지
    first_line = draft.final_post.split("\n")[0].strip()
    for narr in _FACT_NARRATION_STARTS:
        if narr in first_line:
            reasons.append(f"첫문장 사실나열: '{narr}'")
            break

    # 6. 일반론 의견 패턴 감지
    for pat in _OPINION_PATTERNS:
        if pat in draft.final_post:
            reasons.append(f"일반론 의견: '{pat}'")
            break

    # 7. final_short가 final_post 첫 문장과 동일 (독립성 부족)
    first_sentence = draft.final_post.split(".")[0].split("\n")[0].strip()
    short_first = draft.final_short.split(".")[0].split("\n")[0].strip() if draft.final_short else ""
    if first_sentence and short_first and first_sentence == short_first:
        reasons.append("short 독립성 부족")

    if reasons:
        logger.info(f"[Claude감수] 호출 결정: {', '.join(reasons)}")
        return True

    logger.info("[Claude감수] 조건 미충족 — 스킵")
    return False


_CLAUDE_REVIEW_PROMPT = """너는 X 게시글 "사실/톤 보정자"다.

━━━ 최우선 8대 원칙 (모든 규칙보다 우선) ━━━

너가 보정하는 글은 "고급 리뷰"가 아니라 "3초 안에 이해되는 설명문"이다.

목표:
- 첫 줄만 보고 핵심이 바로 들어와야 한다.
- 읽는 사람이 새 판단 기준 1개를 가져가야 한다.
- 마지막에 무엇을 보면 되는지 남겨야 한다.
- 남에게 전달하고 싶을 한 줄이 있어야 한다.

8대 규칙:
1) 첫 문장은 배경 설명 금지.
   허용 유형만:
   - "지금 핵심은 A다"
   - "A가 실제로 시작됐다"
   - "A와 B가 갈린다"
   - "A가 말인지 진짜 조치인지 곧 드러난다"
2) 한 문장 한 주장. 사실+해석+전망 동시 금지.
3) 최종 글 구조:
   문장1 핵심 명제 / 문장2 근거 팩트 / 문장3 판단 좌표 / 문장4 판별 신호
4) 판단 좌표: 기사 요약/추상 명분 금지. 독자가 새로 갖는 해석 기준 1개만.
5) 판별 신호: "무엇을 보면 되는가"만 남겨라.
   금지: "중요하다/관건이다/변수다/확인이 필요하다"
6) low confidence 기사: 정치적 계산/숨은 의도/본심/노림수 금지.
   대신 확인 신호를 앞세워라.
7) 기본 후보 카드 감각: 해석 1문장, 판단좌표 1문장, 판별신호 1문장.
   긴 설명은 자세히 보기로 넘겨라.
8) 짧은 버전: 요약이 아니라 전달 가능한 한 줄.
   공유하고 싶은 문장처럼 써라.

단, 너는 보정자다. 위 원칙 위반 시 최소 수정으로 맞춰라.
논지(thesis)는 바꾸지 마라. 표현만 압축/분리하라.

━━━ 역할 (CRITICAL) ━━━

너는 "최종 책임자"가 아니라 "보정자"다.
OpenAI가 선택된 논지(thesis)로 쓴 초안이 제공된다.
너의 역할은 딱 2가지:
1. 사실 보정: cautions 위반, certainty_level 초과, 기사 사실과 모순되는 표현 수정
2. 톤 보정: 보고서체/칼럼체/전망문/훈계문 → 트윗체로 교정

절대 하면 안 되는 일:
- 논지(thesis)를 바꾸거나 새 해석 축을 추가하는 것
- 초안의 방향성을 뒤집는 것
- "더 좋은 글"을 쓰려고 리라이트하는 것
- 새 사실/수치 추가 (원문에 없는 것)

초안이 이미 괜찮으면 그대로 JSON으로 반환하라.
고칠 게 있으면 최소한으로 고쳐라. 논지를 건드리지 마라.

━━━ Grok 평가 활용 규칙 (평가가 있을 때) ━━━

Grok 평가는 톤 보정 참고 자료다. 논지 변경 근거가 아니다.

1. rewrite_scope=KEEP → 사실/톤만 최소 보정. 첫 문장 유지.
2. rewrite_scope=REWRITE_OPENER_ONLY → 첫 문장 표현만 다듬어라. 논지는 유지.
3. rewrite_scope=REJECT_AND_REGENERATE → 첫 문장을 크게 다듬되 논지 방향은 유지.
4. fail_tags 활용:
   - HEADLINE_RESTATEMENT → 첫 문장을 기사 제목과 다르게 표현.
   - PRESS_RELEASE_TONE / POLICY_MEMO_TONE → 해당 문체만 트윗체로 교정.
   - COLUMN_ENDING → 종결 패턴만 조건형/대비형으로 교체.
   - NO_READER_STAKE → 독자 이해관계를 더 드러내되, 새 사실 추가 금지.
   - GENERIC_SKEPTICISM → 구체적 조건/변수로 좁혀라.
   - SAME_THESIS → 참고만. 논지 자체를 바꾸지 마라.
   - DEAD_ENDING / 죽은마감 → 마지막 문장을 판별 신호로 교체 ("무엇이 나오면/안 나오면" 구체적으로).
   - SPECULATIVE_MOTIVE / 저신뢰과해석 → 동기 추정 톤 낮추기. certainty 미확인이면 특히 약화.
   - LOW_CONFIDENCE_OVERREACH → 과한 해석을 사실 기반으로 후퇴.
   - ABSTRACT_WRAPUP → 추상 명사 정리를 구체적 검증 포인트로 교체.
   - 기사재서술 → 기사 재서술 문장을 해석 기준 문장으로 교체.
   - 평균문 → 해석 밀도를 높이되 새 사실 추가 금지.
   - 판단좌표없음 → 독자 해석 기준이 생기도록 한 문장 보정.
   - 슬롯기능중복 → 참고만. 논지 변경 금지.
5. fix_direction은 톤 보정 참고만. 논지 변경에 쓰지 마라.
6. Grok 평가가 없으면 사실/톤 보정만 하라.
7. 새 사실 추가 금지.

━━━ 문체 모델 ━━━

"트위터 팔로워 10만인 한국 증권사 출신 해설자"
- 신문 칼럼 X, 보고서 X, TV 해설 X
- 건조하고 짧게. 감탄사 없이. 한 문장에 하나만.
- "이 사람 아는 사람이네" 느낌이 들어야 한다.

━━━ 즉시 이해성 보정 (CRITICAL) ━━━

초안의 가장 흔한 문제:
- 첫 문장이 배경 설명/종속절로 시작 → 핵심 명제로 교체
- 한 문장에 주장 2~3개 → 쪼개서 한 문장 한 주장
- 문장이 길고 복잡 → 짧고 직선적으로

보정 규칙:
1. 첫 문장이 배경 설명이면 핵심 명제로 교체하라.
   ✗ "11일 협상 결렬 이후 로이터가 보도한..." → ✓ "지금 포인트는 재회담 성사 여부다."
2. 한 문장에 주장 2개 이상이면 쪼개라.
   ✗ "A가 일어나면서 B가 영향을 받고 C가 중요해진다" → ✓ 문장 3개로 분리
3. 판별 신호는 짧고 직접적으로.
   ✗ "~여부가 분기점이다" → ✓ "금요일까지 재회 소식이 나오면 대화는 살아 있다."
4. 쉼표 2개 이상/접속사 2개 이상 문장은 쪼개라.
5. 보정 시 논지를 바꾸지 마라. 새 논지 추가 금지. 표현만 압축/분리하라.
   판단 좌표와 판별 신호는 유지한 채 문장만 단순하게 만들어라.

━━━ 문장 구조 ━━━

문장 1 — 핵심 명제: 지금 뭐가 핵심인지 바로 박기. 40자 이내 권장. 배경 설명 금지.
문장 2 — 팩트 근거: 확인된 사실 1~2개 + 해석 축 연결. 나열 금지.
문장 3 — 판단 좌표: 독자가 새로 갖게 되는 해석 기준. 기사 재서술/추상 명분 금지.
마지막 문장 — 판별 신호: "무엇이 나오면/안 나오면" 구체적 검증 포인트. 짧게. 전망문·훈계문 금지.

2~4문장. 한 문장 한 주장. 칼럼체 금지.

━━━ 보정 판정 기준 (이것만 고쳐라) ━━━

아래 중 하나라도 해당하면 해당 부분만 최소 보정:
1. cautions와 충돌하는 표현 → 약화/삭제
2. certainty_level 초과 단정 → 톤 낮춤
3. 기사 사실과 모순되는 단정 → 사실 인정 후 좁히기
4. 보고서체/칼럼체 종결 → 트윗체로 교정
5. 금지 마감 패턴 → "판별 신호"로 교체 ("무엇이 나오면/안 나오면" 구체적 검증 포인트)
6. "문제는 ~것이다" "핵심이다" 칼럼/사설 구조 → 조건형/대비형으로 변환
7. Low confidence 추정 과열 → 정치적 계산/숨은 의도/노림수 류 동기 추정이
   certainty_level 미확인/상충인데 중심 서사로 쓰였으면 톤 낮추거나 삭제
8. 판단 좌표 부재 → 기사 재서술 문장이 있으면 독자 해석 기준으로 교체

논지(thesis) 방향, 해석 축, 첫 문장의 의미는 건드리지 마라.

━━━ 마지막 문장 교정 규칙 (CRITICAL) ━━━

마지막 문장이 "관건이다/변수다/확인이 필요하다/지켜봐야 한다"류이면
반드시 "판별 신호"로 교체하라.

판별 신호 = "무엇이 나오면/안 나오면" 구체적 검증 포인트:
  ✓ "후속 시행령이 6월 전에 나오면 정책, 안 나오면 선언에 그침"
  ✓ "브렌트유가 $90 이상 3영업일 유지되면 단기 쇼크가 아니라 추세다"
  ✓ "해군 이동이나 추가 제재가 뒤따르느냐가 진짜 분기점이다"
  ✗ "관건이다" "변수다" "확인이 필요하다" "지켜봐야 한다"
  ✗ "뭘 봐야 하는지" 없이 "봐야 한다"만 말하면 실패

━━━ 사실 상한선 ━━━

- certainty_level이 미확인/상충이면 단정 금지
- cautions와 충돌하는 표현 수정
- 정치/외교/군사는 한 단계 더 보수적으로
- 새 사실/수치 추가 금지 (원문에 없는 것)

━━━ 금지 마감 패턴 (CRITICAL — 이것만은 반드시 잡아라) ━━━

아래 패턴이 마지막 문장에 있으면 반드시 "판별 신호"로 교체:
✗ "추이를 봐야 한다" "변수다" "주목해야 한다" "중요하다"
✗ "영향을 미칠 수 있다" "여파가 예상된다" "핵심은 ~다"
✗ "중요한 시점이다" "관건은 ~다" "관건이다" "~어떻게 될까?"
✗ "핵심이다" "시급하다" "문제는 ~것이다"
✗ "확인이 필요하다" "이어질 수 있을지" "실효성이 결정된다"
✗ "파장이 예상된다" "실행될지" "보여준다" "해석된다" "드러난다"
✗ "전환점이 될" "주목된다" "주목해야 할 대목이다"
✗ "지켜봐야 한다" "얼마나 유지되는지가 핵심이다" "얼마나 오래 유지되는지가 관건"
✗ "여부가 분기점이다" "를 판단하는 기준이다" "를 시사한다"
✗ "에 영향을 미친다" "가 부각된다" "를 의문케 한다" "가능성을 높인다"

교체 = "판별 신호" ("무엇이 나오면/안 나오면" 구체적 검증 포인트):
  ✓ "후속 시행령이 6월 전에 나오면 정책, 안 나오면 선언에 그침"
  ✓ "해군 이동이나 추가 제재가 뒤따르느냐가 분기점이다"
  ✓ "브렌트유가 $90 이상 3영업일 유지되면 단기 쇼크가 아니라 추세다"
  ✓ "배제 명단에 실무급이 포함되는지 다음 주 인사발령에서 갈린다"

━━━ 칼럼/사설 구조 금지 ━━━

"문제는 ~것이다" / "핵심이다" 구조 = 사설체. 트윗에서 금지.
  ✗ "문제는 ~것이다" "문제는 ~라는 점이다" "핵심이다" "본질은 ~"
  ✓ 조건형/대비형으로 변환 ("갈림길은 시행 시점이다")

━━━ 반증 금지 ━━━

기사에 나온 사실과 모순되는 단정 금지.
기사에 대응/조치/계획이 언급됐으면 "준비가 안 돼 있다"고 쓰면 거짓이다.
불충분하다고 보면 "~를 시작했지만 속도가 관건이다" 식으로 사실 인정 후 좁혀라.

━━━ 초안이 좋을 때 ━━━

- 고칠 게 없으면 원문 그대로 JSON으로 반환
- 억지로 고치지 마라

━━━ 출력 ━━━
한국어 JSON만 출력:
{
  "final_post": "최종 완성본",
  "final_short": "독립형 짧은 버전"
}"""


# ─── Phase 2: Gemini 대안 의견 카드 ──────────────────────────────────────────

# Gemini 대안 의견 카드용 토픽 (확장 리뷰 트리거)
_EXTENDED_REVIEW_TOPICS = {
    "정치", "외교", "안보", "군사", "부동산", "정책",
    "국제", "지정학", "거시경제", "규제", "국방", "북한",
}

_GEMINI_OPINION_PROMPT = """너는 X 게시글 "대안 의견 카드" 생성기다.

━━━ 역할 ━━━

OpenAI가 작성한 1차 초안(final_post, final_short)을 읽고,
"더 읽히는 대안"만 제안하라.
본문 전체를 다시 쓰지 마라. 의견 카드만 반환하라.

━━━ 네가 할 일 (우선순위 순) ━━━

1. first_line_suggestion (가장 중요)
   - 초안의 첫 문장보다 더 읽히는 첫 문장 1개
   - 기사 요약/사실 나열 금지
   - "왜 봐야 하는가"로 시작하는 해석형 문장
   - 초안 첫 문장이 이미 좋으면 빈 문자열 ""

2. alt_short
   - 초안 final_short보다 더 살아있는 짧은 버전 1개
   - final_post 축약본이 아닌 독립 문장
   - 초안 short가 이미 좋으면 빈 문자열 ""

3. alt_angle
   - 같은 기사를 다르게 읽는 해석 축 1개
   - 한국 관점 연결 필수 (환율/비용/기업/증시/정부 등)
   - 새로운 축이 없으면 빈 문자열 ""

4. alt_hooks
   - 대안 훅 1~2개
   - 기사 제목과 구별되는 해석형 문장
   - 대안이 없으면 빈 배열 []

━━━ 절대 금지 ━━━

- 새 사실/새 수치 추가 금지 (원문에 없는 것)
- 기사 밖 확장 금지
- cautions/검증 결과보다 강한 주장 금지
- 최종 글 전체 재작성 금지

━━━ 문체 모델 ━━━

"트위터 팔로워 10만인 한국 증권사 출신 해설자"

━━━ 출력 ━━━
한국어 JSON만 출력:
{
  "first_line_suggestion": "더 읽히는 첫 문장 1개",
  "alt_short": "더 나은 short 1개",
  "alt_angle": "다른 해석 각도 1개",
  "alt_hooks": ["대안 훅 1", "대안 훅 2"]
}"""


# ─── Phase 3: Grok X 감각 심사 ──────────────────────────────────────────────

@dataclass
class GrokEvalCard:
    """Grok X 감각 평가 카드 (구조화 버전).

    score: 0-10 (0=완전 기사복붙, 10=X 네이티브 완벽)
    fail_tags: 감지된 실패 태그 목록
    rewrite_scope: KEEP / REWRITE_OPENER_ONLY / REJECT_AND_REGENERATE
    problem: 왜 약한지 한 줄
    fix_direction: 어떻게 고칠지 한 줄
    """
    score: int = 5
    fail_tags: list[str] = field(default_factory=list)
    rewrite_scope: str = "KEEP"
    problem: str = ""
    fix_direction: str = ""

# Grok fail_tags 유효 목록
_GROK_VALID_FAIL_TAGS = {
    "SAME_THESIS",           # 논지가 기사 요약과 같음
    "PRESS_RELEASE_TONE",    # 보도자료/기사체
    "POLICY_MEMO_TONE",      # 정책 보고서체
    "COLUMN_ENDING",         # 칼럼/사설 종결
    "NO_READER_STAKE",       # 독자 이해관계 없음
    "GENERIC_SKEPTICISM",    # 막연한 회의론
    "HEADLINE_RESTATEMENT",  # 기사 제목 재진술
    "SPECULATIVE_MOTIVE",    # 근거 없는 정치/동기 추정이 중심 서사
    "DEAD_ENDING",           # 마지막 문장이 관건/변수/확인 필요류
    "LOW_CONFIDENCE_OVERREACH",  # 미확인 기사에서 과한 해석
    "ABSTRACT_WRAPUP",       # 추상 명사로 두루뭉술 정리
    # ── 한국어 fail_tags ──
    "기사재서술",             # 기사 내용을 다시 풀어쓴 것
    "평균문",                # 누구나 쓸 수 있는 평범한 해설문
    "판단좌표없음",           # 독자에게 새 해석 기준을 주지 못함
    "죽은마감",              # 마지막 문장이 검증 포인트 없이 끝남
    "저신뢰과해석",           # 미확인 기사에서 과한 정치/의도 추정
    "슬롯기능중복",           # 3개 슬롯이 실질적으로 같은 기능
}

_GROK_EVAL_PROMPT = """너는 X 게시글 "X 감각 심사관"이다.

━━━ 역할 ━━━

너는 X에서 한국 이슈 글을 매일 보는 편집자다.
기사 요약문, 평균문, 안전한 해설문을 바로 알아본다.
네 역할은 글을 다시 쓰는 것이 아니라,
이 글이 왜 약한지를 구조화된 태그로 판정하는 것이다.

━━━ 판정 기준 ━━━

1. score (0~10)
   0 = 기사 제목 복붙 수준
   3 = 요약문/보도자료체
   5 = 보통 (읽을 만하지만 X 감각 부족)
   7 = 좋음 (눈이 멈춤)
   9 = 매우 좋음 (반드시 읽게 됨)
   10 = X 네이티브 완벽

2. fail_tags (배열 — 해당하는 것만)
   아래 태그 중 해당하는 것만 넣어라. 해당 없으면 빈 배열 [].

   [영어 태그]
   - SAME_THESIS: 논지가 기사 요약과 같음. 독자적 해석 축 없음.
   - PRESS_RELEASE_TONE: "~밝혔다" "~발표했다" "~전했다" 보도자료/기사 문체.
   - POLICY_MEMO_TONE: "~해야 한다" "~시급하다" "~필요하다" 정책 보고서체.
   - COLUMN_ENDING: "핵심이다" "문제는 ~것이다" "관건이다" 칼럼/사설 종결.
   - NO_READER_STAKE: 독자 이해관계(돈/시간/기회/위험)가 없음. 추상적 중요성만.
   - GENERIC_SKEPTICISM: "과연 ~할까?" "~일지 미지수" 막연한 회의론.
   - HEADLINE_RESTATEMENT: 첫 문장이 기사 제목/요약 재진술.
   - SPECULATIVE_MOTIVE: "정치적 계산" "숨은 의도" "노림수"류 근거 없는 동기 추정이 중심 서사.
   - DEAD_ENDING: 마지막 문장이 "관건이다" "변수다" "확인이 필요하다" "지켜봐야 한다"류.
     외부 검증 신호(뭘 보면 판별되는지)가 없이 "봐야 한다"만 말함.
   - LOW_CONFIDENCE_OVERREACH: certainty 미확인인데 과한 해석/단정을 함.
   - ABSTRACT_WRAPUP: "전환점이 될" "시금석" "분수령" 추상 명사로 두루뭉술 마무리.

   [한국어 태그 — 위 영어 태그와 병행 사용]
   - 기사재서술: 기사 내용을 다시 풀어쓴 것. 해석이 아니라 재서술.
   - 평균문: 누구나 쓸 수 있는 평범한 해설문. 해석 밀도 부족.
   - 판단좌표없음: 독자에게 새 해석 기준을 주지 못함. 읽어도 판단 기준이 안 생김.
   - 죽은마감: 마지막 문장에 구체적 검증 포인트가 없음. "관건이다/변수다" 류.
   - 저신뢰과해석: 미확인/상충 기사에서 과한 정치적 동기 추정/의도 해석.
   - 슬롯기능중복: 3개 슬롯이 실질적으로 같은 기능을 함. 해석 축 분리가 안 됨.

3. rewrite_scope
   - "KEEP": score 7 이상이고 fail_tags 없거나 1개 이하 → 현재 초안 유지
   - "REWRITE_OPENER_ONLY": score 4~6이거나 fail_tags 1~2개 → 첫 문장만 수정
   - "REJECT_AND_REGENERATE": score 3 이하이거나 fail_tags 3개 이상 → 전면 재생성 필요
   주의: DEAD_ENDING 또는 죽은마감만 있어도 최소 REWRITE_OPENER_ONLY 이상.
   주의: SPECULATIVE_MOTIVE/저신뢰과해석 + certainty 미확인 → 강한 감점 (score -2 수준).
   주의: 판단좌표없음이 있으면 해석 밀도 부족 — score -1 수준.

4. problem
   이 글이 왜 X에서 안 먹히는지 한 줄.

5. fix_direction
   어떻게 고치면 되는지 한 줄. 방향만. 전체 리라이트 금지.

━━━ 절대 금지 ━━━

- 글 전체를 다시 쓰지 마라
- 대안 문장을 3줄 이상 쓰지 마라
- 새 사실/수치를 추가하지 마라
- 위 목록에 없는 fail_tag를 만들지 마라

━━━ 출력 ━━━
JSON만 출력:
{
  "score": 0-10,
  "fail_tags": ["TAG1", "TAG2"],
  "rewrite_scope": "KEEP|REWRITE_OPENER_ONLY|REJECT_AND_REGENERATE",
  "problem": "한 줄",
  "fix_direction": "한 줄"
}"""


async def _grok_eval(
    draft: FinalPost, card: CandidateCard, *, selected_hook: str = ""
) -> Optional[GrokEvalCard]:
    """Grok으로 X 감각 평가 카드 생성. 실패 시 None (파이프라인 중단 없음)."""
    from app.config import settings

    if not settings.has_grok:
        return None

    user_prompt = (
        f"━━━ 평가 대상 초안 ━━━\n"
        f"final_post: {draft.final_post}\n"
        f"final_short: {draft.final_short}\n\n"
        f"━━━ 기사 정보 ━━━\n"
        f"선택된 논지/훅: {selected_hook}\n"
        f"certainty_level: {card.certainty_level}\n"
    )
    if card.key_facts:
        user_prompt += "핵심 팩트:\n"
        for i, fact in enumerate(card.key_facts, 1):
            user_prompt += f"  {i}. {fact}\n"

    user_prompt += (
        "\n━━━ 지시 ━━━\n"
        "위 초안을 X 감각으로 평가하고 JSON을 반환하라.\n"
        "글을 다시 쓰지 마라. 판정만 하라.\n"
    )

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.grok_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-3-mini-fast",
                    "messages": [
                        {"role": "system", "content": _GROK_EVAL_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.5,
                },
            )
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage", {})
            logger.info(
                f"[API-COST] grok grok-3-mini-fast "
                f"in={usage.get('prompt_tokens', '?')} "
                f"out={usage.get('completion_tokens', '?')} "
                f"caller=GrokEval"
            )
            try:
                from app.services.api_cost_tracker import record_usage
                record_usage(
                    "grok", "grok-3-mini-fast", "GrokEval",
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
            except Exception:
                pass

            raw_text = data["choices"][0]["message"]["content"]
            # JSON 파싱
            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\s*", "", clean)
                clean = re.sub(r"\s*```$", "", clean)
            parsed = json.loads(clean)

            # fail_tags 유효성 필터링
            raw_tags = parsed.get("fail_tags", [])
            if isinstance(raw_tags, list):
                valid_tags = [t for t in raw_tags if t in _GROK_VALID_FAIL_TAGS]
            else:
                valid_tags = []

            raw_scope = str(parsed.get("rewrite_scope", "KEEP"))
            if raw_scope not in ("KEEP", "REWRITE_OPENER_ONLY", "REJECT_AND_REGENERATE"):
                raw_scope = "KEEP"

            eval_card = GrokEvalCard(
                score=max(0, min(10, int(parsed.get("score", 5)))),
                fail_tags=valid_tags,
                rewrite_scope=raw_scope,
                problem=str(parsed.get("problem", "")),
                fix_direction=str(parsed.get("fix_direction", "")),
            )
            logger.info(
                f"[Grok평가] score={eval_card.score}/10 "
                f"fail_tags={eval_card.fail_tags} "
                f"rewrite_scope={eval_card.rewrite_scope} "
                f"problem=\"{eval_card.problem[:50]}\""
            )
            return eval_card

    except Exception as e:
        logger.warning(f"[Grok평가] 호출 실패: {e}")
        return None


@dataclass
class GeminiOpinionCard:
    """Gemini 대안 의견 카드."""
    first_line_suggestion: str = ""
    alt_short: str = ""
    alt_angle: str = ""
    alt_hooks: list[str] = field(default_factory=list)


def _should_invoke_extended_review(
    card: CandidateCard, draft: FinalPost
) -> bool:
    """Gemini 대안 의견 카드를 호출할지 판단. True면 호출."""
    reasons: list[str] = []

    # 1. 민감/확장 토픽
    if card.topic_tags:
        overlap = _EXTENDED_REVIEW_TOPICS & set(card.topic_tags)
        if overlap:
            reasons.append(f"확장리뷰토픽: {overlap}")

    # 2. 미확인/상충
    if card.certainty_level in ("미확인", "상충"):
        reasons.append(f"certainty={card.certainty_level}")

    # 3. validation warning 2개 이상
    _, _, warnings, _ = _validate_final_post(draft.final_post, draft.final_short)
    if len(warnings) >= 2:
        reasons.append(f"validation경고 {len(warnings)}개")

    # 4. 첫 줄 밋밋한 패턴
    first_line = draft.final_post.split("\n")[0].strip() if draft.final_post else ""
    for narr in _FACT_NARRATION_STARTS:
        if narr in first_line:
            reasons.append(f"첫줄 사실나열: '{narr}'")
            break

    # 5. 뻔한 표현 포함
    for pat in _WEAK_PATTERNS:
        if pat in draft.final_post:
            reasons.append(f"뻔한표현: '{pat}'")
            break

    # 6. final_short가 final_post 첫 문장과 동일 (요약문 느낌)
    first_sentence = draft.final_post.split(".")[0].split("\n")[0].strip()
    short_first = (
        draft.final_short.split(".")[0].split("\n")[0].strip()
        if draft.final_short else ""
    )
    if first_sentence and short_first and first_sentence == short_first:
        reasons.append("short가 요약문")

    if reasons:
        logger.info(f"[Gemini의견카드] 호출 결정: {', '.join(reasons)}")
        return True

    logger.info("[Gemini의견카드] 조건 미충족 — 스킵")
    return False


async def _gemini_opinion_card(
    card: CandidateCard, draft: FinalPost, *, selected_hook: str = ""
) -> Optional[GeminiOpinionCard]:
    """Gemini로 대안 의견 카드 생성. 실패 시 None."""
    from app.config import settings

    if not settings.has_gemini:
        return None

    user_prompt = (
        f"━━━ 1차 초안 (OpenAI) ━━━\n"
        f"final_post: {draft.final_post}\n"
        f"final_short: {draft.final_short}\n\n"
        f"━━━ 선택된 훅 ━━━\n"
        f"{selected_hook}\n\n"
        f"━━━ 카드 정보 ━━━\n"
        f"certainty_level: {card.certainty_level}\n"
    )
    if card.key_facts:
        user_prompt += "핵심 팩트:\n"
        for i, fact in enumerate(card.key_facts, 1):
            user_prompt += f"  {i}. {fact}\n"
    if card.cautions:
        user_prompt += "cautions:\n"
        for c in card.cautions:
            user_prompt += f"  - {c}\n"
    if card.topic_tags:
        user_prompt += f"topic_tags: {', '.join(card.topic_tags)}\n"

    user_prompt += "\n위 초안을 보고 대안 의견 카드를 JSON으로 반환하라."

    try:
        import httpx
        url = (
            "https://generativelanguage.googleapis.com/v1beta"
            "/models/gemini-2.5-flash:generateContent"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                url,
                params={"key": settings.gemini_api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {
                        "parts": [{"text": _GEMINI_OPINION_PROMPT}],
                    },
                    "contents": [
                        {"parts": [{"text": user_prompt}]},
                    ],
                    "generationConfig": {
                        "temperature": 0.8,
                    },
                },
            )
            if r.status_code >= 400:
                body = r.text
                if settings.gemini_api_key:
                    body = body.replace(settings.gemini_api_key, "***")
                logger.error(f"[GeminiOpinion] API {r.status_code}: {body[:500]}")
                raise RuntimeError(f"[GeminiOpinion] API {r.status_code}")
            data = r.json()
            usage = data.get("usageMetadata", {})
            logger.info(
                f"[API-COST] gemini gemini-2.5-flash "
                f"in={usage.get('promptTokenCount', '?')} "
                f"out={usage.get('candidatesTokenCount', '?')} "
                f"caller=GeminiOpinionCard"
            )
            try:
                from app.services.api_cost_tracker import record_usage
                record_usage(
                    "gemini", "gemini-2.5-flash", "GeminiOpinionCard",
                    usage.get("promptTokenCount", 0),
                    usage.get("candidatesTokenCount", 0),
                )
            except Exception:
                pass

            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            _t = raw_text.strip()
            if _t.startswith("```"):
                _t = _t.split("\n", 1)[1] if "\n" in _t else _t[3:]
                if _t.endswith("```"):
                    _t = _t[:-3]
                _t = _t.strip()
            parsed = json.loads(_t)
            result = GeminiOpinionCard(
                first_line_suggestion=str(parsed.get("first_line_suggestion", "")),
                alt_short=str(parsed.get("alt_short", "")),
                alt_angle=str(parsed.get("alt_angle", "")),
                alt_hooks=[str(h) for h in parsed.get("alt_hooks", [])],
            )
            logger.info(
                f"[Gemini의견카드] 생성 완료: "
                f"first_line={'있음' if result.first_line_suggestion else '없음'}, "
                f"alt_hooks={len(result.alt_hooks)}개"
            )
            return result

    except Exception as e:
        safe_msg = str(e)
        if settings.gemini_api_key:
            safe_msg = safe_msg.replace(settings.gemini_api_key, "***")
        logger.warning(f"[Gemini의견카드] 호출 실패: {safe_msg}")
        return None


async def _claude_review_final(
    card: CandidateCard,
    draft: FinalPost,
    *,
    selected_hook: str = "",
    gemini_opinion: Optional[GeminiOpinionCard] = None,
    grok_eval: Optional["GrokEvalCard"] = None,
    gate_fails: Optional[list] = None,
    mode: Optional[str] = None,
) -> Optional[FinalPost]:
    """Anthropic Claude 최종 통합. 실패 시 None (OpenAI 결과로 폴백)."""
    from app.config import settings

    if not settings.has_anthropic:
        return None

    user_prompt = (
        f"━━━ 초안 (OpenAI) ━━━\n"
        f"final_post: {draft.final_post}\n"
        f"final_short: {draft.final_short}\n\n"
    )

    # Phase 3: Grok 평가 카드가 있으면 추가
    if grok_eval:
        user_prompt += (
            f"━━━ Grok X 감각 평가 ━━━\n"
            f"score: {grok_eval.score}/10\n"
            f"fail_tags: {grok_eval.fail_tags}\n"
            f"rewrite_scope: {grok_eval.rewrite_scope}\n"
            f"problem: {grok_eval.problem}\n"
            f"fix_direction: {grok_eval.fix_direction}\n\n"
        )

    # thesis context가 있으면 논지 정보 전달
    selected_thesis: Optional[ThesisCard] = None
    if card.thesis_cards:
        # selected_hook에서 매칭되는 thesis card 찾기
        for tc in card.thesis_cards:
            if tc.opener == selected_hook:
                selected_thesis = tc
                break
        if not selected_thesis and card.thesis_cards:
            # hook_index로 fallback
            hook_idx = card.hook_candidates.index(selected_hook) if selected_hook in card.hook_candidates else 0
            if hook_idx < len(card.thesis_cards):
                selected_thesis = card.thesis_cards[hook_idx]

    if selected_thesis:
        user_prompt += (
            f"━━━ 선택된 논지 (이 방향을 건드리지 마라) ━━━\n"
            f"thesis: {selected_thesis.thesis}\n"
            f"why_not_summary: {selected_thesis.why_not_summary}\n"
            f"reader_stake: {selected_thesis.reader_stake}\n"
            f"opener: {selected_thesis.opener}\n\n"
        )
    else:
        user_prompt += (
            f"━━━ 선택된 훅 ━━━\n"
            f"{selected_hook}\n\n"
        )

    user_prompt += (
        f"━━━ 카드 정보 ━━━\n"
        f"certainty_level: {card.certainty_level}\n"
    )
    if card.cautions:
        user_prompt += "cautions:\n"
        for c in card.cautions:
            user_prompt += f"  - {c}\n"
    if card.topic_tags:
        user_prompt += f"topic_tags: {', '.join(card.topic_tags)}\n"

    # Gemini 대안 의견 카드가 있으면 참고 자료로 추가
    if gemini_opinion:
        user_prompt += (
            "\n━━━ Gemini 대안 의견 (참고자료 — 좋은 것만 흡수, 별로면 무시) ━━━\n"
        )
        if gemini_opinion.first_line_suggestion:
            user_prompt += f"first_line_suggestion: {gemini_opinion.first_line_suggestion}\n"
        if gemini_opinion.alt_short:
            user_prompt += f"alt_short: {gemini_opinion.alt_short}\n"
        if gemini_opinion.alt_angle:
            user_prompt += f"alt_angle: {gemini_opinion.alt_angle}\n"
        if gemini_opinion.alt_hooks:
            user_prompt += "alt_hooks:\n"
            for h in gemini_opinion.alt_hooks:
                user_prompt += f"  - {h}\n"
        user_prompt += (
            "주의: Gemini 의견은 참고일 뿐이다. "
            "새 사실 추가 금지. 검증 결과보다 강한 주장 금지.\n"
        )

    # Low confidence 추정 경고 추가
    if card.certainty_level in ("미확인", "상충"):
        user_prompt += (
            "\n⚠️ LOW CONFIDENCE 기사: "
            "정치적 계산/숨은 의도/선거용 판단 같은 동기 추정이 중심 서사면 톤을 낮춰라. "
            "추정 → '~라는 해석이 나온다' 수준으로.\n"
        )

    # ── 게이트 실패 시 보정 강도 강화 ──
    _gate_instructions = ""
    if gate_fails:
        _tag_to_instruction = {
            "WEAK_OPENER": (
                "🚨 첫 문장이 배경 설명/사실나열이거나 60자를 넘는다. "
                "반드시 첫 문장을 핵심 명제 한 줄로 다시 써라. 40자 이내 권장. "
                "배경 설명/종속절('~에도 불구하고') 시작 금지. "
                "단, 선택된 슬롯의 논지를 바꾸지 마라. 표현만 압축하라. "
                "좋은 예: '지금 포인트는 재회담 성사 여부다.' "
                "'결렬 이후에도 채널이 살아 있는지가 핵심이다.'"
            ),
            "DEAD_ENDING": (
                "🚨 마지막 문장이 '관건이다/변수다/중요하다'류 죽은 마감이다. "
                "반드시 판별 신호로 교체하라: '무엇이 나오면/안 나오면' 구체적 검증 포인트. "
                "판단 좌표와 판별 신호는 유지한 채 표현만 교체."
            ),
            "BRIEFING_SMELL": (
                "🚨 브리핑/보고서 냄새 표현이 2개 이상 감지됐다. "
                "장황한 표현을 전부 짧고 단단한 문장으로 압축하라. "
                "한 문장에 주장 1개만. 쉼표 2개 이상 문장은 쪼개라."
            ),
            "OPINION_LEAK": (
                "🚨 근거 없는 일반론 의견이 감지됐다. "
                "반드시 확인된 사실+수치로 뒷받침하거나 해당 문장을 삭제하라."
            ),
            "COMPLEX_SENTENCE": (
                "🚨 문장이 복잡하다 (쉼표/접속사 과다). "
                "복잡한 문장을 짧은 2~3문장으로 쪼개라. "
                "한 문장 한 주장. 쉼표 2개 이상 금지. "
                "단, 논지를 바꾸지 마라. 표현만 분리하라."
            ),
            "STRUCTURE_COLUMN": (
                "🚨 요약→의견→관건 3단 구조(사설체)가 감지됐다. "
                "'하려는 시도다/의지를 보여준다/로 해석된다'로 시작해 "
                "'가 관건이다/에 달려 있다'로 끝나는 구조를 해체하라. "
                "마지막 문장은 판별 신호('무엇이 나오면/안 나오면')로 교체. "
                "논지는 유지하고 문장 기능만 바꿔라."
            ),
            "LOW_CONFIDENCE_OVERREACH": (
                "🚨 저신뢰(미확인/상충) 기사인데 본문에 "
                "'정치적 계산/숨은 의도/노림수/본심'류 동기 추정이 남아 있다. "
                "동기 추정 문장을 확인 신호 중심으로 교체하라. "
                "꼭 필요하면 '~라는 해석이 나온다' 수준으로 1단계 낮춰라. "
                "사실과 검증 포인트를 앞세워라."
            ),
        }
        parts = []
        for tag in gate_fails:
            instr = _tag_to_instruction.get(tag)
            if instr:
                parts.append(instr)
        if parts:
            _gate_instructions = (
                "\n\n━━━ 품질 게이트 실패 — 반드시 교정 ━━━\n"
                + "\n".join(parts)
                + "\n위 항목은 반드시 교정하라. 교정하지 않으면 게시 불가.\n"
                + "\n⚠️ 보정 제약: 더 직선적으로 다시 써라. "
                "단, 선택된 슬롯의 논지를 바꾸지 마라. 새 논지를 만들지 마라. "
                "판단 좌표와 판별 신호는 유지한 채 표현만 압축하라. "
                "슬롯 이동 금지.\n"
            )

    user_prompt += (
        "\n위 초안의 사실/톤만 보정하고, JSON으로 반환하라. 논지를 바꾸지 마라.\n"
        "마지막 문장이 '관건이다/변수다/확인이 필요하다'류이면 "
        "반드시 외부 검증 신호(뭘 보면 판별되는지)로 교체하라."
        + _gate_instructions
    )

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 500,
                    "system": _CLAUDE_REVIEW_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage", {})
            logger.info(
                f"[API-COST] anthropic claude-haiku-4-5 "
                f"in={usage.get('input_tokens', '?')} "
                f"out={usage.get('output_tokens', '?')} "
                f"caller=ClaudeReview"
            )
            try:
                from app.services.api_cost_tracker import record_usage
                record_usage("anthropic", "claude-haiku-4-5", "ClaudeReview",
                             usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            except Exception:
                pass

            raw = data["content"][0]["text"]
            result = _parse_final_post(
                raw, certainty_level=card.certainty_level, mode=mode
            )
            if result and result.final_post:
                return result

            logger.warning("[Claude감수] 파싱 실패 — 원본 유지")
            return None

    except Exception as e:
        logger.warning(f"[Claude감수] 호출 실패: {e}")
        return None


# ─── 공통 AI 호출 (시스템 프롬프트 주입형) ───────────────────────────────────

async def _call_ai_with_prompt(
    system_prompt: str, user_prompt: str, *, temperature: float = 0.7
) -> Optional[str]:
    """시스템 프롬프트를 직접 받는 AI 호출. OpenAI → Anthropic → None."""
    from app.config import settings

    # OpenAI
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
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                r.raise_for_status()
                data = r.json()
                usage = data.get("usage", {})
                logger.info(
                    f"[API-COST] openai gpt-4o-mini "
                    f"in={usage.get('prompt_tokens', '?')} "
                    f"out={usage.get('completion_tokens', '?')} "
                    f"caller=CandidateCard/Finalize"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("openai", "gpt-4o-mini", "CandidateCard/Finalize",
                                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                except Exception:
                    pass
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"OpenAI 후보카드/마감 호출 실패: {e}")

    # Anthropic
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
                        "max_tokens": 1500,
                        "temperature": temperature,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
                r.raise_for_status()
                data = r.json()
                usage = data.get("usage", {})
                logger.info(
                    f"[API-COST] anthropic claude-haiku-4-5 "
                    f"in={usage.get('input_tokens', '?')} "
                    f"out={usage.get('output_tokens', '?')} "
                    f"caller=CandidateCard/Finalize"
                )
                try:
                    from app.services.api_cost_tracker import record_usage
                    record_usage("anthropic", "claude-haiku-4-5", "CandidateCard/Finalize",
                                 usage.get("input_tokens", 0), usage.get("output_tokens", 0))
                except Exception:
                    pass
                return data["content"][0]["text"]
        except Exception as e:
            logger.warning(f"Anthropic 후보카드/마감 호출 실패: {e}")

    return None


# ─── 검증 상한 결정 ──────────────────────────────────────────────────────────

# 검증 실패 키워드 (하나라도 포함 시 certainty 상한 제한)
_VERIFICATION_FAIL_KEYWORDS = [
    "미검증", "신뢰도: low", "신뢰도:low",
    "no matching", "unrelated",
    "확인 실패", "추가 확인 필요", "검색 결과 없음",
    "무관한 검색", "기사 확인 실패",
]

# certainty 우선순위: 확정 > 상충 > 미확인
_CERTAINTY_RANK = {"확정": 2, "상충": 1, "미확인": 0}
_RANK_TO_CERTAINTY = {2: "확정", 1: "상충", 0: "미확인"}


def _decide_certainty_ceiling(verification_context: str) -> str:
    """
    검증 컨텍스트에서 certainty_level 상한을 결정.

    반환값: "확정" | "상충" | "미확인"
    - 검증 실패 키워드 존재 → "미확인"
    - 신뢰도 medium → "상충"
    - 검증 결과 없음 또는 신뢰도 high → "확정" (제한 없음)
    """
    if not verification_context:
        return "확정"  # 검증 정보 없으면 제한하지 않음

    ctx_lower = verification_context.lower()

    # 검증 실패 키워드 감지
    for keyword in _VERIFICATION_FAIL_KEYWORDS:
        if keyword.lower() in ctx_lower:
            logger.info(f"[CertaintyCeiling] 검증 실패 키워드 감지: '{keyword}' → 상한 '미확인'")
            return "미확인"

    # 신뢰도 medium → 상충까지만
    if "신뢰도: medium" in ctx_lower or "신뢰도:medium" in ctx_lower:
        return "상충"

    return "확정"


# ─── 파서 ────────────────────────────────────────────────────────────────────

def _parse_candidate_card(
    raw: str,
    certainty_ceiling: str = "확정",
) -> Optional[CandidateCard]:
    """AI 응답 JSON → CandidateCard. certainty_level 상한 보정 포함."""
    try:
        text = raw.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
        data = json.loads(text)

        # certainty_level 상한 강제
        ai_certainty = str(data.get("certainty_level", "미확인"))
        ceiling_rank = _CERTAINTY_RANK.get(certainty_ceiling, 0)
        ai_rank = _CERTAINTY_RANK.get(ai_certainty, 0)
        if ai_rank > ceiling_rank:
            logger.warning(
                f"[CertaintyCeiling] AI가 '{ai_certainty}'로 응답했으나 "
                f"상한 '{certainty_ceiling}'으로 하향 보정"
            )
            ai_certainty = certainty_ceiling

        # thesis_cards 파싱 → ThesisCard 객체 리스트
        raw_thesis = data.get("thesis_cards", [])
        thesis_cards: list[ThesisCard] = []
        if isinstance(raw_thesis, list):
            for tc in raw_thesis[:3]:
                if isinstance(tc, dict):
                    thesis_cards.append(ThesisCard(
                        thesis=str(tc.get("thesis", "")),
                        why_not_summary=str(tc.get("why_not_summary", "")),
                        reader_stake=str(tc.get("reader_stake", "")),
                        opener=str(tc.get("opener", "")),
                    ))

        # hook_candidates: OpenAI가 생성해도 무시 — Gemini thesis_cards에서만 채움
        # (OpenAI hook_candidates가 있으면 Gemini 실패 시 thesis_cards 폴백 안 됨)
        raw_hooks: list[str] = []
        if thesis_cards:
            raw_hooks = [tc.opener for tc in thesis_cards if tc.opener]

        return CandidateCard(
            key_facts=_ensure_list(data.get("key_facts"), 5),
            hook_candidates=raw_hooks,
            thesis_cards=thesis_cards,
            one_liner=_ensure_list(data.get("one_liner"), 3),
            cautions=_ensure_list(data.get("cautions"), 3),
            watch_points=_ensure_list(data.get("watch_points"), 5),
            certainty_level=ai_certainty,
            topic_tags=_ensure_list(data.get("topic_tags"), None),
            risk_flags=_ensure_list(data.get("risk_flags"), None),
        )
    except Exception as e:
        logger.warning(f"CandidateCard 파싱 오류: {e}")
        return None


# 마감 금지 패턴 (교훈형/당위형/보고서 투/뻔한 전망문 마무리)
_BANNED_ENDINGS = [
    # 기존 교훈형/당위형
    "주목해야 할 시점이다",
    "주목할 시점이다",
    "주목해야 한다",
    "주목된다",
    "지켜볼 필요가 있다",
    "지켜봐야 한다",
    "지켜봐야 할 것이다",
    "중요하게 봐야 한다",
    "중요해지고 있다",
    "영향을 미칠 것으로 보인다",
    "여파가 클 것으로 보인다",
    "악영향이 예상된다",
    "반발이 커질 수 있다",
    "불가피해 보인다",
    "불가피할 전망이다",
    "귀추가 주목된다",
    # 뻔한 전망문/사설체
    "추이를 봐야 한다",
    "추이를 지켜봐야 한다",
    "영향을 미칠 수 있다",
    "중요한 시점이다",
    "여파가 예상된다",
    "가능성이 커졌다",
    # 기자 질문형/해설 클리셰
    "시장 반응을 봐야 한다",
    "어떻게 될까",
    "향후 결과는",
    "정부의 공식 입장은",
    # 추가 dead endings — 스크린샷 분석
    "변수다",
    "중요하다",
    "확인이 필요하다",
    "확인 필요",
    "이어질 수 있을지",
    "실효성이 결정된다",
    "관건이다",
    "파장이 예상된다",
    "주목해야 할 대목이다",
    "실행될지",
    "보여준다",
    "해석된다",
    "드러난다",
    "전환점이 될",
    "주목된다",
    # 스크린샷 실패 케이스 추가
    "오래 유지되는지가 관건",
    "유지되는지가 핵심",
    "얼마나 지속될지",
    "실제 시행될지는",
    "정말 실행되는지",
    "핵심이다",
    "심각하다",
    # 브리핑/설명문 잔여
    "문제다",
    "가 더 중요하다",
    "를 보면 알 수 있다",
    "를 판단할 수 있다",
    "가 중요하다",
    "로 이어진다",
    "이 중요하다",
    # 리뷰체/해설체 마감
    "여부가 분기점이다",
    "를 판단하는 기준이다",
    "를 시사한다",
    "에 영향을 미친다",
    "가 부각된다",
    "를 의문케 한다",
    "가능성을 높인다",
    "가 부각되고 있다",
    "를 보여주고 있다",
    # 사용자 지정 추가 금지 표현 — 설명 대신 감 잡힘 표현/추정 마감
    "여지가 드러났다",
    "여지가 열렸다",
    "여지가 생겼다",
    "에 그칠 가능성이 있다",
    "에 그칠 수 있다",
    "가능성이 있다",
    # 95점 목표 — 닫힌 판정 마감 금지 (그록 평가 기반)
    # "~는 신호다 / ~다는 확인이다 / ~가 맞다 / ~의미한다" 식 단정 마감은
    # 독자 생각을 닫아버려 글이 얕아진다. endswith 검사라 문장 중간 쓰임은 허용.
    "신호다",
    "의미한다",
    "의미다",
    "확인이다",
    "뜻이다",
    "맞다",
    "패러다임 변화다",
    "구조적 의미를 갖는다",
    "의미를 갖는다",
    # PR 9 — 닫힌 분석가 마감 추가 (DEAD_ENDING strong gate).
    # "기준이다" 는 여기에 넣지 않는다 — SAVE 보상문("답은 다음 CPI가 기준이다")
    # 과 겹쳐 false positive 를 유발한다. "기준이다" 는 _validate_last_line_reward
    # 에서 reward 시그널 유무에 따라 조건부 처리한다.
    "판별 포인트다",
    "결정한다",
    "의미가 있다",
    "중요한 대목이다",
    # PR 10 — 추상 마감 확장. "시사한다" standalone 은 "를 시사한다" 의 상위호환.
    "시사한다",
    "구조적 변화다",
    "영향이 예상된다",
    "관심이 필요하다",
]


# ─── PR 9: Reader Reward Layer ────────────────────────────────────────────
#
# 독자 보상 시그널 = 마지막 문장에서 "왜 저장/공유/팔로우해야 하는지"가 드러
# 나는 표현. 결정론 키워드 매칭으로 3유형 중 하나로 태깅한다.
#
# - SAVE   : 앞으로 비슷한 사안을 판단할 때 참조할 프레임/기준점
# - SHARE  : 간명한 한 줄로 바로 나눌 수 있는 단언
# - FOLLOW : 후속 데이터/발표 시 다시 돌아올 이유 (검증 조건 포함)
#
# VERIFY 템플릿 A/B/C 예시 끝줄("검증 가능" / "살아 있다" / "수사에 가깝다"
# / "그쳤다")은 전부 FOLLOW 계열로 이미 잡힘 → VERIFY 안전성 훼손 없음.
_REWARD_FOLLOW_PATTERNS = [
    "이 나오면",
    "이 공개되면",
    "이 포착되면",
    "가 나오면",
    "가 공개되면",
    "가 포착되면",
    "이 이어지면",
    "가 이어지면",
    "가 드러난다",
    "진짜가 드러난다",
    "후속 데이터",
    "후속 발표",
    "다음 발표",
    "다음 공식",
    "다음 CPI",
    "다음 지표",
    "다음 집계",
    "다음 숫자",
    "추적",
    "검증 가능",
    "확인 가능",
    # 질문형 FOLLOW — "~느냐/는지/될지" 로 닫는 후속 관측 질문.
    # 관건은 ~느냐다 계열은 SAVE marker + FOLLOW closure 겸용이지만
    # 여기선 FOLLOW 로 태깅 (다음 지켜볼 질문이 더 강한 축).
    "느냐다",
    "는지다",
    "될지다",
    "느냐에",
    "는지에",
    # VERIFY 템플릿 B/C 예시 끝줄 — FOLLOW 로 태깅
    "살아 있다",
    "수사에 가깝다",
    "그쳤다",
    "얼 수 있다",
    # 조건부 결과 ("X면 Y 줄어든다/늘어난다/오른다/떨어진다/바뀐다")
    "면 줄어든다",
    "면 늘어난다",
    "면 오른다",
    "면 떨어진다",
    "면 바뀐다",
    "면 갈린다",
    "면 맞는",
]

# SAVE 강한 마커 — 문장에 있으면 FOLLOW 신호와 겹쳐도 SAVE 우선.
# "답은 다음 CPI가 기준이다" 처럼 SAVE marker + FOLLOW 소재 공존 시
# 독자 의도가 '기준점 저장' 쪽이므로 SAVE 태깅이 맞다.
_REWARD_SAVE_STRONG_PATTERNS = [
    "답은 ",
    "결국 먼저 ",
    "먼저 봐야 할 건",
    "먼저 맞는 건",
    "먼저 움직",
    "입금 시점",
    "입금이 먼저",
]

# SAVE 약한 마커 — FOLLOW 와 겹치면 FOLLOW 우선.
_REWARD_SAVE_WEAK_PATTERNS = [
    "핵심은 ",
    "진짜 ",
]

_REWARD_SHARE_PATTERNS = [
    "말보다 숫자가",
    "말보다 출처가",
    "주장보다 출처",
    "주장보다 원본",
    "발표보다 원본",
    "발표보다 데이터",
    "보다 숫자가 먼저",
    "보다 출처가 먼저",
    "그냥 SNS 주장",
    "그냥 주장이다",
    "출처가 안 나오면",
    "원본 데이터가 먼저",
]

# 마지막 문장 전용 — 닫힌 분석가 마감 phrase. reward 시그널 없이 이걸로 끝나면
# NO_READER_REWARD (WARN-only) 를 강하게 찍는다. "기준이다" 도 여기 포함:
# reward 키워드가 같은 문장에 있으면 허용, 없으면 경고.
_CLOSED_ANALYST_LAST_LINE = [
    "기준이다",
    "변수다",
    "핵심 변수다",
    "파장이다",
    "대목이다",
    "쟁점이다",
]


def _extract_last_sentence(text: str) -> str:
    """post 에서 마지막 문장만 뽑는다. 마침표/줄바꿈 기준."""
    if not text:
        return ""
    t = text.strip().rstrip(".!?")
    # 줄바꿈과 마침표 둘 다 splitter 로 취급
    normalized = t.replace("\n", ".")
    parts = [p.strip() for p in normalized.split(".") if p.strip()]
    if not parts:
        return ""
    return parts[-1]


def _detect_reward_type(text: str) -> Optional[str]:
    """
    텍스트에서 독자 보상 시그널을 찾아 'SAVE'/'SHARE'/'FOLLOW'/None 반환.

    결정론. AI 호출 없음. 체크 순서:
      1. SAVE 강한 마커 ("답은 ", "결국 먼저 " 등) — 최우선
         → "답은 다음 CPI가 기준이다" 처럼 FOLLOW 와 겹쳐도 SAVE.
      2. FOLLOW 시그널 (VERIFY 템플릿 포함해 가장 일반적)
      3. SAVE 약한 마커 ("핵심은 ", "진짜 ")
      4. SHARE 시그널
    """
    if not text:
        return None
    for pat in _REWARD_SAVE_STRONG_PATTERNS:
        if pat in text:
            return "SAVE"
    for pat in _REWARD_FOLLOW_PATTERNS:
        if pat in text:
            return "FOLLOW"
    for pat in _REWARD_SAVE_WEAK_PATTERNS:
        if pat in text:
            return "SAVE"
    for pat in _REWARD_SHARE_PATTERNS:
        if pat in text:
            return "SHARE"
    return None


def _validate_last_line_reward(
    post: str,
    short: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    PR 9 — 마지막 줄 독자 보상 검사.

    판정 우선순위 (사용자 지시):
      1. final_post 마지막 문장 → reward_type 잡히면 그걸로 확정.
      2. final_post 에 reward 없을 때만 final_short 보조로 본다.
      3. 둘 다 reward 없을 때만 NO_READER_REWARD 경고 발생.

    반환: (reward_type, warn_reason)
      reward_type : "SAVE"|"SHARE"|"FOLLOW"|None
      warn_reason : None 또는 NO_READER_REWARD 사유 문자열

    주의: 경고는 WARN-only. _STRONG_FAIL_TAGS 에 넣지 말 것. 재생성 루프
    유발 금지.
    """
    if not post:
        return None, None

    last_sent = _extract_last_sentence(post)

    # 1차: post 마지막 문장
    reward = _detect_reward_type(last_sent)
    if reward is not None:
        return reward, None

    # 2차 (보조): short 전체
    if short:
        reward_s = _detect_reward_type(short)
        if reward_s is not None:
            return reward_s, None

    # 3차: closed analyst last-line 이면 강한 사유 부여, 아니면 일반 사유
    last_clean = last_sent.rstrip(".!?").rstrip()
    for pat in _CLOSED_ANALYST_LAST_LINE:
        if last_clean.endswith(pat):
            return None, (
                f"마지막 문장 '{pat}' — 독자 보상(SAVE/SHARE/FOLLOW) 시그널 없음"
            )

    return None, "마지막 문장에 독자 보상(SAVE/SHARE/FOLLOW) 시그널 없음"


# ─── PR 10: Findability Layer ─────────────────────────────────────────────
#
# 첫 2문장 안에 "검색 가능한 구체 앵커"(숫자/영문 약어/고유명사) 가 충분히
# 있는지 휴리스틱으로 검사한다.  v1 은 WARN-only — _STRONG_FAIL_TAGS 미편입.
#
# 앵커 ≥ 2 → 통과,  1 → 경고만,  0 → LOW_FINDABILITY gate tag + 경고.

_FINDABILITY_KNOWN_ENTITIES = [
    # 한국 주요 기업/브랜드
    "삼성", "현대", "기아", "포스코", "카카오", "네이버", "쿠팡", "롯데",
    "한화", "두산", "신한", "하나", "우리", "토스",
    # 한국 정부/기관
    "국세청", "관세청", "금감원", "한국은행", "기재부", "산자부", "국방부",
    "외교부", "통일부", "과기부", "교육부", "환경부", "법무부", "행안부",
    "대통령", "국회", "여당", "야당", "헌법재판소", "대법원", "검찰",
    # 국가
    "미국", "중국", "일본", "러시아", "북한", "우크라이나", "이란",
    "대만", "사우디", "인도", "독일", "영국", "프랑스", "호주",
    # 한국 도시/지역
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "제주",
    "강남", "강북", "서초", "송파", "여의도", "판교",
    # 주요 인물 (검색 빈도 높은)
    "트럼프", "바이든", "시진핑", "푸틴", "젤렌스키", "윤석열", "이재명",
]

_FINDABILITY_ANCHOR_RE = re.compile(
    r"\d[\d,.]*"              # 숫자 (날짜/금액/비율)
    r"|[A-Z][A-Za-z0-9]{1,}"  # 영문 약어/티커 2자+ (CPI, GDP, KOSPI, SK)
)


def _extract_first_two_sentences(text: str) -> str:
    """post 에서 첫 2문장만 뽑는다. 줄바꿈/마침표 기준."""
    if not text:
        return ""
    normalized = text.replace("\n", ".")
    parts = [p.strip() for p in normalized.split(".") if p.strip()]
    return ". ".join(parts[:2])


def _count_findability_anchors(text: str) -> int:
    """텍스트에서 검색 가능한 구체 앵커(숫자/약어/고유명사) 수를 센다."""
    if not text:
        return 0
    anchors: set = set()
    for m in _FINDABILITY_ANCHOR_RE.finditer(text):
        anchors.add(m.group())
    for ent in _FINDABILITY_KNOWN_ENTITIES:
        if ent in text:
            anchors.add(ent)
    return len(anchors)


def _validate_findability(post: str) -> tuple[int, Optional[str]]:
    """
    PR 10 — 첫 2문장 Findability 검사.

    반환: (anchor_count, warn_reason)
      anchor_count : 감지된 구체 앵커 수
      warn_reason  : None 이면 통과, 문자열이면 경고/게이트 사유

    게이트 정책:
      anchor ≥ 2 → 통과 (None)
      anchor = 1 → 경고만 (gate tag 는 호출측에서 판단)
      anchor = 0 → LOW_FINDABILITY 사유 반환
    """
    if not post:
        return 0, None
    head = _extract_first_two_sentences(post)
    count = _count_findability_anchors(head)
    if count >= 2:
        return count, None
    if count == 1:
        return count, (
            f"첫 2문장 검색 앵커 {count}개 — "
            "고유명사/숫자/기관명/지표 최소 2개 권장"
        )
    return count, (
        "첫 2문장에 검색 가능한 고유명사/숫자/기관명/지표 없음 — "
        "추상명사만으로 시작"
    )


# 근거 없는 일반론 의견 패턴 (칼럼체/보고서체 — 원칙 C)
_OPINION_PATTERNS = [
    "역사적으로",
    "전략이다",
    "압박이다",
    "낳기 쉽다",
    "낳을 것이다",
    "큰 파장을",
    "정세에 긴장을",
    "불러일으킬 가능성이 크다",
]

# 첫 문장 사실나열 패턴 (이걸로 시작하면 뉴스 후기 느낌)
_FACT_NARRATION_STARTS = [
    "라는 보도가 나왔다",
    "것으로 전해졌다",
    "것으로 알려졌다",
    "라고 밝혔다",
    "라고 전했다",
    "라고 보도했다",
    "다고 밝혔다",
    "다고 전했다",
]

# 과장 표현 → 약화 매핑
_TONE_SOFTENERS = {
    "직격탄": "영향",
    "불가피": "가능성",
    "급등": "상승",
    "급락": "하락",
    "붕괴": "하락",
    "폭락": "하락",
    "폭등": "급상승",
    "토해냈다": "줄었다",
    "충격": "영향",
    # 브리핑 냄새 — 조사 안전한 치환만
    "직접적인 타격": "타격",
    "가 더욱 중요해지고 있다": "가 갈린다",
}


# ─── 7대 검증 규칙 ────────────────────────────────────────────────────────

# 요약→의견→관건 3단 구조 감지용 패턴
_SUMMARY_OPINION_CRUX_PATTERNS = {
    "summary_starters": ["하려는 시도다", "의지를 보여준다", "로 해석된다", "의도가 드러난다"],
    "crux_endings": ["가 관건이다", "에 달려 있다", "가 결정된다", "관건이다", "달려 있다"],
}

# 추상적 reader_stake 감지 패턴
_ABSTRACT_STAKE_PATTERNS = [
    "중요한 의미",
    "큰 의미",
    "시사하는 바",
    "주목할 만",
    "영향을 미칠",
    "파급효과",
    "파장이",
    "주의 깊게",
    "면밀히",
]


def _validate_thesis_similarity(
    thesis: str, key_facts: list[str]
) -> Optional[str]:
    """규칙1: thesis가 key_facts(기사 요약)와 너무 유사하면 경고."""
    if not thesis or not key_facts:
        return None
    thesis_lower = thesis.strip().lower()
    for fact in key_facts:
        fact_lower = fact.strip().lower()
        # 단순 포함 관계 체크 (한쪽이 다른 쪽에 70% 이상 포함)
        if len(thesis_lower) > 10 and len(fact_lower) > 10:
            # 공통 단어 비율
            thesis_words = set(thesis_lower.split())
            fact_words = set(fact_lower.split())
            if thesis_words and fact_words:
                overlap = thesis_words & fact_words
                ratio = len(overlap) / min(len(thesis_words), len(fact_words))
                if ratio > 0.7:
                    return f"thesis가 key_fact와 유사 (overlap={ratio:.0%}): '{thesis[:40]}'"
    return None


def _validate_headline_restatement(first_line: str, key_facts: list[str]) -> Optional[str]:
    """규칙2: 첫 문장이 기사 제목/핵심팩트 재진술이면 경고."""
    if not first_line or not key_facts:
        return None
    fl = first_line.strip().lower()
    for fact in key_facts[:2]:  # 첫 2개 팩트만 비교
        fact_l = fact.strip().lower()
        if len(fl) > 10 and len(fact_l) > 10:
            fl_words = set(fl.split())
            fact_words = set(fact_l.split())
            if fl_words and fact_words:
                overlap = fl_words & fact_words
                ratio = len(overlap) / min(len(fl_words), len(fact_words))
                if ratio > 0.65:
                    return f"첫 문장이 기사 팩트 재진술 (overlap={ratio:.0%})"
    return None


def _validate_dead_patterns(post: str) -> list[str]:
    """규칙3: _WEAK_PATTERNS 기반 dead pattern 감지. 모든 매칭 반환."""
    found = []
    for pat in _WEAK_PATTERNS:
        if pat in post:
            found.append(pat)
    return found


def _validate_structure_detection(post: str) -> Optional[str]:
    """규칙4: 요약→의견→관건 3단 구조 감지."""
    has_summary = any(
        p in post for p in _SUMMARY_OPINION_CRUX_PATTERNS["summary_starters"]
    )
    has_crux = any(
        post.rstrip().endswith(p) or post.rstrip().endswith(p + ".")
        for p in _SUMMARY_OPINION_CRUX_PATTERNS["crux_endings"]
    )
    if has_summary and has_crux:
        return "요약→의견→관건 3단 구조 감지 (사설/칼럼체)"
    return None


def _validate_reader_stake(reader_stake: str) -> Optional[str]:
    """규칙5: reader_stake가 추상적이면 경고."""
    if not reader_stake:
        return "reader_stake 없음"
    for pat in _ABSTRACT_STAKE_PATTERNS:
        if pat in reader_stake:
            return f"reader_stake 추상적: '{pat}' 포함"
    # 길이가 너무 짧으면 추상적일 가능성
    if len(reader_stake.strip()) < 10:
        return "reader_stake 너무 짧음 (구체성 부족)"
    return None


def _validate_grok_fail_tags_gating(grok_eval: Optional["GrokEvalCard"]) -> Optional[str]:
    """규칙6: Grok fail_tags ≥ 2이면 게이팅 경고."""
    if not grok_eval:
        return None
    if len(grok_eval.fail_tags) >= 2:
        return (
            f"Grok fail_tags {len(grok_eval.fail_tags)}개 감지: "
            f"{grok_eval.fail_tags} → rewrite_scope={grok_eval.rewrite_scope}"
        )
    return None


def _validate_thesis_preservation(
    final_post: str, selected_thesis: Optional["ThesisCard"]
) -> Optional[str]:
    """규칙7: 최종 결과가 선택된 thesis 방향을 유지하는지 검증."""
    if not selected_thesis or not selected_thesis.thesis or not final_post:
        return None
    # thesis에서 핵심 명사/키워드 추출 (2글자 이상, 조사 제거)
    thesis_words = selected_thesis.thesis.split()
    # 한국어 조사 패턴 제거: 이/가/을/를/은/는/의/에/로/와/과 등
    import re as _re
    thesis_keywords = set()
    for w in thesis_words:
        # 끝에 붙은 한국어 조사 제거
        stem = _re.sub(r"[이가을를은는의에로와과도만까지에서으로]$", "", w)
        if len(stem) >= 2:
            thesis_keywords.add(stem)
    if not thesis_keywords:
        return None

    post_text = final_post
    matched = sum(1 for kw in thesis_keywords if kw in post_text)
    match_ratio = matched / len(thesis_keywords) if thesis_keywords else 0

    if match_ratio < 0.2:
        return (
            f"thesis 방향 이탈 가능: thesis 키워드 매칭률 {match_ratio:.0%} "
            f"(thesis: '{selected_thesis.thesis[:40]}')"
        )
    return None


def _run_all_validations(
    post: str,
    card: Optional["CandidateCard"] = None,
    selected_thesis: Optional["ThesisCard"] = None,
    grok_eval: Optional["GrokEvalCard"] = None,
) -> list[str]:
    """7대 검증 규칙 일괄 실행. 경고 목록 반환."""
    warnings: list[str] = []

    first_line = post.split("\n")[0].strip() if post else ""
    key_facts = card.key_facts if card else []

    # 규칙1: thesis 유사도
    if selected_thesis:
        w = _validate_thesis_similarity(selected_thesis.thesis, key_facts)
        if w:
            warnings.append(f"[V1-유사도] {w}")

    # 규칙2: 헤드라인 재진술
    w = _validate_headline_restatement(first_line, key_facts)
    if w:
        warnings.append(f"[V2-재진술] {w}")

    # 규칙3: dead patterns
    dead = _validate_dead_patterns(post)
    if dead:
        warnings.append(f"[V3-데드패턴] {len(dead)}개: {dead[:3]}")

    # 규칙4: 요약→의견→관건 구조
    w = _validate_structure_detection(post)
    if w:
        warnings.append(f"[V4-구조] {w}")

    # 규칙5: reader_stake 품질
    if selected_thesis:
        w = _validate_reader_stake(selected_thesis.reader_stake)
        if w:
            warnings.append(f"[V5-이해관계] {w}")

    # 규칙6: Grok fail_tags 게이팅
    w = _validate_grok_fail_tags_gating(grok_eval)
    if w:
        warnings.append(f"[V6-Grok게이팅] {w}")

    # 규칙7: thesis 보존
    w = _validate_thesis_preservation(post, selected_thesis)
    if w:
        warnings.append(f"[V7-논지보존] {w}")

    return warnings


def _validate_final_post(
    post: str,
    short: str,
    certainty_level: Optional[str] = None,
    mode: Optional[str] = None,
) -> tuple[str, str, list[str], list[str]]:
    """마감 결과 검증 및 자동 보정. (post, short, warnings, gate_fails) 반환.

    gate_fails: 게이트 실패 태그 목록. 비어 있으면 통과.
      - WEAK_OPENER: 첫 문장 사실나열 / 과장
      - DEAD_ENDING: 금지 마감 패턴
      - BRIEFING_SMELL: 브리핑 장황 표현 2개+
      - OPINION_LEAK: 근거 없는 일반론 2개+ (기준 완화: 1→2)
      - COMPLEX_SENTENCE: 문장 구조 복잡 (쉼표/접속사 과다)
        · VERIFY mode: 1개부터 게이트 (브리핑체 복잡문 차단)
        · EXPLAIN / JUDGMENT: 2개부터 게이트 (경고까지만)
      - STRUCTURE_COLUMN: 요약→의견→관건 3단 사설체 구조
      - LOW_CONFIDENCE_OVERREACH: certainty 미확인/상충인데
        _SPECULATIVE_MOTIVE_PATTERNS가 본문에 2개 이상 침투
    """
    warnings: list[str] = []
    gate_fails: list[str] = []

    # 첫 문장 사실나열 감지 (뉴스 후기 느낌의 원흉)
    first_line = post.split("\n")[0].strip() if post else ""
    for pattern in _FACT_NARRATION_STARTS:
        if pattern in first_line:
            warnings.append(f"첫 문장 사실나열 패턴: '{pattern}' — 해석 선행 필요")
            gate_fails.append("WEAK_OPENER")
            break

    # 첫 문장 길이 이중 게이트 — 즉시 이해성 핵심
    # 95점 기준: 45자가 권장, 60자 초과는 게이트 실패 (기존 75자 → 60자로 강화)
    if first_line and "WEAK_OPENER" not in gate_fails:
        first_sent = first_line.split(".")[0] + "." if "." in first_line else first_line
        sent_len = len(first_sent)
        if sent_len > 60:
            warnings.append(f"첫 문장 과장 ({sent_len}자) — 60자 초과, 재작성 필요")
            gate_fails.append("WEAK_OPENER")
        elif sent_len > 45:
            warnings.append(f"첫 문장 길이 경고 ({sent_len}자) — 45자 이내 권장")

    # 첫 문장 배경 설명 시작 패턴 게이트 — "~이후 ...", "~보도한 ..." 구조 차단
    # 처음 20자 안에 배경 설명 연결어가 있으면 핵심 명제 선행이 아님
    if first_line and "WEAK_OPENER" not in gate_fails:
        first_sent = first_line.split(".")[0] if "." in first_line else first_line
        head = first_sent[:20]
        _background_starts = ["이후 ", "보도한 ", "보도된 ", "전해진 ", "알려진 "]
        for bg in _background_starts:
            if bg in head:
                warnings.append(
                    f"첫 문장 배경 설명 시작 ('{bg.strip()}') — 핵심 명제 선행 필요"
                )
                gate_fails.append("WEAK_OPENER")
                break

    # 첫 문장 접속 구조 게이트 — 배경 설명/종속절 시작 차단
    # 접속 표현 2개+ 또는 (쉼표 2개+ AND 접속 1개+) → 첫 문장이 사실+해석+전망 혼합 신호
    if first_line and "WEAK_OPENER" not in gate_fails:
        first_sent = first_line.split(".")[0] if "." in first_line else first_line
        _first_connectors = ["면서", "인데", "하고 ", "하며", "지만", "반면", "가운데", "에도 불구"]
        first_connector_hits = sum(1 for c in _first_connectors if c in first_sent)
        first_comma = first_sent.count(",")
        if first_connector_hits >= 2 or (first_comma >= 2 and first_connector_hits >= 1):
            warnings.append(
                f"첫 문장 접속 구조 과다 (접속={first_connector_hits}, 쉼표={first_comma}) "
                "— 배경 설명/종속절 시작"
            )
            gate_fails.append("WEAK_OPENER")

    # 문장 구조 복잡도 감지 — 리뷰체의 원인
    _connectors = ["면서 ", "인데 ", "하고 ", "하며 ", "지만 ", "반면 "]
    sentences = [s.strip() for s in post.replace("\n", " ").split(".") if s.strip()]
    complex_hits = 0
    for sent in sentences:
        comma_count = sent.count(",")
        connector_count = sum(1 for c in _connectors if c in sent)
        if comma_count >= 3 or connector_count >= 2:
            complex_hits += 1
    if complex_hits >= 1:
        warnings.append(f"복잡한 문장 {complex_hits}개 (쉼표/접속사 과다)")
        # VERIFY 모드: 1개부터 게이트 (브리핑체 복잡문 전면 차단)
        # EXPLAIN / JUDGMENT: 기존대로 2개 이상에서만 게이트
        if mode == MODE_VERIFY and complex_hits >= 1:
            gate_fails.append("COMPLEX_SENTENCE")
        elif complex_hits >= 2:
            gate_fails.append("COMPLEX_SENTENCE")

    # 금지 마무리 패턴 감지
    for banned in _BANNED_ENDINGS:
        if post.rstrip().endswith(banned) or post.rstrip().endswith(banned + "."):
            warnings.append(f"final_post 금지 마감 패턴: '{banned}'")
            gate_fails.append("DEAD_ENDING")
            break
        if short and (short.rstrip().endswith(banned) or short.rstrip().endswith(banned + ".")):
            warnings.append(f"final_short 금지 마감 패턴: '{banned}'")
            break

    # 과장/브리핑 표현 자동 약화 (긴 패턴 우선 — 부분 치환 방지)
    for strong, soft in sorted(
        _TONE_SOFTENERS.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if strong in post:
            post = post.replace(strong, soft)
            warnings.append(f"자동 약화: '{strong}' → '{soft}'")
        if short and strong in short:
            short = short.replace(strong, soft)

    # 뻔한 표현 경고 (본문 전체 검사) — 2개 이상이면 게이트 실패
    briefing_hits = []
    for pat in _WEAK_PATTERNS:
        if pat in post:
            briefing_hits.append(pat)
    if briefing_hits:
        warnings.append(f"뻔한 표현 감지: {', '.join(briefing_hits[:3])}")
        if len(briefing_hits) >= 2:
            gate_fails.append("BRIEFING_SMELL")

    # 일반론 의견 패턴 감지 (원칙 C) — 1개는 경고, 2개 이상이면 게이트
    opinion_hits = [pat for pat in _OPINION_PATTERNS if pat in post]
    if opinion_hits:
        warnings.append(f"일반론 의견 패턴: {opinion_hits[:3]}")
        if len(opinion_hits) >= 2:
            gate_fails.append("OPINION_LEAK")

    # 요약→의견→관건 3단 사설체 감지 → STRUCTURE_COLUMN 게이트
    has_summary_start = any(
        p in post for p in _SUMMARY_OPINION_CRUX_PATTERNS["summary_starters"]
    )
    stripped = post.rstrip().rstrip(".")
    has_crux_end = any(
        stripped.endswith(p) for p in _SUMMARY_OPINION_CRUX_PATTERNS["crux_endings"]
    )
    if has_summary_start and has_crux_end:
        warnings.append("요약→의견→관건 3단 구조 (사설체) 감지")
        gate_fails.append("STRUCTURE_COLUMN")

    # 저신뢰 과해석 본문 침투 → LOW_CONFIDENCE_OVERREACH 게이트
    # 저신뢰 기사는 1개 등장만으로도 게이트 (사용자 지시: 강한 제한)
    if certainty_level in ("미확인", "상충"):
        post_lower = post.lower()
        motive_hits = [
            p for p in _SPECULATIVE_MOTIVE_PATTERNS if p.lower() in post_lower
        ]
        if len(motive_hits) >= 1:
            warnings.append(
                f"저신뢰 과해석 본문 침투 ({len(motive_hits)}개): {motive_hits[:3]}"
            )
            if "LOW_CONFIDENCE_OVERREACH" not in gate_fails:
                gate_fails.append("LOW_CONFIDENCE_OVERREACH")

        # VERIFY 과해석 — 구조 해석 / 외교 시나리오 확장 / 채널 단정 축
        # 1개 등장만으로도 실패. "무슨 일이 벌어질 수 있다" 금지.
        overreach_hits = [
            p for p in _VERIFY_OVERREACH_PATTERNS if p in post
        ]
        if len(overreach_hits) >= 1:
            warnings.append(
                f"VERIFY 구조해석 본문 침투 ({len(overreach_hits)}개): "
                f"{overreach_hits[:3]}"
            )
            if "LOW_CONFIDENCE_OVERREACH" not in gate_fails:
                gate_fails.append("LOW_CONFIDENCE_OVERREACH")

        # VERIFY 첫 줄: 1문장 1주장만. "A인지 B인지 C가 결정한다" 금지.
        if first_line and "WEAK_OPENER" not in gate_fails:
            first_sent = first_line.split(".")[0] if "." in first_line else first_line
            verify_opener_hits = [
                p for p in _VERIFY_WEAK_OPENER_PATTERNS if p in first_sent
            ]
            if verify_opener_hits:
                warnings.append(
                    f"VERIFY 첫 문장 이중분기 수사: {verify_opener_hits[:2]}"
                )
                gate_fails.append("WEAK_OPENER")

        # VERIFY 본문 문장 수 하드 캡 — 최대 3문장.
        # 구조 해석을 더 얹으려면 문장 수가 늘 수밖에 없으므로 구조적으로 차단.
        post_sentences = [
            s.strip()
            for s in post.replace("\n", " ").split(".")
            if s.strip()
        ]
        if len(post_sentences) > 3:
            warnings.append(
                f"VERIFY 본문 문장 수 초과 ({len(post_sentences)}문장) — "
                "최대 3문장 (지금 나온 말 / 아직 확인 안 된 것 / "
                "무엇이 나오면 진짜인지)"
            )
            if "LOW_CONFIDENCE_OVERREACH" not in gate_fails:
                gate_fails.append("LOW_CONFIDENCE_OVERREACH")

        # PR 6 — VERIFY 짧은 버전 하드 캡 — 최대 2문장.
        # 저신뢰 기사 요약에 해설문이 다시 기어 들어오는 걸 구조적으로 차단.
        # 허용 구조: '주장 1' + '확인 포인트 1'.
        if short:
            short_sentences = [
                s.strip()
                for s in short.replace("\n", " ").split(".")
                if s.strip()
            ]
            if len(short_sentences) > 2:
                warnings.append(
                    f"VERIFY 짧은 버전 문장 수 초과 "
                    f"({len(short_sentences)}문장) — 최대 2문장 "
                    "(주장 1 + 확인 포인트 1)"
                )
                if "LOW_CONFIDENCE_OVERREACH" not in gate_fails:
                    gate_fails.append("LOW_CONFIDENCE_OVERREACH")

    # final_short가 final_post 첫 문장과 동일한지 체크
    first_sentence = post.split(".")[0].split("\n")[0].strip()
    short_first = short.split(".")[0].split("\n")[0].strip() if short else ""
    if first_sentence and short_first and first_sentence == short_first:
        warnings.append("final_short 첫 문장이 final_post와 동일")

    # PR 9 — Reader Reward Layer: 마지막 문장 독자 보상 검사.
    # post 마지막 문장에 SAVE/SHARE/FOLLOW 시그널이 있으면 통과,
    # 없으면 short 를 보조로 본다. 둘 다 없을 때만 NO_READER_REWARD 경고.
    # WARN-only — _STRONG_FAIL_TAGS 에 포함시키지 않는다 (재생성 루프 금지).
    _, _reward_warn = _validate_last_line_reward(post, short)
    if _reward_warn:
        warnings.append(_reward_warn)
        if "NO_READER_REWARD" not in gate_fails:
            gate_fails.append("NO_READER_REWARD")

    # PR 10 — Findability Layer: 첫 2문장 검색 앵커 검사.
    # anchor ≥ 2 통과, 1 경고만, 0 LOW_FINDABILITY gate tag.
    # WARN-only — _STRONG_FAIL_TAGS 미편입 (재생성 루프 금지).
    _anchor_count, _find_warn = _validate_findability(post)
    if _find_warn:
        warnings.append(_find_warn)
        if _anchor_count == 0 and "LOW_FINDABILITY" not in gate_fails:
            gate_fails.append("LOW_FINDABILITY")

    return post, short, warnings, gate_fails


def _parse_final_post(
    raw: str,
    certainty_level: Optional[str] = None,
    mode: Optional[str] = None,
) -> Optional[FinalPost]:
    """AI 응답 JSON → FinalPost. 검증 포함.

    certainty_level이 주어지면 LOW_CONFIDENCE_OVERREACH 게이트를 활성화.
    mode(VERIFY/EXPLAIN/JUDGMENT)가 주어지면 mode별 게이트 강도를 적용
    (VERIFY 는 COMPLEX_SENTENCE 1개부터 게이트).
    """
    try:
        text = raw.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
        data = json.loads(text)
        post = str(data.get("final_post", ""))
        short = str(data.get("final_short", ""))
        if not post:
            return None

        # 검증 및 자동 보정
        post, short, warnings, gate_fails = _validate_final_post(
            post, short, certainty_level=certainty_level, mode=mode
        )
        for w in warnings:
            logger.warning(f"[마감검증] {w}")

        return FinalPost(
            final_post=post,
            final_short=short,
            gate_fails=gate_fails,
            reward_type=_resolve_reward_type(post, short),
        )
    except Exception as e:
        logger.warning(f"FinalPost 파싱 오류: {e}")
        return None
