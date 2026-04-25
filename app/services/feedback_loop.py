"""주간 피드백 루프 — 일요일 23:00 KST 자동 실행.

지난 7일 발행 글의 24시간 가중 ER 데이터로 룰 가중치 자동 재계산.
샘플 < 5건이면 skip. lift 지속 마이너스면 룰 자동 비활성화.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import statistics
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

from app.config import settings

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul") if ZoneInfo else None


def _sqlite_path() -> str:
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


def _now_kst() -> datetime:
    return datetime.now(KST) if KST else datetime.utcnow()


def reweight_rules() -> None:
    """지난 7일 24h ER 기반 룰 가중치 재계산.

    각 룰별 lift = (룰 만족 그룹 평균 ER) / (불만족 그룹 평균 ER) - 1.
    새 가중치 = clamp(기존 + 0.5 × lift, [-3, +5]).
    weight < -1.5 면 enabled=0 으로 자동 비활성화.
    """
    cutoff = (_now_kst() - timedelta(days=7)).isoformat()
    try:
        conn = sqlite3.connect(_sqlite_path())
        from app.services.pattern_db import _ensure_tables
        _ensure_tables(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT pp.post_id,
                   pp.first_line_chars,
                   pp.line_count,
                   pp.has_external_link,
                   pp.self_thread_count,
                   pp.has_number,
                   pp.has_metaphor,
                   pp.hashtag_count,
                   pp.emoji_count,
                   pp.bookmark_cta,
                   eh.weighted_er
            FROM posting_patterns pp
            JOIN er_history eh
              ON eh.post_id = pp.post_id
             AND eh.minutes_since = 1440
            WHERE pp.posted_at_kst >= ?
        """, (cutoff,)).fetchall()
    except Exception as e:
        logger.warning(f"[FeedbackLoop] DB 조회 실패: {e}")
        return

    if len(rows) < 5:
        logger.info(
            f"[FeedbackLoop] 샘플 부족 ({len(rows)}/5) — skip"
        )
        try:
            conn.close()
        except Exception:
            pass
        return

    def lift(predicate) -> float | None:
        on  = [r["weighted_er"] for r in rows if predicate(r)]
        off = [r["weighted_er"] for r in rows if not predicate(r)]
        if len(on) < 2 or len(off) < 2:
            return None
        on_avg = statistics.mean(on)
        off_avg = statistics.mean(off) or 1.0
        return (on_avg / off_avg) - 1.0

    rule_lifts = {
        "C1_first_line_50ch":     lift(lambda r: 35 <= (r["first_line_chars"] or 0) <= 50),
        "C4_body_4_6_lines":      lift(lambda r: 4 <= (r["line_count"] or 0) <= 8),
        "C6_no_ext_link_body":    lift(lambda r: r["has_external_link"] == 0),
        "C7_self_thread_2_3":     lift(lambda r: 2 <= (r["self_thread_count"] or 0) <= 3),
        "C8_number_timestamped":  lift(lambda r: r["has_number"] == 1),
        "C9_identity_metaphor":   lift(lambda r: r["has_metaphor"] == 1),
        "C12_hashtag_0_1":        lift(lambda r: (r["hashtag_count"] or 0) <= 1),
        "C13_bookmark_cta":       lift(lambda r: r["bookmark_cta"] == 1),
        "N2_no_body_link":        lift(lambda r: r["has_external_link"] == 0),
        "N3_no_3hashtag":         lift(lambda r: (r["hashtag_count"] or 0) < 3),
    }

    now_iso = _now_kst().isoformat()
    updated = 0
    deactivated = 0
    try:
        for rule_code, l in rule_lifts.items():
            if l is None:
                continue
            conn.execute("""
                UPDATE pattern_rules
                SET weight = MAX(-3.0, MIN(5.0, weight + 0.5 * ?)),
                    last_eval_at = ?,
                    avg_lift_24h = ?,
                    sample_size = ?
                WHERE rule_code = ?
            """, (l, now_iso, round(l, 4), len(rows), rule_code))
            updated += 1
            cur = conn.execute("""
                UPDATE pattern_rules
                SET enabled = 0
                WHERE rule_code = ?
                  AND weight < -1.5
            """, (rule_code,))
            if cur.rowcount > 0:
                deactivated += 1
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[FeedbackLoop] 업데이트 실패: {e}")
        return

    logger.info(
        f"[FeedbackLoop] 룰 재가중치 완료 — {updated}개 업데이트 / "
        f"{deactivated}개 비활성화 (샘플 {len(rows)}개)"
    )
