"""
text_cleaner.ensure_resonance_structure — Resonance 구조(⚠️/📌) 최후 방어선 테스트.

이 함수는 프롬프트(OpenAI DraftWriter / Anthropic Reviewer)가 마커를
출력하지 못한 경우에만 동작하는 fallback 이다. 프롬프트가 정상이면 no-op.
"""
from app.services.text_cleaner import ensure_resonance_structure


class TestEnsureResonanceStructureOk:
    def test_ko_both_markers_present_returns_ok(self):
        body = (
            "한국은행이 기준금리를 0.25%p 인하했다.\n\n"
            "⚠️ 진짜 쟁점: 환율 방어와 내수 부양의 충돌\n"
            "📌 지금 봐야 할 포인트: 원달러 1380선 이탈 여부"
        )
        out, status = ensure_resonance_structure(body, language="ko")
        assert status == "ok"
        assert out == body  # no-op

    def test_en_both_markers_present_returns_ok(self):
        body = (
            "BOK cut rates 25bp today.\n\n"
            "⚠️ Real issue: FX defense vs domestic demand\n"
            "📌 Watch for: USD/KRW breaking 1380"
        )
        out, status = ensure_resonance_structure(body, language="en")
        assert status == "ok"
        assert out == body


class TestEnsureResonanceStructurePartial:
    def test_ko_only_warn_keeps_original(self):
        body = "본문 한 줄.\n\n⚠️ 진짜 쟁점: 갈림길"
        out, status = ensure_resonance_structure(body, language="ko")
        assert status == "partial"
        assert out == body  # 반쪽 구조 보존 — 원본 유지

    def test_ko_only_pin_keeps_original(self):
        body = "본문 한 줄.\n\n📌 지금 봐야 할 포인트: 확인 신호"
        out, status = ensure_resonance_structure(body, language="ko")
        assert status == "partial"
        assert out == body


class TestEnsureResonanceStructureInjected:
    def test_ko_missing_both_injects_placeholder(self):
        body = "한국은행이 기준금리를 인하했다. 환율에 영향이 있다."
        out, status = ensure_resonance_structure(body, language="ko")
        assert status == "injected"
        assert "⚠️ 진짜 쟁점:" in out
        assert "📌 지금 봐야 할 포인트:" in out
        assert "구조 누락" in out  # placeholder 가시성
        assert out.startswith(body.rstrip())

    def test_en_missing_both_injects_placeholder(self):
        body = "BOK cut rates today. FX impact likely."
        out, status = ensure_resonance_structure(body, language="en")
        assert status == "injected"
        assert "⚠️ Real issue:" in out
        assert "📌 Watch for:" in out
        assert "structure missing" in out
        assert out.startswith(body.rstrip())

    def test_default_language_treated_as_ko(self):
        body = "본문만 있고 마커 없음."
        out, status = ensure_resonance_structure(body)
        assert status == "injected"
        assert "⚠️ 진짜 쟁점:" in out


class TestEnsureResonanceStructureEdge:
    def test_empty_returns_empty(self):
        out, status = ensure_resonance_structure("", language="ko")
        assert out == ""
        assert status == "empty"

    def test_preserves_ko_markers_even_when_language_is_en(self):
        # 실제 운영에서 한국어 초안이 language="en" 로 잘못 들어와도
        # 마커 자체는 KO/EN 모두 인식되어야 함
        body = (
            "본문.\n\n"
            "⚠️ 진짜 쟁점: 충돌\n"
            "📌 지금 봐야 할 포인트: 신호"
        )
        out, status = ensure_resonance_structure(body, language="en")
        assert status == "ok"
        assert out == body
