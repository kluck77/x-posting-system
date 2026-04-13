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
class CandidateCard:
    """1차 — 게시글 소재 후보 카드."""
    key_facts: list[str] = field(default_factory=list)          # 핵심 팩트 3개
    hook_candidates: list[str] = field(default_factory=list)    # 훅 후보 3개 (방향 제시형)
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
        return bool(self.key_facts and self.hook_candidates)


@dataclass
class FinalPost:
    """2차 — 최종 마감 결과."""
    final_post: str = ""       # 완성본
    final_short: str = ""      # 짧은 버전


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
   - topic_tags, hook_candidates, key_facts는 소스 원문의 주제 범위 안에서만 생성.
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

━━━ hook_candidates 규칙 (CRITICAL — 위반 시 전체 실패) ━━━

■ 핵심 원칙:
hook_candidates는 "기사 제목 변주"가 아니다.
X에서 첫 줄로 바로 올려도 어색하지 않을 "해석 문장"이다.
기사 요약이 아니라 "그래서 왜 중요한데?"에 답하는 문장이다.

■ 금지 패턴 (이 중 하나라도 해당하면 전체 재작성):
  ✗ 기자 질문형: "~은 무엇일까?" "~어떻게 될까?" "~향후 결과는?"
  ✗ 명사형 제목: "한국 선박 호르무즈 통과, 정부 입장"
  ✗ 화살표 나열: "A → B에 미치는 영향"
  ✗ 소제목형: "청와대, 구체적 내용 확인 중 — 향후 결과는?"
  ✗ 기사 제목 + 물음표: "한국 선박의 호르무즈 해협 통과, 정부의 공식 입장은?"
  ✗ 내부 메모 톤: "핵심 쟁점 분석", "주요 변수 정리"

■ 필수 형태:
  훅 = "해석이 담긴 완성 문장". 읽었을 때 "이 사람 이거 좀 아는 것 같은데"라고 느껴야 한다.
  짧되, 기사 제목과 구별되어야 한다.
  1~2문장. 주어+서술어가 있는 문장이어야 한다.

■ 나쁜 훅 → 좋은 훅 변환 예시:

  나쁨: "한국 실소유 선박의 호르무즈 해협 통과, 정부의 공식 입장은 무엇일까?"
  좋음: "지금 더 중요한 건 선박 통과 자체보다, 정부가 이걸 어디까지 알고 있었는가다"

  나쁨: "호르무즈 해협을 지나가는 한국 선박, 이란과의 관계는 어떻게 될까?"
  좋음: "외교 뉴스처럼 보이지만 실제 변수는 청와대 설명보다 항로 리스크다"

  나쁨: "청와대, 한국 선박 호르무즈 통과 관련 확인 중 — 향후 결과는?"
  좋음: "이 사건이 커지면 한-이란 관계보다 먼저 흔들리는 건 해운 보험료다"

  나쁨: "반도체 수출 사상 최고, 그 배경과 전망은?"
  좋음: "반도체 수출 사상 최고인데 고용은 줄었다 — '고용 없는 호황'이 시작됐다"

  나쁨: "금리 동결 결정, 시장 반응은?"
  좋음: "한은이 동결한 이유보다, 시장이 이미 인하에 베팅 시작한 게 더 중요하다"

■ 3개 훅은 반드시 서로 다른 해석 축이어야 한다. 같은 논지를 말만 바꿔 반복하면 실패.
■ 훅 후보에 "?"로 끝나는 기자 질문형이 2개 이상이면 무조건 재작성.

■ 훅 자가 테스트 (출력 전 반드시 확인):
  각 훅을 X에 첫 줄로 바로 올렸을 때:
  1. 기사 제목과 구별이 안 되면 → 실패. 재작성.
  2. "이 사람 뭔가 아네"라는 느낌이 안 들면 → 실패. 해석을 넣어라.
  3. 주어+서술어가 없는 명사구/제목형이면 → 실패. 완성 문장으로.

