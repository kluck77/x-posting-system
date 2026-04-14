"""
콘텐츠 팩 언어 기본값 테스트
============================
한국어 기본 / 영어 명시 시만 영어 규칙을 검증합니다.
"""

import json
import pytest

from app.services.content_pack import (
    _get_system_prompt, _mock_pack, _is_short_input, _classify_topic,
    FactSheet, ContentPack, extract_fact_sheet, check_density, TOPIC_MIN_FIELDS,
    _audit_numeric_safety,
    _STRONG_ASSERTION_RE, _CONCRETE_NUM_RE, _STOCK_NAME_RE, _PERCENT_RE,
    CandidateCard, FinalPost, ThesisCard,
    _CANDIDATE_PROMPT_KO, _FINALIZE_PROMPT_KO,
    _parse_candidate_card, _parse_final_post,
    _validate_final_post, _BANNED_ENDINGS, _TONE_SOFTENERS,
    _decide_certainty_ceiling, _VERIFICATION_FAIL_KEYWORDS,
    _CERTAINTY_RANK,
    _should_invoke_claude_review, _CLAUDE_REVIEW_PROMPT,
    _SENSITIVE_TOPICS, _WEAK_PATTERNS,
    _FACT_NARRATION_STARTS,
    _OPINION_PATTERNS,
    # Phase 2: Gemini 대안 의견 카드 + Gemini thesis 생성
    _GEMINI_OPINION_PROMPT, GeminiOpinionCard,
    _should_invoke_extended_review, _EXTENDED_REVIEW_TOPICS,
    _GEMINI_THESIS_PROMPT,
    # Phase 3: Grok X 감각 심사 (구조화 버전)
    _GROK_EVAL_PROMPT, GrokEvalCard, _GROK_VALID_FAIL_TAGS,
    _noop_async, _log_draft_comparison,
    # 7대 검증 규칙
    _validate_thesis_similarity, _validate_headline_restatement,
    _validate_dead_patterns, _validate_structure_detection,
    _validate_reader_stake, _validate_grok_fail_tags_gating,
    _validate_thesis_preservation, _run_all_validations,
)
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
        """골든 룰 9개 항목이 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "하우스 스타일 골든 룰" in prompt
        assert "해석 > 사실" in prompt
        assert "구체 > 추상" in prompt
        assert "대화체 > 보고서체" in prompt
        assert "credibility > virality" in prompt
        assert "다음에 볼 것" in prompt
        assert "기사 제목 재진술 금지" in prompt
        assert "숫자 사용 절대 규칙" in prompt
        assert "강한 단정 약화 규칙" in prompt
        assert "메인 3축 분리" in prompt

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
        """숫자 사용 절대 규칙이 골든 룰에 있다."""
        prompt = _get_system_prompt("ko")
        assert "틀린 수치 1개" in prompt
        assert "절대 금지" in prompt

    def test_ko_prompt_data_backed_assertion_rule(self):
        """강한 단정 약화 규칙이 골든 룰에 있다."""
        prompt = _get_system_prompt("ko")
        assert "강한 단정 약화 규칙" in prompt
        assert "지역/대상" in prompt       # STEP 1에 유지
        assert "기간/비교 시점" in prompt   # STEP 1에 유지
        assert "수치/변화폭" in prompt     # STEP 1에 유지
        assert "반드시 약화" in prompt     # 룰 8 본문

    def test_ko_prompt_has_generation_steps(self):
        """3단계 생성 절차가 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "STEP 1" in prompt
        assert "STEP 2" in prompt
        assert "STEP 3" in prompt
        assert "입력 데이터 점검" in prompt
        assert "핵심축 3개 선택" in prompt

    def test_ko_prompt_has_qa_checklist(self):
        """최종 QA 체크리스트 12항목이 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "최종 QA 체크리스트" in prompt
        assert "제목 재진술 아닌가" in prompt
        assert "데이터 충족" in prompt
        assert "메인 축 분리" in prompt
        assert "댓글 답글형" in prompt
        assert "인용 독립" in prompt
        assert "추상어 과다" in prompt
        assert "why_it_matters 3요소" in prompt
        assert "시리즈 라벨 과다" in prompt
        assert "첫 2문장 핵심축" in prompt
        assert "포스트당 축 단일" in prompt
        assert "3개 이상 실패하면 전체 재작성" in prompt

    def test_ko_prompt_has_core_values(self):
        """계정 핵심 가치 3개가 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "혼란 속의 명료함" in prompt
        assert "안티 하이프 현실주의" in prompt
        assert "조기 신호 감각" in prompt

    def test_ko_prompt_has_universal_axis_frame(self):
        """범용 축 프레임이 STEP 2에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "구조/원인 축" in prompt
        assert "신호/지표 축" in prompt
        assert "글로벌 맥락/투자 의미 축" in prompt

    def test_ko_prompt_data_gate_includes_crypto_policy(self):
        """데이터 게이트가 크립토·정책도 커버한다."""
        prompt = _get_system_prompt("ko")
        assert "정책·크립토" in prompt

    def test_ko_prompt_has_axis_lead_rule(self):
        """첫 2문장 핵심축 선행 규칙이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "첫 2문장 안에" in prompt
        assert "핵심축" in prompt
        assert "부차 디테일" in prompt

    def test_ko_prompt_has_single_axis_rule(self):
        """포스트당 핵심축 단일화 규칙이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "한 포스트 = 핵심축 1개" in prompt
        assert "축 혼합 금지" in prompt

    def test_ko_prompt_has_market_variable_priority(self):
        """지정학·정책 글에서 시장 변수 우선 규칙이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "시장 참가자가 먼저 볼 변수" in prompt
        assert "유가" in prompt
        assert "해운·보험" in prompt
        assert "수입물가" in prompt


class TestFactSheetExtraction:
    """규칙 기반 팩트 시트 추출 테스트."""

    def test_real_estate_topic_classification(self):
        """부동산 키워드 2개 이상이면 부동산으로 분류."""
        text = "서울 아파트 전세 가격이 3개월 연속 하락했다."
        sheet = extract_fact_sheet(text)
        assert sheet.topic == "부동산"

    def test_crypto_topic_classification(self):
        """크립토 키워드 2개 이상이면 크립토로 분류."""
        text = "업비트 비트코인 거래량이 40% 감소했다."
        sheet = extract_fact_sheet(text)
        assert sheet.topic == "크립토"

    def test_single_keyword_classifies(self):
        """키워드 1개만으로도 주제 분류."""
        assert _classify_topic("서울 부동산") == "부동산"
        assert _classify_topic("업비트 점유율") == "크립토"
        assert _classify_topic("한국 금리") == "금리"

    def test_unknown_topic_fallback(self):
        """매칭 키워드 부족 시 기타로 분류."""
        text = "오늘 날씨가 좋아서 산책을 했다."
        sheet = extract_fact_sheet(text)
        assert sheet.topic == "기타"

    def test_figures_extraction_percentage(self):
        """퍼센트 수치 추출."""
        text = "전월비 2.3% 하락, 거래량은 15% 감소"
        sheet = extract_fact_sheet(text)
        assert any("2.3%" in f or "2.3 %" in f for f in sheet.figures)

    def test_figures_extraction_korean_amount(self):
        """한국식 금액 추출."""
        text = "부동산 시장에서 거래액이 350억원을 기록했다."
        sheet = extract_fact_sheet(text)
        assert any("350억" in f for f in sheet.figures)

    def test_figures_must_contain_numbers(self):
        """figures에 숫자가 없는 추상 문구는 포함되지 않는다."""
        text = "시장이 위축되고 거래량이 감소하는 추세다."
        sheet = extract_fact_sheet(text)
        assert all(any(c.isdigit() for c in f) for f in sheet.figures)

    def test_timeframe_extraction(self):
        """날짜/기간 표현 추출."""
        text = "2024년 3월 기준 전월비 하락세가 이어졌다."
        sheet = extract_fact_sheet(text)
        assert "2024년 3월" in sheet.timeframe

    def test_entities_extraction_known(self):
        """고유명사 사전 매칭."""
        text = "한국은행이 기준금리를 동결하고 삼성전자 실적을 주시하고 있다."
        sheet = extract_fact_sheet(text)
        assert "한국은행" in sheet.entities
        assert "삼성전자" in sheet.entities

    def test_key_facts_contain_numbers(self):
        """key_facts는 숫자 포함 문장만."""
        text = "서울 아파트 매매가 2.3% 하락. 시장 분위기가 좋지 않다. 거래량은 1500건이다."
        sheet = extract_fact_sheet(text)
        for fact in sheet.key_facts:
            assert any(c.isdigit() for c in fact)

    def test_empty_input(self):
        """빈 입력에도 크래시 없이 빈 시트 반환."""
        sheet = extract_fact_sheet("")
        assert sheet.topic == "기타"
        assert sheet.figures == []
        assert sheet.entities == []


class TestDensityCheck:
    """밀도 검증 테스트."""

    def test_real_estate_all_fields(self):
        """부동산 3필드 모두 충족 → 통과."""
        sheet = FactSheet(
            topic="부동산",
            entities=["서울"],
            figures=["전월비 -2.3%"],
            timeframe="2024년 3월",
        )
        passed, missing = check_density(sheet)
        assert passed is True
        assert missing == []
        assert sheet.data_density_score == 3

    def test_real_estate_two_fields(self):
        """부동산 2필드 충족 → 통과."""
        sheet = FactSheet(
            topic="부동산",
            entities=["강남"],
            figures=["3.5%"],
            timeframe="",
        )
        passed, missing = check_density(sheet)
        assert passed is True

    def test_real_estate_insufficient(self):
        """부동산 0~1필드 → 차단."""
        sheet = FactSheet(topic="부동산", entities=[], figures=[], timeframe="")
        passed, missing = check_density(sheet)
        assert passed is False
        assert len(missing) == 3

    def test_crypto_sufficient(self):
        """크립토 3필드 충족 → 통과."""
        sheet = FactSheet(
            topic="크립토",
            entities=["업비트"],
            figures=["40%"],
            key_facts=["업비트 거래량 40% 급감"],
        )
        passed, missing = check_density(sheet)
        assert passed is True

    def test_crypto_insufficient(self):
        """크립토 0필드 → 차단."""
        sheet = FactSheet(topic="크립토", entities=[], figures=[], key_facts=[])
        passed, missing = check_density(sheet)
        assert passed is False

    def test_figures_without_numbers_fail(self):
        """figures에 숫자 없는 값만 있으면 미충족 처리."""
        sheet = FactSheet(
            topic="부동산",
            entities=["서울"],
            figures=["하락세", "위축"],
            timeframe="2024년",
        )
        passed, missing = check_density(sheet)
        assert "figures" in missing

    def test_timeframe_without_numbers_fail(self):
        """timeframe에 숫자 없으면 미충족 처리."""
        sheet = FactSheet(
            topic="금리",
            entities=["한국은행"],
            figures=["3.5%"],
            timeframe="최근",
        )
        passed, missing = check_density(sheet)
        assert "timeframe" in missing

    def test_unknown_topic_uses_fallback(self):
        """알 수 없는 주제는 기타 기준 적용."""
        sheet = FactSheet(topic="알수없음", key_facts=["사실1"], entities=["대상1"])
        passed, missing = check_density(sheet)
        assert passed is True

    def test_content_pack_insufficient_fields(self):
        """ContentPack insufficient_data 필드 동작."""
        pack = ContentPack(
            insufficient_data=True,
            missing_fields=["figures", "timeframe"],
        )
        assert pack.insufficient_data is True
        assert "figures" in pack.missing_fields
        assert len(pack.missing_fields) == 2

    def test_content_pack_default_not_insufficient(self):
        """기본 ContentPack은 insufficient_data=False."""
        pack = ContentPack()
        assert pack.insufficient_data is False
        assert pack.missing_fields == []


class TestFactSheetIntegration:
    """팩트 시트 → 밀도 검증 통합 테스트."""

    def test_data_rich_real_estate_passes(self):
        """데이터 풍부한 부동산 기사 → 통과."""
        text = (
            "서울 강남구 아파트 매매가격이 2024년 3월 기준 "
            "전월비 0.5% 하락했다. 거래량은 1,200건으로 전년 동기 대비 30% 감소."
        )
        sheet = extract_fact_sheet(text)
        passed, missing = check_density(sheet)
        assert passed is True
        assert sheet.topic == "부동산"
        assert len(sheet.figures) >= 2

    def test_vague_crypto_blocked(self):
        """데이터 없는 크립토 분위기문 → 차단."""
        text = (
            "최근 크립토 가격이 급락하고 시장의 신뢰도가 하락하고 있다. "
            "투자자들의 회의감이 커지고 있으며 거래량도 줄어드는 추세다."
        )
        sheet = extract_fact_sheet(text)
        passed, missing = check_density(sheet)
        assert passed is False

    def test_data_rich_crypto_passes(self):
        """데이터 있는 크립토 기사 → 통과."""
        text = (
            "업비트 비트코인 거래량이 2024년 3월 기준 "
            "일평균 1조2000억원에서 7000억원으로 40% 감소했다."
        )
        sheet = extract_fact_sheet(text)
        passed, missing = check_density(sheet)
        assert passed is True
        assert "업비트" in sheet.entities

    def test_vague_policy_blocked(self):
        """구체 데이터 없는 정책 기사 → 차단."""
        text = "정부가 새로운 규제를 검토하고 있다. 시장에 큰 영향을 줄 것으로 보인다."
        sheet = extract_fact_sheet(text)
        passed, missing = check_density(sheet)
        assert passed is False


class TestInputTypeSplit:
    """입력 유형 분리 (기사형 vs 탐색형) 테스트."""

    def test_short_input_detection(self):
        """100자 이하는 짧은 입력."""
        assert _is_short_input("서울 부동산") is True
        assert _is_short_input("한국 금리 전망") is True
        assert _is_short_input("업비트 점유율") is True

    def test_long_input_detection(self):
        """100자 초과는 기사형 입력."""
        long_text = "서울 강남구 아파트 매매가격이 2024년 3월 기준 전월비 0.5% 하락했다. " * 3
        assert _is_short_input(long_text) is False

    def test_short_input_topic_classification(self):
        """짧은 입력도 주제 분류가 정확해야 한다."""
        sheet = extract_fact_sheet("서울 부동산")
        assert sheet.topic == "부동산"
        assert "서울" in sheet.entities

    def test_short_crypto_topic(self):
        """짧은 크립토 입력 주제 분류."""
        sheet = extract_fact_sheet("업비트 점유율")
        assert sheet.topic == "크립토"
        assert "업비트" in sheet.entities

    def test_short_rate_topic(self):
        """짧은 금리 입력 주제 분류."""
        sheet = extract_fact_sheet("한국 금리")
        assert sheet.topic == "금리"

    def test_short_input_not_blocked_by_density(self):
        """짧은 입력은 밀도 검증에 실패해도 차단 대상이 아니다."""
        sheet = extract_fact_sheet("서울 부동산")
        passed, missing = check_density(sheet)
        # 밀도 검증은 실패하지만, generate_content_pack에서 short_input이면 우회
        assert passed is False  # 밀도는 부족
        # 하지만 _is_short_input이 True이므로 게이트 우회됨

    def test_long_vague_still_blocked(self):
        """긴 분위기문은 여전히 차단."""
        text = (
            "최근 크립토 시장의 불안정성이 커지고 있다. "
            "투자자들의 심리가 위축되면서 시장 전반에 걸쳐 "
            "불확실성이 확대되는 양상이다. "
            "전문가들은 당분간 이런 추세가 이어질 것으로 전망하고 있다."
        )
        assert _is_short_input(text) is False
        sheet = extract_fact_sheet(text)
        passed, _ = check_density(sheet)
        assert passed is False


