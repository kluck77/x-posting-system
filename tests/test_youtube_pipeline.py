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
        assert "95% 이상 보존" in YOUTUBE_DIGEST_SYSTEM_PROMPT
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
        from app.services.grok_handoff import format_handoff
        out = format_handoff(
            self._sp_with_meta(), self._ap_with_meta(),
            "본문", source_type="youtube",
        )
        assert "원문에 없는 모든 것" in out
        assert "결론 명제 변경 금지" in out
        assert "95% 미만 보존 금지" in out
        assert "메타 표현" in out
        assert "편집 결과 외 다른 텍스트 출력 금지" in out

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
        # "A 때문에 B" 인과 비약 방지 룰
        assert "A 때문에 B" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "원문이 직접 연결하지 않았다면" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_prompt_keeps_95pct_rules(self):
        # render_mode OS 추가가 기존 95% 보존 룰을 약화하지 않았는지
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for must_have in (
            "95% 이상 보존",
            "스레드 분할 금지",
            "결론 명제 변경 금지",
            "발명 0 건",
        ):
            assert must_have in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"기존 95% 보존 룰 '{must_have}' 누락"
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


# ─── 10) Claim-Locked Renderer v1 — YouTube prompt + slim handoff ────
class TestClaimLockedRenderer:
    """[A] YouTube prompt 에 Claim-Locked Renderer 블록이 포함됐는지 검증.
    [B] 일반 KO prompt 는 변경 안 됐는지.
    [C] YouTube slim handoff 에 Claim Strength 가드가 추가됐는지.
    [D] non-YouTube handoff 는 legacy 구조 유지하고 Claim-Locked 문구
        들어가지 않았는지."""

    # ── A. OpenAI YouTube prompt ────────────────────────────────────
    def test_youtube_prompt_has_claim_locked_block(self):
        from app.providers.openai_provider import (
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
            YOUTUBE_CLAIM_LOCKED_RENDERER_V1,
        )
        # 별도 상수도 노출되어 있어야 함 (테스트 가능성 / swap 용이)
        assert "Claim-Locked Renderer v1" in YOUTUBE_CLAIM_LOCKED_RENDERER_V1
        # 합쳐진 최종 prompt 에 핵심 키워드 모두 포함
        for kw in (
            "Claim-Locked Renderer",
            "LOCKED CLAIM",
            "Claim Strength",
            "인과 비약",
            "A 와 B 가 모두",
            "HIGH RISK",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube prompt 에 '{kw}' 누락"
            )

    def test_youtube_prompt_has_5_render_modes(self):
        # 직전 PR 의 5 모드는 Claim-Locked 적용 후에도 유지
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for mode in (
            "news_policy",
            "lecture_summary",
            "analysis_market",
            "community_x",
            "writerly",
        ):
            assert mode in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_prompt_has_strength_examples(self):
        # 약한 표현 → 강한 표현 변환 금지 예시
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "가능성이 있다" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "확정적이다" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "무너뜨린다" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_prompt_has_claim_type_taxonomy(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for t in ("FACT", "NUMBER", "CAUSE", "FORECAST", "OPINION",
                  "UNCERTAIN", "UNSAFE"):
            assert t in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"Claim Type '{t}' 누락"
            )

    def test_youtube_prompt_has_high_risk_domains(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for d in ("의료", "감염병", "금융", "법률", "정책", "전쟁"):
            assert d in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_youtube_prompt_body_meta_label_block(self):
        # body 에 LOCKED CLAIM / FACT 같은 메타 라벨 출력 금지 룰
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "LOCKED CLAIM" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "메타 설명" in YOUTUBE_DIGEST_SYSTEM_PROMPT or "메타 라벨" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── B. 일반 lane 격리 ───────────────────────────────────────────
    def test_general_ko_prompt_no_claim_locked(self):
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "Claim-Locked Renderer",
            "LOCKED CLAIM",
            "Claim Strength",
            "FACT",
            "FORECAST",
            "UNSAFE",
        ):
            assert kw not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 YouTube 전용 '{kw}' 가 새어들어가면 안 됨"
            )

    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    # ── C. YouTube slim handoff 에 Claim Strength 가드 ──────────────
    def _slim_out(self) -> str:
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        return format_handoff(sp, ap, "본문", source_type="youtube")

    def test_youtube_slim_has_strength_guard(self):
        out = self._slim_out()
        for line in (
            "원문 주장 강도를 높이지 말 것",
            "\"가능성\"을 \"확정\"으로 바꾸지 말 것",
            "문장은 다듬되 주장은 확장하지 말 것",
        ):
            assert line in out, f"YouTube slim handoff 에 '{line}' 누락"

    def test_youtube_slim_has_causal_leap_guard(self):
        out = self._slim_out()
        assert "A 와 B 가 모두" in out
        assert "A 때문에 B" in out

    def test_youtube_slim_has_high_risk_domain_rule(self):
        out = self._slim_out()
        assert "의료·정책·금융·법률·전쟁" in out
        assert "공포·확정·붕괴 표현" in out

    # ── D. non-YouTube handoff legacy 구조 유지 ─────────────────────
    def test_non_youtube_handoff_no_claim_locked_lines(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문", source_type="news_link")
        # YouTube slim 만 있는 강도 가드 문구가 일반 lane 에 새지 않아야 함
        for line in (
            "원문 주장 강도를 높이지 말 것",
            "\"가능성\"을 \"확정\"으로 바꾸지 말 것",
            "공포·확정·붕괴 표현",
            "[YouTube 95% 보존형 장문 — Grok 편집용]",
        ):
            assert line not in out, f"일반 lane 에 YouTube 전용 '{line}' 가 새면 안 됨"
        # 일반 lane 의 legacy 메타 블록은 그대로 유지
        assert "## 이 글의 핵심 각도" in out
        assert "## 최종 출력 규칙" in out


# ─── 11) Korean Writer/Lecturer/Journalist Rendering Layer v1 ────────
class TestKoreanWriterRenderingLayer:
    """[A] YouTube prompt 에 Writer Layer 7 표현 기술 + 강도 유지.
    [B] 5 모드별 비율 명시.
    [C] 일반 KO prompt 격리.
    [D] YouTube slim handoff 에 Writer Boundary 7 줄.
    [E] non-YouTube handoff 에 Writer Boundary 미노출."""

    # ── A. YouTube prompt 에 Writer Layer ───────────────────────────
    def test_prompt_has_writer_layer_block(self):
        from app.providers.openai_provider import (
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
            YOUTUBE_KOREAN_WRITER_RENDERING_LAYER_V1,
        )
        assert "Korean Writer/Lecturer/Journalist Rendering Layer v1" in (
            YOUTUBE_KOREAN_WRITER_RENDERING_LAYER_V1
        )
        for kw in (
            "Korean Writer/Lecturer/Journalist Rendering Layer",
            "첫 문장 강화",
            "긴장 배치",
            "강사식 설명",
            "저널리스트식 정리",
            "작가식 몰입",
            "애널리스트식 결론",
            "원문에 없는 장면",
            "주장 강도",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube prompt 에 Writer Layer 키워드 '{kw}' 누락"
            )

    def test_prompt_keeps_claim_lock_priority(self):
        # Writer Layer 가 Claim-Lock 위에 추가됐어도 Claim-Lock 키워드는
        # 여전히 prompt 안에 살아있어야 함
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for kw in (
            "Claim-Locked Renderer",
            "LOCKED CLAIM",
            "95% 이상 보존",
            "스레드 분할 금지",
            "결론 명제 변경 금지",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── B. mode 별 비율 명시 ────────────────────────────────────────
    def test_prompt_has_per_mode_ratios(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        # 5 mode 모두 비율/역할 차이 명시 (간접 검증: 모드명 + % 또는 역할)
        for mode in (
            "news_policy",
            "lecture_summary",
            "analysis_market",
            "community_x",
            "writerly",
        ):
            assert mode in YOUTUBE_DIGEST_SYSTEM_PROMPT
        # 비율 명시 — 70% / 60% / 사람 말투 등 키워드로 간접 검증
        assert "저널리스트 70%" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "강사 70%" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "애널리스트 60%" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "사람 말투 60%" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "작가 60%" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── C. 일반 KO prompt 격리 ──────────────────────────────────────
    def test_general_ko_prompt_no_writer_layer(self):
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "Korean Writer/Lecturer/Journalist Rendering Layer",
            "첫 문장 강화",
            "긴장 배치",
            "강사식 설명",
            "저널리스트식 정리",
            "작가식 몰입",
            "애널리스트식 결론",
        ):
            assert kw not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 Writer Layer '{kw}' 가 새어들어가면 안 됨"
            )

    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    # ── D. YouTube slim handoff 에 Writer Boundary ──────────────────
    def _slim_out(self) -> str:
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        return format_handoff(sp, ap, "본문", source_type="youtube")

    def test_youtube_slim_has_writer_boundary(self):
        out = self._slim_out()
        for line in (
            "문장 리듬은 다듬되, 주장은 확장하지 말 것",
            "작가처럼 보이려고 원문에 없는 장면/감정/대사를 만들지 말 것",
            "강사처럼 쉽게 풀되, 원문에 없는 예시를 만들지 말 것",
            "저널리스트처럼 사실과 해석을 분리할 것",
        ):
            assert line in out, f"YouTube slim handoff 에 '{line}' 누락"

    def test_youtube_slim_has_first_last_sentence_rules(self):
        out = self._slim_out()
        assert "첫 문장은 강화하되, 원문에 없는 사실을 넣지 말 것" in out
        assert "마지막 문장은 선명하게 만들되, 결론 명제를 바꾸지 말 것" in out
        assert "불확실한 주장은 낮춰 쓸 것" in out

    # ── E. non-YouTube handoff 에 Writer Boundary 미노출 ────────────
    def test_non_youtube_handoff_no_writer_boundary(self):
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문", source_type="news_link")
        for line in (
            "작가처럼 보이려고 원문에 없는 장면/감정/대사를 만들지 말 것",
            "강사처럼 쉽게 풀되, 원문에 없는 예시를 만들지 말 것",
            "저널리스트처럼 사실과 해석을 분리할 것",
            "마지막 문장은 선명하게 만들되, 결론 명제를 바꾸지 말 것",
        ):
            assert line not in out, (
                f"일반 lane 에 YouTube 전용 Writer Boundary '{line}' 가 새면 안 됨"
            )
        # 일반 lane legacy 구조 유지
        assert "## 이 글의 핵심 각도" in out
        assert "## 최종 출력 규칙" in out


# ─── 12) Salience-Locked Economic Spine v1 ──────────────────────────
class TestSalienceLockedEconomicSpine:
    """[A] Gemini extractor prompt 에 Economic Spine 추출 룰.
    [B] OpenAI YouTube renderer prompt 에 Economic Spine 보존 룰.
    [C] 일반 KO prompt 격리.
    [D] schema/interface/모델 보존."""

    # ── A. Gemini extractor (youtube_pipeline.py) ───────────────────
    def test_gemini_prompt_has_dynamic_salience_map(self):
        # Dynamic Salience Map v1 으로 교체됨 — 도메인-agnostic 7 카테고리.
        # 옛 Salience-Locked Economic Spine 헤더 / Polymarket·Kalshi 명시는
        # Gemini extractor 에서 제거 (도메인 강제 회피).
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
            "preservation_targets",
        ):
            assert kw in GEMINI_VIDEO_ANALYSIS_PROMPT, (
                f"Gemini prompt 에 Dynamic Salience 키워드 '{kw}' 누락"
            )

    def test_gemini_prompt_no_domain_overfitting(self):
        # Polymarket/Kalshi 같은 특정 도메인 예시는 Gemini extractor 에
        # 박혀있으면 안 됨 (모든 영상에 강제될 위험). OpenAI prompt 의
        # Economic Spine 안에서만 선택 패턴으로 사용.
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        assert "Polymarket" not in GEMINI_VIDEO_ANALYSIS_PROMPT
        assert "Kalshi" not in GEMINI_VIDEO_ANALYSIS_PROMPT
        # 옛 헤더도 사라졌어야 함
        assert "Salience-Locked Economic Spine" not in GEMINI_VIDEO_ANALYSIS_PROMPT

    def test_gemini_prompt_keeps_existing_extraction(self):
        # Spine 추가가 기존 atomic_claims / claim graph 추출 룰을 약화하지
        # 않았는지
        from app.sources.youtube_pipeline import GEMINI_VIDEO_ANALYSIS_PROMPT
        for kw in (
            "atomic_claims",
            "examples",
            "counter_arguments",
            "conclusion_claim",
            "claims",
            "key_numbers",
        ):
            assert kw in GEMINI_VIDEO_ANALYSIS_PROMPT

    # ── B. OpenAI YouTube renderer (openai_provider.py) ─────────────
    def test_openai_youtube_prompt_has_economic_spine_rule(self):
        from app.providers.openai_provider import (
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
            YOUTUBE_ECONOMIC_SPINE_PRESERVATION_V1,
        )
        # 별도 상수도 노출 (개별 검증 가능)
        assert "Economic Spine Preservation Rule" in (
            YOUTUBE_ECONOMIC_SPINE_PRESERVATION_V1
        )
        for kw in (
            "Economic Spine Preservation Rule",
            "핵심 기업/플랫폼",
            "성장 수치",
            "돈이 흐르는 구조",
            "누가 버는지",
            "누가 잃는지",
            "Polymarket",
            "Kalshi",
            "윤리 논란은 중요하지만",
            "preservation_targets",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube renderer 에 Spine 키워드 '{kw}' 누락"
            )

    def test_openai_youtube_prompt_has_predmarket_structure(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "예측시장 주제 전용 구조" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        # "정보 비대칭을 돈으로" 와 "바꾸는 시장" 이 prompt 안 (줄바꿈 사이)
        # 모두 등장하는지 검증
        assert "정보 비대칭을 돈으로" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "바꾸는 시장" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_openai_youtube_prompt_keeps_prior_layers(self):
        # 95% 보존 / Claim-Locked / Writer Layer 가 그대로 살아있는지
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        for kw in (
            "95% 이상 보존",
            "스레드 분할 금지",
            "결론 명제 변경 금지",
            "Claim-Locked Renderer",
            "LOCKED CLAIM",
            "Korean Writer/Lecturer/Journalist Rendering Layer",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── C. 일반 lane 격리 ───────────────────────────────────────────
    def test_general_ko_prompt_no_economic_spine(self):
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "Economic Spine Preservation Rule",
            "Salience-Locked Economic Spine",
            "Polymarket",
            "Kalshi",
            "Money Flow",
            "Retail Outcome",
            "Winner / Loser Map",
        ):
            assert kw not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 YouTube 전용 Spine '{kw}' 가 새어들어가면 안 됨"
            )

    # ── D. schema / interface / model 보존 ──────────────────────────
    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_response_format_schema_unchanged(self):
        # _RESPONSE_FORMAT_KO 의 strict schema 5 필드 그대로
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        schema = _RESPONSE_FORMAT_KO["json_schema"]["schema"]
        required = set(schema["required"])
        assert required == {"hook", "body", "stake", "point", "archetype"}, (
            "response_format strict schema 가 변경되면 provider interface "
            "변경에 해당 — Spine 추가는 prompt-level 만 허용"
        )

    def test_youtube_analysis_dataclass_unchanged(self):
        # YoutubeAnalysis dataclass 의 v4 확장 필드 (atomic_claims /
        # examples / counter_arguments / segments / conclusion_claim /
        # preservation_targets) 가 그대로 존재
        from app.sources.youtube_pipeline import YoutubeAnalysis
        ana = YoutubeAnalysis(
            video_id="v", url="u", channel="c", speaker="s",
            video_summary="vs", main_argument="ma",
            full_analysis="fa", downstream_summary="ds",
        )
        for field in (
            "atomic_claims", "examples", "counter_arguments",
            "segments", "conclusion_claim", "preservation_targets",
        ):
            assert hasattr(ana, field), (
                f"YoutubeAnalysis 에서 '{field}' 누락 — DB schema 변경 의심"
            )


