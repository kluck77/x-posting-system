"""Prompt caching 헬퍼.

Anthropic Messages API cache_control 규격:
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching

system 블록을 text+cache_control list 로 래핑해서 5분 ephemeral 캐시 적용.
"""
from __future__ import annotations


def wrap_anthropic_cache(text: str) -> list[dict]:
    """Anthropic cache_control 적용 system 블록 반환.

    Args:
        text: system prompt 전문

    Returns:
        [{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}]
    """
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ]
