"""YouTube pipeline 테스트.

검증 대상 (claude/handoff-quality-guard-QTOig 스코프):
1. extract_video_id 기본 동작
2. _recover_truncated_json partial recovery
3. YoutubeAnalysis 가 v4 확장 필드 (atomic_claims / counter_arguments /
   conclusion_claim / segments / examples / preservation_targets) 없이도
   생성 가능 (backward-compatible)
4. to_pipeline_input() body 가 95% 보존형 헤더 문구를 포함
5. to_pipeline_input() body 가 옛 storytelling_header 문구 / 280자 /
   thread_continuation 문구를 포함하지 않음
"""
from __future__ import annotations

from app.sources.youtube_pipeline import (
    YoutubeAnalysis,
    _recover_truncated_json,
    extract_video_id,
    is_youtube_url,
    normalize_url,
)


# ─── 1) URL 파싱 ────────────────────────────────────────────────────
class TestExtractVideoId:
    def test_watch_url(self):
        assert extract_video_id(
            "https://www.youtube.com/watch?v=abc123XYZ_-"
        ) == "abc123XYZ_-"

    def test_short_url(self):
        assert extract_video_id("https://youtu.be/abc123XYZ") == "abc123XYZ"

    def test_shorts_url(self):
        assert extract_video_id(
            "https://www.youtube.com/shorts/abc123XYZ"
        ) == "abc123XYZ"

    def test_invalid_url(self):
        assert extract_video_id("https://example.com/whatever") is None

    def test_empty(self):
        assert extract_video_id("") is None
        assert extract_video_id(None) is None  # type: ignore[arg-type]

    def test_is_youtube_url(self):
        assert is_youtube_url("https://youtu.be/abc")
        assert not is_youtube_url("https://example.com")

    def test_normalize_url(self):
        assert normalize_url(
            "https://youtu.be/abc"
        ) == "https://www.youtube.com/watch?v=abc"


# ─── 2) JSON partial recovery ──────────────────────────────────────
class TestRecoverTruncatedJson:
    def test_complete_json(self):
        data = _recover_truncated_json('{"a": 1, "b": "x"}')
        assert data == {"a": 1, "b": "x"}

    def test_truncated_string(self):
        # 닫히지 않은 문자열 → auto_close 가 닫고 파싱
        text = '{"a": 1, "b": "unclosed value'
        data = _recover_truncated_json(text)
        assert isinstance(data, dict)
        assert data.get("a") == 1

    def test_truncated_array_partial_objects(self):
        # claims 배열 중 일부만 잘려있어도 살린다
        text = (
            '{"speaker": "X", "channel": "Y", "claims": ['
            '{"timestamp": "00:01", "claim": "A"}, '
            '{"timestamp": "00:02", "claim": "B"}, '
            '{"timestamp": "00:03", "claim": "C'
        )
        data = _recover_truncated_json(text)
        assert isinstance(data, dict)
        # speaker / channel scalar 또는 claims 배열 둘 중 하나는 살아야 함
        assert data.get("speaker") == "X" or "claims" in data

    def test_empty_returns_none(self):
        assert _recover_truncated_json("") is None
        assert _recover_truncated_json("not json at all <>") is None


# ─── 3) YoutubeAnalysis backward-compatible 생성 ────────────────────
class TestYoutubeAnalysisBackwardCompat:
    def _minimal(self) -> YoutubeAnalysis:
        return YoutubeAnalysis(
            video_id="vid_abc",
            url="https://www.youtube.com/watch?v=vid_abc",
            channel="채널 A",
            speaker="발언자 A",
            video_summary="핵심 메시지 한 줄",
            main_argument="핵심 메시지 한 줄",
            full_analysis="[영상 원문 추출]\n발언자: 발언자 A\n...",
            downstream_summary="요약 텍스트",
        )

    def test_creates_without_extension_fields(self):
        # 확장 필드 (atomic_claims 등) 없이도 생성 가능해야 함
        ana = self._minimal()
        assert ana.atomic_claims == []
        assert ana.counter_arguments == []
        assert ana.examples == []
        assert ana.segments == []
        assert ana.preservation_targets == []
        assert ana.conclusion_claim == ""

    def test_creates_with_extension_fields(self):
        ana = YoutubeAnalysis(
            video_id="v",
            url="u",
            channel="c",
            speaker="s",
            video_summary="vs",
            main_argument="ma",
            full_analysis="fa",
            downstream_summary="ds",
            atomic_claims=[{"timestamp": "00:11", "claim": "A"}],
            counter_arguments=[{"counter": "B"}],
            examples=[{"example": "C"}],
            conclusion_claim="결론 명제 D",
            preservation_targets=["E"],
        )
        assert ana.atomic_claims[0]["claim"] == "A"
        assert ana.conclusion_claim == "결론 명제 D"


# ─── 4 + 5) to_pipeline_input() 헤더 검증 ────────────────────────────
class TestToPipelineInputHeader:
    def _minimal(self) -> YoutubeAnalysis:
        return YoutubeAnalysis(
            video_id="vid_abc",
            url="https://www.youtube.com/watch?v=vid_abc",
            channel="채널 A",
            speaker="발언자 A",
            video_summary="요약",
            main_argument="핵심 주장",
            full_analysis="[영상 원문 추출]\n...",
            downstream_summary="요약",
        )

    def test_body_contains_preservation_phrases(self):
        body = self._minimal().to_pipeline_input()["body"]
        for phrase in (
            "95% 보존",
            "atomic claim",
            "발명 0건",
            "결론 명제 동일",
            "스레드 분할 금지",
        ):
            assert phrase in body, f"body 에 '{phrase}' 가 포함되어야 함"

    def test_body_does_not_contain_old_phrases(self):
        body = self._minimal().to_pipeline_input()["body"]
        for forbidden in (
            "280자",
            "thread_continuation",
            "배경:",
            "긴장:",
            "반전:",
            "예측:",
        ):
            assert forbidden not in body, (
                f"body 에 '{forbidden}' 가 포함되면 안 됨"
            )

    def test_extended_blocks_when_present(self):
        ana = YoutubeAnalysis(
            video_id="v",
            url="u",
            channel="c",
            speaker="s",
            video_summary="vs",
            main_argument="ma",
            full_analysis="fa",
            downstream_summary="ds",
            atomic_claims=[
                {"timestamp": "00:11", "claim": "atomic A"},
                {"timestamp": "00:22", "claim": "atomic B"},
            ],
            counter_arguments=[{"counter": "반론 X"}],
            examples=[{"example": "사례 Y"}],
            conclusion_claim="결론 명제 Z",
            preservation_targets=["반드시 살릴 항목 1"],
        )
        body = ana.to_pipeline_input()["body"]
        assert "atomic A" in body
        assert "반론 X" in body
        assert "사례 Y" in body
        assert "결론 명제 Z" in body
        assert "반드시 살릴 항목 1" in body

    def test_extended_blocks_skipped_when_empty(self):
        # 확장 필드가 비어있으면 헤더만 추가되고 [Atomic Claims] 같은
        # 블록은 출력되지 않아야 함 (backward-compatible)
        body = self._minimal().to_pipeline_input()["body"]
        assert "[Atomic Claims]" not in body
        assert "[반론]" not in body
        assert "[사례]" not in body
        assert "[결론 명제 (영상)]" not in body

    def test_pipeline_input_keys(self):
        out = self._minimal().to_pipeline_input()
        for key in ("title", "body", "url", "source", "source_type"):
            assert key in out
        assert out["source_type"] == "youtube"
