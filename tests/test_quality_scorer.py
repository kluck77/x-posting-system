"""
quality_scorer.score_5criteria 한국어 패턴 회귀 테스트
======================================================

배경:
    score_5criteria 의 _INTERPRETATION_SIGNALS / _MARKETABILITY_SIGNALS /
    _REPEAT_SIGNALS / right_audience / pillar_pattern 이 전부 영어 `\\b` word
    boundary 기반이었다. Python `re` 의 `\\b` 는 ASCII word character 기준이라
    한국어 글자 경계에서 동작이 보장되지 않고, 한국어 Reviewer 출력은 총점 20
    근처에 고정돼 무조건 reject 로 떨어졌다. 이 상태에서 평가 3축 게이트
    (이전 세션) 를 추가하자 한국어 드래프트가 전부 "❌ 거절 권장" 으로 쏠렸다.

수정:
    기존 영어 regex 는 건드리지 않고, `\\b` 없는 substring 매치용 한국어 패턴
    을 모듈 레벨에 별도 추가(`_*_KO`) → score_5criteria 안에서 OR 결합.

이 테스트는 다음을 검증한다:
    1. 한국어 정상 본문(해석+글로벌+팔로워+재방문) → pass
    2. 한국어 빈약 본문 → 여전히 reject (억지 인플레이션 없음)
    3. 한국어 클릭베이트 → reject
    4. 영어 정상 본문 → pass (회귀 불변)
    5. 영어 단순 번역 → reject (회귀 불변)
    6. 각 한국어 dimension 이 독립적으로 점수를 주는지
"""

import pytest
from app.services.quality_scorer import score_5criteria


class TestKoreanInterpretationSignals:
    """한국어 해석 신호가 expertise 점수를 올리는지."""

    def test_core_interpretation_words_give_score(self):
        # '배경', '의미', '핵심' — 해석 키워드
        hook = "금리 동결, 가계부채 둔화가 핵심 배경"
        body = "이 결정의 의미는 긴축 완화 신호가 아니라 내수 보호다."
        r = score_5criteria(hook, body)
        assert r["scores"]["expertise"] >= 15, (
            f"해석 키워드 있는데 expertise={r['scores']['expertise']}. 패턴 미적용."
        )

    def test_structural_keyword(self):
        r = score_5criteria(
            "한국 반도체 수출, 구조적 전환점",
            "이 흐름은 구조적 공급망 재편의 결과다.",
        )
        assert r["scores"]["expertise"] >= 15

    def test_no_interpretation_low_expertise(self):
        # 순수 팩트 나열 — 해석 없음
        r = score_5criteria(
            "한국 GDP 2.1% 성장",
            "올 3분기 한국 GDP는 2.1% 성장했다. 제조업 생산이 늘었다.",
        )
        # translation 패턴 아님 → +5, interpretation 없음 → 0+5=5
        assert r["scores"]["expertise"] < 10


class TestKoreanMarketabilitySignals:
    """한국어 마켓/글로벌 신호가 marketability 점수를 올리는지."""

    def test_dollar_exchange_rate(self):
        r = score_5criteria(
            "원달러 환율 1380원 돌파",
            "달러 강세가 지속되면서 환율이 연고점을 찍었다.",
        )
        assert r["scores"]["marketability"] >= 20, (
            f"환율/달러 신호 있는데 mkt={r['scores']['marketability']}."
        )

    def test_supply_chain(self):
        r = score_5criteria(
            "반도체 공급망 재편",
            "글로벌 공급망이 재편되면서 대만과 한국 사이 역학이 달라졌다.",
        )
        assert r["scores"]["marketability"] >= 20

    def test_korea_only_weak_signal(self):
        # '한국' 언급만 있고 글로벌 연결 없음 → 약신호(+8)
        r = score_5criteria(
            "한국 정부 발표",
            "한국 정부가 오늘 새로운 정책을 발표했다.",
        )
        assert r["scores"]["marketability"] == 8, (
            f"한국 약신호만 있어야 하는데 mkt={r['scores']['marketability']}."
        )


