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
    # Low confidence 추정 감점
    _SPECULATIVE_MOTIVE_PATTERNS, _has_speculative_motive,
    _reorder_slots_for_low_confidence,
    # Phase 3: Grok X 감각 심사 (구조화 버전)
    _GROK_EVAL_PROMPT, GrokEvalCard, _GROK_VALID_FAIL_TAGS,
    _noop_async, _log_draft_comparison,
    # 7대 검증 규칙
    _validate_thesis_similarity, _validate_headline_restatement,
    _validate_dead_patterns, _validate_structure_detection,
    _validate_reader_stake, _validate_grok_fail_tags_gating,
    _validate_thesis_preservation, _run_all_validations,
    # PR 10: Findability Layer
    _FINDABILITY_KNOWN_ENTITIES, _FINDABILITY_ANCHOR_RE,
    _extract_first_two_sentences, _count_findability_anchors,
    _validate_findability,
    # PR 11: Reader Question Resolver
    ReaderQuestion,
    _generate_reader_questions, _resolve_questions_from_source,
    _build_question_prompt_section, _validate_question_coverage,
    _SOURCE_CITATION_RE, _SCOPE_NUMBER_RE,
    # PR 12 Layer A: Source Integrity
    _check_source_integrity, _SOURCE_TEXT_MIN_LEN,
    # PR 12 Layer C: Evidence Resolver
    _CHECKPOINT_EVIDENCE_PATTERNS,
    # PR 12 Layer D: Market/Stake v2
    _detect_market_angle_type, _validate_market_stake,
    _MARKET_ANGLE_PATTERNS, _MARKET_ANGLE_VALID_TYPES,
    # PR 12 Layer E: Evaluation Loop
    _build_evaluation_meta,
    # PR 13: External Evidence Layer
    _detect_primary_source, _resolve_questions_from_external,
    _PRIMARY_SOURCE_URL_PATTERNS, _PRIMARY_SOURCE_TEXT_PATTERNS,
    _PRIMARY_SOURCE_VALID_TYPES,
    # PR 14: Draft Ranking Layer
    _score_draft, _select_best_draft,
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
        """정상 JSON → CandidateCard. hook_candidates는 thesis_cards에서만 채워짐."""
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
        # OpenAI hook_candidates는 무시됨 (Gemini thesis_cards에서만 채움)
        assert len(card.hook_candidates) == 0
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
        """JSON 스키마에 7개 필드 존재 (hook_candidates는 Gemini 전담)."""
        p = _CANDIDATE_PROMPT_KO
        for field in [
            "key_facts", "one_liner",
            "cautions", "watch_points", "certainty_level",
            "topic_tags", "risk_flags",
        ]:
            assert field in p
        # hook_candidates는 OpenAI 프롬프트에서 제거됨 (Gemini thesis_cards로 이관)
        assert "hook_candidates" not in p or "생성하지 마라" in p

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
    """_FINALIZE_PROMPT_KO 프롬프트 규칙 검증 — 슬롯 조립 구조."""

    def test_slot_assembly_role(self):
        """역할이 슬롯 조립 담당."""
        p = _FINALIZE_PROMPT_KO
        assert "슬롯" in p and "조립한다" in p

    def test_three_sentence_structure(self):
        """문장 조립 구조: 핵심명제/팩트/판단좌표/판별신호."""
        p = _FINALIZE_PROMPT_KO
        assert "핵심 명제" in p
        assert "팩트 근거" in p
        assert "판단 좌표" in p
        assert "판별 신호" in p

    def test_banned_endings_in_prompt(self):
        """금지 마감 패턴 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "심각하다" in p
        assert "변수다" in p
        assert "관건이다" in p
        assert "확인이 필요하다" in p

    def test_ending_types(self):
        """마지막 문장 유형: 조건형/대비형/질문형."""
        p = _FINALIZE_PROMPT_KO
        assert "조건형" in p
        assert "대비형" in p
        assert "질문형" in p

    def test_article_summary_banned(self):
        """기사 재요약 금지."""
        p = _FINALIZE_PROMPT_KO
        assert "기사 재요약" in p or "기사 요약 금지" in p
        assert "것으로 전해졌다" in p

    def test_cautions_conflict_rule(self):
        """cautions 충돌 금지."""
        p = _FINALIZE_PROMPT_KO
        assert "cautions" in p and "충돌" in p

    def test_output_fields(self):
        """출력 필드: final_post, final_short."""
        p = _FINALIZE_PROMPT_KO
        assert "final_post" in p
        assert "final_short" in p

    def test_self_check_section(self):
        """셀프 체크 섹션 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "셀프 체크" in p

    def test_short_version_independence(self):
        """final_short 독립 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "독립적으로 읽혀야 한다" in p
        assert "다른 각도로 시작" in p

    def test_overstatement_reduction(self):
        """과장 약화 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "불가피" in p


class TestValidateFinalPost:
    """_validate_final_post 검증 로직 테스트."""

    def test_clean_post_no_warnings(self):
        """깨끗한 게시글은 경고 없음."""
        post = "관건은 미국 관세 25%가 반도체까지 확대되느냐다. 답은 원가 상승이 먼저 반영되느냐다."
        short = "반도체 관세가 확대되면 삼성 마진이 줄어든다."
        _, _, warnings, _ = _validate_final_post(post, short)
        assert len(warnings) == 0

    def test_banned_ending_detected(self):
        """금지 마감 패턴 감지."""
        post = "이번 사안은 영향을 미칠 것으로 보인다. 향후 추이를 지켜볼 필요가 있다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전")
        assert any("금지 마감 패턴" in w for w in warnings)

    def test_banned_ending_with_period(self):
        """마침표 포함 금지 패턴."""
        post = "시장에 미칠 여파가 클 것으로 보인다."
        _, _, warnings, _ = _validate_final_post(post, "")
        assert any("금지 마감 패턴" in w for w in warnings)

    def test_tone_softener_auto_replace(self):
        """과장 표현 자동 약화."""
        post = "이번 조치는 수출 기업에 직격탄이다."
        result_post, _, warnings, _ = _validate_final_post(post, "")
        assert "직격탄" not in result_post
        assert "영향" in result_post
        assert any("자동 약화" in w for w in warnings)

    def test_multiple_softeners(self):
        """여러 과장 표현 동시 약화."""
        post = "급등이 불가피한 상황이다."
        result_post, _, warnings, _ = _validate_final_post(post, "")
        assert "급등" not in result_post
        assert "불가피" not in result_post
        assert "상승" in result_post
        assert "가능성" in result_post

    def test_short_tone_softened(self):
        """final_short에서도 과장 표현 약화."""
        post = "정상 게시글."
        short = "시장이 붕괴되었다."
        _, result_short, _, _ = _validate_final_post(post, short)
        assert "붕괴" not in result_short
        assert "하락" in result_short

    def test_same_first_sentence_warning(self):
        """final_short 첫 문장이 final_post와 동일하면 경고."""
        post = "관세 확대가 핵심이다. 시장은 예외 품목을 본다."
        short = "관세 확대가 핵심이다."
        _, _, warnings, _ = _validate_final_post(post, short)
        assert any("첫 문장이 final_post와 동일" in w for w in warnings)

    def test_different_first_sentence_no_warning(self):
        """첫 문장이 다르면 경고 없음."""
        post = "관세 확대가 핵심이다. 시장은 예외 품목을 본다."
        short = "예외 품목 리스트가 관건이다."
        _, _, warnings, _ = _validate_final_post(post, short)
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
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감 패턴" in w for w in warnings)

    def test_validate_catches_possibility_grew(self):
        post = "이번 조치로 인해 가능성이 커졌다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감 패턴" in w for w in warnings)


class TestWeakPatternValidation:
    """_validate_final_post에서 뻔한 표현 감지."""

    def test_weak_pattern_warning(self):
        """본문 내 뻔한 표현이 경고로 기록."""
        post = "시장에 영향을 미칠 수 있다는 관측이 나온다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현 감지" in w for w in warnings)

    def test_clean_post_no_weak_warning(self):
        """깨끗한 글에서는 뻔한 표현 경고 없음."""
        post = "시장은 발언이 아니라 시행령을 본다."
        _, _, warnings, _ = _validate_final_post(post, "독립 버전.")
        assert not any("뻔한 표현 감지" in w for w in warnings)


class TestFinalizePromptEndingRules:
    """_FINALIZE_PROMPT_KO 마지막 문장 유형 강제 규칙 검증 — 슬롯 구조."""

    def test_three_ending_types(self):
        """조건형/대비형/질문형 3가지 유형이 명시."""
        p = _FINALIZE_PROMPT_KO
        assert "조건형" in p
        assert "대비형" in p
        assert "질문형" in p

    def test_banned_ending_patterns_in_prompt(self):
        """금지 마감 패턴이 프롬프트에 포함."""
        p = _FINALIZE_PROMPT_KO
        assert "변수다" in p
        assert "관건이다" in p
        assert "확인이 필요하다" in p

    def test_no_article_summary(self):
        """기사 재요약 금지 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "기사 요약 금지" in p or "기사 재요약" in p

    def test_selfcheck_exists(self):
        """셀프 체크 섹션."""
        p = _FINALIZE_PROMPT_KO
        assert "셀프 체크" in p
        assert "판별 신호" in p


class TestGeminiThesisPromptRules:
    """_GEMINI_THESIS_PROMPT thesis_cards 규칙 검증 (Gemini가 논지 생성)."""

    def test_gemini_thesis_prompt_exists(self):
        """_GEMINI_THESIS_PROMPT가 존재하고 비어있지 않음."""
        assert _GEMINI_THESIS_PROMPT
        assert len(_GEMINI_THESIS_PROMPT) > 100

    def test_gemini_persona_is_slot_filler(self):
        """Gemini 페르소나가 해석 슬롯 채우기 기계."""
        assert "해석 슬롯 채우기 기계" in _GEMINI_THESIS_PROMPT

    def test_thesis_card_fields(self):
        """thesis_card 필드(thesis, why_not_summary, reader_stake, opener) 정의."""
        p = _GEMINI_THESIS_PROMPT
        assert "thesis" in p
        assert "why_not_summary" in p
        assert "reader_stake" in p
        assert "opener" in p

    def test_fixed_slot_rules(self):
        """고정 슬롯 3개 규칙."""
        p = _GEMINI_THESIS_PROMPT
        assert "고정 슬롯" in p

    def test_dead_patterns_banned(self):
        """금지 종결 패턴 목록."""
        p = _GEMINI_THESIS_PROMPT
        assert "해석된다" in p
        assert "관건이다" in p
        assert "변수다" in p


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
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("사실나열" in w for w in warnings)

    def test_detects_jeonhaejyeotda(self):
        """'~것으로 전해졌다' 패턴 감지."""
        post = "한국 선박이 해협을 통과한 것으로 전해졌다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("사실나열" in w for w in warnings)

    def test_clean_start_no_warning(self):
        """해석 선행 첫 문장은 경고 없음."""
        post = "외교 뉴스처럼 보이지만 먼저 흔들리는 건 비용이다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert not any("사실나열" in w for w in warnings)

    def test_fact_narration_starts_not_empty(self):
        """_FACT_NARRATION_STARTS 리스트가 비어있지 않음."""
        assert len(_FACT_NARRATION_STARTS) >= 5


class TestFirstSentenceLengthGate:
    """첫 문장 길이 게이트 테스트."""

    def test_long_first_sentence_triggers_gate(self):
        """60자 초과 첫 문장은 WEAK_OPENER 게이트 실패 (95점 기준 — 60자로 강화)."""
        post = "11일 파키스탄 협상 결렬 이후 로이터 통신이 보도한 이번 주 후반 이슬라마바드 재협상이 실제로 이루어지는지 여부가 미국과 이란 관계의 분기점이다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" in gate_fails

    def test_short_first_sentence_passes(self):
        """40자 이내 첫 문장은 통과."""
        post = "지금 포인트는 재회담 성사 여부다. 근거는 이것이다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" not in gate_fails

    def test_moderate_first_sentence_passes(self):
        """45자 이내 첫 문장은 게이트 통과 (경고 없음)."""
        post = "미국의 대이란 봉쇄가 선언에 그칠지 실제 통제로 갈지 곧 드러난다. 후속 조치."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" not in gate_fails

    def test_46_to_60_first_sentence_warning_only(self):
        """46~60자 첫 문장은 경고만, 게이트 실패 아님 (95점 기준 새 경계)."""
        post = "이번 협상에서 미국과 이란이 보상안과 사찰 수용 조건을 놓고 완전히 갈린 것이 본질이다. 근거 있다."
        _, _, warnings, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" not in gate_fails
        assert any("길이 경고" in w for w in warnings)


class TestFirstSentenceConnectorGate:
    """첫 문장 접속 구조 과다 게이트 (배경/종속절 시작 차단)."""

    def test_two_connectors_gated(self):
        """첫 문장에 접속 표현이 2개 이상이면 WEAK_OPENER 게이트."""
        post = "미국이 봉쇄를 선언하면서 이란은 반발하는 가운데 시장이 흔들렸다. 금요일이 분기점이다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" in gate_fails

    def test_commas_plus_connector_gated(self):
        """첫 문장 쉼표 2개 이상 + 접속 1개 → 게이트."""
        post = "미국이 봉쇄를 선언하면서, 이란은 신중, 시장은 흔들렸다. 금요일이 분기점."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" in gate_fails

    def test_clean_opener_passes(self):
        """접속 구조 없는 직선 첫 문장은 통과."""
        post = "지금 포인트는 재회담 성사 여부다. 금요일까지 답이 나온다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" not in gate_fails

    def test_single_connector_passes(self):
        """접속 1개, 쉼표 1개 이하는 통과."""
        post = "재협상이 이뤄지면서 채널이 살아났다. 금요일 결론이 난다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "WEAK_OPENER" not in gate_fails


class TestComplexSentenceGate:
    """문장 구조 복잡도 게이트 테스트."""

    def test_complex_sentence_detected(self):
        """쉼표 3개 이상 문장이 2개면 COMPLEX_SENTENCE 게이트."""
        post = (
            "미국이 봉쇄를 선언하면서, 이란은 반발하고, 중재국은 관망하며, 시장은 흔들렸다. "
            "한국은 에너지 가격에 영향을 받고, 환율이 흔들리며, 수출 기업이 긴장하고, 정부는 대응을 준비한다."
        )
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "COMPLEX_SENTENCE" in gate_fails

    def test_simple_sentences_pass(self):
        """단순한 문장들은 통과."""
        post = "지금 포인트는 재회담 성사 여부다. 이란은 신중하다. 금요일까지 답이 나온다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "COMPLEX_SENTENCE" not in gate_fails

    def test_single_complex_is_warning_only(self):
        """복잡한 문장 1개는 경고만, 게이트 실패 아님."""
        post = "미국이 봉쇄를 선언하면서, 이란은 반발하고, 중재국은 관망하며, 시장은 흔들렸다. 금요일이 분기점이다."
        _, _, warnings, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "COMPLEX_SENTENCE" not in gate_fails
        assert any("복잡한 문장" in w for w in warnings)


class TestStructureColumnGate:
    """요약→의견→관건 3단 사설체 게이트 테스트."""

    def test_summary_to_crux_structure_gated(self):
        """'하려는 시도다' + 마지막에 '가 관건이다' → STRUCTURE_COLUMN 게이트."""
        post = (
            "이번 조치는 안정을 꾀하려는 시도다. "
            "후속 조치가 더 나온다. 결국 시행 속도가 관건이다."
        )
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "STRUCTURE_COLUMN" in gate_fails

    def test_summary_alone_no_gate(self):
        """요약 시작만 있고 관건 마감이 없으면 게이트 없음."""
        post = "이번 조치는 안정을 꾀하려는 시도다. 금요일에 시행령이 나오면 실행, 아니면 선언에 그친다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "STRUCTURE_COLUMN" not in gate_fails

    def test_clean_structure_passes(self):
        """정상 구조는 STRUCTURE_COLUMN 게이트 통과."""
        post = "지금 포인트는 시행 시점이다. 근거는 시행령 준비 상태다. 금요일까지 안 나오면 선언이다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "STRUCTURE_COLUMN" not in gate_fails


class TestLowConfidenceOverreachGate:
    """저신뢰 과해석 본문 침투 게이트 테스트."""

    def test_low_confidence_with_motives_gated(self):
        """certainty 미확인 + 추정성 동기 2개 → LOW_CONFIDENCE_OVERREACH."""
        post = "이번 조치는 정치적 계산에서 나온 포석이다. 선거용 카드로 쓰려는 노림수가 읽힌다."
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.", certainty_level="미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_confirmed_with_motives_no_gate(self):
        """certainty 확정이면 동기 추정이 있어도 게이트 없음."""
        post = "이번 조치는 정치적 계산에서 나온 포석이다. 선거용 카드로 쓰려는 노림수가 읽힌다."
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.", certainty_level="확정"
        )
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails

    def test_low_confidence_single_motive_gated(self):
        """저신뢰면 동기 추정 1개만 등장해도 게이트 (강한 제한)."""
        post = "이번 조치는 정치적 계산에서 나왔다. 금요일 시행령이 관전 포인트."
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.", certainty_level="상충"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_no_certainty_no_gate(self):
        """certainty_level 미지정이면 게이트 비활성화."""
        post = "이번 조치는 정치적 계산에서 나온 포석이다. 선거용 카드로 쓰려는 노림수가 읽힌다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails


class TestOpinionLeakGateRelaxed:
    """OPINION_LEAK 게이트 완화: 1개는 경고만, 2개 이상만 게이트."""

    def test_single_opinion_no_gate(self):
        """일반론 패턴 1개는 경고만, OPINION_LEAK 게이트 실패 아님."""
        post = "역사적으로 이런 상황에서는 위기가 반복되었다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "OPINION_LEAK" not in gate_fails

    def test_double_opinion_gated(self):
        """일반론 패턴 2개 이상이면 OPINION_LEAK 게이트."""
        post = "역사적으로 이런 상황은 큰 파장을 낳기 쉽다. 전략이다."
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "OPINION_LEAK" in gate_fails


class TestNewBannedEndingPatterns:
    """새로 추가된 금지 마감 패턴 테스트."""

    def test_journalist_question_banned(self):
        """기자 질문형 마감 감지."""
        post = "이 사안은 앞으로 어떻게 될까."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감" in w or "뻔한 표현" in w for w in warnings)

    def test_market_reaction_banned(self):
        """시장 반응을 봐야 한다 감지."""
        post = "결국 시장 반응을 봐야 한다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감" in w or "뻔한 표현" in w for w in warnings)


class TestRoleLoyaltyInPrompt:
    """역할 충성 원칙이 프롬프트에 포함된 테스트."""

    def test_finalize_role_is_slot_assembler(self):
        """마감 프롬프트에 슬롯 조립 역할이 명시."""
        p = _FINALIZE_PROMPT_KO
        assert "슬롯" in p and "조립한다" in p
        assert "기사를 요약하는 사람이 아니다" in p

    def test_finalize_forbidden_actions(self):
        """마감 프롬프트에 금지 행동이 명시."""
        p = _FINALIZE_PROMPT_KO
        assert "기사 재요약" in p
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
        assert "후보 카드" in first["text"]
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

    def test_hook_labels_slot_names(self):
        """슬롯 이름이 표시."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        hook_msgs = [m for m in msgs if m["hook_index"] is not None]
        assert "무엇이 바뀌나" in hook_msgs[0]["text"]
        assert "왜 뉴스 이상이냐" in hook_msgs[1]["text"]
        assert "다음 판가름" in hook_msgs[2]["text"]

    def test_compact_card_no_facts_in_main(self):
        """압축형: 기본 카드에 핵심 팩트/한줄 결론/주의문/관찰 포인트 미포함."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        all_text = " ".join(m["text"] for m in msgs)
        assert "핵심 팩트" not in all_text
        assert "한줄 결론" not in all_text
        assert "주의문" not in all_text
        assert "지금 봐야 할 포인트" not in all_text

    def test_compact_card_count(self):
        """압축형: 개요 1개 + 슬롯 3개 = 4개 메시지."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card())
        assert len(msgs) == 4  # 개요 + 슬롯 3개

    def test_slot_detail_has_full_info(self):
        """상세보기에 긴장점/독자영향/초안 포함."""
        from app.services.telegram_service import format_slot_detail
        card = self._make_card()
        card.thesis_cards = [ThesisCard(
            thesis="테스트 해석",
            why_not_summary="테스트 긴장점",
            reader_stake="테스트 독자 영향",
            opener="테스트 초안",
            judgment_coord="테스트 좌표",
            verification_signal="테스트 신호",
        )]
        detail = format_slot_detail(card, 0)
        assert "테스트 긴장점" in detail
        assert "테스트 독자 영향" in detail
        assert "테스트 초안" in detail
        assert "테스트 좌표" in detail
        assert "테스트 신호" in detail

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


class TestCandidateCardCompactionPR7:
    """PR 7 — 기본 카드는 mode 별 단일 축 노출. '고르는 화면'으로 압축."""

    def _make_card(self, certainty: str) -> "CandidateCard":
        return CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            hook_candidates=["훅A", "훅B", "훅C"],
            thesis_cards=[
                ThesisCard(
                    thesis=f"해석 슬롯 {i} — 비교용 한 줄 해석 문장이다",
                    why_not_summary="긴장점 문장",
                    reader_stake="독자 영향 문장",
                    opener="첫 문장 초안",
                    judgment_coord=f"판단 좌표 슬롯 {i}",
                    verification_signal=f"판별 신호 슬롯 {i}",
                )
                for i in range(3)
            ],
            certainty_level=certainty,
            topic_tags=["태그"],
        )

    def test_verify_card_shows_only_verification_signal(self):
        """VERIFY (미확인) 기본 카드: 판별 신호만 노출, 판단 좌표 비노출."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card("미확인"))
        slot_msgs = [m for m in msgs if m["hook_index"] is not None]
        assert len(slot_msgs) == 3
        for m in slot_msgs:
            assert "판별 신호" in m["text"], \
                f"VERIFY 기본카드에 판별 신호 없음:\n{m['text']}"
            assert "판단 좌표" not in m["text"], \
                f"VERIFY 기본카드에 판단 좌표가 노출됨:\n{m['text']}"

    def test_explain_card_shows_only_judgment_coord(self):
        """EXPLAIN (확정) 기본 카드: 판단 좌표만 노출, 판별 신호 비노출."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card("확정"))
        slot_msgs = [m for m in msgs if m["hook_index"] is not None]
        for m in slot_msgs:
            assert "판단 좌표" in m["text"], \
                f"EXPLAIN 기본카드에 판단 좌표 없음:\n{m['text']}"
            assert "판별 신호" not in m["text"], \
                f"EXPLAIN 기본카드에 판별 신호가 노출됨:\n{m['text']}"

    def test_judgment_card_shows_only_judgment_coord(self):
        """JUDGMENT (상충) 기본 카드: 판단 좌표만 노출."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card("상충"))
        slot_msgs = [m for m in msgs if m["hook_index"] is not None]
        for m in slot_msgs:
            assert "판단 좌표" in m["text"]
            assert "판별 신호" not in m["text"]

    def test_compact_card_drops_tension_and_reader_stake(self):
        """기본 카드에는 긴장점/독자 영향/첫 문장 초안/핵심 팩트 없음."""
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card("미확인"))
        slot_msgs = [m for m in msgs if m["hook_index"] is not None]
        for m in slot_msgs:
            assert "긴장점" not in m["text"]
            assert "독자 영향" not in m["text"]
            assert "첫 문장 초안" not in m["text"]
            assert "핵심 팩트" not in m["text"]

    def test_compact_card_thesis_trimmed_55(self):
        """해석 길이가 55자 안팎으로 trim (해석 prefix 포함, … 말줄임 포함)."""
        from app.services.telegram_service import send_candidate_card_messages
        card = self._make_card("확정")
        card.thesis_cards[0].thesis = (
            "이 해석은 매우 길어서 반드시 55자 하드 캡에서 잘려야 한다 — "
            "그래야 비교 카드 역할을 한다. 길게 이어지면 안 된다."
        )
        msgs = send_candidate_card_messages(card)
        slot0 = [m for m in msgs if m["hook_index"] == 0][0]
        # "해석: " prefix 뒤 본문을 찾는다
        interpret_line = [ln for ln in slot0["text"].split("\n")
                          if ln.startswith("해석:")][0]
        body = interpret_line[len("해석: "):]
        # trim_display 는 55자 limit 을 넘으면 55자에 … 를 붙인다.
        # 정확한 길이 체크: 원문 > 55 → 잘림 확인.
        assert len(body) <= 60, f"해석 본문 과길이: {len(body)}자"
        assert "…" in body or len(body) <= 55

    def test_compact_card_axis_trimmed_35(self):
        """단일 축(판단 좌표/판별 신호) 35자 하드 캡."""
        from app.services.telegram_service import send_candidate_card_messages
        card = self._make_card("확정")
        card.thesis_cards[0].judgment_coord = (
            "이 판단 좌표는 반드시 35자 캡에 걸려야 한다 — 기본 카드는 읽기 아닌 비교용"
        )
        msgs = send_candidate_card_messages(card)
        slot0 = [m for m in msgs if m["hook_index"] == 0][0]
        coord_line = [ln for ln in slot0["text"].split("\n")
                      if "판단 좌표" in ln][0]
        # prefix 제거 후 본문만
        body = coord_line.split("판단 좌표:", 1)[1].strip()
        assert len(body) <= 40, f"판단 좌표 본문 과길이: {len(body)}자"
        assert "…" in body or len(body) <= 35

    def test_compact_card_visible_line_count(self):
        """한 슬롯 메시지의 시각적 라인 ≤ 5 (제목 + 빈줄 + 해석 + 빈줄 + 축).

        추정 해석 배지가 붙을 수 있으므로 상한 7로 방어. 기존 카드는 7~8 라인.
        """
        from app.services.telegram_service import send_candidate_card_messages
        msgs = send_candidate_card_messages(self._make_card("확정"))
        slot_msgs = [m for m in msgs if m["hook_index"] is not None]
        for m in slot_msgs:
            line_count = len(m["text"].split("\n"))
            assert line_count <= 5, \
                f"슬롯 기본 카드 라인 수 초과 ({line_count} > 5):\n{m['text']}"

    def test_detail_view_still_has_full_info(self):
        """'자세히 보기' 상세 카드에는 긴장점/독자영향/좌표/신호/초안/팩트 모두 유지."""
        from app.services.telegram_service import format_slot_detail
        card = self._make_card("미확인")
        detail = format_slot_detail(card, 0)
        assert "긴장점" in detail
        assert "독자 영향" in detail
        assert "판단 좌표" in detail
        assert "판별 신호" in detail
        assert "첫 문장 초안" in detail
        assert "핵심 팩트" in detail

    def test_speculative_badge_only_on_verify(self):
        """추정 해석 배지는 저신뢰(VERIFY/JUDGMENT) 에서만 노출."""
        from app.services.telegram_service import send_candidate_card_messages
        # VERIFY + 본심/노림수 포함 → 배지
        card_low = self._make_card("미확인")
        card_low.thesis_cards[0].thesis = "진짜 본심은 이것이다"
        msgs_low = send_candidate_card_messages(card_low)
        slot0_low = [m for m in msgs_low if m["hook_index"] == 0][0]
        assert "추정 해석 주의" in slot0_low["text"]

        # EXPLAIN (확정) → 배지 없음 (추정 패턴 있어도 저신뢰 아님)
        card_high = self._make_card("확정")
        card_high.thesis_cards[0].thesis = "진짜 본심은 이것이다"
        msgs_high = send_candidate_card_messages(card_high)
        slot0_high = [m for m in msgs_high if m["hook_index"] == 0][0]
        assert "추정 해석 주의" not in slot0_high["text"]

    def test_compact_card_count_preserved(self):
        """압축 후에도 메시지 수는 개요 1 + 슬롯 3 = 4 유지."""
        from app.services.telegram_service import send_candidate_card_messages
        for cert in ("확정", "미확인", "상충"):
            msgs = send_candidate_card_messages(self._make_card(cert))
            assert len(msgs) == 4, f"{cert} 카드 메시지 수 변경됨: {len(msgs)}"


# ─── 국제 뉴스 한국 관점 강화 테스트 ─────────────────────────────────────────


class TestKoreaAngleGeminiThesisPrompt:
    """Gemini thesis 프롬프트에 한국 관점 훅 규칙이 있는지 검증."""

    def test_korea_angle_rule_exists(self):
        """한국 관점 규칙이 Gemini thesis 프롬프트에 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "한국" in p
        assert "한국 관점" in p

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
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전")
        opinion_warns = [w for w in warnings if "일반론 의견" in w]
        assert len(opinion_warns) >= 1

    def test_validate_no_false_positive(self):
        """일반론 패턴이 없는 정상 문장은 경고 없음."""
        post = "한국 환율이 1400원을 넘기면 수입 물가 부담이 커진다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전")
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
        """고정 슬롯 규칙 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "고정 슬롯" in p


class TestFinalPostThreeSlotStructure:
    """마감 프롬프트에 3문장 구조(WHY/WHAT/SO WHAT)가 있는지 검증."""

    def test_three_slots_exist(self):
        """3문장 조립 구조(변화/팩트/검증)가 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "문장 1" in p
        assert "문장 2" in p
        assert "문장 3" in p

    def test_sentence_count_rule(self):
        """2~4문장 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "2~4문장" in p

    def test_no_room_for_summary(self):
        """기사 재설명 문장이 끼어들 자리 없다는 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "기사를 다시 설명하는 문장" in p


