"""
Control Room 엔드포인트 테스트
==============================
Phase 17 — Control Room Bundle
/control/status, /control/flow-trace, /control/providers, /control/naver 엔드포인트 및
naver_usage 모듈 테스트.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ── naver_usage 단위 테스트 ────────────────────────────────────────────────────

class TestNaverUsage:
    def setup_method(self):
        """각 테스트 전 모듈 상태 초기화."""
        import app.services.naver_usage as nu
        nu._today_date = None
        nu._today_calls = 0

    def test_initial_state_is_zero(self):
        from app.services.naver_usage import get_today_calls
        assert get_today_calls() == 0

    def test_record_call_increments(self):
        from app.services.naver_usage import record_call, get_today_calls
        record_call(1)
        assert get_today_calls() == 1
        record_call(3)
        assert get_today_calls() == 4

    def test_get_status_idle_when_zero(self):
        from app.services.naver_usage import get_status
        s = get_status()
        assert s["level"] == "idle"
        assert s["used_today"] == 0
        assert s["daily_limit"] == 25_000
        assert s["remaining"] == 25_000

    def test_get_status_ok_level(self):
        from app.services.naver_usage import record_call, get_status
        record_call(5_000)   # 20% used
        s = get_status()
        assert s["level"] == "ok"
        assert s["pct_used"] == pytest.approx(20.0)

    def test_get_status_caution_level(self):
        from app.services.naver_usage import record_call, get_status
        record_call(15_000)  # 60% used
        s = get_status()
        assert s["level"] == "caution"

    def test_get_status_warning_level(self):
        from app.services.naver_usage import record_call, get_status
        record_call(22_000)  # 88% used
        s = get_status()
        assert s["level"] == "warning"

    def test_remaining_never_negative(self):
        from app.services.naver_usage import record_call, get_status
        record_call(30_000)  # over limit
        s = get_status()
        assert s["remaining"] == 0

    def test_date_reset_on_new_day(self):
        """날짜가 바뀌면 카운터가 리셋된다."""
        from app.services.naver_usage import record_call, get_today_calls
        import app.services.naver_usage as nu
        from datetime import date
        record_call(100)
        assert get_today_calls() == 100
        # Simulate date change
        nu._today_date = date(2000, 1, 1)
        assert get_today_calls() == 0

    def test_status_has_note_field(self):
        from app.services.naver_usage import get_status
        s = get_status()
        assert "note" in s
        assert len(s["note"]) > 0


# ── FastAPI TestClient 픽스처 ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from app.api.admin import app
    return TestClient(app, raise_server_exceptions=False)


# ── /control/naver ────────────────────────────────────────────────────────────

class TestNaverEndpoint:
    def test_naver_returns_200(self, client):
        resp = client.get("/control/naver")
        assert resp.status_code == 200

    def test_naver_has_required_keys(self, client):
        resp = client.get("/control/naver")
        data = resp.json()
        for key in ("used_today", "daily_limit", "remaining", "pct_used", "level"):
            assert key in data, f"Missing key: {key}"

    def test_naver_level_is_valid(self, client):
        resp = client.get("/control/naver")
        assert resp.json()["level"] in ("idle", "ok", "caution", "warning")


# ── /control/status ───────────────────────────────────────────────────────────

class TestControlStatus:
    def test_status_returns_200(self, client):
        resp = client.get("/control/status")
        assert resp.status_code == 200

    def test_status_has_top_level_keys(self, client):
        resp = client.get("/control/status")
        data = resp.json()
        for key in ("generated_at", "health", "queue", "usage", "activity", "monitor", "news"):
            assert key in data, f"Missing top-level key: {key}"

    def test_health_subkeys(self, client):
        resp = client.get("/control/status")
        health = resp.json()["health"]
        # Either has error key (partial failure) or has expected subkeys
        if "error" not in health:
            assert "db_ok" in health
            assert "mock_mode" in health

    def test_generated_at_is_iso(self, client):
        resp = client.get("/control/status")
        ts = resp.json()["generated_at"]
        # Should be parseable as ISO datetime
        from datetime import datetime
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_generated_at_kst_present(self, client):
        resp = client.get("/control/status")
        assert "generated_at_kst" in resp.json()
        assert "KST" in resp.json()["generated_at_kst"]


# ── /control/flow-trace ───────────────────────────────────────────────────────

class TestFlowTrace:
    def test_flow_trace_returns_200(self, client):
        resp = client.get("/control/flow-trace")
        assert resp.status_code == 200

    def test_flow_trace_is_list(self, client):
        resp = client.get("/control/flow-trace")
        assert isinstance(resp.json(), list)

    def test_flow_trace_limit_param(self, client):
        resp = client.get("/control/flow-trace?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 5

    def test_flow_trace_item_schema(self, client):
        """기존 초안이 있다면 필드 구조를 검증한다."""
        resp = client.get("/control/flow-trace")
        items = resp.json()
        if items:
            item = items[0]
            for key in ("id", "hook", "status", "created_kst"):
                assert key in item, f"Missing key: {key}"


# ── /control/providers ────────────────────────────────────────────────────────

class TestProviders:
    def test_providers_returns_200(self, client):
        resp = client.get("/control/providers")
        assert resp.status_code == 200

    def test_providers_has_roles(self, client):
        resp = client.get("/control/providers")
        data = resp.json()
        assert "roles" in data
        assert isinstance(data["roles"], list)

    def test_providers_role_count(self, client):
        resp = client.get("/control/providers")
        roles = resp.json()["roles"]
        assert len(roles) == 5

    def test_providers_role_schema(self, client):
        resp = client.get("/control/providers")
        for role in resp.json()["roles"]:
            assert "role" in role
            assert "provider" in role
            assert "configured" in role

    def test_providers_has_mock_mode(self, client):
        resp = client.get("/control/providers")
        assert "mock_mode" in resp.json()

    def test_providers_has_today_draft_count(self, client):
        resp = client.get("/control/providers")
        assert "today_draft_count" in resp.json()

    def test_providers_role_names(self, client):
        resp = client.get("/control/providers")
        role_names = {r["role"] for r in resp.json()["roles"]}
        expected = {"DraftWriter", "Reviewer", "Researcher", "FactChecker", "TrendHunter"}
        assert role_names == expected


# ── /control/ 대시보드 HTML ───────────────────────────────────────────────────

class TestDashboardPage:
    def test_dashboard_returns_html(self, client):
        from pathlib import Path
        if not Path("static/dashboard.html").exists():
            pytest.skip("static/dashboard.html 없음 — 환경 미설정")
        resp = client.get("/control/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_html_has_key_sections(self, client):
        from pathlib import Path
        if not Path("static/dashboard.html").exists():
            pytest.skip("static/dashboard.html 없음 — 환경 미설정")
        resp = client.get("/control/")
        body = resp.text
        # Check for key API endpoints referenced in the JS
        assert "/control/status" in body
        assert "/control/providers" in body
        assert "/control/flow-trace" in body
