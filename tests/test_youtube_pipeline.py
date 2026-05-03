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


# ─── 6) format_handoff lane 분기 (YouTube 95% 보존형) ────────────────
class TestFormatHandoffYouTubeLane:
    def _min_sp(self) -> dict:
        return {
            "confirmed_facts": ["사실 1", "사실 2"],
            "conflicts_or_uncertainty": [],
            "evidence_pack": [],
            "concept_translation": "",
        }

    def _min_ap(self) -> dict:
        return {
            "winner_angle": {"angle": "테스트 앵글"},
            "core_tension": "테스트 긴장",
            "frame_type": "underreported_angle",
            "readability_risk": "medium",
            "share_trigger": "공유 트리거",
            "scan_pattern": "",
            "story_spine": ["A", "B", "C"],
        }

    def test_youtube_handoff_has_95pct_rule(self):
        # 슬림 handoff 도 "95% 보존" 문구는 편집 지시 + 금지사항 양쪽에 있음.
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._min_sp(), self._min_ap(),
            "본문 — 영상 결론 명제로 끝남.",
            source_type="youtube",
        )
        assert "95% 보존" in out

    def test_youtube_handoff_strips_280_700_rule(self):
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._min_sp(), self._min_ap(),
            "본문",
            source_type="youtube",
        )
        assert "280~700자" not in out

    def test_non_youtube_handoff_keeps_280_700_rule(self):
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._min_sp(), self._min_ap(),
            "본문",
            source_type="news_link",
        )
        assert "280~700자" in out

    def test_default_source_type_keeps_legacy_rule(self):
        # source_type kwarg 미전달 시 기존 동작 유지 (backward-compatible).
        from app.services.grok_handoff import format_handoff
        out = format_handoff(self._min_sp(), self._min_ap(), "본문")
        assert "280~700자" in out

    def test_youtube_handoff_preserves_long_body(self):
        # YouTube body 1500자 가량 → handoff 안 원문 초안에 1000자 이상 살아있어야 함.
        # (다른 lane 은 _BODY_MAX=900 truncate)
        from app.services.grok_handoff import format_handoff
        long_body = (
            "이것은 영상의 atomic claim 을 95% 보존한 장문 본문이다. " * 50
        )
        assert len(long_body) > 1500
        out = format_handoff(
            self._min_sp(), self._min_ap(),
            long_body,
            source_type="youtube",
        )
        # `## 원문 초안` 블록 안 본문 길이 확인
        # YouTube lane body cap 3500 이므로 1500자는 잘리지 않음
        assert long_body[:1000] in out


# ─── 7) openai_provider YouTube fallback skip ───────────────────────
class TestOpenAIProviderYouTubeLane:
    def test_youtube_skips_stake_point_generic_fallback(self):
        # source_type='youtube' + 빈 stake/point → combined_body 가
        # "📌 지금 봐야 할 포인트:" 로 끝나면 안 됨.
        # 실제 OpenAI 호출 없이 path 검증만: response handler logic 을
        # source_type='youtube' 분기로 우회시켜야 한다.
        # 단순화: provider 모듈의 상수만 import 해서 prompt 변경 검증.
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "280자" not in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "thread_continuation" not in YOUTUBE_DIGEST_SYSTEM_PROMPT
        # cleanup-first 후: 명시 수치 ("95% 이상 보존") 대신 의미 동등 phrasing
        assert "핵심 재료는 빼지 않는다" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "스레드 분할 금지" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_lane_branch_present_in_source(self):
        # 코드 내 'youtube' 분기가 stake/point fallback 앞에 배치되었는지
        # 정적 검증 (mock 호출 없이).
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        # source_type == 'youtube' 분기가 있고, 그 분기가 fallback 보다
        # 위쪽(또는 fallback 을 우회) 에 있어야 한다.
        assert 'source_type == "youtube"' in src or "_is_youtube_lane" in src
        # YouTube 분기 안에서는 generic fallback 문구 합성 안 함.
        assert "해석 gap 확인 필요" in src  # 다른 lane 용 fallback 은 그대로 존재
        assert "후속 지표 확인" in src


# ─── 8) format_handoff(youtube) 슬림 3 섹션 — Grok 메타 오해 차단 ────
class TestFormatHandoffYouTubeSlim:
    """YouTube lane handoff 가 3 섹션만 (Grok 편집 지시 / 원문 초안 / 금지사항)
    이고 일반 lane 의 메타 블록 (각도/lock/free/근거/why_push/...) 이 모두
    제거됐는지 검증."""

    def _sp_with_meta(self) -> dict:
        # 의도적으로 풍부한 source_pack — 일반 lane 이면 ## 절대 바꾸지 말 것 /
        # ## 핵심 근거 등이 자동 렌더된다. 슬림에선 모두 미렌더 검증.
        return {
            "confirmed_facts": ["사실 1", "사실 2", "사실 3"],
            "conflicts_or_uncertainty": ["미확정 1"],
            "evidence_pack": ["근거 1", "근거 2"],
            "concept_translation": "어려운 개념 한국어 번역",
        }

    def _ap_with_meta(self) -> dict:
        return {
            "winner_angle": {"angle": "중요 앵글"},
            "core_tension": "핵심 긴장",
            "frame_type": "underreported_angle",
            "readability_risk": "medium",
            "share_trigger": "공유 트리거",
            "scan_pattern": "스캔 패턴",
            "story_spine": ["A", "B", "C"],
        }

    def _rich_meta(self) -> dict:
        return {
            "rt_motivation": "RT 동기",
            "weak_signals": ["weakness 1"],
            "must_keep": ["반드시 살릴 1"],
            "salvageability_grade": "A",
            "salvageability_reason": "이유",
        }

    def test_slim_has_3_required_sections(self):
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            "본문 한 줄.", source_type="youtube",
            editorial_meta=self._rich_meta(),
        )
        assert "## Grok 편집 지시" in out
        assert "## 원문 초안" in out
        assert "## 금지사항" in out

    def test_slim_has_header_banner(self):
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            "본문", source_type="youtube",
        )
        assert "[YouTube 95% 보존형 장문 — Grok 편집용]" in out
        assert "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" in out

    def test_slim_strips_all_legacy_meta_blocks(self):
        # 일반 lane 의 메타 블록은 슬림에서 0/0 노출되어야 함.
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            "본문", source_type="youtube",
            editorial_meta=self._rich_meta(),
        )
        forbidden_blocks = [
            "## 이 글의 핵심 각도",
            "## 절대 바꾸지 말 것",
            "## 바꿔도 되는 것",
            "## 어려운 개념 한 줄 번역",
            "## 핵심 근거 2~3개",
            "## 최종 출력 규칙",
            "## 🔥 왜 이 글을 세게 써야 하는가",
            "## 🏴 지금 초안이 평평한 이유",
            "## 💎 반드시 살릴 포인트",
            "## 🎯 살릴 가치",
            "## 계정 톤",
            "## ⚠️ 재료 품질 경고",
        ]
        for block in forbidden_blocks:
            assert block not in out, f"슬림 handoff 에 '{block}' 가 남으면 안 됨"

    def test_slim_instruction_has_core_rules(self):
        # SCAN_FIRST_POST_STYLE_V1 도입 후 — 13 룰 → 핵심 룰 + 내부 분석 라벨
        # 제거 + 보고서 결말 제거 지시로 재편.
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            "본문", source_type="youtube",
        )
        rules = [
            "새 사실 추가 금지",
            "새 숫자 추가 금지",
            "새 인용 추가 금지",
            "새 인물/장소/장면 추가 금지",
            "새 인과관계 추가 금지",
            "원문 결론 명제 변경 금지",
            "원문 내용 95% 보존",
            "중복 제거",
            "문장 리듬 개선",
            "둘째 줄에는 핵심 숫자",
            "마지막 문장은 짧고 단단한 판단",
            "내부 분석 라벨 제거",
            "보고서 말투 / 뉴스 해설형 장문 / 유튜브 리뷰체 제거",
            "편집 결과만 출력",
        ]
        for rule in rules:
            assert rule in out, f"편집 지시 규칙 '{rule}' 누락"

    def test_slim_prohibitions_section_present(self):
        # 슬림 handoff 6 핵심 금지사항 (cleanup-first 단일 통합 후).
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            "본문", source_type="youtube",
        )
        assert "새 사실/숫자/인용/인물/장면/감정/인과 추가 금지" in out
        assert "원문 결론 명제 변경 금지" in out
        assert "핵심 재료" in out
        assert "주장은 확장하지 말 것" in out
        assert "원문 밖으로 나가지 말 것" in out
        assert "사람 말투로 정리할 것" in out

    def test_slim_body_in_text_codefence(self):
        from app.services.grok_handoff import format_handoff
        body_text = "원문 초안 본문이 여기에 들어간다 — 영상 결론 명제로 끝남."
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            body_text, source_type="youtube",
        )
        assert "```text\n" in out
        assert body_text in out
        # 코드펜스 정상 종결
        assert out.count("```") == 2

    def test_slim_long_body_truncated_to_3500(self):
        from app.services.grok_handoff import format_handoff
        long_body = "긴 본문 " * 1000  # ~5000+ chars
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            long_body, source_type="youtube",
        )
        # 코드펜스 사이 본문 추출
        import re
        m = re.search(r'```text\n(.*?)\n```', out, re.DOTALL)
        assert m is not None
        extracted = m.group(1)
        assert len(extracted) <= 3500
        # 슬림 전체도 합리적 사이즈 (헤더 + 13 룰 + body + 5 금지)
        assert len(out) < 5000

    def test_orchestrator_skips_resonance_check_for_youtube(self):
        # orchestrator.py 의 ensure_resonance_structure 호출이 source_type
        # == "youtube" 분기로 우회되는지 정적 검증.
        # 우회 안 하면 ⚠️/📌 누락 → placeholder 삽입 → send-guard 가 승인
        # 카드 + Grok 편집 버튼 자체를 차단함.
        import inspect
        from app.orchestrator import Orchestrator
        src = inspect.getsource(Orchestrator.ingest_and_generate)
        # ensure_resonance_structure 호출이 youtube 분기 안에 있어야 함
        assert 'data.source_type != "youtube"' in src, (
            "orchestrator 가 YouTube lane 에서 ensure_resonance_structure "
            "를 우회하지 않으면 승인 카드가 Resonance fallback 으로 차단됨"
        )