class TestNumericSafetyAudit:
    """후처리 숫자 안전성 감사 테스트."""

    def test_ungrounded_number_flagged(self):
        """소스에 없는 수치가 생성되면 경고."""
        pack = ContentPack(
            main_posts=["환율 1493.9원 돌파, 위기 신호"],
            short_version="",
            reply_drafts=[],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])  # 소스에 수치 없음
        _audit_numeric_safety(pack, sheet)
        assert any("숫자 안전" in w for w in pack.style_warnings)

    def test_grounded_number_ok(self):
        """소스에 있는 수치는 경고 안 함."""
        pack = ContentPack(
            main_posts=["환율 1493.9원 돌파"],
            short_version="",
            reply_drafts=[],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=["1493.9원"])
        _audit_numeric_safety(pack, sheet)
        assert not any("숫자 안전" in w for w in pack.style_warnings)

    def test_strong_assertion_flagged(self):
        """급증/급등/폭락 등 강한 단정 표현이 경고됨."""
        pack = ContentPack(
            main_posts=["강남 아파트 수요 급증, 거래 활발"],
            short_version="",
            reply_drafts=[],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)

    def test_no_assertion_no_warning(self):
        """강한 단정 없으면 경고 없음."""
        pack = ContentPack(
            main_posts=["강남 아파트 거래 움직임, 관심 증가"],
            short_version="",
            reply_drafts=[],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert not any("단정 강도" in w for w in pack.style_warnings)

    def test_reply_ungrounded_number_caught(self):
        """댓글에 있는 미확인 수치도 감지."""
        pack = ContentPack(
            main_posts=["분석글"],
            short_version="",
            reply_drafts=["달러인덱스 99.085 기준으로 보면"],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("숫자 안전" in w for w in pack.style_warnings)

    def test_percentage_from_source_ok(self):
        """소스에 있는 퍼센트는 통과."""
        pack = ContentPack(
            main_posts=["전월 대비 3.2% 하락"],
            short_version="",
            reply_drafts=[],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=["전월비 3.2%"])
        _audit_numeric_safety(pack, sheet)
        assert not any("숫자 안전" in w for w in pack.style_warnings)


class TestNumericSafetyPromptRules:
    """프롬프트에 숫자 안전성/단정 강도 규칙이 포함되어 있는지."""

    def test_critical_numeric_rule(self):
        """골든 룰 7에 CRITICAL 마크가 있다."""
        prompt = _get_system_prompt("ko")
        assert "숫자 사용 절대 규칙 (CRITICAL)" in prompt

    def test_assertion_weakening_table(self):
        """골든 룰 8에 약화 표현 매핑이 있다."""
        prompt = _get_system_prompt("ko")
        assert "급증/급등 → 증가 조짐/오름세" in prompt
        assert "급락/급감 → 하락 압력/약세 흐름" in prompt

    def test_reply_conservatism_rule(self):
        """골든 룰 10에 댓글/인용 보수성 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "댓글·인용 보수성 규칙" in prompt
        assert "본문보다 더 보수적" in prompt

    def test_qa_numeric_source_check(self):
        """QA 체크리스트에 수치 출처 확인이 있다."""
        prompt = _get_system_prompt("ko")
        assert "소스 원문에 실제 있는가" in prompt

    def test_qa_reply_numeric_check(self):
        """QA 체크리스트에 댓글/인용 수치 항목이 있다."""
        prompt = _get_system_prompt("ko")
        assert "댓글·인용 수치 보수성" in prompt

    def test_exploratory_no_number_rule(self):
        """탐색형 프롬프트에 수치 생성 금지 규칙이 있다."""
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "소스에 없는 숫자를 만들지 마라" in source


class TestTopicModePrompt:
    """탐색형(주제형) 입력 전용 프롬프트 규칙 테스트."""

    def test_topic_mode_axis_split_in_prompt(self):
        """탐색형 축 분리 규칙(A=어디/B=왜/C=뭘 봐야)이 user_prompt에 삽입되는지 간접 검증."""
        # 탐색형 프롬프트 블록이 content_pack.py에 존재하는지 확인
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "지금 어디가 움직이는가" in source
        assert "왜 그런가" in source
        assert "뭘 봐야 하나" in source

    def test_topic_mode_subregion_rule(self):
        """탐색형에서 하위 지역/변수 구체화 규칙이 존재하는지."""
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "강남" in source
        assert "마포·성동" in source or "마포" in source
        assert "하위로 내려가라" in source

    def test_topic_mode_reply_rules(self):
        """탐색형 댓글 규칙: 질문형/반응형, 요약 반복 금지."""
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "질문형/반응형" in source
        assert "요약 반복 금지" in source

    def test_topic_mode_quote_perspective_split(self):
        """탐색형 인용 규칙: 시장/실수요자/해외독자 관점 분리."""
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "시장 관점" in source
        assert "실수요자 관점" in source
        assert "해외독자 관점" in source

    def test_topic_mode_why_concrete(self):
        """탐색형 why_it_matters: 추상 금지, 구체 파급 경로 필수."""
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "구체 파급 경로" in source
        assert "추적할 지표" in source

    def test_topic_mode_generalism_banned(self):
        """탐색형에서 일반론 금지 규칙이 명시되어 있는지."""
        import inspect
        from app.services.content_pack import generate_content_pack
        source = inspect.getsource(generate_content_pack)
        assert "일반론" in source
        assert "상위 주제" in source


class TestPoliticalMilitaryPromptRules:
    """정치·외교·군사 주제 표현 강도 규칙이 프롬프트에 포함되어 있는지."""

    def test_political_military_rule_exists(self):
        """골든 룰 11에 정치·외교·군사 표현 강도 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "정치·외교·군사 주제 표현 강도 규칙" in prompt

    def test_weakening_table_has_examples(self):
        """고강도 → 약화 매핑 예시가 있다."""
        prompt = _get_system_prompt("ko")
        assert "청구서를 내밀었다 → 비용 분담 압박을 시사했다" in prompt
        assert "부풀렸다 → 실제보다 크게 언급했다" in prompt
        assert "직격했다 → 강경한 입장을 밝혔다" in prompt
        assert "봉쇄를 시행 → 봉쇄 리스크가 부상했다" in prompt

    def test_source_verification_for_military(self):
        """군사·봉쇄 관련 단정에 출처 확인 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "군사·봉쇄·시행·공식 발표 문장은 출처가 명확할 때만" in prompt

    def test_combat_rhetoric_tone_down(self):
        """전투적 수사 재서술 톤 다운 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "전투적 수사" in prompt
        assert "톤을 낮춰라" in prompt

    def test_density_separation_in_rule(self):
        """갈등 요소 분리 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "갈등 요소" in prompt
        assert "핵심축 1개를 고르고" in prompt

    def test_qa_political_military_check(self):
        """QA 체크리스트에 정치/군사 표현 강도 항목이 있다."""
        prompt = _get_system_prompt("ko")
        assert "정치·외교·군사 표현 강도" in prompt


class TestPoliticalAssertionAudit:
    """정치/군사 고강도 표현이 _audit_numeric_safety에서 감지되는지."""

    def test_직격_flagged(self):
        pack = ContentPack(
            main_posts=["트럼프가 한국을 직격했다"],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)

    def test_부풀렸_flagged(self):
        pack = ContentPack(
            main_posts=["병력 수치를 부풀렸다"],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)

    def test_공식_시행_flagged(self):
        pack = ContentPack(
            main_posts=["봉쇄를 공식 시행했다"],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)

    def test_weakened_expression_ok(self):
        """약화된 표현은 경고 안 함."""
        pack = ContentPack(
            main_posts=["비용 분담 압박을 시사했다. 봉쇄 리스크가 부상했다."],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert not any("단정 강도" in w for w in pack.style_warnings)

    def test_선언했_flagged(self):
        pack = ContentPack(
            main_posts=["트럼프가 봉쇄를 선언했다"],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)

    def test_불가피_flagged(self):
        pack = ContentPack(
            main_posts=["유가 급등은 불가피하다"],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)

    def test_직격탄_flagged(self):
        pack = ContentPack(
            main_posts=["한국 에너지 안보에 직격탄이 된다"],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("단정 강도" in w for w in pack.style_warnings)


class TestConfirmThenHedgeDetection:
    """확정형+단서 자기모순 안티패턴 탐지 테스트."""

    def test_선언_then_미확인(self):
        """'선언했다 ... 미확인' 패턴 감지."""
        pack = ContentPack(
            main_posts=["봉쇄를 선언했다. 실제 이행 여부는 미확인 상태다."],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("확정+단서 자기모순" in w for w in pack.style_warnings)

    def test_시행_then_확인필요(self):
        """'시행했다 ... 확인 필요' 패턴 감지."""
        pack = ContentPack(
            main_posts=["봉쇄를 시행했다. 다만 확인이 필요하다."],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("확정+단서 자기모순" in w for w in pack.style_warnings)

    def test_불가피_then_변수(self):
        """'불가피하다 ... 변수가 남' 패턴 감지."""
        pack = ContentPack(
            main_posts=["유가 급등은 불가피하다. 다만 변수가 남아있다."],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("확정+단서 자기모순" in w for w in pack.style_warnings)

    def test_safe_phrasing_no_warning(self):
        """올바른 표현 — 가능성 수준 + 단서 → 경고 없음."""
        pack = ContentPack(
            main_posts=["봉쇄 가능성이 부상했다. 실제 시행 여부는 미지수지만 시장은 반응한다."],
            short_version="", reply_drafts=[], quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert not any("확정+단서 자기모순" in w for w in pack.style_warnings)

    def test_확정형_in_reply_caught(self):
        """댓글에서도 확정+단서 패턴 감지."""
        pack = ContentPack(
            main_posts=["분석글"],
            short_version="",
            reply_drafts=["봉쇄를 선언했다. 확인은 필요하다."],
            quote_post_drafts=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("확정+단서 자기모순" in w for w in pack.style_warnings)


class TestUnverifiedFactPromptRules:
    """미확인 사안 확정형 금지 규칙이 프롬프트에 포함되어 있는지."""

    def test_rule_12_exists(self):
        prompt = _get_system_prompt("ko")
        assert "미확인 사안 확정형 금지" in prompt

    def test_confirm_then_hedge_banned(self):
        prompt = _get_system_prompt("ko")
        assert "확정형으로 먼저 쓰고, 뒤에서 단서로 수습하는 구조" in prompt

    def test_correct_order_specified(self):
        prompt = _get_system_prompt("ko")
        assert "가능성/긴장 고조/강경 발언" in prompt
        assert "확인 필요/이행 여부 미지수" in prompt

    def test_weakening_examples_for_unverified(self):
        prompt = _get_system_prompt("ko")
        assert "~을 선언했다 → ~가능성을 시사했다" in prompt
        assert "불가피하다 → 커질 수 있다" in prompt
        assert "직격탄이 된다 → 압박이 커질 수 있다" in prompt

    def test_core_principle(self):
        prompt = _get_system_prompt("ko")
        assert "미확인 사실 자체는 확정형으로 쓰지 않는다" in prompt

    def test_qa_15_exists(self):
        prompt = _get_system_prompt("ko")
        assert "확정+단서 자기모순" in prompt


class TestCrossFieldContradiction:
    """교차필드 모순 탐지: risk_flags 미확인 + 본문 확정형."""

    def test_결렬_with_상충_risk(self):
        """main_posts에 '결렬됐' + risk_flags에 '상충' → 교차필드 모순."""
        pack = ContentPack(
            main_posts=["첫 담판이 결렬됐다. 에너지 리스크 직격."],
            short_version="빈손 — 호르무즈 막힌 채",
            reply_drafts=[], quote_post_drafts=[],
            risk_flags=["결렬 여부 상충, 조건부 합의 보도도 있음"],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("교차필드 모순" in w for w in pack.style_warnings)

    def test_닫혀있다_with_미확인_risk(self):
        """'닫혀 있다' + '미확인' → 교차필드 모순."""
        pack = ContentPack(
            main_posts=["호르무즈는 여전히 닫혀 있다."],
            short_version="",
            reply_drafts=[], quote_post_drafts=[],
            risk_flags=["봉쇄 이행 여부 미확인, 추가 보도 확인 필요"],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("교차필드 모순" in w for w in pack.style_warnings)

    def test_빈손_with_불확실_risk(self):
        """'빈손' + '불확실' → 교차필드 모순."""
        pack = ContentPack(
            main_posts=["21시간 협상, 빈손."],
            short_version="",
            reply_drafts=[], quote_post_drafts=[],
            risk_flags=["협상 결과 불확실"],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert any("교차필드 모순" in w for w in pack.style_warnings)

    def test_safe_phrasing_with_uncertain_risk(self):
        """가능성 수준 표현 + 미확인 risk_flags → 경고 없음."""
        pack = ContentPack(
            main_posts=["협상 난항, 합의 불투명. 시장이 보는 건 유가다."],
            short_version="호르무즈 리스크가 풀리지 않았다",
            reply_drafts=[], quote_post_drafts=[],
            risk_flags=["결렬 여부 상충, 추가 보도 확인 필요"],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert not any("교차필드 모순" in w for w in pack.style_warnings)

    def test_no_uncertainty_in_risk_flags_ok(self):
        """risk_flags에 불확실성 없으면 확정형 OK (교차필드 경고 안 함)."""
        pack = ContentPack(
            main_posts=["협상이 결렬됐다. 공식 발표가 나왔다."],
            short_version="",
            reply_drafts=[], quote_post_drafts=[],
            risk_flags=["정치적 민감 — 게시 전 타이밍 확인"],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert not any("교차필드 모순" in w for w in pack.style_warnings)

    def test_empty_risk_flags_ok(self):
        """risk_flags 비어있으면 교차필드 체크 안 함."""
        pack = ContentPack(
            main_posts=["협상이 결렬됐다."],
            short_version="",
            reply_drafts=[], quote_post_drafts=[],
            risk_flags=[],
        )
        sheet = FactSheet(figures=[])
        _audit_numeric_safety(pack, sheet)
        assert not any("교차필드 모순" in w for w in pack.style_warnings)


class TestCrossFieldPromptRules:
    """교차필드 정합성 규칙이 프롬프트에 포함되어 있는지."""

    def test_step1_certainty_assessment(self):
        """STEP 1에 '사실 확정 수준' 판정 단계가 있다."""
        prompt = _get_system_prompt("ko")
        assert "사실 확정 수준" in prompt
        assert "확정" in prompt and "미확인" in prompt and "상충" in prompt

    def test_cross_field_consistency_rule(self):
        """골든룰 12에 교차필드 정합성 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "교차필드 정합성" in prompt
        assert "risk_flags와 본문의 확정 수준은 반드시 일치" in prompt

    def test_bad_good_examples(self):
        """교차필드 나쁜 예 / 좋은 예가 있다."""
        prompt = _get_system_prompt("ko")
        assert "협상 결렬, 빈손" in prompt  # 나쁜 예
        assert "협상 난항, 합의 불투명" in prompt  # 좋은 예

    def test_hook_unverified_examples(self):
        """훅에서 미확인 사안 처리 예시가 있다."""
        prompt = _get_system_prompt("ko")
        assert "합의 불투명" in prompt

    def test_weakening_결렬_닫혀_빈손(self):
        """결렬/닫혀 있다/빈손 약화 매핑이 있다."""
        prompt = _get_system_prompt("ko")
        assert "결렬됐다 → 난항을 겪고 있다" in prompt
        assert "닫혀 있다/막힌 채 → 차단 리스크가 지속되고 있다" in prompt
        assert "빈손 → 뚜렷한 성과 없이 마무리된 것으로 전해졌다" in prompt

    def test_qa_16_exists(self):
        """QA 체크리스트 16번 교차필드 정합성 항목이 있다."""
        prompt = _get_system_prompt("ko")
        assert "교차필드 정합성" in prompt


# ─── 시장·종목 밀도 규칙 테스트 ──────────────────────────────────────────────


class TestMarketDensityPromptRules:
    """골든룰 13 시장·종목 밀도 제한 규칙이 프롬프트에 반영됐는지 확인."""

    def test_golden_rule_13_exists(self):
        """골든룰 13이 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "시장·종목 포스트 밀도 제한 규칙" in prompt

    def test_density_limits_in_prompt(self):
        """포스트당 밀도 상한 (숫자 2, 종목 2, 퍼센트 2)이 명시."""
        prompt = _get_system_prompt("ko")
        assert "구체 숫자" in prompt and "최대 2개" in prompt
        assert "개별 종목명" in prompt
        assert "퍼센트" in prompt

    def test_weakening_map_in_prompt(self):
        """토해냈다/분수령 약화 매핑이 프롬프트에 있다."""
        prompt = _get_system_prompt("ko")
        assert "토해냈다 → 하락 전환했다" in prompt
        assert "분수령 → 변곡점 가능성" in prompt

    def test_one_core_connection_rule(self):
        """핵심 연결 1개 규칙이 프롬프트에 있다."""
        prompt = _get_system_prompt("ko")
        assert "핵심 시장 연결 1개" in prompt

    def test_market_more_conservative(self):
        """시장 글이 정치보다 더 보수적이어야 한다는 규칙."""
        prompt = _get_system_prompt("ko")
        assert "정치/외교 글보다 더 보수적" in prompt

    def test_qa_17_exists(self):
        """QA 체크리스트 17번 시장 밀도 항목이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "시장 밀도 상한" in prompt


class TestMarketAssertionRegex:
    """_STRONG_ASSERTION_RE에 시장 표현이 추가됐는지 확인."""

    def test_토해냈다_detected(self):
        assert _STRONG_ASSERTION_RE.search("외국인이 순매도를 토해냈다")

    def test_분수령_detected(self):
        assert _STRONG_ASSERTION_RE.search("이번 주가 분수령이 될 것이다")

    def test_직격탄_still_detected(self):
        assert _STRONG_ASSERTION_RE.search("유가 상승이 직격탄이 됐다")

    def test_normal_text_no_match(self):
        assert not _STRONG_ASSERTION_RE.search("시장이 조정 국면에 진입했다")


class TestDensityRegexes:
    """밀도 검사용 regex 단위 테스트."""

    def test_concrete_num_matches_dollar(self):
        assert _CONCRETE_NUM_RE.search("$100")
        assert _CONCRETE_NUM_RE.search("$ 115")

    def test_concrete_num_matches_won(self):
        assert _CONCRETE_NUM_RE.search("1500원")
        assert _CONCRETE_NUM_RE.search("3조 원")

    def test_concrete_num_matches_4digit(self):
        assert _CONCRETE_NUM_RE.search("WTI 1234")

    def test_concrete_num_no_match_small(self):
        """3자리 이하 단독 숫자는 매치하지 않는다."""
        assert not _CONCRETE_NUM_RE.search("3개")

    def test_percent_re(self):
        assert _PERCENT_RE.search("15%")
        assert _PERCENT_RE.search("3.2％")

    def test_stock_name_korean(self):
        assert _STOCK_NAME_RE.search("삼성전자")
        assert _STOCK_NAME_RE.search("대한항공")
        assert _STOCK_NAME_RE.search("현대건설")

    def test_stock_name_english_ticker(self):
        assert _STOCK_NAME_RE.search("WTI 가격")
        assert _STOCK_NAME_RE.search("KOSPI 하락")

    def test_stock_name_index(self):
        assert _STOCK_NAME_RE.search("코스피 지수")
        assert _STOCK_NAME_RE.search("나스닥 반등")


class TestMarketDensityAudit:
    """_audit_numeric_safety check 5 — 포스트별 밀도 초과 경고 테스트."""

    def _make_pack(self, main_posts):
        return ContentPack(
            main_posts=main_posts,
            short_version="테스트 숏버전",
            reply_drafts=[],
            quote_post_drafts=[],
            thread_option=None,
            risk_flags=[],
            topic_tags=["시장"],
            why_it_matters="테스트",
            style_warnings=[],
        )

    def _make_fs(self):
        return FactSheet(
            topic="시장",
            figures=["유가 $100", "WTI $115", "15%", "3.2%", "1500원"],
            key_facts=["유가 상승"],
        )

    def test_dense_post_triggers_warning(self):
        """숫자 3개 + 종목 3개인 포스트 → 밀도 경고 발생."""
        post = (
            "삼성전자 -5%, 대한항공 -7%, 현대건설 -3%. "
            "유가 $100 돌파, WTI $115, 코스피 2500 급락."
        )
        pack = self._make_pack([post])
        fs = self._make_fs()
        _audit_numeric_safety(pack, fs)
        density_warnings = [w for w in pack.style_warnings if "밀도 초과" in w]
        assert len(density_warnings) == 1
        assert "포스트1" in density_warnings[0]

    def test_within_limits_no_warning(self):
        """숫자 2개, 종목 2개, 퍼센트 2개 이내 → 밀도 경고 없음."""
        post = "삼성전자 -5%, 대한항공 하락. 유가 $100 돌파."
        pack = self._make_pack([post])
        fs = self._make_fs()
        _audit_numeric_safety(pack, fs)
        density_warnings = [w for w in pack.style_warnings if "밀도 초과" in w]
        assert len(density_warnings) == 0

    def test_multiple_dense_posts(self):
        """포스트 2개가 각각 밀도 초과 → 두 포스트 모두 경고에 포함."""
        post1 = "삼성전자 -5%, 대한항공 -7%, 현대건설 -3%."
        post2 = "유가 $100, WTI $115, 브렌트 $120. 코스피 2500."
        post3 = "시장이 조정 국면이다."
        pack = self._make_pack([post1, post2, post3])
        fs = self._make_fs()
        _audit_numeric_safety(pack, fs)
        density_warnings = [w for w in pack.style_warnings if "밀도 초과" in w]
        assert len(density_warnings) == 1
        assert "포스트1" in density_warnings[0]
        assert "포스트2" in density_warnings[0]
        assert "포스트3" not in density_warnings[0]

    def test_percent_overload(self):
        """퍼센트만 3개 초과 → 경고 발생."""
        post = "A 섹터 -5%, B 섹터 +3%, C 섹터 -2.1% 하락."
        pack = self._make_pack([post])
        fs = self._make_fs()
        _audit_numeric_safety(pack, fs)
        density_warnings = [w for w in pack.style_warnings if "밀도 초과" in w]
        assert len(density_warnings) == 1
        assert "퍼센트" in density_warnings[0]

    def test_stock_overload(self):
        """종목명 3개 초과 → 경고 발생."""
        post = "삼성전자, 대한항공, 현대건설 모두 하락. 시장 불안."
        pack = self._make_pack([post])
        fs = self._make_fs()
        _audit_numeric_safety(pack, fs)
        density_warnings = [w for w in pack.style_warnings if "밀도 초과" in w]
        assert len(density_warnings) == 1
        assert "종목" in density_warnings[0]

    def test_number_overload(self):
        """구체 숫자 3개 초과 → 경고 발생."""
        post = "유가 $100, WTI $115, 코스피 2500 포인트."
        pack = self._make_pack([post])
        fs = self._make_fs()
        _audit_numeric_safety(pack, fs)
        density_warnings = [w for w in pack.style_warnings if "밀도 초과" in w]
        assert len(density_warnings) == 1
        assert "숫자" in density_warnings[0]


# ─── 발언 해석 강도 규칙 테스트 ─────────────────────────────────────────────


class TestSpeechInterpretationPromptRules:
    """골든룰 14 발언 해석 강도 규칙이 프롬프트에 반영됐는지 확인."""

    def test_golden_rule_14_exists(self):
        """골든룰 14가 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "발언 해석 강도 규칙" in prompt

    def test_speech_vs_action_separation(self):
        """발언과 조치 분리 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "발언과 조치는 반드시 분리" in prompt

    def test_intent_judgment_weakening(self):
        """발언 의도 확정 판정 약화 매핑이 있다."""
        prompt = _get_system_prompt("ko")
        assert "~의 신호다 → ~신호로 읽힐 수 있다" in prompt
        assert "맞장구치는 형국 → 비슷한 기조로 해석될 수 있다" in prompt

    def test_market_impact_weakening(self):
        """시장 영향 확정 금지 매핑이 있다."""
        prompt = _get_system_prompt("ko")
        assert "불가피하다 → 부담이 먼저 나타날 수 있다" in prompt

    def test_impact_path_density_rule(self):
        """파급 경로 3개 이상 나열 금지 규칙이 있다."""
        prompt = _get_system_prompt("ko")
        assert "파급 경로를 3개 이상 나열" in prompt

    def test_bad_good_examples(self):
        """발언 vs 조치 나쁜/좋은 예시가 있다."""
        prompt = _get_system_prompt("ko")
        assert "봉쇄를 시사하며 공급을 제한하고 있다" in prompt  # 나쁜 예
        assert "봉쇄 가능성을 언급했다" in prompt  # 좋은 예

    def test_qa_18_exists(self):
        """QA 체크리스트 18번 발언 해석 강도 항목이 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "발언 해석 강도" in prompt


class TestSpeechAssertionRegex:
    """_STRONG_ASSERTION_RE에 발언 해석 표현이 추가됐는지 확인."""

    def test_맞장구_detected(self):
        assert _STRONG_ASSERTION_RE.search("트럼프의 경고는 이에 맞장구치는 형국")

    def test_기존_직격탄_still_works(self):
        assert _STRONG_ASSERTION_RE.search("유가 상승이 직격탄이 됐다")

    def test_기존_불가피_still_works(self):
        assert _STRONG_ASSERTION_RE.search("비용 구조 변화도 불가피하다")

    def test_safe_text_no_match(self):
        """안전한 해석 표현은 매치하지 않는다."""
        assert not _STRONG_ASSERTION_RE.search(
            "공급 불안 신호로 받아들여질 수 있다"
        )


class TestImpactPathOverflow:
    """_audit_numeric_safety check 6 — 파급 경로 과밀 경고 테스트."""

    def _make_pack(self, main_posts):
        return ContentPack(
            main_posts=main_posts,
            short_version="테스트",
            reply_drafts=[],
            quote_post_drafts=[],
            thread_option=None,
            risk_flags=[],
            topic_tags=["에너지"],
            why_it_matters="테스트",
            style_warnings=[],
        )

    def _make_fs(self):
        return FactSheet(figures=[])

    def test_3_keywords_triggers_warning(self):
        """파급 경로 키워드 3개 → 경고 발생."""
        post = "유가 상승은 물가 압력으로 이어지고, 한은의 금리 판단에도 영향을 줄 수 있다."
        pack = self._make_pack([post])
        _audit_numeric_safety(pack, self._make_fs())
        path_warnings = [w for w in pack.style_warnings if "파급 경로 과밀" in w]
        assert len(path_warnings) == 1

    def test_2_keywords_no_warning(self):
        """파급 경로 키워드 2개 이하 → 경고 없음."""
        post = "유가 상승이 물가에 영향을 줄 수 있다."
        pack = self._make_pack([post])
        _audit_numeric_safety(pack, self._make_fs())
        path_warnings = [w for w in pack.style_warnings if "파급 경로 과밀" in w]
        assert len(path_warnings) == 0

    def test_5_keywords_strong(self):
        """파급 경로 키워드 5개 → 경고에 키워드 나열."""
        post = "물가, 한은 금리, 환율 압력, 항공 비용, 해운 운임까지 전방위 영향."
        pack = self._make_pack([post])
        _audit_numeric_safety(pack, self._make_fs())
        path_warnings = [w for w in pack.style_warnings if "파급 경로 과밀" in w]
        assert len(path_warnings) == 1
        assert "포스트1" in path_warnings[0]

    def test_multiple_posts_independent(self):
        """각 포스트 독립 검사 — 포스트1만 과밀."""
        post1 = "물가, 한은 금리, 환율 모두 흔들린다."
        post2 = "유가가 관건이다."
        pack = self._make_pack([post1, post2])
        _audit_numeric_safety(pack, self._make_fs())
        path_warnings = [w for w in pack.style_warnings if "파급 경로 과밀" in w]
        assert len(path_warnings) == 1
        assert "포스트1" in path_warnings[0]
        assert "포스트2" not in path_warnings[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 2단계 구조 테스트: 후보 카드 + 최종 마감
# ═══════════════════════════════════════════════════════════════════════════════


class TestCandidateCardDataclass:
    """CandidateCard 데이터클래스 기본 동작."""

    def test_default_values(self):
        """기본 생성 시 빈 리스트 + 미확인."""
        card = CandidateCard()
        assert card.key_facts == []
        assert card.hook_candidates == []
        assert card.one_liner == []
        assert card.certainty_level == "미확인"
        assert card.source_url is None

    def test_is_valid_with_data(self):
        """key_facts + hook_candidates 있으면 유효."""
        card = CandidateCard(
            key_facts=["팩트1"],
            hook_candidates=["훅1"],
        )
        assert card.is_valid() is True

    def test_is_valid_no_facts(self):
        """key_facts 없으면 무효."""
        card = CandidateCard(hook_candidates=["훅1"])
        assert card.is_valid() is False

    def test_is_valid_no_hooks(self):
        """hook_candidates 없으면 무효."""
        card = CandidateCard(key_facts=["팩트1"])
        assert card.is_valid() is False

    def test_is_valid_empty(self):
        """둘 다 없으면 무효."""
        card = CandidateCard()
        assert card.is_valid() is False


class TestFinalPostDataclass:
    """FinalPost 데이터클래스 기본 동작."""

    def test_default_values(self):
        card = FinalPost()
        assert card.final_post == ""
        assert card.final_short == ""

    def test_with_values(self):
        fp = FinalPost(final_post="게시글 본문", final_short="짧은 버전")
        assert fp.final_post == "게시글 본문"
        assert fp.final_short == "짧은 버전"


class TestParseCandidateCard:
    """_parse_candidate_card 파서 테스트."""

    def test_valid_json(self):
        """정상 JSON → CandidateCard."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1", "팩트2"],
            "hook_candidates": ["훅A", "훅B", "훅C"],
            "one_liner": ["결론1"],
            "cautions": ["주의1"],
            "watch_points": ["포인트1"],
            "certainty_level": "확정",
            "topic_tags": ["에너지"],
            "risk_flags": [],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert card.key_facts == ["팩트1", "팩트2"]
        assert len(card.hook_candidates) == 3
        assert card.certainty_level == "확정"

    def test_json_in_markdown_fence(self):
        """```json ... ``` 형태도 파싱."""
        raw = '```json\n{"key_facts": ["팩트"], "hook_candidates": ["훅"], "certainty_level": "미확인"}\n```'
        card = _parse_candidate_card(raw)
        assert card is not None
        assert card.key_facts == ["팩트"]

    def test_missing_optional_fields(self):
        """선택 필드 누락 → 빈 리스트 기본값."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["훅1"],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert card.one_liner == []
        assert card.cautions == []
        assert card.certainty_level == "미확인"

    def test_invalid_json_returns_none(self):
        """깨진 JSON → None."""
        assert _parse_candidate_card("이것은 JSON이 아니다") is None

    def test_empty_string_returns_none(self):
        """빈 문자열 → None."""
        assert _parse_candidate_card("") is None

    def test_truncated_list(self):
        """key_facts 6개 입력 → 5개로 절단."""
        import json
        raw = json.dumps({
            "key_facts": ["f1", "f2", "f3", "f4", "f5", "f6"],
            "hook_candidates": ["h1"],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert len(card.key_facts) == 5


class TestParseFinalPost:
    """_parse_final_post 파서 테스트."""

    def test_valid_json(self):
        """정상 JSON → FinalPost."""
        import json
        raw = json.dumps({
            "final_post": "280자 이내 게시글 본문입니다.",
            "final_short": "200자 이내 짧은 버전.",
        })
        result = _parse_final_post(raw)
        assert result is not None
        assert "280자" in result.final_post
        assert "200자" in result.final_short

    def test_json_in_markdown_fence(self):
        """```json``` 감싸기 파싱."""
        raw = '```json\n{"final_post": "본문", "final_short": "짧은"}\n```'
        result = _parse_final_post(raw)
        assert result is not None
        assert result.final_post == "본문"

    def test_empty_final_post_returns_none(self):
        """final_post 빈 문자열 → None."""
        import json
        raw = json.dumps({"final_post": "", "final_short": "짧은"})
        result = _parse_final_post(raw)
        assert result is None

    def test_missing_final_post_returns_none(self):
        """final_post 없음 → None."""
        import json
        raw = json.dumps({"final_short": "짧은"})
        result = _parse_final_post(raw)
        assert result is None

    def test_invalid_json_returns_none(self):
        assert _parse_final_post("{broken") is None

    def test_missing_short_ok(self):
        """final_short 없어도 final_post만 있으면 OK."""
        import json
        raw = json.dumps({"final_post": "본문만"})
        result = _parse_final_post(raw)
        assert result is not None
        assert result.final_post == "본문만"
        assert result.final_short == ""


class TestCandidatePromptRules:
    """_CANDIDATE_PROMPT_KO 프롬프트 규칙 검증."""

    def test_has_5_golden_rules(self):
        """골든룰 5개 핵심 키워드가 포함."""
        p = _CANDIDATE_PROMPT_KO
        assert "소스에 없는 수치/사실을 생성하지 말 것" in p
        assert "미확인·상충된 사안은 확정형으로 쓰지 말 것" in p
        assert "발언·경고·시사는 실제 조치·시행과 분리" in p
        assert "원문 밖 해석을 과도하게 확장하지 말 것" in p
        assert "짧고 구조화된 재료 중심" in p

    def test_has_5_qa_checks(self):
        """QA 체크 5개가 포함."""
        p = _CANDIDATE_PROMPT_KO
        assert "숫자/사실이 소스에 있는가" in p
        assert "미확인 사안을 확정처럼 쓰지 않았는가" in p
        assert "발언과 조치를 혼동하지 않았는가" in p
        assert "certainty_level이 내용과 일치하는가" in p
        assert "훅 후보가 서로 다른 방향을 제시하는가" in p

    def test_json_schema_has_all_fields(self):
        """JSON 스키마에 8개 필드 존재."""
        p = _CANDIDATE_PROMPT_KO
        for field in [
            "key_facts", "hook_candidates", "one_liner",
            "cautions", "watch_points", "certainty_level",
            "topic_tags", "risk_flags",
        ]:
            assert field in p

    def test_openai_does_not_generate_thesis(self):
        """OpenAI 프롬프트에서 thesis_cards 생성 지시 제거 확인."""
        p = _CANDIDATE_PROMPT_KO
        assert "thesis_cards는 생성하지 마라" in p
        assert "thesis_cards 규칙" not in p

    def test_no_complete_sentence_instruction(self):
        """완성 문장 금지 지시가 있다."""
        p = _CANDIDATE_PROMPT_KO
        assert "완성 글을 쓰지 마라" in p
        assert "완성 게시글 문체로 길게 쓰지 마라" in p

    def test_verification_linkage_section(self):
        """검증 연동 규칙 섹션이 존재."""
        p = _CANDIDATE_PROMPT_KO
        assert "검증 연동 규칙" in p
        assert "미검증" in p
        assert "certainty_level 상한" in p

    def test_verification_fail_keywords_in_prompt(self):
        """검증 실패 키워드가 프롬프트에 포함."""
        p = _CANDIDATE_PROMPT_KO
        assert "신뢰도: low" in p
        assert "no matching" in p
        assert "추가 확인 필요" in p

    def test_no_arbitrary_expansion_rule(self):
        """원문 밖 시장축 임의 확장 금지."""
        p = _CANDIDATE_PROMPT_KO
        assert "부동산/환율/주식시장/피해액" in p
        assert "임의 추가하지 마라" in p

    def test_force_fill_ban(self):
        """억지 해설 금지 규칙."""
        p = _CANDIDATE_PROMPT_KO
        assert "억지 해설 금지" in p
        assert "빈칸을 일반 경제 해설로 메우지 마라" in p

    def test_qa_check_extended(self):
        """QA 체크 7개로 확장."""
        p = _CANDIDATE_PROMPT_KO
        assert "상단 검증 결과와 certainty_level이 일관" in p
        assert "원문 밖 시장축을 임의 확장하지 않았는가" in p


class TestDecideCertaintyCeiling:
    """_decide_certainty_ceiling 로직 검증."""

    def test_no_context_returns_confirmed(self):
        """검증 컨텍스트 없으면 제한 없음."""
        assert _decide_certainty_ceiling("") == "확정"

    def test_unverified_low_returns_unconfirmed(self):
        """미검증 + 신뢰도 low → 미확인."""
        ctx = "⚠️ 미검증 (신뢰도: low)"
        assert _decide_certainty_ceiling(ctx) == "미확인"

    def test_low_confidence_returns_unconfirmed(self):
        """신뢰도 low만으로도 미확인."""
        ctx = "✅ 검증됨 (신뢰도: low)"
        assert _decide_certainty_ceiling(ctx) == "미확인"

    def test_medium_confidence_returns_conflicting(self):
        """신뢰도 medium → 상충."""
        ctx = "✅ 검증됨 (신뢰도: medium)"
        assert _decide_certainty_ceiling(ctx) == "상충"

    def test_high_confidence_no_restriction(self):
        """신뢰도 high → 제한 없음."""
        ctx = "✅ 검증됨 (신뢰도: high)"
        assert _decide_certainty_ceiling(ctx) == "확정"

    def test_no_matching_detected(self):
        """no matching 키워드 감지."""
        ctx = "검색 결과: no matching articles found"
        assert _decide_certainty_ceiling(ctx) == "미확인"

    def test_article_verification_failed(self):
        """기사 확인 실패 키워드 감지."""
        ctx = "YTN 기사 확인 실패, 무관한 검색 결과 혼입"
        assert _decide_certainty_ceiling(ctx) == "미확인"

    def test_additional_verification_needed(self):
        """추가 확인 필요 키워드 감지."""
        ctx = "일부 수치 추가 확인 필요"
        assert _decide_certainty_ceiling(ctx) == "미확인"

    def test_all_fail_keywords_covered(self):
        """_VERIFICATION_FAIL_KEYWORDS 모두 감지 확인."""
        for keyword in _VERIFICATION_FAIL_KEYWORDS:
            ctx = f"분석 결과: {keyword}"
            result = _decide_certainty_ceiling(ctx)
            assert result == "미확인", f"키워드 '{keyword}'가 감지되지 않음"


class TestCertaintyCeilingEnforcement:
    """_parse_candidate_card의 certainty 상한 보정 검증."""

    def test_confirmed_downgraded_to_unconfirmed(self):
        """AI가 확정으로 응답했지만 상한이 미확인이면 하향."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["훅1"],
            "certainty_level": "확정",
        })
        card = _parse_candidate_card(raw, certainty_ceiling="미확인")
        assert card is not None
        assert card.certainty_level == "미확인"

    def test_confirmed_downgraded_to_conflicting(self):
        """AI가 확정 → 상한 상충이면 상충으로."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["훅1"],
            "certainty_level": "확정",
        })
        card = _parse_candidate_card(raw, certainty_ceiling="상충")
        assert card is not None
        assert card.certainty_level == "상충"

    def test_unconfirmed_not_upgraded(self):
        """AI가 미확인 → 상한 확정이어도 그대로 미확인."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["훅1"],
            "certainty_level": "미확인",
        })
        card = _parse_candidate_card(raw, certainty_ceiling="확정")
        assert card is not None
        assert card.certainty_level == "미확인"

    def test_no_ceiling_default(self):
        """기본값은 제한 없음 (확정 허용)."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["훅1"],
            "certainty_level": "확정",
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert card.certainty_level == "확정"

    def test_conflicting_within_ceiling(self):
        """AI가 상충 → 상한 상충이면 그대로."""
        import json
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["훅1"],
            "certainty_level": "상충",
        })
        card = _parse_candidate_card(raw, certainty_ceiling="상충")
        assert card is not None
        assert card.certainty_level == "상충"


class TestFinalizePromptRules:
    """_FINALIZE_PROMPT_KO 프롬프트 규칙 검증."""

    def test_hook_single_axis(self):
        """골든룰 1: 논지 1개 중심축."""
        p = _FINALIZE_PROMPT_KO
        assert "논지(thesis) 1개 = 중심축 1개" in p
        assert "다른 방향" in p

    def test_first_sentence_meaning_first(self):
        """골든룰 2: 첫 문장은 해석/의미 선행."""
        p = _FINALIZE_PROMPT_KO
        assert "왜 중요한가" in p
        assert "사실 나열" in p
        assert "보도가 나왔다" in p  # 금지 예시

    def test_impact_path_max_2(self):
        """골든룰 3: 파급 경로 최대 2개."""
        p = _FINALIZE_PROMPT_KO
        assert "파급 경로는 최대 2개" in p
        assert "3개 이상 나열하면 실패" in p

    def test_certainty_level_downgrade(self):
        """골든룰 4: 미확인/정치 해석 한 단계 낮춤."""
        p = _FINALIZE_PROMPT_KO
        assert "확정 → 단정형 허용" in p
        assert "미확인 →" in p
        assert "상충 →" in p
        assert "시사했다" in p

    def test_last_sentence_type_enforcement(self):
        """골든룰 5: 마지막 문장은 조건형/대비형/질문형 중 하나."""
        p = _FINALIZE_PROMPT_KO
        assert "조건형" in p
        assert "대비형" in p
        assert "질문형" in p

    def test_bad_endings_banned(self):
        """전망문/훈계문/뻔한 마감 금지."""
        p = _FINALIZE_PROMPT_KO
        assert "영향을 주목해야 할 시점이다" in p  # 금지 예시
        assert "악영향이 예상된다" in p
        assert "교훈형" in p
        assert "훈계형" in p

    def test_good_ending_examples(self):
        """좋은 마감 예시가 포함 (조건형/대비형/질문형)."""
        p = _FINALIZE_PROMPT_KO
        # 조건형 예시
        assert "문제는 이 발언이 실제 정책으로 이어지느냐다" in p
        # 대비형 예시
        assert "시장은 말보다 규칙 변화를 먼저 본다" in p

    def test_style_rules(self):
        """문체 규칙: 칼럼 금지, 3문장 구조."""
        p = _FINALIZE_PROMPT_KO
        assert "칼럼" in p and "문체 금지" in p
        assert "3문장이 기본" in p
        assert "4문장까지 허용" in p

    def test_cautions_conflict_rule(self):
        """골든룰 6: cautions 충돌 금지."""
        p = _FINALIZE_PROMPT_KO
        assert "cautions" in p and "충돌" in p

    def test_only_two_output_fields(self):
        """출력 필드가 2개(final_post, final_short)만."""
        p = _FINALIZE_PROMPT_KO
        assert "final_post" in p
        assert "final_short" in p
        assert "2개 필드만 생성하라" in p

    def test_has_good_examples(self):
        """좋은 마감 예시 3개 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "반도체 관세" in p  # 예시 A
        assert "서울 아파트 거래" in p  # 예시 B
        assert "한은 총재 발언" in p  # 예시 C

    def test_diversity_rule_exists(self):
        """다양성 규칙 섹션이 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "다양성 규칙" in p

    def test_diversity_start_patterns(self):
        """시작 패턴 다양화: 질문형, 단정형, 수치형, 대비형."""
        p = _FINALIZE_PROMPT_KO
        assert "질문형" in p
        assert "단정형" in p
        assert "수치" in p
        assert "대비형" in p

    def test_diversity_ending_patterns(self):
        """마무리 다양화: 조건형, 대비형, 질문형."""
        p = _FINALIZE_PROMPT_KO
        assert "조건형" in p
        assert "대비형" in p
        assert "질문형" in p

    def test_diversity_no_repeat_structure(self):
        """같은 구조 반복 금지."""
        p = _FINALIZE_PROMPT_KO
        assert "구조 자체도 바꿔라" in p

    def test_first_sentence_fact_narration_ban(self):
        """첫 문장 사실나열 금지 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "기사 사실 요약으로 시작하면 실패" in p
        assert "것으로 전해졌다" in p

    def test_tone_temperature_rule(self):
        """문장 온도 규칙: 과장 표현 약화."""
        p = _FINALIZE_PROMPT_KO
        assert "직격탄" in p
        assert "불가피" in p
        assert "과장 표현 기본 약화" in p

    def test_paragraph_density_rule(self):
        """문단 밀도: 변수 2개까지만."""
        p = _FINALIZE_PROMPT_KO
        assert "변수 2개까지만" in p

    def test_short_version_independence(self):
        """final_short 독립 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "압축본이 아니다" in p
        assert "독립적으로 읽혀야 한다" in p
        assert "다른 각도로 시작" in p

    def test_self_check_section(self):
        """셀프 체크 섹션 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "셀프 체크" in p
        assert "과장 표현" in p

    def test_political_conservative_rule(self):
        """정치/외교/군사 보수적 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "정치/외교/군사 주제는 더 보수적" in p

    def test_more_banned_endings(self):
        """추가 금지 마감 패턴."""
        p = _FINALIZE_PROMPT_KO
        assert "추이를 봐야 한다" in p
        assert "시장에 미칠 여파가 클 것으로 보인다" in p
        assert "보고서 투" in p

    def test_final_short_examples(self):
        """final_short 독립 예시 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "final_short 예시" in p