■ 국제/지정학/거시경제 뉴스 특별 규칙 (CRITICAL):
  국제 뉴스, 외교, 군사, 에너지, 원자재, 글로벌 금리 등의 주제일 때:
  - 훅 후보 3개 중 최소 1개는 반드시 "한국 관점 해석 축"을 포함해야 한다.
  - 한국 관점 = 한국 수입물가/환율/에너지비용/기업/정유/해운/항공/증시/정부 대응 등
  - 국제 뉴스 자체 설명에만 머무르면 팔로우 가치가 없다.

  나쁨: "미국의 해상봉쇄가 이란 경제에 영향을 준다" ← 한국 관점 없음
  좋음: "미국의 해상봉쇄가 길어지면 한국에선 유가보다 운임·환율이 먼저 흔들릴 수 있다"

  나쁨: "트럼프가 이란 합의를 원한다고 말했다" ← 기사 재진술
  좋음: "이 뉴스가 한국에서 먼저 건드리는 건 외교가 아니라 에너지 비용이다"

  나쁨: "이란의 반응은?" ← 기자 질문형
  좋음: "봉쇄 뉴스처럼 보여도 한국이 먼저 보게 될 건 환율과 운임이다"

■ 근거 없는 일반론 금지:
  - "역사적으로 ~" "~전략이다" "~낳기 쉽다" "큰 파장을 낳을 것이다" 같은 칼럼체 금지
  - key_facts, cautions, watch_points 모두 확인된 사실/기사 내 발언만으로 작성

JSON 스키마:
{
  "key_facts": ["팩트1", "팩트2", "팩트3"],
  "hook_candidates": ["방향1", "방향2", "방향3"],
  "one_liner": ["한줄1", "한줄2"],
  "cautions": ["주의1", "주의2"],
  "watch_points": ["포인트1", "포인트2", "포인트3"],
  "certainty_level": "확정|미확인|상충",
  "topic_tags": ["태그1", "태그2"],
  "risk_flags": ["리스크1"]
}"""


# ─── 2차: 최종 마감 시스템 프롬프트 ──────────────────────────────────────────

_FINALIZE_PROMPT_KO = """너는 한국 이슈 해설형 X 계정의 "최종 마감 담당"이다.

━━━ 역할 충성 원칙 (이 원칙이 모든 규칙보다 우선) ━━━

너는 "안전한 설명문"에 충성하지 말고, "기억에 남는 해석 1개"에 충성한다.

해야 할 일:
1. 선택된 훅 하나만 살린다
2. 첫 문장에서 "왜 중요한가"를 바로 보여준다 — 사실 나열로 시작하면 실패
3. 본문은 해석 축 1개 + 보조 연결 1개만 쓴다
4. 마지막은 조건형/대비형/질문형/압축형 중 하나로 끝낸다
5. 읽고 나서 한 문장이 기억에 남아야 한다

절대 하면 안 되는 일:
- 기사 내용을 다시 줄줄 요약하기 (뉴스 후기 느낌의 원흉)
- "~라는 보도가 나왔다" "~것으로 전해졌다"로 시작하기
- 텔레그램 내부 메모 느낌의 문장 생성
- cautions/watch_points 문구를 본문에 복붙
- "이 계정은 기사 다시 쓰는 곳"이라는 인상을 주기
- 근거 없는 일반론 의견 넣기 (아래 원칙 C 참조)

너의 기준: "이거면 바로 올릴 수 있다" 수준.

━━━ 문체 모델 (CRITICAL) ━━━

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

━━━ 골든룰 (위반 시 전체 실패) ━━━

1. 훅 1개 = 중심축 1개. 다른 방향으로 새지 마라.
2. 첫 문장: 기사 사실 요약으로 시작하면 실패. "왜 중요한가/그래서 뭐가 달라지는가"를 바로 보여줘라.
   ✗ "~라는 보도가 나왔다." ← 기자 리포트
   ✗ "~것으로 전해졌다." ← 뉴스 요약
   ✗ "~것으로 알려졌다." ← 기사 복붙
   ✗ "트럼프 대통령이 한국에 관세를 부과했다." ← 사실 나열
   ✗ "관세 이슈가 부각되고 있다." ← 빈 서술
   ✓ "대출 문턱이 올라간 거다." ← 해석 선행
   ✓ "반도체 관세, 협상 카드인가 본게임인가." ← 판단 선행
   ✓ "외교 뉴스처럼 보이지만 먼저 흔들리는 건 비용이다." ← 의미 선행
