"""
BREAKING ALERT CLASSIFIER 테스트
================================
네이버 기사 입력 1건의 분류(BREAKING_NOW / CANDIDATE / HOLD / REJECT) 를 검증한다.

본 테스트는 docs/TELEGRAM_BREAKING_ALERT_TEMPLATE.md §6 예시와
docs/ACCOUNT_CONSTITUTION.md §1.2 / §2 정합 여부를 중심으로 작성했다.
"""

from datetime import datetime

from app.services.breaking_classifier import (
    classify_article,
    ClassificationResult,
)


# ---------------------------------------------------------------------------
# BREAKING_NOW 예시 2개
# ---------------------------------------------------------------------------
class TestBreakingNow:
    def test_한은_기준금리_인하_의결_high(self):
        result = classify_article(
            title="한은 기준금리 25bp 인하 의결 — 시장 동결 컨센서스 뒤집어",
            body=(
                "4월 9일 금통위가 기준금리를 연 3.25%에서 3.00%로 25bp 인하 의결했다. "
                "시장 컨센서스는 동결이었으며, 발표 직후 단기 채권 금리가 즉시 하락 반응했다. "
                "한은 총재는 가계부채 증가 속도와 환율 변동성에 대한 우려를 언급했다. "
                "국고채 3년물 금리는 장중 10bp 이상 밀렸고 원/달러 환율은 소폭 반등했다. "
                "다음 금통위까지 정책 기대 경로가 재조정될 전망이다."
            ),
            publisher="연합뉴스",
            published_at=datetime(2026, 4, 9, 11, 0),
            url="https://www.bok.or.kr/portal/news/123",
        )
        assert result.classification == "BREAKING_NOW"
        assert result.topic_domain == "금융"
        assert result.urgency == "high"
        assert result.breaking_reason is not None
        assert "정책" in result.breaking_reason
        assert any("기준금리" in kw or "금통위" in kw for kw in result.matched_keywords)

    def test_거래소_출금_중단_high(self):
        result = classify_article(
            title="국내 5대 거래소 중 1곳 원화 입출금 일시 중단 공지",
            body=(
                "거래소 공식 공지로 원화 입출금이 무기한 일시 중단됐다. "
                "사유는 전산 점검으로만 명시되어 있고 추가 설명이나 재개 시점은 공지되지 않았다. "
                "업비트와 빗썸 등 다른 국내 거래소는 정상 운영 중이며 현재 문제는 확인되지 않았다. "
                "이용자 커뮤니티에서는 출금 지연에 대한 문의가 급증하고 있는 상황이다. "
                "운영사 측은 추가 공지를 빠르게 올릴 예정이라고만 밝혔다."
            ),
            publisher="코인데스크코리아",
            published_at=datetime(2026, 4, 9, 11, 14),
            url="https://upbit.com/service_center/notice/789",
        )
        assert result.classification == "BREAKING_NOW"
        assert result.topic_domain == "크립토"
        assert result.urgency == "high"
        assert result.breaking_reason is not None
        assert "사고" in result.breaking_reason or "중단" in result.breaking_reason


# ---------------------------------------------------------------------------
# CANDIDATE 예시 2개
# ---------------------------------------------------------------------------
class TestCandidate:
    def test_코스피_외국인_매도_strong_no_breaking(self):
        result = classify_article(
            title="코스피, 외국인 매도 우위로 약보합 마감",
            body=(
                "코스피가 오늘 외국인 매도 우위로 약보합 마감했다. "
                "기관 매수세는 약했고 연기금은 소폭 순매수에 그쳤다. "
                "거래대금은 전일 대비 크게 줄었고 업종별 수급 차이가 있었다."
            ),
            publisher="한국경제",
            published_at=datetime(2026, 4, 9, 15, 40),
            url="https://www.hankyung.com/article/123",
        )
        assert result.classification == "CANDIDATE"
        assert result.topic_domain == "주식"
        assert result.breaking_reason is None
        assert result.urgency is None
        assert len(result.matched_keywords) >= 1

    def test_비트코인_온체인_분석_strong_no_breaking(self):
        result = classify_article(
            title="비트코인 온체인 순유입 이틀째 — 장기 보유자 비중 증가",
            body=(
                "비트코인 온체인 데이터에서 장기 보유자 비중이 이틀 연속 늘었다. "
                "거래소 유입 물량은 평소보다 적었고 장기 보유 지갑으로의 이동이 관측됐다. "
                "ETH 동향은 상대적으로 조용했다."
            ),
            publisher="블록미디어",
            published_at=datetime(2026, 4, 9, 10, 12),
            url="https://www.blockmedia.co.kr/archives/123",
        )
        assert result.classification == "CANDIDATE"
        assert result.topic_domain == "크립토"
        assert result.breaking_reason is None
        assert result.urgency is None


