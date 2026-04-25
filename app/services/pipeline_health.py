"""파이프라인 헬스 체크 — 5-AI 동시 핑.

매일 06:00 KST 텔레그램 운영자 채팅으로 리포트.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class HealthCheck:
    service:    str
    status:     str            # ok / degraded / down
    latency_ms: int = 0
    error:      str = ""


async def _check_openai() -> HealthCheck:
    if not getattr(settings, "openai_api_key", ""):
        return HealthCheck("OpenAI", "down", 0, "no api key")
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 5,
                },
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return HealthCheck("OpenAI", "ok", latency)
            return HealthCheck("OpenAI", "degraded", latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return HealthCheck("OpenAI", "down", 0, str(e)[:50])


async def _check_anthropic() -> HealthCheck:
    if not getattr(settings, "anthropic_api_key", ""):
        return HealthCheck("Anthropic", "down", 0, "no api key")
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ok"}],
                },
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return HealthCheck("Anthropic", "ok", latency)
            return HealthCheck("Anthropic", "degraded", latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return HealthCheck("Anthropic", "down", 0, str(e)[:50])


async def _check_gemini() -> HealthCheck:
    if not getattr(settings, "gemini_api_key", ""):
        return HealthCheck("Gemini", "down", 0, "no api key")
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": "ok"}]}],
                    "generationConfig": {"maxOutputTokens": 5},
                },
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return HealthCheck("Gemini", "ok", latency)
            return HealthCheck("Gemini", "degraded", latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return HealthCheck("Gemini", "down", 0, str(e)[:50])


async def _check_perplexity() -> HealthCheck:
    if not getattr(settings, "perplexity_api_key", ""):
        return HealthCheck("Perplexity", "down", 0, "no api key")
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.perplexity_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 5,
                },
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return HealthCheck("Perplexity", "ok", latency)
            return HealthCheck("Perplexity", "degraded", latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return HealthCheck("Perplexity", "down", 0, str(e)[:50])


async def _check_grok() -> HealthCheck:
    grok_key = (
        getattr(settings, "grok_api_key", "")
        or getattr(settings, "xai_api_key", "")
    )
    if not grok_key:
        return HealthCheck("Grok", "down", 0, "no api key")
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {grok_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-3-mini-fast",
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 5,
                },
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return HealthCheck("Grok", "ok", latency)
            return HealthCheck("Grok", "degraded", latency, f"HTTP {resp.status_code}")
    except Exception as e:
        return HealthCheck("Grok", "down", 0, str(e)[:50])


async def run_full_check() -> list[HealthCheck]:
    """5-AI 전체 헬스 체크 — 병렬 실행."""
    results = await asyncio.gather(
        _check_openai(),
        _check_anthropic(),
        _check_gemini(),
        _check_perplexity(),
        _check_grok(),
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, HealthCheck)]


def format_health_report(checks: list[HealthCheck]) -> str:
    """텔레그램 메시지 포맷 — 한국어."""
    lines = ["⚡ 시스템 상태 (5-AI 파이프라인)", ""]
    icon_map = {"ok": "✅", "degraded": "⚠️", "down": "❌"}
    for c in checks:
        icon = icon_map.get(c.status, "❓")
        line = f"{icon} {c.service}"
        if c.status == "ok":
            line += f" · {c.latency_ms}ms"
        elif c.error:
            line += f" · {c.error}"
        lines.append(line)
    return "\n".join(lines)


async def _send_to_operator(text: str) -> None:
    """운영자 chat_id 로 평문 메시지 전송 — 텔레그램 Bot API 직접."""
    token = getattr(settings, "telegram_bot_token", "") or ""
    chat_id = getattr(settings, "telegram_chat_id", "") or ""
    if not (token and chat_id):
        logger.info(f"[Health] 운영자 채팅 미설정 — skip\n{text}")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception as e:
        logger.warning(f"[Health] 운영자 전송 실패: {e}")


async def daily_report_loop():
    """매일 06:00 KST 헬스 리포트."""
    while True:
        try:
            now = datetime.now()
            target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait = (target - now).total_seconds()
            await asyncio.sleep(max(60, wait))

            checks = await run_full_check()
            report = format_health_report(checks)
            await _send_to_operator(report)
        except Exception as e:
            logger.warning(f"[Health] 일일 리포트 실패: {e}")
            await asyncio.sleep(3600)
