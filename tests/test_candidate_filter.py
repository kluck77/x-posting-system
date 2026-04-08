"""
후보 선별 필터 테스트 (Phase A)
================================
heuristic-only candidate_filter 의 단위 테스트.
파이프라인(orchestrator) 연결과는 독립적이다.
"""

import json
import pytest

from app.models.content import CandidateStatus, SourceItem
from app.services.candidate_filter import (
    BUCKET_10,
    BUCKET_20,
    BUCKET_25,
    CUTLINE_HOLD_MIN,
    CUTLINE_PASS,
    CUTLINE_REJECT_MAX,
    L1_BLACKLIST_KEYWORDS,
    SCORE_MAX_TOTAL,
    apply_result_to_source,
    classify_by_cutline,
    evaluate_candidate,
    evaluate_source_item,
    run_heuristic_score,
    run_l1_filter,
)


# =============================================================================
# 상수 / 버킷 확인
# =============================================================================

class TestConstants:
    def test_cutlines_exact_values(self):
        assert CUTLINE_PASS == 60
        assert CUTLINE_HOLD_MIN == 45
        assert CUTLINE_REJECT_MAX == 44

    def test_cutlines_are_contiguous(self):
        # 45~59 hold, 60 이상 pass, 44 이하 reject
        assert CUTLINE_REJECT_MAX + 1 == CUTLINE_HOLD_MIN
        assert CUTLINE_HOLD_MIN < CUTLINE_PASS

    def test_max_total_is_85(self):
        assert SCORE_MAX_TOTAL == 85

    def test_buckets_5_levels(self):
        assert BUCKET_25 == (0, 6, 13, 19, 25)
        assert BUCKET_20 == (0, 5, 10, 15, 20)
        assert BUCKET_10 == (0, 3, 5, 8, 10)

    def test_bucket_sum_equals_max_total(self):
        assert BUCKET_25[-1] + BUCKET_20[-1] + BUCKET_20[-1] + BUCKET_10[-1] + BUCKET_10[-1] == 85


# =============================================================================
# L1 필터
# =============================================================================

class TestL1Filter:
    def test_clean_text_passes_l1(self):
        assert run_l1_filter("한국 반도체 수출", "삼성과 SK하이닉스가 미국으로 반도체를 수출") is None

    def test_entertainment_blocked(self):
        assert run_l1_filter("연예 뉴스", "오늘의 연예인 소식") is not None

    def test_idol_blocked(self):
        assert run_l1_filter("아이돌 컴백", "새 아이돌 그룹이 데뷔") is not None

    def test_actor_blocked(self):
        assert run_l1_filter("배우 인터뷰", "한국 배우가 헐리웃 진출") is not None

    def test_festival_blocked(self):
        assert run_l1_filter("부산 축제 개막", "이번 주말 지역 축제가 열린다") is not None

    def test_weather_blocked(self):
        assert run_l1_filter("날씨 속보", "내일 전국에 한파가 예상된다") is not None

    def test_fire_blocked(self):
        assert run_l1_filter("서울 화재", "오늘 새벽 대형 화재가 발생") is not None

    def test_homicide_blocked(self):
        assert run_l1_filter("살인 사건", "용의자를 체포했다") is not None

    def test_accident_blocked(self):
        assert run_l1_filter("교통 사고", "사고로 3명이 부상") is not None

    def test_domestic_politics_detail_blocked(self):
        assert run_l1_filter("여야 공방 격화", "국회에서 여야 공방이 이어졌다") is not None

    def test_l1_blacklist_is_small_enough(self):
        # 스펙상 Phase A 는 최소 범위 유지. 과도하게 늘리지 않음.
        assert len(L1_BLACKLIST_KEYWORDS) < 60


# =============================================================================
# 컷라인 분류
# =============================================================================

class TestClassifyByCutline:
    def test_60_is_passed(self):
        assert classify_by_cutline(60) == CandidateStatus.PASSED

    def test_85_is_passed(self):
        assert classify_by_cutline(85) == CandidateStatus.PASSED

    def test_59_is_hold(self):
        assert classify_by_cutline(59) == CandidateStatus.HOLD

    def test_45_is_hold(self):
        assert classify_by_cutline(45) == CandidateStatus.HOLD

    def test_44_is_rejected_score(self):
        assert classify_by_cutline(44) == CandidateStatus.REJECTED_SCORE

    def test_0_is_rejected_score(self):
        assert classify_by_cutline(0) == CandidateStatus.REJECTED_SCORE


# =============================================================================
# heuristic 점수
# =============================================================================