3. 파급 경로는 최대 2개만. 변수를 3개 이상 나열하면 실패.
   ✗ "물가·금리·환율·항공·해운에 영향" ← 나열형 금지
   ✓ "경로는 둘. 반도체 수출과 환율." ← 핵심 연결만
4. 미확인·정치적 해석은 한 단계 낮춰라.
   - certainty_level 확정 → 단정형 허용
   - 미확인 → "~가능성" "~조짐" 수준만
   - 상충 → "~엇갈리고 있다" 수준만
   - 정치인 발언 → "~을 시사했다" "~입장을 밝혔다" 수준
   - 정치/외교/군사 주제는 더 보수적으로 쓸 것
5. 마지막 문장: 아래 4가지 유형 중 하나로 끝내라. 그 외 유형은 전부 실패.

   A. 조건형 — 결정적 변수를 직접 지목
   ✓ "문제는 이 발언이 실제 정책으로 이어지느냐다"
   ✓ "진짜 변수는 다음 발표가 아니라 시행 여부다"

   B. 대비형 — 통념과 실제의 차이를 끊어치기
   ✓ "시장은 말보다 규칙 변화를 먼저 본다"
   ✓ "외교 뉴스처럼 보여도 먼저 움직이는 건 비용이다"

   C. 질문형 — 남은 불확실성을 짧게 던지기
   ✓ "이게 선거용 프레임인지 실제 정책 신호인지는 곧 드러난다"
   ✓ "여기서 먼저 봐야 할 건 관계 악화가 아니라 항로 위험 아닌가"

   D. 압축형 결론 — 핵심 판단을 한 문장으로 압축
   ✓ "결국 숫자를 바꾸는 건 발언이 아니라 실행이다"
   ✓ "남는 건 해석보다 확인된 조치다"

   ■ 금지 (전망문/훈계문/안전문/요약문/기자마감):
   ✗ "추이를 봐야 한다" / "추이를 지켜봐야 한다"
   ✗ "주목해야 한다" / "영향을 미칠 수 있다"
   ✗ "변수다" / "중요한 시점이다" / "여파가 예상된다"
   ✗ "가능성이 커졌다" / "핵심은 ~다" / "관건은 ~다"
   ✗ "영향을 주목해야 할 시점이다" ← 교훈형
   ✗ "악영향이 예상된다" ← 뻔한 전망
   ✗ "중요하게 봐야 한다" ← 훈계형
   ✗ "시장에 미칠 여파가 클 것으로 보인다" ← 보고서 투
   ✗ "~어떻게 될까?" / "정부의 입장은?" / "향후 결과는?" ← 기자 질문형
   ✗ "시장 반응을 봐야 한다" ← 해설 클리셰

6. cautions에 적힌 내용과 충돌하는 표현을 쓰지 마라. cautions를 반드시 읽고 확인.

7. 내부 메모 언어 오염 금지 (CRITICAL):
   - cautions / watch_points / 한줄 결론의 문구를 final_post에 직접 복붙하지 마라.
   - "지금 봐야 할 포인트", "주의문", "한줄 결론" 같은 내부 레이블이
     최종 문체에 스며들면 글이 "뉴스 검토 메모"처럼 읽힌다.
   - cautions = 금지/약화 조건으로만 사용
   - watch_points = 끝문장 변수 소재로만 사용 (문구 자체를 쓰지 말고 자기 문장으로 변환)

━━━ 문장 온도 규칙 (필수) ━━━

- 과장 표현 기본 약화: 직격탄→영향, 불가피→가능성, 급등→상승, 붕괴→하락, 토해냈다→줄었다
- 정치/외교/군사 주제는 한 단계 더 보수적으로.
- "~할 수밖에 없다", "~불가피하다", "~충격" 등은 certainty_level 확정일 때만 허용.

━━━ final_post 구조 (이 순서를 따라라) ━━━