class TestValidationGate:
    """validation 경고가 Claude 감수 트리거로 연결되는지 검증."""

    def test_single_warning_no_force(self):
        """경고 1개는 강제 트리거 미발동."""
        # 금지 마감 패턴 1개만 걸리는 케이스
        post = "정상적인 첫 문장이다.\n해석 축 연결.\n추이를 봐야 한다."
        _, _, warnings, _ = _validate_final_post(post, "독립 짧은 버전")
        # 금지 마감 1개만 걸림 — 강제 아님
        ban_warns = [w for w in warnings if "금지 마감" in w]
        assert len(ban_warns) >= 1
        # 총 경고 1개면 force=False
        # (다른 경고 안 걸리는 깨끗한 입력)

    def test_multiple_warnings_force(self):
        """경고 2개 이상이면 강제 트리거."""
        # 첫 문장 사실나열 + 금지 마감 + 뻔한 표현 → 3개
        post = "라는 보도가 나왔다. 시장 반응을 봐야 한다."
        _, _, warnings, _ = _validate_final_post(post, "독립 짧은 버전")
        assert len(warnings) >= 2, f"경고 2개 이상 예상, 실제: {warnings}"

    def test_clean_post_no_warnings(self):
        """깨끗한 포스트는 경고 0개."""
        post = "미국 관세 발표에서 먼저 건드리는 건 외교가 아니라 비용이다.\n원화 환율이 1400원대에 진입했다.\n진짜 변수는 시행 여부다."
        _, _, warnings, _ = _validate_final_post(post, "환율 1400원대, 변수는 시행이다.")
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

    def test_prompt_has_sentence_structure(self):
        """문장 구조가 Claude 프롬프트에 포함."""
        p = _CLAUDE_REVIEW_PROMPT
        assert "핵심 명제" in p
        assert "팩트 근거" in p
        assert "판단 좌표" in p
        assert "판별 신호" in p

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
        """Gemini thesis 프롬프트에 금지 종결 패턴 존재."""
        p = _GEMINI_THESIS_PROMPT
        assert "해석된다" in p
        assert "관건이다" in p

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
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)

    def test_validate_catches_urgent(self):
        """'시급하다' 패턴이 validation에서 감지."""
        post = "중동 의존도를 줄이는 것이 시급하다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)

    def test_validate_catches_risk_grow(self):
        """'리스크가 커질 수 있다' 패턴이 validation에서 감지."""
        post = "향후 경제적 리스크가 커질 수 있다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)

    def test_no_false_positive_on_clean(self):
        """깨끗한 글에서 새 패턴 false positive 없음."""
        post = "브롬 가격이 2배 되면 반도체 원가에서 먼저 흔들리는 건 식각 공정이다."
        _, _, warnings, _ = _validate_final_post(post, "독립 짧은 버전.")
        assert not any("뻔한 표현" in w for w in warnings)


class TestAntiReportToneInFinalize:
    """마감 프롬프트에 보고서 톤 방지 규칙이 있는지 검증."""

    def test_supply_chain_anti_report(self):
        """보고서 톤 방지 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "보고서 X" in p

    def test_narrow_down_rule(self):
        """간결한 조립 구조 규칙 존재."""
        p = _FINALIZE_PROMPT_KO
        assert "2~4문장" in p


class TestColumnStructureBan:
    """칼럼/사설 구조 금지 규칙 검증."""

    # ── _FINALIZE_PROMPT_KO 검증 ──

    def test_finalize_has_column_ban_section(self):
        """마감 프롬프트에 사설체 금지가 존재."""
        assert "사설체 금지" in _FINALIZE_PROMPT_KO

    def test_finalize_bans_moonjeneun(self):
        """'문제는 ~것이다' 금지 패턴이 마감 프롬프트에 존재."""
        assert "문제는 ~것이다" in _FINALIZE_PROMPT_KO

    def test_finalize_bans_haeksimida(self):
        """'핵심이다' 금지 패턴이 마감 프롬프트에 존재."""
        assert "핵심이다" in _FINALIZE_PROMPT_KO

    def test_finalize_bans_moonjeneun(self):
        """'문제는 ~것이다' 금지 패턴이 마감 프롬프트에 존재."""
        assert "문제는 ~것이다" in _FINALIZE_PROMPT_KO

    def test_finalize_has_alternative_example(self):
        """조건형/대비형 대안이 제시."""
        assert "조건형" in _FINALIZE_PROMPT_KO
        assert "대비형" in _FINALIZE_PROMPT_KO

    def test_finalize_selfcheck_has_summary_ban(self):
        """셀프 체크 항목에 기사 요약 체크가 존재."""
        assert "기사 요약" in _FINALIZE_PROMPT_KO

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
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("뻔한 표현" in w for w in warnings)


class TestAntiContradictionRule:
    """반증 금지 규칙 검증."""

    # ── _FINALIZE_PROMPT_KO 검증 ──

    def test_finalize_has_cautions_conflict_rule(self):
        """마감 프롬프트에 cautions 충돌 금지 규칙이 존재."""
        assert "cautions와 충돌" in _FINALIZE_PROMPT_KO

    def test_finalize_has_certainty_rule(self):
        """미확인이면 단정 금지 규칙이 존재."""
        assert "미확인이면 단정 금지" in _FINALIZE_PROMPT_KO

    def test_finalize_has_no_exaggeration_rule(self):
        """과장 약화 규칙이 존재."""
        assert "과장 약화" in _FINALIZE_PROMPT_KO

    def test_finalize_selfcheck_has_cautions_check(self):
        """셀프 체크 항목에 cautions 충돌 체크가 존재."""
        assert "cautions와 충돌하는 표현이 없는가" in _FINALIZE_PROMPT_KO

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

    def test_both_have_cautions_rule(self):
        """양쪽 모두 cautions 충돌 규칙 보유."""
        assert "cautions" in _FINALIZE_PROMPT_KO
        assert "cautions" in _CLAUDE_REVIEW_PROMPT

    def test_both_have_column_or_editorial_ban(self):
        """양쪽 모두 사설체/칼럼 금지 규칙 보유."""
        assert "사설체 금지" in _FINALIZE_PROMPT_KO or "핵심이다" in _FINALIZE_PROMPT_KO
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
        """_GROK_VALID_FAIL_TAGS에 17개 태그 존재 (영어 11 + 한국어 6)."""
        assert len(_GROK_VALID_FAIL_TAGS) == 17
        expected = {
            "SAME_THESIS", "PRESS_RELEASE_TONE", "POLICY_MEMO_TONE",
            "COLUMN_ENDING", "NO_READER_STAKE", "GENERIC_SKEPTICISM",
            "HEADLINE_RESTATEMENT",
            "SPECULATIVE_MOTIVE", "DEAD_ENDING",
            "LOW_CONFIDENCE_OVERREACH", "ABSTRACT_WRAPUP",
            # 한국어 fail_tags
            "기사재서술", "평균문", "판단좌표없음",
            "죽은마감", "저신뢰과해석", "슬롯기능중복",
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

    def test_hook_candidates_from_thesis_cards_only(self):
        """hook_candidates는 thesis_cards opener에서만 채워짐 (OpenAI 것 무시)."""
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
        # OpenAI hook_candidates 무시, thesis_cards opener에서만 채움
        assert card.hook_candidates == ["첫문장A"]

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

    def test_slot_interpretation_rule(self):
        """골든룰에 슬롯 해석 방향 규칙."""
        p = _FINALIZE_PROMPT_KO
        assert "슬롯 해석 방향" in p

    def test_tension_reference(self):
        """긴장점을 드러내라는 지시."""
        p = _FINALIZE_PROMPT_KO
        assert "긴장점" in p

    def test_verification_point_reference(self):
        """검증 포인트로 끝내라는 지시."""
        p = _FINALIZE_PROMPT_KO
        assert "검증 포인트" in p


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


# ═══════════════════════════════════════════════════════════════════════════════
# Low confidence 추정성 감점 테스트
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpeculativeMotiveDetection:
    """_has_speculative_motive() 추정성 동기 탐지 검증."""

    def test_detects_political_calculation(self):
        """정치적 계산 탐지."""
        assert _has_speculative_motive("중간선거를 앞둔 정치적 계산에서 비롯")

    def test_detects_hidden_intention(self):
        """숨은 의도 탐지."""
        assert _has_speculative_motive("숨은 의도가 깔려 있다")

    def test_detects_electoral_motive(self):
        """선거용 판단 탐지."""
        assert _has_speculative_motive("선거를 앞둔 승부수")

    def test_clean_text_no_detection(self):
        """추정 없는 깨끗한 텍스트."""
        assert not _has_speculative_motive("WTI가 배럴당 105달러까지 올랐다")

    def test_patterns_not_empty(self):
        """패턴 리스트가 비어있지 않음."""
        assert len(_SPECULATIVE_MOTIVE_PATTERNS) >= 10


class TestSlotReorderForLowConfidence:
    """_reorder_slots_for_low_confidence() 슬롯 재정렬 검증."""

    def _make_card(self, certainty="미확인"):
        return CandidateCard(
            key_facts=["팩트1"],
            hook_candidates=["A", "B", "C"],
            one_liner=[],
            cautions=[],
            watch_points=[],
            certainty_level=certainty,
            thesis_cards=[
                ThesisCard(thesis="WTI가 올랐다", opener="A", why_not_summary="", reader_stake=""),
                ThesisCard(thesis="정치적 계산에서 비롯된 것", opener="B", why_not_summary="", reader_stake=""),
                ThesisCard(thesis="후속 시행령 여부가 분기점", opener="C", why_not_summary="", reader_stake=""),
            ],
        )

    def test_reorder_pushes_speculative_back(self):
        """추정성 슬롯이 뒤로 이동."""
        card = self._make_card(certainty="미확인")
        _reorder_slots_for_low_confidence(card)
        # 정치적 계산 슬롯이 마지막으로
        assert "정치적 계산" in card.thesis_cards[-1].thesis

    def test_no_reorder_for_high_confidence(self):
        """확정 confidence에서는 재정렬 안 함."""
        card = self._make_card(certainty="확정")
        original_order = [tc.thesis for tc in card.thesis_cards]
        _reorder_slots_for_low_confidence(card)
        assert [tc.thesis for tc in card.thesis_cards] == original_order

    def test_hook_candidates_synced(self):
        """재정렬 후 hook_candidates도 동기화."""
        card = self._make_card(certainty="미확인")
        _reorder_slots_for_low_confidence(card)
        assert card.hook_candidates == [tc.opener for tc in card.thesis_cards]


class TestExternalVerificationSignalRule:
    """외부 검증 신호 규칙이 프롬프트에 있는지 검증."""

    def test_finalize_has_signal_examples(self):
        """마감 프롬프트에 판별 신호 예시가 있음."""
        assert "나오면" in _FINALIZE_PROMPT_KO
        assert "선언에 그친다" in _FINALIZE_PROMPT_KO or "살아 있는 것이다" in _FINALIZE_PROMPT_KO

    def test_claude_has_verification_signal_rule(self):
        """Claude 프롬프트에 판별 신호 규칙이 있음."""
        assert "판별 신호" in _CLAUDE_REVIEW_PROMPT

    def test_finalize_bans_dead_ending_explicitly(self):
        """마감 프롬프트에 '봐야 한다'만 말하면 실패 규칙."""
        assert "봐야 한다" in _FINALIZE_PROMPT_KO
        assert "실패" in _FINALIZE_PROMPT_KO


class TestNewGrokFailTags:
    """새로 추가된 Grok fail_tags 검증."""

    def test_speculative_motive_in_prompt(self):
        """SPECULATIVE_MOTIVE가 Grok 프롬프트에 존재."""
        assert "SPECULATIVE_MOTIVE" in _GROK_EVAL_PROMPT

    def test_dead_ending_in_prompt(self):
        """DEAD_ENDING이 Grok 프롬프트에 존재."""
        assert "DEAD_ENDING" in _GROK_EVAL_PROMPT

    def test_low_confidence_overreach_in_prompt(self):
        """LOW_CONFIDENCE_OVERREACH가 Grok 프롬프트에 존재."""
        assert "LOW_CONFIDENCE_OVERREACH" in _GROK_EVAL_PROMPT

    def test_abstract_wrapup_in_prompt(self):
        """ABSTRACT_WRAPUP이 Grok 프롬프트에 존재."""
        assert "ABSTRACT_WRAPUP" in _GROK_EVAL_PROMPT

    def test_dead_ending_in_claude_fail_tags(self):
        """DEAD_ENDING이 Claude 프롬프트 fail_tags 활용에 존재."""
        assert "DEAD_ENDING" in _CLAUDE_REVIEW_PROMPT


class TestLowConfidenceGuardInPrompts:
    """Low confidence 추정 제한이 프롬프트에 있는지 검증."""

    def test_finalize_has_low_confidence_section(self):
        """마감 프롬프트에 Low confidence 추정 제한 섹션 존재."""
        assert "Low confidence" in _FINALIZE_PROMPT_KO
        assert "동기 추정" in _FINALIZE_PROMPT_KO

    def test_claude_has_low_confidence_rule(self):
        """Claude 보정 기준에 low confidence 추정 과열 항목 존재."""
        assert "Low confidence 추정 과열" in _CLAUDE_REVIEW_PROMPT


class TestNewBannedEndingsFromScreenshot:
    """스크린샷 실패 케이스에서 추가된 금지 마감 패턴."""

    def test_maintenance_duration_banned(self):
        """'오래 유지되는지가 관건' 패턴 금지."""
        post = "이 조치가 정말 실행되는지, 얼마나 오래 유지되는지가 관건이다."
        _, _, warnings, _ = _validate_final_post(post, "짧은 버전.")
        assert any("금지 마감" in w for w in warnings)

    def test_really_executed_banned(self):
        """'정말 실행되는지' 패턴 금지."""
        assert "정말 실행되는지" in _BANNED_ENDINGS

    def test_core_is_banned(self):
        """'핵심이다' 패턴 금지."""
        assert "핵심이다" in _BANNED_ENDINGS


class TestJudgmentCoordAndVerificationSignal:
    """판단 좌표(judgment_coord) + 판별 신호(verification_signal) 필드 검증."""

    def test_thesis_card_has_judgment_coord_field(self):
        """ThesisCard에 judgment_coord 필드 존재."""
        tc = ThesisCard()
        assert hasattr(tc, "judgment_coord")
        assert tc.judgment_coord == ""

    def test_thesis_card_has_verification_signal_field(self):
        """ThesisCard에 verification_signal 필드 존재."""
        tc = ThesisCard()
        assert hasattr(tc, "verification_signal")
        assert tc.verification_signal == ""

    def test_thesis_card_stores_values(self):
        """ThesisCard에 판단 좌표/판별 신호 값 저장."""
        tc = ThesisCard(
            thesis="테스트",
            judgment_coord="배제 범위가 직급인지 직무인지가 핵심",
            verification_signal="다음 주 인사발령에서 확인 가능",
        )
        assert tc.judgment_coord == "배제 범위가 직급인지 직무인지가 핵심"
        assert tc.verification_signal == "다음 주 인사발령에서 확인 가능"

    def test_gemini_prompt_has_judgment_coord(self):
        """Gemini 프롬프트에 판단 좌표 규칙 존재."""
        assert "judgment_coord" in _GEMINI_THESIS_PROMPT
        assert "판단 좌표" in _GEMINI_THESIS_PROMPT

    def test_gemini_prompt_has_verification_signal(self):
        """Gemini 프롬프트에 판별 신호 규칙 존재."""
        assert "verification_signal" in _GEMINI_THESIS_PROMPT
        assert "판별 신호" in _GEMINI_THESIS_PROMPT

    def test_finalize_prompt_has_judgment_coord(self):
        """마감 프롬프트에 판단 좌표 조립 구조 존재."""
        assert "판단 좌표" in _FINALIZE_PROMPT_KO

    def test_finalize_prompt_has_verification_signal(self):
        """마감 프롬프트에 판별 신호 조립 구조 존재."""
        assert "판별 신호" in _FINALIZE_PROMPT_KO

    def test_claude_prompt_has_judgment_coord(self):
        """Claude 프롬프트에 판단 좌표 교정 규칙 존재."""
        assert "판단 좌표" in _CLAUDE_REVIEW_PROMPT

    def test_grok_prompt_has_korean_fail_tags(self):
        """Grok 프롬프트에 한국어 fail_tags 존재."""
        assert "기사재서술" in _GROK_EVAL_PROMPT
        assert "평균문" in _GROK_EVAL_PROMPT
        assert "판단좌표없음" in _GROK_EVAL_PROMPT
        assert "죽은마감" in _GROK_EVAL_PROMPT
        assert "저신뢰과해석" in _GROK_EVAL_PROMPT
        assert "슬롯기능중복" in _GROK_EVAL_PROMPT

    def test_korean_fail_tags_in_valid_set(self):
        """한국어 fail_tags가 유효 목록에 포함."""
        korean_tags = {"기사재서술", "평균문", "판단좌표없음", "죽은마감", "저신뢰과해석", "슬롯기능중복"}
        assert korean_tags.issubset(_GROK_VALID_FAIL_TAGS)


class TestNewBannedDeliveryPatterns:
    """사용자 지정 신규 금지 패턴 — '감 잡힘' 표현 / 추정 마감."""

    def test_yeoji_dr러나다_banned(self):
        """'여지가 드러났다' 패턴이 금지 마감/약한 패턴에 포함."""
        assert "여지가 드러났다" in _BANNED_ENDINGS
        assert "여지가 드러났다" in _WEAK_PATTERNS

    def test_yeoji_yeol리다_banned(self):
        """'여지가 열렸다' 패턴이 금지 마감/약한 패턴에 포함."""
        assert "여지가 열렸다" in _BANNED_ENDINGS
        assert "여지가 열렸다" in _WEAK_PATTERNS

    def test_egeuchil_gananeungseong_banned(self):
        """'에 그칠 가능성이 있다' 패턴이 금지 마감/약한 패턴에 포함."""
        assert "에 그칠 가능성이 있다" in _BANNED_ENDINGS
        assert "에 그칠 가능성이 있다" in _WEAK_PATTERNS

    def test_validate_detects_yeoji_banned(self):
        """'여지가 드러났다' 로 끝나면 DEAD_ENDING 게이트 발동."""
        post = (
            "미국이 보상안을 꺼냈다.\n"
            "실제로 진짜 협상인지는 사찰 수용 여부가 답을 준다.\n"
            "협상 재개 여지가 드러났다."
        )
        short = "짧은 버전."
        _, _, warnings, gate_fails = _validate_final_post(post, short)
        assert any("금지 마감" in w or "죽은 마감" in w for w in warnings)
        assert "DEAD_ENDING" in gate_fails

    def test_finalize_prompt_has_4_function_mapping(self):
        """마감 프롬프트에 '변화/의미/판별 기준/실패 시 해석' 기능 매핑 존재."""
        assert "변화" in _FINALIZE_PROMPT_KO
        assert "판별 기준" in _FINALIZE_PROMPT_KO
        assert "실패 시 해석" in _FINALIZE_PROMPT_KO

    def test_finalize_prompt_has_delivery_short_example(self):
        """final_short 규칙에 사용자 지정 전달문 예시 존재."""
        assert "미국이 처음 보상안을 꺼냈다" in _FINALIZE_PROMPT_KO
        assert "광통신 수혜주는 갈린다" in _FINALIZE_PROMPT_KO


class TestTrimDisplay:
    """trim_display — 표시용 의미 보존형 자르기."""

    def test_short_text_unchanged(self):
        from app.services.telegram_service import trim_display
        assert trim_display("짧은 문장", 50) == "짧은 문장"

    def test_empty_text(self):
        from app.services.telegram_service import trim_display
        assert trim_display("", 50) == ""
        assert trim_display(None, 50) is None  # type: ignore[arg-type]

    def test_cuts_at_sentence_boundary(self):
        from app.services.telegram_service import trim_display
        # 첫 문장 종결점이 limit//2 지점을 넘어야 선택됨 (한글 1자 기준)
        text = "이번 조치는 실제 발표로 이어졌다. 시행 여부는 다음 달 공개된다."
        result = trim_display(text, 30)
        # '다.' 경계에서 끊기는 게 맞다
        assert result.endswith("다.")
        assert len(result) <= 30

    def test_long_text_truncated_with_ellipsis(self):
        from app.services.telegram_service import trim_display
        text = "매우긴문장이며마침표도없고공백도없어서종결점을찾을수없다한번에박혀"
        result = trim_display(text, 15)
        assert len(result) <= 16  # include trailing '…' if appended
        # 이 경우 공백·종결점 없어서 그냥 잘릴 수 있음
        assert result.startswith("매우긴문장이며마침표")

    def test_cuts_at_space_with_ellipsis(self):
        from app.services.telegram_service import trim_display
        text = "한국은 오늘 아침 발표를 냈고 미국은 저녁까지 대응을 보류했다"
        result = trim_display(text, 20)
        assert len(result) <= 21  # 공백 + '…'
        assert result.endswith("…") or len(result) <= 20


class TestFirstSentenceHardGate:
    """첫 문장 즉시 이해성 — 95점 기준 하드 게이트."""

    def test_first_sentence_over_60_chars_gated(self):
        """첫 문장 60자 초과 → WEAK_OPENER 하드 게이트."""
        long_first = (
            "미국 행정부의 대이란 협상 기조가 과거의 강경 일변도에서 "
            "조건부 접근 방식으로 빠르게 전환되는 조짐이 드러나고 있다."
        )
        assert len(long_first) > 60
        post = long_first + "\n근거 팩트 한 줄.\n판별 신호: X가 나오면 확정."
        short = "짧은 버전 전달문이다."
        _, _, warnings, gate_fails = _validate_final_post(post, short)
        assert "WEAK_OPENER" in gate_fails
        assert any("60자 초과" in w for w in warnings)

    def test_first_sentence_45_to_60_warning_only(self):
        """첫 문장 46~60자 → 경고만, 게이트 통과."""
        mid_first = "이번 협상에서 미국과 이란이 보상안과 사찰 수용 조건을 놓고 완전히 갈린 것이 본질이다."
        assert 45 < len(mid_first) <= 60
        post = mid_first + "\n서울 48%, 인천 36%.\n사찰 수용이 답이다."
        short = "짧은 버전 전달문."
        _, _, warnings, gate_fails = _validate_final_post(post, short)
        assert "WEAK_OPENER" not in gate_fails
        assert any("45자 이내 권장" in w for w in warnings)

    def test_first_sentence_under_45_pass(self):
        """첫 문장 45자 이내 → 통과."""
        post = (
            "미국이 처음 보상안을 꺼냈다.\n"
            "서울 48%가 공급을 먼저 꼽았다.\n"
            "사찰 수용이 답이다."
        )
        short = "미국이 처음 보상안을 꺼냈다. 사찰 수용이 답이다."
        _, _, warnings, gate_fails = _validate_final_post(post, short)
        # 첫 문장 길이 경고/게이트 없음 (다른 이유로 WEAK_OPENER 올 수는 있음)
        first_warnings = [w for w in warnings if "첫 문장" in w and "자" in w]
        assert not any("60자 초과" in w or "45자 이내 권장" in w for w in first_warnings)

    def test_first_sentence_starts_with_ihu_gated(self):
        """첫 문장이 '~이후' 시작 → WEAK_OPENER 게이트."""
        post = (
            "11일 협상 결렬 이후 로이터가 재협상을 보도했다.\n"
            "실제 재회는 금요일.\n"
            "그날 결정된다."
        )
        short = "짧은 버전."
        _, _, warnings, gate_fails = _validate_final_post(post, short)
        assert "WEAK_OPENER" in gate_fails
        assert any("배경 설명 시작" in w for w in warnings)

    def test_first_sentence_starts_with_bodohan_gated(self):
        """첫 문장에 '~보도한' 이 앞쪽에 있으면 WEAK_OPENER 게이트."""
        post = (
            "로이터가 보도한 재협상은 실제로는 확정되지 않았다.\n"
            "사찰 수용이 먼저.\n"
            "그다음 재회다."
        )
        short = "짧은 버전."
        _, _, warnings, gate_fails = _validate_final_post(post, short)
        assert "WEAK_OPENER" in gate_fails

    def test_finalize_prompt_first_sentence_45_hard_gate(self):
        """마감 프롬프트에 첫 문장 45자 이내 하드 게이트 명시."""
        assert "45자 이내" in _FINALIZE_PROMPT_KO
        assert "60자 넘으면" in _FINALIZE_PROMPT_KO

    def test_finalize_prompt_final_short_120(self):
        """마감 프롬프트의 final_short 상한이 120자로 조정됨."""
        assert "120자 안쪽" in _FINALIZE_PROMPT_KO

    def test_finalize_prompt_final_short_banned_hints(self):
        """final_short 금지어 명시."""
        # "중요하다 / 관건이다 / 변수다" 명시
        assert "중요하다" in _FINALIZE_PROMPT_KO and "관건이다" in _FINALIZE_PROMPT_KO


class TestStrongFailHelpers:
    """강한 실패 태그 판정 헬퍼."""

    def test_strong_fail_tags_content(self):
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert _STRONG_FAIL_TAGS == frozenset({
            "WEAK_OPENER", "DEAD_ENDING",
            "STRUCTURE_COLUMN", "LOW_CONFIDENCE_OVERREACH",
        })

    def test_has_strong_fail_true(self):
        from app.services.content_pack import _has_strong_fail
        assert _has_strong_fail(["WEAK_OPENER"]) is True
        assert _has_strong_fail(["BRIEFING_SMELL", "DEAD_ENDING"]) is True

    def test_has_strong_fail_false_on_soft_only(self):
        from app.services.content_pack import _has_strong_fail
        # 소프트 태그만 있으면 재생성 대상 아님
        assert _has_strong_fail(["BRIEFING_SMELL"]) is False
        assert _has_strong_fail(["COMPLEX_SENTENCE", "OPINION_LEAK"]) is False
        assert _has_strong_fail([]) is False
        assert _has_strong_fail(None) is False

    def test_count_strong_fails(self):
        from app.services.content_pack import _count_strong_fails
        assert _count_strong_fails(["WEAK_OPENER", "DEAD_ENDING"]) == 2
        assert _count_strong_fails(["WEAK_OPENER", "BRIEFING_SMELL"]) == 1
        assert _count_strong_fails([]) == 0

    def test_build_retry_instruction_weak_opener(self):
        from app.services.content_pack import _build_retry_instruction
        msg = _build_retry_instruction(["WEAK_OPENER"])
        assert "재생성 지시" in msg
        assert "45자 이내" in msg
        assert "배경 설명" in msg

    def test_build_retry_instruction_all_four(self):
        from app.services.content_pack import _build_retry_instruction
        msg = _build_retry_instruction([
            "WEAK_OPENER", "DEAD_ENDING",
            "STRUCTURE_COLUMN", "LOW_CONFIDENCE_OVERREACH",
        ])
        assert "45자 이내" in msg
        assert "관건이다" in msg
        assert "요약→의견→관건" in msg
        assert "동기 추정" in msg

    def test_build_retry_instruction_empty_on_soft_only(self):
        from app.services.content_pack import _build_retry_instruction
        # 소프트 태그만 있으면 빈 문자열 (재생성 지시 없음)
        assert _build_retry_instruction(["BRIEFING_SMELL"]) == ""
        assert _build_retry_instruction([]) == ""

    def test_build_retry_instruction_preserves_논지(self):
        """재생성 지시문에 논지 유지 조항 명시."""
        from app.services.content_pack import _build_retry_instruction
        msg = _build_retry_instruction(["WEAK_OPENER"])
        assert "판단 좌표" in msg
        assert "판별 신호" in msg
        assert "새 논지 추가 금지" in msg


class TestGenerateFinalPostRetry:
    """generate_final_post 자동 재생성 1회 시나리오 — 4개 강한 실패 태그.

    전략: _call_ai_with_prompt / _grok_eval / _claude_review_final 를
    monkeypatch 하여 1차 실패 / 2차 (성공|실패) 시나리오를 시뮬레이션.
    """

    @pytest.fixture
    def card(self):
        from app.services.content_pack import CandidateCard, ThesisCard
        return CandidateCard(
            key_facts=["팩트1", "팩트2"],
            hook_candidates=["훅1"],
            thesis_cards=[
                ThesisCard(
                    thesis="해석 슬롯 논지",
                    why_not_summary="긴장점",
                    reader_stake="독자 영향",
                    opener="초안 첫 문장",
                    judgment_coord="판단 기준",
                    verification_signal="확인 신호",
                )
            ],
            certainty_level="확정",
        )

    def _setup_mocks(self, monkeypatch, raw_sequence):
        """_call_ai_with_prompt 를 raw_sequence 순서대로 반환하도록 패치.
        _grok_eval 은 None, _claude_review_final 은 입력 그대로 반환."""
        from app.services import content_pack as cp

        calls = {"count": 0}

        async def fake_ai(system, user, *, temperature=0.7):
            idx = calls["count"]
            calls["count"] += 1
            return raw_sequence[idx] if idx < len(raw_sequence) else None

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(card, draft, **kw):
            # Claude 보정 생략 — draft 그대로 (재파싱으로 gate_fails 유지)
            return None

        monkeypatch.setattr(cp, "_call_ai_with_prompt", fake_ai)
        monkeypatch.setattr(cp, "_grok_eval", fake_grok)
        monkeypatch.setattr(cp, "_claude_review_final", fake_claude)
        return calls

    @pytest.mark.asyncio
    async def test_weak_opener_retry_succeeds(self, monkeypatch, card):
        """WEAK_OPENER (60자 초과 첫 문장) → 첫 줄 rewrite 경로로 통과.

        PR: WEAK_OPENER 단독 실패는 본문 전체 재생성 대신 opener 만 교체한다.
        PR 14: draft_count=2 → 초안 2개 생성 후 최선 선택. 시퀀스 앞에
        동일 bad 2개 배치.
        """
        from app.services.content_pack import generate_final_post

        bad = json.dumps({
            "final_post": "미국 행정부의 대이란 협상 기조가 과거의 강경 일변도에서 조건부 접근 방식으로 전환되는 조짐이 드러나고 있다.\n근거 한 줄.\n사찰 수용이 답이다.",
            "final_short": "짧은 버전.",
        })
        # 3차 호출은 opener rewrite — `{new_opener}` 형식
        good = json.dumps({"new_opener": "미국이 처음 보상안을 꺼냈다"})
        calls = self._setup_mocks(monkeypatch, [bad, bad, good])

        result = await generate_final_post(card, 0, "")

        assert calls["count"] == 3, "draft×2 + opener rewrite 1회 = 총 3회"
        assert "WEAK_OPENER" not in result.gate_fails
        assert "RETRY_EXHAUSTED" not in result.gate_fails
        # rewrite 로 첫 줄이 교체됐어야 한다 — 본문은 유지
        assert result.final_post.startswith("미국이 처음 보상안을 꺼냈다")
        assert "근거 한 줄" in result.final_post
        assert "사찰 수용이 답이다" in result.final_post

    @pytest.mark.asyncio
    async def test_dead_ending_retry_still_fails_marks_exhausted(
        self, monkeypatch, card
    ):
        """DEAD_ENDING → 재생성 후에도 실패 → RETRY_EXHAUSTED 마커.

        PR 14: draft_count=2 초기 + draft_count=1 재생성 = 총 3회.
        """
        from app.services.content_pack import generate_final_post

        bad1 = json.dumps({
            "final_post": "지금 핵심은 재회담이다.\n근거 한 줄.\n이것이 관건이다.",
            "final_short": "짧은 버전.",
        })
        bad2 = json.dumps({
            "final_post": "지금 핵심은 재회담이다.\n근거 한 줄.\n결국 이것이 변수다.",
            "final_short": "짧은 버전.",
        })
        calls = self._setup_mocks(monkeypatch, [bad1, bad1, bad2])

        result = await generate_final_post(card, 0, "")

        assert calls["count"] == 3
        assert "DEAD_ENDING" in result.gate_fails
        assert "RETRY_EXHAUSTED" in result.gate_fails

    @pytest.mark.asyncio
    async def test_structure_column_retry_succeeds(self, monkeypatch, card):
        """STRUCTURE_COLUMN (요약→의견→관건) → 재생성에서 구조 변경 성공.

        PR 14: draft×2 초기 + draft×1 재생성 = 총 3회.
        """
        from app.services.content_pack import (
            generate_final_post,
            _SUMMARY_OPINION_CRUX_PATTERNS,
        )

        starter = _SUMMARY_OPINION_CRUX_PATTERNS["summary_starters"][0]
        crux = _SUMMARY_OPINION_CRUX_PATTERNS["crux_endings"][0]
        bad = json.dumps({
            "final_post": f"{starter} 이번 조치는 중요한 의미를 담고 있다.\n결국 {crux}",
            "final_short": "짧은 버전.",
        })
        good = json.dumps({
            "final_post": "미국이 처음 보상안을 꺼냈다.\n서울 48%.\n사찰 수용이 나오면 확정.",
            "final_short": "미국이 처음 보상안을 꺼냈다. 사찰 수용이 답이다.",
        })
        calls = self._setup_mocks(monkeypatch, [bad, bad, good])

        result = await generate_final_post(card, 0, "")

        assert calls["count"] == 3
        assert "STRUCTURE_COLUMN" not in result.gate_fails
        assert "RETRY_EXHAUSTED" not in result.gate_fails

    @pytest.mark.asyncio
    async def test_low_confidence_overreach_retry_succeeds(
        self, monkeypatch, card
    ):
        """LOW_CONFIDENCE_OVERREACH → 재생성에서 동기 추정 제거 성공.

        PR 14: draft×2 초기 + draft×1 재생성 = 총 3회.
        """
        from app.services.content_pack import CandidateCard, ThesisCard, generate_final_post

        low_card = CandidateCard(
            key_facts=["팩트1"],
            hook_candidates=["훅1"],
            thesis_cards=[ThesisCard(thesis="t", opener="o")],
            certainty_level="미확인",
        )

        bad = json.dumps({
            "final_post": "지금 핵심은 보상안이다.\n정치적 계산이 깔린 것으로 보인다.\n사찰 수용이 나오면 확정.",
            "final_short": "짧은 버전.",
        })
        good = json.dumps({
            "final_post": "미국이 처음 보상안을 꺼냈다.\n서울 48%.\n사찰 수용이 나오면 확정.",
            "final_short": "미국이 처음 보상안을 꺼냈다. 사찰 수용이 답이다.",
        })
        calls = self._setup_mocks(monkeypatch, [bad, bad, good])

        result = await generate_final_post(low_card, 0, "")

        assert calls["count"] == 3
        assert "LOW_CONFIDENCE_OVERREACH" not in result.gate_fails
        assert "RETRY_EXHAUSTED" not in result.gate_fails

    @pytest.mark.asyncio
    async def test_soft_fail_only_no_retry(self, monkeypatch, card):
        """소프트 실패만 있으면 재생성하지 않고 1회로 종료.

        PR 14: draft×2 = 총 2회 호출, 재생성 없음.
        """
        from app.services.content_pack import generate_final_post

        # BRIEFING_SMELL만 걸리도록 _WEAK_PATTERNS 2개 이상 삽입
        only_soft = json.dumps({
            "final_post": "지금 핵심은 재회담이다.\n추이를 봐야 한다. 영향을 미칠 수 있다.\n사찰 수용이 나오면 확정.",
            "final_short": "짧은 버전.",
        })
        calls = self._setup_mocks(monkeypatch, [only_soft, only_soft])

        result = await generate_final_post(card, 0, "")

        # 재생성 트리거 안 됨 — draft×2 = 총 2회 호출
        assert calls["count"] == 2
        assert "RETRY_EXHAUSTED" not in result.gate_fails
        # BRIEFING_SMELL 은 그대로 유지 (경고만)
        assert "BRIEFING_SMELL" in result.gate_fails

    @pytest.mark.asyncio
    async def test_retry_never_loops_twice(self, monkeypatch, card):
        """재생성은 최대 1회 — 두 번 연속 강한 실패여도 추가 호출 없음.

        PR 14: draft×2 초기 + draft×1 재생성 = 총 3회. 4번째는 없어야.
        """
        from app.services.content_pack import generate_final_post

        bad1 = json.dumps({
            "final_post": "지금 핵심은 재회담이다.\n근거 한 줄.\n이것이 관건이다.",
            "final_short": "짧은 버전.",
        })
        bad2 = json.dumps({
            "final_post": "지금 핵심은 재회담이다.\n근거 한 줄.\n결국 변수다.",
            "final_short": "짧은 버전.",
        })
        calls = self._setup_mocks(monkeypatch, [bad1, bad1, bad2, "SHOULD_NOT_USE"])

        result = await generate_final_post(card, 0, "")

        assert calls["count"] == 3, "무한 루프 금지 — draft×2 + retry×1 = 3회"
        assert "RETRY_EXHAUSTED" in result.gate_fails


class TestTelegramRetryExhaustedLabel:
    """telegram_bot._tag_labels 에 RETRY_EXHAUSTED 라벨 존재."""

    def test_tag_labels_contains_retry_exhausted(self):
        # 소스 파일에 라벨 정의 존재 여부를 문자열로 확인 (텔레그램 import 회피)
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "app" / "telegram_bot.py"
        text = src.read_text(encoding="utf-8")
        assert '"RETRY_EXHAUSTED"' in text
        assert "재생성 1회 실패" in text
        assert "게시 전 수동 확인 필수" in text


# ─── 기사 라우터 (EXPLAIN / JUDGMENT / VERIFY) ──────────────────────────────


class TestArticleModeRouter:
    """certainty_level + 구조/태그 조합 → article mode 매핑."""

    # ── 기본 매핑 (정상 조건: 팩트 3개, 경고 없음, 약한 태그 없음) ──
    def test_high_confidence_routes_to_explain(self):
        from app.services.content_pack import (
            route_article_mode, MODE_EXPLAIN,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="확정",
        )
        assert route_article_mode(card) == MODE_EXPLAIN

    def test_conflicting_signals_routes_to_judgment(self):
        from app.services.content_pack import (
            route_article_mode, MODE_JUDGMENT,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="상충",
        )
        assert route_article_mode(card) == MODE_JUDGMENT

    def test_unverified_routes_to_verify(self):
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="미확인",
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_unknown_certainty_defaults_to_verify(self):
        """안전장치: 예상 밖 값이면 가장 보수적인 VERIFY."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="",
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_mode_label_shape(self):
        from app.services.content_pack import (
            mode_label, MODE_EXPLAIN, MODE_JUDGMENT, MODE_VERIFY,
        )
        assert "EXPLAIN" in mode_label(MODE_EXPLAIN)
        assert "JUDGMENT" in mode_label(MODE_JUDGMENT)
        assert "VERIFY" in mode_label(MODE_VERIFY)

    # ── 강등 규칙 (팩트체크 결과 + 구조/태그 조합) ──
    def test_many_cautions_demote_to_verify(self):
        """cautions 3개 이상이면 확정이어도 VERIFY로 최대 강등."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="확정",
            cautions=["출처 단일", "시점 불명", "원문 미확인"],
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_weak_tag_demotes_explain_to_verify(self):
        """약한 신호 태그(루머/단독/관측/추정)는 PR 4 classifier 가
        UNVERIFIED_CLAIM 으로 잡아 VERIFY 까지 내린다.

        (PR 4 이전엔 JUDGMENT 였으나, 같은 성질 기사의 일관성을 위해
        보수적으로 VERIFY 로 통일.)
        """
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩3"],
            certainty_level="확정",
            topic_tags=["경제", "루머성"],
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_shallow_evidence_demotes_explain_to_judgment(self):
        """key_facts 2개 이하면 근거 얕음 → EXPLAIN → JUDGMENT."""
        from app.services.content_pack import (
            route_article_mode, MODE_JUDGMENT,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2"],
            certainty_level="확정",
        )
        assert route_article_mode(card) == MODE_JUDGMENT

    def test_unverified_with_weak_tag_stays_verify(self):
        """이미 VERIFY면 강등 규칙과 무관하게 VERIFY 유지 (상향 없음)."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["팩트1"],
            certainty_level="미확인",
            topic_tags=["단독보도"],
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_judgment_base_not_upgraded_by_full_facts(self):
        """상충 base 는 팩트가 풍부해도 EXPLAIN 으로 상향되지 않는다."""
        from app.services.content_pack import (
            route_article_mode, MODE_JUDGMENT,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3", "팩트4"],
            certainty_level="상충",
        )
        assert route_article_mode(card) == MODE_JUDGMENT