class TestValidateFinalPost:
    """_validate_final_post 검증 로직 테스트."""

    def test_clean_post_no_warnings(self):
        """깨끗한 게시글은 경고 없음."""
        post = "관건은 이 관세가 반도체까지 확대되느냐다."
        short = "반도체 관세 확대 여부가 변수다."
        _, _, warnings = _validate_final_post(post, short)
        assert len(warnings) == 0

    def test_banned_ending_detected(self):
        """금지 마감 패턴 감지."""
        post = "이번 사안은 영향을 미칠 것으로 보인다. 향후 추이를 지켜볼 필요가 있다."
        _, _, warnings = _validate_final_post(post, "짧은 버전")
        assert any("금지 마감 패턴" in w for w in warnings)

    def test_banned_ending_with_period(self):
        """마침표 포함 금지 패턴."""
        post = "시장에 미칠 여파가 클 것으로 보인다."
        _, _, warnings = _validate_final_post(post, "")
        assert any("금지 마감 패턴" in w for w in warnings)

    def test_tone_softener_auto_replace(self):
        """과장 표현 자동 약화."""
        post = "이번 조치는 수출 기업에 직격탄이다."
        result_post, _, warnings = _validate_final_post(post, "")
        assert "직격탄" not in result_post
        assert "영향" in result_post
        assert any("자동 약화" in w for w in warnings)

    def test_multiple_softeners(self):
        """여러 과장 표현 동시 약화."""
        post = "급등이 불가피한 상황이다."
        result_post, _, warnings = _validate_final_post(post, "")
        assert "급등" not in result_post
        assert "불가피" not in result_post
        assert "상승" in result_post
        assert "가능성" in result_post

    def test_short_tone_softened(self):
        """final_short에서도 과장 표현 약화."""
        post = "정상 게시글."
        short = "시장이 붕괴되었다."
        _, result_short, _ = _validate_final_post(post, short)
        assert "붕괴" not in result_short
        assert "하락" in result_short

    def test_same_first_sentence_warning(self):
        """final_short 첫 문장이 final_post와 동일하면 경고."""
        post = "관세 확대가 핵심이다. 시장은 예외 품목을 본다."
        short = "관세 확대가 핵심이다."
        _, _, warnings = _validate_final_post(post, short)
        assert any("첫 문장이 final_post와 동일" in w for w in warnings)

    def test_different_first_sentence_no_warning(self):
        """첫 문장이 다르면 경고 없음."""
        post = "관세 확대가 핵심이다. 시장은 예외 품목을 본다."
        short = "예외 품목 리스트가 관건이다."
        _, _, warnings = _validate_final_post(post, short)
        assert not any("첫 문장이 final_post와 동일" in w for w in warnings)


