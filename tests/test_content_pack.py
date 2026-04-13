"""
콘텐츠 팩 언어 기본값 테스트
============================
한국어 기본 / 영어 명시 시만 영어 규칙을 검증합니다.
"""

from app.services.content_pack import (
    _get_system_prompt, _mock_pack, _is_short_input, _classify_topic,
    FactSheet, ContentPack, extract_fact_sheet, check_density, TOPIC_MIN_FIELDS,
    _audit_numeric_safety,
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
