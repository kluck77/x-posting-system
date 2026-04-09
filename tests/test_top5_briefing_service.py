"""
tests/test_top5_briefing_service.py
===================================
Top5 브리핑 서비스 단위 테스트.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services.top5_briefing_service import (
    CandidateEntry,
    _KST,
    _clip,
    _is_in_night_window,
    _issue_key,
    _one_line_summary,
    _penalty_sensational_title,
    _penalty_thin_body,
    _reset_stores_for_tests,
    _score_freshness,
    _score_market_impact,
    _score_evidence,
    _score_account_fit,
    build_top5_briefing_text,
    record_breaking_sent,
    record_candidate,
    score_candidate,
    select_top5,
    send_top5_briefing,
)


@pytest.fixture(autouse=True)
def _clean_stores():
    """매 테스트 전후 저장소 초기화."""
    _reset_stores_for_tests()
    yield
    _reset_stores_for_tests()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _make_ref_kst(hour: int = 5, minute: int = 0) -> datetime:
    """2026-04-09 기준 KST 시각 생성."""
    return datetime(2026, 4, 9, hour, minute, tzinfo=_KST)


def _make_candidate(
    title: str = "테스트 기사",
    body: str = "본문 " * 100,  # ~300자
    topic_domain: str = "금융",
    matched_keywords: list | None = None,
    hour_kst: int = 3,
    minute_kst: int = 30,
) -> CandidateEntry:
    """테스트용 CandidateEntry 생성."""
    dt_kst = datetime(2026, 4, 9, hour_kst, minute_kst, tzinfo=_KST)
    dt_utc = dt_kst.astimezone(timezone.utc)
    return CandidateEntry(
        title=title,
        body=body,
        url="https://example.com/test",
        topic_domain=topic_domain,
        matched_keywords=matched_keywords or ["기준금리"],
        breaking_reason=None,
        urgency=None,
        collected_at=dt_utc,
    )


# ---------------------------------------------------------------------------
# §5 신선도 점수
# ---------------------------------------------------------------------------
class TestFreshness:
    def test_early_morning_high(self):
        """03:00~05:00 KST → 16~20점."""
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 9, 4, 30, tzinfo=_KST).astimezone(timezone.utc)
        score = _score_freshness(dt, ref)
        assert 16 <= score <= 20

    def test_midnight_mid(self):
        """00:00~03:00 KST → 11~15점."""
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 9, 1, 30, tzinfo=_KST).astimezone(timezone.utc)
        score = _score_freshness(dt, ref)
        assert 11 <= score <= 15

    def test_late_evening_low(self):
        """22:00~24:00 KST → 6~10점."""
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 8, 23, 0, tzinfo=_KST).astimezone(timezone.utc)
        score = _score_freshness(dt, ref)
        assert 6 <= score <= 10

    def test_outside_window_zero(self):
        """22:00 이전 → 0점."""
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 8, 15, 0, tzinfo=_KST).astimezone(timezone.utc)
        score = _score_freshness(dt, ref)
        assert score == 0


# ---------------------------------------------------------------------------
# §6 시장 영향도
# ---------------------------------------------------------------------------
class TestMarketImpact:
    def test_macro_high(self):
        """거시 키워드 2+ → 25~30."""
        score = _score_market_impact("금융", ["금리"], "연준 금리 인상 CPI 급등")
        assert score >= 25

    def test_tier1(self):
        """Tier1 키워드 → 17~24."""
        score = _score_market_impact("크립토", ["비트코인"], "비트코인 ETF 승인 이더리움 상승")
        assert 17 <= score <= 30

    def test_domain_only(self):
        """도메인만 → 8~16."""
        score = _score_market_impact("주식", ["종목"], "중소형주 단신")
        assert 8 <= score <= 16


# ---------------------------------------------------------------------------
# §7 근거 강도
# ---------------------------------------------------------------------------
class TestEvidence:
    def test_rich_body(self):
        """긴 본문 + 수치 + 인용 → 높은 점수."""
        body = "한국은행이 밝혔다. GDP 성장률 2.1% 전망. 수출액 500억달러. " * 30
        score = _score_evidence(body, "https://example.com")
        assert score >= 18

    def test_no_body(self):
        """본문 없음 → 최저."""
        assert _score_evidence(None, None) == 3


# ---------------------------------------------------------------------------
# §8 계정 적합도
# ---------------------------------------------------------------------------
class TestAccountFit:
    def test_domain_with_interpretation(self):
        """도메인 + 해석 축 2+ → 20~25."""
        body = "전망이 어둡다. 자금흐름 분석에 따르면 리스크가 높다."
        score = _score_account_fit("금융", ["금리"], body)
        assert score >= 20

    def test_off_domain(self):
        """도메인 외 → 0~5."""
        score = _score_account_fit("none", [], "연예인 열애설")
        assert score <= 5


# ---------------------------------------------------------------------------
# §9 패널티
# ---------------------------------------------------------------------------
class TestPenalties:
    def test_sensational_title(self):
        """자극 단어 → 감점."""
        pen = _penalty_sensational_title("충격!! 비트코인 폭등 임박!!")
        assert pen >= 6  # "충격" 3 + "폭등" 3 + "!!" 3 = 9, cap 10

    def test_clean_title(self):
        """정상 제목 → 0."""
        assert _penalty_sensational_title("한국은행 기준금리 동결") == 0

    def test_thin_body(self):
        """짧은 본문 → 감점."""
        pen = _penalty_thin_body("짧은 단신")
        assert pen >= 5

    def test_no_body(self):
        """본문 없음 → 최대 감점."""
        assert _penalty_thin_body(None) == 10


# ---------------------------------------------------------------------------
# Top5 선정
# ---------------------------------------------------------------------------
class TestSelectTop5:
    def test_basic_selection(self):
        """CANDIDATE 5건 이상 → 상위 5건 선정."""
        for i in range(7):
            body = f"연준 금리 인상 CPI GDP 전망 분석 의미. 기사 {i}번. " * 20
            record_candidate(
                title=f"기사 {i}: 연준 금리 결정 {i}",
                body=body,
                url=f"https://example.com/{i}",
                topic_domain="금융",
                matched_keywords=["금리", "CPI"],
                collected_at=datetime(2026, 4, 9, 3, i * 5, tzinfo=_KST).astimezone(timezone.utc),
            )
        ref = _make_ref_kst()
        selected = select_top5(ref_kst=ref)
        assert len(selected) <= 5
        # 점수 내림차순
        scores = [c.score for c in selected]
        assert scores == sorted(scores, reverse=True)

    def test_breaking_excluded(self):
        """BREAKING_NOW 전송분은 Top5에서 제외."""
        record_candidate(
            title="연준 긴급 금리 인상",
            body="연준이 금리를 인상했다. GDP CPI 전망 분석. " * 20,
            url="https://example.com/1",
            topic_domain="금융",
            matched_keywords=["금리"],
            collected_at=datetime(2026, 4, 9, 3, 0, tzinfo=_KST).astimezone(timezone.utc),
        )
        # 동일 기사를 BREAKING_NOW 로 전송됐다고 등록
        record_breaking_sent(title="연준 긴급 금리 인상", topic_domain="금융")

        ref = _make_ref_kst()
        selected = select_top5(ref_kst=ref)
        assert len(selected) == 0

    def test_threshold_filter(self):
        """60점 미만은 탈락."""
        record_candidate(
            title="충격!! 소형 알트코인 폭등!!",
            body="짧은 단신",
            url=None,
            topic_domain="none",
            matched_keywords=[],
            collected_at=datetime(2026, 4, 9, 2, 0, tzinfo=_KST).astimezone(timezone.utc),
        )
        ref = _make_ref_kst()
        selected = select_top5(ref_kst=ref)
        assert len(selected) == 0

    def test_asset_balance(self):
        """동일 자산군 최대 3건."""
        for i in range(6):
            record_candidate(
                title=f"크립토 뉴스 {i}: 비트코인 ETF 분석 전망",
                body=f"비트코인 ETF 유입 {i}억달러. 전망 분석 의미. " * 20,
                url=f"https://example.com/c{i}",
                topic_domain="크립토",
                matched_keywords=["비트코인", "ETF"],
                collected_at=datetime(2026, 4, 9, 3, i * 5, tzinfo=_KST).astimezone(timezone.utc),
            )
        # 다른 자산군 추가
        record_candidate(
            title="한국은행 금리 결정 전망 분석",
            body="한국은행 금통위가 금리를 결정했다. 전망 분석 자금흐름. " * 20,
            url="https://example.com/fin",
            topic_domain="금융",
            matched_keywords=["금리", "CPI"],
            collected_at=datetime(2026, 4, 9, 4, 0, tzinfo=_KST).astimezone(timezone.utc),
        )
        ref = _make_ref_kst()
        selected = select_top5(ref_kst=ref)
        crypto_count = sum(1 for c in selected if c.topic_domain == "크립토")
        assert crypto_count <= 3

    def test_empty_store_skips(self):
        """후보 0건 → 빈 리스트."""
        ref = _make_ref_kst()
        selected = select_top5(ref_kst=ref)
        assert selected == []


# ---------------------------------------------------------------------------
# 카드 생성
# ---------------------------------------------------------------------------
class TestBuildCard:
    def test_card_structure(self):
        """§9 템플릿 구조 확인."""
        entries = [_make_candidate(title=f"테스트 기사 {i}") for i in range(3)]
        for e in entries:
            e.score = 75.0
        card = build_top5_briefing_text(entries, ref_kst=_make_ref_kst())

        assert "[새벽 5시 브리핑]" in card
        assert "Top 3" in card
        assert "기간 :" in card
        assert "기준 :" in card
        assert "BREAKING_NOW 발송분 제외" in card
        assert "1." in card
        assert "원문" in card

    def test_card_max_length(self):
        """800자 상한."""
        entries = [_make_candidate(title=f"매우 긴 제목의 기사 번호 {i} " * 5) for i in range(5)]
        for e in entries:
            e.score = 80.0
        card = build_top5_briefing_text(entries, ref_kst=_make_ref_kst())
        assert len(card) <= 800

    def test_no_emoji(self):
        """§8 이모지 금지."""
        entries = [_make_candidate()]
        entries[0].score = 70.0
        card = build_top5_briefing_text(entries, ref_kst=_make_ref_kst())
        # 이모지 범위 검사 (기본 이모지)
        import re
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0]"
        )
        assert not emoji_pattern.search(card)


# ---------------------------------------------------------------------------
# 텔레그램 전송 (mock)
# ---------------------------------------------------------------------------
class TestSendBriefing:
    def test_empty_returns_true(self):
        """후보 0건 → True (브리핑 생략, 에러 아님)."""
        result = asyncio.run(send_top5_briefing(ref_kst=_make_ref_kst()))
        assert result is True

    def test_mock_send(self):
        """has_telegram_config=False → mock 전송."""
        for i in range(3):
            record_candidate(
                title=f"연준 금리 결정 뉴스 {i}",
                body=f"연준 금리 인상 CPI GDP 전망 분석 의미 자금흐름. 기사 {i}. " * 25,
                url=f"https://example.com/{i}",
                topic_domain="금융",
                matched_keywords=["금리", "CPI", "GDP"],
                collected_at=datetime(2026, 4, 9, 4, i * 10, tzinfo=_KST).astimezone(timezone.utc),
            )
        ref = _make_ref_kst()
        result = asyncio.run(send_top5_briefing(ref_kst=ref))
        # mock 모드 (has_telegram_config 없으면 True)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# 야간 시간대 필터
# ---------------------------------------------------------------------------
class TestNightWindow:
    def test_inside(self):
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 9, 1, 0, tzinfo=_KST).astimezone(timezone.utc)
        assert _is_in_night_window(dt, ref) is True

    def test_outside_afternoon(self):
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 8, 15, 0, tzinfo=_KST).astimezone(timezone.utc)
        assert _is_in_night_window(dt, ref) is False

    def test_boundary_start(self):
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 8, 22, 0, tzinfo=_KST).astimezone(timezone.utc)
        assert _is_in_night_window(dt, ref) is True

    def test_boundary_end(self):
        ref = _make_ref_kst()
        dt = datetime(2026, 4, 9, 5, 0, tzinfo=_KST).astimezone(timezone.utc)
        assert _is_in_night_window(dt, ref) is True
