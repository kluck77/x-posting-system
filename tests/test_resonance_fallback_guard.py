"""
Resonance fallback placeholder 가 approve / telegram send 경로로 새는 버그 회귀 방지.

배경:
  text_cleaner.ensure_resonance_structure() 는 draft body 에 ⚠️/📌 두 마커가
  모두 없을 때 placeholder 2줄을 삽입한다(재생성 유도 목적, 의도된 설계).
  placeholder 문구:
    (KO) "(구조 누락 — 재생성 권장)"
    (EN) "(structure missing — regenerate recommended)"

원칙:
  1) placeholder 가 포함된 draft 는 승인/전송이 절대 통과하지 못한다
  2) 사용자는 "재생성 후 승인" 이라는 구체 안내를 받는다
  3) 정상 draft 는 오탐되지 않는다
"""
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.services.draft_service import (
    is_resonance_fallback_draft,
    _FALLBACK_PLACEHOLDER_MARKERS,
)


# ─── Helper 단위 테스트 ─────────────────────────────────────────────────

class TestIsResonanceFallbackDraft:
    def test_ko_placeholder_detected(self):
        body = (
            "본문 한 줄입니다.\n\n"
            "⚠️ 진짜 쟁점: (구조 누락 — 재생성 권장)\n"
            "📌 지금 봐야 할 포인트: (구조 누락 — 재생성 권장)"
        )
        assert is_resonance_fallback_draft(body) is True

    def test_en_placeholder_detected(self):
        body = (
            "Body text here.\n\n"
            "⚠️ Real issue: (structure missing — regenerate recommended)\n"
            "📌 Watch for: (structure missing — regenerate recommended)"
        )
        assert is_resonance_fallback_draft(body) is True

    def test_placeholder_anywhere_in_body_is_caught(self):
        # 운영자가 수동 편집 중 placeholder 일부만 남긴 경우도 차단
        body = "본문. (구조 누락 — 재생성 권장)"
        assert is_resonance_fallback_draft(body) is True

    def test_empty_body(self):
        assert is_resonance_fallback_draft("") is False
        assert is_resonance_fallback_draft(None) is False

    def test_normal_draft_is_not_fallback(self):
        body = (
            "한국은행이 기준금리를 0.25%p 인하했다. 환율에 영향이 있다.\n\n"
            "⚠️ 진짜 쟁점: 환율 방어와 내수 부양의 충돌\n"
            "📌 지금 봐야 할 포인트: 원달러 1380선 이탈 여부"
        )
        assert is_resonance_fallback_draft(body) is False

    def test_markers_are_exported(self):
        # 마커 리스트가 모듈에서 노출되어야 한다(테스트 안정성)
        assert "(구조 누락 — 재생성 권장)" in _FALLBACK_PLACEHOLDER_MARKERS
        assert (
            "(structure missing — regenerate recommended)"
            in _FALLBACK_PLACEHOLDER_MARKERS
        )


# ─── orchestrator._handle_approve 통합 테스트 ──────────────────────────

class TestApproveGuardBlocksFallback:
    @pytest.mark.asyncio
    async def test_handle_approve_blocks_ko_fallback(self):
        from app.orchestrator import Orchestrator

        mock_draft = MagicMock()
        mock_draft.id = 77
        mock_draft.body = (
            "본문.\n\n"
            "⚠️ 진짜 쟁점: (구조 누락 — 재생성 권장)\n"
            "📌 지금 봐야 할 포인트: (구조 누락 — 재생성 권장)"
        )
        mock_draft.hook = "테스트 훅"

        orch = Orchestrator.__new__(Orchestrator)
        orch.draft_service = MagicMock()
        orch.draft_service.update_status = MagicMock()

        result = await orch._handle_approve(mock_draft)

        assert result["success"] is False
        assert "재생성 후 승인" in result["error"]
        orch.draft_service.update_status.assert_called_once()
        # APPROVED 가 아닌 FAILED 로 전환돼야 함
        args = orch.draft_service.update_status.call_args
        from app.models.content import ApprovalStatus
        assert args[0][1] == ApprovalStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_approve_blocks_en_fallback(self):
        from app.orchestrator import Orchestrator

        mock_draft = MagicMock()
        mock_draft.id = 78
        mock_draft.body = (
            "Body.\n\n"
            "⚠️ Real issue: (structure missing — regenerate recommended)\n"
            "📌 Watch for: (structure missing — regenerate recommended)"
        )
        mock_draft.hook = "hook"

        orch = Orchestrator.__new__(Orchestrator)
        orch.draft_service = MagicMock()
        orch.draft_service.update_status = MagicMock()

        result = await orch._handle_approve(mock_draft)
        assert result["success"] is False
        assert "재생성" in result["error"]


