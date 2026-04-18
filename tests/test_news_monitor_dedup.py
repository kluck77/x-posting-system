"""
후보 알림 중복 회귀 방지.

배경:
  "Bitcoin, Stocks Surge..." 기사를 초안 생성했는데도 동일 기사가
  다시 후보알림으로 오는 사건이 발생. in-memory _seen_urls 는
  프로세스 재시작 시 소실되고, _alert_cooldown 은 score 패널티만 주므로
  하드 차단이 없었다.

원칙:
  1) DB 에 동일 URL 로 Draft 가 걸려 있으면 알림 skip
  2) URL 변형(트래킹 파라미터 등)도 제목 story_key 로 매칭해 skip
  3) fail-open: DB 오류 시 False (알림 흐름 유지)
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
)


def _mk_source(session, *, title: str, url: str):
    s = SourceItem(
        title=title,
        url=url,
        source_text="본문",
        source_type="news",
        language="ko",
        created_at=datetime.now(timezone.utc),
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _mk_draft(session, *, source_id: int):
    d = Draft(
        source_item_id=source_id,
        hook="hook",
        body="본문\n\n⚠️ 진짜 쟁점: x\n📌 지금 봐야 할 포인트: y",
        category=ContentCategory.ECONOMY,
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PENDING,
    )
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


class TestHasExistingDraft:
    def test_same_url_with_draft_blocks(self, db_session, monkeypatch):
        """동일 URL + Draft 존재 → skip"""
        from app.services import news_monitor
        src = _mk_source(db_session, title="Bitcoin Hormuz", url="https://decrypt.co/364725")
        _mk_draft(db_session, source_id=src.id)

        # SessionLocal 을 테스트 세션 팩토리로 대체
        monkeypatch.setattr(
            news_monitor, "_has_existing_draft",
            news_monitor._has_existing_draft,  # keep reference
        )
        with patch.object(news_monitor, "SessionLocal", create=True) as _:
            pass  # we'll patch via the module import inside the function instead

        with patch("app.db.SessionLocal", return_value=db_session) as _sl:
            # prevent the `with ... as s` context manager from closing the session
            db_session.close = lambda: None
            db_session.__enter__ = lambda: db_session
            db_session.__exit__ = lambda *a: None
            drafted, reason = news_monitor._has_existing_draft(
                "https://decrypt.co/364725", "Bitcoin Hormuz"
            )
            assert drafted is True
            assert reason == "same-url"

    def test_url_variant_same_story_blocks(self, db_session):
        """URL 다르지만 제목 story_key 일치 → skip"""
        from app.services import news_monitor
        src = _mk_source(
            db_session,
            title="Bitcoin Stocks Surge as Iran Says Strait of Hormuz Is Completely Open",
            url="https://decrypt.co/364725",
        )
        _mk_draft(db_session, source_id=src.id)

        db_session.close = lambda: None
        db_session.__enter__ = lambda: db_session
        db_session.__exit__ = lambda *a: None
        with patch("app.db.SessionLocal", return_value=db_session):
            # 완전히 다른 URL 인데 제목이 같은 기사
            drafted, reason = news_monitor._has_existing_draft(
                "https://decrypt.co/364725?utm_source=feed&utm_campaign=rss",
                "Bitcoin Stocks Surge as Iran Says Strait of Hormuz Is Completely Open",
            )
            assert drafted is True
            # same-url 로 먼저 걸리지 않는 경우 same-story 로 걸려야 한다
            assert reason in ("same-url", "same-story")

    def test_new_article_allows(self, db_session):
        """기존에 Draft 없는 새 기사 → 통과 (False)"""
        from app.services import news_monitor
        db_session.close = lambda: None
        db_session.__enter__ = lambda: db_session
        db_session.__exit__ = lambda *a: None
        with patch("app.db.SessionLocal", return_value=db_session):
            drafted, reason = news_monitor._has_existing_draft(
                "https://example.com/brand-new-article",
                "완전히 새로운 제목",
            )
            assert drafted is False
            assert reason == ""

    def test_source_without_draft_allows(self, db_session):
        """SourceItem 만 있고 Draft 없으면 통과 (news_monitor 가 수집만 한 단계)"""
        from app.services import news_monitor
        _mk_source(db_session, title="수집만 된 기사", url="https://example.com/x")
        db_session.close = lambda: None
        db_session.__enter__ = lambda: db_session
        db_session.__exit__ = lambda *a: None
        with patch("app.db.SessionLocal", return_value=db_session):
            drafted, reason = news_monitor._has_existing_draft(
                "https://example.com/x", "수집만 된 기사"
            )
            assert drafted is False

    def test_db_error_fail_open(self):
        """DB import 자체가 실패해도 fail-open (False 반환)."""
        from app.services import news_monitor
        # 잘못된 Session 팩토리 — 호출 시 예외
        def _boom():
            raise RuntimeError("DB down")
        with patch("app.db.SessionLocal", side_effect=_boom):
            drafted, reason = news_monitor._has_existing_draft(
                "https://example.com/a", "제목"
            )
            assert drafted is False
            assert reason == ""

    def test_empty_url_and_title(self):
        """URL + 제목 둘 다 빈 값 → False"""
        from app.services import news_monitor
        drafted, reason = news_monitor._has_existing_draft("", "")
        assert drafted is False
        assert reason == ""