1문장(WHY): 한국 독자가 왜 이걸 봐야 하는가. 기사 요약 금지.
2문장(WHAT): 확인된 사실 1~2개 + 해석 축 연결. 나열 금지.
3문장(SO WHAT): 진짜 변수/조건/대비. 전망문·훈계문 금지.

3문장이 기본. 4문장까지 허용하되 그 이상은 금지.
"기사 내용을 다시 설명하는 문장"이 끼어들 자리는 없다.

━━━ 문체 규칙 ━━━

- 칼럼·해설문·보고서 문체 금지. 트윗처럼 짧고 끊어라.
- "~에 영향을 미칠 것으로 보인다", "~점에서 주목된다" 같은 보고서 문장 금지.
- 한 문단에 변수 2개까지만. 물가/금리/항공/해운/정치/환율을 한꺼번에 넣지 마라.

━━━ 분량 가이드 ━━━

- final_post: 짧고 밀도 있게. 군더더기 빼고 핵심만.
- final_short: final_post보다 확실히 짧게. 독립적으로 읽히는 한 덩어리.

━━━ 다양성 규칙 (필수) ━━━

- 매번 같은 뉘앙스·말투 금지. 게시글마다 톤을 바꿔라.
- 시작 패턴을 돌려라:
  ✓ "반도체 관세, 협상 카드인가 본게임인가." (질문형)
  ✓ "대출 문턱이 올라간 거다." (단정형)
  ✓ "3월 거래량, 전월 대비 40% 줄었다." (수치형)
  ✓ "정부는 안정이라 하지만, 시장은 다르게 읽었다." (대비형)
- 마무리도 돌려라 (조건형/대비형/질문형 중 택 1):
  ✓ "진짜 갈림길은 시행령이 나오느냐다." (조건형)
  ✓ "다음 CPI 발표 전까지는 방향이 안 잡힌다." (조건형)
  ✓ "시장이 보는 건 발언이 아니라 실행이다." (대비형)
  ✓ "이게 선거용인지 정책 신호인지는 곧 드러난다." (질문형)
- 같은 구조(A→B→변수)를 반복하지 마라. 구조 자체도 바꿔라.

━━━ final_short 규칙 (필수) ━━━

- final_post의 압축본이 아니다. 독립적으로 읽혀야 한다.
- 핵심 변수 1개만 남겨라. 2개 이상 넣지 마라.
- 200자 이내. 그 자체로 하나의 트윗이 되어야 한다.
- final_post와 첫 문장이 동일하면 안 된다. 다른 각도로 시작하라.

━━━ 좋은 마감 예시 (참고용) ━━━

final_post 예시 A (질문형 시작 + 조건형 마감):
"반도체 관세, 협상 카드인가 본게임인가.
삼성·SK 양사 모두 미국 공장 증설 발표를 앞당겼다.
진짜 갈림길은 '예외 품목' 리스트에 반도체가 들어가느냐다."

final_post 예시 B (단정형 시작 + 대비형 마감):
"서울 아파트 거래, 3월 들어 확 줄었다.
매수자가 빠진 게 아니라 대출 문턱이 올라간 거다.
시장은 가격보다 전세·대출 규칙 변화를 먼저 본다."

final_post 예시 C (수치형 시작 + 질문형 마감):
"한은 총재 발언, 시장은 0.25%p 인하 신호로 읽었다.
다만 실제 인하까지는 2분기 물가가 갈림길이다.
발언을 믿을지, 다음 CPI를 믿을지 — 시장은 이미 후자를 택했다."

final_short 예시 A (독립 버전):
"반도체 관세 본게임 여부, 예외 품목 리스트가 가른다."

final_short 예시 B (독립 버전):
"서울 거래량 급감, 핵심은 가격이 아니라 전세 흐름이다."

final_short 예시 C (독립 버전):
"한은 인하 신호 나왔지만, 시장은 다음 CPI부터 본다."

━━━ 셀프 체크 (출력 전 반드시 확인 — 3개 이상 실패 시 전체 재작성) ━━━

