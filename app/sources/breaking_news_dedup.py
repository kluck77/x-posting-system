"""속보 중복 제거.

1단계: SimHash 64bit (hamming ≤ 6 → 즉시 dup)
2단계: (Phase 2 예정) 임베딩 cosine ≥ 0.85

kiwipiepy 가 없으면 자동으로 단순 split 토큰화로 fallback.
"""
from __future__ import annotations

import hashlib
import logging
import time

logger = logging.getLogger(__name__)

try:
    from kiwipiepy import Kiwi  # type: ignore
    _KIWI = Kiwi(model_type="cong")
    _KIWI_AVAILABLE = True
except Exception as _e:
    logger.warning(f"[Dedup] kiwipiepy 없음 — split 토큰 fallback: {_e}")
    _KIWI = None
    _KIWI_AVAILABLE = False


def _extract_nouns(text: str) -> list[str]:
    if _KIWI_AVAILABLE:
        try:
            tokens = _KIWI.tokenize(text)
            return [t.form for t in tokens if t.tag.startswith("NN")]
        except Exception:
            return text.split()
    return text.split()


def _simhash(text: str, bits: int = 64) -> int:
    """간단한 SimHash 구현."""
    nouns = _extract_nouns(text)
    if not nouns:
        return 0
    v = [0] * bits
    for word in nouns:
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        for i in range(bits):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    return sum(1 << i for i in range(bits) if v[i] > 0)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class DedupCache:
    """프로세스 인메모리 dedup 캐시. TTL 기반 자동 purge."""

    def __init__(self, ttl_seconds: int = 3600):
        self.cache: list[tuple[int, float, str]] = []   # (hash, ts, title)
        self.ttl = ttl_seconds

    def _purge(self):
        now = time.time()
        self.cache = [
            (h, ts, t) for h, ts, t in self.cache if now - ts < self.ttl
        ]

    def is_duplicate(self, title: str, threshold: int = 6) -> bool:
        self._purge()
        new_hash = _simhash(title)
        for h, _, _ in self.cache:
            if _hamming(new_hash, h) <= threshold:
                return True
        return False

    def add(self, title: str):
        self._purge()
        h = _simhash(title)
        self.cache.append((h, time.time(), title))


# 전역 캐시 인스턴스
_DEDUP_CACHE = DedupCache(ttl_seconds=3600)


def check_and_register(title: str) -> bool:
    """
    True  → 중복 (스킵)
    False → 신규 (처리)
    """
    if not title:
        return False
    if _DEDUP_CACHE.is_duplicate(title):
        logger.info(f"[Dedup] 중복 감지: {title[:50]}")
        return True
    _DEDUP_CACHE.add(title)
    return False