class TestBannedEndingsCompleteness:
    """_BANNED_ENDINGS 리스트 완전성."""

    def test_banned_list_not_empty(self):
        assert len(_BANNED_ENDINGS) >= 10

    def test_key_patterns_in_list(self):
        patterns = ["주목해야", "지켜볼", "봐야 한다", "예상된다", "불가피"]
        for pat in patterns:
            assert any(pat in b for b in _BANNED_ENDINGS), f"'{pat}' 패턴 누락"


class TestToneSoftenersCompleteness:
    """_TONE_SOFTENERS 매��� 완전성."""

    def test_softeners_not_empty(self):
        assert len(_TONE_SOFTENERS) >= 5

    def test_key_softeners(self):
        assert "직격탄" in _TONE_SOFTENERS
        assert "불가피" in _TONE_SOFTENERS
        assert "급등" in _TONE_SOFTENERS
        assert "붕괴" in _TONE_SOFTENERS
        assert "토해냈다" in _TONE_SOFTENERS


class TestParseFinalPostWithValidation:
    """_parse_final_post에 검증이 통합되어 있는지 테스트."""

    def test_tone_softened_in_parse(self):
        """파싱 시 과장 표현이 자동 약화."""
        import json
        raw = json.dumps({"final_post": "직격탄을 맞았다.", "final_short": "급등세다."})
        result = _parse_final_post(raw)
        assert result is not None
        assert "직격탄" not in result.final_post
        assert "급등" not in result.final_short

    def test_valid_post_parses_clean(self):
        """정상 게시글은 그대로 파싱."""
        import json
        raw = json.dumps({
            "final_post": "관건은 시행령이 나오느냐다.",
            "final_short": "시행령 여부가 변수다."
        })
        result = _parse_final_post(raw)
        assert result is not None
        assert result.final_post == "관건은 시행령이 나오느냐다."
        assert result.final_short == "시행령 여부가 변수다."


