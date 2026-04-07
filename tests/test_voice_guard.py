"""
VoiceGuard 테스트
=================
AI 어투 패턴 감지 + 엣지 케이스 + Layer 2 안전성 검증.
"""

import pytest
from app.services.voice_guard import check_voice, check_pack_voices


class TestCheckVoiceCleanText:
    def test_clean_text_returns_empty(self):
        text = "Household debt just hit 105% of GDP. That's not a typo. Follow to track."
        assert check_voice(text) == []

    def test_empty_string_returns_empty(self):
        assert check_voice("") == []

    def test_very_short_text_returns_empty(self):
        assert check_voice("Hi") == []

    def test_none_equivalent_empty(self):
        # 빈 문자열 처리
        result = check_voice("   ")
        assert result == []


class TestCheckVoiceForbiddenWords:
    def test_detects_furthermore(self):
        text = "Furthermore, the data shows a clear trend."
        warnings = check_voice(text)
        assert any("Furthermore" in w for w in warnings)

    def test_detects_moreover(self):
        text = "Moreover, this signals a structural shift."
        warnings = check_voice(text)
        assert any("Moreover" in w for w in warnings)

    def test_detects_notably(self):
        text = "Notably, the BOK raised rates unexpectedly."
        warnings = check_voice(text)
        assert any("Notably" in w for w in warnings)

    def test_detects_in_conclusion(self):
        text = "In conclusion, Korea's export sector is under pressure."
        warnings = check_voice(text)
        assert any("In conclusion" in w for w in warnings)

    def test_detects_worth_noting(self):
        text = "It's worth noting that the won weakened 3% this week."
        warnings = check_voice(text)
        assert any("worth noting" in w for w in warnings)

    def test_detects_it_is_important(self):
        text = "It is important to understand the structural context here."
        warnings = check_voice(text)
        assert any("important to" in w for w in warnings)

    def test_detects_delve_into(self):
        text = "Let's delve into the reasons behind this shift."
        warnings = check_voice(text)
        assert any("delve into" in w for w in warnings)

    def test_detects_navigate(self):
        text = "Companies navigate an uncertain regulatory environment."
        warnings = check_voice(text)
        assert any("navigate" in w for w in warnings)

    def test_detects_unprecedented(self):
        text = "This is an unprecedented move by the central bank."
        warnings = check_voice(text)
        assert any("unprecedented" in w for w in warnings)

    def test_detects_game_changer(self):
        text = "The new policy is a game-changer for the sector."
        warnings = check_voice(text)
        assert any("game" in w.lower() for w in warnings)

    def test_detects_this_underscores(self):
        text = "This underscores the importance of fiscal discipline."
        warnings = check_voice(text)
        assert any("underscores" in w for w in warnings)

    def test_detects_forbidden_start_south_korea(self):
        text = "South Korea's economy contracted last quarter."
        warnings = check_voice(text)
        assert any("South Korea" in w or "Korea" in w for w in warnings)


class TestCheckVoiceCaseInsensitive:
    def test_uppercase_furthermore(self):
        result = check_voice("FURTHERMORE this matters.")
        assert any("Furthermore" in w for w in result)

    def test_mixed_case_delve(self):
        result = check_voice("We should Delve Into these issues.")
        assert any("delve" in w.lower() for w in result)


class TestCheckVoiceMultiplePatterns:
    def test_multiple_patterns_in_one_text(self):
        text = (
            "Furthermore, it's worth noting that this is unprecedented. "
            "In conclusion, we must navigate the situation."
        )
        warnings = check_voice(text)
        assert len(warnings) >= 3

    def test_each_pattern_counted_once(self):
        # 같은 패턴이 두 번 나와도 경고는 하나
        text = "Furthermore this and furthermore that."
        warnings = check_voice(text)
        furthermore_warnings = [w for w in warnings if "Furthermore" in w]
        assert len(furthermore_warnings) == 1


class TestCheckPackVoices:
    def test_empty_list_returns_empty(self):
        assert check_pack_voices([]) == []

    def test_deduplicates_same_warning_across_posts(self):
        posts = [
            "Furthermore, the data is clear.",
            "Furthermore, we see a pattern.",
        ]
        warnings = check_pack_voices(posts)
        furthermore_warnings = [w for w in warnings if "Furthermore" in w]
        assert len(furthermore_warnings) == 1

    def test_different_warnings_from_different_posts(self):
        posts = [
            "Furthermore, the data is clear.",
            "In conclusion, this matters.",
        ]
        warnings = check_pack_voices(posts)
        assert len(warnings) == 2

    def test_clean_posts_return_empty(self):
        posts = [
            "Household debt hit 105% of GDP.",
            "The BOK raised rates 25bps. Follow to track.",
        ]
        assert check_pack_voices(posts) == []

    def test_single_warning_per_unique_pattern(self):
        posts = [
            "Moreover this, moreover that.",
            "Furthermore this matters.",
            "Moreover it is important to note.",
        ]
        warnings = check_pack_voices(posts)
        # 'Moreover' should appear once, 'Furthermore' once, 'important to' once
        assert any("Moreover" in w for w in warnings)
        assert any("Furthermore" in w for w in warnings)


class TestVoiceGuardReturnFormat:
    def test_warnings_start_with_emoji(self):
        text = "Furthermore, this is unprecedented."
        warnings = check_voice(text)
        for w in warnings:
            assert w.startswith("⚠️"), f"경고가 ⚠️로 시작해야 함: {w}"

    def test_warnings_are_strings(self):
        text = "In conclusion, it's worth noting the unprecedented shift."
        warnings = check_voice(text)
        assert all(isinstance(w, str) for w in warnings)
