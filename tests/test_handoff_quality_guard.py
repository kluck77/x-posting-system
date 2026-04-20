"""
handoff_quality_guard 단위 + 통합 테스트.

Phase 1 spec:
- 정상 source_pack → 빈 warning_block
- heuristic fallback / empty facts / meta-only facts → HIGH
- HIGH 2개 이상 → block_recommended=True + BLOCK_RECOMMENDED 문자열 포함
- MEDIUM 만 → block_recommended=False
- english_residue MEDIUM
- concept_translation 길이 > 150 MEDIUM
- Draft 1388 실제 fixture → 4종 flag 전부 감지
"""
from app.services.handoff_quality_guard import (
    HIGH_FLAG_BLOCK_THRESHOLD,
    detect_angle_pack_heuristic,
    detect_concept_translation_misuse,
    detect_confirmed_facts_empty,
    detect_english_residue,
    render_warning_block,
    run_quality_guard,
)


def _clean_pack():
    return {
        "confirmed_facts": [
            "한국은행은 6월 18일 기준금리를 동결했다.",
            "원유 수입의 70%가 중동에서 온다.",
        ],
        "concept_translation": "호르무즈 해협: 세계 원유 수송의 핵심 관문",
        "core_tension": "중동 변수가 한국 가계에 비대칭 노출",
        "uncertainty_note": "일시적 변동성과 구조적 차질 구분 어려움",
        "angle_pack": {
            "method": "gemini",
            "winner_angle": {"source": "gemini", "angle": "호르무즈 비대칭 노출"},
            "editorial_goal": "중동 변수 → 한국 가계 비대칭",
        },
    }


# ── 1. 정상 입력 ─────────────────────────────────────────────────────

def test_all_clean_returns_empty_warning():
    result = run_quality_guard(_clean_pack())
    assert result["flags"] == []
    assert result["high_count"] == 0
    assert result["medium_count"] == 0
    assert result["block_recommended"] is False
    assert result["rendered_warning_block"] == ""


# ── 2. heuristic fallback ────────────────────────────────────────────

def test_heuristic_fallback_detected_via_editorial_goal():
    p = _clean_pack()
    p["angle_pack"]["editorial_goal"] = "heuristic fallback (no Gemini call)"
    flag = detect_angle_pack_heuristic(p)
    assert flag is not None
    assert flag["flag_id"] == "angle_heuristic"
    assert flag["severity"] == "HIGH"


def test_heuristic_fallback_detected_via_method():
    p = _clean_pack()
    p["angle_pack"]["method"] = "fallback"
    flag = detect_angle_pack_heuristic(p)
    assert flag is not None
    assert flag["flag_id"] == "angle_heuristic"


def test_heuristic_fallback_detected_via_winner_source():
    p = _clean_pack()
    p["angle_pack"]["winner_angle"]["source"] = "heuristic"
    flag = detect_angle_pack_heuristic(p)
    assert flag is not None
    assert flag["severity"] == "HIGH"


# ── 2a. Phase 1.5a: winner_angle.reason 경로 (실 빌더 저장 위치) ───

def test_heuristic_detected_via_winner_angle_reason():
    """angle_pack.winner_angle.reason 에 heuristic 마커 있으면 HIGH flag 반환.

    _heuristic_angle_pack() 빌더가 실제 저장하는 위치 (angle_pack.py:173-177).
    다른 heuristic 단서는 모두 제거하고 reason 필드만으로 감지 확인.
    """
    p = _clean_pack()
    # Gemini 정상 경로 흔적 제거
    p["angle_pack"]["winner_angle"].pop("source", None)
    p["angle_pack"].pop("method", None)
    p["angle_pack"].pop("editorial_goal", None)
    # reason 만 설정
    p["angle_pack"]["winner_angle"]["reason"] = "heuristic fallback (no Gemini call)"
    flag = detect_angle_pack_heuristic(p)
    assert flag is not None
    assert flag["flag_id"] == "angle_heuristic"
    assert flag["severity"] == "HIGH"
    assert "winner_angle.reason" in flag["evidence"]


def test_heuristic_detected_via_winner_angle_reason_case_insensitive():
    """매칭은 대소문자 무시."""
    p = _clean_pack()
    p["angle_pack"]["winner_angle"]["reason"] = "HEURISTIC FALLBACK — manual override"
    flag = detect_angle_pack_heuristic(p)
    assert flag is not None
    assert flag["severity"] == "HIGH"