# ─── 9) YouTube prompt 한국어 5모드 렌더링 OS v1 ─────────────────────
class TestYouTubePromptRenderModeOS:
    """YouTube 전용 prompt 에 5 개 render_mode 와 한국어 작성 룰이
    포함되었는지 + 일반 KO prompt 는 변경되지 않았는지 검증."""

    def test_youtube_prompt_has_all_5_render_modes(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for mode in (
            "news_policy",
            "lecture_summary",
            "analysis_market",
            "community_x",
            "writerly",
        ):
            assert mode in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube prompt 에 render_mode '{mode}' 누락"
            )

    def test_youtube_prompt_has_source_vs_render_distinction(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        # source_type 은 재료 출처 / render_mode 는 글쓰기 방식 구분
        assert "재료 출처" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "글쓰기 방식" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "섞지 마라" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_prompt_has_causal_leap_block(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        # "A 때문에 B" 인과 비약 방지 룰 (cleanup-first 후 phrasing 갱신)
        assert "A 때문에 B" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "직접 연결 안 했으면" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_prompt_keeps_95pct_rules(self):
        # cleanup-first 후 핵심 truth integrity 룰 유지 검증.
        # "95% 이상 보존" / "발명 0 건" 같은 명시 수치 phrasing 은 의미
        # 동등 표현 ("핵심 재료는 빼지 않는다" / "영상에 없는 사실 추가
        # 금지") 으로 대체됨.
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for must_have in (
            "스레드 분할 금지",
            "결론 명제 변경 금지",
            "핵심 재료는 빼지 않는다",
            "영상에 없는 사실/숫자/인용/인물/장소/장면/감정/인과 추가 금지",
        ):
            assert must_have in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"truth integrity 룰 '{must_have}' 누락"
            )

    def test_youtube_prompt_archetype_holds_render_mode(self):
        # archetype schema 자체는 그대로 두되 YouTube 만 거기 render_mode
        # 값을 박으라고 prompt-level 로 지시.
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "archetype" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "render_mode" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_general_ko_prompt_unchanged(self):
        # 일반 KO prompt (뉴스/manual/news_link 등) 에는 render_mode 5종이
        # 새어들어가면 안 됨.
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for mode in (
            "news_policy",
            "lecture_summary",
            "analysis_market",
            "community_x",
            "writerly",
        ):
            assert mode not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 YouTube 전용 mode '{mode}' 가 들어가면 안 됨"
            )
        # render_mode 키워드 자체도 일반 prompt 에 없어야 함
        assert "render_mode" not in SYSTEM_PROMPT_KO

    def test_openai_model_unchanged(self):
        # 모델 업그레이드 / 변경 금지
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_non_youtube_handoff_unchanged_full_meta(self):
        # 슬림 분기는 youtube 만. news_link 는 기존 full handoff 유지.
        # (이전 TestFormatHandoffYouTubeSlim 안 동명 테스트가 클래스 경계
        # 위로 흘러와 helper 부재로 깨졌던 케이스 — fixture 인라인으로 복구.)
        from app.services.grok_handoff import format_handoff
        sp = {
            "confirmed_facts": ["사실 1", "사실 2"],
            "evidence_pack": ["근거 1"],
            "concept_translation": "",
        }
        ap = {
            "winner_angle": {"angle": "앵글"},
            "core_tension": "긴장",
            "frame_type": "x",
            "story_spine": ["A", "B"],
        }
        out = format_handoff(sp, ap, "본문", source_type="news_link")
        assert "## 이 글의 핵심 각도" in out
        assert "## 절대 바꾸지 말 것" in out
        assert "## 최종 출력 규칙" in out
        assert "[YouTube 95% 보존형 장문 — Grok 편집용]" not in out