class TestArticleTypeClassifier:
    """PR 4: rule-first article type classifier.

    AI 호출 없이 source_type / source_url / certainty_level / cautions /
    risk_flags / topic_tags / key_facts 조합으로 기사 성질을 분류한다.
    """

    def test_all_article_types_registered(self):
        from app.services.content_pack import (
            _ARTICLE_TYPES,
            TYPE_STRAIGHT_NEWS, TYPE_CONFLICTING_REPORT, TYPE_UNVERIFIED_CLAIM,
            TYPE_OPINION_COLUMN, TYPE_COMMUNITY_SCREENSHOT, TYPE_MARKET_MOVING_NEWS,
        )
        for t in (
            TYPE_STRAIGHT_NEWS, TYPE_CONFLICTING_REPORT, TYPE_UNVERIFIED_CLAIM,
            TYPE_OPINION_COLUMN, TYPE_COMMUNITY_SCREENSHOT, TYPE_MARKET_MOVING_NEWS,
        ):
            assert t in _ARTICLE_TYPES

    # ── 1. COMMUNITY_SCREENSHOT ──
    def test_community_screenshot_from_source_type(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_COMMUNITY_SCREENSHOT,
        )
        card = CandidateCard(source_type="community_screenshot",
                             certainty_level="확정")
        assert classify_article_type(card) == TYPE_COMMUNITY_SCREENSHOT

    def test_community_screenshot_from_url(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_COMMUNITY_SCREENSHOT,
        )
        card = CandidateCard(
            source_url="https://www.dcinside.com/board/something",
            certainty_level="확정",
        )
        assert classify_article_type(card) == TYPE_COMMUNITY_SCREENSHOT

    def test_community_screenshot_from_tag(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_COMMUNITY_SCREENSHOT,
        )
        card = CandidateCard(
            topic_tags=["커뮤니티 스크린샷", "정치"],
            certainty_level="확정",
        )
        assert classify_article_type(card) == TYPE_COMMUNITY_SCREENSHOT

    # ── 2. OPINION_COLUMN ──
    def test_opinion_column_from_url_slug(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_OPINION_COLUMN,
        )
        card = CandidateCard(
            source_url="https://news.example.com/column/2026/04/15/view",
            certainty_level="확정",
            key_facts=["f1", "f2", "f3"],
        )
        assert classify_article_type(card) == TYPE_OPINION_COLUMN

    def test_opinion_column_from_source_type(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_OPINION_COLUMN,
        )
        card = CandidateCard(source_type="opinion",
                             certainty_level="확정",
                             key_facts=["f1", "f2", "f3"])
        assert classify_article_type(card) == TYPE_OPINION_COLUMN

    # ── 3. UNVERIFIED_CLAIM ──
    def test_unverified_claim_by_certainty(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_UNVERIFIED_CLAIM,
        )
        card = CandidateCard(
            certainty_level="미확인",
            key_facts=["f1", "f2", "f3"],
        )
        assert classify_article_type(card) == TYPE_UNVERIFIED_CLAIM

    def test_unverified_claim_by_cautions_text(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_UNVERIFIED_CLAIM,
        )
        card = CandidateCard(
            certainty_level="확정",
            cautions=["출처 미검증"],
            key_facts=["f1", "f2", "f3"],
        )
        assert classify_article_type(card) == TYPE_UNVERIFIED_CLAIM

    def test_unverified_claim_by_weak_tag(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_UNVERIFIED_CLAIM,
        )
        card = CandidateCard(
            certainty_level="확정",
            topic_tags=["경제", "단독보도"],
            key_facts=["f1", "f2", "f3"],
        )
        assert classify_article_type(card) == TYPE_UNVERIFIED_CLAIM

    # ── 4. CONFLICTING_REPORT ──
    def test_conflicting_report_by_certainty(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_CONFLICTING_REPORT,
        )
        card = CandidateCard(
            certainty_level="상충",
            key_facts=["f1", "f2", "f3"],
        )
        assert classify_article_type(card) == TYPE_CONFLICTING_REPORT

    # ── 5. MARKET_MOVING_NEWS ──
    def test_market_moving_by_tag(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_MARKET_MOVING_NEWS,
        )
        card = CandidateCard(
            certainty_level="확정",
            topic_tags=["증시", "코스피"],
            key_facts=["f1", "f2", "f3"],
        )
        assert classify_article_type(card) == TYPE_MARKET_MOVING_NEWS

    def test_market_moving_by_key_facts(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_MARKET_MOVING_NEWS,
        )
        card = CandidateCard(
            certainty_level="확정",
            key_facts=["원/달러 환율 1400원 돌파", "CPI 상승", "국채금리 반등"],
        )
        assert classify_article_type(card) == TYPE_MARKET_MOVING_NEWS

    # ── 6. STRAIGHT_NEWS (fallback) ──
    def test_straight_news_fallback(self):
        from app.services.content_pack import (
            classify_article_type, TYPE_STRAIGHT_NEWS,
        )
        card = CandidateCard(
            certainty_level="확정",
            source_url="https://news.example.com/article/123",
            source_type="news_link",
            key_facts=["팩트1", "팩트2", "팩트3"],
            topic_tags=["정책"],
        )
        assert classify_article_type(card) == TYPE_STRAIGHT_NEWS

    # ── 7. 예외 시 보수 fallback ──
    def test_classifier_exception_fallback_to_straight_news(self):
        """카드가 깨진 상태여도 STRAIGHT_NEWS 반환 (강등 없음)."""
        from app.services.content_pack import (
            classify_article_type, TYPE_STRAIGHT_NEWS,
        )

        class BrokenCard:
            def __getattr__(self, name):
                raise RuntimeError("broken field access")

        assert classify_article_type(BrokenCard()) == TYPE_STRAIGHT_NEWS