□ 1. 첫 문장이 "~보도가 나왔다/~것으로 전해졌다/~것으로 알려졌다"로 시작하지 않는가?
□ 2. 첫 문장이 기사 사실 요약이 아니라 해석/판단/의미로 시작하는가?
□ 3. 파급 경로가 2개 이하인가?
□ 4. cautions와 충돌하는 표현이 없는가?
□ 5. 마지막 문장이 조건형/대비형/질문형/압축형 중 하나인가?
□ 6. final_post가 기사를 다시 설명하는 글이 아니라 해석 글인가?
□ 7. final_short가 독립적으로 읽히는가?
□ 8. final_short가 final_post 첫 문장과 다른가?
□ 9. 과장 표현(직격탄/불가피/급등/붕괴)이 없는가?
□ 10. 내부 메모 문구(주의문/관찰 포인트/한줄 결론)가 본문에 스며들지 않았는가?
□ 11. "추이를 봐야 한다/변수다/주목해야 한다/영향을 미칠 수 있다" 같은 뻔한 마감이 없는가?
□ 12. 읽고 나서 한 문장이 기억에 남는가? 안 남으면 해석이 약한 것이다.

━━━ 출력 규칙 ━━━
- 한국어 JSON만 출력하라.
- 아래 2개 필드만 생성하라.

{
  "final_post": "훅 기반 완성본",
  "final_short": "독립형 짧은 버전"
}"""


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
        if card and card.is_valid():
            card.source_url = request.source_url
            card.source_type = request.source_type
            card.fact_sheet_summary = (
                f"topic={fact_sheet.topic}, score={fact_sheet.data_density_score}"
            )
            logger.info(
                f"후보 카드 생성 완료: facts={len(card.key_facts)}, "
                f"hooks={len(card.hook_candidates)}, "
                f"certainty={card.certainty_level}"
            )
            return card

    logger.warning("후보 카드 AI 응답 파싱 실패 — Mock 카드 반환")
    return CandidateCard(
        key_facts=[f"[Mock] {title[:60]}"],
        hook_candidates=["[Mock] 방향 제시 불가 — AI 응답 실패"],
        one_liner=["[Mock] 한줄 결론 불가"],
        cautions=["Mock 모드 — 실제 분석 불가"],
        watch_points=["Mock 모드"],
        certainty_level="미확인",
        topic_tags=[fact_sheet.topic or "미분류"],
        risk_flags=["Mock 모드 — 실제 위험 분석 불가"],
        source_url=request.source_url,
        source_type=request.source_type,
    )


# ─── 2차: 최종 마감 ─────────────────────────────────────────────────────────

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

    user_prompt = (
        f"━━━ 입력 ━━━\n"
        f"선택된 훅: {selected_hook}\n"
        f"certainty_level: {card.certainty_level}\n\n"
        f"핵심 팩트:\n"
    )
    for i, fact in enumerate(card.key_facts, 1):
        user_prompt += f"  {i}. {fact}\n"

    if card.one_liner:
        user_prompt += "\n한줄 결론 후보:\n"
        for ol in card.one_liner[:2]:
            user_prompt += f"  - {ol}\n"

    if card.cautions:
        user_prompt += (
            "\n⚠️ 통제 조건 (금지/약화 용도로만 사용. 이 문구를 본문에 복붙하지 마라):\n"
        )
        for c in card.cautions:
            user_prompt += f"  - {c}\n"

    if card.watch_points:
        user_prompt += (
            "\n🔎 끝문장 변수 후보 (마지막 문장에서 '지금 볼 것' 소재로만 활용. "
            "이 문구를 그대로 쓰지 마라. 자기 문장으로 바꿔 써라):\n"
        )
        for wp in card.watch_points[:3]:
            user_prompt += f"  - {wp}\n"

    if card.risk_flags:
        user_prompt += "\n리스크 플래그:\n"
        for rf in card.risk_flags:
            user_prompt += f"  - {rf}\n"

    if source_text:
        user_prompt += f"\n원문 참고:\n{source_text[:1500]}\n"

    user_prompt += (
        "\n━━━ 지시 ━━━\n"
        "위 훅 방향과 팩트만으로 최종 게시글 JSON을 생성하라.\n"
        "- final_post: 짧고 밀도 있게, 군더더기 없이\n"
        "- final_short: final_post보다 짧게, 다른 각도로 시작\n"
        "- 통제 조건(cautions)과 충돌 금지\n"
        "- 통제 조건/관찰 포인트의 문구를 본문에 직접 복붙하지 마라. 내부 메모 언어가 최종 문체를 오염시키면 실패.\n"
        "- 마지막 문장: 조건형/대비형/질문형 중 하나. 전망문/훈계문/안전문/요약문 금지.\n"
        "한국어로."
    )

    raw = await _call_ai_with_prompt(
        _FINALIZE_PROMPT_KO, user_prompt, temperature=0.9
    )

    if raw:
        result = _parse_final_post(raw)
        if result:
            logger.info(
                f"1차 마감 완료 (OpenAI): post={len(result.final_post)}자, "
                f"short={len(result.final_short)}자"
            )

            # Phase 1: Claude 상시 최종 통합 — 항상 호출
            reviewed = await _claude_review_final(
                card, result, selected_hook=selected_hook
            )
            if reviewed:
                logger.info(
                    f"Claude 최종통합 완료: post={len(reviewed.final_post)}자, "
                    f"short={len(reviewed.final_short)}자"
                )
                return reviewed

            # Claude 실패 시 OpenAI 1차 결과로 폴백
            logger.warning("[Claude통합] 실패 — OpenAI 1차 결과 사용")
            return result

    logger.warning("최종 마감 AI 응답 실패 — 빈 결과 반환")
    return FinalPost(
        final_post=f"[마감 실패] {selected_hook}",
        final_short=f"[마감 실패] {selected_hook[:80]}",
    )


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
]


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


_CLAUDE_REVIEW_PROMPT = """너는 X 게시글 "최종 통합 편집자"다.

