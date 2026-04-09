"""
BREAKING ALERT SERVICE 테스트 (P1 stage-3, S3-C + S3-A)
=======================================================
검증 범위:
1. build_breaking_alert_text : 7개 필수 필드 모두 출력되는지
2. send_breaking_alert        : BREAKING_NOW 에서만 실제 시도
3. send_breaking_alert        : CANDIDATE/HOLD/REJECT 는 즉시 False
4. send_breaking_alert        : 텔레그램 미설정 시 MOCK True
5. send_breaking_alert        : httpx.HTTPError 를 삼키고 False (fail-open)
6. orchestrator.py wiring     : Step 1.6 BREAKING_NOW 분기 smoke

S3-A 추가 범위 (dedup 최소 연결)
7. normalize_title / compute_issue_key   : §6 / §7.1 최소 구현 속성
8. send_breaking_alert dedup 게이트       : window 내 2회 → 1회만 발송
9. send_breaking_alert dedup 게이트       : window 밖 → 재발송 허용
10. send_breaking_alert dedup 게이트       : 다른 이슈는 서로 영향 없음
11. send_breaking_alert dedup fail-open   : dedup 계산 예외 → 전송 진행
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.breaking_alert_service import (
    BREAKING_DEDUP_WINDOW_SECONDS,
    _reset_dedup_store_for_tests,
    build_breaking_alert_text,
    compute_issue_key,
    normalize_title,
    send_breaking_alert,
)
from app.services.breaking_classifier import ClassificationResult


@pytest.fixture(autouse=True)
def _clean_dedup_store():
    """
    각 테스트마다 dedup 저장소를 초기화.
    프로세스 내 dict 기반이므로 테스트 간 상태 누수를 방지한다.
    """
    _reset_dedup_store_for_tests()
    yield
    _reset_dedup_store_for_tests()


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


# ===========================================================================
# S3-A : DEDUP 최소 연결
# ===========================================================================

# ---------------------------------------------------------------------------
# 7) normalize_title / compute_issue_key 속성
# ---------------------------------------------------------------------------
class TestNormalizeTitleAndIssueKey:
    def test_normalize_title_strips_leading_bracket_tags(self):
        # [속보][단독] 같은 선행 브래킷 태그는 제거된다
        t = normalize_title("[속보][단독] 한은 기준금리 25bp 인하 의결")
        assert "속보" not in t
        assert "단독" not in t
        assert "기준금리" in t

    def test_normalize_title_strips_publisher_tail(self):
        # "- 연합뉴스" 같은 꼬리표는 제거된다
        t = normalize_title("한은 기준금리 25bp 인하 의결 - 연합뉴스")
        assert "연합뉴스" not in t
        assert "기준금리" in t

    def test_normalize_title_deterministic(self):
        a = normalize_title("한은 기준금리 25bp 인하 의결")
        b = normalize_title("한은 기준금리 25bp 인하 의결")
        assert a == b
        assert a != ""

    def test_normalize_title_empty_input(self):
        assert normalize_title("") == ""
        assert normalize_title("   ") == ""

    def test_compute_issue_key_format(self):
        # <coarse_bucket>:<entity_slug>:<topic_slug>:<hash8>
        key = compute_issue_key(
            title="한은 기준금리 25bp 인하 의결", topic_domain="금융",
        )
        parts = key.split(":")
        assert len(parts) == 4
        # §7.1 : 금융 → macro 버킷
        assert parts[0] == "macro"
        # MVP : entity_slug = unknown 고정
        assert parts[1] == "unknown"
        # topic_slug 는 비어있지 않음
        assert parts[2] != ""
        # hash8 은 8자
        assert len(parts[3]) == 8

    def test_compute_issue_key_deterministic(self):
        k1 = compute_issue_key(title="한은 기준금리 25bp 인하 의결", topic_domain="금융")
        k2 = compute_issue_key(title="한은 기준금리 25bp 인하 의결", topic_domain="금융")
        assert k1 == k2

    def test_compute_issue_key_distinct_for_different_titles(self):
        k1 = compute_issue_key(title="한은 기준금리 25bp 인하 의결", topic_domain="금융")
        k2 = compute_issue_key(title="국내 거래소 원화 출금 일시 중단", topic_domain="크립토")
        assert k1 != k2

    def test_compute_issue_key_bucket_mapping(self):
        # ACCOUNT_CONSTITUTION 4개 도메인 → spec 6개 버킷
        assert compute_issue_key(title="t", topic_domain="크립토").split(":")[0] == "crypto"
        assert compute_issue_key(title="t", topic_domain="주식").split(":")[0] == "stock"
        assert compute_issue_key(title="t", topic_domain="금융").split(":")[0] == "macro"
        assert compute_issue_key(title="t", topic_domain="투자").split(":")[0] == "macro"
        assert compute_issue_key(title="t", topic_domain="none").split(":")[0] == "other"


# ---------------------------------------------------------------------------
# 8) dedup 게이트 : window 내 2회 → 1회만 MOCK 모드에서도 차단됨
# ---------------------------------------------------------------------------
def test_send_breaking_alert_dedup_blocks_second_within_window_mock():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False

        first = asyncio.run(
            send_breaking_alert(
                breaking_result=r,
                title="한은 기준금리 25bp 인하 의결",
                url="https://example.com/1",
                now=1_000_000.0,
            )
        )
        # 같은 시점 (조금 뒤) 에 같은 이슈 → 차단
        second = asyncio.run(
            send_breaking_alert(
                breaking_result=r,
                title="한은 기준금리 25bp 인하 의결",
                url="https://example.com/1",
                now=1_000_001.0,
            )
        )
    assert first is True
    assert second is False, "dedup window 내 중복은 False 로 차단되어야 한다"


# ---------------------------------------------------------------------------
# 8-b) dedup 게이트 : 실제 텔레그램 경로에서도 2번째 호출이 POST 되지 않음
# ---------------------------------------------------------------------------
def test_send_breaking_alert_dedup_does_not_call_telegram_twice():
    r = _breaking_result()

    ok_response = MagicMock()
    ok_response.raise_for_status = MagicMock(return_value=None)
    ok_response.json = MagicMock(
        return_value={"ok": True, "result": {"message_id": 1}}
    )

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=ok_response)

    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = True
        mock_settings.telegram_bot_token = "fake"
        mock_settings.telegram_chat_id = "fake"
        with patch(
            "app.services.breaking_alert_service.httpx.AsyncClient",
            return_value=mock_client,
        ):
            asyncio.run(
                send_breaking_alert(
                    breaking_result=r,
                    title="한은 기준금리 25bp 인하 의결",
                    url="https://example.com/1",
                    now=2_000_000.0,
                )
            )
            asyncio.run(
                send_breaking_alert(
                    breaking_result=r,
                    title="한은 기준금리 25bp 인하 의결",
                    url="https://example.com/1",
                    now=2_000_060.0,
                )
            )

    assert mock_client.post.await_count == 1, (
        "dedup 차단 경로에서는 텔레그램 POST 가 1회만 수행되어야 한다"
    )


# ---------------------------------------------------------------------------
# 9) dedup 게이트 : window 밖 → 재발송 허용
# ---------------------------------------------------------------------------
def test_send_breaking_alert_dedup_allows_after_window_expires():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False

        first = asyncio.run(
            send_breaking_alert(
                breaking_result=r,
                title="한은 기준금리 25bp 인하 의결",
                url="https://example.com/1",
                now=1_000_000.0,
            )
        )
        # window (6h) + 1s 뒤 → 허용
        later = 1_000_000.0 + BREAKING_DEDUP_WINDOW_SECONDS + 1.0
        second = asyncio.run(
            send_breaking_alert(
                breaking_result=r,
                title="한은 기준금리 25bp 인하 의결",
                url="https://example.com/1",
                now=later,
            )
        )
    assert first is True
    assert second is True, "dedup window 밖에서는 재발송이 허용되어야 한다"


# ---------------------------------------------------------------------------
# 10) dedup 게이트 : 서로 다른 이슈는 서로 영향 없음
# ---------------------------------------------------------------------------
def test_send_breaking_alert_dedup_distinct_issues_independent():
    r1 = _breaking_result()
    r2 = ClassificationResult(
        classification="BREAKING_NOW",  # type: ignore[arg-type]
        topic_domain="크립토",
        matched_keywords=["원화", "중단"],
        breaking_reason="거래소 사고/중단",
        urgency="high",
    )
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False
        a = asyncio.run(
            send_breaking_alert(
                breaking_result=r1,
                title="한은 기준금리 25bp 인하 의결",
                url="https://example.com/a",
                now=1_000_000.0,
            )
        )
        b = asyncio.run(
            send_breaking_alert(
                breaking_result=r2,
                title="국내 5대 거래소 중 1곳 원화 입출금 일시 중단",
                url="https://example.com/b",
                now=1_000_001.0,
            )
        )
    assert a is True and b is True, (
        "서로 다른 이슈 키는 dedup 에서 서로 영향이 없어야 한다"
    )


# ---------------------------------------------------------------------------
# 10-b) dedup 게이트 : 차단 경로에서는 저장소에 기록하지 않는다
#      → 차단된 이슈를 window 한참 밖으로 옮겨도 여전히 허용됨을 통해 검증
# ---------------------------------------------------------------------------
def test_send_breaking_alert_dedup_block_path_does_not_record():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False

        # 첫 전송 → 기록됨
        asyncio.run(
            send_breaking_alert(
                breaking_result=r, title="T", url=None, now=100.0,
            )
        )
        # 2번째 호출은 차단
        blocked = asyncio.run(
            send_breaking_alert(
                breaking_result=r, title="T", url=None, now=200.0,
            )
        )
        assert blocked is False

        # window 한참 밖 → 다시 허용 (차단 경로가 last 값을 덮어쓰지 않았어야 한다)
        later = 100.0 + BREAKING_DEDUP_WINDOW_SECONDS + 10.0
        allowed = asyncio.run(
            send_breaking_alert(
                breaking_result=r, title="T", url=None, now=later,
            )
        )
        assert allowed is True


# ---------------------------------------------------------------------------
# 11) dedup fail-open : compute_issue_key 예외 → 전송 진행
# ---------------------------------------------------------------------------
def test_send_breaking_alert_dedup_fail_open_on_exception():
    r = _breaking_result()
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False
        with patch(
            "app.services.breaking_alert_service.compute_issue_key",
            side_effect=RuntimeError("boom"),
        ):
            result = asyncio.run(
                send_breaking_alert(
                    breaking_result=r,
                    title="한은 기준금리 25bp 인하 의결",
                    url="https://example.com/1",
                    now=1_000_000.0,
                )
            )
    assert result is True, (
        "dedup 계산 예외는 삼키고 (fail-open) MOCK 전송은 True 를 반환해야 한다"
    )


# ---------------------------------------------------------------------------
# 11-b) dedup fail-open : CANDIDATE/HOLD/REJECT 는 여전히 (dedup 이전에) 차단
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("klass", ["CANDIDATE", "HOLD", "REJECT"])
def test_send_breaking_alert_dedup_does_not_affect_non_breaking(klass):
    r = _breaking_result(classification=klass)
    with patch("app.services.breaking_alert_service.settings") as mock_settings:
        mock_settings.has_telegram_config = False
        result = asyncio.run(
            send_breaking_alert(breaking_result=r, title="t", url=None, now=100.0)
        )
    assert result is False, (
        "비-BREAKING_NOW classification 은 dedup 과 무관하게 즉시 False 여야 한다"
    )
