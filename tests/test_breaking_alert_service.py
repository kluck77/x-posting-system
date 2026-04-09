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
# 1) payload 조립 — docs §3 8필드 모두 렌더링되는지 + §5 라벨 고정
# ---------------------------------------------------------------------------
def test_build_breaking_alert_text_contains_all_required_fields():
    r = _breaking_result()
    text = build_breaking_alert_text(
        breaking_result=r,
        title="한은 기준금리 25bp 인하 의결",
        url="https://www.bok.or.kr/news/1",
        body=(
            "4월 9일 금통위가 기준금리를 연 3.25%에서 3.00%로 25bp 인하 의결했다. "
            "시장 컨센서스는 동결이었으며, 발표 직후 단기 채권 금리가 즉시 하락 반응했다."
        ),
    )
    # §3 필드 1 : 제목 + [속보] prefix
    assert text.startswith("[속보] 한은 기준금리 25bp 인하 의결")
    # §3 필드 2 : 핵심 요지 라벨 + body 선두 문장 반영
    assert "핵심 :" in text
    assert "금통위가 기준금리를" in text
    # §3 필드 3 : 키워드 라벨 + 매칭 키워드
    assert "키워드 :" in text
    assert "기준금리" in text
    # §3 필드 4 : 영향 자산군
    assert "영향 자산군 : 금융" in text
    # §3 필드 5 : 긴급도 (소문자 유지, docs §4)
    assert "긴급도 : high" in text
    # §3 필드 6 : 분류 사유
    assert "분류 사유 :" in text
    assert "정책 결정" in text
    # §3 필드 7 : 원문 링크
    assert "원문 : https://www.bok.or.kr/news/1" in text
    # §3 필드 8 : 운영자 액션 힌트 (high → "즉시 확인")
    assert "운영자 액션 :" in text
    assert "즉시 확인" in text
    # §3 부가 정보 : 수집 시각 (YYYY-MM-DD HH:MM KST)
    assert "시각 :" in text
    assert "KST" in text
    # §4 이모지 금지
    for ch in "🚨⚠️🔔📰🏷️📂🔑💥⚡🔗":
        assert ch not in text
    # §4 HTML 태그 금지 (plain text 로 전환)
    assert "<b>" not in text
    assert "</b>" not in text


def test_build_breaking_alert_text_handles_missing_url():
    r = _breaking_result()
    text = build_breaking_alert_text(
        breaking_result=r, title="t", url=None, body="본문 없음."
    )
    # §3 필드 7 : url 없을 때 "원문 :" 라인 자체가 없어야 한다
    assert "원문 :" not in text
    # 다른 필수 필드는 여전히 존재
    assert "[속보] t" in text
    assert "핵심 :" in text
    assert "긴급도 :" in text


# ---------------------------------------------------------------------------
# 1-b) 템플릿 상세 : medium 긴급도 / body 부재 fallback / 제목 clip / 600자 상한
# ---------------------------------------------------------------------------
def test_build_breaking_alert_text_medium_urgency_action_hint():
    r = ClassificationResult(
        classification="BREAKING_NOW",  # type: ignore[arg-type]
        topic_domain="금융",
        matched_keywords=["환율", "1,420"],
        breaking_reason="가격 충격 + 단기 변동 + 1차 시세 출처",
        urgency="medium",
    )
    text = build_breaking_alert_text(
        breaking_result=r,
        title="원/달러 환율 장중 1,420원 돌파",
        url="https://example.com/fx/1",
        body="4월 9일 오전 환율이 장중 1,420원을 돌파했다. 1주일 전 대비 +1.8% 변동.",
    )
    # §3 필드 5 medium 소문자 (docs §4)
    assert "긴급도 : medium" in text
    # §3 필드 8 medium → "정보만" (§6.3 / §6.4 예시)
    assert "정보만" in text
    # high 경로 문구가 섞이지 않아야 한다
    assert "즉시 확인" not in text


def test_build_breaking_alert_text_summary_falls_back_to_title_when_body_missing():
    r = _breaking_result()
    text = build_breaking_alert_text(
        breaking_result=r,
        title="한은 기준금리 25bp 인하 의결",
        url="https://example.com/1",
        body=None,
    )
    # body 없을 때도 "핵심 :" 라벨은 존재 (§3 필드 2 생략 금지)
    assert "핵심 :" in text
    # fallback : 제목이 핵심 요지 자리에 들어간다
    # (요지 라벨 + 제목 문구)
    assert "핵심 : 한은 기준금리 25bp 인하 의결" in text


def test_build_breaking_alert_text_extracts_only_first_two_sentences():
    r = _breaking_result()
    body = (
        "첫 문장은 핵심이다. "
        "두 번째 문장은 맥락이다. "
        "세 번째 문장은 무시되어야 한다. "
        "네 번째 문장도 포함되면 안 된다."
    )
    text = build_breaking_alert_text(
        breaking_result=r, title="t", url=None, body=body,
    )
    assert "첫 문장은 핵심이다" in text
    assert "두 번째 문장은 맥락이다" in text
    assert "세 번째 문장은 무시되어야 한다" not in text
    assert "네 번째 문장" not in text


def test_build_breaking_alert_text_title_clipped_to_60_chars():
    r = _breaking_result()
    # 60자 초과 제목
    long_title = "가" * 80
    text = build_breaking_alert_text(
        breaking_result=r, title=long_title, url=None, body="본문."
    )
    # [속보] 라인은 [속보] + 공백 + (제목 ≤ 60자, 끝 `…`)
    header_line = text.splitlines()[0]
    # 원문 제목 80자 그대로는 들어가면 안 됨
    assert "가" * 80 not in header_line
    # 끝에 `…` 표시
    assert header_line.endswith("…")


def test_build_breaking_alert_text_respects_total_length_budget():
    r = _breaking_result()
    text = build_breaking_alert_text(
        breaking_result=r,
        title="한은 기준금리 25bp 인하 의결",
        url="https://example.com/1",
        body=(
            "4월 9일 금통위가 기준금리를 연 3.25%에서 3.00%로 25bp 인하 의결했다. "
            "시장 컨센서스는 동결이었으며, 발표 직후 단기 채권 금리가 즉시 하락 반응했다."
        ),
    )
    # §4 600자 상한 (하드 캡)
    assert len(text) <= 600


def test_build_breaking_alert_text_collected_at_uses_kst_format():
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    r = _breaking_result()
    text = build_breaking_alert_text(
        breaking_result=r,
        title="t",
        url=None,
        body="본문.",
        collected_at=datetime(2026, 4, 9, 11, 2, tzinfo=kst),
    )
    assert "시각 : 2026-04-09 11:02 KST" in text


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
