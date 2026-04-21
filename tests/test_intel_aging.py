"""
Intel aging / display_score / visibility slot / cleanup 테스트 (Phase 6)
========================================================================
순수 함수 테스트 — 네트워크/DB 없음.
"""

from app.services.intel.score import (
    classify_visibility_slot,
    compute_display_score,
    compute_freshness_penalty,
    is_cleanup_candidate,
)


# ── compute_freshness_penalty 경계 ───────────────────────────────────────────

def test_penalty_0_to_2h():
    assert compute_freshness_penalty(0) == 0
    assert compute_freshness_penalty(1.9) == 0


def test_penalty_2_to_6h():
    assert compute_freshness_penalty(2) == 5
    assert compute_freshness_penalty(5.9) == 5


def test_penalty_6_to_12h():
    assert compute_freshness_penalty(6) == 10
    assert compute_freshness_penalty(11.9) == 10


def test_penalty_12_to_24h():
    assert compute_freshness_penalty(12) == 20
    assert compute_freshness_penalty(23.9) == 20


def test_penalty_24h_plus():
    assert compute_freshness_penalty(24) == 30
    assert compute_freshness_penalty(100) == 30
    assert compute_freshness_penalty(24 * 30) == 30


def test_penalty_negative_or_none():
    assert compute_freshness_penalty(-1) == 0
    assert compute_freshness_penalty(None) == 0  # type: ignore[arg-type]


# ── compute_display_score ────────────────────────────────────────────────────

def test_display_score_basic():
    assert compute_display_score(85, 20) == 65
    assert compute_display_score(0, 0) == 0


def test_display_score_floor_at_zero():
    assert compute_display_score(10, 30) == 0
    assert compute_display_score(5, 999) == 0


def test_display_score_invalid_inputs():
    # 예외 대신 0 반환
    assert compute_display_score("bad", 10) == 0  # type: ignore[arg-type]
    assert compute_display_score(50, None) == 50  # type: ignore[arg-type]


# ── classify_visibility_slot ─────────────────────────────────────────────────

def test_slot_strong_fresh_is_main():
    assert classify_visibility_slot("strong", 1, "none") == "main"


def test_slot_strong_window_boundary():
    assert classify_visibility_slot("strong", 24, "none") == "main"
    assert classify_visibility_slot("strong", 36, "none") == "aged"


def test_slot_strong_too_old_hidden():
    assert classify_visibility_slot("strong", 24 * 10, "none") == "hidden"


def test_slot_strong_sent_preserved_as_aged():
    # sent 는 이력 보존 — hidden 으로 떨어지지 않고 aged 유지
    assert classify_visibility_slot("strong", 24 * 10, "sent") == "aged"


def test_slot_watch_window():
    assert classify_visibility_slot("watch", 20, "none") == "main"
    assert classify_visibility_slot("watch", 30, "none") == "aged"


def test_slot_weak_window():
    assert classify_visibility_slot("weak", 6, "none") == "main"
    assert classify_visibility_slot("weak", 24, "none") == "aged"
    assert classify_visibility_slot("weak", 100, "none") == "hidden"


def test_slot_noise_window():
    assert classify_visibility_slot("noise", 3, "none") == "secondary"
    assert classify_visibility_slot("noise", 10, "none") == "hidden"


def test_slot_noise_sent_preserved():
    assert classify_visibility_slot("noise", 10, "sent") == "aged"


# ── is_cleanup_candidate ─────────────────────────────────────────────────────

def test_cleanup_noise_over_48h():
    assert is_cleanup_candidate("noise", 50, "none") is True


def test_cleanup_noise_within_48h_is_false():
    assert is_cleanup_candidate("noise", 30, "none") is False


def test_cleanup_weak_over_72h():
    assert is_cleanup_candidate("weak", 80, "none") is True


def test_cleanup_strong_over_7d():
    assert is_cleanup_candidate("strong", 24 * 8, "none") is True


def test_cleanup_sent_never_candidate():
    # 전송된 이력은 항상 보존
    assert is_cleanup_candidate("noise", 500, "sent") is False
    assert is_cleanup_candidate("weak", 500, "sent") is False
    assert is_cleanup_candidate("strong", 500, "sent") is False


def test_cleanup_fresh_items_false():
    assert is_cleanup_candidate("strong", 1, "none") is False
    assert is_cleanup_candidate("watch", 1, "none") is False
    assert is_cleanup_candidate("weak", 1, "none") is False