class TestClaudeReviewCondition:
    """_should_invoke_claude_review 조건 판단 테스트."""

    @pytest.fixture(autouse=True)
    def _mock_has_anthropic(self, monkeypatch):
        """테스트 환경에 API 키 없으므로 has_anthropic을 True로 mock."""
        from app.config import settings
        monkeypatch.setattr(type(settings), "has_anthropic", property(lambda self: True))

    def _make_card(self, **kwargs):
        defaults = dict(
            key_facts=["팩트1"],
            hook_candidates=["훅1"],
            certainty_level="확정",
            topic_tags=["경제"],
            cautions=[],
        )
        defaults.update(kwargs)
        return CandidateCard(**defaults)

    def _make_draft(self, post="정상 게시글.", short="짧은 버전."):
        return FinalPost(final_post=post, final_short=short)

    def test_sensitive_topic_triggers(self):
        """민감 토픽이면 Claude 호출."""
        card = self._make_card(topic_tags=["정치", "경제"])
        assert _should_invoke_claude_review(card, self._make_draft()) is True

    def test_safe_topic_no_trigger(self):
        """안전 토픽 + 정상 초안 → 스킵."""
        card = self._make_card(topic_tags=["기술"], certainty_level="확정", cautions=[])
        assert _should_invoke_claude_review(card, self._make_draft()) is False

    def test_unconfirmed_triggers(self):
        """미확인 certainty면 호출."""
        card = self._make_card(certainty_level="미확인")
        assert _should_invoke_claude_review(card, self._make_draft()) is True

    def test_conflicting_triggers(self):
        """상충 certainty면 호출."""
        card = self._make_card(certainty_level="상충")
        assert _should_invoke_claude_review(card, self._make_draft()) is True

    def test_cautions_trigger(self):
        """cautions 있으면 호출."""
        card = self._make_card(cautions=["출처 미검증"])
        assert _should_invoke_claude_review(card, self._make_draft()) is True

    def test_weak_pattern_triggers(self):
        """뻔한 표현이면 호출."""
        card = self._make_card()
        draft = self._make_draft(post="이번 사안의 추이를 봐야 한다.")
        assert _should_invoke_claude_review(card, draft) is True

    def test_multiple_weak_patterns(self):
        """여러 뻔한 표현도 감지."""
        for pat in ["핵심은", "변수다", "주목해야 한다"]:
            card = self._make_card()
            draft = self._make_draft(post=f"이번 이슈에서 {pat}")
            assert _should_invoke_claude_review(card, draft) is True, f"'{pat}' 미감지"

    def test_short_independence_triggers(self):
        """final_short 첫 문장이 final_post와 동일하면 호출."""
        card = self._make_card()
        draft = self._make_draft(
            post="관세 확대가 핵심이다. 시장은 시행을 본다.",
            short="관세 확대가 핵심이다.",
        )
        assert _should_invoke_claude_review(card, draft) is True

    def test_all_sensitive_topics_covered(self):
        """_SENSITIVE_TOPICS 전체 확인."""
        for topic in _SENSITIVE_TOPICS:
            card = self._make_card(topic_tags=[topic])
            assert _should_invoke_claude_review(card, self._make_draft()) is True, \
                f"토픽 '{topic}' 미감지"


class TestClaudeReviewPromptRules:
    """_CLAUDE_REVIEW_PROMPT 프롬프트 규칙 검증."""

    def test_role_is_reviewer(self):
        p = _CLAUDE_REVIEW_PROMPT
        assert "보정자" in p
        assert "논지" in p

    def test_no_new_facts_rule(self):
        p = _CLAUDE_REVIEW_PROMPT
        assert "새 사실" in p and "금지" in p

    def test_fact_ceiling_rule(self):
        """사실 상한선 규칙이 포함."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "사실 상한선" in p
        assert "단정 금지" in p

    def test_weak_pattern_replacement(self):
        p = _CLAUDE_REVIEW_PROMPT
        assert "관건은" in p
        assert "변수다" in p
        assert "주목해야 한다" in p

    def test_cautions_respect(self):
        p = _CLAUDE_REVIEW_PROMPT
        assert "cautions" in p
        assert "충돌" in p

    def test_short_independence(self):
        p = _CLAUDE_REVIEW_PROMPT
        assert "독립" in p
        assert "final_short" in p

    def test_passthrough_allowed(self):
        """초안이 좋으면 그대로 반환 가능."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "고칠 게 없으면" in p

    def test_json_output(self):
        p = _CLAUDE_REVIEW_PROMPT
        assert "final_post" in p
        assert "final_short" in p
        assert "JSON" in p


class TestWeakPatternsCompleteness:
    """_WEAK_PATTERNS 리스트 완전성."""

    def test_not_empty(self):
        assert len(_WEAK_PATTERNS) >= 8

    def test_key_patterns(self):
        flat = " ".join(_WEAK_PATTERNS)
        assert "변수" in flat
        assert "주목" in flat
        assert "추이" in flat
        assert "핵심은" in flat
        assert "로 보인다" in flat


class TestSensitiveTopicsCompleteness:
    """_SENSITIVE_TOPICS 집합 완전성."""

    def test_core_topics(self):
        for t in ["정치", "외교", "안보", "군사", "부동산", "정책"]:
            assert t in _SENSITIVE_TOPICS, f"'{t}' 누락"


class TestExpandedBannedEndings:
    """확장된 _BANNED_ENDINGS 검증."""

    def test_new_patterns_exist(self):
        """추가된 뻔한 전망문 패턴이 포함."""
        for pat in ["추이를 봐야 한다", "영향을 미칠 수 있다",
                     "중요한 시점이다", "여파가 예상된다", "가능성이 커졌다"]:
            assert pat in _BANNED_ENDINGS, f"'{pat}' 누락"

    def test_validate_catches_new_banned(self):
        """새로 추가된 금지 패턴이 _validate_final_post에서 감지."""
        post = "이번 사안의 추이를 봐야 한다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감 패턴" in w for w in warnings)

    def test_validate_catches_possibility_grew(self):
        post = "이번 조치로 인해 가능성이 커졌다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감 패턴" in w for w in warnings)


class TestWeakPatternValidation:
    """_validate_final_post에서 뻔한 표현 감지."""

    def test_weak_pattern_warning(self):
        """본문 내 뻔한 표현이 경고로 기록."""
        post = "시장에 영향을 미칠 수 있다는 관측이 나온다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현 감지" in w for w in warnings)

    def test_clean_post_no_weak_warning(self):
        """깨끗한 글에서는 뻔한 표현 경고 없음."""
        post = "시장은 발언이 아니라 시행령을 본다."
        _, _, warnings = _validate_final_post(post, "독립 버전.")
        assert not any("뻔한 표현 감지" in w for w in warnings)


class TestFinalizePromptEndingRules:
    """_FINALIZE_PROMPT_KO 마지막 문장 유형 강제 규칙 검증."""

    def test_three_ending_types(self):
        """조건형/대비형/질문형 3가지 유형이 명시."""
        p = _FINALIZE_PROMPT_KO
        assert "조건형" in p
        assert "대비형" in p
        assert "질문형" in p

    def test_banned_ending_examples_in_prompt(self):
        """금지 마감 예시가 프롬프트에 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "추이를 봐야 한다" in p
        assert "영향을 미칠 수 있다" in p
        assert "가능성이 커졌다" in p

    def test_memo_contamination_rule(self):
        """내부 메모 오염 금지 규칙이 프롬프트에 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "내부 메모 언어 오염 금지" in p
        assert "복붙하지 마라" in p

    def test_selfcheck_updated(self):
        """셀프 체크에 새 항목 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "조건형/대비형/질문형" in p
        assert "뻔한 마감" in p


class TestGeminiThesisPromptRules:
    """_GEMINI_THESIS_PROMPT thesis_cards 규칙 검증 (Gemini가 논지 생성)."""

    def test_gemini_thesis_prompt_exists(self):
        """_GEMINI_THESIS_PROMPT가 존재하고 비어있지 않음."""
        assert _GEMINI_THESIS_PROMPT
        assert len(_GEMINI_THESIS_PROMPT) > 100

    def test_gemini_persona_is_thesis_generator(self):
        """Gemini 페르소나가 논지 분기기."""
        assert "논지 분기기" in _GEMINI_THESIS_PROMPT

    def test_thesis_card_fields(self):
        """thesis_card 필드(thesis, why_not_summary, reader_stake, opener) 정의."""
        p = _GEMINI_THESIS_PROMPT
        assert "thesis" in p
        assert "why_not_summary" in p
        assert "reader_stake" in p
        assert "opener" in p

    def test_divergence_rules(self):
        """논지 분기 규칙 (서로 다른 해석 축)."""
        p = _GEMINI_THESIS_PROMPT
        assert "해석 축" in p

    def test_dead_patterns_banned(self):
        """dead pattern 금지 목록."""
        p = _GEMINI_THESIS_PROMPT
        assert "하려는 시도다" in p
        assert "로 해석된다" in p
        assert "가 관건이다" in p


class TestClaudeReviewPromptUpdated:
    """Claude 감수 프롬프트 업데이트 검증."""

    def test_ending_type_guidance(self):
        """마지막 문장 유형 가이드가 포함."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "조건형" in p or "대비형" in p

    def test_role_is_corrector_not_editor(self):
        """Claude 역할이 보정자(사실/톤)로 축소."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "보정자" in p
        assert "논지(thesis)를 바꾸거나" in p or "논지를 건드리지 마라" in p

    def test_banned_ending_patterns_in_prompt(self):
        """금지 마감 패턴이 포함."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "추이를 봐야 한다" in p
        assert "관건은" in p


class TestFactNarrationDetection:
    """첫 문장 사실나열 감지 테스트."""

    def test_detects_report_start(self):
        """'~보도가 나왔다' 패턴 감지."""
        post = "호르무즈 해협을 지나는 선박이 통과했다라는 보도가 나왔다. 정부는 확인 중."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("사실나열" in w for w in warnings)

    def test_detects_jeonhaejyeotda(self):
        """'~것으로 전해졌다' 패턴 감지."""
        post = "한국 선박이 해협을 통과한 것으로 전해졌다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("사실나열" in w for w in warnings)

    def test_clean_start_no_warning(self):
        """해석 선행 첫 문장은 경고 없음."""
        post = "외교 뉴스처럼 보이지만 먼저 흔들리는 건 비용이다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert not any("사실나열" in w for w in warnings)

    def test_fact_narration_starts_not_empty(self):
        """_FACT_NARRATION_STARTS 리스트가 비어있지 않음."""
        assert len(_FACT_NARRATION_STARTS) >= 5


class TestNewBannedEndingPatterns:
    """새로 추가된 금지 마감 패턴 테스트."""

    def test_journalist_question_banned(self):
        """기자 질문형 마감 감지."""
        post = "이 사안은 앞으로 어떻게 될까."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감" in w or "뻔한 표현" in w for w in warnings)

    def test_market_reaction_banned(self):
        """시장 반응을 봐야 한다 감지."""
        post = "결국 시장 반응을 봐야 한다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감" in w or "뻔한 표현" in w for w in warnings)


class TestRoleLoyaltyInPrompt:
    """역할 충성 원칙이 프롬프트에 포함된 테스트."""

    def test_finalize_role_loyalty(self):
        """마감 프롬프트에 역할 충성 원칙이 있음."""
        p = _FINALIZE_PROMPT_KO
        assert "역할 충성 원칙" in p
        assert "기억에 남는 해석" in p
        assert "안전한 설명문" in p

    def test_finalize_forbidden_actions(self):
        """마감 프롬프트에 금지 행동이 명시."""
        p = _FINALIZE_PROMPT_KO
        assert "기사 내용을 다시 줄줄 요약" in p
        assert "뉴스 후기" in p

    def test_gemini_thesis_critical(self):
        """Gemini thesis 프롬프트 규칙이 CRITICAL 레벨."""
        p = _GEMINI_THESIS_PROMPT
        assert "CRITICAL" in p

    def test_claude_review_correction_criteria(self):
        """Claude 보정 프롬프트에 보정 판정 기준이 있음."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "보정 판정 기준" in p
        assert "최소 보정" in p

    def test_ending_type_d_compression(self):
        """D. 압축형 결론 유형이 프롬프트에 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "압축형" in p


class TestSendCandidateCardMessages:
    """send_candidate_card_messages() 출력 구조 검증."""

    def _make_card(self):
        return CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            hook_candidates=["훅A 방향", "훅B 방향", "훅C 방향"],
            one_liner=["한줄 결론1", "한줄 결론2"],
            cautions=["주의문1"],
            watch_points=["포인트1", "포인트2"],
            certainty_level="미확인",
            topic_tags=["에너지", "유가"],
            risk_flags=["테스트 리스크"],
        )

    def test_returns_list(self):
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        assert isinstance(msgs, list)
        assert len(msgs) > 0

    def test_overview_card_first(self):
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        first = msgs[0]
        assert first["hook_index"] is None
        assert "후보 카드 생성 완료" in first["text"]
        assert "미확인" in first["text"]

    def test_certainty_icons(self):
        from app.services.telegram_service import send_candidate_card_messages
        # 확정
        card = self._make_card()
        card.certainty_level = "확정"
        msgs = send_candidate_card_messages(card)
        assert "✅" in msgs[0]["text"]
        # 상충
        card.certainty_level = "상충"
        msgs = send_candidate_card_messages(card)
        assert "🔀" in msgs[0]["text"]

    def test_hook_messages_have_indices(self):
        """훅 후보 메시지에 hook_index 0,1,2가 할당."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        hook_msgs = [m for m in msgs if m["hook_index"] is not None]
        assert len(hook_msgs) == 3
        assert hook_msgs[0]["hook_index"] == 0
        assert hook_msgs[1]["hook_index"] == 1
        assert hook_msgs[2]["hook_index"] == 2

    def test_hook_labels_abc(self):
        """훅 후보에 A, B, C 라벨 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        hook_msgs = [m for m in msgs if m["hook_index"] is not None]
        assert "훅 후보 A" in hook_msgs[0]["text"]
        assert "훅 후보 B" in hook_msgs[1]["text"]
        assert "훅 후보 C" in hook_msgs[2]["text"]

    def test_key_facts_section(self):
        """핵심 팩트 섹션이 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        facts_msg = [m for m in msgs if "핵심 팩트" in m["text"]]
        assert len(facts_msg) == 1
        assert "팩트1" in facts_msg[0]["text"]

    def test_one_liner_section(self):
        """한줄 결론 섹션이 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        liner_msg = [m for m in msgs if "한줄 결론" in m["text"]]
        assert len(liner_msg) == 1

    def test_cautions_section(self):
        """주의문 섹션이 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        caution_msg = [m for m in msgs if "주의문" in m["text"]]
        assert len(caution_msg) == 1

    def test_watch_points_section(self):
        """관찰 포인트 섹션이 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        watch_msg = [m for m in msgs if "지금 봐야 할 포인트" in m["text"]]
        assert len(watch_msg) == 1

    def test_tags_in_overview(self):
        """태그가 개요에 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        assert "#에너지" in msgs[0]["text"]

    def test_risk_flags_in_overview(self):
        """위험 신호가 개요에 포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        assert "테스트 리스크" in msgs[0]["text"]

    def test_empty_optional_sections(self):
        """선택 섹션이 비어 있으면 해당 메시지 생략."""
        from app.services.telegram_service import send_candidate_card_messages
        card = CandidateCard(
            key_facts=["팩트"],
            hook_candidates=["훅"],
            one_liner=[],
            cautions=[],
            watch_points=[],
        )
        msgs = send_candidate_card_messages(card)
        texts_joined = " ".join(m["text"] for m in msgs)
        assert "한줄 결론" not in texts_joined
        assert "주의문" not in texts_joined
        assert "지금 봐야 할 포인트" not in texts_joined


