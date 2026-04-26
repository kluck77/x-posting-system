"""
Resonance fallback telemetry — metadata flag 기반 차단 회귀 방지.

배경:
  기존 guard 는 본문 문자열("(구조 누락 — 재생성 권장)") 을 매칭한다.
  문구가 살짝 변형되면 우회되므로 Draft 에 resonance_fallback_used 플래그를
  추가해 metadata 경로로도 차단할 수 있게 했다.

원칙:
  1) ensure_resonance_structure 가 "injected" 를 반환하면 Draft.resonance_fallback_used 가 True 로 저장된다
  2) guard 는 metadata flag 만 True 여도(문자열 없더라도) 차단해야 한다
  3) 기존 문자열 매칭은 제거하지 않고 병행한다 (OR)
  4) 정상 draft(flag=False & 문자열 없음) 는 오탐되지 않는다
"""
from unittest.mock import MagicMock
import pytest

from app.services.draft_service import (
    is_resonance_fallback_draft,
    is_resonance_fallback_signal,
)


# ─── 메타데이터 signal 단위 테스트 ─────────────────────────────────────

class TestIsResonanceFallbackSignal:
    def test_metadata_flag_alone_blocks(self):
        """body 엔 placeholder 가 없어도 flag=True 면 차단."""
        draft = MagicMock()
        draft.resonance_fallback_used = True
        draft.body = "⚠️ 진짜 쟁점: 정상\n📌 지금 봐야 할 포인트: 정상"
        assert is_resonance_fallback_signal(draft) is True

    def test_body_string_alone_blocks(self):
        """flag=False 여도(마이그레이션 이전 draft) 문자열이 있으면 차단."""
        draft = MagicMock()
        draft.resonance_fallback_used = False
        draft.body = "본문. (구조 누락 — 재생성 권장)"
        assert is_resonance_fallback_signal(draft) is True

    def test_both_signals_blocks(self):
        draft = MagicMock()
        draft.resonance_fallback_used = True
        draft.body = "본문. (structure missing — regenerate recommended)"
        assert is_resonance_fallback_signal(draft) is True

    def test_neither_signal_allows(self):
        """정상 draft 는 오탐되지 않는다."""
        draft = MagicMock()
        draft.resonance_fallback_used = False
        draft.body = (
            "한은 금리 인하. 환율 영향.\n\n"
            "⚠️ 진짜 쟁점: 환율 방어 vs 내수\n"
            "📌 지금 봐야 할 포인트: 원달러 1380"
        )
        assert is_resonance_fallback_signal(draft) is False

    def test_missing_flag_attribute_falls_back_to_string(self):
        """resonance_fallback_used 속성이 없는 기존 draft 는 문자열만 본다."""
        class LegacyDraft:
            body = "본문 정상\n\n⚠️ 진짜 쟁점: x\n📌 지금 봐야 할 포인트: y"
        assert is_resonance_fallback_signal(LegacyDraft()) is False

        class LegacyFallbackDraft:
            body = "본문 (구조 누락 — 재생성 권장)"
        assert is_resonance_fallback_signal(LegacyFallbackDraft()) is True

    def test_none_draft(self):
        assert is_resonance_fallback_signal(None) is False

    def test_empty_body_with_flag_still_blocks(self):
        """flag=True 면 body 가 비어 있어도 차단."""
        draft = MagicMock()
        draft.resonance_fallback_used = True
        draft.body = ""
        assert is_resonance_fallback_signal(draft) is True


# ─── create_draft persistence 테스트 ───────────────────────────────────

class TestCreateDraftPersistsFlag:
    def test_create_draft_default_flag_is_false(self, db_session):
        from app.services.draft_service import DraftService
        from app.models.content import (
            SourceItem, ContentCategory, RiskLevel,
        )
        source = SourceItem(
            title="테스트",
            source_text="테스트 본문입니다.",
            source_type="manual",
            language="ko",
        )
        db_session.add(source)
        db_session.commit()

        svc = DraftService(db_session)
        draft = svc.create_draft(
            source_item=source,
            hook="테스트 훅",
            body="본문 정상\n\n⚠️ 진짜 쟁점: x\n📌 지금 봐야 할 포인트: y",
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
        )
        assert draft.resonance_fallback_used is False

    def test_create_draft_flag_true_is_persisted(self, db_session):
        from app.services.draft_service import DraftService
        from app.models.content import (
            SourceItem, ContentCategory, RiskLevel,
        )
        source = SourceItem(
            title="테스트 fallback",
            source_text="테스트 본문입니다.",
            source_type="manual",
            language="ko",
        )
        db_session.add(source)
        db_session.commit()

        svc = DraftService(db_session)
        draft = svc.create_draft(
            source_item=source,
            hook="훅",
            body="본문. (구조 누락 — 재생성 권장)",
            category=ContentCategory.ECONOMY,
            risk_level=RiskLevel.LOW,
            resonance_fallback_used=True,
        )
        assert draft.resonance_fallback_used is True

        # 재조회 시에도 유지
        reloaded = svc.get_by_id(draft.id)
        assert reloaded.resonance_fallback_used is True


