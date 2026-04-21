"""
Intel promote 엔드포인트 테스트 (Phase 2)
==========================================
Orchestrator.full_pipeline 을 monkeypatch 로 stub. 네트워크/AI 호출 0.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.content import Base
from app.models.intel import IntelItem


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient + in-file SQLite + 실제 IntelItem 1 건 삽입."""
    # 격리된 DB 파일
    db_file = tmp_path / "intel_promote.db"
    url = f"sqlite:///{db_file}"

    import app.db as appdb
    engine = create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr(appdb, "engine", engine)
    monkeypatch.setattr(appdb, "SessionLocal",
                        sessionmaker(autocommit=False, autoflush=False, bind=engine))
    import app.models.intel  # noqa: F401 — 테이블 등록
    Base.metadata.create_all(bind=engine)

    # 테스트 레코드
    db = appdb.SessionLocal()
    db.add(IntelItem(
        source="cryptopanic", source_type="crypto_news",
        title="SEC approved Bitcoin ETF",
        summary="Spot BTC ETF approved", url="https://example.com/x",
        published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        entity="SEC", category="crypto_stream",
        content_hash="promote-test-hash-1", shortlisted=True,
        flagged_reason="R1:keyword=bitcoin; R3:stage=approved",
        priority_score=90, score_label="strong",
        why_flagged_human="SEC 규제 승인 · 크립토 핵심 키워드",
    ))
    db.commit(); db.close()

    from app.api.admin import app
    return TestClient(app)


def _stub_orchestrator(monkeypatch, *, success=True, draft_id=42,
                       telegram_sent=True, error=None):
    """Orchestrator.full_pipeline 을 결정적 결과로 stub."""
    from app.api import intel as intel_api

    class _StubOrch:
        def __init__(self, db=None):
            pass
        async def full_pipeline(self, data):
            if success:
                return {
                    "success": True,
                    "draft_id": draft_id,
                    "category": "crypto",
                    "risk_level": "low",
                    "telegram_sent": telegram_sent,
                    "hook": "stub hook",
                    "body": "stub body",
                    "message": "stub",
                }
            return {"success": False, "error": error or "stub-fail"}
        def close(self):
            pass

    monkeypatch.setattr(intel_api, "Orchestrator", _StubOrch)


# ── 정상 promote ─────────────────────────────────────────────────────────────

def test_promote_success_marks_sent(client, monkeypatch):
    _stub_orchestrator(monkeypatch, success=True, draft_id=42, telegram_sent=True)
    r = client.post("/control/intel/items/1/promote")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["draft_id"] == 42
    assert body["promotion_status"] == "sent"

    detail = client.get("/control/intel/items/1").json()
    assert detail["promotion_status"] == "sent"
    assert detail["promoted_draft_id"] == 42


# ── 중복 전송 가드 ───────────────────────────────────────────────────────────

def test_promote_duplicate_returns_409(client, monkeypatch):
    _stub_orchestrator(monkeypatch, success=True, draft_id=42)
    r1 = client.post("/control/intel/items/1/promote")
    assert r1.status_code == 200
    r2 = client.post("/control/intel/items/1/promote")
    assert r2.status_code == 409
    detail = r2.json()["detail"]
    assert detail["already"] is True
    assert detail["draft_id"] == 42


# ── 실패 → failed 상태 ──────────────────────────────────────────────────────

def test_promote_failure_marks_failed(client, monkeypatch):
    _stub_orchestrator(monkeypatch, success=False, error="AI provider down")
    r = client.post("/control/intel/items/1/promote")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["promotion_status"] == "failed"
    assert "AI provider down" in (body["error"] or "")


# ── failed → 재시도 성공 전환 ────────────────────────────────────────────────

def test_promote_retry_after_failure(client, monkeypatch):
    _stub_orchestrator(monkeypatch, success=False, error="temp fail")
    client.post("/control/intel/items/1/promote")  # failed

    _stub_orchestrator(monkeypatch, success=True, draft_id=77)
    r = client.post("/control/intel/items/1/promote")
    assert r.status_code == 200
    assert r.json()["promotion_status"] == "sent"
    assert r.json()["draft_id"] == 77


# ── 404 ──────────────────────────────────────────────────────────────────────

def test_promote_unknown_id_returns_404(client, monkeypatch):
    _stub_orchestrator(monkeypatch, success=True)
    r = client.post("/control/intel/items/9999/promote")
    assert r.status_code == 404


# ── language detection ──────────────────────────────────────────────────────

def test_source_item_language_detected_ko(client, monkeypatch):
    """한글 제목 인지 확인 — full_pipeline 이 받는 data 를 가로채서 검사."""
    received: dict = {}

    from app.api import intel as intel_api

    class _CaptureOrch:
        def __init__(self, db=None): pass
        async def full_pipeline(self, data):
            received["title"] = data.title
            received["source_type"] = data.source_type
            received["language"] = data.language
            return {"success": True, "draft_id": 101, "category":"crypto",
                    "risk_level":"low","telegram_sent":True,"hook":"h","body":"b","message":"m"}
        def close(self): pass

    monkeypatch.setattr(intel_api, "Orchestrator", _CaptureOrch)

    # 기존 레코드(영문) 을 한글 제목으로 업데이트
    import app.db as appdb
    db = appdb.SessionLocal()
    row = db.query(IntelItem).first()
    row.title = "한화 사업목적에 가상자산 추가 공시"
    db.commit(); db.close()

    r = client.post("/control/intel/items/1/promote")
    assert r.status_code == 200
    assert received["language"] == "ko"
    assert received["source_type"].startswith("intel:")