# ─── 국제 뉴스 한국 관점 강화 테스트 ─────────────────────────────────────────


class TestKoreaAngleGeminiThesisPrompt:
    """Gemini thesis 프롬프트에 한국 관점 훅 규칙이 있는지 검증."""

    def test_korea_angle_rule_exists(self):
        """한국 관점 해석 축 규칙이 Gemini thesis 프롬프트에 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "한국" in p
        assert "해석 축" in p

    def test_international_news_rule(self):
        """국제 뉴스 특별 규칙이 Gemini thesis 프롬프트에 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "국제" in p


class TestFinalizePromptPrincipleABC:
    """마감 프롬프트에 원칙 A/B/C가 있는지 검증."""

    def test_principle_a_why_it_matters(self):
        """원칙 A: 첫 문장 'why this matters' 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "원칙 A" in p
        assert "왜 중요한가" in p

    def test_principle_b_korea_angle(self):
        """원칙 B: 한국 관점 해석 축 필수 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "원칙 B" in p
        assert "한국 관점" in p

    def test_principle_c_no_general_opinion(self):
        """원칙 C: 일반론 의견 금지 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "원칙 C" in p
        assert "일반론" in p

    def test_bad_good_examples_exist(self):
        """원칙 B에 나쁨/좋음 예시가 있는지 검증."""
        p = _FINALIZE_PROMPT_KO
        # 원칙 B 관련 나쁨/좋음
        assert "한국 관점 없음" in p


class TestOpinionPatterns:
    """일반론 의견 패턴 상수 및 검증 통합 테스트."""

    def test_opinion_patterns_exist(self):
        """_OPINION_PATTERNS 상수가 존재하고 비어있지 않음."""
        assert len(_OPINION_PATTERNS) > 0

    def test_key_patterns_included(self):
        """핵심 일반론 패턴이 포함."""
        assert "역사적으로" in _OPINION_PATTERNS
        assert "전략이다" in _OPINION_PATTERNS
        assert "낳기 쉽다" in _OPINION_PATTERNS
        assert "큰 파장을" in _OPINION_PATTERNS

    def test_validate_detects_opinion_pattern(self):
        """_validate_final_post가 일반론 의견 패턴을 감지."""
        post = "역사적으로 이런 상황에서는 항상 위기가 반복되었다."
        _, _, warnings = _validate_final_post(post, "짧은 버전")
        opinion_warns = [w for w in warnings if "일반론 의견" in w]
        assert len(opinion_warns) >= 1

    def test_validate_no_false_positive(self):
        """일반론 패턴이 없는 정상 문장은 경고 없음."""
        post = "한국 환율이 1400원을 넘기면 수입 물가 부담이 커진다."
        _, _, warnings = _validate_final_post(post, "짧은 버전")
        opinion_warns = [w for w in warnings if "일반론 의견" in w]
        assert len(opinion_warns) == 0

    def test_claude_trigger_on_opinion(self, monkeypatch):
        """일반론 의견 패턴이 있으면 Claude 감수 트리거."""
        from app.config import settings
        monkeypatch.setattr(type(settings), "has_anthropic", property(lambda self: True))
        card = CandidateCard(
            key_facts=["팩트"], hook_candidates=["훅"],
            one_liner=["한줄"], cautions=[], watch_points=[],
        )
        draft = FinalPost(
            final_post="역사적으로 이런 상황은 항상 반복되어 왔다.",
            final_short="짧은 버전",
        )
        assert _should_invoke_claude_review(card, draft) is True


class TestClaudeReviewPrincipleSync:
    """Claude 보정자 프롬프트에 핵심 보정 규칙이 동기화되었는지 검증."""

    def test_thesis_preservation_in_claude_prompt(self):
        """Claude 보정 프롬프트에 논지 보존 규칙 존재."""
        assert "논지" in _CLAUDE_REVIEW_PROMPT
        assert "건드리지 마라" in _CLAUDE_REVIEW_PROMPT

    def test_fact_correction_in_claude_prompt(self):
        """Claude 보정 프롬프트에 사실 보정 규칙 존재."""
        assert "사실 보정" in _CLAUDE_REVIEW_PROMPT or "cautions" in _CLAUDE_REVIEW_PROMPT

    def test_correction_criteria_count(self):
        """보정 판정 기준이 6개."""
        assert "6." in _CLAUDE_REVIEW_PROMPT


class TestToneAnchorInFinalize:
    """마감 프롬프트에 문체 모델(톤 앵커)이 존재하는지 검증."""

    def test_tone_anchor_exists(self):
        """문체 모델 섹션이 존재."""
        assert "문체 모델" in _FINALIZE_PROMPT_KO

    def test_tone_anchor_persona(self):
        """증권사 출신 해설자 페르소나가 명시."""
        assert "증권사" in _FINALIZE_PROMPT_KO
        assert "팔로워" in _FINALIZE_PROMPT_KO

    def test_tone_anchor_anti_patterns(self):
        """신문 칼럼/보고서/TV 해설 금지가 명시."""
        assert "신문 칼럼 X" in _FINALIZE_PROMPT_KO
        assert "보고서 X" in _FINALIZE_PROMPT_KO


class TestOpinionPatternsNoFalsePositive:
    """_OPINION_PATTERNS에 과잉 패턴이 없는지 검증."""

    def test_no_common_expression_in_patterns(self):
        """'으로 보인다'가 _OPINION_PATTERNS에 없음 (과잉 false positive 방지)."""
        assert "으로 보인다" not in _OPINION_PATTERNS


# ─── 병목 재설계 테스트 ──────────────────────────────────────────────────────


class TestThesisCardQualityRules:
    """Gemini thesis 프롬프트에 thesis card 품질 규칙이 있는지 검증."""

    def test_reader_stake_quality_rule(self):
        """reader_stake 품질 규칙 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "reader_stake" in p

    def test_thesis_divergence_rule(self):
        """논지 분기 규칙(서로 다른 해석 축) 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "해석 축" in p


class TestFinalPostThreeSlotStructure:
    """마감 프롬프트에 3문장 구조(WHY/WHAT/SO WHAT)가 있는지 검증."""

    def test_three_slots_exist(self):
        """WHY/WHAT/SO WHAT 슬롯이 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "WHY" in p
        assert "WHAT" in p
        assert "SO WHAT" in p

    def test_three_sentence_default(self):
        """3문장 기본, 4문장 허용 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "3문장이 기본" in p
        assert "4문장까지 허용" in p

    def test_no_room_for_summary(self):
        """기사 재설명 문장이 끼어들 자리 없다는 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "기사 내용을 다시 설명하는 문장" in p


class TestValidationGate:
    """validation 경고가 Claude 감수 트리거로 연결되는지 검증."""

    def test_single_warning_no_force(self):
        """경고 1개는 강제 트리거 미발동."""
        # 금지 마감 패턴 1개만 걸리는 케이스
        post = "정상적인 첫 문장이다.\n해석 축 연결.\n추이를 봐야 한다."
        _, _, warnings = _validate_final_post(post, "독립 짧은 버전")
        # 금지 마감 1개만 걸림 — 강제 아님
        ban_warns = [w for w in warnings if "금지 마감" in w]
        assert len(ban_warns) >= 1
        # 총 경고 1개면 force=False
        # (다른 경고 안 걸리는 깨끗한 입력)

    def test_multiple_warnings_force(self):
        """경고 2개 이상이면 강제 트리거."""
        # 첫 문장 사실나열 + 금지 마감 + 뻔한 표현 → 3개
        post = "라는 보도가 나왔다. 시장 반응을 봐야 한다."
        _, _, warnings = _validate_final_post(post, "독립 짧은 버전")
        assert len(warnings) >= 2, f"경고 2개 이상 예상, 실제: {warnings}"

    def test_clean_post_no_warnings(self):
        """깨끗한 포스트는 경고 0개."""
        post = "이 뉴스에서 먼저 건드리는 건 외교가 아니라 비용이다.\n원화 환율이 1400원대에 진입했다.\n진짜 변수는 시행령 여부다."
        _, _, warnings = _validate_final_post(post, "환율 1400원대, 변수는 시행령이다.")
        # 과장 표현도 없고 금지 마감도 없는 깨끗한 포스트
        assert len(warnings) == 0, f"경고 0개 예상, 실제: {warnings}"


# ─── Phase 1: Claude 상시 최종 통합 테스트 ──────────────────────────────────────


class TestClaudeAlwaysOnIntegrator:
    """Phase 1: Claude가 사실/톤 보정자로 역할 축소되었는지 검증."""

    def test_prompt_role_is_corrector(self):
        """프롬프트 역할이 '사실/톤 보정자'."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "사실/톤 보정자" in p

    def test_prompt_role_is_not_final_owner(self):
        """'보정자'로 명시, '최종 책임자'가 아님."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "보정자" in p
        assert '"최종 책임자"가 아니라' in p

    def test_prompt_thesis_preservation(self):
        """논지를 바꾸지 말라는 규칙 존재."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "논지(thesis)를 바꾸거나" in p or "논지를 건드리지 마라" in p

    def test_prompt_has_tone_model(self):
        """문체 모델 (증권사 출신 해설자)이 Claude 프롬프트에도 존재."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "증권사" in p
        assert "팔로워" in p

    def test_prompt_has_three_sentence_structure(self):
        """3문장 구조(WHY/WHAT/SO WHAT)가 Claude 프롬프트에 포함."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "WHY" in p
        assert "WHAT" in p
        assert "SO WHAT" in p

    def test_prompt_passthrough_when_good(self):
        """초안이 좋으면 그대로 반환 가능."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "고칠 게 없으면" in p
        assert "그대로" in p

    def test_claude_review_accepts_selected_hook(self):
        """_claude_review_final이 selected_hook 키워드 인자를 받음."""
        import inspect
        from app.services.content_pack import _claude_review_final
        sig = inspect.signature(_claude_review_final)
        assert "selected_hook" in sig.parameters

    def test_claude_review_accepts_gemini_opinion(self):
        """_claude_review_final이 gemini_opinion 키워드 인자를 받음."""
        import inspect
        from app.services.content_pack import _claude_review_final
        sig = inspect.signature(_claude_review_final)
        assert "gemini_opinion" in sig.parameters


# ─── Phase 2: Gemini 대안 의견 카드 테스트 ──────────────────────────────────────


class TestGeminiOpinionPrompt:
    """Gemini 대안 의견 카드 프롬프트 검증."""

    def test_role_is_opinion_card(self):
        """역할이 '대안 의견 카드 생성기'."""
        assert "대안 의견 카드" in _GEMINI_OPINION_PROMPT

    def test_first_line_priority(self):
        """first_line_suggestion이 가장 우선순위 높음."""
        p = _GEMINI_OPINION_PROMPT
        assert "first_line_suggestion" in p
        # 1번으로 나와야 함
        idx_first = p.find("1. first_line_suggestion")
        idx_alt = p.find("2. alt_short")
        assert idx_first < idx_alt

    def test_no_full_rewrite(self):
        """본문 전체 재작성 금지."""
        assert "전체 재작성 금지" in _GEMINI_OPINION_PROMPT

    def test_no_new_facts(self):
        """새 사실 추가 금지."""
        assert "새 사실" in _GEMINI_OPINION_PROMPT
        assert "금지" in _GEMINI_OPINION_PROMPT

    def test_tone_model_sync(self):
        """문체 모델이 동기화되어 있음."""
        assert "증권사" in _GEMINI_OPINION_PROMPT

    def test_json_output_schema(self):
        """출력 스키마에 4개 필드 존재."""
        p = _GEMINI_OPINION_PROMPT
        for field in ["first_line_suggestion", "alt_short", "alt_angle", "alt_hooks"]:
            assert field in p

    def test_cautions_constraint(self):
        """cautions 상한선 규칙 존재."""
        assert "cautions" in _GEMINI_OPINION_PROMPT or "검증 결과" in _GEMINI_OPINION_PROMPT


class TestGeminiOpinionCardDataclass:
    """GeminiOpinionCard 데이터클래스 검증."""

    def test_default_values(self):
        """기본값이 빈 문자열/빈 리스트."""
        card = GeminiOpinionCard()
        assert card.first_line_suggestion == ""
        assert card.alt_short == ""
        assert card.alt_angle == ""
        assert card.alt_hooks == []

    def test_with_values(self):
        """값 할당 정상 동작."""
        card = GeminiOpinionCard(
            first_line_suggestion="테스트 첫 줄",
            alt_hooks=["훅1", "훅2"],
        )
        assert card.first_line_suggestion == "테스트 첫 줄"
        assert len(card.alt_hooks) == 2


class TestShouldInvokeExtendedReview:
    """_should_invoke_extended_review() 조건 함수 검증."""

    def _make_card(self, **kwargs):
        defaults = {
            "hook_candidates": ["훅1", "훅2", "훅3"],
            "key_facts": ["팩트1"],
            "certainty_level": "확인",
            "topic_tags": [],
            "cautions": [],
            "one_liner": [],
            "watch_points": [],
            "risk_flags": [],
        }
        defaults.update(kwargs)
        return CandidateCard(**defaults)

    def _make_draft(self, post="정상 첫 문장이다.\n해석 축.\n변수는 시행령이다.", short="독립 짧은 버전."):
        return FinalPost(final_post=post, final_short=short)

    def test_sensitive_topic_triggers(self):
        """민감 토픽이면 True."""
        card = self._make_card(topic_tags=["외교", "경제"])
        draft = self._make_draft()
        assert _should_invoke_extended_review(card, draft) is True

    def test_unconfirmed_certainty_triggers(self):
        """certainty_level 미확인이면 True."""
        card = self._make_card(certainty_level="미확인")
        draft = self._make_draft()
        assert _should_invoke_extended_review(card, draft) is True

    def test_conflicting_certainty_triggers(self):
        """certainty_level 상충이면 True."""
        card = self._make_card(certainty_level="상충")
        draft = self._make_draft()
        assert _should_invoke_extended_review(card, draft) is True

    def test_weak_pattern_triggers(self):
        """뻔한 표현 포함 시 True."""
        card = self._make_card()
        draft = self._make_draft(post="이 사안의 추이를 봐야 한다.")
        assert _should_invoke_extended_review(card, draft) is True

    def test_fact_narration_first_line_triggers(self):
        """첫 줄 사실나열이면 True."""
        card = self._make_card()
        draft = self._make_draft(post="라는 보도가 나왔다. 후속 조치 예상.")
        assert _should_invoke_extended_review(card, draft) is True

    def test_short_same_as_post_triggers(self):
        """final_short가 final_post 첫 문장과 동일하면 True."""
        card = self._make_card()
        draft = self._make_draft(
            post="동일한 문장이다. 두 번째.",
            short="동일한 문장이다. 다른 내용.",
        )
        assert _should_invoke_extended_review(card, draft) is True

    def test_clean_post_no_trigger(self):
        """깨끗한 포스트+일반 토픽이면 False."""
        card = self._make_card(topic_tags=["기술", "IT"])
        draft = self._make_draft(
            post="이 뉴스에서 먼저 건드리는 건 외교가 아니라 비용이다.\n원화 환율이 1400원대에 진입했다.\n진짜 변수는 시행령 여부다.",
            short="환율 1400원대, 변수는 시행령이다.",
        )
        assert _should_invoke_extended_review(card, draft) is False

    def test_extended_review_topics_includes_international(self):
        """국제/지정학/거시경제도 확장 토픽에 포함."""
        for topic in ["국제", "지정학", "거시경제"]:
            assert topic in _EXTENDED_REVIEW_TOPICS

    def test_multiple_warnings_trigger(self):
        """validation 경고 2개 이상이면 True."""
        card = self._make_card()
        # 첫 문장 사실나열 + 금지 마감 = 경고 2개
        draft = self._make_draft(
            post="라는 보도가 나왔다. 시장 반응을 봐야 한다.",
        )
        assert _should_invoke_extended_review(card, draft) is True


