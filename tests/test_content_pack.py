"""
콘텐츠 팩 언어 기본값 테스트
============================
한국어 기본 / 영어 명시 시만 영어 규칙을 검증합니다.
"""

from app.services.content_pack import _get_system_prompt, _mock_pack
from app.models.content_request import ContentRequest


class TestContentPackLanguageDefault:
    """콘텐츠 팩 생성 경로에서 한국어가 기본인지 회귀 검증."""

    def test_default_prompt_is_korean(self):
        """language='ko' → 시스템 프롬프트가 한국어."""
        prompt = _get_system_prompt("ko")
        assert "한국어" in prompt
        assert "English-language" not in prompt

    def test_english_prompt_when_explicit(self):
        """language='en' → 시스템 프롬프트가 영어."""
        prompt = _get_system_prompt("en")
        assert "English-language" in prompt

    def test_mock_pack_default_korean(self):
        """language 미지정(기본 ko) → Mock 팩 한국어."""
        req = ContentRequest(raw_text="테스트", source_type="raw_text")
        pack = _mock_pack(req)
        assert "데이터 기반" in pack.main_posts[0]
        assert "Mock 모드" in pack.why_it_matters
        # 영어 잔존 없음
        assert "data-driven" not in pack.main_posts[0]

    def test_mock_pack_english_when_explicit(self):
        """language='en' → Mock 팩 영어."""
        req = ContentRequest(raw_text="test", source_type="raw_text", language="en")
        pack = _mock_pack(req)
        assert "data-driven" in pack.main_posts[0]
        assert "Mock mode" in pack.why_it_matters

    def test_content_request_default_language_is_ko(self):
        """ContentRequest.language 기본값이 'ko'."""
        req = ContentRequest(raw_text="기본", source_type="raw_text")
        assert req.language == "ko"

    def test_prompt_variants_are_different(self):
        """ko/en 프롬프트가 실제로 다른 내용."""
        ko = _get_system_prompt("ko")
        en = _get_system_prompt("en")
        assert ko != en


class TestContentPackPromptQuality:
    """프롬프트 품질 고도화 — few-shot 예시 포함 여부 회귀 검증."""

    def test_ko_prompt_has_good_hook_examples(self):
        """한국어 프롬프트에 좋은 훅 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "12년 만 최고 금리, 문제는 물가보다 가계부채다" in prompt
        assert "삼성전자 영업이익 10배 반등" in prompt

    def test_ko_prompt_has_bad_hook_examples(self):
        """한국어 프롬프트에 나쁜 훅 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "한국 기준금리 3.50%, 12년 만 최고" in prompt
        assert "사실 나열" in prompt

    def test_ko_prompt_has_good_why_examples(self):
        """한국어 프롬프트에 좋은 why_it_matters 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "원화와 외국인 자금 흐름이 먼저 흔들린다" in prompt

    def test_ko_prompt_has_bad_why_examples(self):
        """한국어 프롬프트에 나쁜 why_it_matters 예시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "이는 경제에 중요한 의미를 가진다" in prompt

    def test_ko_prompt_has_reply_tone_guidance(self):
        """한국어 프롬프트에 댓글 대화체 지시가 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "대화체" in prompt
        assert "보고서 문체 금지" in prompt

    def test_ko_prompt_has_quote_post_types(self):
        """한국어 프롬프트에 인용 포스트 3유형이 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "반론형" in prompt
        assert "시장영향형" in prompt
        assert "해외설명형" in prompt

    def test_ko_prompt_has_short_version_rules(self):
        """한국어 프롬프트에 짧은 버전 규칙이 포함되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "단순 축약하지 마라" in prompt
        assert "독립 훅" in prompt


class TestContentPackHouseStyle:
    """하우스 스타일 골든 룰 + 시리즈 라벨 + 자기 검증 회귀 검증."""

    def test_ko_prompt_has_golden_rules(self):
        """골든 룰 7개 항목이 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "하우스 스타일 골든 룰" in prompt
        assert "해석 > 사실" in prompt
        assert "구체 > 추상" in prompt
        assert "대화체 > 보고서체" in prompt
        assert "credibility > virality" in prompt
        assert "다음에 볼 것" in prompt
        assert "기사 제목 재진술 금지" in prompt
        assert "낡은 수치 단정 금지" in prompt

    def test_ko_prompt_has_series_labels(self):
        """시리즈 라벨이 한국어로 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "한줄:" in prompt
        assert "한국 밖에서 보면:" in prompt

    def test_ko_prompt_no_english_series_label(self):
        """영어 시리즈 라벨이 좋은 예시에 없다."""
        prompt = _get_system_prompt("ko")
        # "Korea in One Line:" 은 나쁜 예시에만 존재해야 함
        good_section = prompt.split("✅ 좋은 예:")[1].split("❌")[0] if "✅ 좋은 예:" in prompt else ""
        # short_version 좋은 예시 영역에 영어 라벨 없어야 함
        assert "Korea in One Line:" not in good_section.split("═══")[0]

    def test_ko_prompt_has_self_verification(self):
        """main_posts 자기 검증 규칙이 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "자기 검증" in prompt
        assert "기사 제목과 구분이 안 되면" in prompt
        assert '"그래서?"' in prompt

    def test_ko_prompt_has_why_three_elements(self):
        """why_it_matters 3요소 필수 규칙이 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "직접 영향받는 대상" in prompt
        assert "해외 독자가 봐야 하는 이유" in prompt
        assert "다음에 볼 지표" in prompt
        assert "3요소 중 하나라도 빠지면 다시 써라" in prompt

    def test_ko_prompt_has_reply_data_rule(self):
        """reply_drafts에 데이터 필수 규칙이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "데이터 규칙" in prompt

    def test_ko_prompt_has_reply_anti_patterns(self):
        """reply_drafts에 당위형 금지가 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "당위형" in prompt

    def test_ko_prompt_has_quote_independence_rule(self):
        """인용 포스트 독립 가치 규칙이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "이 인용만으로 가치를 느껴야" in prompt

    def test_ko_prompt_account_goal(self):
        """계정 목표가 뉴스 요약이 아닌 이해 기반임이 명시되어 있다."""
        prompt = _get_system_prompt("ko")
        assert "뉴스 요약 계정이 아님" in prompt

    def test_ko_prompt_main_posts_axis_rule(self):
        """main_posts 3개가 서로 다른 핵심축을 가져야 한다는 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "서로 다른 핵심축" in prompt

    def test_ko_prompt_reply_length_rule(self):
        """reply_drafts가 1~2문장 답글형을 강제한다."""
        prompt = _get_system_prompt("ko")
        assert "1~2문장" in prompt
        assert "칼럼 축약이 아니다" in prompt

    def test_ko_prompt_quote_overlap_check(self):
        """인용 포스트에 겹침 체크 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "겹침 체크" in prompt

    def test_ko_prompt_no_stale_data_rule(self):
        """낡은 수치 단정 금지 규칙이 골든 룰에 있다."""
        prompt = _get_system_prompt("ko")
        assert "현재 시점과 어긋나는 수치는 신뢰를 깎는다" in prompt