def test_heuristic_detected_with_real_builder_output():
    """실 _heuristic_angle_pack() 빌더 출력에 대해 감지 함수가 정상 작동.

    향후 빌더 출력 구조가 변경되어도 감지 로직이 실 데이터와 동기화돼
    있는지 지속 검증. fixture 복붙이 아니라 실제 빌더 함수를 호출해서
    그 출력을 source_pack.angle_pack 에 주입한다.
    """
    from app.services.angle_pack import _heuristic_angle_pack
    # 빌더가 비어있는 source_pack 에서도 최소 winner_angle 을 만드는지 확인
    # 실패 케이스 대비 일반적인 conflict 하나 공급.
    source_pack = {
        "confirmed_facts": [],
        "conflicts_or_uncertainty": ["한국은행 금리 경로 불확실"],
        "concept_translation": "",
    }
    built_angle_pack = _heuristic_angle_pack(source_pack)
    # 빌더 출력이 dict 이고 winner_angle.reason 에 fallback 마커가 있어야 함
    assert isinstance(built_angle_pack, dict)
    wa = built_angle_pack.get("winner_angle")
    assert isinstance(wa, dict)
    assert "reason" in wa
    assert "heuristic" in wa["reason"].lower() or "fallback" in wa["reason"].lower(), (
        "빌더 출력이 heuristic 마커를 reason 필드에 넣지 않음 — "
        "_heuristic_angle_pack() 구현이 바뀌었다면 감지 함수도 업데이트 필요"
    )
    # source_pack 에 angle_pack 주입 후 감지 호출
    guard_input = dict(source_pack)
    guard_input["angle_pack"] = built_angle_pack
    flag = detect_angle_pack_heuristic(guard_input)
    assert flag is not None
    assert flag["flag_id"] == "angle_heuristic"
    assert flag["severity"] == "HIGH"


def test_heuristic_detected_via_legacy_paths():
    """기존 경로(method, winner_angle.source, editorial_goal) 만 있어도 감지 유지.

    Phase 1.5a 에서 winner_angle.reason 을 추가했지만 legacy 3개 경로도
    여전히 단독으로 동작해야 한다 (회귀 방지).
    """
    # method 단독
    p = _clean_pack()
    p["angle_pack"]["method"] = "fallback"
    assert detect_angle_pack_heuristic(p) is not None

    # winner_angle.source 단독
    p = _clean_pack()
    p["angle_pack"]["winner_angle"]["source"] = "heuristic"
    assert detect_angle_pack_heuristic(p) is not None

    # editorial_goal 단독
    p = _clean_pack()
    p["angle_pack"]["editorial_goal"] = "heuristic fallback (no Gemini call)"
    assert detect_angle_pack_heuristic(p) is not None


# ── 3. confirmed_facts 비어있음 ──────────────────────────────────────

def test_empty_confirmed_facts_detected():
    p = _clean_pack()
    p["confirmed_facts"] = []
    flag = detect_confirmed_facts_empty(p)
    assert flag is not None
    assert flag["flag_id"] == "facts_empty"
    assert flag["severity"] == "HIGH"


def test_meta_only_confirmed_facts_detected():
    p = _clean_pack()
    p["confirmed_facts"] = [
        "(확정 사실이 공급되지 않음 — 새 숫자/고유명사 추가 금지)",
        "숫자·고유명사·날짜는 초안 그대로 유지",
    ]
    flag = detect_confirmed_facts_empty(p)
    assert flag is not None
    assert flag["severity"] == "HIGH"


def test_single_real_fact_still_below_min():
    p = _clean_pack()
    p["confirmed_facts"] = ["한국은행은 6월 18일 기준금리를 동결했다."]
    flag = detect_confirmed_facts_empty(p)
    # MIN_CONFIRMED_FACTS=2 라 1건도 HIGH
    assert flag is not None


# ── 4. BLOCK_RECOMMENDED 경계 ────────────────────────────────────────

def test_two_high_triggers_block_recommended():
    p = _clean_pack()
    p["angle_pack"]["method"] = "fallback"
    p["confirmed_facts"] = []
    result = run_quality_guard(p)
    assert result["high_count"] >= HIGH_FLAG_BLOCK_THRESHOLD
    assert result["block_recommended"] is True
    assert "**BLOCK_RECOMMENDED**" in result["rendered_warning_block"]


def test_only_medium_no_block_recommended():
    p = _clean_pack()
    # MEDIUM 1개만 (english_residue)
    p["core_tension"] = "Nvidia CEO comment fuels counter-intuitive bridge between chips and crypto"
    result = run_quality_guard(p)
    assert result["high_count"] == 0
    assert result["medium_count"] >= 1
    assert result["block_recommended"] is False
    assert "**BLOCK_RECOMMENDED**" not in result["rendered_warning_block"]


