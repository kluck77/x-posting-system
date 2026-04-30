"""Info Value Gate v1 — 6 scenario tests.

heuristic only (no AI calls). 평가 결과 dict 의 score / action_label /
forbidden_claims / korean_context 등을 검증.
"""
from __future__ import annotations

from app.services.info_value_gate import (
    evaluate_info_value,
    format_info_value_block,
    ACTION_PUBLISH,
    ACTION_VERIFY_MORE,
    ACTION_COMMENT_ONLY,
    ACTION_RESEARCH_REQUIRED,
    ACTION_DROP,
    LEVEL_HIGH,
    LEVEL_MEDIUM,
    LEVEL_LOW,
)


class TestThinQueryGuard:
    def test_short_topic_only_query_triggers_research_required(self):
        # source_type=manual + 짧은 본문 + url 없음 → RESEARCH_REQUIRED
        out = evaluate_info_value(
            title="휴리스틱 5가지 원리",
            source_text="휴리스틱 5가지 원리에 대해 알려줘",
            source_url=None,
            source_type="manual",
            research_summary="",
            factcheck_summary="",
        )
        assert out["action_label"] == ACTION_RESEARCH_REQUIRED, (
            "thin query 는 강제 RESEARCH_REQUIRED 분기되어야 함"
        )
        assert out["score"] < 50, "thin query 는 score < 50"
        assert out["thin_query"] is True
        # forbidden 에 단정 표현 금지 포함
        forbidden_text = " ".join(out["forbidden_claims"])
        assert "단정" in forbidden_text or "추정" in forbidden_text or "인용" in forbidden_text


class TestStrongSourcedNews:
    def test_news_link_with_specific_facts_scores_high(self):
        # 구체 숫자 + 날짜 + factcheck 검증됨 → PUBLISH or VERIFY_MORE
        out = evaluate_info_value(
            title="UAE OPEC+ 탈퇴 발표 — 2026년 5월 1일 효력",
            source_text=(
                "UAE 정부는 2026년 5월 1일부터 OPEC+ 탈퇴 효력 개시를 발표했다. "
                "사우디 영향력 축소 및 일일 산유량 350만 배럴 변동 예상. "
                "2025년 11월 28일 OPEC 본부 성명 발표. "
                "Brent 유가 12.5% 상승, S&P 500 에너지 섹터 8.2% 변동."
            ),
            source_url="https://www.news1.kr/world/usa-canada/6152007",
            source_type="news_link",
            research_summary="UAE 가 2026 년 5 월 OPEC+ 탈퇴를 공식 발표.",
            factcheck_summary="✅ 검증됨 (신뢰도: high)",
        )
        assert out["action_label"] in (ACTION_PUBLISH, ACTION_VERIFY_MORE), (
            f"strong sourced news 는 PUBLISH/VERIFY_MORE 권장, got={out['action_label']}"
        )
        assert out["score"] >= 70
        assert out["info_rarity"] in (LEVEL_HIGH, LEVEL_MEDIUM)
        assert out["trust_level"] in (LEVEL_HIGH, LEVEL_MEDIUM)


class TestPolymarketRiskFlag:
    def test_polymarket_topic_flags_betting_forbidden(self):
        out = evaluate_info_value(
            title="Polymarket 2026 대선 베팅 비율 분석",
            source_text=(
                "Polymarket 의 2026 대선 odds 가 65% 로 변동. "
                "prediction market 참가자 12만명 돌파."
            ),
            source_url="https://polymarket.com/event/2026-election",
            source_type="news_link",
            research_summary="Polymarket 베팅 odds 데이터.",
            factcheck_summary="✅ 검증됨 (신뢰도: medium)",
        )
        assert out["risk_level"] in (LEVEL_MEDIUM, LEVEL_HIGH), (
            f"Polymarket 은 risk medium+ 이어야 함, got={out['risk_level']}"
        )
        # 베팅 권유 금지 forbidden_claims 에 포함
        forbidden_text = " ".join(out["forbidden_claims"])
        assert "베팅" in forbidden_text or "도박" in forbidden_text, (
            "Polymarket 은 베팅 / 도박 금지 forbidden_claims 필수"
        )
        # PUBLISH 차단 (risk high → 최소 VERIFY_MORE)
        if out["risk_level"] == LEVEL_HIGH:
            assert out["action_label"] != ACTION_PUBLISH