# ─── 훅 각도 분리 + 약한 패턴 보강 테스트 ──────────────────────────────────────


class TestThesisAngleSeparation:
    """Gemini thesis 프롬프트에 논지 분기(각도 분리) 규칙이 있는지 검증."""

    def test_angle_separation_rule_exists(self):
        """논지 분기 CRITICAL 규칙이 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "CRITICAL" in p

    def test_dead_patterns_in_gemini(self):
        """Gemini thesis 프롬프트에 dead pattern 금지 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "하려는 시도다" in p
        assert "로 해석된다" in p

    def test_reader_stake_in_gemini(self):
        """Gemini thesis 프롬프트에 reader_stake 규칙 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "reader_stake" in p

    def test_opener_in_gemini(self):
        """Gemini thesis 프롬프트에 opener 규칙 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "opener" in p


class TestWeakPatternsExtended:
    """추가된 약한 패턴 검증."""

    def test_new_patterns_exist(self):
        """새로 추가된 경고문/당위형 종결 패턴이 포함."""
        for pat in ["핵심이다", "시급하다", "시급한 과제",
                     "우려가 커지고 있다", "리스크가 커질 수 있다",
                     "중요한 변수다"]:
            assert pat in _WEAK_PATTERNS, f"'{pat}' 누락"

    def test_validate_catches_core_is(self):
        """'핵심이다' 패턴이 validation에서 감지."""
        post = "한국 반도체가 취약한지가 핵심이다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)

    def test_validate_catches_urgent(self):
        """'시급하다' 패턴이 validation에서 감지."""
        post = "중동 의존도를 줄이는 것이 시급하다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)

    def test_validate_catches_risk_grow(self):
        """'리스크가 커질 수 있다' 패턴이 validation에서 감지."""
        post = "향후 경제적 리스크가 커질 수 있다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)

    def test_no_false_positive_on_clean(self):
        """깨끗한 글에서 새 패턴 false positive 없음."""
        post = "브롬 가격이 2배 되면 반도체 원가에서 먼저 흔들리는 건 식각 공정이다."
        _, _, warnings = _validate_final_post(post, "독립 짧은 버전.")
        assert not any("뻔한 표현" in w for w in warnings)


class TestAntiReportToneInFinalize:
    """마감 프롬프트에 보고서 톤 방지 규칙이 있는지 검증."""

    def test_supply_chain_anti_report(self):
        """산업/공급망 보고서 톤 방지 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "산업 리스크 보고서" in p

    def test_narrow_down_rule(self):
        """'한 문장으로 좁혀라' 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "한 문장으로 좁혀라" in p


class TestColumnStructureBan:
    """칼럼/사설 구조 금지 규칙 검증."""

    # ── _FINALIZE_PROMPT_KO 검증 ──

    def test_finalize_has_column_ban_section(self):
        """마감 프롬프트에 칼럼/사설 구조 금지 섹션이 존재."""
        assert "칼럼/사설 구조 금지" in _FINALIZE_PROMPT_KO

    def test_finalize_bans_moonjeneun(self):
        """'문제는 ~것이다' 금지 패턴이 마감 프롬프트에 존재."""
        assert "문제는 ~것이다" in _FINALIZE_PROMPT_KO

    def test_finalize_bans_haeksimida(self):
        """'핵심이다' 금지 패턴이 마감 프롬프트에 존재."""
        assert "핵심이다" in _FINALIZE_PROMPT_KO

    def test_finalize_bans_bonjileun(self):
        """'본질은 ~' 금지 패턴이 마감 프롬프트에 존재."""
        assert "본질은 ~" in _FINALIZE_PROMPT_KO

    def test_finalize_has_alternative_example(self):
        """조건형/대비형 대안 예시가 존재."""
        assert "갈림길은 시행 시점이다" in _FINALIZE_PROMPT_KO

    def test_finalize_selfcheck_has_column_ban(self):
        """셀프 체크 항목에 칼럼/사설 구조 체크가 존재."""
        assert "칼럼/사설 구조가 없는가" in _FINALIZE_PROMPT_KO

    # ── _CLAUDE_REVIEW_PROMPT 검증 ──

    def test_claude_has_column_ban_section(self):
        """Claude 프롬프트에 칼럼/사설 구조 금지 섹션이 존재."""
        assert "칼럼/사설 구조 금지" in _CLAUDE_REVIEW_PROMPT

    def test_claude_bans_moonjeneun(self):
        """Claude 프롬프트에 '문제는 ~것이다' 금지."""
        assert "문제는 ~것이다" in _CLAUDE_REVIEW_PROMPT

    def test_claude_bans_haeksimida(self):
        """Claude 프롬프트에 '핵심이다' 금지."""
        assert "핵심이다" in _CLAUDE_REVIEW_PROMPT

    def test_claude_rewrite_criterion_column(self):
        """Claude 리라이트 판정 기준에 칼럼 구조 조건이 포함."""
        assert "칼럼/사설 구조" in _CLAUDE_REVIEW_PROMPT

    # ── _WEAK_PATTERNS 검증 ──

    def test_weak_patterns_has_moonjeneun(self):
        """'문제는'이 _WEAK_PATTERNS에 포함."""
        assert "문제는" in _WEAK_PATTERNS

    def test_validate_catches_moonjeneun(self):
        """'문제는' 패턴이 validation에서 감지."""
        post = "문제는 기업들의 대응 속도가 느리다는 것이다."
        _, _, warnings = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)


class TestAntiContradictionRule:
    """반증 금지 규칙 검증."""

    # ── _FINALIZE_PROMPT_KO 검증 ──

    def test_finalize_has_anti_contradiction_section(self):
        """마감 프롬프트에 반증 금지 섹션이 존재."""
        assert "반증 금지" in _FINALIZE_PROMPT_KO

    def test_finalize_has_contradiction_example(self):
        """'준비가 안 돼 있다' 반증 예시가 존재."""
        assert "준비 안 됐다" in _FINALIZE_PROMPT_KO or "준비가 안 돼 있다" in _FINALIZE_PROMPT_KO

    def test_finalize_has_factual_acknowledgment_rule(self):
        """사실 인정 후 좁히기 규칙이 존재."""
        assert "사실을 인정한 뒤 좁혀라" in _FINALIZE_PROMPT_KO

    def test_finalize_selfcheck_has_contradiction(self):
        """셀프 체크 항목에 반증 체크가 존재."""
        assert "모순되는 단정" in _FINALIZE_PROMPT_KO

    # ── _CLAUDE_REVIEW_PROMPT 검증 ──

    def test_claude_has_anti_contradiction_section(self):
        """Claude 프롬프트에 반증 금지 섹션이 존재."""
        assert "반증 금지" in _CLAUDE_REVIEW_PROMPT

    def test_claude_rewrite_criterion_contradiction(self):
        """Claude 리라이트 판정 기준에 반증 조건이 포함."""
        assert "모순되는 단정" in _CLAUDE_REVIEW_PROMPT

    def test_claude_has_speed_alternative(self):
        """Claude 프롬프트에 속도 관건 대안이 존재."""
        assert "속도가 관건" in _CLAUDE_REVIEW_PROMPT


class TestColumnAndContradictionSync:
    """_FINALIZE_PROMPT_KO와 _CLAUDE_REVIEW_PROMPT 간 규칙 동기화 검증."""

    def test_both_ban_moonjeneun_pattern(self):
        """양쪽 모두 '문제는 ~것이다' 금지."""
        assert "문제는 ~것이다" in _FINALIZE_PROMPT_KO
        assert "문제는 ~것이다" in _CLAUDE_REVIEW_PROMPT

    def test_both_ban_haeksimida(self):
        """양쪽 모두 '핵심이다' 금지."""
        assert "핵심이다" in _FINALIZE_PROMPT_KO
        assert "핵심이다" in _CLAUDE_REVIEW_PROMPT

    def test_both_have_anti_contradiction(self):
        """양쪽 모두 반증 금지 규칙 보유."""
        assert "반증 금지" in _FINALIZE_PROMPT_KO
        assert "반증 금지" in _CLAUDE_REVIEW_PROMPT

    def test_both_have_column_ban(self):
        """양쪽 모두 칼럼/사설 구조 금지 섹션 보유."""
        assert "칼럼/사설 구조 금지" in _FINALIZE_PROMPT_KO
        assert "칼럼/사설 구조 금지" in _CLAUDE_REVIEW_PROMPT


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: Grok 경쟁 초안 테스트
# ═══════════════════════════════════════════════════════════════════════


class TestGrokEvalPrompt:
    """Grok X 감각 심사관 프롬프트 규칙 검증 (구조화 버전)."""

    def test_grok_prompt_exists(self):
        """_GROK_EVAL_PROMPT가 존재하고 비어있지 않음."""
        assert _GROK_EVAL_PROMPT
        assert len(_GROK_EVAL_PROMPT) > 100

    def test_grok_persona_is_editor(self):
        """Grok 페르소나가 편집자."""
        assert "편집자" in _GROK_EVAL_PROMPT

    def test_grok_persona_not_writer(self):
        """Grok 페르소나가 작성자가 아님."""
        role_section = _GROK_EVAL_PROMPT.split("━━━ 역할 ━━━")[1].split("━━━")[0]
        assert "초안 작성자" not in role_section
        assert "작가" not in role_section

    def test_grok_role_is_judgment(self):
        """구조화된 태그로 판정하는 역할."""
        assert "판정" in _GROK_EVAL_PROMPT
        assert "다시 쓰는 것이 아니라" in _GROK_EVAL_PROMPT

    def test_grok_has_score_field(self):
        """score 0~10 점수 체계 존재."""
        assert "score" in _GROK_EVAL_PROMPT
        assert "0~10" in _GROK_EVAL_PROMPT or "0-10" in _GROK_EVAL_PROMPT

    def test_grok_has_fail_tags_field(self):
        """fail_tags 배열 필드 존재."""
        assert "fail_tags" in _GROK_EVAL_PROMPT
        for tag in _GROK_VALID_FAIL_TAGS:
            assert tag in _GROK_EVAL_PROMPT, f"fail_tag '{tag}' 프롬프트에 누락"

    def test_grok_has_rewrite_scope_field(self):
        """rewrite_scope 필드 및 3가지 옵션 존재."""
        assert "rewrite_scope" in _GROK_EVAL_PROMPT
        assert "KEEP" in _GROK_EVAL_PROMPT
        assert "REWRITE_OPENER_ONLY" in _GROK_EVAL_PROMPT
        assert "REJECT_AND_REGENERATE" in _GROK_EVAL_PROMPT

    def test_grok_has_problem_field(self):
        """problem 필드 존재."""
        assert "problem" in _GROK_EVAL_PROMPT

    def test_grok_has_fix_direction_field(self):
        """fix_direction 필드 존재."""
        assert "fix_direction" in _GROK_EVAL_PROMPT

    def test_grok_bans_full_rewrite(self):
        """전체 리라이트 금지."""
        assert "다시 쓰지 마라" in _GROK_EVAL_PROMPT

    def test_grok_bans_new_facts(self):
        """새 사실/수치 추가 금지."""
        assert "새 사실" in _GROK_EVAL_PROMPT

    def test_grok_bans_custom_tags(self):
        """목록에 없는 fail_tag 생성 금지."""
        assert "목록에 없는 fail_tag" in _GROK_EVAL_PROMPT or "위 목록에 없는" in _GROK_EVAL_PROMPT

    def test_grok_output_json_format(self):
        """JSON 출력 형식에 5개 필드 모두 명시."""
        for f in ["score", "fail_tags", "rewrite_scope", "problem", "fix_direction"]:
            assert f in _GROK_EVAL_PROMPT, f"출력 필드 '{f}' 누락"

    def test_grok_score_descriptions(self):
        """점수별 설명 존재."""
        assert "기사 제목 복붙" in _GROK_EVAL_PROMPT  # score 0 설명
        assert "반드시 읽게 됨" in _GROK_EVAL_PROMPT    # score 9 설명


class TestGrokEvalCard:
    """GrokEvalCard 데이터클래스 검증 (구조화 버전)."""

    def test_eval_card_defaults(self):
        """기본값 확인."""
        card = GrokEvalCard()
        assert card.score == 5
        assert card.fail_tags == []
        assert card.rewrite_scope == "KEEP"
        assert card.problem == ""
        assert card.fix_direction == ""

    def test_eval_card_with_values(self):
        """값 설정 확인."""
        card = GrokEvalCard(
            score=3,
            fail_tags=["HEADLINE_RESTATEMENT", "PRESS_RELEASE_TONE"],
            rewrite_scope="REWRITE_OPENER_ONLY",
            problem="첫 문장이 기사 제목 복붙",
            fix_direction="구체 숫자로 시작하라",
        )
        assert card.score == 3
        assert len(card.fail_tags) == 2
        assert "HEADLINE_RESTATEMENT" in card.fail_tags
        assert card.rewrite_scope == "REWRITE_OPENER_ONLY"
        assert "복붙" in card.problem

    def test_valid_fail_tags_constant(self):
        """_GROK_VALID_FAIL_TAGS에 7개 태그 존재."""
        assert len(_GROK_VALID_FAIL_TAGS) == 7
        expected = {
            "SAME_THESIS", "PRESS_RELEASE_TONE", "POLICY_MEMO_TONE",
            "COLUMN_ENDING", "NO_READER_STAKE", "GENERIC_SKEPTICISM",
            "HEADLINE_RESTATEMENT",
        }
        assert _GROK_VALID_FAIL_TAGS == expected


class TestClaudeGrokEvalRules:
    """Claude 프롬프트의 Grok 평가 활용 규칙 검증 (구조화 버전)."""

    def test_claude_has_eval_section(self):
        """Grok 평가 활용 규칙 섹션 존재."""
        assert "Grok 평가 활용 규칙" in _CLAUDE_REVIEW_PROMPT

    def test_claude_rewrite_scope_keep_rule(self):
        """rewrite_scope=KEEP 시 사실/톤만 최소 보정."""
        assert "KEEP" in _CLAUDE_REVIEW_PROMPT

    def test_claude_rewrite_scope_opener_rule(self):
        """rewrite_scope=REWRITE_OPENER_ONLY 시 첫 문장만 다듬기."""
        assert "REWRITE_OPENER_ONLY" in _CLAUDE_REVIEW_PROMPT
        assert "첫 문장" in _CLAUDE_REVIEW_PROMPT

    def test_claude_rewrite_scope_reject_rule(self):
        """rewrite_scope=REJECT_AND_REGENERATE 시 크게 다듬기."""
        assert "REJECT_AND_REGENERATE" in _CLAUDE_REVIEW_PROMPT

    def test_claude_fail_tags_rules(self):
        """주요 fail_tags 활용 규칙 존재."""
        assert "HEADLINE_RESTATEMENT" in _CLAUDE_REVIEW_PROMPT
        assert "PRESS_RELEASE_TONE" in _CLAUDE_REVIEW_PROMPT
        assert "COLUMN_ENDING" in _CLAUDE_REVIEW_PROMPT
        assert "NO_READER_STAKE" in _CLAUDE_REVIEW_PROMPT
        assert "GENERIC_SKEPTICISM" in _CLAUDE_REVIEW_PROMPT

    def test_claude_no_thesis_change_from_grok(self):
        """Grok 평가로 논지 변경 금지."""
        assert "논지 변경" in _CLAUDE_REVIEW_PROMPT

    def test_claude_no_eval_correction_only(self):
        """평가 없을 때 사실/톤 보정만."""
        assert "사실/톤 보정만" in _CLAUDE_REVIEW_PROMPT

    def test_claude_no_new_facts_from_grok(self):
        """새 사실 추가 금지."""
        assert "새 사실 추가 금지" in _CLAUDE_REVIEW_PROMPT