# ── 5. english_residue ───────────────────────────────────────────────

def test_english_residue_detection():
    p = _clean_pack()
    p["core_tension"] = (
        "Nvidia CEO's AI token comment fuels counter-intuitive bridge "
        "between semiconductors and crypto markets, challenging siloed views."
    )
    flag = detect_english_residue(p)
    assert flag is not None
    assert flag["flag_id"] == "english_residue"
    assert flag["severity"] == "MEDIUM"


def test_english_residue_ignores_korean():
    p = _clean_pack()
    p["core_tension"] = "중동 변수 → 한국 가계 비대칭 노출, 구조적 취약성 드러남"
    flag = detect_english_residue(p)
    assert flag is None


# ── 6. concept_translation 오용 ──────────────────────────────────────

def test_concept_translation_length_misuse():
    p = _clean_pack()
    # spec: 정상 30~80자. 임계 150자 초과면 오용.
    p["concept_translation"] = (
        "엔비디아 최고경영자 젠슨 황의 한마디가 암호화폐 시장을 무섭게 달구고 있다. "
        "그는 최근 팟캐스터 드와케시 파텔과의 인터뷰에서 반도체와 암호화폐의 경계를 "
        "허무는 새로운 비즈니스 모델을 제시하며, 시장의 고정관념을 깨고 새로운 "
        "기회를 창출할 수 있는 가능성을 내포하고 있다고 강조했다."
    )
    assert len(p["concept_translation"]) > 150
    flag = detect_concept_translation_misuse(p)
    assert flag is not None
    assert flag["flag_id"] == "concept_translation_misuse"
    assert flag["severity"] == "MEDIUM"


def test_concept_translation_normal_length_passes():
    p = _clean_pack()
    p["concept_translation"] = "호르무즈 해협: 세계 원유 수송 관문"
    flag = detect_concept_translation_misuse(p)
    assert flag is None


# ── 7. render_warning_block 동작 ─────────────────────────────────────

def test_render_empty_when_no_flags():
    assert render_warning_block([], False) == ""


def test_render_orders_high_first_then_alphabetical():
    flags = [
        {"flag_id": "english_residue", "severity": "MEDIUM",
         "description": "영어 잔존", "evidence": "x"},
        {"flag_id": "facts_empty", "severity": "HIGH",
         "description": "사실 부재", "evidence": "x"},
        {"flag_id": "angle_heuristic", "severity": "HIGH",
         "description": "각도 부재", "evidence": "x"},
    ]
    rendered = render_warning_block(flags, block_recommended=True)
    lines = rendered.splitlines()
    # 첫 줄은 헤더, 그 다음 3줄은 플래그
    assert lines[0].startswith("## ⚠️ 재료 품질 경고")
    # HIGH 2개 먼저, 그 안에서 angle_heuristic < facts_empty 알파벳 순
    assert "angle_heuristic" in lines[1] or "각도 부재" in lines[1]
    assert "[HIGH]" in lines[1]
    assert "[HIGH]" in lines[2]
    assert "[MEDIUM]" in lines[3]
    assert "**BLOCK_RECOMMENDED**" in rendered


def test_render_skips_block_recommended_when_false():
    flags = [
        {"flag_id": "english_residue", "severity": "MEDIUM",
         "description": "영어 잔존", "evidence": "x"},
    ]
    rendered = render_warning_block(flags, block_recommended=False)
    assert "**BLOCK_RECOMMENDED**" not in rendered
    assert "[MEDIUM]" in rendered


# ── 8. Draft 1388 integration fixture ────────────────────────────────