class TestKoreanRepeatSignals:
    """한국어 재방문 신호가 repeat_consumption 점수를 올리는지."""

    def test_주시해야(self):
        r = score_5criteria(
            "환율 지표 경고",
            "투자자는 향후 3개월 동안 환율과 물가를 주시해야 한다.",
        )
        assert r["scores"]["repeat_consumption"] >= 20

    def test_패턴_반복(self):
        r = score_5criteria(
            "시장 패턴 분석",
            "이 패턴이 반복되면 다음 주 유사한 움직임이 나올 수 있다.",
        )
        assert r["scores"]["repeat_consumption"] >= 20

    def test_향후_계속(self):
        r = score_5criteria(
            "한국 재정 정책",
            "앞으로 향후 분기 동안 계속 지켜봐야 할 흐름이다.",
        )
        assert r["scores"]["repeat_consumption"] >= 20

    def test_no_repeat_signal(self):
        r = score_5criteria(
            "금리 동결",
            "한국은행이 금리를 동결했다. 끝.",
        )
        assert r["scores"]["repeat_consumption"] == 0


class TestKoreanFollowerQuality:
    """한국어 팔로워 유인 신호가 follower_quality 점수를 올리는지."""

    def test_투자자_키워드(self):
        r = score_5criteria(
            "환율 경고",
            "개인 투자자가 주목해야 할 글로벌 달러 흐름이다.",
        )
        # right_audience_ko(+10) + mkt(+5, 달러) = 15
        assert r["scores"]["follower_quality"] >= 10

    def test_애널리스트_키워드(self):
        r = score_5criteria(
            "분석 리포트",
            "애널리스트가 지적하는 구조적 리스크는 부동산이다.",
        )
        assert r["scores"]["follower_quality"] >= 10


class TestKoreanConsistencyPillars:
    """한국어 필러 키워드가 Consistency -5 감점을 막는지."""

    def test_금리_pillar(self):
        r = score_5criteria(
            "금리 정책",
            "금리 변동이 가계부채에 미치는 영향.",
        )
        assert r["scores"]["consistency"] == 20, (
            f"금리/가계부채 pillar 있는데 con={r['scores']['consistency']}."
        )

    def test_부동산_pillar(self):
        r = score_5criteria(
            "부동산 시장",
            "부동산 가격과 주택 공급의 불균형.",
        )
        assert r["scores"]["consistency"] == 20

    def test_no_pillar_penalty(self):
        # 필러 키워드가 전혀 없으면 -5
        r = score_5criteria("날씨가 좋다", "오늘은 맑다.")
        assert r["scores"]["consistency"] == 15


class TestKoreanWrongAudience:
    """한국어 클릭베이트가 Consistency 를 -15 하는지."""

    def test_스캔들_루머(self):
        r = score_5criteria(
            "충격! 재벌 스캔들",
            "대박 난리난 열애 루머 실화냐?",
        )
        assert r["scores"]["consistency"] <= 5, (
            f"wrong_audience 잡혔는데 con={r['scores']['consistency']}."
        )

    def test_normal_korean_no_penalty(self):
        # 정상 한국어 경제 본문은 -15 안 걸려야
        r = score_5criteria(
            "한국은행 정책",
            "금리 동결은 가계부채 부담을 고려한 결정이다.",
        )
        assert r["scores"]["consistency"] == 20