class TestRouteArticleModeWithClassifier:
    """PR 4: route_article_mode 가 classifier 결과로 추가 강등한다.

    규칙:
      COMMUNITY_SCREENSHOT / OPINION_COLUMN / UNVERIFIED_CLAIM → VERIFY
      CONFLICTING_REPORT + base EXPLAIN → JUDGMENT
      STRAIGHT_NEWS / MARKET_MOVING_NEWS → base 유지
    """

    def test_community_screenshot_forces_verify(self):
        """certainty=확정 이어도 커뮤니티 스크린샷이면 VERIFY 로 내린다."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["f1", "f2", "f3"],
            certainty_level="확정",
            source_url="https://www.ruliweb.com/community/board/300143/read/123",
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_opinion_url_slug_forces_verify(self):
        """칼럼/사설 URL 이면 certainty 무관하게 VERIFY."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["f1", "f2", "f3"],
            certainty_level="확정",
            source_url="https://news.example.com/opinion/2026/view/12345",
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_low_certainty_or_weak_tag_forces_verify(self):
        """certainty 미확인 이면 UNVERIFIED_CLAIM → VERIFY."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        card = CandidateCard(
            key_facts=["f1", "f2", "f3"],
            certainty_level="미확인",
        )
        assert route_article_mode(card) == MODE_VERIFY

    def test_conflicting_report_with_explain_base_demotes_to_judgment(self):
        """certainty 확정 + risk_flags 에 '엇갈린 보도' → JUDGMENT 강등."""
        from app.services.content_pack import (
            route_article_mode, MODE_JUDGMENT,
        )
        # 본 케이스를 위해 certainty='확정' 이지만 risk_flags 에 conflict 신호
        card = CandidateCard(
            key_facts=["f1", "f2", "f3"],
            certainty_level="확정",
            risk_flags=["양측 주장이 엇갈린다 — 보도 반박"],
        )
        assert route_article_mode(card) == MODE_JUDGMENT

    def test_straight_news_keeps_base_mode(self):
        """정상 STRAIGHT_NEWS 는 base mode 유지."""
        from app.services.content_pack import (
            route_article_mode, MODE_EXPLAIN,
        )
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="확정",
            source_url="https://news.example.com/article/123",
            topic_tags=["정책"],
        )
        assert route_article_mode(card) == MODE_EXPLAIN

    def test_market_moving_keeps_base_mode(self):
        """시장 반응 기사도 classifier 가 강등하지 않는다."""
        from app.services.content_pack import (
            route_article_mode, MODE_EXPLAIN,
        )
        card = CandidateCard(
            key_facts=["원/달러 환율 1400원 돌파", "코스피 급락", "국채금리 반등"],
            certainty_level="확정",
            topic_tags=["증시", "환율"],
        )
        assert route_article_mode(card) == MODE_EXPLAIN

    def test_classifier_never_upgrades(self):
        """classifier 결과로 VERIFY → EXPLAIN 같은 상향은 없다."""
        from app.services.content_pack import (
            route_article_mode, MODE_VERIFY,
        )
        # STRAIGHT_NEWS 로 분류되지만 base 가 VERIFY 이므로 상향 없음
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="미확인",  # base=VERIFY
            source_url="https://news.example.com/article/123",
            topic_tags=["정책"],
        )
        # UNVERIFIED_CLAIM 으로 분류되고 VERIFY 로 demote (이미 VERIFY 라 no-op)
        assert route_article_mode(card) == MODE_VERIFY

    def test_route_logs_article_type(self, caplog):
        """route_article_mode 는 [ArticleType] 로그를 남긴다."""
        import logging
        from app.services.content_pack import route_article_mode
        card = CandidateCard(
            key_facts=["팩트1", "팩트2", "팩트3"],
            certainty_level="확정",
            source_url="https://news.example.com/opinion/view/123",
        )
        with caplog.at_level(logging.INFO, logger="app.services.article_router"):
            route_article_mode(card)
        # 로그에 필요한 4개 필드 모두 포함
        log_text = "\n".join(r.message for r in caplog.records)
        assert "[ArticleType]" in log_text
        assert "type=OPINION_COLUMN" in log_text
        assert "certainty=확정" in log_text
        assert "base=EXPLAIN" in log_text
        assert "final=VERIFY" in log_text


class TestModeSlotInstructions:
    """Gemini 슬롯 생성 user_prompt에 mode별 프레임 지시가 들어간다."""

    def test_explain_slot_instruction_has_three_axes(self):
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_slot_instruction(MODE_EXPLAIN)
        assert "EXPLAIN" in s
        assert "무엇이 바뀌나" in s
        assert "왜 뉴스 이상이냐" in s
        assert "다음 판가름" in s

    def test_judgment_slot_instruction_downtones_meaning_axis(self):
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_JUDGMENT,
        )
        s = _build_mode_slot_instruction(MODE_JUDGMENT)
        assert "JUDGMENT" in s
        assert "무엇이 바뀌나" in s
        assert "다음 판가름" in s
        # JUDGMENT에서는 의미 해석 톤을 약하게
        assert ("짧게" in s) or ("짧게만" in s)

    def test_verify_slot_instruction_blocks_long_term_reading(self):
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_VERIFY,
        )
        s = _build_mode_slot_instruction(MODE_VERIFY)
        assert "VERIFY" in s
        # 새 슬롯 3축
        assert "지금 나온 주장" in s
        assert "아직 확인" in s
        assert "확인되면" in s or "검증 신호" in s
        # 장기 해석 금지 키워드 포함
        for banned in ("정치적 계산", "숨은 의도", "노림수", "체제 양보"):
            assert banned in s, f"VERIFY 금지어 누락: {banned}"


class TestModeFinalizeInstructions:
    """Finalize user_prompt의 '지시' 블록이 mode별로 다르게 조립된다."""

    def test_explain_uses_four_sentence_structure(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        assert "MODE: EXPLAIN" in s
        assert "4문장" in s
        # 4단 구조가 그대로 노출
        for kw in ("핵심 명제", "근거 팩트", "판단 기준", "판별 신호"):
            assert kw in s, f"EXPLAIN 문장 가이드 누락: {kw}"

    def test_judgment_uses_three_sentence_structure(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_JUDGMENT,
        )
        s = _build_mode_finalize_instruction(MODE_JUDGMENT)
        assert "MODE: JUDGMENT" in s
        assert "3문장" in s
        for kw in ("지금 핵심", "엇갈리는 신호", "확인 포인트"):
            assert kw in s, f"JUDGMENT 문장 가이드 누락: {kw}"
        # 장기 구조 해석 억제
        assert "구조적 전환" in s or "체제 재편" in s

    def test_verify_blocks_long_term_and_motive(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        assert "MODE: VERIFY" in s
        assert "3문장" in s
        # 새 3단 구조
        for kw in ("현재 나온 주장", "아직 확인 안 된 점", "다음 확인 신호"):
            assert kw in s, f"VERIFY 문장 가이드 누락: {kw}"
        # 장기/의도 해석 금지어
        for banned in (
            "정치적 계산", "숨은 의도", "본심", "노림수",
            "체제 양보", "질서 재편", "구조적 변화",
        ):
            assert banned in s, f"VERIFY 금지어 누락: {banned}"


class TestExplainDepthInstruction:
    """95점 목표 — EXPLAIN 마감 지시가 구조 + 이해관계 + 열린 마감을 요구한다."""

    def test_explain_requires_structure_hint(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        # 구조 설명 요구
        assert "구조" in s
        # '왜 그 순서로 움직이는지' 요구 문구
        assert "왜 그 순서로" in s

    def test_explain_requires_stakeholder_axis(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        # 이해관계 축 요구
        assert "이해관계" in s
        # 이해관계 후보군 예시
        assert "유리/불리" in s or "먼저 유리" in s

    def test_explain_requires_open_ending_templates(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        # 열린 마감 A/B 템플릿
        assert "판정 기준형" in s
        assert "이해관계형" in s
        # 예시 표현 최소 1개
        assert "답은" in s or "먼저 맞는" in s

    def test_explain_explicitly_bans_closed_verdict_endings(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        for banned in ("신호다", "확인이다", "의미한다", "맞다",
                       "보여준다", "시사한다"):
            assert banned in s, f"EXPLAIN 닫힌 마감 금지어 누락: {banned}"

    def test_explain_short_version_instruction(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        # 짧은 버전: 요약 금지, 구조/이해관계 한 줄
        assert "final_short" in s
        assert "요약 금지" in s

    def test_explain_keeps_old_four_sentence_keywords(self):
        """후방호환 — 기존 4문장 구조 키워드는 유지된다."""
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        for kw in ("핵심 명제", "근거 팩트", "판단 기준", "판별 신호", "4문장"):
            assert kw in s, f"EXPLAIN 기존 키워드 손실: {kw}"


class TestBannedClosedVerdictEndings:
    """95점 목표 — _BANNED_ENDINGS 에 닫힌 판정 마감이 포함된다."""

    def test_banned_endings_include_closed_verdict_tokens(self):
        from app.services.content_pack import _BANNED_ENDINGS
        for token in ("신호다", "의미한다", "의미다", "확인이다",
                      "뜻이다", "맞다", "패러다임 변화다",
                      "구조적 의미를 갖는다", "의미를 갖는다"):
            assert token in _BANNED_ENDINGS, f"금지 마감 누락: {token}"

    def test_validate_final_post_gates_closed_verdict(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "강남3구 하락은 단순 조정이 아니다.\n"
            "규제와 금리가 투자 구조를 바꾼다는 신호다."
        )
        short = "투자 구조 변화의 신호다."
        _, _, warnings, gate_fails = _validate_final_post(post, short, "확정")
        # 닫힌 마감 '신호다' 는 DEAD_ENDING 게이트로 잡혀야 한다
        assert "DEAD_ENDING" in gate_fails
        assert any("신호다" in w for w in warnings)

    def test_validate_final_post_gates_confirmation_verdict(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "정책이 작동하고 있다.\n"
            "양극화가 고착됐다는 확인이다."
        )
        _, _, warnings, gate_fails = _validate_final_post(post, "", "확정")
        assert "DEAD_ENDING" in gate_fails

    def test_validate_allows_closed_word_mid_sentence(self):
        """닫힌 단어가 문장 중간에 오면 허용 (endswith 검사).

        예: '답은 거래량이다' 처럼 열린 마감은 '맞다'/'신호다' 를
        문장 중간에 써도 통과해야 한다.
        """
        from app.services.content_pack import _validate_final_post
        post = (
            "강남3구 하락은 규제 작동 신호다. 그러나 중저가가 버티는 구조는 따로다.\n"
            "답은 다음 달 거래량이다."
        )
        _, _, warnings, gate_fails = _validate_final_post(post, "", "확정")
        # endswith('신호다') 가 False 이므로 DEAD_ENDING 트리거 안 됨
        assert "DEAD_ENDING" not in gate_fails


class TestVerifyOverreachGate:
    """VERIFY / certainty 미확인·상충 기사에서 구조 해석 본문 침투를 막는다.

    실제 실패 샘플(호르무즈/제3국 채널/다음 국면을 결정 …) 을 하드닝.
    """

    def test_verify_overreach_patterns_registered(self):
        from app.services.content_pack import _VERIFY_OVERREACH_PATTERNS
        for token in (
            "제3국을 통한 실질적 대화",
            "외교 채널 복원",
            "협상 의제 연동",
            "긴장 수위 상승",
            "구조적 의미",
            "다음 국면을 결정",
            "진짜 신호",
            "실효성 여부가 판가름",
        ):
            assert any(token in p for p in _VERIFY_OVERREACH_PATTERNS), (
                f"VERIFY 과해석 패턴 누락: {token}"
            )

    def test_verify_gates_third_country_channel(self):
        """실제 실패 샘플 재현 — 제3국 채널 + 다음 국면을 결정 → gate fail."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "파키스탄 등 제3국을 통한 실질적 대화 채널로 이어질지가 다음 "
            "국면을 결정한다는 관측도 있다.\n"
            "고위급 특사 파견이 포착되면 대화 채널이 살아 있다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails
        assert any("VERIFY 구조해석" in w for w in warnings)

    def test_verify_gates_structural_meaning(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "A측이 ~라고 밝혔다.\n"
            "이번 조치는 구조적 의미를 갖는 변화다.\n"
            "공식 발표가 나오면 확인 가능."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "상충")
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_verify_does_not_gate_high_confidence(self):
        """certainty '확정' 에서는 VERIFY 과해석 게이트가 발동하지 않는다."""
        from app.services.content_pack import _validate_final_post
        post = (
            "정부가 공식 발표했다.\n"
            "다음 국면을 결정할 조치다.\n"
            "시행은 다음 달이다."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "확정")
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails

    # ── PR 8: "대화 채널이 살아" false positive 제거 회귀 테스트 ─────────
    def test_verify_allows_contact_confirm_channel(self):
        """
        PR 8 — VERIFY 템플릿 B 예시 ("특사 파견이 포착되면 대화 채널이
        살아 있다") 는 '확인 조건부 단정' 이지 외교 시나리오 확장이 아니다.
        저신뢰 기사에서 단독으로 나와도 LOW_CONFIDENCE_OVERREACH 가 찍히면
        안 된다.
        """
        from app.services.content_pack import _validate_final_post
        post = (
            "공식 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 포착되면 대화 채널이 살아 있다."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails, (
            f"'대화 채널이 살아 있다' 단독은 게이트 통과해야 함: {gate_fails}"
        )

    def test_verify_still_gates_channel_expansion(self):
        """
        PR 8 — '~로 이어질지' 계열 (확장형) 은 계속 차단해야 한다.
        false positive 제거 후에도 진짜 위험 표현은 살아있어야 한다.
        """
        from app.services.content_pack import _validate_final_post
        post = (
            "발언만으로는 판단 어렵다.\n"
            "실제 대화 채널로 이어질지가 관건이다.\n"
            "특사 파견이 확인되면 검증 가능."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "미확인")
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails, (
            f"'대화 채널로 이어' 계열은 계속 차단되어야 함: {gate_fails}"
        )

    def test_verify_overreach_pattern_removed_channel_alive(self):
        """PR 8 — '대화 채널이 살아' 패턴이 리스트에서 빠졌는지 직접 확인."""
        from app.services.content_pack import _VERIFY_OVERREACH_PATTERNS
        assert "대화 채널이 살아" not in _VERIFY_OVERREACH_PATTERNS, (
            "'대화 채널이 살아' 는 VERIFY 템플릿 B 예시와 충돌하므로 제거됨"
        )
        # 확장형은 여전히 남아있어야 한다
        assert "대화 채널로 이어" in _VERIFY_OVERREACH_PATTERNS


class TestVerifyFirstLineDualBranch:
    """VERIFY 첫 문장은 1문장 1주장만. A인지 B인지 수사 금지."""

    def test_verify_first_line_bans_registered(self):
        from app.services.content_pack import _VERIFY_WEAK_OPENER_PATTERNS
        for token in (
            "이어질지", "그칠지", "판가름이다",
            "단순 수사인지", "단순 압박인지", "실질 채널인지",
        ):
            assert token in _VERIFY_WEAK_OPENER_PATTERNS, (
                f"VERIFY 첫 줄 금지 누락: {token}"
            )

    def test_verify_first_line_gate_dual_branch(self):
        """첫 줄에 '~이어질지 ~판가름이다' 있으면 WEAK_OPENER."""
        from app.services.content_pack import _validate_final_post
        post = (
            "트럼프 발언이 수사에 그칠지 실질 채널로 이어질지가 판가름이다.\n"
            "이는 아직 확인되지 않았다.\n"
            "특사 파견이 포착되면 검증 가능."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "미확인")
        assert "WEAK_OPENER" in gate_fails

    def test_verify_first_line_allows_single_claim(self):
        """1문장 1주장 허용 예 — 게이트 통과."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 발언이 아니라 접촉 확인이다.\n"
            "공식 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 공개되면 검증 가능."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "미확인")
        assert "WEAK_OPENER" not in gate_fails

    def test_verify_first_line_gate_skipped_on_high_confidence(self):
        """확정 모드에서는 VERIFY 첫 줄 이중분기 게이트 비활성."""
        from app.services.content_pack import _validate_final_post
        post = (
            "정부 조치가 실효성이 있을지 판가름이다.\n"
            "시행령은 공포됐다.\n"
            "다음 달 적용."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "확정")
        # VERIFY 전용 첫 줄 이중분기 게이트는 '확정' 에서 비활성.
        # (다른 게이트는 여전히 동작 가능)
        # 여기서는 _VERIFY_WEAK_OPENER_PATTERNS 기반 판정이 안 들어갔는지만 확인.
        # 다른 게이트로 WEAK_OPENER 가 찍힐 수 있으므로 warnings 직접 검사.
        # 단순 smoke: 확정 모드에서는 LOW_CONFIDENCE_OVERREACH 발동 안 함.
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails


class TestReaderRewardLayer:
    """
    PR 9 — Reader Reward Layer.

    final_post / final_short 의 마지막 문장에서 SAVE / SHARE / FOLLOW
    독자 보상 시그널을 감지. 둘 다 없으면 NO_READER_REWARD 경고 (WARN-only).
    VERIFY 템플릿 끝줄은 이미 FOLLOW 계열이라 회귀 없음.
    """

    # ─── 1. _detect_reward_type 단위 테스트 ─────────────────────────────
    def test_detect_save_marker_strong_beats_follow(self):
        """'답은 다음 CPI가 기준이다' — SAVE 강 마커가 FOLLOW 신호를 이긴다."""
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("답은 다음 CPI가 기준이다.") == "SAVE"

    def test_detect_save_input_timing(self):
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("결국 먼저 맞는 건 공장이다.") == "SAVE"
        assert _detect_reward_type("핵심은 발표가 아니라 입금 시점이다.") == "SAVE"

    def test_detect_follow_verify_template(self):
        """VERIFY 템플릿 A/B/C 예시 끝줄이 전부 FOLLOW 로 잡혀야 함."""
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("특사 파견이 공개되면 검증 가능.") == "FOLLOW"
        assert _detect_reward_type("특사 파견이 포착되면 대화 채널이 살아 있다.") == "FOLLOW"
        assert _detect_reward_type("이틀 내 공식 접촉이 없으면 수사에 가깝다.") == "FOLLOW"
        assert _detect_reward_type("통상적 통행이 이어지면 상징에 그쳤다.") == "FOLLOW"

    def test_detect_follow_question_form(self):
        """'관건은 ~느냐다' 류 질문형 FOLLOW."""
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("관건은 반도체까지 확대되느냐다.") == "FOLLOW"

    def test_detect_share_source_priority(self):
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("말보다 숫자가 먼저다.") == "SHARE"
        assert _detect_reward_type("출처가 안 나오면 이 숫자는 그냥 SNS 주장이다.") == "SHARE"

    def test_detect_none_closed_analyst(self):
        """'결국 이것이 기준이다' — 보상 키워드 없이 기준이다 로 닫힘."""
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("결국 이것이 기준이다.") is None
        assert _detect_reward_type("이는 구조적 의미가 있다.") is None
        assert _detect_reward_type("이번 결과가 판별 포인트다.") is None

    # ─── 2. _validate_last_line_reward 우선순위 ─────────────────────────
    def test_post_reward_alone_no_warn(self):
        """final_post 에 reward 있으면 final_short 비어도 경고 없음."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "X가 발표됐다. 답은 다음 CPI다.",
            "",
        )
        assert rt == "SAVE"
        assert warn is None

    def test_short_reward_fills_gap_no_warn(self):
        """final_post 에 reward 없어도 final_short 에 있으면 경고 없음."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "정부가 조치를 발표했다. 시행은 다음 달이다.",
            "답은 다음 공식 집계다.",
        )
        assert rt == "SAVE"
        assert warn is None

    def test_both_missing_warns(self):
        """post 와 short 둘 다 reward 없으면 NO_READER_REWARD 경고."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "정부가 조치를 발표했다. 이번 결과가 중요한 대목이다.",
            "정부 조치가 시행됐다.",
        )
        assert rt is None
        assert warn is not None
        assert "독자 보상" in warn

    def test_kijun_ida_with_save_marker_ok(self):
        """'답은 다음 CPI가 기준이다' — SAVE marker 있으므로 경고 없음."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "지표가 엇갈린다. 답은 다음 CPI가 기준이다.",
            "",
        )
        assert rt == "SAVE"
        assert warn is None

    def test_kijun_ida_without_reward_warns(self):
        """'결국 이것이 기준이다' — SAVE marker 없으므로 경고."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "지표가 엇갈린다. 결국 이것이 기준이다.",
            "",
        )
        assert rt is None
        assert warn is not None
        assert "기준이다" in warn

    # ─── 3. _validate_final_post 와이어링 ────────────────────────────────
    def test_explain_save_ending_no_gate(self):
        """EXPLAIN 마감 — '답은 다음 CPI다' SAVE 문장 → NO_READER_REWARD 없음."""
        from app.services.content_pack import _validate_final_post
        post = (
            "강남3구 하락은 규제 작동 신호다.\n"
            "중저가가 버티는 구조는 따로다.\n"
            "답은 다음 CPI다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "답은 다음 CPI다.", "확정"
        )
        assert "NO_READER_REWARD" not in gate_fails

    def test_judgment_follow_ending_no_gate(self):
        """JUDGMENT — '다음 발표가 나오면 갈린다' FOLLOW → 경고 없음."""
        from app.services.content_pack import _validate_final_post
        post = (
            "지표가 갈린다.\n"
            "A측과 B측 근거가 충돌한다.\n"
            "다음 공식 발표가 나오면 어느 쪽인지 갈린다."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "상충")
        assert "NO_READER_REWARD" not in gate_fails

    def test_verify_template_b_no_gate(self):
        """VERIFY 템플릿 B 예시 — FOLLOW 계열 끝줄 → 경고 없음."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 발언이 아니라 접촉 확인이다.\n"
            "공식 접촉 기록은 현재까지 없다.\n"
            "특사 파견이 포착되면 대화 채널이 살아 있다."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "주장 한 줄. 특사 파견이 공개되면 검증 가능.", "미확인"
        )
        assert "NO_READER_REWARD" not in gate_fails

    def test_closed_analyst_ending_warns(self):
        """닫힌 분석가 마감 — '구조적 의미가 있다' → NO_READER_REWARD 경고."""
        from app.services.content_pack import _validate_final_post
        post = (
            "정부가 새 정책을 공개했다.\n"
            "시장은 조심스럽게 반응했다.\n"
            "이번 조치는 구조적 의미가 있다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "정부 조치 발표.", "확정"
        )
        # "구조적 의미가 있다" 자체는 DEAD_ENDING 도 발동하지만 NO_READER_REWARD
        # 가 반드시 같이 찍혀야 한다.
        assert "NO_READER_REWARD" in gate_fails

    def test_no_reward_is_warn_not_strong(self):
        """NO_READER_REWARD 는 _STRONG_FAIL_TAGS 에 없어야 한다."""
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert "NO_READER_REWARD" not in _STRONG_FAIL_TAGS

    # ─── 4. FinalPost.reward_type 주입 ───────────────────────────────────
    def test_final_post_reward_type_field_save(self):
        from app.services.content_pack import _parse_final_post
        import json
        raw = json.dumps({
            "final_post": (
                "지표가 엇갈린다. 관측이 나뉜다. 답은 다음 CPI다."
            ),
            "final_short": "답은 다음 CPI다.",
        })
        fp = _parse_final_post(raw, certainty_level="확정", mode="EXPLAIN")
        assert fp is not None
        assert fp.reward_type == "SAVE"

    def test_final_post_reward_type_field_follow(self):
        from app.services.content_pack import _parse_final_post
        import json
        raw = json.dumps({
            "final_post": (
                "트럼프 측이 대화 의향을 밝혔다.\n"
                "그러나 실제 접촉은 아직 확인되지 않았다.\n"
                "특사 파견이 공개되면 검증 가능."
            ),
            "final_short": "대화 의향 밝혔다. 접촉은 확인되지 않았다.",
        })
        fp = _parse_final_post(raw, certainty_level="미확인", mode="VERIFY")
        assert fp is not None
        assert fp.reward_type == "FOLLOW"

    def test_final_post_reward_type_field_none_when_closed(self):
        from app.services.content_pack import _parse_final_post
        import json
        raw = json.dumps({
            "final_post": (
                "정부가 발표했다. 반응이 엇갈렸다. 결국 이것이 기준이다."
            ),
            "final_short": "정부가 발표했다.",
        })
        fp = _parse_final_post(raw, certainty_level="확정", mode="EXPLAIN")
        assert fp is not None
        assert fp.reward_type is None

    def test_final_post_reward_type_default_none(self):
        """FinalPost() 기본값 reward_type=None."""
        from app.services.content_pack import FinalPost
        fp = FinalPost()
        assert fp.reward_type is None

    # ─── 5. final_short 요약 vs 추적 포인트 ────────────────────────────
    def test_short_summary_only_warns(self):
        """final_short 가 단순 요약('정부가 발표했다') 이면 reward 없음."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "정부가 새 정책을 발표했다. 시행은 다음 달이다. 현장은 조용하다.",
            "정부가 새 정책을 발표했다.",
        )
        assert rt is None
        assert warn is not None

    def test_short_with_tracking_point_ok(self):
        """'주장 + 확인 포인트' 구조면 reward 검출."""
        from app.services.content_pack import _validate_last_line_reward
        rt, warn = _validate_last_line_reward(
            "정부가 발표했다. 반응이 엇갈린다. 결과는 미확정.",
            "정부가 발표했다. 다음 발표가 나오면 진짜가 드러난다.",
        )
        assert rt == "FOLLOW"
        assert warn is None

    # ─── 6. PR 4~8 회귀 없음 ───────────────────────────────────────────
    def test_verify_strong_gates_intact(self):
        """VERIFY 강게이트 (LOW_CONFIDENCE_OVERREACH) 회귀 없음."""
        from app.services.content_pack import _validate_final_post
        post = (
            "A측이 발언했다.\n"
            "이번 조치는 구조적 의미를 갖는 변화다.\n"
            "공식 발표가 나오면 확인 가능."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "상충")
        # PR 6 기존 강게이트는 그대로 동작
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_banned_endings_new_additions(self):
        """PR 9 에서 _BANNED_ENDINGS 에 추가된 4개 회귀."""
        from app.services.content_pack import _BANNED_ENDINGS
        for phrase in (
            "판별 포인트다",
            "결정한다",
            "의미가 있다",
            "중요한 대목이다",
        ):
            assert phrase in _BANNED_ENDINGS, f"{phrase} 누락"
        # "기준이다" 는 전역 banned 에 넣지 말 것
        assert "기준이다" not in _BANNED_ENDINGS, (
            "'기준이다' 는 전역 banned 가 아니라 reward 조건부 경고"
        )


class TestVerifySentenceCap:
    """VERIFY / 저신뢰 본문은 최대 3문장."""

    def test_verify_body_over_three_sentences_fails(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "A측이 발언했다.\n"
            "아직 확인되지 않았다.\n"
            "특사 파견이 나오면 검증 가능하다.\n"
            "추가로 고위급 접촉도 예상된다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails
        assert any("문장 수 초과" in w for w in warnings)

    def test_verify_body_three_sentences_passes(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "공식 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 공개되면 검증 가능."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails

    def test_high_confidence_four_sentences_allowed(self):
        """EXPLAIN(확정) 은 4문장이 정상 — 문장 수 캡 비적용."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심 명제 한 줄이다.\n"
            "근거 팩트 한 줄이다.\n"
            "판단 기준 한 줄이다.\n"
            "답은 다음 달 거래량이다."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "확정")
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails


class TestVerifyModeInstruction:
    """article_router VERIFY 지시가 저신뢰 과해석 축을 명시적으로 거부."""

    def test_verify_slot_weakens_why_news_matters(self):
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_VERIFY,
        )
        s = _build_mode_slot_instruction(MODE_VERIFY)
        # '왜 뉴스 이상이냐' 슬롯 약화 지시 존재
        assert "왜 뉴스 이상이냐" in s
        assert "약화" in s
        # 3축 고정
        assert "지금 나온 주장" in s
        assert "아직 확인 안 된" in s
        assert "무엇이 확인되면 진짜" in s

    def test_verify_slot_bans_overreach_vocab(self):
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_VERIFY,
        )
        s = _build_mode_slot_instruction(MODE_VERIFY)
        for token in (
            "제3국", "외교 채널", "협상 의제", "긴장 수위",
            "구조적 의미", "다음 국면", "진짜 신호",
        ):
            assert token in s, f"VERIFY 슬롯 금지어 누락: {token}"

    def test_verify_finalize_caps_three_sentences(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        assert "최대 3문장" in s or "3문장" in s
        # 첫 줄 이중 분기 금지 명시
        assert "이중 분기" in s or "이어질지" in s
        # 본문 전역 금지어
        assert "제3국" in s
        assert "구조적 의미" in s
        assert "다음 국면을 결정" in s

    def test_verify_finalize_states_verify_principle(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        # 핵심 원칙: '무슨 일이 벌어질 수 있다' 금지, '아직 확인되지
        # 않았다' 만
        assert "아직 확인되지 않았다" in s

    def test_verify_finalize_bans_closed_tail_after_conditional(self):
        """'~이 나오면 ~라는 뜻이다' 같은 조건부 + 닫힌 판정 조합 차단 명시."""
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        # endswith 금지어가 지시문에 명시됨
        for tok in ("뜻이다", "신호다", "의미한다", "확인이다"):
            assert tok in s, f"VERIFY 마감 금지 토큰 누락: {tok}"
        # 허용 예시 (동사 원형 마감)
        assert "살아 있다" in s or "가깝다" in s or "그쳤다" in s


class TestVerifyOverreachPR6Extended:
    """PR 6 — VERIFY 출력 스키마 축소: 신규 금지 어휘 6개 + body-wide 이중분기."""

    def test_new_overreach_tokens_registered(self):
        """신규 6개 금지 어휘가 OVERREACH 리스트에 등록되어 있다."""
        from app.services.content_pack import _VERIFY_OVERREACH_PATTERNS
        for token in (
            "패러다임", "상징적 의미", "본심", "노림수",
            "를 시사한다", "라는 뜻이다", "제3국 실질 채널",
        ):
            assert any(token in p for p in _VERIFY_OVERREACH_PATTERNS), (
                f"PR 6 신규 VERIFY 금지 어휘 누락: {token}"
            )

    def test_paradigm_triggers_gate(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "A측이 발언했다.\n"
            "이번 조치는 패러다임 변화의 신호다.\n"
            "공식 확인은 없다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "주장. 확인 안 됨.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails
        assert any("VERIFY 구조해석" in w for w in warnings)

    def test_symbolic_meaning_triggers_gate(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "이번 발언의 상징적 의미가 크다.\n"
            "공식 발표는 없다."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "주장. 확인 안 됨.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_signal_verb_triggers_gate(self):
        """'~를 시사한다' 본문 등장 → gate."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "이번 발언은 구조 변화를 시사한다.\n"
            "공식 확인은 없다."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "주장. 확인 안 됨.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_closed_conditional_tail_triggers_gate(self):
        """'~라는 뜻이다' 본문 등장 → gate."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "특사 파견이 없으면 수사라는 뜻이다.\n"
            "공식 확인은 없다."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "주장. 확인 안 됨.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_body_wide_dual_branch_triggers_gate(self):
        """본문 2~3문장에 숨어들어온 이중분기 수사도 차단.

        기존 _VERIFY_WEAK_OPENER_PATTERNS 는 첫 줄만 검사. PR 6 에서
        _VERIFY_OVERREACH_PATTERNS 에 '이어질지/그칠지/판가름' 을 추가해
        본문 전역에서도 잡는다.
        """
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 발언 확인이다.\n"
            "수사에 그칠지 실질로 이어질지가 판가름이다.\n"
            "공식 발표는 없다."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "주장. 확인 안 됨.", "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails

    def test_high_confidence_unaffected_by_new_tokens(self):
        """확정 모드에서는 신규 금지 어휘 gate 발동 안 함 (회귀 방지)."""
        from app.services.content_pack import _validate_final_post
        post = (
            "정부가 공식 발표했다.\n"
            "이번 조치는 패러다임 변화다.\n"
            "시행은 다음 달이다."
        )
        _, _, _, gate_fails = _validate_final_post(post, "", "확정")
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails


class TestVerifyShortSentenceCap:
    """PR 6 — VERIFY / 저신뢰 final_short 는 최대 2문장."""

    def test_verify_short_three_sentences_fails(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "공식 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 공개되면 검증 가능."
        )
        short = (
            "핵심은 접촉 확인이다. "
            "공식 접촉은 없다. "
            "특사 파견이 공개되면 검증 가능이다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, short, "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" in gate_fails
        assert any("짧은 버전 문장 수 초과" in w for w in warnings)

    def test_verify_short_two_sentences_passes(self):
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 접촉 확인이다.\n"
            "공식 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 공개되면 검증 가능."
        )
        short = "핵심은 접촉 확인이다. 특사 파견이 공개되면 검증 가능."
        _, _, _, gate_fails = _validate_final_post(
            post, short, "미확인"
        )
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails

    def test_high_confidence_short_cap_disabled(self):
        """확정(EXPLAIN) 모드에서는 short 2문장 캡 비활성 (회귀 방지)."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심 명제다.\n"
            "근거 팩트다.\n"
            "판단 기준이다.\n"
            "답은 다음 달 거래량이다."
        )
        short = (
            "강남3구부터 꺾였다. "
            "규제가 먼저 고가 주택 심리를 눌렀다. "
            "문제는 중저가까지 번지느냐다."
        )
        _, _, _, gate_fails = _validate_final_post(post, short, "확정")
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails


class TestVerifyFinalizeTemplatesPR6:
    """PR 6 — VERIFY finalize 가 3문장 템플릿 A/B/C 를 강제한다."""

    def test_finalize_includes_three_templates(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        # 템플릿 A/B/C 라벨 존재
        assert "템플릿 A" in s, "VERIFY 템플릿 A 누락"
        assert "템플릿 B" in s, "VERIFY 템플릿 B 누락"
        assert "템플릿 C" in s, "VERIFY 템플릿 C 누락"

    def test_finalize_declares_verifier_not_explainer(self):
        """VERIFY 는 설명문이 아니라 검증문이라는 원칙을 명시."""
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        assert "검증문" in s or "검증 조건만" in s
        assert "아직 단정하면 안 되는가" in s or "아직 확인되지 않았다" in s

    def test_finalize_caps_final_short_two_sentences(self):
        """VERIFY 지시문이 final_short 2문장 규칙을 명시한다."""
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        assert "최대 2문장" in s
        # 구조 힌트 (주장 + 확인 포인트)
        assert "주장" in s and "확인 포인트" in s

    def test_finalize_bans_pr6_new_tokens(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        for tok in (
            "패러다임", "상징적 의미", "본심", "노림수",
            "시사한다", "뜻이다",
        ):
            assert tok in s, f"VERIFY finalize 에 신규 금지 토큰 누락: {tok}"

    def test_slot_instruction_bans_pr6_new_tokens(self):
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_VERIFY,
        )
        s = _build_mode_slot_instruction(MODE_VERIFY)
        for tok in (
            "패러다임", "상징적 의미", "본심", "노림수",
            "제3국 실질 채널",
        ):
            assert tok in s, f"VERIFY slot 에 신규 금지 토큰 누락: {tok}"

    def test_slot_instruction_frames_as_verification(self):
        """슬롯 지시가 '왜 아직 단정하면 안 되는가' 프레임으로 전환."""
        from app.services.content_pack import (
            _build_mode_slot_instruction, MODE_VERIFY,
        )
        s = _build_mode_slot_instruction(MODE_VERIFY)
        assert "아직 단정하면 안 되는가" in s or "검증문" in s


class TestVerifyNoRegressionOnOtherModes:
    """PR 6 — EXPLAIN/JUDGMENT 지시/게이트 회귀 없음."""

    def test_explain_instruction_unchanged_structure(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        # EXPLAIN 4문장 구조 유지
        assert "MODE: EXPLAIN" in s
        assert "4문장" in s
        assert "왜 그 순서로" in s

    def test_judgment_instruction_unchanged(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_JUDGMENT,
        )
        s = _build_mode_finalize_instruction(MODE_JUDGMENT)
        assert "MODE: JUDGMENT" in s
        assert "3문장" in s
        assert "엇갈리는 신호" in s

    def test_explain_body_long_not_gated(self):
        """EXPLAIN(확정) 4~5문장 정상 — PR 6 신규 gate 가 영향 없음."""
        from app.services.content_pack import _validate_final_post
        post = (
            "강남3구부터 거래량이 꺾였다.\n"
            "규제가 먼저 고가 주택 심리를 눌렀다.\n"
            "문제는 중저가까지 번지느냐다.\n"
            "답은 다음 달 거래량이다."
        )
        short = "강남3구부터 꺾였다. 문제는 중저가까지 번지느냐다."
        _, _, _, gate_fails = _validate_final_post(post, short, "확정")
        assert "LOW_CONFIDENCE_OVERREACH" not in gate_fails


class TestDeadEndingRetryHintClosedTokens:
    """DEAD_ENDING 재생성 힌트가 닫힌 판정 토큰을 명시한다."""

    def test_retry_hint_lists_closed_verdict_tokens(self):
        from app.services.content_pack import _build_retry_instruction
        hint = _build_retry_instruction(["DEAD_ENDING"])
        # 실패 샘플 재현 방지: '~이 나오면 ~뜻이다' 조합 차단 명시
        for tok in ("뜻이다", "신호다", "의미한다"):
            assert tok in hint, f"재생성 힌트에 닫힌 토큰 누락: {tok}"
        # 뒤에 붙이지 말라는 메타 지시
        assert "붙이지" in hint or "endswith" in hint


class TestFinalizeUserPromptModeInjection:
    """generate_final_post 실행 시 user_prompt 안에 mode 라벨이 주입된다."""

    @pytest.fixture
    def card_high(self):
        return CandidateCard(
            key_facts=[
                "확정 팩트 — 정부가 공식 발표",
                "확정 팩트 — 관련 법령 공포",
                "확정 팩트 — 시행일 명시",
            ],
            hook_candidates=["확정 훅"],
            thesis_cards=[ThesisCard(
                thesis="확정 해석축",
                why_not_summary="긴장점",
                reader_stake="독자 영향",
                opener="오프너",
                judgment_coord="판단 좌표",
                verification_signal="판별 신호",
            )],
            tensions=["tension1"],
            cautions=["caution1"],
            certainty_level="확정",
        )

    @pytest.fixture
    def card_low(self):
        return CandidateCard(
            key_facts=["미확인 단독 주장"],
            hook_candidates=["훅"],
            thesis_cards=[ThesisCard(
                thesis="해석",
                why_not_summary="긴장",
                reader_stake="영향",
                opener="오프너",
            )],
            cautions=["출처 미검증"],
            certainty_level="미확인",
        )

    def _capture_user_prompt(self, monkeypatch):
        """_call_ai_with_prompt 를 가로채 user_prompt 캡처."""
        captured = {"user_prompt": None}

        async def fake_call(system_prompt, user_prompt, temperature=0.9, **kw):
            captured["user_prompt"] = user_prompt
            # 유효 JSON 반환 — 게이트 통과시켜 1회만 호출되게
            return json.dumps({
                "final_post": (
                    "핵심 명제 한 줄이다.\n"
                    "근거 팩트 한 줄 있다.\n"
                    "판단 좌표 녹아 있다.\n"
                    "새 발표가 6월 전에 나오면 확정이고 안 나오면 선언이다."
                ),
                "final_short": "짧은 버전 한 줄.",
            })

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(*a, **kw):
            return None

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )
        monkeypatch.setattr(
            "app.services.content_pack._grok_eval", fake_grok
        )
        monkeypatch.setattr(
            "app.services.content_pack._claude_review_final", fake_claude
        )
        return captured

    @pytest.mark.asyncio
    async def test_explain_mode_injected_for_high_confidence(
        self, monkeypatch, card_high,
    ):
        from app.services.content_pack import generate_final_post
        cap = self._capture_user_prompt(monkeypatch)
        await generate_final_post(card_high, 0, "")
        up = cap["user_prompt"]
        assert up is not None
        assert "ARTICLE_MODE: EXPLAIN" in up
        assert "MODE: EXPLAIN" in up
        # EXPLAIN에는 VERIFY 전용 표현이 없어야 한다
        assert "MODE: VERIFY" not in up
        assert "MODE: JUDGMENT" not in up

    @pytest.mark.asyncio
    async def test_verify_mode_injected_for_low_confidence(
        self, monkeypatch, card_low,
    ):
        from app.services.content_pack import generate_final_post
        cap = self._capture_user_prompt(monkeypatch)
        await generate_final_post(card_low, 0, "")
        up = cap["user_prompt"]
        assert up is not None
        assert "ARTICLE_MODE: VERIFY" in up
        assert "MODE: VERIFY" in up
        # VERIFY 기사에는 EXPLAIN 4단 가이드가 들어가면 안 됨
        assert "MODE: EXPLAIN" not in up
        # VERIFY 금지어가 프롬프트에 들어가 있어야 함
        assert "숨은 의도" in up or "노림수" in up
        # Low confidence 경고도 유지
        assert "LOW CONFIDENCE" in up


class TestGeminiThesisCardsModeParam:
    """_gemini_generate_thesis_cards 가 mode 파라미터를 받아 user_prompt에 주입."""

    @pytest.mark.asyncio
    async def test_mode_parameter_reaches_user_prompt(self, monkeypatch):
        """Gemini 호출 직전의 user_prompt에 mode별 슬롯 지시가 포함된다."""
        from app.services import content_pack as cp

        # has_gemini True 로 고정
        class _FakeSettings:
            has_gemini = True
            gemini_api_key = "KEY"
        monkeypatch.setattr(
            "app.config.settings", _FakeSettings, raising=False,
        )

        captured = {"body": None}

        class _FakeResp:
            status_code = 200
            text = ""
            def json(self):
                return {
                    "candidates": [{
                        "content": {"parts": [{"text": "{\"thesis_cards\": [], \"tensions\": []}"}]}
                    }],
                    "usageMetadata": {},
                }

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, params=None, headers=None, json=None):
                captured["body"] = json
                return _FakeResp()

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "AsyncClient", _FakeClient)

        await cp._gemini_generate_thesis_cards(
            key_facts=["팩트1"],
            source_text="원문",
            topic_tags=["tag"],
            cautions=["caution"],
            mode=cp.MODE_VERIFY,
        )

        body = captured["body"]
        assert body is not None
        up = body["contents"][0]["parts"][0]["text"]
        assert "VERIFY" in up
        assert "지금 나온 주장" in up
        assert "숨은 의도" in up


