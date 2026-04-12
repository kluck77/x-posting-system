"""
콘텐츠 팩 언어 기본값 테스트
============================
한국어 기본 / 영어 명시 시만 영어 규칙을 검증합니다.
"""

from app.services.content_pack import (
    _get_system_prompt, _mock_pack,
    FactSheet, ContentPack, extract_fact_sheet, check_density, TOPIC_MIN_FIELDS,
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
        assert "낡은 수치 단정 금지" in prompt
        assert "데이터 없는 단정 금지" in prompt
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
        """낡은 수치 단정 금지 규칙이 골든 룰에 있다."""
        prompt = _get_system_prompt("ko")
        assert "현재 시점과 어긋나는 수치는 신뢰를 깎는다" in prompt

    def test_ko_prompt_data_backed_assertion_rule(self):
        """데이터 없는 단정 금지 규칙이 골든 룰에 있다."""
        prompt = _get_system_prompt("ko")
        assert "데이터 없는 단정 금지" in prompt
        assert "지역/대상" in prompt
        assert "기간/비교 시점" in prompt
        assert "수치/변화폭" in prompt
        assert "톤을 낮춰라" in prompt

    def test_ko_prompt_has_generation_steps(self):
        """3단계 생성 절차가 프롬프트에 존재한다."""
        prompt = _get_system_prompt("ko")
        assert "STEP 1" in prompt
        assert "STEP 2" in prompt
        assert "STEP 3" in prompt
        assert "입력 데이터 점검" in prompt
        assert "핵심축 3개 선택" in prompt

    def test_ko_prompt_has_qa_checklist(self):
        """최종 QA 체크리스트 10항목이 프롬프트에 존재한다."""
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