# ─── approve guard metadata-only 테스트 ────────────────────────────────

class TestApproveGuardUsesMetadata:
    @pytest.mark.asyncio
    async def test_approve_blocks_on_metadata_flag_even_if_body_clean(self):
        """
        body 는 정상이지만 flag=True (이론적 케이스 — placeholder 문구가 변형돼
        문자열 매칭으로는 못 잡는 상황) 도 차단해야 한다.
        """
        from app.orchestrator import Orchestrator

        mock_draft = MagicMock()
        mock_draft.id = 401
        mock_draft.body = (
            "본문 정상\n\n⚠️ 진짜 쟁점: 실제 쟁점\n📌 지금 봐야 할 포인트: 실제 신호"
        )
        mock_draft.resonance_fallback_used = True  # 메타만 True
        mock_draft.hook = "훅"

        orch = Orchestrator.__new__(Orchestrator)
        orch.draft_service = MagicMock()
        orch.draft_service.update_status = MagicMock()

        result = await orch._handle_approve(mock_draft)
        assert result["success"] is False
        assert "재생성" in result["error"]
        orch.draft_service.update_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_allows_when_neither_signal(self):
        """flag=False & body 깨끗하면 guard 를 통과해야 한다."""
        from app.orchestrator import Orchestrator
        from app.services.draft_service import is_resonance_fallback_signal

        mock_draft = MagicMock()
        mock_draft.id = 402
        mock_draft.body = (
            "정상 본문\n\n⚠️ 진짜 쟁점: 쟁점\n📌 지금 봐야 할 포인트: 포인트"
        )
        mock_draft.resonance_fallback_used = False

        # 이 테스트는 signal helper 만 검증 (is_broken_draft 등 이후 단계는 skip)
        assert is_resonance_fallback_signal(mock_draft) is False


# ─── send guard metadata-only 테스트 ───────────────────────────────────

class TestSendGuardUsesMetadata:
    @pytest.mark.asyncio
    async def test_send_for_approval_blocks_on_metadata_flag(self):
        from app.orchestrator import Orchestrator

        mock_draft = MagicMock()
        mock_draft.id = 501
        # body 는 깨끗하지만 metadata 가 True
        mock_draft.body = (
            "본문\n\n⚠️ 진짜 쟁점: x\n📌 지금 봐야 할 포인트: y"
        )
        mock_draft.resonance_fallback_used = True
        mock_draft.source_item = None

        orch = Orchestrator.__new__(Orchestrator)
        orch.rate_limiter = MagicMock()
        orch.rate_limiter.can_send_telegram = MagicMock(return_value=(True, ""))
        orch.draft_service = MagicMock()
        orch.draft_service.get_by_id = MagicMock(return_value=mock_draft)
        orch.draft_service.set_telegram_message_id = MagicMock()

        result = await orch.send_for_approval(draft_id=501)
        assert result is False
        orch.draft_service.set_telegram_message_id.assert_not_called()


# ─── telegram renderer guard metadata-only 테스트 ──────────────────────

class TestRendererGuardUsesMetadata:
    @pytest.mark.asyncio
    async def test_renderer_blocks_on_metadata_flag(self):
        from app.services.telegram_service import send_approval_card

        mock_draft = MagicMock()
        mock_draft.id = 601
        mock_draft.body = (
            "본문 정상\n\n⚠️ 진짜 쟁점: x\n📌 지금 봐야 할 포인트: y"
        )
        mock_draft.resonance_fallback_used = True  # 메타만 True
        mock_draft.hook = "훅"

        result = await send_approval_card(mock_draft, source_url=None)
        assert result is None


# ─── 문자열 guard 병행 확인 (기존 guard 제거 금지 원칙) ───────────────

class TestStringGuardStillWorks:
    def test_string_matching_helper_unchanged(self):
        """기존 is_resonance_fallback_draft(body) 는 그대로 동작해야 한다."""
        assert is_resonance_fallback_draft(
            "본문. (구조 누락 — 재생성 권장)"
        ) is True
        assert is_resonance_fallback_draft(
            "본문. (structure missing — regenerate recommended)"
        ) is True
        assert is_resonance_fallback_draft("정상 본문 ⚠️ 📌") is False
        assert is_resonance_fallback_draft(None) is False