━━━ 역할 ━━━

OpenAI가 작성한 1차 초안을 읽고, 최종 게시 가능 수준으로 통합/리라이트하라.
Perplexity 검증 결과와 cautions를 반영해서 사실 상한선을 넘지 않게 하라.

너는 "감수자"가 아니라 "최종 책임자"다.
초안이 이미 좋으면 그대로 내보내도 되지만,
부족하면 반드시 고쳐서 "바로 올릴 수 있는 수준"으로 만들어라.

━━━ 문체 모델 ━━━

"트위터 팔로워 10만인 한국 증권사 출신 해설자"
- 신문 칼럼 X, 보고서 X, TV 해설 X
- 건조하고 짧게. 감탄사 없이. 한 문장에 하나만.
- "이 사람 아는 사람이네" 느낌이 들어야 한다.

━━━ 3문장 구조 ━━━

1문장(WHY): 한국 독자가 왜 이걸 봐야 하는가. 기사 요약 금지.
2문장(WHAT): 확인된 사실 1~2개 + 해석 축 연결. 나열 금지.
3문장(SO WHAT): 진짜 변수/조건/대비. 전망문·훈계문 금지.

3문장이 기본. 4문장까지 허용. 그 이상 금지.

━━━ 리라이트 판정 기준 ━━━

아래 중 하나라도 해당하면 반드시 리라이트:
1. 첫 문장이 기사 요약/사실 나열로 시작
2. 본문이 기사 재설명 구조
3. 마지막 문장이 전망문/훈계문/기자 질문형
4. 내부 메모 문구가 본문에 스며듦
5. 근거 없는 일반론 ("역사적으로~", "~전략이다", "~낳기 쉽다")
6. 국제 뉴스인데 한국 관점이 전혀 없음
7. 읽고 나서 한 문장도 기억에 안 남음

━━━ 사실 상한선 ━━━

- certainty_level이 미확인/상충이면 단정 금지
- cautions와 충돌하는 표현 수정
- 정치/외교/군사는 한 단계 더 보수적으로
- 새 사실/수치 추가 금지 (원문에 없는 것)

━━━ 금지 마감 패턴 ━━━