class TestNoopAsync:
    """_noop_async 헬퍼 함수 테스트."""

    @pytest.mark.asyncio
    async def test_noop_returns_none(self):
        """_noop_async()가 None을 반환."""
        result = await _noop_async()
        assert result is None


class TestLogDraftComparison:
    """_log_draft_comparison 로깅 함수 테스트."""

    def test_log_with_all_components(self):
        """OpenAI + GrokEval 모두 있을 때 정상 동작."""
        oa = FinalPost(final_post="OpenAI 첫 줄", final_short="짧은 버전")
        gk = GrokEvalCard(score=7, fail_tags=["PRESS_RELEASE_TONE"], problem="보도자료체")
        _log_draft_comparison(oa, gk)

    def test_log_with_grok_none(self):
        """Grok 없을 때 정상 동작."""
        oa = FinalPost(final_post="OpenAI 첫 줄", final_short="짧은 버전")
        _log_draft_comparison(oa, None)

    def test_log_with_empty_drafts(self):
        """빈 초안도 정상 처리."""
        oa = FinalPost(final_post="", final_short="")
        _log_draft_comparison(oa, None)


class TestGrokPromptSync:
    """Grok/OpenAI/Claude 프롬프트 간 핵심 규칙 동기화 검증."""

    def test_openai_and_claude_ban_column_structure(self):
        """OpenAI/Claude 프롬프트 모두 칼럼/사설 금지."""
        assert "칼럼" in _FINALIZE_PROMPT_KO
        assert "칼럼" in _CLAUDE_REVIEW_PROMPT

    def test_openai_and_claude_ban_moonjeneun(self):
        """OpenAI/Claude 프롬프트 모두 '문제는 ~것이다' 금지."""
        assert "문제는 ~것이다" in _FINALIZE_PROMPT_KO
        assert "문제는 ~것이다" in _CLAUDE_REVIEW_PROMPT

    def test_openai_bans_unsupported_opinion(self):
        """OpenAI 프롬프트에 근거 없는 일반론 금지."""
        assert "근거 없는 일반론" in _FINALIZE_PROMPT_KO

    def test_claude_bans_thesis_change(self):
        """Claude 보정 프롬프트에 논지 변경 금지."""
        assert "논지" in _CLAUDE_REVIEW_PROMPT
        assert "건드리지 마라" in _CLAUDE_REVIEW_PROMPT

    def test_grok_eval_detects_safe_patterns(self):
        """Grok 평가 프롬프트가 평균문/안전문 감지 기준을 가짐."""
        assert "평균문" in _GROK_EVAL_PROMPT
        assert "안전" in _GROK_EVAL_PROMPT


class TestWeakPatternNewAdditions:
    """_WEAK_PATTERNS 신규 추가 패턴 검증."""

    def test_weak_pattern_pihal_su(self):
        """'피할 수 없다' 패턴이 _WEAK_PATTERNS에 있음."""
        assert "피할 수 없다" in _WEAK_PATTERNS

    def test_weak_pattern_ilukil_su(self):
        """'일으킬 수 있다' 패턴이 _WEAK_PATTERNS에 있음."""
        assert "일으킬 수 있다" in _WEAK_PATTERNS

    def test_weak_patterns_total_count(self):
        """_WEAK_PATTERNS 총 개수가 예상 범위."""
        # 기존 ~24개 + 7개 thesis dead patterns = ~31개
        assert len(_WEAK_PATTERNS) >= 31


# ─── thesis card 구조 변경 테스트 ────────────────────────────────────────────


class TestThesisCardDataclass:
    """ThesisCard dataclass 검증."""

    def test_thesis_card_fields(self):
        """ThesisCard 필드가 모두 존재."""
        tc = ThesisCard(
            thesis="비용 축",
            why_not_summary="가격 영향 분석이지 요약 아님",
            reader_stake="전세 만기 때 영향받을 수 있다",
            opener="대출 문턱이 올라간 거다.",
        )
        assert tc.thesis == "비용 축"
        assert tc.why_not_summary
        assert tc.reader_stake
        assert tc.opener

    def test_thesis_card_defaults(self):
        """ThesisCard 기본값은 모두 빈 문자열."""
        tc = ThesisCard()
        assert tc.thesis == ""
        assert tc.why_not_summary == ""
        assert tc.reader_stake == ""
        assert tc.opener == ""


class TestCandidateCardThesisIntegration:
    """CandidateCard에 thesis_cards 통합 검증."""

    def test_is_valid_with_thesis_cards(self):
        """thesis_cards가 있으면 hook_candidates 없어도 유효."""
        card = CandidateCard(
            key_facts=["팩트1"],
            thesis_cards=[ThesisCard(thesis="논지1", opener="첫 문장")],
        )
        assert card.is_valid()

    def test_is_valid_with_hooks_only(self):
        """하위호환: hook_candidates만 있어도 유효."""
        card = CandidateCard(
            key_facts=["팩트1"],
            hook_candidates=["훅1"],
        )
        assert card.is_valid()

    def test_invalid_without_both(self):
        """thesis_cards와 hook_candidates 둘 다 없으면 무효."""
        card = CandidateCard(key_facts=["팩트1"])
        assert not card.is_valid()


class TestParseThesisCards:
    """_parse_candidate_card의 thesis_cards 파싱 검증."""

    def test_parse_thesis_cards_from_json(self):
        """thesis_cards JSON이 ThesisCard 객체로 파싱."""
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "thesis_cards": [
                {
                    "thesis": "비용 축",
                    "why_not_summary": "가격 분석이지 요약 아님",
                    "reader_stake": "전기료 올라감",
                    "opener": "에너지 비용이 먼저 움직인다."
                },
                {
                    "thesis": "비교 축",
                    "why_not_summary": "한국만 취약한 이유 분석",
                    "reader_stake": "수출 기업 마진 줄어든다",
                    "opener": "한국만 유독 타격이 큰 이유가 있다."
                },
            ],
            "one_liner": ["결론"],
            "cautions": ["주의"],
            "watch_points": [],
            "certainty_level": "확정",
            "topic_tags": ["경제"],
            "risk_flags": [],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert len(card.thesis_cards) == 2
        assert card.thesis_cards[0].thesis == "비용 축"
        assert card.thesis_cards[1].reader_stake == "수출 기업 마진 줄어든다"

    def test_hook_candidates_backfill_from_openers(self):
        """thesis_cards가 있고 hook_candidates가 없으면 opener로 채움."""
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "thesis_cards": [
                {"thesis": "논지A", "why_not_summary": "x", "reader_stake": "y", "opener": "첫문장A"},
                {"thesis": "논지B", "why_not_summary": "x", "reader_stake": "y", "opener": "첫문장B"},
            ],
            "one_liner": [],
            "cautions": [],
            "watch_points": [],
            "certainty_level": "미확인",
            "topic_tags": [],
            "risk_flags": [],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert len(card.hook_candidates) == 2
        assert card.hook_candidates[0] == "첫문장A"
        assert card.hook_candidates[1] == "첫문장B"

    def test_hook_candidates_preserved_when_both(self):
        """hook_candidates와 thesis_cards 둘 다 있으면 hook_candidates 유지."""
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "hook_candidates": ["기존훅1", "기존훅2"],
            "thesis_cards": [
                {"thesis": "논지A", "opener": "첫문장A"},
            ],
            "one_liner": [],
            "cautions": [],
            "watch_points": [],
            "certainty_level": "확정",
            "topic_tags": [],
            "risk_flags": [],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert card.hook_candidates == ["기존훅1", "기존훅2"]

    def test_thesis_cards_max_3(self):
        """thesis_cards는 최대 3개까지만 파싱."""
        raw = json.dumps({
            "key_facts": ["팩트1"],
            "thesis_cards": [
                {"thesis": f"논지{i}", "opener": f"첫문장{i}"}
                for i in range(5)
            ],
            "one_liner": [],
            "cautions": [],
            "watch_points": [],
            "certainty_level": "확정",
            "topic_tags": [],
            "risk_flags": [],
        })
        card = _parse_candidate_card(raw)
        assert card is not None
        assert len(card.thesis_cards) == 3


class TestWeakPatternDeadPatterns:
    """thesis card dead pattern이 _WEAK_PATTERNS에 추가되었는지 검증."""

    def test_dead_patterns_in_weak_patterns(self):
        """thesis card dead pattern 7개가 모두 포함."""
        dead = [
            "하려는 시도다", "의지를 보여준다", "로 해석된다",
            "의도가 드러난다", "가 관건이다", "에 달려 있다", "가 결정된다",
        ]
        for pat in dead:
            assert pat in _WEAK_PATTERNS, f"dead pattern '{pat}' 누락"


class TestFinalizePromptThesisReference:
    """_FINALIZE_PROMPT_KO에 thesis 참조가 올바른지 검증."""

    def test_thesis_axis_rule(self):
        """골든룰에 '논지(thesis)' 참조."""
        p = _FINALIZE_PROMPT_KO
        assert "논지(thesis)" in p

    def test_reader_stake_reference(self):
        """reader_stake를 첫 문장에서 보여주라는 지시."""
        p = _FINALIZE_PROMPT_KO
        assert "reader_stake" in p

    def test_why_not_summary_reference(self):
        """why_not_summary를 지침으로 삼으라는 지시."""
        p = _FINALIZE_PROMPT_KO
        assert "why_not_summary" in p


class TestClaudePromptCorrectorRole:
    """Claude 보정자 역할 축소 검증."""

    def test_not_rewriter(self):
        """'더 좋은 글' 리라이트 금지."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "리라이트" in p

    def test_two_roles_only(self):
        """역할이 사실 보정 + 톤 보정 2가지로 제한."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "사실 보정" in p
        assert "톤 보정" in p

    def test_thesis_change_forbidden(self):
        """논지 변경 금지가 명시."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "논지(thesis)를 바꾸거나" in p


# ═══════════════════════════════════════════════════════════════════════════════
# 7대 검증 규칙 테스트
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidationRule1ThesisSimilarity:
    """규칙1: thesis가 key_facts와 유사하면 경고."""

    def test_similar_thesis_warns(self):
        """thesis가 key_fact와 70% 이상 겹치면 경고."""
        result = _validate_thesis_similarity(
            "삼성전자가 반도체 투자를 확대한다",
            ["삼성전자가 반도체 투자를 확대한다고 발표"]
        )
        assert result is not None

    def test_different_thesis_ok(self):
        """완전히 다른 thesis는 경고 없음."""
        result = _validate_thesis_similarity(
            "관건은 HBM 수율이 TSMC를 넘느냐다",
            ["삼성전자가 반도체 투자를 확대한다고 발표"]
        )
        assert result is None

    def test_empty_inputs_ok(self):
        """빈 입력은 경고 없음."""
        assert _validate_thesis_similarity("", []) is None
        assert _validate_thesis_similarity("test", []) is None


class TestValidationRule2HeadlineRestatement:
    """규칙2: 첫 문장이 기사 팩트 재진술이면 경고."""

    def test_restatement_warns(self):
        result = _validate_headline_restatement(
            "삼성전자가 반도체 투자를 확대한다",
            ["삼성전자가 반도체 투자를 확대한다고 발표"]
        )
        assert result is not None

    def test_unique_opener_ok(self):
        result = _validate_headline_restatement(
            "HBM 수율이 관건인 이유는 간단하다",
            ["삼성전자가 반도체 투자를 확대한다고 발표"]
        )
        assert result is None


class TestValidationRule3DeadPatterns:
    """규칙3: _WEAK_PATTERNS 감지."""

    def test_detects_weak_pattern(self):
        found = _validate_dead_patterns("추이를 봐야 한다. 중요한 시점이다.")
        assert len(found) >= 1

    def test_clean_text_ok(self):
        found = _validate_dead_patterns("HBM 수율이 3분기 갈림길이다.")
        assert len(found) == 0


class TestValidationRule4StructureDetection:
    """규칙4: 요약→의견→관건 3단 구조 감지."""

    def test_detects_column_structure(self):
        text = "정부의 의지를 보여준다. 시장 반응이 좋다. 성패는 실행에 달려 있다."
        result = _validate_structure_detection(text)
        assert result is not None

    def test_clean_structure_ok(self):
        text = "HBM 수율이 3분기 갈림길이다."
        result = _validate_structure_detection(text)
        assert result is None


class TestValidationRule5ReaderStake:
    """규칙5: reader_stake 추상성 검증."""

    def test_abstract_stake_warns(self):
        result = _validate_reader_stake("중요한 의미를 가진다")
        assert result is not None

    def test_concrete_stake_ok(self):
        result = _validate_reader_stake("전세 2억 이하 세입자는 보증금 회수 못 할 수 있다")
        assert result is None

    def test_empty_stake_warns(self):
        result = _validate_reader_stake("")
        assert result is not None

    def test_too_short_warns(self):
        result = _validate_reader_stake("중요하다")
        assert result is not None


class TestValidationRule6GrokGating:
    """규칙6: Grok fail_tags ≥ 2 게이팅."""

    def test_two_tags_warns(self):
        gk = GrokEvalCard(
            score=4,
            fail_tags=["HEADLINE_RESTATEMENT", "PRESS_RELEASE_TONE"],
            rewrite_scope="REWRITE_OPENER_ONLY",
        )
        result = _validate_grok_fail_tags_gating(gk)
        assert result is not None
        assert "2개" in result

    def test_one_tag_ok(self):
        gk = GrokEvalCard(score=7, fail_tags=["PRESS_RELEASE_TONE"])
        result = _validate_grok_fail_tags_gating(gk)
        assert result is None

    def test_no_grok_ok(self):
        result = _validate_grok_fail_tags_gating(None)
        assert result is None


class TestValidationRule7ThesisPreservation:
    """규칙7: 최종 결과가 thesis 방향을 유지하는지."""

    def test_preserved_thesis_ok(self):
        tc = ThesisCard(thesis="HBM 수율이 삼성의 갈림길이다")
        result = _validate_thesis_preservation(
            "HBM 수율 경쟁에서 삼성이 뒤처지면 갈림길을 넘기 어렵다.", tc
        )
        assert result is None

    def test_diverged_thesis_warns(self):
        tc = ThesisCard(thesis="HBM 수율이 삼성의 갈림길이다")
        result = _validate_thesis_preservation(
            "미국 연준의 금리 인하가 세계 경제를 흔든다.", tc
        )
        assert result is not None

    def test_no_thesis_ok(self):
        result = _validate_thesis_preservation("아무 글이나", None)
        assert result is None


class TestRunAllValidations:
    """_run_all_validations 통합 실행 테스트."""

    def test_clean_post_no_warnings(self):
        """깨끗한 글에는 경고 없음."""
        card = CandidateCard(key_facts=["미국 CPI 발표"])
        tc = ThesisCard(
            thesis="CPI 둔화가 한국 수출에 미치는 영향",
            reader_stake="수출 기업 주가가 CPI 둔화 폭에 연동될 수 있다",
        )
        warnings = _run_all_validations(
            "CPI 둔화 폭이 한국 수출 기업 주가를 좌우한다.",
            card=card,
            selected_thesis=tc,
        )
        # 경고가 아예 없거나 최소
        assert len(warnings) <= 1

    def test_bad_post_multiple_warnings(self):
        """문제 많은 글은 여러 경고."""
        card = CandidateCard(key_facts=["삼성전자 반도체 투자 확대 발표"])
        tc = ThesisCard(
            thesis="삼성전자 반도체 투자 확대",
            reader_stake="중요한 의미를 가진다",
        )
        gk = GrokEvalCard(
            score=2,
            fail_tags=["HEADLINE_RESTATEMENT", "PRESS_RELEASE_TONE", "NO_READER_STAKE"],
            rewrite_scope="REJECT_AND_REGENERATE",
        )
        warnings = _run_all_validations(
            "삼성전자 반도체 투자 확대 발표. 추이를 봐야 한다.",
            card=card,
            selected_thesis=tc,
            grok_eval=gk,
        )
        assert len(warnings) >= 3
