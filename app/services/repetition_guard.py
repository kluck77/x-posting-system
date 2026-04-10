"""
반복 방지 / 스타일 일관성 가드
================================
최근 승인/게시된 초안과의 유사도를 확인하여 반복 경고를 반환합니다.

알고리즘: 토큰 수준 Jaccard 유사도 (외부 의존성 없음).
저장소: 현재 SQLite Draft 테이블 재사용 (별도 저장소 없음).

임계값:
  >= 0.55 → 경고
  >= 0.75 → 강한 경고 (거의 동일)
"""

import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 0.55
STRONG_WARN_THRESHOLD = 0.75


class RepetitionGuard:
    """SQLite 기반 경량 반복/스타일 경고 생성기."""

    def __init__(self, db: Session):
        self.db = db

    def check_texts(
        self,
        texts: list[str],
        lookback_days: int = 14,
    ) -> list[str]:
        """
        텍스트 목록을 최근 승인 초안과 비교하여 경고 목록 반환.

        Args:
            texts: 확인할 텍스트 목록 (main_posts + short_version 등)
            lookback_days: 과거 N일치 데이터와 비교

        Returns:
            경고 문자열 목록 (없으면 빈 리스트)
        """
        recent = self._get_recent_hooks(lookback_days)
        if not recent:
            return []

        warnings: list[str] = []
        seen_pairs: set[tuple[str, str]] = set()

        for text in texts:
            if not text or len(text) < 20:
                continue

            hook = _extract_hook(text)

            for recent_hook in recent:
                pair = (hook[:40], recent_hook[:40])
                if pair in seen_pairs:
                    continue

                sim = _jaccard(hook, recent_hook)

                if sim >= STRONG_WARN_THRESHOLD:
                    warnings.append(
                        f"🚨 거의 동일한 표현 감지 ({int(sim*100)}% 유사)\n"
                        f"  신규: \"{hook[:60]}...\"\n"
                        f"  기존: \"{recent_hook[:60]}...\""
                    )
                    seen_pairs.add(pair)
                    break
                elif sim >= WARN_THRESHOLD:
                    warnings.append(
                        f"⚠️ 유사 표현 감지 ({int(sim*100)}% 유사)\n"
                        f"  신규: \"{hook[:60]}...\"\n"
                        f"  기존: \"{recent_hook[:60]}...\""
                    )
                    seen_pairs.add(pair)
                    break

        return warnings

    def check_pack(self, pack, lookback_days: int = 14) -> list[str]:
        """ContentPack 전체 확인. style_warnings에 추가할 항목 반환."""
        texts = [
            *pack.main_posts,
            pack.short_version,
            *pack.quote_post_drafts,
        ]
        return self.check_texts(texts, lookback_days)

    def _get_recent_hooks(self, days: int) -> list[str]:
        """최근 승인/게시된 초안의 훅 텍스트 목록."""
        try:
            from app.models.content import Draft, ApprovalStatus
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows = (
                self.db.query(Draft.hook)
                .filter(
                    Draft.approval_status.in_([
                        ApprovalStatus.APPROVED,
                        ApprovalStatus.PUBLISHED,
                    ]),
                    Draft.created_at >= cutoff,
                    Draft.hook.isnot(None),
                )
                .limit(60)
                .all()
            )
            return [r.hook for r in rows if r.hook]
        except Exception as e:
            logger.warning(f"RepetitionGuard DB 조회 실패 (무시): {e}")
            return []


# ─── 유틸 ─────────────────────────────────────────────────────────────────────

def _extract_hook(text: str) -> str:
    """텍스트의 첫 줄(훅)만 추출. 없으면 전체 반환."""
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else text.strip()


def _jaccard(a: str, b: str) -> float:
    """토큰 수준 Jaccard 유사도."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    # 불용어 제거 (영어 기준)
    stopwords = {"the", "a", "an", "is", "it", "in", "of", "to", "and", "for", "on", "at"}
    tokens_a -= stopwords
    tokens_b -= stopwords
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