def _draft_1388_pack():
    """실제 운영자가 보여준 draft 1388 의 핸드오프 재료 재구성.

    Phase 1.5a 기준: 실 `_heuristic_angle_pack()` 빌더 출력과 동일 구조.
    editorial_goal 필드는 실 빌더가 생성하지 않으므로 제거하고,
    fallback 마커는 winner_angle.reason 에 박는다 (angle_pack.py:173-177).

    증거 4종이 모두 포함된 케이스:
      - angle_heuristic           HIGH   (winner_angle.reason 에 "heuristic fallback")
      - facts_empty               HIGH   (메타 지시문만)
      - english_residue           MEDIUM (core_tension 영어)
      - concept_translation_misuse MEDIUM (200자+ 기사 요약)
    """
    return {
        "confirmed_facts": [
            "(확정 사실이 공급되지 않음 — 새 숫자/고유명사 추가 금지)",
            "숫자·고유명사·날짜는 초안 그대로 유지",
        ],
        "concept_translation": (
            "엔비디아(Nvidia) 최고경영자 젠슨 황(Jensen Huang)의 "
            "한마디가 암호 화폐 ( 가상화폐 · 코인 ) 시장을 무섭게 달구고 있다. "
            "그는 최근 팟캐스터 드와케시 파텔(Dwarkesh Patel)과의 인터뷰에서 "
            "반도체와 암호화폐의 경계를 허무는 새로운 비즈니스 모델을 제시했다."
        ),
        "core_tension": (
            "Uncertainty on record: [opportunity] high — Nvidia CEO's AI "
            "token comment fuels counter-intuitive bridge between "
            "semiconductors and crypto markets, challenging siloed views."
        ),
        "angle_pack": {
            "winner_angle": {
                "angle": (
                    "Korea angle: 엔비디아(Nvidia) 최고경영자 젠슨 황(Jensen Huang)의 "
                    "한마디가 암호 화폐 ( 가상화폐 · 코인 ) 시장을 무섭게 달구고 있다. "
                    "그는 최근 팟캐스터 드와케시 파텔(Dwarkesh Patel)과의 인터뷰"
                ),
                "score": 50,
                "reason": "heuristic fallback (no Gemini call)",
            },
        },
    }


def test_draft_1388_detects_all_four_flags():
    result = run_quality_guard(_draft_1388_pack())
    ids = sorted(f["flag_id"] for f in result["flags"])
    assert "angle_heuristic" in ids
    assert "facts_empty" in ids
    assert "english_residue" in ids
    assert "concept_translation_misuse" in ids
    assert result["high_count"] >= 2
    assert result["block_recommended"] is True
    assert "**BLOCK_RECOMMENDED**" in result["rendered_warning_block"]


def test_draft_1388_format_handoff_starts_with_warning():
    from app.services.grok_handoff import format_handoff
    sp = _draft_1388_pack()
    # format_handoff 은 source_pack 과 angle_pack 을 분리 전달 — fixture 에서
    # angle_pack 을 꺼내 별도 인자로 준다.
    ap = sp.pop("angle_pack")
    out = format_handoff(sp, ap, "draft 본문")
    assert out.startswith("## ⚠️ 재료 품질 경고")
    assert "**BLOCK_RECOMMENDED**" in out


# ── 9. Phase 3b integration: heuristic_en_blocked placeholder 연동 ──

def test_phase3b_heuristic_en_blocked_pack_triggers_high_medium_only():
    """Phase 3b: _heuristic_angle_pack 의 placeholder 출력을 guard 가 감지.

    기대 동작:
      - detect_angle_pack_heuristic 가 winner_angle.reason 의 "heuristic fallback"
        substring 매칭으로 HIGH flag 반환
      - detect_english_residue 는 source_pack 의 [en] 프리픽스 korea_angle 로
        MEDIUM flag 반환
      - HIGH 1 + MEDIUM 1 → high_count < HIGH_FLAG_BLOCK_THRESHOLD(=2) 이므로
        block_recommended=False (Phase 3b 의도된 결과)
    """
    # Phase 3b 가 상류에서 실제 생성할 source_pack 형태
    source_pack = {
        # confirmed_facts 는 [unverified] 태그로 최소 2건 이상 채워져 facts_empty 회피
        "confirmed_facts": [
            "[unverified] 일본 방위성 2026-04-20 관련 브리핑",
            "[unverified] Mitsubishi Heavy Industries 수주 공시",
        ],
        "concept_translation": "Mogami: 호주 SEA3000 사업 낙찰 일본 호위함",
        # korea_angle 영어 → [en] 프리픽스 (> 0.3 임계 기준 감지)
        "core_tension": "[en] Australia picks Japan Mogami over Germany TKMS MEKO A-200",
        # angle_pack 은 영어 conflicts 로 인해 heuristic_en_blocked 경로로 빠진 상태
        "angle_pack": {
            "winner_angle": {
                "angle": "[angle 재작성 필요 - 영어 source 감지]",
                "score": 0,
                "reason": "heuristic fallback blocked (english source detected)",
            },
            "method": "heuristic_en_blocked",
        },
    }
    result = run_quality_guard(source_pack)
    ids = sorted(f["flag_id"] for f in result["flags"])
    assert "angle_heuristic" in ids
    assert "english_residue" in ids
    # facts_empty 는 감지되지 않아야 함 — [unverified] 태그 항목이 실제 fact 로 카운트
    assert "facts_empty" not in ids
    # HIGH 1 + MEDIUM 1 상태
    assert result["high_count"] == 1
    assert result["medium_count"] >= 1
    assert result["block_recommended"] is False
    assert "**BLOCK_RECOMMENDED**" not in result["rendered_warning_block"]