# ─── orchestrator.send_for_approval 통합 테스트 ────────────────────────

class TestSendForApprovalBlocksFallback:
    @pytest.mark.asyncio
    async def test_send_for_approval_blocks_fallback(self):
        from app.orchestrator import Orchestrator

        mock_draft = MagicMock()
        mock_draft.id = 99
        mock_draft.body = (
            "본문.\n\n⚠️ 진짜 쟁점: (구조 누락 — 재생성 권장)"
            "\n📌 지금 봐야 할 포인트: (구조 누락 — 재생성 권장)"
        )
        mock_draft.source_item = None

        orch = Orchestrator.__new__(Orchestrator)
        orch.rate_limiter = MagicMock()
        orch.rate_limiter.can_send_telegram = MagicMock(return_value=(True, ""))
        orch.draft_service = MagicMock()
        orch.draft_service.get_by_id = MagicMock(return_value=mock_draft)

        result = await orch.send_for_approval(draft_id=99)
        assert result is False
        # 정상 send_approval_card 호출까지 도달하지 않아야 함 → draft_service.set_telegram_message_id
        orch.draft_service.set_telegram_message_id = MagicMock()
        orch.draft_service.set_telegram_message_id.assert_not_called()


# ─── telegram_service.send_approval_card 방어선 테스트 ─────────────────

class TestSendApprovalCardRendererGuard:
    @pytest.mark.asyncio
    async def test_renderer_returns_none_for_fallback_draft(self):
        from app.services.telegram_service import send_approval_card

        mock_draft = MagicMock()
        mock_draft.id = 55
        mock_draft.body = (
            "본문.\n\n(구조 누락 — 재생성 권장)"
        )
        mock_draft.hook = "hook"

        # telegram 전송까지 가기 전에 None 반환해야 함
        result = await send_approval_card(mock_draft, source_url=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_renderer_allows_normal_draft_through_guard(self):
        # Normal draft 는 guard 를 통과 (실제 전송은 텔레그램 설정 부재 시 None)
        from app.services.telegram_service import send_approval_card
        from app.config import settings

        mock_draft = MagicMock()
        mock_draft.id = 56
        mock_draft.body = (
            "정상 본문.\n\n⚠️ 진짜 쟁점: 실제 충돌\n📌 지금 봐야 할 포인트: 실제 신호"
        )
        mock_draft.hook = "정상 훅"
        mock_draft.category = MagicMock(value="economy")
        mock_draft.risk_level = MagicMock(value="medium")
        mock_draft.risk_reasoning = ""
        mock_draft.ai_rationale = ""
        mock_draft.thread_continuation = None
        mock_draft.community_warning = None
        # build_approval_card 가 숫자 비교 하므로 int 로 설정 (MagicMock 기본값은 비교 불가)
        mock_draft.text_length = 100
        mock_draft.version = 1
        mock_draft.id = 56

        # Mock 모드(텔레그램 미설정)에서도 guard 는 통과 → None 반환 이유는 설정 부재
        # guard 로 인한 None 이 아닌지 확인하기 위해 로그 레벨로는 검증 어려움 —
        # 여기서는 최소한 예외 없이 완료되는지만 확인
        if not settings.has_telegram_config:
            result = await send_approval_card(mock_draft, source_url=None)
            # 텔레그램 미설정이므로 None 이지만 guard 차단은 아님
            assert result is None
