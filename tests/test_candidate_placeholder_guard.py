"""
Lane early-return placeholder draft 가 승인 경로로 새어나가는 버그 회귀 방지.

버그 체인:
  1) orchestrator Lane early-return 이 auto-collected CANDIDATE/BREAKING_NOW
     기사에 대해 placeholder draft 를 만든다
       hook = "[CANDIDATE] {title}"
       body = "[CANDIDATE] 알림/적재 완료 — AI 미호출"
  2) approve-guard(is_broken_draft) 가 이 placeholder 를 감지해야 한다
  3) sanitize_internal_tags 는 body 접두사가 [CANDIDATE]/[BREAKING_NOW] 이면
     body 를 blank 으로 만들어 "본문이 없습니다" 경로로 유도해야 한다
"""
from app.services.draft_service import is_broken_draft, broken_reason
from app.services.text_cleaner import sanitize_internal_tags


class TestIsBrokenDraftCatchesPlaceholder:
    def test_candidate_placeholder_is_broken(self):
        body = "[CANDIDATE] 알림/적재 완료 — AI 미호출"
        assert is_broken_draft(body) is True
        assert "알림/적재 완료" in broken_reason(body)

    def test_breaking_now_placeholder_is_broken(self):
        body = "[BREAKING_NOW] 알림/적재 완료 — AI 미호출"
        assert is_broken_draft(body) is True
        assert "알림/적재 완료" in broken_reason(body)

    def test_normal_body_is_not_broken(self):
        body = (
            "한국은행이 기준금리를 0.25%p 인하했다. 환율 방어와 내수 부양 사이의 긴장.\n\n"
            "⚠️ 진짜 쟁점: 정책 우선순위\n"
            "📌 지금 봐야 할 포인트: 원달러 1380선"
        )
        assert is_broken_draft(body) is False


class TestSanitizeBlanksPlaceholder:
    def test_candidate_body_is_blanked(self):
        hook, body = sanitize_internal_tags(
            "[CANDIDATE] 장특공제 폐지 논란",
            "[CANDIDATE] 알림/적재 완료 — AI 미호출",
        )
        # hook 은 내부 태그만 제거
        assert hook == "장특공제 폐지 논란"
        # body 는 통째로 blank 처리 (→ _handle_approve 가 "본문 없음" 경로 탐)
        assert body == ""

    def test_breaking_now_body_is_blanked(self):
        hook, body = sanitize_internal_tags(
            "[BREAKING_NOW] 속보",
            "[BREAKING_NOW] 알림/적재 완료 — AI 미호출",
        )
        assert hook == "속보"
        assert body == ""

    def test_normal_body_passes_through(self):
        hook, body = sanitize_internal_tags(
            "한국은행 금리 인하",
            "본문 2~3문장\n\n⚠️ 진짜 쟁점: 환율 방어\n📌 지금 봐야 할 포인트: 원달러",
        )
        assert hook == "한국은행 금리 인하"
        assert body.startswith("본문 2~3문장")
        assert "⚠️ 진짜 쟁점:" in body