class TestLongButLowValue:
    def test_long_text_without_concrete_facts_not_publish(self):
        # 긴 본문이지만 구체 사실 / 숫자 / 날짜 부재 → not PUBLISH
        out = evaluate_info_value(
            title="동기부여에 대한 일반론",
            source_text=(
                "동기부여란 무엇인가에 대한 긴 에세이. " * 30
            ),
            source_url=None,
            source_type="manual",
            research_summary="",
            factcheck_summary="⚠️ 미검증 (신뢰도: low)",
        )
        assert out["action_label"] != ACTION_PUBLISH, (
            "구체 사실 없는 긴 일반론은 PUBLISH 금지"
        )


class TestHighRiskFinance:
    def test_finance_recommendation_flags_risk(self):
        out = evaluate_info_value(
            title="삼성전자 매수 추천 — 목표주가 95000원",
            source_text=(
                "삼성전자 매수 추천. 목표주가 95000 원. "
                "수익 보장 30% 예상. 2026 년 4 월 시점."
            ),
            source_url="https://example.com/stock",
            source_type="news_link",
            research_summary="삼성전자 주가 분석.",
            factcheck_summary="⚠️ 미검증 (신뢰도: low)",
        )
        assert out["risk_level"] in (LEVEL_MEDIUM, LEVEL_HIGH), (
            "매수 추천 / 목표주가 / 수익보장 → 위험 medium+"
        )
        assert out["action_label"] in (
            ACTION_VERIFY_MORE, ACTION_COMMENT_ONLY,
            ACTION_RESEARCH_REQUIRED, ACTION_DROP,
        ), "고위험 금융 권유는 PUBLISH 금지"
        forbidden_text = " ".join(out["forbidden_claims"])
        assert "매수" in forbidden_text or "수익" in forbidden_text


class TestKoreanContextRecommendation:
    def test_global_topic_disallows_korean_context(self):
        # OPEC / FOMC 등 글로벌 토픽 → 한국 맥락 금지
        out = evaluate_info_value(
            title="OPEC+ 산유량 결정",
            source_text=(
                "OPEC+ 회담에서 일일 산유량 200만 배럴 감산 결정. "
                "Brent 유가 변동. Federal Reserve 금리 영향 분석."
            ),
            source_url="https://example.com/opec",
            source_type="news_link",
            research_summary="OPEC+ 감산 결정.",
            factcheck_summary="✅ 검증됨 (신뢰도: medium)",
        )
        assert out.get("korean_context_allowed") is False, (
            "글로벌 토픽 (OPEC) 은 한국 맥락 금지여야 함"
        )

    def test_explicit_korean_topic_allows_korean_context(self):
        # 명시 한국 키워드 → 한국 맥락 허용
        out = evaluate_info_value(
            title="한국은행 기준금리 0.25%p 인상",
            source_text=(
                "한국은행이 2026 년 4 월 기준금리를 0.25%p 인상. "
                "코스피 -1.2% 하락. 원화 약세 전환."
            ),
            source_url="https://example.com/bok",
            source_type="news_link",
            research_summary="한국은행 금리 인상.",
            factcheck_summary="✅ 검증됨 (신뢰도: high)",
        )
        assert out.get("korean_context_allowed") is True, (
            "명시 한국 키워드 (한국은행/코스피/원화) 는 한국 맥락 허용"
        )


class TestFormatBlockHTML:
    def test_format_block_returns_safe_html(self):
        out = evaluate_info_value(
            title="테스트",
            source_text="테스트",
            source_url=None,
            source_type="manual",
        )
        block = format_info_value_block(out)
        assert "<b>" in block and "</b>" in block
        # 4-6 줄 (3 줄 minimum + 선택 forbidden 줄)
        line_count = block.count("\n") + 1
        assert 3 <= line_count <= 6


class TestFailOpen:
    def test_invalid_input_returns_safe_default(self):
        # title=None / source_text=None 도 예외 없이 분기
        out = evaluate_info_value(
            title="",
            source_text="",
            source_url=None,
            source_type="unknown_type",
            research_summary="",
            factcheck_summary="",
        )
        assert "score" in out
        assert "action_label" in out
        # 빈 입력 → 거의 확실히 PUBLISH 아님
        assert out["action_label"] != ACTION_PUBLISH