class TestHeuristicScore:
    def test_empty_text_scores_zero(self):
        total, breakdown = run_heuristic_score("", "")
        assert total == 0
        assert breakdown["total"] == 0
        assert breakdown["max_total"] == 85
        for axis in (
            "global_linkage",
            "korea_specificity",
            "foreign_reader_interest",
            "explanation_value",
            "series_repeat_value",
        ):
            assert breakdown[axis]["score"] == 0

    def test_score_has_all_five_axes(self):
        _, breakdown = run_heuristic_score("test", "test")
        assert "global_linkage" in breakdown
        assert "korea_specificity" in breakdown
        assert "foreign_reader_interest" in breakdown
        assert "explanation_value" in breakdown
        assert "series_repeat_value" in breakdown

    def test_high_score_example(self):
        # 글로벌 맥락 + 한국 특수성 + 해외독자 관심 + 설명가치 + 시리즈 모두 자극
        title = "Korea semiconductor export to China and US amid AI chip demand"
        text = (
            "Samsung and SK hynix face tariff pressure from global trade. "
            "Korea's chaebol structure and demographic crisis shape policy reform. "
            "This is a structural analysis of why Korea matters for semiconductor supply."
        )
        total, breakdown = run_heuristic_score(title, text)
        assert total >= CUTLINE_PASS, f"expected passed, got {total}, breakdown={breakdown}"

    def test_low_score_example(self):
        total, _ = run_heuristic_score("random blurb", "nothing interesting here")
        assert total <= CUTLINE_REJECT_MAX


# =============================================================================
# evaluate_candidate (통합 경로)
# =============================================================================

class TestEvaluateCandidate:
    def test_l1_rejection_has_score_zero(self):
        result = evaluate_candidate(
            title="연예인 루머",
            source_text="오늘의 연예 뉴스",
        )
        assert result.status == CandidateStatus.REJECTED_L1
        assert result.score == 0
        assert "l1_hit" in result.breakdown

    def test_passed_path(self):
        result = evaluate_candidate(
            title="Korea semiconductor policy reform for global chip supply",
            source_text=(
                "Samsung and SK hynix navigate US tariffs and China export rules. "
                "Korea's chaebol system, demographic decline, and AI chip demand "
                "shape the structural analysis of why the government proposes new policy reform. "
                "This is a long-running semiconductor series story."
            ),
        )
        assert result.status == CandidateStatus.PASSED, result.breakdown
        assert result.score >= CUTLINE_PASS

    def test_rejected_score_path(self):
        result = evaluate_candidate(
            title="generic daily post",
            source_text="nothing in particular",
        )
        assert result.status == CandidateStatus.REJECTED_SCORE
        assert result.score <= CUTLINE_REJECT_MAX

    def test_breakdown_is_json_serializable(self):
        result = evaluate_candidate("test", "test")
        text = result.breakdown_json()
        parsed = json.loads(text)
        assert parsed["total"] == result.score


# =============================================================================
# SourceItem 반영
# =============================================================================

class TestEvaluateSourceItem:
    def test_apply_result_writes_three_columns(self, db_session):
        item = SourceItem(
            title="연예 뉴스",
            url=None,
            source_text="연예인 스캔들",
            source_type="manual",
            language="ko",
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        result = evaluate_source_item(item)
        apply_result_to_source(item, result)
        db_session.commit()
        db_session.refresh(item)

        assert item.candidate_status == CandidateStatus.REJECTED_L1
        assert item.candidate_score == 0
        assert item.candidate_score_breakdown is not None
        parsed = json.loads(item.candidate_score_breakdown)
        assert parsed["total"] == 0
        assert "l1_hit" in parsed


# =============================================================================
# Grok 미연결 확인 (AST 기반 — 주석/docstring 은 제외)
# =============================================================================

class TestNoGrokInPhaseA:
    def test_candidate_filter_ast_has_no_grok_symbol(self):
        """
        스펙 11. 금지: Grok provider 연결 금지.
        docstring/주석은 제외하고, AST 수준의 식별자/import 만 검사한다.
        """
        import ast
        import app.services.candidate_filter as cf

        with open(cf.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        grok_hits: list[str] = []

        for node in ast.walk(tree):
            # import grok / import ... as grok
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "grok" in (alias.name or "").lower():
                        grok_hits.append(f"import {alias.name}")
                    if alias.asname and "grok" in alias.asname.lower():
                        grok_hits.append(f"import as {alias.asname}")
            # from grok import ...
            elif isinstance(node, ast.ImportFrom):
                if node.module and "grok" in node.module.lower():
                    grok_hits.append(f"from {node.module}")
            # 식별자
            elif isinstance(node, ast.Name):
                if "grok" in node.id.lower():
                    grok_hits.append(f"name {node.id}")
            elif isinstance(node, ast.Attribute):
                if "grok" in node.attr.lower():
                    grok_hits.append(f"attr {node.attr}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if "grok" in node.name.lower():
                    grok_hits.append(f"def {node.name}")

        assert not grok_hits, f"Phase A 는 AST 수준 Grok 0건이어야 한다: {grok_hits}"