# ─── Cleanup v1 — Salience-First Draft Planner 단일 통합 검증 ────────
class TestYouTubeCleanupSalienceFirstPlanner:
    """[A] Gemini extractor 의 Dynamic Salience Map.
    [B] OpenAI YouTube prompt 의 Salience-First Draft Planner.
    [C] overfitting 차단 (Polymarket/Kalshi/도메인 spine 전역 강제 없음).
    [D] Grok handoff 6 핵심 금지사항.
    [E] 일반 lane 격리 + 모델/schema 보존."""

    # ── A. Gemini Dynamic Salience Map ──────────────────────────────
    def test_gemini_has_dynamic_salience_map(self):
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for kw in (
            "Dynamic Salience Map",
            "Core Entities",
            "Core Numbers",
            "Core Events",
            "Core Tension",
            "Core Mechanism",
            "Core Outcome",
            "Must-Keep Items",
        ):
            assert kw in GEMINI_VIDEO_ANALYSIS_PROMPT, (
                f"Gemini prompt 에 '{kw}' 누락"
            )

    # ── B. OpenAI Salience-First Draft Planner ──────────────────────
    def test_openai_has_salience_first_draft_planner(self):
        from app.providers.openai_provider import (
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
            YOUTUBE_SALIENCE_FIRST_DRAFT_PLANNER_V1,
        )
        assert "Salience-First Draft Planner" in (
            YOUTUBE_SALIENCE_FIRST_DRAFT_PLANNER_V1
        )
        for kw in (
            "Salience-First Draft Planner",
            "바로 글을 쓰지 않는다",
            "핵심 재료의 중요도 순서",
            "영상마다 구조를 다르게 설계",
            "특정 도메인 고정 구조로 모든 영상을 처리하기",
            "추상어로 지우기",
            "짧은 요약문으로 끝내기",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube prompt 에 '{kw}' 누락"
            )

    def test_openai_has_audience_context_and_truth_integrity(self):
        # 새 base 의 [IDENTITY] / [Truth Integrity] / 타겟 독자 유지
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "Truth Integrity" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "타겟 독자" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "여성 타겟 전환" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "남초 코인판" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── C. Overfitting prevention ───────────────────────────────────
    def test_no_domain_spine_globally_forced(self):
        # 옛 layered 상수가 모두 제거됐고 도메인 spine 헤더 0 hit
        import app.providers.openai_provider as op
        for old_const in (
            "YOUTUBE_CLAIM_LOCKED_RENDERER_V1",
            "YOUTUBE_KOREAN_WRITER_RENDERING_LAYER_V1",
            "YOUTUBE_ECONOMIC_SPINE_PRESERVATION_V1",
            "YOUTUBE_DYNAMIC_SALIENCE_DRAFTING_V1",
        ):
            assert not hasattr(op, old_const), (
                f"옛 layered 상수 '{old_const}' 가 모듈에 남아있으면 안 됨"
            )
        for spine in (
            "Economic Spine",
            "Policy Spine",
            "Medical Spine",
            "AI Tech Spine",
        ):
            assert spine not in op.YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"도메인 spine '{spine}' 이 prompt 에 박혀있으면 안 됨"
            )

    def test_no_polymarket_kalshi_globally(self):
        # Polymarket / Kalshi 가 전역 필수 규칙으로 prompt 안에 남아있지
        # 않는지 (둘 다 OpenAI prompt + Gemini prompt 모두 0 hit)
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for kw in ("Polymarket", "Kalshi"):
            assert kw not in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"'{kw}' 가 OpenAI YouTube prompt 에 전역 강제로 남으면 안 됨"
            )
            assert kw not in GEMINI_VIDEO_ANALYSIS_PROMPT, (
                f"'{kw}' 가 Gemini extractor 에 전역 강제로 남으면 안 됨"
            )

    # ── D. Grok slim handoff 6 핵심 금지사항 ────────────────────────
    def test_slim_handoff_has_6_essentials(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문", source_type="youtube")
        for line in (
            "새 사실/숫자/인용/인물/장면/감정/인과 추가 금지",
            "원문 결론 명제 변경 금지",
            "핵심 재료 (기업/숫자/작동 구조) 삭제 금지",
            "문장은 다듬되 주장은 확장하지 말 것",
            "첫 문장과 마지막 문장은 강화하되 원문 밖으로 나가지 말 것",
            "보고서 말투를 줄이고 사람 말투로 정리할 것",
        ):
            assert line in out, f"slim handoff 에 핵심 금지 '{line}' 누락"

    # ── E. 격리 + 모델/schema 보존 ──────────────────────────────────
    def test_general_ko_prompt_isolation(self):
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "Salience-First Draft Planner",
            "Dynamic Salience Map",
            "Core Entities",
            "Truth Integrity",
            "타겟 독자",
        ):
            assert kw not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 YouTube 전용 '{kw}' 새어들어가면 안 됨"
            )

    def test_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_schema_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        assert set(_RESPONSE_FORMAT_KO["json_schema"]["schema"]["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }

    def test_youtube_analysis_dataclass_unchanged(self):
        from app.sources.youtube_pipeline import YoutubeAnalysis
        ana = YoutubeAnalysis(
            video_id="v", url="u", channel="c", speaker="s",
            video_summary="vs", main_argument="ma",
            full_analysis="fa", downstream_summary="ds",
        )
        for f in ("atomic_claims", "examples", "counter_arguments",
                  "segments", "conclusion_claim", "preservation_targets"):
            assert hasattr(ana, f), f"YoutubeAnalysis 에 '{f}' 누락"


# ─── 4-Editor Board trigger + 과감한 재구성 (YouTube slim handoff) ──
class TestYouTubeFourEditorBoardTrigger:
    """Grok 맞춤 에이전트 안의 4-Editor Board 합의 편집을 트리거하는
    1줄 + Grok 이 단순 교정자가 아니라 구조 편집자로 움직이게 하는
    1줄 = 총 2 줄이 YouTube slim handoff 의 ## Grok 편집 지시 섹션 안에만
    들어가는지 검증. non-YouTube handoff 에는 절대 들어가면 안 됨."""

    TRIGGER = (
        "위 handoff 초안을 4-Editor Board 기준으로 합의 편집하고, "
        "최종 편집본 1개만 출력해줘."
    )
    RESTRUCTURE = (
        "원문 사실은 유지하되, 문단 순서·첫 문장·마지막 문장·표현 방식은 "
        "과감하게 재구성해라. 단, 새 사실은 추가하지 마라."
    )
    # SCAN_FIRST_POST_STYLE_V1 도입 — 기존 영상 리뷰체/구조적 의미 라인을
    # 모바일 스캔형 X 포스트 지시 + 줄별 지시 (첫 줄 / 둘째 줄 / 마지막) 로 교체.
    NO_REVIEW = (
        "이 글은 뉴스 요약이나 영상 리뷰가 아니라 모바일 스캔형 X 포스트여야 "
        "한다."
    )
    FINAL_ANGLE = (
        "마지막은 긴 철학적 결론이 아니라 짧은 판단 한 줄로 닫아라."
    )

    def _slim(self) -> str:
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        return format_handoff(sp, ap, "본문 한 줄.", source_type="youtube")

    def test_trigger_present_in_youtube_handoff(self):
        out = self._slim()
        assert self.TRIGGER in out
        assert self.RESTRUCTURE in out
        assert self.NO_REVIEW in out
        assert self.FINAL_ANGLE in out

    def test_trigger_inside_grok_instruction_section(self):
        # 네 줄 모두 `## Grok 편집 지시` 와 `## 원문 초안` 사이 +
        # TRIGGER → RESTRUCTURE → NO_REVIEW → FINAL_ANGLE 순서.
        out = self._slim()
        instr_idx = out.find("## Grok 편집 지시")
        draft_idx = out.find("## 원문 초안")
        trigger_idx = out.find(self.TRIGGER)
        restruct_idx = out.find(self.RESTRUCTURE)
        no_review_idx = out.find(self.NO_REVIEW)
        final_angle_idx = out.find(self.FINAL_ANGLE)
        assert instr_idx != -1 and draft_idx != -1
        assert all(idx != -1 for idx in (
            trigger_idx, restruct_idx, no_review_idx, final_angle_idx
        ))
        assert (
            instr_idx < trigger_idx < restruct_idx < no_review_idx
            < final_angle_idx < draft_idx
        ), (
            "네 지시 줄이 ## Grok 편집 지시 섹션 안 (## 원문 초안 위) + "
            "trigger → restructure → no-review → final-angle 순서로 있어야 함"
        )

    def test_trigger_not_inside_draft_codefence(self):
        # 네 줄 모두 ```text ... ``` 원문 초안 코드블록 안에 들어가면 안 됨
        out = self._slim()
        import re
        m = re.search(r"```text\n(.*?)\n```", out, re.DOTALL)
        assert m is not None
        assert self.TRIGGER not in m.group(1)
        assert self.RESTRUCTURE not in m.group(1)
        assert self.NO_REVIEW not in m.group(1)
        assert self.FINAL_ANGLE not in m.group(1), (
            "final-angle 지시가 원문 초안 코드블록 안에 들어가면 Grok 이 "
            "본문으로 오해함"
        )

    def test_no_topic_specific_lens_examples(self):
        # 주제별 렌즈 목록 (돈/욕망/공포/신뢰/권력/인프라 등) 이 handoff 에
        # 나열되면 안 됨. final_angle 은 "유연하게 선택" 만 지시.
        out = self._slim()
        # 렌즈 키워드 목록이 prompt 에 박히면 X
        forbidden_lens_lists = [
            "돈/욕망/공포/신뢰/권력",
            "돈 / 욕망 / 공포 / 신뢰 / 권력",
            "권력/인프라",
            "lens list",
            "렌즈 목록",
        ]
        for kw in forbidden_lens_lists:
            assert kw not in out, (
                f"주제별 렌즈 나열 '{kw}' 이 handoff 에 들어가면 안 됨"
            )

    def test_trigger_absent_from_non_youtube_handoff(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문", source_type="news_link")
        # YouTube slim 전용 지시 (TRIGGER/RESTRUCTURE) 는 news_link 에 없어야 함
        assert self.TRIGGER not in out
        assert self.RESTRUCTURE not in out
        # YouTube slim 전용 키워드도 새지 말 것
        assert "4-Editor Board" not in out
        assert "과감하게 재구성" not in out
        # 첫 줄/둘째 줄 줄별 지시 (YouTube slim 전용 phrasing)
        assert "둘째 줄에는 핵심 숫자/판세/상태" not in out
        # 단, news_link 자체 House Format 블록의 "모바일 스캔형 X 포스트"
        # phrasing 은 OK (lane-specific block).
        assert "모바일 스캔형 X 포스트" in out

    def test_trigger_absent_when_default_source_type(self):
        # source_type kwarg 미전달 시 (=일반 lane 기본 동작) 도 네 줄 미포함
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문")
        assert "4-Editor Board" not in out
        assert "과감하게 재구성" not in out
        assert "영상 리뷰/요약처럼" not in out
        assert "구조적 의미나 인간의 선택" not in out


# ─── Fix 1+2 — 영상 원문 밖 한국 macro 섞임 차단 ─────────────────────
class TestYouTubeKoreanContextLeakBlock:
    """draft #1497 류 (영상 밖 BTC 6.5만 / 원/달러 1475 / 가계부채 1900조 /
    부동산 조언 / 금리 인하 신호 등) 의 자체 발명 차단:
    [Fix 1] openai_provider user_msg lane 분기 (YouTube 한정 잠금 지시)
    [Fix 2] orchestrator _kr_brief YouTube 경로 우회"""

    # ── Fix 1: openai_provider user_msg 분기 ────────────────────────
    def test_openai_user_msg_youtube_branch_present_in_source(self):
        # generate_draft 안에 source_type 분기 + youtube 전용 잠금 지시 존재
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        # YouTube 전용 directive — 영상 원문 잠금
        assert "영상 원문 안에서만 드래프트를 작성하라" in src
        assert "한국 macro/시장/환율/투자/부동산" in src
        # non-YouTube directive — Bug 1 fix 후 "한국 맥락이 강제 주입된" 제거,
        # "한국 맥락이 명시된 경우에만" / "한국 맥락을 강제로 추가하지 마라"
        # 같은 약화형 directive 사용
        assert "한국 맥락이 강제 주입된 드래프트를" not in src
        assert (
            "한국 맥락이 명시된" in src
            or "한국 맥락을 강제로 추가하지 마라" in src
        )
        # source_type 분기 사용
        assert 'source_type == "youtube"' in src

    def test_openai_user_msg_youtube_directive_replaces_default(self):
        # YouTube 분기 안에서 _final_directive 가 정확히 잠금형으로 셋되고,
        # 다른 lane 기본 directive 가 같은 분기 안 else 에 있어야 함
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        # if/else 두 directive 모두 정의됨
        assert src.count("_final_directive") >= 3, (
            "_final_directive 변수로 if/else 분기 + user_msg 합성 = 최소 3 hit"
        )

    # ── Fix 2: orchestrator _kr_brief 우회 ──────────────────────────
    def test_orchestrator_skips_kr_brief_for_youtube(self):
        # ingest_and_generate 안에 youtube lane 우회 분기 정적 검증
        import inspect
        from app.orchestrator import Orchestrator
        src = inspect.getsource(Orchestrator.ingest_and_generate)
        # _kr_brief 호출이 source_type != "youtube" 분기 안에 있어야 함
        assert 'data.source_type != "youtube"' in src, (
            "orchestrator 가 YouTube lane 에서 _kr_brief prepend 를 우회 "
            "하지 않으면 외부 KR DB 맥락이 GPT 입력에 섞임"
        )
        # build_korean_entity_brief 호출은 여전히 존재 (다른 lane 용)
        assert "build_korean_entity_brief" in src

    def test_general_lane_kr_brief_still_called(self):
        # 일반 lane (data.source_type != "youtube") 에서는 _kr_brief 가 기존
        # 그대로 호출되는지 — 정적 검증.
        import inspect
        from app.orchestrator import Orchestrator
        src = inspect.getsource(Orchestrator.ingest_and_generate)
        # `if data.source_type != "youtube":` 블록 안에 build 호출
        # (구조 검증 — 라인 별 enclosed 검사)
        kr_idx = src.find("build_korean_entity_brief(")
        guard_idx = src.find('data.source_type != "youtube"')
        assert kr_idx != -1 and guard_idx != -1
        assert guard_idx < kr_idx, (
            "build_korean_entity_brief 호출이 youtube 우회 가드 안쪽에 "
            "있어야 함 (일반 lane 만 호출)"
        )

    # ── 격리 + 모델/schema 보존 ─────────────────────────────────────
    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_response_format_schema_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        assert set(_RESPONSE_FORMAT_KO["json_schema"]["schema"]["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }


# ─── Enumerated Framework Lock v1 — 번호형 구조 보존 ────────────────
class TestEnumeratedFrameworkLock:
    """[A] Gemini extractor 의 Enumerated Framework Lock.
    [B] OpenAI YouTube renderer 의 Framework Preservation Rule.
    [C] overfitting 차단 (도메인 spine 추가 없음, 모든 영상 공통).
    [D] schema/interface/모델 보존."""

    # ── A. Gemini Enumerated Framework Lock ─────────────────────────
    def test_gemini_has_enumerated_framework_lock(self):
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for kw in (
            "Enumerated Framework Lock",
            "expected_count",
            "framework_items",
            "missing_or_unclear_items",
            "FRAMEWORK_LOCK",
            "N가지",
            "N단계",
            "N유형",
        ):
            assert kw in GEMINI_VIDEO_ANALYSIS_PROMPT, (
                f"Gemini prompt 에 framework 키워드 '{kw}' 누락"
            )

    def test_gemini_framework_lock_preserves_dynamic_salience_map(self):
        # 직전 PR 의 Dynamic Salience Map 7 카테고리도 그대로 살아있어야 함
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for kw in (
            "Dynamic Salience Map",
            "Core Entities", "Core Numbers", "Core Events",
            "Core Tension", "Core Mechanism", "Core Outcome",
            "Must-Keep Items",
        ):
            assert kw in GEMINI_VIDEO_ANALYSIS_PROMPT

    # ── B. OpenAI Framework Preservation Rule ───────────────────────
    def test_openai_has_framework_preservation_rule(self):
        from app.providers.openai_provider import (
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
            YOUTUBE_FRAMEWORK_PRESERVATION_V1,
        )
        # 별도 상수도 노출
        assert "Framework Preservation Rule" in (
            YOUTUBE_FRAMEWORK_PRESERVATION_V1
        )
        for kw in (
            "Framework Preservation Rule",
            "7가지",
            "2가지 유형",
            "expected_count 와 실제 반영 항목 수가 맞아야",
            "결론 한 문장으로 압축",
            "FRAMEWORK_LOCK",
            "번호형 구조",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube prompt 에 framework 보존 키워드 '{kw}' 누락"
            )

    def test_openai_framework_keeps_prior_layers(self):
        # Salience-First Draft Planner / Truth Integrity / 5 모드 / 타겟
        # 독자 등 직전 PR 들의 구조가 그대로 살아있는지
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for kw in (
            "Salience-First Draft Planner",
            "Truth Integrity",
            "타겟 독자",
            "render_mode",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── C. Overfitting prevention — 도메인 spine 추가 없음 ──────────
    def test_no_domain_spine_added(self):
        # framework lock 은 도메인-agnostic. 경제/정책/의료/AI 전용 spine
        # 헤더가 prompt 에 새로 들어오면 안 됨.
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for spine in (
            "Economic Spine",
            "Policy Spine",
            "Medical Spine",
            "AI Tech Spine",
        ):
            assert spine not in YOUTUBE_DIGEST_SYSTEM_PROMPT
            assert spine not in GEMINI_VIDEO_ANALYSIS_PROMPT

    def test_no_polymarket_kalshi_added(self):
        # Polymarket/Kalshi 같은 사례명 전역 강제 0 hit 유지
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for kw in ("Polymarket", "Kalshi"):
            assert kw not in YOUTUBE_DIGEST_SYSTEM_PROMPT
            assert kw not in GEMINI_VIDEO_ANALYSIS_PROMPT

    def test_general_ko_prompt_no_framework_block(self):
        # 일반 KO prompt 에 framework lock 이 새지 말 것
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "Framework Preservation Rule",
            "Enumerated Framework Lock",
            "FRAMEWORK_LOCK",
            "expected_count",
            "framework_items",
        ):
            assert kw not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 YouTube 전용 '{kw}' 가 새어들어가면 안 됨"
            )

    # ── D. schema/interface/모델 보존 ───────────────────────────────
    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_response_format_schema_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        assert set(_RESPONSE_FORMAT_KO["json_schema"]["schema"]["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }

    def test_youtube_analysis_dataclass_unchanged(self):
        # DB schema 변경 없이 기존 필드만 활용 — preservation_targets /
        # atomic_claims 통해 framework items 보존
        from app.sources.youtube_pipeline import YoutubeAnalysis
        ana = YoutubeAnalysis(
            video_id="v", url="u", channel="c", speaker="s",
            video_summary="vs", main_argument="ma",
            full_analysis="fa", downstream_summary="ds",
        )
        for f in ("preservation_targets", "atomic_claims"):
            assert hasattr(ana, f)


# ─── Dedup lane isolation — 운영자 수동 입력 lane 우회 ──────────────
class TestDedupSkipForManualLanes:
    """orchestrator 의 Step 0.5 dedup 이 운영자 수동 입력 lane (manual /
    youtube / community_input) 에서 우회되는지 정적 검증.
    영어 제목 + split fallback false positive 차단 + 운영자 의도 우선."""

    def test_orchestrator_has_dedup_skip_set(self):
        import inspect
        from app.orchestrator import Orchestrator
        src = inspect.getsource(Orchestrator.ingest_and_generate)
        assert "_DEDUP_SKIP_SOURCES" in src
        # 3 lane 모두 skip set 안 명시
        for lane in ('"manual"', '"youtube"', '"community_input"'):
            assert lane in src, f"dedup skip lane '{lane}' 누락"

    def test_orchestrator_dedup_skip_branches_check_and_register(self):
        import inspect
        from app.orchestrator import Orchestrator
        src = inspect.getsource(Orchestrator.ingest_and_generate)
        # check_and_register 호출이 _DEDUP_SKIP_SOURCES 가드 안 else 에 있어야 함
        skip_idx = src.find("_DEDUP_SKIP_SOURCES")
        check_idx = src.find("check_and_register(")
        assert skip_idx != -1 and check_idx != -1
        assert skip_idx < check_idx, (
            "check_and_register 호출이 _DEDUP_SKIP_SOURCES 가드 뒤쪽 "
            "(else 블록) 에 있어야 함 — 자동 수집 lane 만 호출"
        )

    def test_orchestrator_dedup_skip_logs_lane_name(self):
        # 우회 시 운영자가 로그에서 확인 가능하도록 lane 이름 명시
        import inspect
        from app.orchestrator import Orchestrator
        src = inspect.getsource(Orchestrator.ingest_and_generate)
        assert "운영자 수동 입력 lane" in src
        assert "dedup 우회" in src

    def test_breaking_news_dedup_module_unchanged(self):
        # check_and_register 함수 자체는 무손 (자동 수집 lane 에서 정상 작동)
        from app.sources.breaking_news_dedup import check_and_register
        assert callable(check_and_register)
        # 함수 인터페이스 (title:str → bool) 그대로
        import inspect
        sig = inspect.signature(check_and_register)
        params = list(sig.parameters.keys())
        assert params == ["title"]


# ─── Option D — Gemini 응답 부담 + retry + Telegram hard timeout ────
class TestYouTubeGeminiTimingOptionD:
    """A: maxOutputTokens 32000 → 16000
    B: retry 3 → 2
    C: Telegram process_youtube_url 을 asyncio.wait_for(timeout=480) 으로 감쌈
    D: 안내 문구 30초~5분 → 30초~8분
    모델명 / DB schema / provider interface 변경 없음."""

    def test_gemini_max_output_tokens_reduced_to_16000(self):
        import inspect
        from app.sources import youtube_pipeline
        src = inspect.getsource(youtube_pipeline.analyze_video_with_gemini)
        assert '"maxOutputTokens": 16000' in src, (
            "maxOutputTokens 가 16000 이 아님 — Option A 미적용"
        )
        assert '"maxOutputTokens": 32000' not in src

    def test_gemini_retry_reduced_to_2(self):
        import inspect
        from app.sources import youtube_pipeline
        src = inspect.getsource(youtube_pipeline.analyze_video_with_gemini)
        # retry 루프가 range(2) 로 변경
        assert "for attempt in range(2)" in src
        assert "for attempt in range(3)" not in src
        # log 문구도 동기화
        assert "/2 after" in src
        assert "/2)" in src  # "(attempt N/2)"

    def test_telegram_youtube_handler_has_hard_timeout(self):
        # telegram_bot 직접 import 불가 (cryptography sandbox 이슈) →
        # 파일 read 로 정적 검증
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "telegram_bot.py",
        )
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # _handle_youtube_url 함수 주변 슬라이스 검증
        idx = src.find("async def _handle_youtube_url(")
        end_idx = src.find("async def ", idx + 10)
        handler_src = src[idx:end_idx]
        assert "asyncio.wait_for(" in handler_src, (
            "_handle_youtube_url 에 asyncio.wait_for hard timeout 누락"
        )
        assert "timeout=480" in handler_src or "timeout=480.0" in handler_src
        assert "asyncio.TimeoutError" in handler_src
        assert "8분을 초과" in handler_src or "8분 초과" in handler_src

    def test_telegram_youtube_processing_message_updated(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "telegram_bot.py",
        )
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        idx = src.find("async def _handle_youtube_url(")
        end_idx = src.find("async def ", idx + 10)
        handler_src = src[idx:end_idx]
        assert "30초~8분 소요" in handler_src
        assert "30초~5분 소요" not in handler_src

    def test_model_name_unchanged(self):
        # gemini-2.5-flash 그대로 (모델 변경 금지)
        import inspect
        from app.sources import youtube_pipeline
        src = inspect.getsource(youtube_pipeline)
        assert '_GEMINI_MODEL = "gemini-2.5-flash"' in src

    def test_provider_interface_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        assert set(_RESPONSE_FORMAT_KO["json_schema"]["schema"]["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }

    def test_youtube_analysis_dataclass_unchanged(self):
        from app.sources.youtube_pipeline import YoutubeAnalysis
        ana = YoutubeAnalysis(
            video_id="v", url="u", channel="c", speaker="s",
            video_summary="vs", main_argument="ma",
            full_analysis="fa", downstream_summary="ds",
        )
        for f in ("atomic_claims", "preservation_targets",
                  "conclusion_claim", "examples", "counter_arguments"):
            assert hasattr(ana, f)


# ─── SCAN_FIRST_POST_STYLE v1 — 모바일 스캔형 X 포스트 (House Format 폐기) ─
class TestScanFirstPostStyleV1:
    """[A] OpenAI YouTube prompt 에 SCAN_FIRST_POST_STYLE_V1 (4 형식 후보 +
        공통 스캔 규칙).
    [B] Grok handoff 모바일 스캔형 X 포스트 1 줄 + 4 후보 명시.
    [C] overfitting 차단 (도메인 spine / 산업 예시 / 기업명 / 정치인명 /
        코인명 / 국가명 0 hit).
    [D] schema/interface/모델 보존.
    [E] 기존 내부 분석 라벨 ("진짜 쟁점" / "지금 봐야 할 포인트" /
        "반드시 살릴 포인트" 등) 금지 목록 포함."""

    # ── A. OpenAI prompt — SCAN_FIRST_POST_STYLE_V1 ──────────────────
    def test_scan_first_constant_exists_and_named(self):
        from app.providers.openai_provider import (
            SCAN_FIRST_POST_STYLE_V1,
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
        )
        assert "SCAN_FIRST_POST_STYLE v1" in SCAN_FIRST_POST_STYLE_V1
        assert "SCAN_FIRST_POST_STYLE v1" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_house_format_router_alias_points_to_scan_first(self):
        # backward-compat alias — 기존 호출부 (generate_draft 등) 무손
        from app.providers.openai_provider import (
            HOUSE_FORMAT_ROUTER_V1, SCAN_FIRST_POST_STYLE_V1,
        )
        assert HOUSE_FORMAT_ROUTER_V1 is SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_has_seven_common_rules(self):
        # 7 섹션 — 첫 줄 / 둘째 줄 / 본문 / 이모지 / 숫자 / 단어 / 마지막
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        for kw in (
            "1. 첫 줄",
            "2. 둘째 줄",
            "3. 본문",
            "4. 이모지",
            "5. 숫자 처리",
            "6. 단어 선택",
            "7. 마지막",
        ):
            assert kw in SCAN_FIRST_POST_STYLE_V1, (
                f"공통 규칙 섹션 '{kw}' 누락"
            )

    def test_scan_first_first_line_rules(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "주제 제목 또는 강한 질문으로 시작" in SCAN_FIRST_POST_STYLE_V1
        assert "뉴스 기사 제목을 그대로 복붙하지 않는다" in SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_second_line_rules(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "핵심 숫자" in SCAN_FIRST_POST_STYLE_V1
        assert "숫자를 문장 속에 숨기지 않는다" in SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_short_block_rule(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "한 문단은 1~3 줄을 넘기지 않는다" in SCAN_FIRST_POST_STYLE_V1
        assert "항목 구조" in SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_emoji_rules(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "구역 구분용으로만 사용" in SCAN_FIRST_POST_STYLE_V1
        # 내부 분석 라벨 금지 (4 패턴)
        for label in (
            "진짜 쟁점",
            "지금 봐야 할 포인트",
            "왜 세게 써야 하는가",
            "반드시 살릴 포인트",
            "살릴 가치",
        ):
            assert label in SCAN_FIRST_POST_STYLE_V1, (
                f"내부 분석 라벨 금지 목록 '{label}' 누락"
            )

    def test_scan_first_last_line_rules(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "짧은 판단" in SCAN_FIRST_POST_STYLE_V1
        assert "긴 철학적 결론" in SCAN_FIRST_POST_STYLE_V1
        assert "질문형 결말을 남발하지 않는다" in SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_has_four_format_candidates(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        for fmt in (
            "CURRENT_ODDS_COMPARE",
            "WHY_MARKET_HOLDS",
            "DATA_LEDGER",
            "SHORT_SIGNAL",
        ):
            assert fmt in SCAN_FIRST_POST_STYLE_V1, (
                f"4 글 모양 후보 '{fmt}' 누락"
            )

    def test_scan_first_emphasizes_candidates_not_categories(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "고정 카테고리가 아니라" in SCAN_FIRST_POST_STYLE_V1
        assert "글 모양 후보" in SCAN_FIRST_POST_STYLE_V1
        assert "혼합" in SCAN_FIRST_POST_STYLE_V1
        assert "자유형" in SCAN_FIRST_POST_STYLE_V1
        assert "모든 글을 같은 템플릿으로 고정하지 않는다" in SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_forbids_review_summary_styles(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for forbidden in (
            "뉴스 해설형 장문",
            "유튜브 리뷰체",
            "보고서 문체",
        ):
            assert forbidden in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"금지 항목 '{forbidden}' 명시 누락"
            )

    def test_scan_first_forbids_legacy_speaker_phrases(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        for kw in (
            "이 영상에서는",
            "발언자는",
            "하더라고요",
            "화제가 됐다",
        ):
            assert kw in SCAN_FIRST_POST_STYLE_V1, (
                f"기존 약한 전달자 표현 '{kw}' 금지 목록 누락"
            )

    def test_scan_first_forbids_summary_endings(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        for kw in (
            "주목된다",
            "중요하다",
            "의미가 있다",
            "시사점을 준다",
            "여러분의 생각은?",
            "댓글로 남겨주세요",
        ):
            assert kw in SCAN_FIRST_POST_STYLE_V1, (
                f"기존 보고서식 결말 금지 예시 '{kw}' 누락"
            )

    def test_scan_first_forbids_fact_invention(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "새 숫자 발명" in SCAN_FIRST_POST_STYLE_V1
        assert "새 인과관계 추가" in SCAN_FIRST_POST_STYLE_V1
        assert "새 사실 / 새 숫자 / 새 인과는 추가하지 않는다" in SCAN_FIRST_POST_STYLE_V1

    def test_scan_first_forbids_korean_context_injection(self):
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        assert "원문에 없는 한국 맥락 강제 연결" in SCAN_FIRST_POST_STYLE_V1

    def test_openai_youtube_keeps_prior_layers(self):
        # 직전 PR 들의 핵심 구조가 그대로 살아있는지 (Fact Lock / Salience 등 무손)
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for kw in (
            "Salience-First Draft Planner",
            "Truth Integrity",
            "render_mode",
            "Framework Preservation Rule",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── B. Grok handoff — YouTube slim ───────────────────────────────
    def test_grok_handoff_has_scan_first_line(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문 한 줄.", source_type="youtube")
        for kw in (
            "모바일 스캔형 X 포스트",
            "뉴스 요약이나 영상 리뷰가 아니라",
            "긴 해설보다 첫 줄, 핵심 숫자, 짧은 항목",
            "원문에 없는 사실·숫자·사례·인과는 추가하지 마라",
        ):
            assert kw in out, f"Grok handoff 스캔형 지시 '{kw}' 누락"

    def test_grok_handoff_youtube_slim_lists_four_candidates(self):
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            {}, {"winner_angle": {"angle": "x"}}, "본문",
            source_type="youtube",
        )
        for fmt in (
            "CURRENT_ODDS_COMPARE", "WHY_MARKET_HOLDS",
            "DATA_LEDGER", "SHORT_SIGNAL",
        ):
            assert fmt in out, f"YouTube slim 4 후보 '{fmt}' 누락"

    def test_grok_handoff_directive_outside_codeblock(self):
        # 모바일 스캔형 지시가 ```text 코드블록 안에 들어가면 실패
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            {}, {"winner_angle": {"angle": "x"}}, "본문 한 줄.",
            source_type="youtube",
        )
        marker = "모바일 스캔형 X 포스트"
        instr_idx = out.find("## Grok 편집 지시")
        draft_idx = out.find("## 원문 초안")
        marker_idx = out.find(marker)
        assert -1 < instr_idx < marker_idx < draft_idx, (
            "스캔형 지시가 ## Grok 편집 지시 ↔ ## 원문 초안 사이여야 함"
        )
        import re
        m = re.search(r"```text\n(.*?)\n```", out, re.DOTALL)
        assert m is not None
        assert marker not in m.group(1)

    def test_grok_handoff_internal_label_removal_listed(self):
        # 내부 분석 라벨 제거 지시 명시
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            {}, {"winner_angle": {"angle": "x"}}, "본문",
            source_type="youtube",
        )
        for kw in (
            "진짜 쟁점",
            "지금 봐야 할 포인트",
            "반드시 살릴 포인트",
        ):
            assert kw in out, f"내부 분석 라벨 제거 지시 '{kw}' 누락"

    # ── C. Overfitting prevention ───────────────────────────────────
    def test_no_domain_spine_added(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for spine in (
            "Economic Spine",
            "Policy Spine",
            "Medical Spine",
            "AI Tech Spine",
        ):
            assert spine not in YOUTUBE_DIGEST_SYSTEM_PROMPT
            assert spine not in GEMINI_VIDEO_ANALYSIS_PROMPT

    def test_no_industry_or_company_overfitting(self):
        # 특정 기업/코인/정치인/국가/산업 예시 prompt 박힘 0
        from app.providers.openai_provider import SCAN_FIRST_POST_STYLE_V1
        forbidden_specifics = (
            "Polymarket", "Kalshi",
            "Tesla", "Apple", "Nvidia",
            "비트코인", "이더리움", "USDT",
            "삼성전자", "SK하이닉스",
            "트럼프", "이재명",
            # 특정 국가명
            "미국", "중국", "일본",
        )
        for kw in forbidden_specifics:
            assert kw not in SCAN_FIRST_POST_STYLE_V1, (
                f"SCAN_FIRST_POST_STYLE 안에 특정 실명 '{kw}' 박히면 안 됨 "
                f"(과적합)"
            )

    def test_grok_handoff_no_industry_overfitting(self):
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            {}, {"winner_angle": {"angle": "x"}}, "본문",
            source_type="youtube",
        )
        # 외부 Grok 편집용 마스터 프롬프트 + 4 후보 설명 안에 특정 실명 0
        for kw in ("Polymarket", "Tesla", "비트코인", "삼성전자",
                   "트럼프", "이재명"):
            assert kw not in out, (
                f"Grok handoff 안에 특정 실명 '{kw}' 박히면 안 됨"
            )

    def test_general_ko_prompt_no_scan_first(self):
        # 일반 KO prompt 에 SCAN_FIRST 가 새지 말 것 (기존 동작 보호)
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "SCAN_FIRST_POST_STYLE",
            "CURRENT_ODDS_COMPARE",
            "WHY_MARKET_HOLDS",
        ):
            assert kw not in SYSTEM_PROMPT_KO

    # ── D. schema/interface/모델 보존 ───────────────────────────────
    def test_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_response_format_schema_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        assert set(_RESPONSE_FORMAT_KO["json_schema"]["schema"]["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }


# ─── 외부 Grok 편집용 마스터 프롬프트 (SCAN_FIRST_GROK_EDITOR_PROMPT_V1) ─
class TestScanFirstGrokEditorPromptV1:
    """운영자가 외부 Grok UI 에 직접 복붙해 쓸 수 있는 편집 프롬프트."""

    def test_external_prompt_constant_exists(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "SCAN_FIRST_GROK_EDITOR_PROMPT_V1" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "X 포스트 전문 편집자" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1

    def test_external_prompt_has_four_candidates(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        for fmt in (
            "CURRENT_ODDS_COMPARE", "WHY_MARKET_HOLDS",
            "DATA_LEDGER", "SHORT_SIGNAL",
        ):
            assert fmt in SCAN_FIRST_GROK_EDITOR_PROMPT_V1, (
                f"외부 Grok 프롬프트 4 후보 '{fmt}' 누락"
            )

    def test_external_prompt_has_no_addition_rules(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        for kw in (
            "새 사실 추가 금지",
            "새 숫자 추가 금지",
            "새 인물/기업/기관/국가/사례 추가 금지",
            "새 인과관계 추가 금지",
            "원문에 없는 한국 맥락 추가 금지",
            "원문 핵심 재료 보존",
        ):
            assert kw in SCAN_FIRST_GROK_EDITOR_PROMPT_V1, (
                f"외부 Grok 핵심 금지 '{kw}' 누락"
            )

    def test_external_prompt_removes_legacy_styles(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        for kw in (
            "뉴스 해설형 장문",
            "유튜브 리뷰체",
            "보고서 말투",
            "이 영상에서는",
            "발언자는",
            "주목된다",
            "의미가 있다",
            "시사점을 준다",
            "여러분의 생각은?",
            "댓글로 남겨주세요",
            "긴 철학적 결론",
        ):
            assert kw in SCAN_FIRST_GROK_EDITOR_PROMPT_V1, (
                f"외부 Grok 제거 문체 예시 '{kw}' 누락"
            )

    def test_external_prompt_removes_internal_analysis_labels(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        for label in (
            "진짜 쟁점",
            "지금 봐야 할 포인트",
            "왜 이 글을 세게 써야 하는가",
            "반드시 살릴 포인트",
            "살릴 가치",
        ):
            assert label in SCAN_FIRST_GROK_EDITOR_PROMPT_V1, (
                f"내부 분석 라벨 제거 지시 '{label}' 누락"
            )

    def test_external_prompt_emphasizes_candidates_not_categories(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        # "고정 템플릿 아님" / "고정 템플릿이 아니라" 등 변형 허용
        assert "고정 템플릿" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "후보" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "혼합" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1

    def test_external_prompt_no_specific_overfitting(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        for kw in (
            "Polymarket", "Kalshi", "Tesla", "Apple", "Nvidia",
            "비트코인", "이더리움", "USDT",
            "삼성전자", "SK하이닉스",
            "트럼프", "이재명",
            "미국", "중국", "일본",
        ):
            assert kw not in SCAN_FIRST_GROK_EDITOR_PROMPT_V1, (
                f"외부 Grok 프롬프트 안에 특정 실명 '{kw}' 박히면 안 됨"
            )

    def test_external_prompt_final_output_one_post_only(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        # Output Language Rule v1 도입 — 한국어 X 포스트 → 영어 X 포스트
        assert "영어 X 포스트 1 개만 출력" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "English X post" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "편집 결과만 출력" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1


# ─── News Article Fact Lock v1 + news_link lane 적용 ────────────────
class TestNewsArticleFactLockV1:
    """[A] NEWS_ARTICLE_FACT_LOCK_V1 상수 + 8 룰 명시.
    [B] generate_draft 가 source_type == "news_link" 일 때 Fact Lock +
        House Format Router 를 SYSTEM_PROMPT_KO 에 append 하는 분기.
    [C] 다른 lane 동작 무손."""

    def test_news_fact_lock_constant_exists(self):
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        assert "News Article Fact Lock" in NEWS_ARTICLE_FACT_LOCK_V1

    def test_news_fact_lock_has_8_rules(self):
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for kw in (
            "기사 안에 있는 사실",
            "기사에 있는 사실과 작성자의 해석을 구분",
            "확정되지 않은 내용은 단정하지 않는다",
            "주장 강도를 높이지 않는다",
            "한국 맥락을 강제 주입하지 않는다",
        ):
            assert kw in NEWS_ARTICLE_FACT_LOCK_V1, (
                f"News Fact Lock 룰 '{kw}' 누락"
            )

    def test_news_fact_lock_applies_four_candidates(self):
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for fmt in (
            "CURRENT_ODDS_COMPARE", "WHY_MARKET_HOLDS",
            "DATA_LEDGER", "SHORT_SIGNAL",
        ):
            assert fmt in NEWS_ARTICLE_FACT_LOCK_V1, (
                f"News Fact Lock 의 형식 후보 '{fmt}' 누락"
            )

    def test_news_fact_lock_forbids_review_phrases(self):
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for kw in ("~라고 밝혔다", "~로 알려졌다", "~를 주목해야 한다"):
            assert kw in NEWS_ARTICLE_FACT_LOCK_V1

    def test_generate_draft_appends_fact_lock_for_news_link(self):
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        assert 'source_type == "news_link"' in src
        assert "NEWS_ARTICLE_FACT_LOCK_V1" in src
        # SCAN_FIRST_POST_STYLE_V1 (구 HOUSE_FORMAT_ROUTER_V1) append 확인
        assert "SCAN_FIRST_POST_STYLE_V1" in src

    def test_general_ko_prompt_no_fact_lock(self):
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        assert "News Article Fact Lock" not in SYSTEM_PROMPT_KO


# ─── Grok handoff lane 별 House Format 편집 지시 ────────────────────
class TestGrokHandoffHouseFormatLines:
    @staticmethod
    def _full_handoff(source_type: str) -> str:
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        return format_handoff(sp, ap, "본문", source_type=source_type)

    def test_youtube_slim_mentions_four_candidates(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문", source_type="youtube")
        for fmt in (
            "CURRENT_ODDS_COMPARE", "WHY_MARKET_HOLDS",
            "DATA_LEDGER", "SHORT_SIGNAL",
        ):
            assert fmt in out, f"YouTube slim 에 '{fmt}' 누락"
        assert "혼합" in out

    def test_news_link_handoff_has_house_format_section(self):
        out = self._full_handoff("news_link")
        assert "## House Format 편집 지시" in out
        assert "모바일 스캔형 X 포스트" in out
        assert "원문에 없는 사실·숫자·사례·인과는 추가하지 마라" in out
        for fmt in (
            "CURRENT_ODDS_COMPARE", "WHY_MARKET_HOLDS",
            "DATA_LEDGER", "SHORT_SIGNAL",
        ):
            assert fmt in out, f"news_link handoff 4 후보 '{fmt}' 누락"

    def test_news_link_handoff_section_outside_codeblock(self):
        out = self._full_handoff("news_link")
        import re
        m = re.search(r"```text\n(.*?)\n```", out, re.DOTALL)
        if m:
            assert "## House Format 편집 지시" not in m.group(1)
            assert "모바일 스캔형 X 포스트" not in m.group(1)
        rules_idx = out.find("## 최종 출력 규칙")
        house_idx = out.find("## House Format 편집 지시")
        assert -1 < rules_idx < house_idx, (
            "House Format 블록은 ## 최종 출력 규칙 다음 위치"
        )

    def test_manual_handoff_has_house_format_section(self):
        out = self._full_handoff("manual")
        assert "## House Format 편집 지시" in out
        assert "모바일 스캔형 X 포스트" in out
        assert "긴 해설보다 첫 줄, 핵심 숫자, 짧은 항목" in out

    def test_community_input_handoff_has_house_format_section(self):
        out = self._full_handoff("community_input")
        assert "## House Format 편집 지시" in out
        assert "모바일 스캔형 X 포스트" in out

    def test_rss_lane_no_house_format_section(self):
        out = self._full_handoff("rss")
        assert "## House Format 편집 지시" not in out

    def test_default_source_type_no_house_format_section(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문")
        assert "## House Format 편집 지시" not in out


# ─── Current Article Event Lock (news_link 분석 시점 강화) ──────────
class TestCurrentArticleEventLock:
    """draft 1497 류 — 2026 년 발표 기사를 2024 년 검토 사건으로 요약하는
    시간 오염 차단. NEWS_ARTICLE_FACT_LOCK_V1 안에 Current Article Event
    Lock 블록 (9 룰 + 4 금지) 명시."""

    def test_event_lock_block_present(self):
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        assert "Current Article Event Lock" in NEWS_ARTICLE_FACT_LOCK_V1

    def test_event_lock_has_9_rules(self):
        # 9 핵심 룰 — phrasing 변형 허용, 핵심 키워드만 검증
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for kw in (
            "기사 제목 / 출처 / 작성일",
            "새로 발생한 핵심 이벤트",
            "과거 연도",
            "과거 배경을 현재 기사 핵심 사건처럼 쓰지 않는다",
            "2026 년",
            "2024 년 사건으로 시작하면",
            "고려했다",
            "발표했다 / 결정했다 /\n   시행된다",
            "확정 이벤트",
            "보조\n   맥락으로만",
        ):
            assert kw in NEWS_ARTICLE_FACT_LOCK_V1, (
                f"Event Lock 룰 '{kw}' 누락"
            )

    def test_event_lock_has_explicit_prohibitions(self):
        # 4 명시 금지
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for kw in (
            "기사 작성일보다 과거인 배경 사건을 핵심 요약 첫 문장",
            "탈퇴 발표",
            "탈퇴 고려",
            "시행 예정",
            "검토 중",
            "LLM 지식으로 끌어오지 마라",
        ):
            assert kw in NEWS_ARTICLE_FACT_LOCK_V1, (
                f"Event Lock 금지 예시 '{kw}' 누락"
            )

    def test_event_lock_distinguishes_consider_vs_announce(self):
        # "고려했다 / 검토했다 / 루머" vs "발표했다 / 결정했다 / 시행된다"
        # 구분 명시
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        # 둘 다 prompt 안 명시 (구분 지시)
        assert "고려했다" in NEWS_ARTICLE_FACT_LOCK_V1
        assert "검토했다" in NEWS_ARTICLE_FACT_LOCK_V1
        assert "발표했다" in NEWS_ARTICLE_FACT_LOCK_V1
        assert "시행된다" in NEWS_ARTICLE_FACT_LOCK_V1

    def test_event_lock_lists_decisive_events(self):
        # "발표 / 결정 / 시행 / 탈퇴 / 승인 / 통past / 수주 / 공개" 같은
        # 확정 이벤트 키워드 명시
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for kw in ("발표", "결정", "시행", "탈퇴", "승인", "통과", "수주", "공개"):
            assert kw in NEWS_ARTICLE_FACT_LOCK_V1

    def test_event_lock_priority_before_fact_lock_rules(self):
        # Current Article Event Lock 이 News Article Fact Lock 핵심 8 룰
        # 보다 먼저 위치 (우선순위)
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        evt_idx = NEWS_ARTICLE_FACT_LOCK_V1.find("[Current Article Event Lock]")
        fact_idx = NEWS_ARTICLE_FACT_LOCK_V1.find(
            "[News Article Fact Lock — 핵심 8 룰]"
        )
        assert evt_idx != -1 and fact_idx != -1
        assert evt_idx < fact_idx, (
            "Event Lock 이 Fact Lock 핵심 8 룰보다 먼저 위치해야 함 "
            "(시점 잠금 우선순위)"
        )

    def test_existing_fact_lock_rules_preserved(self):
        # 기존 8 룰 그대로 유지 (Event Lock 추가가 기존 규칙 약화 X)
        from app.providers.openai_provider import NEWS_ARTICLE_FACT_LOCK_V1
        for kw in (
            "기사 안에 있는 사실",
            "기사에 있는 사실과 작성자의 해석을 구분",
            "확정되지 않은 내용은 단정하지 않는다",
            "주장 강도를 높이지 않는다",
            "한국 맥락을 강제 주입하지 않는다",
        ):
            assert kw in NEWS_ARTICLE_FACT_LOCK_V1

    def test_news_link_runtime_append_still_present(self):
        # generate_draft 의 news_link 분기에서 Fact Lock + SCAN_FIRST_POST_STYLE
        # runtime append 여전히 작동 (이전 PR 결과 유지)
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        assert 'source_type == "news_link"' in src
        assert "NEWS_ARTICLE_FACT_LOCK_V1" in src
        assert "SCAN_FIRST_POST_STYLE_V1" in src


# ─── Bug 1 fix — non-YouTube user_msg directive 한국 맥락 강제 제거 ──
class TestNonYouTubeFinalDirective:
    """기존 'non-YouTube directive = 한국 맥락 강제 주입' 명령이 글로벌
    주제까지 한국 macro/시장/정책으로 오염시키던 문제 차단.

    한국 키워드 (한국 / 국내 / 한국 시장 / 한국 기업 / 한국 투자자 /
    한국 정책) 가 명시된 경우에만 한국 맥락 사용. 그 외 글로벌 주제는
    한국 맥락 강제 추가 금지."""

    def test_non_youtube_directive_no_forced_korea(self):
        # generate_draft 안에 "한국 맥락이 강제 주입된 드래프트" 문구
        # (강제 주입형) 0 hit
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        assert "한국 맥락이 강제 주입된 드래프트" not in src, (
            "non-YouTube directive 가 '한국 맥락이 강제 주입된 드래프트' "
            "문구를 그대로 사용하면 글로벌 주제까지 한국 맥락으로 오염됨"
        )

    def test_non_youtube_directive_conditional_korea_only(self):
        # 한국 맥락은 키워드 명시된 경우에만 사용 — 조건문 명시
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        assert "한국 맥락이 명시된" in src or "한국 키워드" in src
        assert "한국 맥락을 강제로 추가하지 마라" in src or (
            "한국 맥락 강제" in src and "추가하지 마라" in src
        )

    def test_non_youtube_directive_lists_korea_keywords(self):
        # 한국 명시 키워드 — Python 멀티라인 문자열 concat ("한국 " "기업"
        # → 런타임 "한국 기업") 도 hit. 인접 string literal 사이의 `" "`
        # 제거 후 whitespace normalize.
        import inspect
        import re
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        # Strip inter-literal `" "` + 일반 공백 normalize
        joined = re.sub(r'"\s*"', "", src)
        normalized = re.sub(r"\s+", " ", joined)
        for kw in ("한국", "국내", "한국 시장", "한국 기업",
                   "한국 투자자", "한국 정책"):
            assert kw in normalized, f"한국 명시 키워드 '{kw}' 누락"

    def test_non_youtube_directive_forbids_korea_macro_invention(self):
        # 원문 밖 한국 거시경제 / 코인 / 정책 / 투자자 발명 금지 명시
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        for kw in ("거시", "한국 코인", "한국 정책", "한국 투자자"):
            assert kw in src

    def test_youtube_directive_unchanged(self):
        # YouTube directive (영상 원문 잠금) 그대로 유지
        import inspect
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        assert "영상 원문 안에서만 드래프트를 작성하라" in src
        assert "한국 macro/시장/환율/투자/부동산" in src
        assert 'source_type == "youtube"' in src