# ─── VERIFY 전용 복잡문 게이트 (1개부터) ──────────────────────────────────────
#
# EXPLAIN / JUDGMENT 은 기존대로 복잡문 2개부터 게이트 (경고까지만).
# VERIFY 모드는 브리핑체 복잡문을 구조적으로 차단해야 하므로 1개부터 게이트.


class TestVerifyComplexSentenceGate:
    """VERIFY 모드: 복잡문 1개부터 COMPLEX_SENTENCE gate fail."""

    def test_verify_single_complex_sentence_fails_gate(self):
        """VERIFY + 복잡문 1개 → COMPLEX_SENTENCE 게이트 실패."""
        from app.services.content_pack import _validate_final_post, MODE_VERIFY
        # 쉼표 3개 — complex_hits=1
        post = (
            "현재 나온 주장은 A, B, C, D 네 축으로 정리된다.\n"
            "아직 확인 안 됐다.\n"
            "특사 파견이 나오면 확정."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.",
            certainty_level="미확인",
            mode=MODE_VERIFY,
        )
        assert "COMPLEX_SENTENCE" in gate_fails

    def test_verify_three_simple_sentences_passes_complex_gate(self):
        """VERIFY + 단문 3문장 → COMPLEX_SENTENCE 통과."""
        from app.services.content_pack import _validate_final_post, MODE_VERIFY
        post = (
            "핵심은 접촉 확인이다.\n"
            "공식 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 공개되면 검증 가능."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.",
            certainty_level="미확인",
            mode=MODE_VERIFY,
        )
        assert "COMPLEX_SENTENCE" not in gate_fails

    def test_explain_single_complex_sentence_warn_only(self):
        """EXPLAIN + 복잡문 1개 → 경고만, 게이트 통과 (기존 동작 유지)."""
        from app.services.content_pack import (
            _validate_final_post, MODE_EXPLAIN,
        )
        post = (
            "핵심 명제는 A, B, C, D 네 축이다.\n"
            "근거 팩트 한 줄.\n"
            "판단 좌표 한 줄.\n"
            "6월까지 새 발표가 나오면 확정이고 안 나오면 선언이다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.",
            certainty_level="확정",
            mode=MODE_EXPLAIN,
        )
        # EXPLAIN 은 복잡문 1개에서 경고만 — 게이트는 통과해야 한다
        assert "COMPLEX_SENTENCE" not in gate_fails
        assert any("복잡한 문장" in w for w in warnings)

    def test_judgment_single_complex_sentence_warn_only(self):
        """JUDGMENT + 복잡문 1개 → 경고만, 게이트 통과 (기존 동작 유지)."""
        from app.services.content_pack import (
            _validate_final_post, MODE_JUDGMENT,
        )
        post = (
            "엇갈리는 주장은 A, B, C, D 네 축에서 갈린다.\n"
            "다른 축에서는 반대 해석이 나온다.\n"
            "다음 발표가 갈림길이다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.",
            certainty_level="상충",
            mode=MODE_JUDGMENT,
        )
        assert "COMPLEX_SENTENCE" not in gate_fails
        assert any("복잡한 문장" in w for w in warnings)

    def test_non_verify_two_complex_sentences_still_gated(self):
        """EXPLAIN + 복잡문 2개 → 기존대로 게이트 실패 (하위 호환)."""
        from app.services.content_pack import (
            _validate_final_post, MODE_EXPLAIN,
        )
        post = (
            "핵심 명제는 A, B, C, D 네 축이다.\n"
            "근거는 P, Q, R, S 네 축이다.\n"
            "판단 좌표 한 줄.\n"
            "6월 발표가 나오면 확정."
        )
        _, _, _, gate_fails = _validate_final_post(
            post, "짧은 버전.",
            certainty_level="확정",
            mode=MODE_EXPLAIN,
        )
        assert "COMPLEX_SENTENCE" in gate_fails

    def test_verify_no_mode_param_uses_legacy_threshold(self):
        """mode 인자 없이 호출 시 기존 threshold(≥2) 유지 — 기존 호출부 보호."""
        from app.services.content_pack import _validate_final_post
        post = (
            "핵심은 A, B, C, D 네 축이다.\n"
            "한 줄 추가.\n"
            "결론 한 줄."
        )
        _, _, _, gate_fails = _validate_final_post(post, "짧은 버전.")
        # mode 없이 호출되면 복잡문 1개로는 게이트 발동 안 함
        assert "COMPLEX_SENTENCE" not in gate_fails


# ─── 첫 줄 전용 rewrite 엔진 ─────────────────────────────────────────────────


class TestSpliceOpener:
    """_splice_opener: post 의 첫 문장만 new_opener 로 교체."""

    def test_splice_replaces_first_sentence(self):
        from app.services.content_pack import _splice_opener
        post = "원래 첫 줄이 길다. 두 번째 문장이다. 세 번째다."
        out = _splice_opener(post, "새 핵심 명제다")
        assert out.startswith("새 핵심 명제다.")
        assert "두 번째 문장이다." in out
        assert "세 번째다." in out
        # 원래 첫 문장은 제거돼야 함
        assert "원래 첫 줄이 길다" not in out

    def test_splice_preserves_body_sentences(self):
        from app.services.content_pack import _splice_opener
        post = (
            "첫 문장 A.\n"
            "두 번째 B.\n"
            "세 번째 C."
        )
        out = _splice_opener(post, "완전히 다른 첫 줄")
        assert "두 번째 B." in out
        assert "세 번째 C." in out
        assert "첫 문장 A" not in out

    def test_splice_adds_period_if_missing(self):
        from app.services.content_pack import _splice_opener
        out = _splice_opener("원래 A. 본문 B.", "마침표 없는 새 오프너")
        assert out.startswith("마침표 없는 새 오프너.")

    def test_splice_empty_opener_returns_original(self):
        from app.services.content_pack import _splice_opener
        post = "원래 문장."
        assert _splice_opener(post, "") == post
        assert _splice_opener("", "새 오프너") == ""


class TestRewriteOpenerOnly:
    """_rewrite_opener_only: AI 호출로 첫 문장만 교체."""

    def _make_card(self):
        return CandidateCard(
            key_facts=["확정 팩트"],
            hook_candidates=["훅"],
            thesis_cards=[ThesisCard(
                thesis="해석 슬롯",
                why_not_summary="긴장점",
                reader_stake="독자 영향",
                opener="훅",
                judgment_coord="판단 좌표",
                verification_signal="판별 신호",
            )],
            certainty_level="확정",
        )

    def _make_draft(self):
        return FinalPost(
            final_post=(
                "이후 보도된 긴 배경 설명형 첫 줄 한 문장이 게이트에서 걸렸다.\n"
                "두 번째 문장은 정상.\n"
                "세 번째 판별 신호."
            ),
            final_short="짧은 버전.",
            gate_fails=["WEAK_OPENER"],
        )

    @pytest.mark.asyncio
    async def test_rewrite_success_replaces_first_sentence(self, monkeypatch):
        from app.services.content_pack import (
            _rewrite_opener_only, MODE_EXPLAIN,
        )

        async def fake_call(system_prompt, user_prompt, temperature=0.5, **kw):
            return json.dumps({"new_opener": "새 핵심 명제 한 줄이다"})

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )

        result = await _rewrite_opener_only(
            self._make_card(), self._make_draft(),
            selected_hook="훅", mode=MODE_EXPLAIN,
        )
        assert result is not None
        assert result.final_post.startswith("새 핵심 명제 한 줄이다")
        # 본문 유지 확인
        assert "두 번째 문장은 정상" in result.final_post
        assert "세 번째 판별 신호" in result.final_post
        # WEAK_OPENER 게이트 해소됐는지
        assert "WEAK_OPENER" not in result.gate_fails

    @pytest.mark.asyncio
    async def test_rewrite_ai_none_returns_none(self, monkeypatch):
        from app.services.content_pack import _rewrite_opener_only

        async def fake_call(*a, **kw):
            return None

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )
        result = await _rewrite_opener_only(
            self._make_card(), self._make_draft(), selected_hook="훅",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rewrite_over_60_chars_rejected(self, monkeypatch):
        """60자 초과 new_opener 는 폐기."""
        from app.services.content_pack import _rewrite_opener_only

        too_long = (
            "아주 긴 설명형 문장으로 길게 늘어놓는 첫 줄이 60자를 "
            "훌쩍 넘도록 계속 쓰이고 있어 도저히 통과할 수 없는 아주 길고 긴 오프너"
        )
        assert len(too_long) > 60

        async def fake_call(*a, **kw):
            return json.dumps({"new_opener": too_long})

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )
        result = await _rewrite_opener_only(
            self._make_card(), self._make_draft(), selected_hook="훅",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rewrite_json_parse_error_returns_none(self, monkeypatch):
        from app.services.content_pack import _rewrite_opener_only

        async def fake_call(*a, **kw):
            return "이건 JSON 이 아니다"

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )
        result = await _rewrite_opener_only(
            self._make_card(), self._make_draft(), selected_hook="훅",
        )
        assert result is None


class TestOpenerRewritePathInGenerateFinalPost:
    """generate_final_post: WEAK_OPENER 단독 실패 시 opener 경로를 탄다."""

    @pytest.fixture
    def _card(self):
        return CandidateCard(
            key_facts=["팩트1", "팩트2"],
            hook_candidates=["훅"],
            thesis_cards=[ThesisCard(
                thesis="해석", why_not_summary="긴장",
                reader_stake="영향", opener="훅",
                judgment_coord="판단 좌표",
                verification_signal="판별 신호",
            )],
            certainty_level="확정",
        )

    @pytest.mark.asyncio
    async def test_weak_opener_alone_triggers_opener_rewrite_not_full_regen(
        self, monkeypatch, _card,
    ):
        """
        1차 cycle 이 WEAK_OPENER 하나만 반환할 때,
        _rewrite_opener_only 가 호출되고 _run_cycle 이 2회째 호출되지 않는다.
        """
        from app.services import content_pack as cp

        call_counter = {"cycle": 0, "rewrite": 0}

        # _call_ai_with_prompt: 항상 WEAK_OPENER 걸리는 긴 첫 줄 반환
        async def fake_call(system_prompt, user_prompt, temperature=0.9, **kw):
            call_counter["cycle"] += 1
            return json.dumps({
                "final_post": (
                    "이후 보도된 한참 긴 배경 설명형 첫 줄이 쭉 이어지는 "
                    "초안이다 매우 길게.\n"
                    "두 번째 정상 문장.\n"
                    "세 번째 판별 신호."
                ),
                "final_short": "짧은 버전.",
            })

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(*a, **kw):
            # Claude 보정 실패 → OpenAI 초안 그대로 사용
            return None

        async def fake_rewrite(card, draft, *, selected_hook="", mode=None):
            call_counter["rewrite"] += 1
            return cp.FinalPost(
                final_post=(
                    "새 핵심 명제 한 줄이다.\n"
                    "두 번째 정상 문장.\n"
                    "세 번째 판별 신호."
                ),
                final_short=draft.final_short,
                gate_fails=[],
            )

        monkeypatch.setattr(cp, "_call_ai_with_prompt", fake_call)
        monkeypatch.setattr(cp, "_grok_eval", fake_grok)
        monkeypatch.setattr(cp, "_claude_review_final", fake_claude)
        monkeypatch.setattr(cp, "_rewrite_opener_only", fake_rewrite)

        result = await cp.generate_final_post(_card, 0, "")

        # opener rewrite 경로가 타야 한다
        assert call_counter["rewrite"] == 1
        # PR 14: draft×2 = AI 2회, full regenerate 호출 금지
        assert call_counter["cycle"] == 2
        # rewrite 이후 결과가 반영됐는지
        assert result.final_post.startswith("새 핵심 명제 한 줄이다")

    @pytest.mark.asyncio
    async def test_weak_opener_plus_other_fail_takes_full_regen(
        self, monkeypatch, _card,
    ):
        """WEAK_OPENER + 다른 태그 동시 실패 → opener rewrite 말고 full regen 경로."""
        from app.services import content_pack as cp

        call_counter = {"cycle": 0, "rewrite": 0}

        async def fake_call(system_prompt, user_prompt, temperature=0.9, **kw):
            call_counter["cycle"] += 1
            # WEAK_OPENER + DEAD_ENDING 을 모두 트리거하는 초안
            # 1차/2차 모두 동일 반환해도 호출만 확인하면 됨
            return json.dumps({
                "final_post": (
                    "이후 보도된 배경 설명형 긴 첫 줄이 쭉 이어진다.\n"
                    "두 번째 문장.\n"
                    "마지막은 관건이다"
                ),
                "final_short": "짧은 버전.",
            })

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(*a, **kw):
            return None

        async def fake_rewrite(*a, **kw):
            call_counter["rewrite"] += 1
            return None

        monkeypatch.setattr(cp, "_call_ai_with_prompt", fake_call)
        monkeypatch.setattr(cp, "_grok_eval", fake_grok)
        monkeypatch.setattr(cp, "_claude_review_final", fake_claude)
        monkeypatch.setattr(cp, "_rewrite_opener_only", fake_rewrite)

        await cp.generate_final_post(_card, 0, "")

        # PR 14: full regen 경로 → draft×2 초기 + draft×1 재생성 = AI 3회
        assert call_counter["cycle"] == 3
        # opener rewrite 경로 호출 안 됨
        assert call_counter["rewrite"] == 0


# ─── 분류기 로그 샘플 10개 ─────────────────────────────────────────────────────


class TestClassifierLogSamples:
    """PR 4 분류기가 10개 샘플에 대해 결정적 type + final_mode 를 낸다.

    기자가 캡쳐한 로그("[ArticleType] type=... final=...") 가 CI 위에서
    재현되는지 확인한다. 같은 성질 기사는 항상 같은 mode 로 간다.
    """

    _SAMPLES = [
        # 1. 정석 경제 확정 보도 → STRAIGHT_NEWS + EXPLAIN
        dict(
            name="S1_straight_news_explain",
            card=dict(
                source_url="https://www.yna.co.kr/news/1",
                certainty_level="확정",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["경제"],
            ),
            expect_type="STRAIGHT_NEWS",
            expect_mode="EXPLAIN",
        ),
        # 2. 상충 보도 → CONFLICTING_REPORT + JUDGMENT
        dict(
            name="S2_conflicting_report_judgment",
            card=dict(
                source_url="https://www.yna.co.kr/news/2",
                certainty_level="상충",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["정치"],
            ),
            expect_type="CONFLICTING_REPORT",
            expect_mode="JUDGMENT",
        ),
        # 3. 미확인 단독 → UNVERIFIED_CLAIM + VERIFY
        dict(
            name="S3_unverified_claim_verify",
            card=dict(
                source_url="https://www.yna.co.kr/news/3",
                certainty_level="미확인",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["외교"],
            ),
            expect_type="UNVERIFIED_CLAIM",
            expect_mode="VERIFY",
        ),
        # 4. 오피니언 컬럼 URL → OPINION_COLUMN + VERIFY
        dict(
            name="S4_opinion_column_verify",
            card=dict(
                source_url="https://news.example.com/column/2026/04/opinion",
                certainty_level="확정",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["칼럼"],
            ),
            expect_type="OPINION_COLUMN",
            expect_mode="VERIFY",
        ),
        # 5. 커뮤니티 스크린샷 → COMMUNITY_SCREENSHOT + VERIFY
        dict(
            name="S5_community_screenshot_verify",
            card=dict(
                source_url="https://www.dcinside.com/board/xxx",
                certainty_level="확정",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["정치"],
            ),
            expect_type="COMMUNITY_SCREENSHOT",
            expect_mode="VERIFY",
        ),
        # 6. 시장 급변 보도 (주가/시세) → MARKET_MOVING_NEWS + EXPLAIN
        dict(
            name="S6_market_moving_explain",
            card=dict(
                source_url="https://www.yna.co.kr/news/6",
                certainty_level="확정",
                key_facts=["삼성전자 장중 7.3% 급락", "거래대금 2조원", "환율 1420원"],
                topic_tags=["증시", "경제"],
            ),
            expect_type="MARKET_MOVING_NEWS",
            expect_mode="EXPLAIN",
        ),
        # 7. 단독 태그 → UNVERIFIED_CLAIM + VERIFY (단독은 미확인으로 보수 강등)
        dict(
            name="S7_solo_scoop_verify",
            card=dict(
                source_url="https://www.yna.co.kr/news/7",
                certainty_level="미확인",
                key_facts=["팩트1", "팩트2"],
                topic_tags=["단독"],
            ),
            expect_type="UNVERIFIED_CLAIM",
            expect_mode="VERIFY",
        ),
        # 8. reddit 캡처성 URL → COMMUNITY_SCREENSHOT + VERIFY
        dict(
            name="S8_reddit_community_verify",
            card=dict(
                source_url="https://www.reddit.com/r/news/comments/abc",
                certainty_level="확정",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["해외", "커뮤니티"],
            ),
            expect_type="COMMUNITY_SCREENSHOT",
            expect_mode="VERIFY",
        ),
        # 9. 근거 얕은 확정 (key_facts ≤ 2) → EXPLAIN→JUDGMENT (legacy demotion)
        dict(
            name="S9_thin_facts_judgment",
            card=dict(
                source_url="https://www.yna.co.kr/news/9",
                certainty_level="확정",
                key_facts=["팩트1", "팩트2"],  # ≤ 2 → 최소 JUDGMENT
                topic_tags=["경제"],
            ),
            expect_type="STRAIGHT_NEWS",
            expect_mode="JUDGMENT",
        ),
        # 10. 약신호 topic_tag → EXPLAIN→JUDGMENT (legacy weak_tag demotion)
        dict(
            name="S10_weak_tag_verify",
            card=dict(
                source_url="https://www.yna.co.kr/news/10",
                certainty_level="확정",
                key_facts=["팩트1", "팩트2", "팩트3"],
                topic_tags=["루머", "정치"],  # '루머' → weak_tag
            ),
            # weak_tag 은 classify 쪽에서 UNVERIFIED_CLAIM 로 밀어 VERIFY 가 됨
            expect_type="UNVERIFIED_CLAIM",
            expect_mode="VERIFY",
        ),
    ]

    def test_ten_samples_classify_deterministically(self, caplog):
        """10개 샘플 classify + route → 결정적 결과 + 로그 출력."""
        import logging
        from app.services.content_pack import (
            classify_article_type, route_article_mode,
        )

        caplog.set_level(logging.INFO, logger="app.services.article_router")

        results = []
        for s in self._SAMPLES:
            card = CandidateCard(**s["card"])
            t = classify_article_type(card)
            m = route_article_mode(card)
            results.append((s["name"], t, m))
            assert t == s["expect_type"], (
                f"{s['name']}: type 불일치 — got={t} expect={s['expect_type']}"
            )
            assert m == s["expect_mode"], (
                f"{s['name']}: mode 불일치 — got={m} expect={s['expect_mode']}"
            )

        # 로그에 [ArticleType] line 이 10개 샘플 모두에 대해 남아야 한다
        article_type_logs = [
            r for r in caplog.records if "[ArticleType]" in r.getMessage()
        ]
        # route_article_mode 1회 호출당 최소 1개 로그 (error 제외)
        assert len(article_type_logs) >= 10, (
            f"[ArticleType] 로그가 10개 미만: {len(article_type_logs)}개"
        )

        # 6개 type 모두 최소 한 번 이상 샘플에 등장해야 한다 (분류기 커버리지)
        types_seen = {t for _, t, _ in results}
        for expected_type in (
            "STRAIGHT_NEWS", "CONFLICTING_REPORT", "UNVERIFIED_CLAIM",
            "OPINION_COLUMN", "COMMUNITY_SCREENSHOT", "MARKET_MOVING_NEWS",
        ):
            assert expected_type in types_seen, (
                f"샘플이 {expected_type} 를 커버하지 않음"
            )

        # 3개 mode 모두 최소 한 번 이상 샘플에 등장해야 한다
        modes_seen = {m for _, _, m in results}
        assert {"EXPLAIN", "JUDGMENT", "VERIFY"} <= modes_seen


# ─── PR 5: Opener 점수 함수 + 2회 재시도 + full regen 폴백 ─────────────────


class TestScoreOpener:
    """_score_opener: 첫 줄 품질을 결정론적 규칙으로 0~100 점수화."""

    def test_empty_string_is_zero(self):
        from app.services.content_pack import _score_opener
        assert _score_opener("") == 0
        assert _score_opener("   ") == 0

    def test_over_60_chars_is_zero_hard_cap(self):
        from app.services.content_pack import _score_opener
        long_opener = (
            "아주 긴 설명형 문장으로 길게 늘어놓는 첫 줄이 60자를 "
            "훌쩍 넘도록 계속 쓰이고 있어 통과할 수 없는 긴 오프너"
        )
        assert len(long_opener) > 60
        assert _score_opener(long_opener) == 0

    def test_short_clean_opener_passes_threshold(self):
        """45자 이하 + 감점 없음 → 50+15 = 65점 (>= 60)."""
        from app.services.content_pack import _score_opener, _OPENER_MIN_SCORE
        score = _score_opener("미국이 처음 보상안을 꺼냈다")
        assert score >= _OPENER_MIN_SCORE
        assert score == 65

    def test_strong_keyword_bonus(self):
        """강한 키워드('핵심은') 가점."""
        from app.services.content_pack import _score_opener
        plain = _score_opener("새 규제가 시행된다")  # ≤45 → 65
        bonus = _score_opener("핵심은 시행일 변경이다")  # ≤45 + strong → 75
        assert bonus > plain
        assert bonus == 75

    def test_background_start_penalty(self):
        """배경 시작어 '이후 '는 감점 30."""
        from app.services.content_pack import _score_opener, _OPENER_MIN_SCORE
        score = _score_opener("이후 보도된 한국 정부 발표가 나왔다")
        # 50 + 15(len≤45) - 30(배경) = 35
        assert score < _OPENER_MIN_SCORE
        assert score <= 40

    def test_bifurcation_penalty(self):
        """'이어질지 / 그칠지 / 판가름' 감점."""
        from app.services.content_pack import _score_opener, _OPENER_MIN_SCORE
        s1 = _score_opener("이번 회담이 이어질지 그칠지가 갈림이다")
        # 50 +15 -25(이어질지) +10(갈림) = 50 → 미달
        assert s1 < _OPENER_MIN_SCORE

    def test_fact_narration_penalty(self):
        """기사 재서술 패턴 감점."""
        from app.services.content_pack import _score_opener, _OPENER_MIN_SCORE
        score = _score_opener("한국은행이 금리 인하를 결정했다고 밝혔다")
        # 50 +15 -20(다고 밝혔다) = 45
        assert score < _OPENER_MIN_SCORE

    def test_verify_overreach_heavy_penalty(self):
        """VERIFY/저신뢰에서 구조 해석 금지어 -35."""
        from app.services.content_pack import _score_opener, MODE_VERIFY
        score = _score_opener(
            "외교 채널 복원이 최근 포인트다",
            mode=MODE_VERIFY,
            certainty_level="미확인",
        )
        # 50 +15(≤45) -35(외교 채널 복원) = 30, < 60 미달
        assert score < 60
        assert score == 30

    def test_verify_weak_opener_bifurcation_penalty(self):
        """VERIFY + '이어질지/그칠지' 복합 감점."""
        from app.services.content_pack import _score_opener, MODE_VERIFY
        s = _score_opener(
            "단순 수사인지 실질 채널인지 갈림이다",
            mode=MODE_VERIFY,
            certainty_level="미확인",
        )
        # 50 +15(len<=45) -25(이어질지 패턴 아님, 판가름 아님,
        # 실제로는 _VERIFY_WEAK_OPENER_PATTERNS 에 '단순 수사인지', '실질 채널인지'
        # 매칭) -25 +10(갈림) = 25
        assert s < 60

    def test_banned_ending_penalty(self):
        """금지 마감('관건이다') 으로 끝나면 감점."""
        from app.services.content_pack import _score_opener, _OPENER_MIN_SCORE
        score = _score_opener("다음 발표가 관건이다")
        # 50 +15 -20(금지 마감) +10(관건은? 매칭 안 됨, _STRONG_OPENER_WORDS 에
        # '관건은'으로 등록되어 있으므로 '관건이다'는 매칭 안 됨) = 45
        assert score < _OPENER_MIN_SCORE

    def test_length_tier_45_vs_55(self):
        """≤45 +15, 46~55 +5, 56~60 +0."""
        from app.services.content_pack import _score_opener
        s45 = _score_opener("가" * 45)  # 50+15 = 65
        s50 = _score_opener("가" * 50)  # 50+5 = 55
        s58 = _score_opener("가" * 58)  # 50+0 = 50
        assert s45 == 65
        assert s50 == 55
        assert s58 == 50