✗ "추이를 봐야 한다" "변수다" "주목해야 한다"
✗ "영향을 미칠 수 있다" "여파가 예상된다" "핵심은 ~다"
✗ "중요한 시점이다" "관건은 ~다" "~어떻게 될까?"
✓ 조건형/대비형/질문형/압축형만 허용

━━━ 초안이 좋을 때 ━━━

- 고칠 게 없으면 원문 그대로 JSON으로 반환
- 억지로 고치지 마라

━━━ 출력 ━━━
한국어 JSON만 출력:
{
  "final_post": "최종 완성본",
  "final_short": "독립형 짧은 버전"
}"""


async def _claude_review_final(
    card: CandidateCard, draft: FinalPost, *, selected_hook: str = ""
) -> Optional[FinalPost]:
    """Anthropic Claude 최종 통합. 실패 시 None (OpenAI 결과로 폴백)."""
    from app.config import settings

    if not settings.has_anthropic:
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
    if card.cautions:
        user_prompt += "cautions:\n"
        for c in card.cautions:
            user_prompt += f"  - {c}\n"
    if card.topic_tags:
        user_prompt += f"topic_tags: {', '.join(card.topic_tags)}\n"

    user_prompt += (
        "\n위 초안을 최종 통합 편집하고, JSON으로 반환하라."
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
            result = _parse_final_post(raw)
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

        return CandidateCard(
            key_facts=_ensure_list(data.get("key_facts"), 5),
            hook_candidates=_ensure_list(data.get("hook_candidates"), 5),
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
]

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
}


def _validate_final_post(post: str, short: str) -> tuple[str, str, list[str]]:
    """마감 결과 검증 및 자동 보정. (post, short, warnings) 반환."""
    warnings = []

    # 첫 문장 사실나열 감지 (뉴스 후기 느낌의 원흉)
    first_line = post.split("\n")[0].strip() if post else ""
    for pattern in _FACT_NARRATION_STARTS:
        if pattern in first_line:
            warnings.append(f"첫 문장 사실나열 패턴: '{pattern}' — 해석 선행 필요")
            break

    # 금지 마무리 패턴 감지
    for banned in _BANNED_ENDINGS:
        if post.rstrip().endswith(banned) or post.rstrip().endswith(banned + "."):
            warnings.append(f"final_post 금지 마감 패턴: '{banned}'")
            break
        if short and (short.rstrip().endswith(banned) or short.rstrip().endswith(banned + ".")):
            warnings.append(f"final_short 금지 마감 패턴: '{banned}'")
            break

    # 과장 표현 자동 약화
    for strong, soft in _TONE_SOFTENERS.items():
        if strong in post:
            post = post.replace(strong, soft)
            warnings.append(f"과장 표현 자동 약화: '{strong}' → '{soft}'")
        if short and strong in short:
            short = short.replace(strong, soft)

    # 뻔한 표현 경고 (본문 전체 검사)
    for pat in _WEAK_PATTERNS:
        if pat in post:
            warnings.append(f"뻔한 표현 감지: '{pat}'")
            break  # 첫 번째 하나만 경고

    # 일반론 의견 패턴 감지 (원칙 C)
    for pat in _OPINION_PATTERNS:
        if pat in post:
            warnings.append(f"일반론 의견 패턴: '{pat}'")
            break  # 첫 번째 하나만 경고

    # final_short가 final_post 첫 문장과 동일한지 체크
    first_sentence = post.split(".")[0].split("\n")[0].strip()
    short_first = short.split(".")[0].split("\n")[0].strip() if short else ""
    if first_sentence and short_first and first_sentence == short_first:
        warnings.append("final_short 첫 문장이 final_post와 동일")

    return post, short, warnings


def _parse_final_post(raw: str) -> Optional[FinalPost]:
    """AI 응답 JSON → FinalPost. 검증 포함."""
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
        post, short, warnings = _validate_final_post(post, short)
        for w in warnings:
            logger.warning(f"[마감검증] {w}")

        return FinalPost(final_post=post, final_short=short)
    except Exception as e:
        logger.warning(f"FinalPost 파싱 오류: {e}")
        return None