# ---------------------------------------------------------------------------
# HOLD 예시 2개
# ---------------------------------------------------------------------------
class TestHold:
    def test_본문_짧음_도메인무관_hold(self):
        # 본문 짧고 제목에 STRONG 키워드 없음 → HOLD
        result = classify_article(
            title="오늘 시장 동향 요약",
            body="시장이 조용했다.",
            publisher="연합뉴스",
            published_at=datetime(2026, 4, 9, 11, 5),
            url="https://www.yna.co.kr/view/123",
        )
        assert result.classification == "HOLD"
        assert result.topic_domain == "none"

    def test_본문_짧음_제목_강한키워드_candidate(self):
        # 본문 짧아도 제목에 STRONG 키워드 있으면 CANDIDATE 구제
        result = classify_article(
            title="한은 기준금리 인하 의결 (속보)",
            body="한은이 기준금리를 인하했다.",
            publisher="연합뉴스",
            published_at=datetime(2026, 4, 9, 11, 5),
            url="https://www.yna.co.kr/view/123",
        )
        assert result.classification == "CANDIDATE"
        assert result.topic_domain == "금융"
        assert len(result.matched_keywords) >= 1

    def test_url_누락_hold(self):
        # 본문 / 도메인은 충분해도 URL 이 없으면 HOLD (FILTER §10.2)
        result = classify_article(
            title="비트코인 현물 ETF 순유입 확대",
            body=(
                "비트코인 현물 ETF 일일 순유입이 이틀 연속 늘었다. "
                "거래소 간 베이시스는 여전히 좁게 유지되고 있다. "
                "온체인 데이터도 꾸준한 누적 매수를 보이고 있다."
            ),
            publisher="코인데스크코리아",
            published_at=datetime(2026, 4, 9, 9, 0),
            url="",
        )
        assert result.classification == "HOLD"
        assert result.topic_domain == "none"


# ---------------------------------------------------------------------------
# REJECT 예시 2개
# ---------------------------------------------------------------------------
class TestReject:
    def test_연예_드라마_exclude(self):
        result = classify_article(
            title="인기 드라마 주연 배우 열애설 보도",
            body=(
                "인기 드라마의 주연 배우가 열애 중이라는 보도가 나왔다. "
                "소속사는 아직 공식 입장을 내지 않았다. "
                "팬 커뮤니티에서는 다양한 반응이 나오고 있다."
            ),
            publisher="스포츠연예",
            published_at=datetime(2026, 4, 9, 8, 30),
            url="https://entertain.example.com/news/1",
        )
        assert result.classification == "REJECT"
        assert result.topic_domain == "none"
        assert any(
            kw in ("드라마", "배우", "열애", "연예") for kw in result.matched_keywords
        )

    def test_도메인_밖_일반_사회_reject(self):
        result = classify_article(
            title="서울시, 여의도 봄꽃 축제 개최 안내",
            body=(
                "서울시가 다음 주 금요일부터 여의도 봄꽃 축제를 개최한다. "
                "축제 기간 일부 도로는 통제되며 셔틀버스가 운행된다. "
                "시민 100만명 이상 방문이 예상된다."
            ),
            publisher="서울신문",
            published_at=datetime(2026, 4, 9, 7, 0),
            url="https://seoul.example.com/news/99",
        )
        assert result.classification == "REJECT"
        assert result.topic_domain == "none"
        assert result.matched_keywords == []


# ---------------------------------------------------------------------------
# 반환 타입 방어
# ---------------------------------------------------------------------------
def test_return_type_is_classification_result():
    result = classify_article(
        title="테스트",
        body="a",
        url="https://example.com",
    )
    assert isinstance(result, ClassificationResult)
    assert result.classification == "HOLD"
