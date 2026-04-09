"""
BREAKING CLASSIFIER WIRING 테스트 (P1 stage-2)
==============================================
breaking_classifier 가 기존 orchestrator 파이프라인의 Step 1.5 진입점에
fail-open 으로 연결되어 있는지 검증한다.

본 테스트의 목적은:
1. orchestrator.py 소스에 wiring 이 박혀 있는지 (smoke)
2. classify_article 가 orchestrator 가 넘기는 5개 kwarg 시그니처를 수용하는지 (contract)

전체 파이프라인(DB / AI / rate limiter) 통합 테스트는 본 단계 범위 밖.
"""

from datetime import datetime
from pathlib import Path

from app.services.breaking_classifier import (
    ClassificationResult,
    classify_article,
)


# ---------------------------------------------------------------------------
# 1) Smoke: orchestrator 소스에 wiring 문구가 박혀 있어야 한다
# ---------------------------------------------------------------------------
def test_orchestrator_source_contains_breaking_classifier_wiring():
    orch_path = Path(__file__).resolve().parents[1] / "app" / "orchestrator.py"
    src = orch_path.read_text(encoding="utf-8")

    # breaking_classifier 모듈 호출이 존재해야 함
    assert "breaking_classifier" in src, (
        "orchestrator.py 에 breaking_classifier wiring 이 사라졌다 — "
        "Step 1.5 hook 이 제거된 것으로 보임"
    )
    assert "classify_article(" in src, (
        "orchestrator.py 에서 classify_article() 호출이 사라졌다"
    )

    # fail-open 가드가 유지되어야 함 (try/except 블록)
    assert "breaking classify 실패" in src, (
        "orchestrator.py 의 breaking classify fail-open 경고 로그가 사라졌다"
    )

    # Step 1.5 라벨 유지 (추후 grep 으로 빠르게 찾기 위함)
    assert "[1.5/6]" in src, "Step 1.5 log label 누락"


# ---------------------------------------------------------------------------
# 2) Contract: classify_article 가 orchestrator 가 넘기는 5개 kwarg 을 받는다
# ---------------------------------------------------------------------------
def test_classify_article_accepts_source_item_field_mapping():
    """
    orchestrator 가 SourceItem 필드에서 추출하여 넘기는 5개 kwarg 시그니처
    (title / body / publisher / published_at / url) 가 그대로 유효함을 핀다.

    SourceItem 스키마가 변경되면 본 테스트가 먼저 깨져야 한다.
    """
    result = classify_article(
        title="한은 기준금리 25bp 인하 의결 — 시장 동결 컨센서스 뒤집어",
        body=(
            "4월 9일 금통위가 기준금리를 연 3.25%에서 3.00%로 25bp 인하 의결했다. "
            "시장 컨센서스는 동결이었으며, 발표 직후 단기 채권 금리가 즉시 하락 반응했다. "
            "한은 총재는 가계부채 증가 속도와 환율 변동성에 대한 우려를 언급했다. "
            "국고채 3년물 금리는 장중 10bp 이상 밀렸고 원/달러 환율은 소폭 반등했다."
        ),
        publisher=None,
        published_at=datetime(2026, 4, 9, 11, 0),
        url="https://www.bok.or.kr/portal/news/123",
    )
    assert isinstance(result, ClassificationResult)
    assert result.classification in ("BREAKING_NOW", "CANDIDATE", "HOLD", "REJECT")
    assert result.topic_domain in ("금융", "투자", "크립토", "주식", "none")


# ---------------------------------------------------------------------------
# 3) Fail-open 가드: None body 등 비정상 입력에서도 예외 없이 HOLD 로 내려와야 한다
# ---------------------------------------------------------------------------
def test_classify_article_returns_hold_on_degenerate_input():
    """
    orchestrator wiring 은 fail-open 이므로 classify_article 자체도
    비정상 입력에 raise 하지 않고 HOLD 로 내려오는 것이 바람직하다.
    """
    result = classify_article(
        title="",
        body="",
        publisher=None,
        published_at=None,
        url=None,
    )
    assert isinstance(result, ClassificationResult)
    assert result.classification == "HOLD"
