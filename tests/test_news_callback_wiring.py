"""뉴스 daytime alert 의 ✍️ 초안 생성 → _handle_news_callback 흐름 4 가지
회귀 가드 (실제 텔레그램 호출 없이 source 정적 검증).

배경: daytime alert 알림에서 초안 생성 시 (1) Grok 편집 버튼 누락,
(2) source_type='manual' 잘못 박힘, (3) ai_rationale [flags:...] leak,
(4) 옛 내부 분석 라벨 (⚠️ 진짜 쟁점 / 📌 지금 봐야 할 포인트) 본문 잔존
4 버그를 lane-isolated 패치로 차단.

샌드박스에 cryptography C 확장 미존재 — telegram_bot 모듈 import 회피.
파일 단위 source 읽기로 정적 검증.
"""
from __future__ import annotations

import re
from pathlib import Path

_TG_PATH = Path(__file__).parent.parent / "app" / "telegram_bot.py"


def _file_src() -> str:
    return _TG_PATH.read_text(encoding="utf-8")


def _slice_function(src: str, name: str) -> str:
    """`async def name(` 부터 다음 top-level def 또는 class 까지 추출."""
    m = re.search(
        rf"(?ms)^async def {re.escape(name)}\(.*?(?=^async def |^def |^class |\Z)",
        src,
    )
    return m.group(0) if m else ""


class TestNewsCallbackWiring:
    def setup_method(self):
        self.fn = _slice_function(_file_src(), "_handle_news_callback")
        assert self.fn, "_handle_news_callback function source not found"

    def test_uses_news_link_source_type(self):
        assert 'source_type="news_link"' in self.fn, (
            "news_callback 은 SourceItemCreate(source_type='news_link') 여야 "
            "News Article Fact Lock + Current Article Event Lock 적용됨"
        )
        # SourceItemCreate(...) 블록에 source_type="manual" 잔존 X
        # (score_draft 호출의 별도 source_type='manual' 파라미터는 무관 —
        # 품질 점수 lane 매핑일 뿐)
        m = re.search(
            r"SourceItemCreate\([^)]*?\)", self.fn, flags=re.DOTALL,
        )
        assert m is not None, "SourceItemCreate 호출 못 찾음"
        assert 'source_type="manual"' not in m.group(0), (
            "SourceItemCreate 안에 옛 source_type='manual' 잔존"
        )

    def test_grok_edit_button_added(self):
        assert "copy_grok:" in self.fn, (
            "Grok 편집 버튼 (copy_grok:{draft_id}) 콜백 누락"
        )
        assert "🤖 Grok 편집" in self.fn

    def test_copy_body_button_added(self):
        assert "copy_body:" in self.fn
        assert "📋 본문 복사" in self.fn

    def test_regen_button_preserved(self):
        assert "news_regen:" in self.fn
        assert "🔄 재생성" in self.fn

    def test_strip_internal_labels_present(self):
        # 옛 내부 분석 라벨 (⚠️ 진짜 쟁점 / 📌 지금 봐야 할 포인트 등) strip
        # 패턴 안에 핵심 키워드가 포함되었는지 substring 검사 (regex 안에서
        # \s* 가 사이에 들어가도 키워드 토큰 자체는 그대로 잔존).
        for kw in (
            "진짜",
            "지금",
            "세게",
            "반드시",
            "살릴",
        ):
            assert kw in self.fn, f"strip 패턴 키워드 '{kw}' 누락"

    def test_ai_rationale_strips_flags(self):
        # ai_rationale 의 [flags: speculation,summary_only,ai_smell,...] 노출 차단
        # re.sub 호출 + 'flags' 패턴 (phrasing 변형 허용)
        assert re.search(r"re\.sub\([^)]*flags", self.fn) is not None, (
            "ai_rationale [flags: ...] suffix strip 누락"
        )


class TestNewsCallbackRegressionSafety:
    """다른 흐름 (정규 분석 카드 / yt_callback) 무손."""

    def test_send_analysis_card_passes_source_type(self):
        src = _slice_function(_file_src(), "_run_analysis_and_show_card")
        assert src, "_run_analysis_and_show_card not found"
        # 정규 카드는 source_type 매개변수 그대로 사용
        assert "source_type" in src

    def test_yt_callback_unchanged(self):
        src = _slice_function(_file_src(), "_handle_yt_callback")
        assert src, "_handle_yt_callback not found"
        assert "yt_draft" in src
        assert "yt_skip" in src