# ─── 13) Dynamic Salience-First Drafting v1 (renderer + clamp 완화) ──
class TestDynamicSalienceFirstDrafting:
    """[B] OpenAI YouTube prompt 에 Salience-First Drafting 블록.
    [C] Economic Spine / 도메인 패턴이 Salience 아래 선택적으로 작동.
    [D] 일반 KO prompt 격리.
    [E] 모델/schema/interface 보존."""

    # ── B. Salience-First Drafting ──────────────────────────────────
    def test_youtube_prompt_has_salience_first_drafting(self):
        from app.providers.openai_provider import (
            YOUTUBE_DIGEST_SYSTEM_PROMPT,
            YOUTUBE_DYNAMIC_SALIENCE_DRAFTING_V1,
        )
        assert "Salience-First Drafting" in YOUTUBE_DYNAMIC_SALIENCE_DRAFTING_V1
        for kw in (
            "Salience-First Drafting",
            "핵심 재료 보존",
            "고정 템플릿으로 글을 쓰지 않는다",
            "추상어로 지우기",
            "500자 이하 요약문으로 끝내지 마라",
            "Tone-Safety Clamp 완화",
            "truth integrity",
        ):
            assert kw in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"YouTube prompt 에 Salience-First 키워드 '{kw}' 누락"
            )

    def test_youtube_prompt_has_priority_order(self):
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        # 작성 우선순위 5 단계: 1 핵심 재료 / 2 결론 / 3 몰입 / 4 리듬 / 5 압축
        assert "작성 우선순위" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "1. 핵심 재료 보존" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "5. 압축" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── C. 고정 도메인 구조 전역화 금지 ─────────────────────────────
    def test_economic_spine_is_optional_under_salience(self):
        # Economic Spine 은 Salience-First Drafting 보다 *위* 위치에 있고,
        # Drafting 블록이 "위의 Economic Spine ... 도 강제 템플릿이 아니다"
        # 라고 명시 → Spine 은 선택 패턴으로 격하됨.
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        # Drafting 블록에 Economic Spine 강제 금지 명시
        assert "Economic Spine" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "강제 템플릿이 아니다" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "특정 도메인 고정 구조를 모든 글에 강제하기" in (
            YOUTUBE_DIGEST_SYSTEM_PROMPT
        )

    def test_clamps_softened_not_removed(self):
        # truth integrity 룰 (Claim-Lock) 은 살아있고, 위험 도메인 자동
        # 낮춰쓰기 clamp 만 완화됐는지.
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        # 유지: truth integrity 5 룰
        for keep in (
            "원문에 없는 사실은 만들지 않는다",
            "원문에 없는 숫자는 만들지 않는다",
            "원문에 없는 인과는 만들지 않는다",
            "주장 강도를 높이지 않는다",
            "결론 명제를 변경하지 않는다",
        ):
            assert keep in YOUTUBE_DIGEST_SYSTEM_PROMPT, (
                f"truth integrity 룰 '{keep}' 가 사라지면 안 됨"
            )
        # 완화: 모든 위험 표현 일괄 낮춤 패턴 차단
        assert "원문 강도를 정확히 유지" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "무조건 낮춰 쓰지 마라" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    # ── D. 일반 lane 격리 ───────────────────────────────────────────
    def test_general_ko_prompt_no_salience_first(self):
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        for kw in (
            "Salience-First Drafting",
            "Dynamic Salience Map",
            "Tone-Safety Clamp",
            "truth integrity",
            "Core Entities",
            "Core Mechanism",
        ):
            assert kw not in SYSTEM_PROMPT_KO, (
                f"일반 KO prompt 에 YouTube 전용 '{kw}' 가 새어들어가면 안 됨"
            )

    # ── E. 모델/schema/interface 보존 ───────────────────────────────
    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_response_format_schema_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        schema = _RESPONSE_FORMAT_KO["json_schema"]["schema"]
        assert set(schema["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }
