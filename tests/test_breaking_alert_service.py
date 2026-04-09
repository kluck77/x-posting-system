"""
BREAKING ALERT SERVICE 테스트 (P1 stage-3, S3-C)
================================================
검증 범위:
1. build_breaking_alert_text : 7개 필수 필드 모두 출력되는지
2. send_breaking_alert        : BREAKING_NOW 에서만 실제 시도
3. send_breaking_alert        : CANDIDATE/HOLD/REJECT 는 즉시 False
4. send_breaking_alert        : 텔레그램 미설정 시 MOCK True
5. send_breaking_alert        : httpx.HTTPError 를 삼키고 False (fail-open)
6. orchestrator.py wiring     : Step 1.6 BREAKING_NOW 분기 smoke
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.breaking_alert_service import (
    build_breaking_alert_text,
    send_breaking_alert,
)
from app.services.breaking_classifier import ClassificationResult


def _breaking_result(classification: str = "BREAKING_NOW") -> ClassificationResult:
    return ClassificationResult(
        classification=classification,  # type: ignore[arg-type]
        topic_domain="금융",
        matched_keywords=["기준금리", "한은"],
        breaking_reason="정책 결정 (인하 의결)",
        urgency="high" if classification == "BREAKING_NOW" else None,
    )


# ---------------------------------------------------------------------------
# 1) payload 조립 — 7개 필드 모두 렌더링되는지
# ---------------------------------------------------------------------------
def test_build_breaking_alert_text_contains_all_required_fields():
    r = _breaking_result()
    text = build_breaking_alert_text(
        breaking_result=r,
        title="한은 기준금리 25bp 인하 의결",
        url="https://www.bok.or.kr/news/1",
    )
    assert "BREAKING ALERT" in text
    assert "한은 기준금리 25bp 인하 의결" in text  # title
    assert "BREAKING_NOW" in text                    # classification
    assert "금융" in text                            # topic_domain
    assert "기준금리" in text                        # matched_keywords
    assert "정책 결정" in text                        # breaking_reason
    assert "HIGH" in text                            # urgency (uppercased)
    assert "https://www.bok.or.kr/news/1" in text    # url


def test_build_breaking_alert_text_handles_missing_url():
    r = _breaking_result()
    text = build_breaking_alert_text(breaking_result=r, title="t", url=None)
    assert "Source:" not in text  # url 없으면 Source 줄 생략


# ---------------------------------------------------------------------------
# 2/3) classification != BREAKING_NOW → 즉시 False
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("klass", ["CANDIDATE", "HOLD", "REJECT"])
def test_send_breaking_alert_ignored_for_non_breaking(klass):
    r = _breaking_result(classification=klass)
    result = asyncio.run(
        send_breaking_alert(breaking_result=r, title="t", url="https://x.com/1")
    )
    assert result is False


# ---------------------------------------------------------------------------
# 4) MOCK 모드 (telegram 미설정) → True
# ---------------------------------------------------------------------------
def test_send_breaking_alert_mock_mode_returns_true():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False
        result = asyncio.run(
            send_breaking_alert(breaking_result=r, title="t", url="https://x.com/1")
        )
    assert result is True


# ---------------------------------------------------------------------------
# 5) httpx 실패 → False, 예외 전파 없음 (fail-open)
# ---------------------------------------------------------------------------
def test_send_breaking_alert_fail_open_on_http_error():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = True
        mock_settings.telegram_bot_token = "fake"
        mock_settings.telegram_chat_id = "fake"

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("boom"))

        with patch(
            "app.services.breaking_alert_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = asyncio.run(
                send_breaking_alert(breaking_result=r, title="t", url="https://x.com/1")
            )
    assert result is False  # raise 되지 않고 False 로 내려와야 한다


def test_send_breaking_alert_success_returns_true():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = True
        mock_settings.telegram_bot_token = "fake"
        mock_settings.telegram_chat_id = "fake"

        ok_response = MagicMock()
        ok_response.raise_for_status = MagicMock(return_value=None)
        ok_response.json = MagicMock(
            return_value={"ok": True, "result": {"message_id": 1}}
        )

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=ok_response)

        with patch(
            "app.services.breaking_alert_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = asyncio.run(
                send_breaking_alert(breaking_result=r, title="t", url="https://x.com/1")
            )
    assert result is True


# ---------------------------------------------------------------------------
# 6) orchestrator wiring smoke — Step 1.6 분기 존재
# ---------------------------------------------------------------------------
def test_orchestrator_has_breaking_alert_branch():
    orch_path = Path(__file__).resolve().parents[1] / "app" / "orchestrator.py"
    src = orch_path.read_text(encoding="utf-8")
    assert "breaking_alert_service" in src, (
        "orchestrator.py 에 breaking_alert_service 연결이 사라졌다"
    )
    assert "send_breaking_alert(" in src, (
        "orchestrator.py 에 send_breaking_alert() 호출이 사라졌다"
    )
    assert 'BREAKING_NOW' in src, (
        "orchestrator.py 에 BREAKING_NOW 분기 조건이 사라졌다"
    )
    assert "[1.6/6]" in src, "Step 1.6 label 누락"
