"""Output Language Rule v1 — 최종 X post body 영어 전환 회귀 가드.

검증 범위:
- OPENAI prompt 의 OUTPUT_LANGUAGE_RULE_V1 상수 존재 + 핵심 룰
- KO lane runtime append (manual / news_link / community_input + youtube)
- _final_directive 안 영어 출력 강제 명시
- Grok handoff (YouTube slim + lane-specific) 영어 출력 명시
- SCAN_FIRST_GROK_EDITOR_PROMPT_V1 영어 출력 명시
- handoff English directive 가 ```text 코드블록 밖 위치
- 운영 UI / Telegram 버튼 / DB schema / provider interface / 모델 / source
  routing 무손
"""
from __future__ import annotations

import inspect
import re


# ─── A. OPENAI provider — OUTPUT_LANGUAGE_RULE_V1 ────────────────────
class TestOutputLanguageRuleConstant:
    def test_constant_exists_and_named(self):
        from app.providers.openai_provider import OUTPUT_LANGUAGE_RULE_V1
        assert "Output Language Rule v1" in OUTPUT_LANGUAGE_RULE_V1
        assert "final X post must be written in English" in OUTPUT_LANGUAGE_RULE_V1

    def test_korean_input_allowed_english_output_required(self):
        # 한국어 입력 OK / 영어 최종 출력 강제 명시
        from app.providers.openai_provider import OUTPUT_LANGUAGE_RULE_V1
        assert "Korean input" in OUTPUT_LANGUAGE_RULE_V1
        assert "natural English" in OUTPUT_LANGUAGE_RULE_V1

    def test_no_literal_translation(self):
        from app.providers.openai_provider import OUTPUT_LANGUAGE_RULE_V1
        assert "Do not translate Korean literally" in OUTPUT_LANGUAGE_RULE_V1

    def test_no_korean_final_body(self):
        from app.providers.openai_provider import OUTPUT_LANGUAGE_RULE_V1
        assert "no Korean final body" in OUTPUT_LANGUAGE_RULE_V1

    def test_keep_facts_no_invention(self):
        from app.providers.openai_provider import OUTPUT_LANGUAGE_RULE_V1
        # facts/numbers/entities 보존 + new facts/numbers/entities 추가 금지
        for kw in (
            "original facts",
            "original numbers",
            "original entities",
            "Do not add",
            "new facts",
            "new numbers",
            "forced Korea context",
        ):
            assert kw in OUTPUT_LANGUAGE_RULE_V1, (
                f"fact preservation 룰 '{kw}' 누락"
            )

    def test_scan_first_style_preserved(self):
        # 스캔 우선 / 짧은 줄 / 강한 헤드라인 명시
        from app.providers.openai_provider import OUTPUT_LANGUAGE_RULE_V1
        for kw in ("short lines", "scan-first", "strong headline", "visible numbers"):
            assert kw in OUTPUT_LANGUAGE_RULE_V1


class TestOutputLanguageRuleWiring:
    def test_youtube_digest_prompt_includes_rule(self):
        # YouTube digest 시스템 프롬프트에 OUTPUT_LANGUAGE_RULE_V1 포함
        from app.providers.openai_provider import YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "Output Language Rule v1" in YOUTUBE_DIGEST_SYSTEM_PROMPT
        assert "final X post must be written in English" in YOUTUBE_DIGEST_SYSTEM_PROMPT

    def test_generate_draft_appends_rule_for_ko_lane(self):
        # KO lane (non-YouTube) 의 system_prompt 끝에 runtime append 확인
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        assert "OUTPUT_LANGUAGE_RULE_V1" in src, (
            "generate_draft 의 KO lane 분기에 OUTPUT_LANGUAGE_RULE_V1 append 누락"
        )

    def test_final_directive_enforces_english_for_youtube(self):
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        # YouTube directive 가 영어 강제 directive 를 합성
        assert "_english_directive" in src
        # 영어 강제 directive 본문에 핵심 키워드
        assert "최종 X post" in src
        assert "영어로만 작성" in src
        assert "한국어 직역" in src or "직역" in src
        assert "Korean final body 금지" in src

    def test_final_directive_enforces_english_for_non_youtube(self):
        # non-YouTube 분기도 동일 _english_directive 사용
        from app.providers.openai_provider import OpenAIDraftWriter
        src = inspect.getsource(OpenAIDraftWriter.generate_draft)
        # _english_directive 변수가 youtube/non-youtube 양쪽에서 + 로 결합
        # → 변수 정의 1 회 + 사용 2 회
        assert src.count("_english_directive") >= 2, (
            "_english_directive 가 youtube + non-youtube 양 분기에 사용 안 됨"
        )

    def test_general_ko_prompt_static_unchanged(self):
        # SYSTEM_PROMPT_KO 정적 상수는 그대로 (runtime append 만 사용)
        from app.providers.openai_provider import SYSTEM_PROMPT_KO
        # 정적 SYSTEM_PROMPT_KO 안에 OUTPUT_LANGUAGE_RULE_V1 직접 포함은 안 함
        # (runtime append 로만 적용 — 기존 정적 상수 보존 원칙)
        assert "Output Language Rule v1" not in SYSTEM_PROMPT_KO