class TestKoreanEndToEnd:
    """실제 Reviewer 출력 수준의 한국어 본문 전체 평가."""

    def test_well_crafted_korean_draft_passes(self):
        """해석 + 글로벌 + 팔로워 + 재방문 모두 있는 한국어 본문 → pass."""
        hook = "한국은행 금리 동결, 가계부채 둔화가 핵심 배경"
        body = (
            "가계부채 증가 속도가 꺾이면서 한국은행이 긴축 기조를 유지할 명분이 "
            "약해졌다. 그러나 환율과 부동산 가격이 여전히 불안정해 공격적 완화는 "
            "어려운 구조다. 이 동결은 타협의 결과로, 투자자는 향후 3개월 동안 "
            "환율과 주택가격 지표를 주시해야 한다."
        )
        r = score_5criteria(hook, body)
        assert r["action"] == "pass", (
            f"정상 Reviewer 한국어 본문인데 action={r['action']}, "
            f"total={r['total']}, scores={r['scores']}"
        )
        assert r["total"] >= 70

    def test_sparse_korean_summary_still_rejects(self):
        """해석 없는 빈약한 한국어 요약 → reject 유지 (억지 인플레 없음)."""
        hook = "한국은행, 7회 연속 기준금리 2.75% 동결"
        body = (
            "가계부채 증가 속도가 둔화되고 내수가 부진한 상황에서 한국은행은 "
            "안정성을 우선시하며 통화정책의 신중함을 보였다."
        )
        r = score_5criteria(hook, body)
        assert r["action"] == "reject", (
            f"해석 없는 요약인데 action={r['action']}, total={r['total']}. "
            f"패턴이 너무 느슨함."
        )
        assert r["total"] < 50

    def test_korean_clickbait_rejects(self):
        r = score_5criteria(
            "충격! 한국 재벌 스캔들 루머",
            "대박 소름 난리난 가십, 이 스캔들 실화냐?",
        )
        assert r["action"] == "reject"


class TestEnglishRegression:
    """영어 평가는 기존과 동일해야 한다. 패턴은 건드리지 않았고 OR 결합만 추가."""

    def test_well_crafted_english_passes(self):
        hook = "Why the BOK freeze means dollar pressure on Korean won"
        body = (
            "The structural mechanism is simple. Global investors watch this "
            "pattern closely because it signals Fed divergence. Your portfolio "
            "exposure to Korean semiconductor exporters changes meaningfully "
            "over the next quarter. Follow for the weekly thread."
        )
        r = score_5criteria(hook, body)
        assert r["action"] == "pass"
        assert r["total"] >= 70

    def test_english_translation_rejects(self):
        hook = "South Korea announced new policy"
        body = "The government said it will review measures."
        r = score_5criteria(hook, body)
        assert r["action"] == "reject"
        # Translation 패턴에 훅이 걸리므로 expertise 0
        assert r["scores"]["expertise"] == 0

    def test_english_clickbait_rejects(self):
        hook = "SHOCKING celebrity scandal"
        body = "You won't believe this insane drama."
        r = score_5criteria(hook, body)
        assert r["action"] == "reject"


class TestPatternIsolation:
    """
    각 한국어 dimension 이 독립적으로 동작하는지 — 한 패턴이 다른 dimension
    으로 점수가 번지지 않아야 한다 (점수 더블카운팅 방지).
    """

    def test_only_interpretation_keyword(self):
        """해석 키워드만 있고 나머지 신호 없음 → expertise 만 올라가야."""
        r = score_5criteria("A", "이것의 의미는 무엇인가.")
        assert r["scores"]["expertise"] >= 15
        assert r["scores"]["marketability"] == 0
        assert r["scores"]["repeat_consumption"] == 0

    def test_only_marketability_keyword(self):
        r = score_5criteria("B", "글로벌 달러 흐름.")
        assert r["scores"]["marketability"] >= 20
        assert r["scores"]["repeat_consumption"] == 0

    def test_only_repeat_keyword(self):
        r = score_5criteria("C", "다음 주 패턴을 주시해야.")
        assert r["scores"]["repeat_consumption"] >= 20
        # '주시' 가 expertise 로 번지면 안 됨
        assert r["scores"]["expertise"] < 15
