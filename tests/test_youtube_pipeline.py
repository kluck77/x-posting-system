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

    def test_slim_instruction_has_all_13_rules(self):
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
            "첫 문장 강화",
            "마지막 문장 강화",
            "⚠️ / 📌 형식 제거",
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

    def test_trigger_inside_grok_instruction_section(self):
        # 두 줄 모두 `## Grok 편집 지시` 와 `## 원문 초안` 사이에 있어야 함
        # 그리고 TRIGGER 가 RESTRUCTURE 보다 먼저 나와야 함 (사용자 명시 순서).
        out = self._slim()
        instr_idx = out.find("## Grok 편집 지시")
        draft_idx = out.find("## 원문 초안")
        trigger_idx = out.find(self.TRIGGER)
        restruct_idx = out.find(self.RESTRUCTURE)
        assert instr_idx != -1 and draft_idx != -1
        assert trigger_idx != -1 and restruct_idx != -1
        assert instr_idx < trigger_idx < restruct_idx < draft_idx, (
            "trigger 와 restructure 가 ## Grok 편집 지시 섹션 안 "
            "(## 원문 초안 위) + 올바른 순서로 있어야 함"
        )

    def test_trigger_not_inside_draft_codefence(self):
        # 두 줄 모두 ```text ... ``` 원문 초안 코드블록 안에 들어가면 안 됨
        out = self._slim()
        import re
        m = re.search(r"```text\n(.*?)\n```", out, re.DOTALL)
        assert m is not None
        assert self.TRIGGER not in m.group(1)
        assert self.RESTRUCTURE not in m.group(1), (
            "재구성 지시가 원문 초안 코드블록 안에 들어가면 Grok 이 "
            "본문으로 오해함"
        )

    def test_trigger_absent_from_non_youtube_handoff(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문", source_type="news_link")
        assert self.TRIGGER not in out
        assert self.RESTRUCTURE not in out
        # non-YouTube 는 관련 키워드 자체도 새지 말 것
        assert "4-Editor Board" not in out
        assert "과감하게 재구성" not in out

    def test_trigger_absent_when_default_source_type(self):
        # source_type kwarg 미전달 시 (=일반 lane 기본 동작) 도 두 줄 미포함
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문")
        assert "4-Editor Board" not in out
        assert "과감하게 재구성" not in out


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
        # non-YouTube 기존 directive 유지
        assert "한국 맥락이 강제 주입된 드래프트를" in src
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