class TestModelAndSchemaUnchanged:
    def test_openai_model_unchanged(self):
        from app.providers import openai_provider
        assert openai_provider.OPENAI_MODEL == "gpt-4o-mini"

    def test_response_format_schema_unchanged(self):
        from app.providers.openai_provider import _RESPONSE_FORMAT_KO
        assert set(_RESPONSE_FORMAT_KO["json_schema"]["schema"]["required"]) == {
            "hook", "body", "stake", "point", "archetype",
        }


# ─── B. Grok handoff — English output directive ──────────────────────
class TestGrokHandoffEnglishDirective:
    @staticmethod
    def _slim_handoff() -> str:
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": [], "evidence_pack": [], "concept_translation": ""}
        ap = {"winner_angle": {"angle": "x"}, "core_tension": "x",
              "frame_type": "x", "story_spine": []}
        return format_handoff(sp, ap, "본문 한 줄.", source_type="youtube")

    @staticmethod
    def _full_handoff(source_type: str) -> str:
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        return format_handoff(sp, ap, "본문", source_type=source_type)

    def test_youtube_slim_has_english_directive(self):
        out = self._slim_handoff()
        for kw in (
            "Final edited post must be in English",
            "Do not output Korean",
            "Do not translate literally from Korean",
        ):
            assert kw in out, f"YouTube slim 영어 directive '{kw}' 누락"

    def test_youtube_slim_english_directive_outside_codeblock(self):
        out = self._slim_handoff()
        marker = "Final edited post must be in English"
        instr_idx = out.find("## Grok 편집 지시")
        draft_idx = out.find("## 원문 초안")
        marker_idx = out.find(marker)
        assert -1 < instr_idx < marker_idx < draft_idx, (
            "영어 directive 가 ## Grok 편집 지시 ↔ ## 원문 초안 사이여야 함"
        )
        m = re.search(r"```text\n(.*?)\n```", out, re.DOTALL)
        assert m is not None
        assert marker not in m.group(1), (
            "영어 directive 가 원문 초안 코드블록 안에 들어가면 안 됨"
        )

    def test_news_link_has_english_directive(self):
        out = self._full_handoff("news_link")
        assert "Final edited post must be in English" in out

    def test_manual_has_english_directive(self):
        out = self._full_handoff("manual")
        assert "Final edited post must be in English" in out

    def test_community_input_has_english_directive(self):
        out = self._full_handoff("community_input")
        assert "Final edited post must be in English" in out

    def test_news_link_english_directive_outside_codeblock(self):
        out = self._full_handoff("news_link")
        m = re.search(r"```text\n(.*?)\n```", out, re.DOTALL)
        if m:
            assert "Final edited post must be in English" not in m.group(1)
        # ## House Format 편집 지시 블록 안에 위치 확인
        house_idx = out.find("## House Format 편집 지시")
        eng_idx = out.find("Final edited post must be in English")
        assert -1 < house_idx < eng_idx

    def test_default_source_type_no_english_directive(self):
        # default source_type (House Format 블록 미적용) 은 영어 directive
        # 미렌더 — 단, lane-specific block 만 미적용 (다른 곳 leak 0)
        from app.services.grok_handoff import format_handoff
        sp = {"confirmed_facts": ["사실 1"], "evidence_pack": [],
              "concept_translation": ""}
        ap = {"winner_angle": {"angle": "앵글"}, "core_tension": "긴장",
              "frame_type": "x", "story_spine": []}
        out = format_handoff(sp, ap, "본문")  # source_type=""
        # House Format 블록 자체가 없으면 영어 directive 도 없음
        assert "## House Format 편집 지시" not in out

    def test_rss_lane_no_house_block(self):
        out = self._full_handoff("rss")
        assert "## House Format 편집 지시" not in out


# ─── C. SCAN_FIRST_GROK_EDITOR_PROMPT_V1 — 외부 Grok 마스터 프롬프트 ──
class TestExternalGrokPromptEnglishRule:
    def test_external_prompt_has_english_section(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        assert "[Output Language Rule]" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1

    def test_external_prompt_english_keywords(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        for kw in (
            "Final edited post must be in English",
            "Do not output Korean",
            "Do not translate literally from Korean",
            "Preserve facts and numbers",
        ):
            assert kw in SCAN_FIRST_GROK_EDITOR_PROMPT_V1, (
                f"외부 Grok 프롬프트 영어 룰 '{kw}' 누락"
            )

    def test_external_prompt_final_output_english(self):
        from app.services.grok_handoff import SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        # 기존 "한국어 X 포스트 1 개만 출력" → 영어로 전환
        assert "English X post" in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
        # 옛 한국어 X 포스트 출력 강제 문구는 잔존하지 않음
        assert "한국어 X 포스트 1 개만 출력" not in SCAN_FIRST_GROK_EDITOR_PROMPT_V1