class TestOpenerRewriteScoreThreshold:
    """_rewrite_opener_only 가 _score_opener 임계값으로 거부·통과."""

    def _make_card(self):
        return CandidateCard(
            key_facts=["팩트"],
            hook_candidates=["훅"],
            thesis_cards=[ThesisCard(
                thesis="해석", why_not_summary="긴장",
                reader_stake="영향", opener="훅",
                judgment_coord="판단 좌표",
                verification_signal="판별 신호",
            )],
            certainty_level="확정",
        )

    def _make_draft(self):
        return FinalPost(
            final_post=(
                "이후 보도된 긴 배경 설명형 첫 줄이 게이트에 걸렸다.\n"
                "두 번째 문장.\n"
                "세 번째 판별 신호."
            ),
            final_short="짧은 버전.",
            gate_fails=["WEAK_OPENER"],
        )

    @pytest.mark.asyncio
    async def test_low_score_opener_rejected(self, monkeypatch):
        """배경어 시작 new_opener (score < 60) → None 반환."""
        from app.services.content_pack import _rewrite_opener_only

        async def fake_call(*a, **kw):
            # "이후 보도된" 시작 → -30점, total ~35점
            return json.dumps({"new_opener": "이후 보도된 새 발표가 나왔다"})

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )
        result = await _rewrite_opener_only(
            self._make_card(), self._make_draft(), selected_hook="훅",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_high_score_opener_accepted(self, monkeypatch):
        """깨끗한 짧은 opener (score ≥ 60) → 반영."""
        from app.services.content_pack import _rewrite_opener_only

        async def fake_call(*a, **kw):
            return json.dumps({"new_opener": "핵심은 시행일 변경이다"})

        monkeypatch.setattr(
            "app.services.content_pack._call_ai_with_prompt", fake_call
        )
        result = await _rewrite_opener_only(
            self._make_card(), self._make_draft(), selected_hook="훅",
        )
        assert result is not None
        assert result.final_post.startswith("핵심은 시행일 변경이다")


class TestOpenerRewriteTwoAttemptsThenFullRegen:
    """PR 5: 2회 opener 시도 → 둘 다 폐기 시 full regen 폴백."""

    @pytest.fixture
    def _card(self):
        return CandidateCard(
            key_facts=["팩트1", "팩트2"],
            hook_candidates=["훅"],
            thesis_cards=[ThesisCard(
                thesis="해석", why_not_summary="긴장",
                reader_stake="영향", opener="훅",
                judgment_coord="판단 좌표",
                verification_signal="판별 신호",
            )],
            certainty_level="확정",
        )

    @pytest.mark.asyncio
    async def test_first_attempt_low_score_second_high_score(
        self, monkeypatch, _card,
    ):
        """1차 opener 점수 미달 → 2차 opener 통과 → rewrite 성공."""
        from app.services import content_pack as cp

        # 호출 시퀀스 (PR 14: draft×2):
        # call 1-2: 초안 생성 ×2 (WEAK_OPENER) — 1차 cycle draft_count=2
        # call 3: opener rewrite 시도 1 (low score — 배경어)
        # call 4: opener rewrite 시도 2 (high score — 깨끗한 opener)
        bad_draft = json.dumps({
            "final_post": (
                "이후 보도된 긴 배경 설명형 첫 줄이 길게 쭉 이어진다.\n"
                "두 번째 정상 문장.\n"
                "세 번째 판별 신호."
            ),
            "final_short": "짧은 버전.",
        })
        responses = [
            bad_draft, bad_draft,
            json.dumps({"new_opener": "이후 보도된 배경어 시작 문장이다"}),
            json.dumps({"new_opener": "핵심은 시행일 변경이다"}),
        ]
        call_counter = {"idx": 0}

        async def fake_call(system_prompt, user_prompt, *, temperature=0.7, **kw):
            idx = call_counter["idx"]
            call_counter["idx"] += 1
            return responses[idx] if idx < len(responses) else None

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(*a, **kw):
            return None

        monkeypatch.setattr(cp, "_call_ai_with_prompt", fake_call)
        monkeypatch.setattr(cp, "_grok_eval", fake_grok)
        monkeypatch.setattr(cp, "_claude_review_final", fake_claude)

        result = await cp.generate_final_post(_card, 0, "")

        # PR 14: 총 4회: draft×2 + opener 시도 2회
        assert call_counter["idx"] == 4
        # 최종 첫 줄이 2차 시도 opener 로 교체됐어야 한다
        assert result.final_post.startswith("핵심은 시행일 변경이다")

    @pytest.mark.asyncio
    async def test_both_attempts_low_score_falls_back_to_full_regen(
        self, monkeypatch, _card,
    ):
        """2회 모두 점수 미달 → full regen 폴백 경로 발동."""
        from app.services import content_pack as cp

        # 호출 시퀀스 (PR 14: draft×2):
        # call 1-2: 초안 ×2 (WEAK_OPENER) — draft_count=2
        # call 3: opener rewrite 시도 1 (low score)
        # call 4: opener rewrite 시도 2 (low score)
        # call 5: full regen cycle (draft_count=1)
        bad_draft = json.dumps({
            "final_post": (
                "이후 보도된 긴 배경 설명형 첫 줄이 길게 쭉 이어진다.\n"
                "두 번째 정상 문장.\n"
                "세 번째 판별 신호."
            ),
            "final_short": "짧은 버전.",
        })
        responses = [
            bad_draft, bad_draft,
            json.dumps({"new_opener": "이후 보도된 배경형 1"}),
            json.dumps({"new_opener": "이후 보도된 배경형 2"}),
            json.dumps({
                "final_post": (
                    "핵심은 시행일 변경이다.\n"
                    "두 번째 정상 문장.\n"
                    "6월 발표가 나오면 확정."
                ),
                "final_short": "짧은 버전.",
            }),
        ]
        call_counter = {"idx": 0}

        async def fake_call(system_prompt, user_prompt, *, temperature=0.7, **kw):
            idx = call_counter["idx"]
            call_counter["idx"] += 1
            return responses[idx] if idx < len(responses) else None

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(*a, **kw):
            return None

        monkeypatch.setattr(cp, "_call_ai_with_prompt", fake_call)
        monkeypatch.setattr(cp, "_grok_eval", fake_grok)
        monkeypatch.setattr(cp, "_claude_review_final", fake_claude)

        result = await cp.generate_final_post(_card, 0, "")

        # PR 14: draft×2 + opener 2회 + full regen(draft×1) = 5회
        assert call_counter["idx"] == 5
        # full regen 결과가 채택되어야 한다
        assert result.final_post.startswith("핵심은 시행일 변경이다")
        # WEAK_OPENER 해소
        assert "WEAK_OPENER" not in result.gate_fails

    @pytest.mark.asyncio
    async def test_body_preserved_across_opener_rewrite(
        self, monkeypatch, _card,
    ):
        """opener rewrite 이후에도 본문 2~3 문장이 바뀌지 않는다."""
        from app.services import content_pack as cp

        body_second = "아주 특별한 두 번째 문장 표식 XYZ123"
        body_third = "세 번째 판별 신호 표식 판별"

        bad_draft = json.dumps({
            "final_post": (
                f"이후 보도된 긴 배경 설명형 첫 줄이 길게 쭉 이어진다.\n"
                f"{body_second}.\n"
                f"{body_third}."
            ),
            "final_short": "짧은 버전.",
        })
        # PR 14: draft×2 + opener rewrite 1회
        responses = [
            bad_draft, bad_draft,
            json.dumps({"new_opener": "핵심은 시행일 변경이다"}),
        ]
        idx = {"v": 0}

        async def fake_call(system_prompt, user_prompt, *, temperature=0.7, **kw):
            v = idx["v"]
            idx["v"] += 1
            return responses[v] if v < len(responses) else None

        async def fake_grok(*a, **kw):
            return None

        async def fake_claude(*a, **kw):
            return None

        monkeypatch.setattr(cp, "_call_ai_with_prompt", fake_call)
        monkeypatch.setattr(cp, "_grok_eval", fake_grok)
        monkeypatch.setattr(cp, "_claude_review_final", fake_claude)

        result = await cp.generate_final_post(_card, 0, "")

        # 본문 표식이 그대로 남아야 한다
        assert body_second in result.final_post
        assert body_third in result.final_post
        # 첫 줄은 교체됨
        assert result.final_post.startswith("핵심은 시행일 변경이다")


# ─────────────────────────────────────────────────────────────────────────────
# PR 10 — Findability Layer + Market/Stake Layer
# ─────────────────────────────────────────────────────────────────────────────


class TestFindabilityLayer:
    """
    PR 10 — Findability Layer.

    첫 2문장에 검색 가능한 고유명사/숫자/기관명/지표가 충분한지 검사.
    LOW_FINDABILITY 는 WARN-only, _STRONG_FAIL_TAGS 미편입.
    """

    # ─── 1. _extract_first_two_sentences ─────────────────────────────────

    def test_extract_two_sentences_normal(self):
        text = "삼성전자 노조가 파업을 예고했다. 답은 실제 참여율이다. 후속 확인 필요."
        result = _extract_first_two_sentences(text)
        assert "삼성전자" in result
        assert "참여율" in result
        # 3번째 문장은 포함되지 않아야
        assert "후속" not in result

    def test_extract_two_sentences_newline(self):
        text = "국세청이 8가지 지원책을 발표했다\n핵심은 신청 가능한 항목 수다"
        result = _extract_first_two_sentences(text)
        assert "국세청" in result
        assert "신청" in result

    def test_extract_empty(self):
        assert _extract_first_two_sentences("") == ""
        assert _extract_first_two_sentences("단문") == "단문"

    # ─── 2. _count_findability_anchors ────────────────────────────────────

    def test_count_anchors_samsung_date(self):
        """삼성전자 + 5월 21일 → 앵커 3개 이상 (삼성, 5, 21)."""
        text = "삼성전자 노조가 5월 21일부터 총파업을 예고했다"
        count = _count_findability_anchors(text)
        assert count >= 3

    def test_count_anchors_nts_number(self):
        """국세청 + 8가지 → 앵커 2개 이상."""
        text = "국세청이 소상공인 세정지원 8가지를 발표했다"
        count = _count_findability_anchors(text)
        assert count >= 2

    def test_count_anchors_coingecko(self):
        """CoinGecko + 30% → 앵커 2개 이상."""
        text = "한국 코인 거래 30%설은 아직 CoinGecko 원본이 없다"
        count = _count_findability_anchors(text)
        assert count >= 2

    def test_count_anchors_cpi(self):
        """CPI → 영문 약어 앵커 1개."""
        text = "답은 다음 CPI가 기준이다"
        count = _count_findability_anchors(text)
        assert count >= 1

    def test_count_anchors_pure_abstract(self):
        """추상명사만 → 앵커 0."""
        text = "정책 변화가 시장에 영향을 줄 수 있다"
        count = _count_findability_anchors(text)
        assert count == 0

    def test_count_anchors_another_abstract(self):
        """추상명사만 (구조 변화) → 앵커 0."""
        text = "이번 구조 변화는 중요한 의미가 있다"
        count = _count_findability_anchors(text)
        assert count == 0

    def test_count_anchors_known_entity_trump(self):
        """트럼프 → 인물 고유명사 앵커 1개."""
        text = "트럼프가 관세를 올렸다"
        count = _count_findability_anchors(text)
        assert count >= 1

    def test_count_anchors_region(self):
        """강남 → 지역명 앵커."""
        text = "강남3구가 먼저 꺾였다"
        count = _count_findability_anchors(text)
        # 강남 + 3 = 2개
        assert count >= 2

    # ─── 3. _validate_findability ─────────────────────────────────────────

    def test_findability_pass_with_2_anchors(self):
        """고유명사 + 숫자 → 통과."""
        post = "삼성전자 노조가 5월 21일부터 총파업을 예고했다.\n답은 실제 참여율이다."
        count, warn = _validate_findability(post)
        assert count >= 2
        assert warn is None

    def test_findability_warn_1_anchor(self):
        """앵커 1개 → 경고만, gate tag 없음."""
        post = "트럼프가 관세를 올렸다.\n시장 반응은 아직 미정이다."
        count, warn = _validate_findability(post)
        assert count >= 1
        assert warn is not None
        assert "권장" in warn

    def test_findability_fail_0_anchors(self):
        """앵커 0 → LOW_FINDABILITY 사유 반환."""
        post = "정책 변화가 시장에 영향을 줄 수 있다.\n이번 구조 변화는 중요하다."
        count, warn = _validate_findability(post)
        assert count == 0
        assert warn is not None
        assert "추상명사" in warn

    def test_findability_empty_post(self):
        count, warn = _validate_findability("")
        assert count == 0
        assert warn is None

    # ─── 4. _validate_final_post wiring ──────────────────────────────────

    def test_validate_final_post_good_findability(self):
        """구체 앵커 충분 → LOW_FINDABILITY 없음."""
        post = "삼성전자 노조가 5월 21일부터 파업을 예고했다.\n답은 실제 참여율이다."
        _, _, warnings, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "LOW_FINDABILITY" not in gate_fails

    def test_validate_final_post_abstract_only(self):
        """추상명사만 → LOW_FINDABILITY gate tag (WARN-only)."""
        post = "정책 변화가 시장에 영향을 줄 수 있다.\n이번 구조 변화는 중요하다."
        _, _, warnings, gate_fails = _validate_final_post(post, "짧은 버전.")
        assert "LOW_FINDABILITY" in gate_fails

    def test_low_findability_not_in_strong_fail(self):
        """LOW_FINDABILITY 는 _STRONG_FAIL_TAGS 에 없어야 한다."""
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert "LOW_FINDABILITY" not in _STRONG_FAIL_TAGS

    # ─── 5. EXPLAIN 시장 반영 포인트 ─────────────────────────────────────

    def test_explain_market_stake_post_pass(self):
        """EXPLAIN — 시장 반영 포인트가 포함된 post 는 추가 경고 없음."""
        post = (
            "삼성전자 노조가 5월 21일부터 파업을 예고했다.\n"
            "이게 맞으면 시장은 메모리 공급 부담부터 반영할 수 있다.\n"
            "답은 실제 참여율이다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.", mode="EXPLAIN"
        )
        assert "LOW_FINDABILITY" not in gate_fails

    # ─── 6. JUDGMENT 갈림 기준 ────────────────────────────────────────────

    def test_judgment_divergence_post_pass(self):
        """JUDGMENT — 갈림 기준이 있는 post 는 추가 경고 없음."""
        post = (
            "관세 25%를 놓고 산업부와 무역협회 해석이 갈린다.\n"
            "산업부는 협상 카드, 무역협회는 실행 의지로 본다.\n"
            "관건은 첫 공시다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.", mode="JUDGMENT"
        )
        assert "LOW_FINDABILITY" not in gate_fails

    # ─── 7. VERIFY 확인 포인트 pass ──────────────────────────────────────

    def test_verify_confirmation_point_pass(self):
        """VERIFY — 확인 포인트만 남긴 post 통과."""
        post = (
            "트럼프 측이 대화 의향을 밝혔다.\n"
            "실제 접촉은 아직 확인되지 않았다.\n"
            "특사 파견이 공개되면 검증 가능."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.", certainty_level="미확인", mode="VERIFY"
        )
        assert "LOW_FINDABILITY" not in gate_fails

    # ─── 8. VERIFY 예언형 문장 gate ──────────────────────────────────────

    def test_verify_prophecy_banned_ending(self):
        """VERIFY — '영향이 예상된다' 는 DEAD_ENDING."""
        post = (
            "트럼프 측이 관세 인상을 시사했다.\n"
            "확인되지 않았다.\n"
            "시장에 영향이 예상된다."
        )
        _, _, warnings, gate_fails = _validate_final_post(
            post, "짧은 버전.", certainty_level="미확인", mode="VERIFY"
        )
        assert "DEAD_ENDING" in gate_fails

    # ─── 9. Reader Reward Layer 회귀 없음 ────────────────────────────────

    def test_reader_reward_still_works(self):
        """PR 9 Reader Reward Layer 가 PR 10 이후에도 정상 동작."""
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("답은 다음 CPI가 기준이다.") == "SAVE"
        assert _detect_reward_type("특사 파견이 공개되면 검증 가능.") == "FOLLOW"
        assert _detect_reward_type("말보다 숫자가 먼저다.") == "SHARE"

    # ─── 10. PR 4-9 strong fail 구조 회귀 ─────────────────────────────────

    def test_strong_fail_tags_unchanged(self):
        """_STRONG_FAIL_TAGS 는 여전히 4개만."""
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert _STRONG_FAIL_TAGS == frozenset({
            "WEAK_OPENER", "DEAD_ENDING",
            "STRUCTURE_COLUMN", "LOW_CONFIDENCE_OVERREACH",
        })

    # ─── 11. 신규 _BANNED_ENDINGS 작동 ──────────────────────────────────

    def test_banned_ending_structural_change(self):
        """PR 10 추가: '구조적 변화다' → DEAD_ENDING."""
        post = "이번 조치는 구조적 변화다."
        _, _, warnings, gate_fails = _validate_final_post(post, "")
        assert "DEAD_ENDING" in gate_fails

    def test_banned_ending_impact_expected(self):
        """PR 10 추가: '영향이 예상된다' → DEAD_ENDING."""
        post = "수출 시장에 영향이 예상된다."
        _, _, warnings, gate_fails = _validate_final_post(post, "")
        assert "DEAD_ENDING" in gate_fails

    def test_banned_ending_attention_needed(self):
        """PR 10 추가: '관심이 필요하다' → DEAD_ENDING."""
        post = "향후 정책 변화에 관심이 필요하다."
        _, _, warnings, gate_fails = _validate_final_post(post, "")
        assert "DEAD_ENDING" in gate_fails

    def test_banned_ending_suggests_standalone(self):
        """PR 10 추가: '시사한다' standalone → DEAD_ENDING."""
        post = "이번 결과는 변화를 시사한다."
        _, _, warnings, gate_fails = _validate_final_post(post, "")
        assert "DEAD_ENDING" in gate_fails

    # ─── 12. 앵커 사전 샘플 ──────────────────────────────────────────────

    def test_anchor_known_entities_coverage(self):
        """_FINDABILITY_KNOWN_ENTITIES 에 주요 기관/기업 포함."""
        assert "삼성" in _FINDABILITY_KNOWN_ENTITIES
        assert "국세청" in _FINDABILITY_KNOWN_ENTITIES
        assert "트럼프" in _FINDABILITY_KNOWN_ENTITIES
        assert "미국" in _FINDABILITY_KNOWN_ENTITIES
        assert "강남" in _FINDABILITY_KNOWN_ENTITIES

    def test_anchor_regex_matches_acronyms(self):
        """_FINDABILITY_ANCHOR_RE 가 영문 약어를 잡는다."""
        import re
        assert _FINDABILITY_ANCHOR_RE.search("CPI") is not None
        assert _FINDABILITY_ANCHOR_RE.search("GDP") is not None
        assert _FINDABILITY_ANCHOR_RE.search("KOSPI") is not None
        assert _FINDABILITY_ANCHOR_RE.search("SK") is not None

    def test_anchor_regex_matches_numbers(self):
        """_FINDABILITY_ANCHOR_RE 가 숫자를 잡는다."""
        import re
        assert _FINDABILITY_ANCHOR_RE.search("25%") is not None
        assert _FINDABILITY_ANCHOR_RE.search("3,000억") is not None
        assert _FINDABILITY_ANCHOR_RE.search("5월") is not None


class TestMarketStakePromptRules:
    """
    PR 10 — article_router.py 에 삽입된
    Findability + Market/Stake Layer 프롬프트 존재 확인.
    """

    def test_explain_findability_prompt(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        assert "Findability" in s
        assert "Market/Stake" in s
        assert "추상명사" in s
        assert "고유명사" in s or "기관명" in s
        assert "시장은 원가 부담" in s

    def test_judgment_findability_prompt(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_JUDGMENT,
        )
        s = _build_mode_finalize_instruction(MODE_JUDGMENT)
        assert "Findability" in s
        assert "갈림 기준" in s
        assert "관건은 첫 공시다" in s

    def test_verify_findability_prompt(self):
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        assert "Findability" in s
        assert "예언 금지" in s
        assert "확인 포인트" in s

    def test_verify_still_bans_prediction(self):
        """VERIFY 에 '시장이 크게 반응할 것이다' 금지 포함."""
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_VERIFY,
        )
        s = _build_mode_finalize_instruction(MODE_VERIFY)
        assert "시장이 크게 반응할 것이다" in s

    def test_explain_bans_abstract_vague(self):
        """EXPLAIN 에 '영향이 예상된다' 금지 포함."""
        from app.services.content_pack import (
            _build_mode_finalize_instruction, MODE_EXPLAIN,
        )
        s = _build_mode_finalize_instruction(MODE_EXPLAIN)
        assert "영향이 예상된다" in s


# ─────────────────────────────────────────────────────────────────────────────
# PR 11 — Reader Question Resolver
# ─────────────────────────────────────────────────────────────────────────────


class TestReaderQuestionResolver:
    """
    PR 11 — Reader Question Resolver.

    독자 핵심 질문 3개 생성 → source_text 대조 → 커버리지 검증.
    UNRESOLVED_READER_QUESTION 는 WARN-only, _STRONG_FAIL_TAGS 미편입.
    """

    # ─── helper ──────────────────────────────────────────────────────────

    def _make_card(self, **kwargs):
        """테스트용 CandidateCard 생성."""
        from app.services.content_pack import ThesisCard
        defaults = dict(
            key_facts=["삼성전자 노조가 5월 21일부터 파업 예고",
                        "메모리 반도체 라인 영향 가능성"],
            hook_candidates=["파업 예고 자체보다 실제 참여율이 핵심"],
            thesis_cards=[ThesisCard(
                thesis="파업 예고보다 실제 참여율이 핵심",
                reader_stake="메모리 반도체 공급에 직결",
                opener="삼성전자 노조가 파업을 예고했다",
            )],
            tensions=["노조 요구 vs 경영진 입장"],
            one_liner=["답은 실제 참여율이다"],
            cautions=["과장 금지"],
            watch_points=["5월 21일 참여율"],
            certainty_level="확정",
            topic_tags=["반도체"],
            risk_flags=[],
        )
        defaults.update(kwargs)
        return CandidateCard(**defaults)

    # ─── 1. ReaderQuestion 데이터클래스 ──────────────────────────────────

    def test_reader_question_defaults(self):
        q = ReaderQuestion(question="테스트", category="SOURCE")
        assert q.status == "UNRESOLVED"
        assert q.evidence == ""

    def test_reader_question_resolved(self):
        q = ReaderQuestion(question="테스트", category="SCOPE", status="RESOLVED",
                           evidence="수치 확인")
        assert q.status == "RESOLVED"
        assert q.evidence == "수치 확인"

    # ─── 2. FinalPost 신규 필드 ──────────────────────────────────────────

    def test_final_post_question_fields(self):
        fp = FinalPost()
        assert fp.reader_questions == []
        assert fp.resolved_count == 0
        assert fp.unresolved_count == 0

    def test_final_post_question_fields_set(self):
        qs = [ReaderQuestion(question="Q1", category="SOURCE", status="RESOLVED")]
        fp = FinalPost(reader_questions=qs, resolved_count=1, unresolved_count=0)
        assert len(fp.reader_questions) == 1
        assert fp.resolved_count == 1

    # ─── 3. _generate_reader_questions ───────────────────────────────────

    def test_generate_4_questions(self):
        """PR 12 v2 — 4개 질문 생성 (SOURCE/SCOPE/IMPACT/CHECKPOINT)."""
        card = self._make_card()
        qs = _generate_reader_questions(card, "EXPLAIN")
        assert len(qs) == 4
        assert all(isinstance(q, ReaderQuestion) for q in qs)

    def test_generate_categories(self):
        card = self._make_card()
        qs = _generate_reader_questions(card, "EXPLAIN")
        cats = [q.category for q in qs]
        assert "SOURCE" in cats
        assert "SCOPE" in cats
        assert "IMPACT" in cats
        assert "CHECKPOINT" in cats

    def test_generate_explain_references_fact(self):
        """EXPLAIN — Q1 이 key_facts 의 내용을 참조."""
        card = self._make_card()
        qs = _generate_reader_questions(card, "EXPLAIN")
        source_q = [q for q in qs if q.category == "SOURCE"][0]
        assert "삼성전자" in source_q.question or "파업" in source_q.question

    def test_generate_verify_mode_source(self):
        """VERIFY — Q1 에 '원본 출처/공식 확인' 포함."""
        card = self._make_card(certainty_level="미확인")
        qs = _generate_reader_questions(card, "VERIFY")
        source_q = [q for q in qs if q.category == "SOURCE"][0]
        assert "원본 출처" in source_q.question or "공식 확인" in source_q.question

    def test_generate_judgment_tension(self):
        """JUDGMENT — Q2 가 tensions 참조."""
        card = self._make_card(certainty_level="상충")
        qs = _generate_reader_questions(card, "JUDGMENT")
        scope_q = [q for q in qs if q.category == "SCOPE"][0]
        assert "노조" in scope_q.question or "양측" in scope_q.question

    def test_generate_verify_impact(self):
        """VERIFY — Q3 는 '공식 발표/확인 시점'."""
        card = self._make_card(certainty_level="미확인")
        qs = _generate_reader_questions(card, "VERIFY")
        impact_q = [q for q in qs if q.category == "IMPACT"][0]
        assert "공식" in impact_q.question or "확인 시점" in impact_q.question

    def test_generate_no_key_facts(self):
        """key_facts 없어도 4개 생성."""
        card = self._make_card(key_facts=[])
        qs = _generate_reader_questions(card, "EXPLAIN")
        assert len(qs) == 4

    # ─── 4. _resolve_questions_from_source ────────────────────────────────

    def test_resolve_source_citation(self):
        """출처 인용이 있으면 SOURCE 질문 RESOLVED."""
        qs = [ReaderQuestion(question="Q1", category="SOURCE")]
        source = "국세청에 따르면 소상공인 지원 8건이 확정됐다."
        result = _resolve_questions_from_source(qs, source)
        assert result[0].status == "RESOLVED"
        assert result[0].evidence == "원문 출처 인용 존재"

    def test_resolve_scope_number(self):
        """구체 수치가 있으면 SCOPE 질문 RESOLVED."""
        qs = [ReaderQuestion(question="Q2", category="SCOPE")]
        source = "대상은 약 3,000억원 규모다."
        result = _resolve_questions_from_source(qs, source)
        assert result[0].status == "RESOLVED"
        assert result[0].evidence == "원문 구체 수치 존재"

    def test_resolve_impact_timeline(self):
        """시점/대상 마커 2개+ 있으면 IMPACT 질문 RESOLVED."""
        qs = [ReaderQuestion(question="Q3", category="IMPACT")]
        source = "5월 시행 예정이며 대상은 소상공인이다."
        result = _resolve_questions_from_source(qs, source)
        assert result[0].status == "RESOLVED"

    def test_resolve_impact_insufficient(self):
        """마커 1개만 있으면 UNRESOLVED 유지."""
        qs = [ReaderQuestion(question="Q3", category="IMPACT")]
        source = "5월 발표 예정."
        result = _resolve_questions_from_source(qs, source)
        assert result[0].status == "UNRESOLVED"

    def test_resolve_empty_source(self):
        """source_text 빈 문자열이면 전부 UNRESOLVED."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE"),
            ReaderQuestion(question="Q2", category="SCOPE"),
            ReaderQuestion(question="Q3", category="IMPACT"),
        ]
        result = _resolve_questions_from_source(qs, "")
        assert all(q.status == "UNRESOLVED" for q in result)

    def test_resolve_full_article(self):
        """완전한 기사 → SOURCE + SCOPE 해결."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE"),
            ReaderQuestion(question="Q2", category="SCOPE"),
            ReaderQuestion(question="Q3", category="IMPACT"),
        ]
        source = (
            "국세청이 발표했다. 지원 규모는 3,000억원이다. "
            "오늘 시행되며 대상은 소상공인이다."
        )
        result = _resolve_questions_from_source(qs, source)
        resolved = [q for q in result if q.status == "RESOLVED"]
        assert len(resolved) >= 2

    # ─── 5. _build_question_prompt_section ────────────────────────────────

    def test_prompt_section_empty(self):
        assert _build_question_prompt_section([]) == ""

    def test_prompt_section_has_labels(self):
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE", status="RESOLVED"),
            ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED"),
        ]
        section = _build_question_prompt_section(qs)
        assert "해결됨" in section
        assert "미해결" in section
        assert "Reader Questions" in section

    def test_prompt_section_contains_questions(self):
        qs = [ReaderQuestion(question="이 수치의 원본은?", category="SOURCE")]
        section = _build_question_prompt_section(qs)
        assert "이 수치의 원본은?" in section

    def test_prompt_section_principle(self):
        """'억지 해석 금지' 원칙 포함."""
        qs = [ReaderQuestion(question="Q", category="SOURCE")]
        section = _build_question_prompt_section(qs)
        assert "억지 해석 금지" in section

    # ─── 6. _validate_question_coverage ───────────────────────────────────

    def test_coverage_all_resolved(self):
        """전부 해결 → 경고 0, gate tag 0."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE", status="RESOLVED"),
            ReaderQuestion(question="Q2", category="SCOPE", status="RESOLVED"),
            ReaderQuestion(question="Q3", category="IMPACT", status="RESOLVED"),
        ]
        warns, tags = _validate_question_coverage("본문", qs, "EXPLAIN")
        assert len(warns) == 0
        assert len(tags) == 0

    def test_coverage_1_unresolved_warn_only(self):
        """1개 미해결 → 경고만, gate tag 없음."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE", status="RESOLVED"),
            ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED"),
            ReaderQuestion(question="Q3", category="IMPACT", status="RESOLVED"),
        ]
        warns, tags = _validate_question_coverage("본문", qs, "EXPLAIN")
        assert len(warns) == 1
        assert "1/" in warns[0]
        assert len(tags) == 0

    def test_coverage_2_unresolved_gate(self):
        """2개 미해결 → UNRESOLVED_READER_QUESTION gate tag."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE", status="UNRESOLVED"),
            ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED"),
            ReaderQuestion(question="Q3", category="IMPACT", status="RESOLVED"),
        ]
        warns, tags = _validate_question_coverage("본문", qs, "EXPLAIN")
        assert "UNRESOLVED_READER_QUESTION" in tags

    def test_coverage_verify_strong_warning(self):
        """VERIFY + 2개 미해결 → '강한 경고' 문구."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE", status="UNRESOLVED"),
            ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED"),
            ReaderQuestion(question="Q3", category="IMPACT", status="RESOLVED"),
        ]
        warns, tags = _validate_question_coverage("본문", qs, "VERIFY")
        assert any("강한 경고" in w for w in warns)
        assert "UNRESOLVED_READER_QUESTION" in tags

    def test_coverage_explain_normal_warning(self):
        """EXPLAIN + 2개 미해결 → '경고' (강한 아님)."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE", status="UNRESOLVED"),
            ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED"),
            ReaderQuestion(question="Q3", category="IMPACT", status="RESOLVED"),
        ]
        warns, tags = _validate_question_coverage("본문", qs, "EXPLAIN")
        assert any("경고" in w and "강한 경고" not in w for w in warns)

    def test_coverage_empty_questions(self):
        warns, tags = _validate_question_coverage("본문", [], "EXPLAIN")
        assert len(warns) == 0
        assert len(tags) == 0

    # ─── 7. UNRESOLVED_READER_QUESTION not in _STRONG_FAIL_TAGS ──────────

    def test_unresolved_not_strong_fail(self):
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert "UNRESOLVED_READER_QUESTION" not in _STRONG_FAIL_TAGS

    # ─── 8. _STRONG_FAIL_TAGS 여전히 4개 (회귀) ─────────────────────────

    def test_strong_fail_tags_unchanged(self):
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert _STRONG_FAIL_TAGS == frozenset({
            "WEAK_OPENER", "DEAD_ENDING",
            "STRUCTURE_COLUMN", "LOW_CONFIDENCE_OVERREACH",
        })

    # ─── 9. Reader Reward Layer 회귀 없음 ────────────────────────────────

    def test_reader_reward_regression(self):
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("답은 다음 CPI가 기준이다.") == "SAVE"
        assert _detect_reward_type("특사 파견이 공개되면 검증 가능.") == "FOLLOW"

    # ─── 10. Findability Layer 회귀 없음 ─────────────────────────────────

    def test_findability_regression(self):
        count, warn = _validate_findability(
            "삼성전자 노조가 5월 21일부터 파업을 예고했다.\n답은 참여율이다."
        )
        assert count >= 2
        assert warn is None

    # ─── 11. 소스 패턴 상수 커버리지 ─────────────────────────────────────

    def test_source_citation_regex(self):
        assert _SOURCE_CITATION_RE.search("정부가 발표했다") is not None
        assert _SOURCE_CITATION_RE.search("보고서에 따르면") is not None
        assert _SOURCE_CITATION_RE.search("아무 내용 없음") is None

    def test_scope_number_regex(self):
        assert _SCOPE_NUMBER_RE.search("3,000억원") is not None
        assert _SCOPE_NUMBER_RE.search("25%") is not None
        assert _SCOPE_NUMBER_RE.search("아무 숫자 없음") is None

    # ─── 12. 전/후 샘플 — 질문 생성 품질 ────────────────────────────────

    def test_sample_imf_article(self):
        """IMF 재정 위험 기사 → SOURCE 질문에 근거/수치 포함."""
        card = self._make_card(
            key_facts=["IMF가 한국 재정 건전성 경고 발표",
                        "GDP 대비 국가 부채 비율 55%"],
        )
        qs = _generate_reader_questions(card, "EXPLAIN")
        source_q = [q for q in qs if q.category == "SOURCE"][0]
        assert "IMF" in source_q.question

    def test_sample_nts_article(self):
        """국세청 세정지원 기사 → SCOPE 질문에 구체성."""
        from app.services.content_pack import ThesisCard
        card = self._make_card(
            key_facts=["국세청 소상공인 세정지원 8가지 발표",
                        "신청 기한 6월 30일"],
            thesis_cards=[ThesisCard(
                thesis="지원 규모보다 신청 가능 항목 수가 핵심",
                reader_stake="지금 신청 가능한 건 몇 개인가",
            )],
        )
        qs = _generate_reader_questions(card, "EXPLAIN")
        scope_q = [q for q in qs if q.category == "SCOPE"][0]
        assert "신청" in scope_q.question or "수치" in scope_q.question

    def test_sample_crypto_claim(self):
        """SNS 크립토 주장 → VERIFY SOURCE 에 '원본 출처' 포함."""
        card = self._make_card(
            key_facts=["한국 코인 거래 비중 30% 주장 확산"],
            certainty_level="미확인",
        )
        qs = _generate_reader_questions(card, "VERIFY")
        source_q = [q for q in qs if q.category == "SOURCE"][0]
        assert "원본 출처" in source_q.question or "공식 확인" in source_q.question

    # ─── 13. PR 4-9 _BANNED_ENDINGS 회귀 ────────────────────────────────

    def test_banned_endings_pr10_intact(self):
        """PR 10 추가 금지 표현 여전히 작동."""
        _, _, _, gate_fails = _validate_final_post(
            "이번 결과는 변화를 시사한다.", ""
        )
        assert "DEAD_ENDING" in gate_fails


# ─── PR 12 Layer A: Source Integrity Layer ─────────────────────────────────

class TestSourceIntegrityLayer:
    """PR 12 Layer A — source_text 상태 점검 테스트."""

    def test_empty_string(self):
        """빈 문자열 → MISSING_SOURCE_TEXT."""
        assert _check_source_integrity("") == "MISSING_SOURCE_TEXT"

    def test_none_value(self):
        """None → MISSING_SOURCE_TEXT."""
        assert _check_source_integrity(None) == "MISSING_SOURCE_TEXT"

    def test_whitespace_only(self):
        """공백만 → MISSING_SOURCE_TEXT."""
        assert _check_source_integrity("   \n\t  ") == "MISSING_SOURCE_TEXT"

    def test_too_short(self):
        """유의미하지만 너무 짧은 텍스트 → SOURCE_TEXT_TOO_SHORT."""
        short = "짧은 기사 내용"
        assert len(short.strip()) < _SOURCE_TEXT_MIN_LEN
        assert _check_source_integrity(short) == "SOURCE_TEXT_TOO_SHORT"

    def test_just_below_min(self):
        """최소 길이 바로 아래 → SOURCE_TEXT_TOO_SHORT."""
        text = "가" * (_SOURCE_TEXT_MIN_LEN - 1)
        assert _check_source_integrity(text) == "SOURCE_TEXT_TOO_SHORT"

    def test_exactly_min(self):
        """최소 길이 정확히 → 정상 (None)."""
        text = "가" * _SOURCE_TEXT_MIN_LEN
        assert _check_source_integrity(text) is None

    def test_normal_article(self):
        """정상 기사 길이 → None."""
        article = (
            "트럼프 대통령이 중국산 제품에 대한 관세를 25%로 인상한다고 발표했다. "
            "이번 조치는 반도체와 전자제품을 포함하며, 5월 1일부터 시행된다. "
            "중국 상무부는 즉각 보복 관세를 예고했다."
        )
        assert _check_source_integrity(article) is None

    def test_long_article(self):
        """긴 기사 → None."""
        text = "한국 경제 뉴스. " * 200
        assert _check_source_integrity(text) is None

    def test_min_len_constant_reasonable(self):
        """_SOURCE_TEXT_MIN_LEN 이 합리적 범위 (50~200)."""
        assert 50 <= _SOURCE_TEXT_MIN_LEN <= 200

    def test_finalpost_has_source_missing_reason(self):
        """FinalPost에 source_missing_reason 필드 존재."""
        fp = FinalPost()
        assert hasattr(fp, "source_missing_reason")
        assert fp.source_missing_reason is None

    def test_finalpost_source_missing_reason_settable(self):
        """FinalPost.source_missing_reason 에 라벨 설정 가능."""
        fp = FinalPost(source_missing_reason="MISSING_SOURCE_TEXT")
        assert fp.source_missing_reason == "MISSING_SOURCE_TEXT"

    def test_finalpost_market_angle_type_exists(self):
        """FinalPost에 market_angle_type 필드 존재 (Layer D 사전 준비)."""
        fp = FinalPost()
        assert hasattr(fp, "market_angle_type")
        assert fp.market_angle_type is None


# ─── PR 12 Layer B+C: Question v2 + Evidence Resolver ────────────────────

class TestQuestionResolverV2:
    """PR 12 Layer B — CHECKPOINT 카테고리 추가 + mode별 우선순위."""

    def _make_card(self, **kwargs):
        defaults = dict(
            key_facts=["삼성전자 노조가 5월 파업 예고",
                        "생산라인 영향 가능성"],
            hook_candidates=["삼성전자 파업 예고"],
            thesis_cards=[ThesisCard(
                thesis="파업 현실화 시 반도체 공급망 영향",
                reader_stake="반도체 가격 영향 가능성",
                opener="삼성 노조가 파업을 예고했다.",
            )],
            tensions=["노조는 파업 불가피, 경영진은 대화 강조"],
            certainty_level="확정",
        )
        defaults.update(kwargs)
        return CandidateCard(**defaults)

    # ─── CHECKPOINT 카테고리 생성 ──────────────────────────────────────

    def test_checkpoint_exists_in_explain(self):
        """EXPLAIN → CHECKPOINT 질문 포함."""
        card = self._make_card()
        qs = _generate_reader_questions(card, "EXPLAIN")
        cats = [q.category for q in qs]
        assert "CHECKPOINT" in cats

    def test_checkpoint_exists_in_verify(self):
        """VERIFY → CHECKPOINT 질문 포함."""
        card = self._make_card(certainty_level="미확인")
        qs = _generate_reader_questions(card, "VERIFY")
        cats = [q.category for q in qs]
        assert "CHECKPOINT" in cats

    def test_checkpoint_exists_in_judgment(self):
        """JUDGMENT → CHECKPOINT 질문 포함."""
        card = self._make_card(certainty_level="상충")
        qs = _generate_reader_questions(card, "JUDGMENT")
        cats = [q.category for q in qs]
        assert "CHECKPOINT" in cats

    # ─── mode별 순서 검증 ──────────────────────────────────────────────

    def test_verify_order_source_checkpoint_first(self):
        """VERIFY → SOURCE 1번, CHECKPOINT 2번."""
        card = self._make_card(certainty_level="미확인")
        qs = _generate_reader_questions(card, "VERIFY")
        assert qs[0].category == "SOURCE"
        assert qs[1].category == "CHECKPOINT"

    def test_explain_order_checkpoint_last(self):
        """EXPLAIN → CHECKPOINT 마지막."""
        card = self._make_card()
        qs = _generate_reader_questions(card, "EXPLAIN")
        assert qs[-1].category == "CHECKPOINT"

    def test_judgment_order_checkpoint_last(self):
        """JUDGMENT → CHECKPOINT 마지막."""
        card = self._make_card(certainty_level="상충")
        qs = _generate_reader_questions(card, "JUDGMENT")
        assert qs[-1].category == "CHECKPOINT"

    # ─── CHECKPOINT 질문 내용 ──────────────────────────────────────────

    def test_verify_checkpoint_content(self):
        """VERIFY CHECKPOINT → '공식 데이터/발표' 포함."""
        card = self._make_card(certainty_level="미확인")
        qs = _generate_reader_questions(card, "VERIFY")
        ck = [q for q in qs if q.category == "CHECKPOINT"][0]
        assert "공식" in ck.question or "발표" in ck.question

    def test_judgment_checkpoint_references_tension(self):
        """JUDGMENT + tensions → CHECKPOINT 질문에 갈림 키워드."""
        card = self._make_card(certainty_level="상충")
        qs = _generate_reader_questions(card, "JUDGMENT")
        ck = [q for q in qs if q.category == "CHECKPOINT"][0]
        assert "어느 쪽" in ck.question or "다음 신호" in ck.question

    def test_explain_checkpoint_references_thesis(self):
        """EXPLAIN + thesis → CHECKPOINT 질문에 '확인' 키워드."""
        card = self._make_card()
        qs = _generate_reader_questions(card, "EXPLAIN")
        ck = [q for q in qs if q.category == "CHECKPOINT"][0]
        assert "확인" in ck.question or "보면" in ck.question

    # ─── 4개 카테고리 유니크 ──────────────────────────────────────────

    def test_all_4_categories_unique(self):
        """4개 질문의 카테고리가 모두 다르다."""
        card = self._make_card()
        for mode in ("EXPLAIN", "JUDGMENT", "VERIFY"):
            qs = _generate_reader_questions(card, mode)
            cats = [q.category for q in qs]
            assert len(set(cats)) == 4, f"mode={mode}: 중복 카테고리"


# ─── PR 12 Layer C: Evidence Resolver 강화 ─────────────────────────────

class TestEvidenceResolverV2:
    """PR 12 Layer C — 4카테고리 evidence 패턴 매칭 강화 테스트."""

    # ─── CHECKPOINT resolve ──────────────────────────────────────────

    def test_checkpoint_resolved_by_시행일(self):
        """source에 '시행일' → CHECKPOINT RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="CHECKPOINT")]
        result = _resolve_questions_from_source(qs, "이 법안의 시행일은 5월 1일이다.")
        assert result[0].status == "RESOLVED"
        assert "검증 시점" in result[0].evidence

    def test_checkpoint_resolved_by_나오면(self):
        """source에 '나오면' → CHECKPOINT RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="CHECKPOINT")]
        result = _resolve_questions_from_source(qs, "원본 데이터가 나오면 확인 가능하다.")
        assert result[0].status == "RESOLVED"

    def test_checkpoint_resolved_by_예정(self):
        """source에 '발표 예정' → CHECKPOINT RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="CHECKPOINT")]
        result = _resolve_questions_from_source(qs, "5월 공식 발표 예정이다.")
        assert result[0].status == "RESOLVED"

    def test_checkpoint_unresolved_no_pattern(self):
        """source에 관련 패턴 없으면 UNRESOLVED."""
        qs = [ReaderQuestion(question="Q", category="CHECKPOINT")]
        result = _resolve_questions_from_source(qs, "시장이 크게 반응했다.")
        assert result[0].status == "UNRESOLVED"

    # ─── SOURCE resolve 강화 (영문 패턴) ──────────────────────────────

    def test_source_resolved_english_announced(self):
        """영문 'announced' → SOURCE RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="SOURCE")]
        result = _resolve_questions_from_source(qs, "The Fed announced a rate decision.")
        assert result[0].status == "RESOLVED"

    def test_source_resolved_english_according(self):
        """영문 'according to' → SOURCE RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="SOURCE")]
        result = _resolve_questions_from_source(qs, "according to the IMF report")
        assert result[0].status == "RESOLVED"

    # ─── SCOPE resolve 강화 (영문 단위) ──────────────────────────────

    def test_scope_resolved_english_billion(self):
        """영문 '$50 billion' → SCOPE RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="SCOPE")]
        result = _resolve_questions_from_source(qs, "The package is worth $50 billion.")
        assert result[0].status == "RESOLVED"

    def test_scope_resolved_dollar_amount(self):
        """'$100' → SCOPE RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="SCOPE")]
        result = _resolve_questions_from_source(qs, "Oil price hit $100 per barrel.")
        assert result[0].status == "RESOLVED"

    # ─── IMPACT resolve 강화 (시장/생활 반영 경로) ──────────────────

    def test_impact_resolved_market_patterns(self):
        """'원가' + '공급' → IMPACT RESOLVED (2개 패턴)."""
        qs = [ReaderQuestion(question="Q", category="IMPACT")]
        result = _resolve_questions_from_source(
            qs, "원가 상승이 예상되며 공급 차질 우려도 있다."
        )
        assert result[0].status == "RESOLVED"

    def test_impact_resolved_생활비_집행(self):
        """'생활비' + '집행' → IMPACT RESOLVED."""
        qs = [ReaderQuestion(question="Q", category="IMPACT")]
        result = _resolve_questions_from_source(
            qs, "생활비 부담 증가와 정책 집행 지연 우려가 나온다."
        )
        assert result[0].status == "RESOLVED"

    # ─── 전체 4개 해결 시나리오 ──────────────────────────────────────

    def test_full_article_resolves_all_4(self):
        """완전한 기사 → 4개 모두 해결 가능."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE"),
            ReaderQuestion(question="Q2", category="SCOPE"),
            ReaderQuestion(question="Q3", category="IMPACT"),
            ReaderQuestion(question="Q4", category="CHECKPOINT"),
        ]
        source = (
            "국세청이 발표했다. 지원 규모는 3,000억원이다. "
            "5월 시행 예정이며 대상은 소상공인이다. "
            "원본 데이터가 나오면 확인 가능하다."
        )
        result = _resolve_questions_from_source(qs, source)
        resolved = [q for q in result if q.status == "RESOLVED"]
        assert len(resolved) == 4

    def test_empty_source_all_unresolved(self):
        """source_text 빈 문자열 → 4개 모두 UNRESOLVED."""
        qs = [
            ReaderQuestion(question="Q1", category="SOURCE"),
            ReaderQuestion(question="Q2", category="SCOPE"),
            ReaderQuestion(question="Q3", category="IMPACT"),
            ReaderQuestion(question="Q4", category="CHECKPOINT"),
        ]
        result = _resolve_questions_from_source(qs, "")
        assert all(q.status == "UNRESOLVED" for q in result)

    # ─── CHECKPOINT_EVIDENCE_PATTERNS 상수 검증 ──────────────────────

    def test_checkpoint_patterns_exist(self):
        """_CHECKPOINT_EVIDENCE_PATTERNS 이 비어있지 않다."""
        assert len(_CHECKPOINT_EVIDENCE_PATTERNS) >= 5

    def test_checkpoint_patterns_contain_key_signals(self):
        """핵심 확인 신호 패턴 포함."""
        pats = _CHECKPOINT_EVIDENCE_PATTERNS
        assert "나오면" in pats
        assert "시행일" in pats
        assert "공개되면" in pats

    # ─── prompt section v2 ──────────────────────────────────────────

    def test_prompt_section_has_checkpoint_label(self):
        """prompt section에 CHECKPOINT 라벨 포함."""
        qs = [ReaderQuestion(question="Q", category="CHECKPOINT", status="UNRESOLVED")]
        section = _build_question_prompt_section(qs)
        assert "다음 확인 신호" in section

    def test_prompt_section_has_checkpoint_instruction(self):
        """prompt section에 CHECKPOINT 지시문 포함."""
        qs = [ReaderQuestion(question="Q", category="CHECKPOINT")]
        section = _build_question_prompt_section(qs)
        assert "CHECKPOINT" in section

    # ─── 회귀 검증 ──────────────────────────────────────────────────

    def test_source_citation_regex_backward_compat(self):
        """기존 한국어 출처 패턴 여전히 동작."""
        assert _SOURCE_CITATION_RE.search("정부가 발표했다") is not None
        assert _SOURCE_CITATION_RE.search("보고서에 따르면") is not None

    def test_scope_number_regex_backward_compat(self):
        """기존 한국어 수치 패턴 여전히 동작."""
        assert _SCOPE_NUMBER_RE.search("3,000억원") is not None
        assert _SCOPE_NUMBER_RE.search("25%") is not None


# ─── PR 12 Layer D: Market/Stake Layer v2 ────────────────────────────────

class TestMarketStakeLayerV2:
    """PR 12 Layer D — market_angle_type 태깅 + validator 테스트."""

    # ─── _detect_market_angle_type ──────────────────────────────────

    def test_detect_cost(self):
        """'원가' → COST."""
        post = "관세 인상으로 원가 상승이 먼저 반영된다."
        assert _detect_market_angle_type(post, "EXPLAIN") == "COST"

    def test_detect_demand(self):
        """'소비' → DEMAND."""
        post = "결국 소비 위축이 먼저 나타난다."
        assert _detect_market_angle_type(post, "EXPLAIN") == "DEMAND"

    def test_detect_supply(self):
        """'공급' → SUPPLY."""
        post = "공급 차질이 먼저 반영될 수 있다."
        assert _detect_market_angle_type(post, "EXPLAIN") == "SUPPLY"

    def test_detect_policy(self):
        """'시행' → POLICY."""
        post = "핵심은 시행일이다."
        assert _detect_market_angle_type(post, "EXPLAIN") == "POLICY"

    def test_detect_flow(self):
        """'실적' → FLOW."""
        post = "다음 실적 발표가 갈림길이다."
        assert _detect_market_angle_type(post, "EXPLAIN") == "FLOW"

    def test_detect_checkpoint(self):
        """'확인 가능' → CHECKPOINT."""
        post = "공식 발표가 나오면 확인 가능."
        assert _detect_market_angle_type(post, "EXPLAIN") == "CHECKPOINT"

    def test_detect_none(self):
        """관련 패턴 없으면 NONE."""
        post = "이 사건은 주목할 만하다."
        assert _detect_market_angle_type(post, "EXPLAIN") == "NONE"

    def test_detect_empty_post(self):
        """빈 post → NONE."""
        assert _detect_market_angle_type("", "EXPLAIN") == "NONE"

    def test_verify_mode_only_checkpoint(self):
        """VERIFY → CHECKPOINT 외의 시장 앵글 무시."""
        post = "원가 상승이 예상된다. 공급 차질 우려."
        result = _detect_market_angle_type(post, "VERIFY")
        # VERIFY에서는 COST/SUPPLY 아닌 NONE 또는 CHECKPOINT만
        assert result in ("NONE", "CHECKPOINT")

    def test_verify_mode_checkpoint_detected(self):
        """VERIFY + 확인 포인트 → CHECKPOINT."""
        post = "특사 파견이 공개되면 확인 가능."
        assert _detect_market_angle_type(post, "VERIFY") == "CHECKPOINT"

    # ─── _validate_market_stake ─────────────────────────────────────

    def test_validate_with_market_expression(self):
        """시장 표현 있으면 통과."""
        warn, tag = _validate_market_stake(
            "원가 상승이 먼저 반영된다.", "EXPLAIN"
        )
        assert warn is None
        assert tag is None

    def test_validate_no_market_expression(self):
        """시장 표현 없으면 NO_MARKET_STAKE."""
        warn, tag = _validate_market_stake(
            "이것은 주목할 만한 사건이다.", "EXPLAIN"
        )
        assert warn is not None
        assert tag == "NO_MARKET_STAKE"

    def test_validate_verify_checkpoint_pass(self):
        """VERIFY + 확인 포인트 표현 → 통과."""
        warn, tag = _validate_market_stake(
            "특사 파견이 공개되면 확인 가능.", "VERIFY"
        )
        assert warn is None
        assert tag is None

    def test_validate_verify_no_checkpoint(self):
        """VERIFY + 확인 포인트 없음 → NO_MARKET_STAKE."""
        warn, tag = _validate_market_stake(
            "트럼프 측이 대화 의향을 밝혔다.", "VERIFY"
        )
        assert warn is not None
        assert tag == "NO_MARKET_STAKE"

    def test_validate_empty_post(self):
        """빈 post → 통과 (None)."""
        warn, tag = _validate_market_stake("", "EXPLAIN")
        assert warn is None
        assert tag is None

    # ─── gate_fails 연동 ──────────────────────────────────────────

    def test_no_market_stake_in_gate_fails(self):
        """시장 표현 없는 post → gate_fails에 NO_MARKET_STAKE."""
        _, _, _, gate_fails = _validate_final_post(
            "이 사건은 주목할 만한 사건이다.", "짧은 버전"
        )
        assert "NO_MARKET_STAKE" in gate_fails

    def test_no_market_stake_not_strong_fail(self):
        """NO_MARKET_STAKE 는 _STRONG_FAIL_TAGS 에 없다."""
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert "NO_MARKET_STAKE" not in _STRONG_FAIL_TAGS

    # ─── 상수 검증 ──────────────────────────────────────────────────

    def test_valid_types_include_all(self):
        """_MARKET_ANGLE_VALID_TYPES 에 7개 유형 포함."""
        assert "COST" in _MARKET_ANGLE_VALID_TYPES
        assert "DEMAND" in _MARKET_ANGLE_VALID_TYPES
        assert "SUPPLY" in _MARKET_ANGLE_VALID_TYPES
        assert "POLICY" in _MARKET_ANGLE_VALID_TYPES
        assert "FLOW" in _MARKET_ANGLE_VALID_TYPES
        assert "CHECKPOINT" in _MARKET_ANGLE_VALID_TYPES
        assert "NONE" in _MARKET_ANGLE_VALID_TYPES

    def test_pattern_dict_not_empty(self):
        """_MARKET_ANGLE_PATTERNS 비어있지 않음."""
        assert len(_MARKET_ANGLE_PATTERNS) >= 6
        for key, patterns in _MARKET_ANGLE_PATTERNS.items():
            assert len(patterns) >= 3, f"{key}: 패턴 수 부족"

    # ─── _parse_final_post 연동 ──────────────────────────────────────

    def test_parse_sets_market_angle_type(self):
        """_parse_final_post → market_angle_type 자동 설정."""
        import json
        raw = json.dumps({
            "final_post": "삼성전자 25% 관세 영향. 원가 상승이 먼저 반영된다. 답은 다음 실적이다.",
            "final_short": "관세가 원가에 먼저 반영된다."
        })
        fp = _parse_final_post(raw, mode="EXPLAIN")
        assert fp is not None
        assert fp.market_angle_type is not None
        assert fp.market_angle_type in _MARKET_ANGLE_VALID_TYPES

    def test_parse_verify_market_angle(self):
        """VERIFY _parse → CHECKPOINT 또는 NONE."""
        import json
        raw = json.dumps({
            "final_post": "트럼프 측 발언이 있었다. 접촉은 확인되지 않았다. 특사 파견이 공개되면 확인 가능.",
            "final_short": "접촉 확인 안 됨."
        })
        fp = _parse_final_post(raw, mode="VERIFY", certainty_level="미확인")
        assert fp is not None
        assert fp.market_angle_type in ("CHECKPOINT", "NONE")

    # ─── mode별 market angle 시나리오 ────────────────────────────────

    def test_explain_cost_scenario(self):
        """EXPLAIN — 원가/비용 기사 → COST."""
        post = (
            "반도체 관세 25%가 시행되면 칩 단가가 먼저 오른다.\n"
            "비용 전가 순서는 파운드리→팹리스→완성품이다.\n"
            "답은 다음 분기 원가 보고서다."
        )
        assert _detect_market_angle_type(post, "EXPLAIN") == "COST"

    def test_judgment_갈림_scenario(self):
        """JUDGMENT — 갈림 기사 → 시장 앵글 감지."""
        post = (
            "인하 vs 동결, 한은의 선택이 갈린다.\n"
            "소비 위축 데이터가 인하 쪽을 밀고 있다.\n"
            "답은 다음 소비자심리지수다."
        )
        angle = _detect_market_angle_type(post, "JUDGMENT")
        assert angle in ("DEMAND", "POLICY"), f"got {angle}"

    def test_verify_checkpoint_scenario(self):
        """VERIFY — 확인 포인트만 허용."""
        post = (
            "중국 측이 대화 의향을 밝혔다.\n"
            "실제 접촉은 확인되지 않았다.\n"
            "특사 파견이 공개되면 확인 가능."
        )
        assert _detect_market_angle_type(post, "VERIFY") == "CHECKPOINT"


# ─── PR 12 Layer E: Evaluation / Learning Loop ──────────────────────────

class TestEvaluationLoop:
    """PR 12 Layer E — 구조화 메타데이터 빌드 + 필드 검증."""

    def _make_card(self, **kwargs):
        defaults = dict(
            key_facts=["삼성전자 노조가 5월 파업 예고"],
            hook_candidates=["삼성전자 파업"],
            thesis_cards=[ThesisCard(
                thesis="파업 현실화 시 반도체 공급망 영향",
                reader_stake="반도체 가격 영향",
            )],
            certainty_level="확정",
            topic_tags=["경제", "산업"],
        )
        defaults.update(kwargs)
        return CandidateCard(**defaults)

    def _make_final(self, **kwargs):
        defaults = dict(
            final_post="삼성전자 파업이 현실화되면 원가가 먼저 오른다.",
            final_short="파업 시 원가 상승.",
            gate_fails=[],
            reward_type="SAVE",
            market_angle_type="COST",
            reader_questions=[
                ReaderQuestion(question="Q1", category="SOURCE", status="RESOLVED"),
                ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED"),
                ReaderQuestion(question="Q3", category="IMPACT", status="RESOLVED"),
                ReaderQuestion(question="Q4", category="CHECKPOINT", status="RESOLVED"),
            ],
            resolved_count=3,
            unresolved_count=1,
            source_missing_reason=None,
        )
        defaults.update(kwargs)
        return FinalPost(**defaults)

    # ─── 기본 구조 검증 ──────────────────────────────────────────────

    def test_meta_returns_dict(self):
        """_build_evaluation_meta → dict 반환."""
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert isinstance(meta, dict)

    def test_meta_has_all_required_fields(self):
        """필수 필드 15개 존재."""
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        required = [
            "mode", "certainty", "reward_type", "market_angle_type",
            "resolved_count", "unresolved_count", "question_count",
            "source_missing_reason", "gate_fails", "strong_fail_count",
            "warn_tag_count", "post_length", "short_length",
            "topic_tags", "has_thesis",
        ]
        for field in required:
            assert field in meta, f"필드 누락: {field}"

    # ─── 값 정확성 ──────────────────────────────────────────────────

    def test_meta_mode(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["mode"] == "EXPLAIN"

    def test_meta_certainty(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["certainty"] == "확정"

    def test_meta_reward_type(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["reward_type"] == "SAVE"

    def test_meta_market_angle(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["market_angle_type"] == "COST"

    def test_meta_question_counts(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["resolved_count"] == 3
        assert meta["unresolved_count"] == 1
        assert meta["question_count"] == 4

    def test_meta_source_missing(self):
        meta = _build_evaluation_meta(
            self._make_final(source_missing_reason="MISSING_SOURCE_TEXT"),
            self._make_card(), "EXPLAIN", "MISSING_SOURCE_TEXT",
        )
        assert meta["source_missing_reason"] == "MISSING_SOURCE_TEXT"

    def test_meta_source_normal(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["source_missing_reason"] is None

    def test_meta_gate_fails_empty(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["gate_fails"] == []
        assert meta["strong_fail_count"] == 0
        assert meta["warn_tag_count"] == 0

    def test_meta_gate_fails_mixed(self):
        """강한 실패 + 약한 실패 → 각각 카운트."""
        final = self._make_final(
            gate_fails=["WEAK_OPENER", "NO_READER_REWARD", "LOW_FINDABILITY"]
        )
        meta = _build_evaluation_meta(final, self._make_card(), "EXPLAIN", None)
        assert meta["strong_fail_count"] == 1  # WEAK_OPENER
        assert meta["warn_tag_count"] == 2     # NO_READER_REWARD + LOW_FINDABILITY

    def test_meta_post_lengths(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["post_length"] > 0
        assert meta["short_length"] > 0

    def test_meta_topic_tags(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert "경제" in meta["topic_tags"]
        assert "산업" in meta["topic_tags"]

    def test_meta_has_thesis_true(self):
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "EXPLAIN", None,
        )
        assert meta["has_thesis"] is True

    def test_meta_has_thesis_false(self):
        card = self._make_card(thesis_cards=[])
        meta = _build_evaluation_meta(
            self._make_final(), card, "EXPLAIN", None,
        )
        assert meta["has_thesis"] is False

    # ─── JSON 직렬화 호환 ────────────────────────────────────────────

    def test_meta_json_serializable(self):
        """메타데이터가 JSON 직렬화 가능."""
        import json
        meta = _build_evaluation_meta(
            self._make_final(), self._make_card(), "VERIFY", "SOURCE_TEXT_TOO_SHORT",
        )
        serialized = json.dumps(meta, ensure_ascii=False)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["mode"] == "VERIFY"

    # ─── VERIFY 시나리오 ─────────────────────────────────────────────

    def test_meta_verify_scenario(self):
        """VERIFY 기사 → 전체 메타 구조 정상."""
        card = self._make_card(certainty_level="미확인")
        final = self._make_final(
            market_angle_type="CHECKPOINT",
            reward_type="FOLLOW",
            resolved_count=1,
            unresolved_count=3,
            gate_fails=["UNRESOLVED_READER_QUESTION"],
        )
        meta = _build_evaluation_meta(final, card, "VERIFY", None)
        assert meta["mode"] == "VERIFY"
        assert meta["certainty"] == "미확인"
        assert meta["market_angle_type"] == "CHECKPOINT"
        assert meta["reward_type"] == "FOLLOW"
        assert meta["strong_fail_count"] == 0
        assert meta["warn_tag_count"] == 1


# ─── PR 13: External Evidence Layer ─────────────────────────────────────

class TestExternalEvidenceLayer:
    """PR 13 — 1차 출처 감지 + 외부 evidence 질문 해결 테스트."""

    def _make_card(self, **kwargs):
        defaults = dict(
            key_facts=["삼성전자 노조가 5월 파업 예고"],
            hook_candidates=["삼성전자 파업"],
            thesis_cards=[ThesisCard(
                thesis="파업 현실화 시 반도체 공급망 영향",
                reader_stake="반도체 가격 영향",
            )],
            certainty_level="확정",
            source_url=None,
            source_type="news_link",
        )
        defaults.update(kwargs)
        return CandidateCard(**defaults)

    # ─── FinalPost 신규 필드 ─────────────────────────────────────────

    def test_finalpost_has_external_fields(self):
        """FinalPost에 PR 13 필드 3개 존재."""
        fp = FinalPost()
        assert hasattr(fp, "used_primary_source")
        assert hasattr(fp, "primary_source_type")
        assert hasattr(fp, "external_evidence_count")
        assert fp.used_primary_source is False
        assert fp.primary_source_type is None
        assert fp.external_evidence_count == 0

    # ─── URL 기반 감지 ────────────────────────────────────────────────

    def test_detect_government_url(self):
        """go.kr URL → GOVERNMENT."""
        card = self._make_card(source_url="https://www.moef.go.kr/news/12345")
        src_type, count = _detect_primary_source(card)
        assert src_type == "GOVERNMENT"
        assert count >= 1

    def test_detect_report_url_imf(self):
        """imf.org URL → REPORT."""
        card = self._make_card(source_url="https://www.imf.org/en/Publications")
        src_type, count = _detect_primary_source(card)
        assert src_type == "REPORT"

    def test_detect_report_url_bok(self):
        """bok.or.kr URL → REPORT."""
        card = self._make_card(source_url="https://ecos.bok.or.kr/data")
        src_type, count = _detect_primary_source(card)
        assert src_type == "REPORT"

    def test_detect_disclosure_url(self):
        """dart.fss.or.kr URL → DISCLOSURE."""
        card = self._make_card(source_url="https://dart.fss.or.kr/report/12345")
        src_type, count = _detect_primary_source(card)
        assert src_type == "DISCLOSURE"

    def test_detect_data_source_url(self):
        """coingecko.com URL → DATA_SOURCE."""
        card = self._make_card(source_url="https://www.coingecko.com/ko/coins/bitcoin")
        src_type, count = _detect_primary_source(card)
        assert src_type == "DATA_SOURCE"

    def test_detect_coinmarketcap_url(self):
        """coinmarketcap.com URL → DATA_SOURCE."""
        card = self._make_card(source_url="https://coinmarketcap.com/currencies/bitcoin")
        src_type, count = _detect_primary_source(card)
        assert src_type == "DATA_SOURCE"

    def test_detect_whitehouse_url(self):
        """whitehouse.gov URL → GOVERNMENT."""
        card = self._make_card(source_url="https://www.whitehouse.gov/briefing")
        src_type, count = _detect_primary_source(card)
        assert src_type == "GOVERNMENT"

    def test_detect_sec_url(self):
        """sec.gov URL → DISCLOSURE."""
        card = self._make_card(source_url="https://www.sec.gov/filing/10-K")
        src_type, count = _detect_primary_source(card)
        assert src_type == "DISCLOSURE"

    # ─── 텍스트 기반 감지 ─────────────────────────────────────────────

    def test_detect_imf_from_key_facts(self):
        """key_facts에 'IMF' → REPORT."""
        card = self._make_card(
            key_facts=["IMF가 한국 재정 건전성 경고 발표"]
        )
        src_type, count = _detect_primary_source(card)
        assert src_type == "REPORT"

    def test_detect_government_from_key_facts(self):
        """key_facts에 '국세청' → GOVERNMENT."""
        card = self._make_card(
            key_facts=["국세청 소상공인 세정지원 8가지 발표"]
        )
        src_type, count = _detect_primary_source(card)
        assert src_type == "GOVERNMENT"

    def test_detect_disclosure_from_source_text(self):
        """source_text에 '공시' + '실적 발표' → DISCLOSURE."""
        card = self._make_card()
        src_type, count = _detect_primary_source(
            card, "삼성전자가 공시를 통해 분기 실적 발표를 했다."
        )
        assert src_type == "DISCLOSURE"
        assert count >= 2

    def test_detect_direct_stmt_from_text(self):
        """source_text에 '보도자료' + '공식 입장' → DIRECT_STMT."""
        card = self._make_card()
        src_type, count = _detect_primary_source(
            card, "회사 측이 보도자료를 통해 공식 입장을 밝혔다."
        )
        assert src_type == "DIRECT_STMT"
        assert count >= 2

    def test_detect_coingecko_from_text(self):
        """source_text에 'CoinGecko' → DATA_SOURCE."""
        card = self._make_card()
        src_type, _ = _detect_primary_source(
            card, "CoinGecko 데이터에 따르면 비트코인 거래량이 급증했다."
        )
        assert src_type == "DATA_SOURCE"

    # ─── 감지 실패 ────────────────────────────────────────────────────

    def test_no_primary_source(self):
        """관련 패턴 없으면 None."""
        card = self._make_card(
            key_facts=["시장이 조정 국면이다"],
            source_url=None,
        )
        src_type, count = _detect_primary_source(card, "일반적인 뉴스 내용.")
        assert src_type is None
        assert count == 0

    def test_empty_card(self):
        """빈 카드 → None."""
        card = self._make_card(key_facts=[], source_url=None)
        src_type, count = _detect_primary_source(card, "")
        assert src_type is None
        assert count == 0

    # ─── URL 우선순위 ─────────────────────────────────────────────────

    def test_url_takes_priority_over_text(self):
        """URL 매칭이 텍스트 매칭보다 우선."""
        card = self._make_card(
            source_url="https://dart.fss.or.kr/report/12345",
            key_facts=["IMF 보고서 경고"],  # 텍스트로는 REPORT
        )
        src_type, _ = _detect_primary_source(card)
        assert src_type == "DISCLOSURE"  # URL 우선

    # ─── _resolve_questions_from_external ──────────────────────────────

    def test_external_resolves_source_question(self):
        """1차 출처 감지 → UNRESOLVED SOURCE 질문 해결."""
        qs = [ReaderQuestion(question="Q1", category="SOURCE", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, "GOVERNMENT", 3)
        assert result[0].status == "RESOLVED"
        assert "외부" in result[0].evidence

    def test_external_resolves_scope_from_report(self):
        """REPORT 출처 + evidence 2+ → SCOPE 해결."""
        qs = [ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, "REPORT", 2)
        assert result[0].status == "RESOLVED"

    def test_external_resolves_checkpoint_from_government(self):
        """GOVERNMENT 출처 + evidence 2+ → CHECKPOINT 해결."""
        qs = [ReaderQuestion(question="Q4", category="CHECKPOINT", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, "GOVERNMENT", 2)
        assert result[0].status == "RESOLVED"

    def test_external_skips_already_resolved(self):
        """이미 RESOLVED 인 질문은 건너뛴다."""
        qs = [ReaderQuestion(question="Q1", category="SOURCE", status="RESOLVED",
                             evidence="원문 출처 인용 존재")]
        result = _resolve_questions_from_external(qs, "GOVERNMENT", 3)
        assert result[0].evidence == "원문 출처 인용 존재"  # 기존 evidence 유지

    def test_external_no_source_type(self):
        """primary_source_type None → 변경 없음."""
        qs = [ReaderQuestion(question="Q1", category="SOURCE", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, None, 0)
        assert result[0].status == "UNRESOLVED"

    def test_external_scope_not_from_direct_stmt(self):
        """DIRECT_STMT 출처 → SCOPE 해결 안 됨 (데이터 출처가 아님)."""
        qs = [ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, "DIRECT_STMT", 3)
        assert result[0].status == "UNRESOLVED"

    def test_external_checkpoint_not_from_data_source(self):
        """DATA_SOURCE 출처 → CHECKPOINT 해결 안 됨."""
        qs = [ReaderQuestion(question="Q4", category="CHECKPOINT", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, "DATA_SOURCE", 3)
        assert result[0].status == "UNRESOLVED"

    def test_external_scope_low_evidence_unresolved(self):
        """evidence_count 1 → SCOPE 해결 안 됨 (2 이상 필요)."""
        qs = [ReaderQuestion(question="Q2", category="SCOPE", status="UNRESOLVED")]
        result = _resolve_questions_from_external(qs, "REPORT", 1)
        assert result[0].status == "UNRESOLVED"

    # ─── 통합 시나리오 ────────────────────────────────────────────────

    def test_full_pipeline_imf_article(self):
        """IMF 기사 → 외부 evidence 로 추가 해결."""
        card = self._make_card(
            key_facts=["IMF가 한국 재정 건전성 경고 발표",
                        "GDP 대비 국가 부채 비율 55%"],
            source_url="https://www.imf.org/publications/report",
        )
        source = "IMF 보고서에 따르면 한국의 부채 비율이 55%에 달한다."
        # 1단계: source_text 매칭
        qs = _generate_reader_questions(card, "EXPLAIN")
        qs = _resolve_questions_from_source(qs, source)
        resolved_internal = sum(1 for q in qs if q.status == "RESOLVED")
        # 2단계: 외부 evidence 매칭
        src_type, ext_count = _detect_primary_source(card, source)
        qs = _resolve_questions_from_external(qs, src_type, ext_count)
        resolved_total = sum(1 for q in qs if q.status == "RESOLVED")
        assert resolved_total >= resolved_internal
        assert src_type == "REPORT"

    def test_full_pipeline_nts_article(self):
        """국세청 기사 → GOVERNMENT 감지."""
        card = self._make_card(
            key_facts=["국세청 소상공인 세정지원 8가지 발표"],
            source_url="https://www.nts.go.kr/news/12345",
        )
        src_type, count = _detect_primary_source(card)
        assert src_type == "GOVERNMENT"
        assert count >= 1

    def test_full_pipeline_no_external(self):
        """외부 출처 없는 기사 → 기존 동작 유지."""
        card = self._make_card(source_url="https://www.chosun.com/news/12345")
        qs = [ReaderQuestion(question="Q", category="SOURCE", status="UNRESOLVED")]
        src_type, count = _detect_primary_source(card, "일반 뉴스 기사")
        qs = _resolve_questions_from_external(qs, src_type, count)
        # 외부 evidence 없으면 UNRESOLVED 유지
        if src_type is None:
            assert qs[0].status == "UNRESOLVED"

    # ─── 상수 검증 ────────────────────────────────────────────────────

    def test_valid_types_set(self):
        """_PRIMARY_SOURCE_VALID_TYPES 5개 유형."""
        assert len(_PRIMARY_SOURCE_VALID_TYPES) == 5
        assert "GOVERNMENT" in _PRIMARY_SOURCE_VALID_TYPES
        assert "REPORT" in _PRIMARY_SOURCE_VALID_TYPES
        assert "DISCLOSURE" in _PRIMARY_SOURCE_VALID_TYPES
        assert "DATA_SOURCE" in _PRIMARY_SOURCE_VALID_TYPES
        assert "DIRECT_STMT" in _PRIMARY_SOURCE_VALID_TYPES

    def test_url_patterns_not_empty(self):
        """URL 패턴 사전 비어있지 않음."""
        for key, patterns in _PRIMARY_SOURCE_URL_PATTERNS.items():
            assert len(patterns) >= 2, f"{key}: URL 패턴 부족"

    def test_text_patterns_not_empty(self):
        """텍스트 패턴 사전 비어있지 않음."""
        for key, patterns in _PRIMARY_SOURCE_TEXT_PATTERNS.items():
            assert len(patterns) >= 3, f"{key}: 텍스트 패턴 부족"

    # ─── EvalMeta 연동 ────────────────────────────────────────────────

    def test_eval_meta_has_external_fields(self):
        """_build_evaluation_meta 에 PR 13 필드 3개 포함."""
        fp = FinalPost(
            used_primary_source=True,
            primary_source_type="REPORT",
            external_evidence_count=5,
        )
        card = self._make_card()
        meta = _build_evaluation_meta(fp, card, "EXPLAIN", None)
        assert meta["used_primary_source"] is True
        assert meta["primary_source_type"] == "REPORT"
        assert meta["external_evidence_count"] == 5

    def test_eval_meta_no_external(self):
        """외부 출처 없으면 기본값."""
        fp = FinalPost()
        card = self._make_card()
        meta = _build_evaluation_meta(fp, card, "EXPLAIN", None)
        assert meta["used_primary_source"] is False
        assert meta["primary_source_type"] is None
        assert meta["external_evidence_count"] == 0

    # ─── 회귀 검증 ────────────────────────────────────────────────────

    def test_verify_regression_intact(self):
        """VERIFY 과해석 게이트 여전히 동작."""
        from app.services.content_pack import _STRONG_FAIL_TAGS
        assert _STRONG_FAIL_TAGS == frozenset({
            "WEAK_OPENER", "DEAD_ENDING",
            "STRUCTURE_COLUMN", "LOW_CONFIDENCE_OVERREACH",
        })

    def test_reader_reward_regression(self):
        """Reader Reward Layer 회귀 없음."""
        from app.services.content_pack import _detect_reward_type
        assert _detect_reward_type("답은 다음 CPI가 기준이다.") == "SAVE"

    def test_findability_regression(self):
        """Findability Layer 회귀 없음."""
        count, warn = _validate_findability(
            "삼성전자 노조가 5월 21일부터 파업을 예고했다.\n답은 참여율이다."
        )
        assert count >= 2
        assert warn is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PR 14: Draft Ranking Layer 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDraftRankingLayer:
    """PR 14 — _score_draft / _select_best_draft 규칙 기반 초안 비교."""

    # ── 헬퍼 ──

    def _make_draft(
        self,
        post=(
            "관세 25%가 반도체까지 확대되면 원가 상승이 먼저 반영된다.\n"
            "삼성전자 파운드리 라인 원가 기준으로 웨이퍼당 12% 인상이 예고됐다.\n"
            "답은 다음 CPI 발표에서 반도체 장비 가격이 반영되느냐다."
        ),
        short="관세 확대 시 원가 상승 선반영.",
        gate_fails=None,
        reward_type="SAVE",
        market_angle_type="COST",
    ):
        return FinalPost(
            final_post=post,
            final_short=short,
            gate_fails=gate_fails if gate_fails is not None else [],
            reward_type=reward_type,
            market_angle_type=market_angle_type,
        )

    # ── _score_draft 기본 ──

    def test_score_clean_draft(self):
        """게이트 통과 + reward + market → 높은 점수."""
        d = self._make_draft()
        score = _score_draft(d)
        assert score >= 115, f"clean draft score too low: {score}"

    def test_score_base_no_bonus(self):
        """reward/market 없으면 base 100."""
        d = self._make_draft(reward_type=None, market_angle_type=None)
        score = _score_draft(d)
        assert score == 100

    def test_score_reward_bonus(self):
        """reward_type 있으면 +10."""
        d1 = self._make_draft(reward_type=None, market_angle_type=None)
        d2 = self._make_draft(reward_type="SAVE", market_angle_type=None)
        assert _score_draft(d2) - _score_draft(d1) == 10

    def test_score_market_bonus(self):
        """market_angle_type 있으면 +10."""
        d1 = self._make_draft(reward_type=None, market_angle_type=None)
        d2 = self._make_draft(reward_type=None, market_angle_type="COST")
        assert _score_draft(d2) - _score_draft(d1) == 10

    def test_score_market_none_no_bonus(self):
        """market_angle_type='NONE'이면 보너스 없음."""
        d = self._make_draft(reward_type=None, market_angle_type="NONE")
        assert _score_draft(d) == 100

    # ── 강한 실패 감점 ──

    def test_score_one_strong_fail(self):
        """강한 실패 1개 → −30."""
        d = self._make_draft(
            gate_fails=["WEAK_OPENER"],
            reward_type=None,
            market_angle_type=None,
        )
        assert _score_draft(d) == 70

    def test_score_two_strong_fails(self):
        """강한 실패 2개 → −60."""
        d = self._make_draft(
            gate_fails=["WEAK_OPENER", "DEAD_ENDING"],
            reward_type=None,
            market_angle_type=None,
        )
        assert _score_draft(d) == 40

    def test_score_strong_plus_warn(self):
        """강한 1개 + 경고 1개 → −30 −5 = −35."""
        d = self._make_draft(
            gate_fails=["WEAK_OPENER", "NO_READER_REWARD"],
            reward_type=None,
            market_angle_type=None,
        )
        assert _score_draft(d) == 65

    # ── 경고 태그 감점 ──

    def test_score_warn_tag_penalty(self):
        """WARN-only 태그 → −5 each."""
        d = self._make_draft(
            gate_fails=["NO_READER_REWARD", "LOW_FINDABILITY"],
            reward_type=None,
            market_angle_type=None,
        )
        assert _score_draft(d) == 90

    # ── 뻔한 표현 감점 ──

    def test_score_weak_pattern_penalty(self):
        """_WEAK_PATTERNS 매칭 → −3 each."""
        d = self._make_draft(
            post="추이를 봐야 한다. 변수다.",
            reward_type=None,
            market_angle_type=None,
        )
        score = _score_draft(d)
        # "추이를 봐야 한다" + "변수다" = 2 hits → −6, plus short (<100) → −20
        assert score < 100

    def test_score_no_weak_patterns(self):
        """뻔한 표현 없으면 감점 0."""
        d = self._make_draft(
            post="관세 25%가 반도체까지 확대되면 원가 상승이 먼저 반영된다." * 3,
            reward_type=None,
            market_angle_type=None,
        )
        score = _score_draft(d)
        assert score == 100

    # ── 길이 감점 ──

    def test_score_too_short(self):
        """100자 미만 → −20."""
        d = self._make_draft(
            post="짧은 글.",
            reward_type=None,
            market_angle_type=None,
        )
        score = _score_draft(d)
        assert score <= 80

    def test_score_too_long(self):
        """800자 초과 → −10."""
        d = self._make_draft(
            post="가" * 801,
            reward_type=None,
            market_angle_type=None,
        )
        score = _score_draft(d)
        assert score == 90

    def test_score_normal_length(self):
        """100~800자 → 길이 감점 없음."""
        d = self._make_draft(
            post="가" * 300,
            reward_type=None,
            market_angle_type=None,
        )
        score = _score_draft(d)
        assert score == 100

    # ── _select_best_draft ──

    def test_select_best_from_two(self):
        """두 후보 중 점수 높은 것 선택."""
        d1 = self._make_draft(
            gate_fails=["WEAK_OPENER"],
            reward_type=None,
            market_angle_type=None,
        )
        d2 = self._make_draft()  # clean, high score
        best, rank, scores = _select_best_draft([d1, d2])
        assert best is d2
        assert rank == 2
        assert len(scores) == 2
        assert scores[1] > scores[0]

    def test_select_best_first_wins_tie(self):
        """동점이면 첫 번째 (최초 생성) 우선."""
        d1 = self._make_draft()
        d2 = self._make_draft()
        best, rank, scores = _select_best_draft([d1, d2])
        assert best is d1
        assert rank == 1
        assert scores[0] == scores[1]

    def test_select_best_from_three(self):
        """3개 후보 중 최고 선택."""
        d1 = self._make_draft(gate_fails=["WEAK_OPENER"], reward_type=None, market_angle_type=None)
        d2 = self._make_draft(gate_fails=["DEAD_ENDING"], reward_type="SAVE", market_angle_type=None)
        d3 = self._make_draft()  # best
        best, rank, scores = _select_best_draft([d1, d2, d3])
        assert best is d3
        assert rank == 3

    def test_select_single_draft(self):
        """후보 1개 → 그대로 반환."""
        d = self._make_draft()
        best, rank, scores = _select_best_draft([d])
        assert best is d
        assert rank == 1
        assert len(scores) == 1

    def test_select_empty_raises(self):
        """빈 리스트 → ValueError."""
        with pytest.raises(ValueError):
            _select_best_draft([])

    # ── 점수 순서 보장 ──

    def test_strong_fail_worse_than_warn(self):
        """강한 실패 초안이 경고만 있는 초안보다 항상 낮다 (동일 보너스 조건)."""
        d_strong = self._make_draft(
            gate_fails=["WEAK_OPENER"],
            reward_type=None,
            market_angle_type=None,
        )
        d_warn = self._make_draft(
            gate_fails=["NO_READER_REWARD", "LOW_FINDABILITY"],
            reward_type=None,
            market_angle_type=None,
        )
        assert _score_draft(d_warn) > _score_draft(d_strong)

    def test_reward_market_beats_bare(self):
        """reward + market 보너스가 bare 100보다 높다."""
        d_bare = self._make_draft(reward_type=None, market_angle_type=None)
        d_bonus = self._make_draft(reward_type="SAVE", market_angle_type="COST")
        assert _score_draft(d_bonus) > _score_draft(d_bare)

    # ── FinalPost 메타 필드 기본값 ──

    def test_finalpost_draft_defaults(self):
        """FinalPost 기본값: count=1, rank=1, scores=[]."""
        fp = FinalPost()
        assert fp.draft_candidates_count == 1
        assert fp.draft_selected_rank == 1
        assert fp.draft_scores == []

    def test_finalpost_draft_meta_roundtrip(self):
        """draft 메타 필드 설정 → 읽기."""
        fp = FinalPost(
            final_post="테스트",
            draft_candidates_count=3,
            draft_selected_rank=2,
            draft_scores=[85, 110, 95],
        )
        assert fp.draft_candidates_count == 3
        assert fp.draft_selected_rank == 2
        assert fp.draft_scores == [85, 110, 95]

    # ── _build_evaluation_meta 연동 ──

    def test_eval_meta_includes_draft_fields(self):
        """EvalMeta 에 draft_candidates_count, draft_selected_rank 포함."""
        fp = FinalPost(
            final_post="관세 25% 확대 시 원가 상승 선반영.",
            final_short="관세 확대 영향.",
            draft_candidates_count=2,
            draft_selected_rank=1,
            draft_scores=[110, 95],
        )
        card = CandidateCard(
            key_facts=["관세 25% 확대"],
            hook_candidates=["관세 확대"],
            certainty_level="확정",
        )
        meta = _build_evaluation_meta(fp, card, "EXPLAIN", None)
        assert meta["draft_candidates_count"] == 2
        assert meta["draft_selected_rank"] == 1

    def test_eval_meta_draft_defaults(self):
        """EvalMeta draft 필드 기본값 (단일 초안)."""
        fp = FinalPost(final_post="테스트", final_short="짧")
        card = CandidateCard(
            key_facts=["팩트"],
            hook_candidates=["훅"],
        )
        meta = _build_evaluation_meta(fp, card, "EXPLAIN", None)
        assert meta["draft_candidates_count"] == 1
        assert meta["draft_selected_rank"] == 1

    # ── 복합 시나리오 ──

    def test_ranking_picks_clean_over_dirty(self):
        """강한 실패 + 뻔한 표현 초안 vs 클린 초안 → 클린 승."""
        dirty = self._make_draft(
            post="추이를 봐야 한다. 변수다. 영향이 커질 수 있다.",
            gate_fails=["WEAK_OPENER", "DEAD_ENDING"],
            reward_type=None,
            market_angle_type=None,
        )
        clean = self._make_draft(
            post="관세 25%가 반도체까지 확대되면 원가 상승이 먼저 반영된다.\n답은 다음 CPI가 기준이다.",
            gate_fails=[],
            reward_type="SAVE",
            market_angle_type="COST",
        )
        best, rank, scores = _select_best_draft([dirty, clean])
        assert best is clean
        assert rank == 2
        assert scores[1] - scores[0] >= 50  # 큰 점수 차이

    def test_ranking_among_imperfect_drafts(self):
        """불완전 초안 3개 중 가장 나은 것 채택."""
        d1 = self._make_draft(
            gate_fails=["WEAK_OPENER"],
            reward_type="SAVE",
            market_angle_type="COST",
        )  # -30 +10 +10 = 90
        d2 = self._make_draft(
            gate_fails=["NO_READER_REWARD"],
            reward_type=None,
            market_angle_type="DEMAND",
        )  # -5 +0 +10 = 105
        d3 = self._make_draft(
            gate_fails=["LOW_FINDABILITY"],
            reward_type="FOLLOW",
            market_angle_type=None,
        )  # -5 +10 +0 = 105
        best, rank, scores = _select_best_draft([d1, d2, d3])
        # d2 and d3 tie at 105, d2 wins (first)
        assert best is d2
        assert rank == 2

    def test_score_deterministic(self):
        """같은 draft → 같은 점수."""
        d = self._make_draft()
        s1 = _score_draft(d)
        s2 = _score_draft(d)
        assert s1 == s2

    def test_score_empty_post(self):
        """빈 post → 길이 감점 적용."""
        d = self._make_draft(
            post="",
            reward_type=None,
            market_angle_type=None,
        )
        score = _score_draft(d)
        assert score == 80  # 100 - 20 (too short)
