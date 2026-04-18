"""기사 라우터 — article mode router.

content_pack.py 에서 분리. PR 1 은 코드 이동만, PR 4 (이번) 는
rule-first article_type classifier 를 추가해서 Perplexity
certainty_level 하나에 의존하던 mode 분기를 보수적으로 일관화한다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.content_pack import CandidateCard

logger = logging.getLogger(__name__)


# ─── 기사 라우터 ─────────────────────────────────────────────────────────────
#
# 같은 해설 엔진을 모든 기사에 돌리지 말고, certainty_level에 따라
# 출력 모드를 분기한다. 슬롯 구조/최종 템플릿/금지어가 mode별로 달라진다.
#
#   EXPLAIN  — 확정 팩트 기반. 해설 밀도 최대. (변화/의미/판별 4문장)
#   JUDGMENT — 상충 신호. 엇갈린다는 점을 그대로 드러낸다. (3문장)
#   VERIFY   — 미확인/단독/루머. 장기 해석 금지, 확인 축만. (3문장)
#
# certainty_level이 예상 밖 값이면 가장 보수적인 VERIFY로 떨어뜨린다.

MODE_EXPLAIN = "EXPLAIN"
MODE_JUDGMENT = "JUDGMENT"
MODE_VERIFY = "VERIFY"

_ARTICLE_MODES = frozenset({MODE_EXPLAIN, MODE_JUDGMENT, MODE_VERIFY})


# ─── Article Type Classifier (PR 4) ─────────────────────────────────────────
#
# 이전까지 mode 분기는 Perplexity 가 판정한 certainty_level + cautions 개수 +
# topic_tags 약신호 만으로 이뤄졌다. 문제: 같은 성질 기사가 certainty_level
# 흔들림에 따라 한 번은 VERIFY, 한 번은 EXPLAIN 으로 들어간다.
#
# 이번 PR 은 AI 호출 없이 source_type / source_url / cautions / risk_flags
# / topic_tags 를 조합해 기사 성질 자체를 먼저 분류한 뒤, 그 결과로 기존
# base_mode 를 **한 단계만 강등** 한다. 상향은 없다.
#
# 우선순위 (첫 매치가 이긴다):
#   1. COMMUNITY_SCREENSHOT → 항상 VERIFY
#   2. OPINION_COLUMN       → 항상 VERIFY
#   3. UNVERIFIED_CLAIM     → 항상 VERIFY
#   4. CONFLICTING_REPORT   → EXPLAIN 이면 JUDGMENT 로 강등
#   5. MARKET_MOVING_NEWS   → base 유지 (라벨만)
#   6. STRAIGHT_NEWS        → base 유지 (fallback)

TYPE_STRAIGHT_NEWS = "STRAIGHT_NEWS"
TYPE_CONFLICTING_REPORT = "CONFLICTING_REPORT"
TYPE_UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
TYPE_OPINION_COLUMN = "OPINION_COLUMN"
TYPE_COMMUNITY_SCREENSHOT = "COMMUNITY_SCREENSHOT"
TYPE_MARKET_MOVING_NEWS = "MARKET_MOVING_NEWS"

_ARTICLE_TYPES = frozenset({
    TYPE_STRAIGHT_NEWS,
    TYPE_CONFLICTING_REPORT,
    TYPE_UNVERIFIED_CLAIM,
    TYPE_OPINION_COLUMN,
    TYPE_COMMUNITY_SCREENSHOT,
    TYPE_MARKET_MOVING_NEWS,
})

# 한국 커뮤니티 도메인 (스크린샷/캡처성)
_COMMUNITY_DOMAIN_HINTS = (
    "dcinside.com", "ruliweb.com", "ppomppu.co.kr", "theqoo.net",
    "fmkorea.com", "ilbe.com", "clien.net", "bobaedream.co.kr",
    "mlbpark", "instiz.net", "nate.com/talk", "pann.nate.com",
    "todayhumor", "82cook.com", "humoruniv", "cafe.naver.com",
    "cafe.daum.net", "reddit.com", "x.com/", "twitter.com/",
)

_COMMUNITY_TAG_HINTS = (
    "스크린샷", "캡처", "커뮤니티", "게시물", "짤", "짤방", "썰",
)

# 사설/칼럼 slug + 태그
_OPINION_URL_SLUGS = (
    "/column", "/opinion", "/editorial", "/view/", "/perspective",
    "/voice", "/essay", "/commentary", "사설", "칼럼",
)

_OPINION_TAG_HINTS = (
    "사설", "칼럼", "오피니언", "논평", "기고", "시론",
)

_OPINION_SOURCE_TYPES = frozenset({"column", "opinion", "editorial"})

# 미확인/단독/루머 신호
_UNVERIFIED_TEXT_HINTS = (
    "출처 미검증", "출처미검증", "미검증", "확인 실패", "확인실패",
    "추가 확인 필요", "single-sourced", "단독 보도", "unverified",
    "unconfirmed", "rumor", "루머", "소문",
)

_UNVERIFIED_TAG_HINTS = (
    "단독", "루머", "미확인", "관측", "추정", "주장", "소문", "전망",
)

# 상충/엇갈린 보도 신호
_CONFLICT_TEXT_HINTS = (
    "상충", "엇갈리", "엇갈린", "conflicting", "conflict",
    "반박", "부인", "뒤집",
)

# 시장 반응 기사 (금융/거시)
_MARKET_KEYWORD_HINTS = (
    "증시", "코스피", "코스닥", "나스닥", "다우", "s&p", "환율",
    "원/달러", "달러", "원화", "금리", "국채", "채권",
    "cpi", "gdp", "ppi", "소비자물가", "생산자물가", "기준금리",
    "주가", "주식", "실적", "영업이익", "매출", "수출", "수입",
    "원유", "유가", "금값", "비트코인", "암호화폐",
)


def _lower_list(items) -> list[str]:
    """리스트/None 을 소문자 문자열 리스트로 평탄화. 비문자열은 skip."""
    if not items:
        return []
    out = []
    for x in items:
        if isinstance(x, str):
            out.append(x.lower())
    return out


def _any_hit(haystack_lower: str, needles: tuple) -> bool:
    return any(n.lower() in haystack_lower for n in needles)


def _any_tag_hit(tags_lower: list[str], needles: tuple) -> bool:
    for t in tags_lower:
        for n in needles:
            if n.lower() in t:
                return True
    return False


def classify_article_type(card: "CandidateCard") -> str:
    """기사 성질 분류기 — AI 호출 없이 source/tags/cautions/flags 조합.

    우선순위 첫 매치 승. 예외 시 보수적으로 STRAIGHT_NEWS 반환
    (=강등 없음). 상향 분류 불가.
    """
    try:
        source_type = (getattr(card, "source_type", "") or "").lower()
        source_url = (getattr(card, "source_url", "") or "").lower()
        certainty = getattr(card, "certainty_level", "미확인") or "미확인"

        cautions_lower = _lower_list(getattr(card, "cautions", None))
        risk_flags_lower = _lower_list(getattr(card, "risk_flags", None))
        topic_tags_lower = _lower_list(getattr(card, "topic_tags", None))
        key_facts_lower = _lower_list(getattr(card, "key_facts", None))

        # 본문/플래그 결합 텍스트 (hint 매칭용)
        combined_flags = " ".join(cautions_lower + risk_flags_lower)

        # 1. COMMUNITY_SCREENSHOT
        if "community" in source_type or "screenshot" in source_type \
                or "image" in source_type:
            return TYPE_COMMUNITY_SCREENSHOT
        if source_url and _any_hit(source_url, _COMMUNITY_DOMAIN_HINTS):
            return TYPE_COMMUNITY_SCREENSHOT
        if _any_tag_hit(topic_tags_lower, _COMMUNITY_TAG_HINTS):
            return TYPE_COMMUNITY_SCREENSHOT

        # 2. OPINION_COLUMN
        if source_type in _OPINION_SOURCE_TYPES:
            return TYPE_OPINION_COLUMN
        if source_url and _any_hit(source_url, _OPINION_URL_SLUGS):
            return TYPE_OPINION_COLUMN
        if _any_tag_hit(topic_tags_lower, _OPINION_TAG_HINTS):
            return TYPE_OPINION_COLUMN

        # 3. UNVERIFIED_CLAIM
        #    (a) certainty 미확인
        #    (b) cautions/risk_flags 에 미검증 계열 문구
        #    (c) cautions 3개 이상 (기존 route 강등 규칙과 같은 기준)
        #    (d) topic_tags 약신호
        if certainty == "미확인":
            return TYPE_UNVERIFIED_CLAIM
        if _any_hit(combined_flags, _UNVERIFIED_TEXT_HINTS):
            return TYPE_UNVERIFIED_CLAIM
        if len(cautions_lower) >= 3:
            return TYPE_UNVERIFIED_CLAIM
        if _any_tag_hit(topic_tags_lower, _UNVERIFIED_TAG_HINTS):
            return TYPE_UNVERIFIED_CLAIM

        # 4. CONFLICTING_REPORT
        if certainty == "상충":
            return TYPE_CONFLICTING_REPORT
        if _any_hit(combined_flags, _CONFLICT_TEXT_HINTS):
            return TYPE_CONFLICTING_REPORT

        # 5. MARKET_MOVING_NEWS — 태그/팩트에 시장 키워드 존재
        if _any_tag_hit(topic_tags_lower, _MARKET_KEYWORD_HINTS) \
                or _any_tag_hit(key_facts_lower, _MARKET_KEYWORD_HINTS):
            return TYPE_MARKET_MOVING_NEWS

        # 6. STRAIGHT_NEWS (fallback)
        return TYPE_STRAIGHT_NEWS
    except Exception as e:  # noqa: BLE001
        # 예외 시 보수적으로 STRAIGHT_NEWS → 강등 없음
        logger.warning(f"[ArticleType] classifier error, fallback: {e}")
        return TYPE_STRAIGHT_NEWS


def _apply_type_demotion(base_mode: str, article_type: str) -> str:
    """article_type 기반 mode 강등. 상향 없음. 일방향 EXPLAIN→JUDGMENT→VERIFY.

    규칙:
      COMMUNITY_SCREENSHOT / OPINION_COLUMN / UNVERIFIED_CLAIM → VERIFY 고정
      CONFLICTING_REPORT + EXPLAIN → JUDGMENT (상충은 JUDGMENT 가 적절)
      STRAIGHT_NEWS / MARKET_MOVING_NEWS → base 유지
    """
    if article_type in (
        TYPE_COMMUNITY_SCREENSHOT,
        TYPE_OPINION_COLUMN,
        TYPE_UNVERIFIED_CLAIM,
    ):
        return MODE_VERIFY
    if article_type == TYPE_CONFLICTING_REPORT and base_mode == MODE_EXPLAIN:
        return MODE_JUDGMENT
    return base_mode


def route_article_mode(card: "CandidateCard") -> str:
    """certainty_level + 구조/태그 조합으로 article mode 를 결정한다.

    1단계: certainty_level 기반 base mode
      확정   → EXPLAIN
      상충   → JUDGMENT
      그 외  → VERIFY (보수 기본값)

    2단계: 강등 규칙 — 사용자가 링크만 대충 던져도 안전한 쪽으로
           자동 분기하도록 아래 신호가 보이면 한 단계 낮춘다.
      (a) cautions 3개 이상  → VERIFY 로 최대 강등
          (팩트체크가 여러 경고를 달았다 = 해석 리스크 큼)
      (b) topic_tags 에 약한 신호 단어 포함 → 최소 JUDGMENT
          ("단독/루머/미확인/관측/추정/주장/소문/전망")
      (c) key_facts 2개 이하 → 최소 JUDGMENT (근거 얕음)

    강등은 일방향(EXPLAIN → JUDGMENT → VERIFY). 상향 없음.
    사용자 입력 품질에 기대지 않고 시스템이 먼저 보수적으로 판정한다.
    """
    c = getattr(card, "certainty_level", "미확인") or "미확인"
    if c == "확정":
        base = MODE_EXPLAIN
    elif c == "상충":
        base = MODE_JUDGMENT
    else:
        base = MODE_VERIFY

    cautions = getattr(card, "cautions", None) or []
    key_facts = getattr(card, "key_facts", None) or []
    topic_tags = getattr(card, "topic_tags", None) or []

    # ── 1단계: 기존 legacy 강등 (팩트체크 신호 기반) ──────────────────────
    #
    # 조기 return 하지 않고 base_after_legacy 에 축적. 반드시 classifier /
    # 로깅 단계까지 흘러간 뒤 반환한다 (PR 4 로그 일관성을 위해).

    base_after_legacy = base

    # (a) 경고가 많으면 VERIFY 로 최대 강등
    if len(cautions) >= 3:
        base_after_legacy = MODE_VERIFY

    # (b) 약한 신호 태그 — 최소 JUDGMENT
    _WEAK_TAG_WORDS = (
        "단독", "루머", "미확인", "관측", "추정", "주장", "소문", "전망",
    )
    has_weak_tag = any(
        isinstance(t, str) and any(w in t for w in _WEAK_TAG_WORDS)
        for t in topic_tags
    )
    if has_weak_tag and base_after_legacy == MODE_EXPLAIN:
        base_after_legacy = MODE_JUDGMENT

    # (c) 근거 얕음 — 최소 JUDGMENT
    if len(key_facts) <= 2 and base_after_legacy == MODE_EXPLAIN:
        base_after_legacy = MODE_JUDGMENT

    # ── 2단계: PR 4 — article_type classifier 기반 최종 강등 ──────────
    #
    # 같은 성질 기사가 certainty_level 흔들림에 따라 mode 가 튀는 문제를
    # 보수적 강등으로 일관화. 상향은 절대 없음.
    article_type = classify_article_type(card)
    final_mode = _apply_type_demotion(base_after_legacy, article_type)

    logger.info(
        "[ArticleType] type=%s certainty=%s base=%s final=%s",
        article_type, c, base_after_legacy, final_mode,
    )

    return final_mode


# mode별 한 줄 라벨 (로그/텔레그램 표시용)
_MODE_LABELS = {
    MODE_EXPLAIN: "📊 EXPLAIN (확정 해설)",
    MODE_JUDGMENT: "⚖️ JUDGMENT (상충 판단)",
    MODE_VERIFY: "🔎 VERIFY (확인 축)",
}


def mode_label(mode: str) -> str:
    return _MODE_LABELS.get(mode, mode)


def _build_mode_slot_instruction(mode: str) -> str:
    """Gemini 슬롯 생성 user_prompt에 주입할 mode별 슬롯 프레임 지시."""
    if mode == MODE_EXPLAIN:
        return (
            "\n━━━ ARTICLE MODE: EXPLAIN (확정 팩트) ━━━\n"
            "해석 슬롯 3개는 아래 3축으로 맞춰라:\n"
            "  슬롯1 = 무엇이 바뀌나 (변화의 실체)\n"
            "  슬롯2 = 왜 뉴스 이상이냐 (구조적 의미)\n"
            "  슬롯3 = 다음 판가름 (앞으로의 검증 기준)\n"
        )
    if mode == MODE_JUDGMENT:
        return (
            "\n━━━ ARTICLE MODE: JUDGMENT (상충 신호) ━━━\n"
            "해석 슬롯 3개는 아래 3축으로 맞춰라:\n"
            "  슬롯1 = 무엇이 바뀌나 (엇갈리는 지금 핵심)\n"
            "  슬롯2 = 다음 판가름 (확인 포인트)\n"
            "  슬롯3 = 왜 뉴스 이상이냐 — 짧게만 (한 줄 의미)\n"
            "장기 구조 해석 톤을 약하게. '엇갈린다/아직 불확실하다'를 "
            "숨기지 말고 드러내라.\n"
        )
    # MODE_VERIFY — PR 6: 출력 스키마 축소 (설명문 → 검증문)
    return (
        "\n━━━ ARTICLE MODE: VERIFY (미확인/단독) ━━━\n"
        "이 기사는 아직 확정되지 않은 주장이다. 해설문/브리핑체/"
        "구조 해석을 전부 버리고 '검증문'으로만 써라.\n"
        "질문은 '왜 뉴스 이상이냐' 가 아니라 '왜 아직 단정하면 안 되는가' 다.\n"
        "\n"
        "해석 슬롯 3개는 아래 3축으로 맞춰라. 다른 축 금지.\n"
        "  슬롯1 = 지금 나온 주장 (누가 무엇을 말했는가) — 1문장.\n"
        "  슬롯2 = 아직 확인 안 된 것 (어떤 공백/출처 미검증이 있는가) — 1문장.\n"
        "        ※ 이 슬롯은 UI 상 '왜 뉴스 이상이냐' 자리에 들어가지만,\n"
        "          VERIFY 에서는 '구조적 의미 / 구조 해석' 서술 금지.\n"
        "          오직 '어떤 공백이 있는가' 한 줄로 약화하라.\n"
        "  슬롯3 = 무엇이 확인되면 진짜인지 (검증 신호) — 1문장.\n"
        "\n"
        "금지(강) — 이 계열 단어가 슬롯에 들어오면 게이트 실패:\n"
        "  · 동기 추정: 정치적 계산 / 숨은 의도 / 본심 / 노림수 / 전략적 카드\n"
        "  · 구조 해석: 구조적 의미 / 구조적 변화 단정 / 질서 재편 /\n"
        "    국제질서 재편 / 패러다임 / 상징적 의미 / 체제 양보\n"
        "  · 외교 시나리오 확장: 제3국을 통한 실질적 대화 채널 /\n"
        "    제3국 실질 채널 / 외교 채널 복원 / 협상 의제 연동 /\n"
        "    긴장 수위 상승 / 다음 국면을 결정 / 진짜 신호\n"
        "  · 단정형 마감: ~를 시사한다 / ~라는 뜻이다 / ~가 판가름\n"
        "  · 이중 분기 수사: ~이어질지 ~그칠지\n"
        "\n"
        "허용: 지금 어떤 말이 나왔는가 / 무엇이 비어 있는가 / "
        "무엇이 나오면 진짜라고 볼 수 있는가.\n"
    )


def _build_mode_finalize_instruction(mode: str) -> str:
    """Finalize user_prompt '━━━ 지시 ━━━' 블록을 mode별로 분기."""
    if mode == MODE_EXPLAIN:
        return (
            "\n━━━ 지시 (MODE: EXPLAIN) ━━━\n"
            "확정 팩트 기반. 4문장으로 '구조 + 이해관계 + 기억점'을 조립하라.\n"
            "기사 요약 금지. 슬롯의 해석 방향만 쓴다.\n"
            "\n"
            "문장 1: 핵심 명제 — 변화/충돌/손익/판정선 중 하나로 박아라.\n"
            "  배경 설명 금지. '이후 ~' '~보도한' 시작 금지.\n"
            "문장 2: 근거 팩트 — 핵심 숫자/조치/발표를 짧게.\n"
            "  가능하면 '왜 그 순서로 움직이는지' 구조 힌트 한 조각을 같이\n"
            "  (예: 고가부터 꺾이는 이유 / 중저가가 버티는 이유 /\n"
            "       수입물가가 소비자가격에 늦게 오는 이유).\n"
            "문장 3: 판단 기준 또는 이해관계 — 둘 중 하나.\n"
            "  A) 독자가 새로 갖게 되는 해석 좌표 한 줄, 또는\n"
            "  B) 누가 먼저 유리/불리한지 한 줄\n"
            "     (정부/기업/소비자/투자자/고가 vs 중저가 중 누구 문제인가).\n"
            "마지막 문장: 판별 신호 — '~이 나오면/안 나오면' 구체 검증.\n"
            "  단, 닫힌 판정으로 끝내지 말고 아래 A/B 톤 중 하나로 연다.\n"
            "    A. 판정 기준형: '답은 ~다' / '진짜 ~는 ~이 나오면 갈린다' /\n"
            "       '핵심은 ~가 먼저 움직이느냐다'\n"
            "    B. 이해관계형: '결국 먼저 맞는 건 ~다' /\n"
            "       '이 충격은 ~보다 ~에 늦게 온다' /\n"
            "       '~이 성공해도 ~는 더 얼 수 있다'\n"
            "\n"
            "금지 마감 (독자 생각을 닫아버림 — 절대 금지):\n"
            "  ✗ '~신호다' '~확인이다' '~맞다' '~의미다' '~의미한다' '~뜻이다'\n"
            "  ✗ '~보여준다' '~시사한다' '~구조적 의미를 갖는다' '~패러다임 변화다'\n"
            "  ✗ '관건이다' '변수다' '확인이 필요하다' '지켜봐야 한다'\n"
            "\n"
            "짧은 버전(final_short): 요약 금지. 구조 한 줄 또는 이해관계 한 줄.\n"
            "  좋은 예:\n"
            "    '강남3구부터 꺾였다는 건 규제가 먼저 고가 주택 심리를 눌렀다.\n"
            "     문제는 중저가까지 번지느냐다.'\n"
            "    '수입물가 충격은 공장에서 먼저 맞고, 소비자 가격엔 한 달쯤\n"
            "     늦게 온다. 답은 다음 CPI다.'\n"
            "\n"
            "━━━ Reader Reward Layer (마지막 문장 규칙) ━━━\n"
            "마지막 문장은 '닫힌 분석가 마감' 대신 아래 3종 중 하나로 연다.\n"
            "  (1) SAVE — 앞으로 비슷한 사안 판단할 때 참조할 기준점\n"
            "      예: '답은 다음 CPI다.' / '결국 먼저 맞는 건 공장이다.'\n"
            "          '핵심은 발표가 아니라 입금 시점이다.'\n"
            "  (2) SHARE — 한 줄로 바로 나눌 수 있는 단언\n"
            "      예: '말보다 숫자가 먼저다.' / '주장보다 출처가 먼저다.'\n"
            "  (3) FOLLOW — 후속 데이터/발표 시 다시 돌아올 이유\n"
            "      예: '다음 공식 집계가 나오면 진짜가 드러난다.'\n"
            "          '후속 데이터가 나오면 진짜가 드러난다.'\n"
            "재확인 금지 마감: '~중요하다' '~의미가 있다' '~결정한다'\n"
            "                  '~판별 포인트다' '~중요한 대목이다'\n"
            "단, '~기준이다' 는 SAVE 보상 문장과 결합될 때만 허용.\n"
            "\n"
            "━━━ Findability + Market/Stake Layer ━━━\n"
            "첫 2문장 안에 검색 가능한 고유명사/기관명/숫자/지표 최소 2개.\n"
            "추상명사(시장/정책/구조/이슈/변화/영향)만으로 시작 금지.\n"
            "  좋음: '삼성전자 노조가 5월 21일부터 총파업을 예고했다.'\n"
            "  나쁨: '정책 변화가 시장에 영향을 줄 수 있다.'\n"
            "\n"
            "마지막 줄 전에 '그래서 어디에 먼저 반영되나' 시각 한 줄:\n"
            "  이 뉴스가 실적/원가/수요/공급/정책 집행/생활비 중\n"
            "  어디로 먼저 번지는지, 어떤 숫자를 다음에 보면 되는지.\n"
            "  ✓ '이게 맞으면 시장은 원가 부담부터 반영할 수 있다'\n"
            "  ✓ '핵심은 발표보다 시행일이다'\n"
            "  ✗ '시장이 크게 반응할 것이다' '무조건 수혜다'\n"
            "  ✗ '구조적 의미를 가진다' '영향이 예상된다'\n"
            "\n"
            "핵심: 날카로움은 센 단어가 아니라 '구조 + 이해관계'에서 나온다.\n"
        )
    if mode == MODE_JUDGMENT:
        return (
            "\n━━━ 지시 (MODE: JUDGMENT) ━━━\n"
            "상충 신호 기사. 3문장으로 엇갈림을 그대로 드러낸다.\n"
            "기사 요약 금지. 장기 구조 해석 톤 약하게.\n"
            "문장 1: 지금 핵심 — 누가 무엇을 놓고 갈리는지 한 줄.\n"
            "문장 2: 엇갈리는 신호 — 양쪽 주장/근거의 충돌 지점.\n"
            "문장 3: 확인 포인트 — '~이 나오면 어느 쪽' 구체 신호.\n"
            "  ✗ '구조적 전환' '체제 재편' '장기 전략'\n"
            "  ✓ '지금 단계에서는 ~가 확인되어야' '~이 나오기 전까진 단정 불가'\n"
            "\n"
            "━━━ Reader Reward Layer (마지막 문장 규칙) ━━━\n"
            "마지막 문장은 '다음 갈림 기준' 으로 닫아 독자가 후속을 볼 이유를 남긴다.\n"
            "  ✓ FOLLOW : '다음 발표가 나오면 어느 쪽이 맞는지 갈린다.'\n"
            "              '이 조치가 시행되면 진짜가 드러난다.'\n"
            "  ✓ SAVE   : '답은 다음 집계다.' '핵심은 발표가 아니라 시행 시점이다.'\n"
            "재확인 금지 마감: '~중요하다' '~의미가 있다' '~결정한다'\n"
            "                  '~판별 포인트다' '~구조적 의미가 있다'\n"
            "'~기준이다' 는 SAVE 보상 문장과 결합될 때만 허용.\n"
            "\n"
            "━━━ Findability + Market/Stake Layer ━━━\n"
            "첫 2문장 안에 검색 가능한 고유명사/숫자/지표 최소 2개.\n"
            "추상명사만으로 시작 금지.\n"
            "\n"
            "갈림 기준을 남겨라:\n"
            "  현재 반응이 과민인지 정당한지, 갈림 기준이 무엇인지.\n"
            "  ✓ '관건은 첫 공시다' '진짜 갈림길은 시행 여부다'\n"
            "  ✗ '주가가 급등할 것이다' '다음 국면을 결정한다'\n"
        )
    # MODE_VERIFY — PR 6: 출력 스키마 축소 (설명문 → 검증문)
    return (
        "\n━━━ 지시 (MODE: VERIFY) ━━━\n"
        "미확인/단독/루머성 기사. **final_post 최대 3문장, "
        "final_short 최대 2문장**. 단문 우선. 쉼표/삽입구/접속구조 최소.\n"
        "장기 해석 · 의도 추정 · 구조 재편 · 외교 시나리오 확장 · 상징 해석 · "
        "패러다임 논의 · 본심/노림수 추정 전면 금지.\n"
        "'왜 뉴스 이상이냐' 가 아니라 '왜 아직 단정하면 안 되는가' 를 쓴다.\n"
        "\n"
        "━━━ final_post 3문장 템플릿 — 반드시 A/B/C 중 하나 ━━━\n"
        "[템플릿 A · 발언 검증형]\n"
        "  문장 1: '<주체>가 <내용>이라고 밝혔다.'  (지금 나온 주장)\n"
        "  문장 2: '그러나 <공백>은 아직 확인되지 않았다.'\n"
        "  문장 3: '<검증 조건>이 나오면 확인 가능.'\n"
        "  예)\n"
        "    '트럼프 측이 대화 의향을 밝혔다.\n"
        "     그러나 실제 접촉은 아직 확인되지 않았다.\n"
        "     특사 파견이 공개되면 확인 가능.'\n"
        "\n"
        "[템플릿 B · 접촉 검증형]\n"
        "  문장 1: '핵심은 <말>이 아니라 <움직임> 확인이다.'\n"
        "  문장 2: '<공식 근거>는 현재까지 없다.'\n"
        "  문장 3: '<신호>가 포착되면 <판정>.'\n"
        "  예)\n"
        "    '핵심은 발언이 아니라 접촉 확인이다.\n"
        "     공식 접촉 기록은 현재까지 없다.\n"
        "     특사 파견이 포착되면 대화 채널이 살아 있다.'\n"
        "\n"
        "[템플릿 C · 시간 조건형]\n"
        "  문장 1: '<기간> 내 <조건>이 없으면 <판정>.'\n"
        "  문장 2: '<주장>은 아직 확인되지 않았다.'\n"
        "  문장 3: '<공식 신호>가 공개되면 검증 가능.'\n"
        "  예)\n"
        "    '이틀 내 공식 접촉이 없으면 수사에 가깝다.\n"
        "     실제 의제 조율은 확인되지 않았다.\n"
        "     공식 발표가 공개되면 검증 가능.'\n"
        "\n"
        "━━━ 각 문장 규칙 ━━━\n"
        "문장 1 (첫 줄): 1문장 1주장 = 현재 나온 주장 한 줄로 고정.\n"
        "  금지(첫 줄):\n"
        "    ✗ 'A인지 B인지 ~이 결정한다' (이중 분기 수사)\n"
        "    ✗ '단순 수사인지 실질 채널인지' '단순 압박인지'\n"
        "    ✗ '~로 이어질지' '~에 그칠지' '~가 판가름이다'\n"
        "문장 2: 아직 확인 안 된 점 — 어떤 공백/출처 미검증이 있는가.\n"
        "  (= '~은 아직 확인되지 않았다' 구조로 고정)\n"
        "문장 3: 다음 확인 신호 — 무엇이 나오면 진짜라고 볼 수 있는가.\n"
        "  (= '~이 공개되면 검증 가능' / '~이 포착되면 <판정>' 구조)\n"
        "\n"
        "━━━ 본문 전역 금지(강) — 한 개 등장만으로도 게이트 실패 ━━━\n"
        "  ✗ 구조 해석: '구조적 의미' '질서 재편' '국제질서 재편'\n"
        "    '패러다임' '상징적 의미' '체제 양보' '구조적 변화'\n"
        "  ✗ 외교 시나리오 확장: '제3국을 통한 실질적 대화 채널'\n"
        "    '제3국 실질 채널' '외교 채널 복원' '협상 의제 연동'\n"
        "    '긴장 수위 상승' '다음 국면을 결정' '진짜 신호'\n"
        "    '실효성 여부가 판가름'\n"
        "  ✗ 동기 추정: '정치적 계산' '숨은 의도' '본심' '노림수'\n"
        "    '전략적 카드' '선거용'\n"
        "  ✗ 단정 수사: '~를 시사한다' '~라는 뜻이다'\n"
        "    '~이어질지 ~그칠지' '~가 판가름'\n"
        "\n"
        "━━━ 본문 전역 허용 ━━━\n"
        "  ✓ '~측이 ~라고 밝혔다'\n"
        "  ✓ '~은 아직 확인되지 않았다'\n"
        "  ✓ '~이 공개되면 검증 가능'\n"
        "  ✓ '~이 포착되면 <판정>'\n"
        "\n"
        "━━━ 마지막 문장 끝맺음 규칙 (게이트 endswith) ━━━\n"
        "  ✗ '~뜻이다' '~신호다' '~의미한다' '~확인이다' '~맞다'\n"
        "    → '~이 나오면 X 라는 뜻이다' 같이 뒤에 붙이지 말 것.\n"
        "  ✗ '~보여준다' '~시사한다' '~구조적 의미를 갖는다'\n"
        "  ✓ '~이 나오면/안 나오면' 조건 뒤를 동사 원형으로 맺어라.\n"
        "    예: '특사 파견이 포착되면 대화 채널이 살아 있다.'\n"
        "    예: '통상적 통행이 이어지면 상징에 그쳤다.'\n"
        "    예: '이틀 내 공식 접촉이 없으면 수사에 가깝다.'\n"
        "\n"
        "━━━ final_short 규칙 (최대 2문장) ━━━\n"
        "  · 요약 금지. 해설체/브리핑체 금지.\n"
        "  · 구조: '<주장 한 줄>. <확인 포인트 한 줄>.'\n"
        "  · 예: '트럼프가 대화 의향을 밝혔다. 실제 접촉은 확인되지 않았다.'\n"
        "  · 예: '핵심은 접촉 확인이다. 특사 파견이 공개되면 검증 가능.'\n"
        "\n"
        "━━━ 핵심 원칙 ━━━\n"
        "VERIFY 에서는 '무슨 일이 벌어질 수 있다' 가 아니라 "
        "'무엇이 아직 확인되지 않았다' 를 써라.\n"
        "설명하지 말고 검증 조건만 남겨라.\n"
        "\n"
        "━━━ Reader Reward Layer (VERIFY 버전 — 마지막 문장 규칙) ━━━\n"
        "VERIFY 마지막 문장은 반드시 FOLLOW 계열 — '후속 검증 포인트' 로 닫는다.\n"
        "장기 해석/의미 부여/단정 마감은 절대 금지.\n"
        "  ✓ 허용 (FOLLOW 계열, 위 A/B/C 템플릿 끝줄과 일치):\n"
        "     '<신호>가 공개되면 검증 가능.'\n"
        "     '<신호>가 포착되면 <조건부 판정>.'\n"
        "     '<기간> 내 <조건>이 없으면 <조건부 판정>.'\n"
        "  ✗ 금지: '~중요하다' '~의미가 있다' '~결정한다'\n"
        "          '~판별 포인트다' '~구조적 의미가 있다' '~기준이다'\n"
        "          (VERIFY 에서는 '기준이다' 도 통째 금지 — SAVE 용법 아님)\n"
        "\n"
        "━━━ Findability + Market/Stake Layer (VERIFY 버전) ━━━\n"
        "첫 2문장 안에 검색 가능한 고유명사/숫자 최소 1개.\n"
        "추상명사만으로 시작 금지.\n"
        "\n"
        "예언 금지. '시장이 먼저 볼 확인 포인트' 만 남겨라.\n"
        "  ✓ '원본 데이터가 안 나오면 이 숫자는 주장 단계다'\n"
        "  ✓ '신청 절차가 공개되면 실제 대상과 규모가 드러난다'\n"
        "  ✓ '답은 5월 21일 실제 참여율이다'\n"
        "  ✗ '시장이 크게 반응할 것이다' '무조건 수혜다'\n"
        "  ✗ '구조적 의미를 가진다' '영향이 예상된다'\n"
    )
