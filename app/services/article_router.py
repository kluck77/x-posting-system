"""기사 라우터 — article mode router.

content_pack.py 에서 분리. 이번 PR 은 **코드 이동만** 한다.
외부 호출자(tests, telegram_bot)는 content_pack.py 의 re-export 를 통해
기존 `from app.services.content_pack import ...` 경로를 그대로 쓴다.

다음 PR 에서 이 파일에 classifier / decide_mode 를 추가할 것이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.content_pack import CandidateCard


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

    # (a) 경고가 많으면 곧바로 VERIFY (제일 강한 강등)
    if len(cautions) >= 3:
        return MODE_VERIFY

    # (b) 약한 신호 태그
    _WEAK_TAG_WORDS = (
        "단독", "루머", "미확인", "관측", "추정", "주장", "소문", "전망",
    )
    has_weak_tag = any(
        isinstance(t, str) and any(w in t for w in _WEAK_TAG_WORDS)
        for t in topic_tags
    )
    if has_weak_tag and base == MODE_EXPLAIN:
        return MODE_JUDGMENT

    # (c) 근거 얕음
    if len(key_facts) <= 2 and base == MODE_EXPLAIN:
        return MODE_JUDGMENT

    return base


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
    # MODE_VERIFY
    return (
        "\n━━━ ARTICLE MODE: VERIFY (미확인/단독) ━━━\n"
        "해석 슬롯 3개는 아래 3축으로 맞춰라:\n"
        "  슬롯1 = 지금 나온 주장 (누가 무엇을 말했는가)\n"
        "  슬롯2 = 아직 확인 안 된 부분 (어떤 공백이 있는가)\n"
        "  슬롯3 = 무엇이 확인되면 진짜인지 (검증 신호)\n"
        "금지: 정치적 계산 / 숨은 의도 / 본심 / 노림수 / 전략적 카드 / "
        "체제 양보 / 질서 재편 / 구조적 변화 단정 / 장기 지정학 해석.\n"
        "허용: 지금 어떤 말이 나왔는가 / 무엇이 비어 있는가 / "
        "무엇이 나오면 진짜라고 볼 수 있는가.\n"
    )


def _build_mode_finalize_instruction(mode: str) -> str:
    """Finalize user_prompt '━━━ 지시 ━━━' 블록을 mode별로 분기."""
    if mode == MODE_EXPLAIN:
        return (
            "\n━━━ 지시 (MODE: EXPLAIN) ━━━\n"
            "확정 팩트 기반. 해설 밀도 최대치로 4문장 조립하라.\n"
            "기사 요약 금지. 슬롯의 해석 방향만 쓴다.\n"
            "문장 1: 핵심 명제 — 변화/갈등/차이를 단정으로 박아라.\n"
            "문장 2: 근거 팩트 — 핵심 숫자/조치/발표를 짧게.\n"
            "문장 3: 판단 기준 — 독자가 새로 갖게 되는 해석 좌표.\n"
            "마지막 문장: 판별 신호 — '~이 나오면/안 나오면' 구체 검증.\n"
            "  ✗ '관건이다' '변수다' '확인이 필요하다' '지켜봐야 한다'\n"
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
        )
    # MODE_VERIFY
    return (
        "\n━━━ 지시 (MODE: VERIFY) ━━━\n"
        "미확인/단독/루머성 기사. 3문장만으로 확인 축만 잡는다.\n"
        "장기 해석·의도 추정·구조 재편 단정 전부 금지.\n"
        "문장 1: 현재 나온 주장 — 누가 무엇을 말했는가 (주장임을 명시).\n"
        "문장 2: 아직 확인 안 된 점 — 어떤 공백/출처 미검증이 있는가.\n"
        "문장 3: 다음 확인 신호 — 무엇이 나오면 진짜라고 볼 수 있는가.\n"
        "  ✗ '정치적 계산' '숨은 의도' '본심' '노림수' '전략적 카드'\n"
        "  ✗ '체제 양보' '질서 재편' '구조적 변화'\n"
        "  ✓ '~측이 ~라고 밝혔다' '~은 아직 확인되지 않았다' "
        "'~이 공개되면 검증 가능'\n"
    )
