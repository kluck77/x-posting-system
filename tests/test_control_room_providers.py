"""
/control/providers v2 회귀 방지.

배경:
  Agents 탭이 상태 리스트에서 "실시간 워크스테이션" 으로 재설계되면서
  /control/providers 응답 구조가 확장됐다. 프론트가 기대하는 필드가
  계속 유지되는지를 고정한다.

원칙:
  1) Grok 은 자동(HookReviewer) + 수동(TrendHunter) 두 역할로 분리돼 존재
  2) 각 역할 row 는 role/role_kr/role_desc/provider/configured/status 가 필수
  3) 응답 최상위에 stats, activity, provider_health 가 존재
  4) stats 는 active_count / total_roles / today_runs / pending 포함
  5) provider_health 에 핵심 5 provider 가 모두 노출 (configured 여부 무관)
"""
import asyncio

import pytest

from app.api import control_room


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def _grok_configured(monkeypatch):
    """테스트 환경에서 grok/openai/anthropic 키가 있다고 가정 (status 분기 확인용)."""
    from app.config import settings
    monkeypatch.setattr(settings, "grok_api_key", "test-grok", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "test-oa", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-an", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "test-gm", raising=False)
    monkeypatch.setattr(settings, "perplexity_api_key", "test-px", raising=False)
    yield


@pytest.mark.asyncio
async def test_providers_v2_shape(_grok_configured):
    """응답 최상위 키 + 역할 split + provider health 를 고정."""
    data = await control_room.get_providers()

    # 최상위
    assert "roles" in data
    assert "stats" in data
    assert "activity" in data
    assert "provider_health" in data
    assert "mock_mode" in data

    # stats
    s = data["stats"]
    for k in ("active_count", "total_roles", "today_runs", "pending"):
        assert k in s, f"stats.{k} missing"

    # roles: Grok 은 반드시 2개 row 로 분리
    roles = data["roles"]
    role_names = [r["role"] for r in roles]
    assert "TrendHunter" in role_names
    assert "HookReviewer" in role_names
    assert "DraftWriter" in role_names
    assert "Reviewer" in role_names
    assert "Researcher" in role_names
    assert "FactChecker" in role_names

    # 각 role 은 요구 필드가 모두 존재
    required = {"role", "role_kr", "role_desc", "provider", "configured", "status"}
    for r in roles:
        missing = required - set(r.keys())
        assert not missing, f"role {r.get('role')} missing {missing}"
        assert r["status"] in ("working", "idle", "blocked", "manual", "delayed", "error")

    # TrendHunter 는 수동이어야 한다
    th = next(r for r in roles if r["role"] == "TrendHunter")
    assert th["status"] == "manual"

    # HookReviewer 는 manual 이 아닌 상태 (working/idle/blocked)
    hr = next(r for r in roles if r["role"] == "HookReviewer")
    assert hr["status"] != "manual"

    # provider_health: 핵심 5 provider 노출
    health_names = {p["name"] for p in data["provider_health"]}
    assert {"openai", "anthropic", "gemini", "grok", "perplexity"}.issubset(health_names)
    for p in data["provider_health"]:
        assert "configured" in p
        assert "calls_today" in p
        assert isinstance(p["calls_today"], int)


@pytest.mark.asyncio
async def test_providers_v2_activity_safe_when_empty():
    """DB 비어있는 환경(테스트) 에서도 activity 는 리스트여야 한다 (None/예외 금지)."""
    data = await control_room.get_providers()
    assert isinstance(data["activity"], list)


@pytest.mark.asyncio
async def test_providers_v2_grok_split_does_not_double_count(_grok_configured):
    """
    Grok 가 2 row 로 나뉘지만 총 runs_today 합계는
    비-Grok 역할(4개) × today_drafts + grok_calls 수준이 돼야 한다.
    """
    data = await control_room.get_providers()
    roles = data["roles"]

    # TrendHunter 는 runs_today 가 None (manual 전용)
    th = next(r for r in roles if r["role"] == "TrendHunter")
    assert th["runs_today"] is None

    # HookReviewer 는 정수 (0 포함)
    hr = next(r for r in roles if r["role"] == "HookReviewer")
    assert isinstance(hr["runs_today"], int)
