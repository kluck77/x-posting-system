"""패턴 DB 헬퍼 — posting_patterns 저장 + rule_score 자동 채점.

발행한 포스트(운영자가 X에 수동 발행 후 등록)를 14개 긍정 룰 기반으로
0~14 점수화. feedback_loop 가 이 데이터로 룰 가중치 재계산.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python <3.9 fallback (이론상 미도달)
    ZoneInfo = None  # type: ignore

from app.config import settings

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul") if ZoneInfo else None


def _sqlite_path() -> str:
    """프로젝트 표준 DB 경로."""
    url = settings.database_url or ""
    m = re.match(r"sqlite:///(.+)", url)
    return m.group(1) if m else "./x_poster.db"


RE_HASHTAG = re.compile(r"#\S+")
RE_URL = re.compile(r"https?://\S+")
RE_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF]"
)
RE_NUMBER = re.compile(r"\d")

_KOREA_KEYWORDS = ("한국", "원화", "코스피", "김프", "한은", "원달러")
_METAPHOR_KEYWORDS = ("굴삭기", "현장", "시동", "진동", "삽질")


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_benchmarks (
            account_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            handle            TEXT NOT NULL UNIQUE,
            display_name      TEXT,
            category          TEXT,
            follower_count    INTEGER,
            follower_updated  TEXT,
            avg_likes_30d     REAL,
            avg_rt_30d        REAL,
            avg_replies_30d   REAL,
            avg_bookmarks_30d REAL,
            avg_weighted_er   REAL,
            notes             TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posting_patterns (
            post_id              TEXT PRIMARY KEY,
            account_id           INTEGER,
            posted_at_kst        TEXT NOT NULL,
            slot                 TEXT,
            weekday              INTEGER,
            text                 TEXT NOT NULL,
            char_count           INTEGER,
            first_line_chars     INTEGER,
            line_count           INTEGER,
            has_external_link    INTEGER DEFAULT 0,
            has_self_thread      INTEGER DEFAULT 0,
            self_thread_count    INTEGER DEFAULT 0,
            hook_type            TEXT,
            has_number           INTEGER DEFAULT 0,
            has_metaphor         INTEGER DEFAULT 0,
            emoji_count          INTEGER DEFAULT 0,
            hashtag_count        INTEGER DEFAULT 0,
            bookmark_cta         INTEGER DEFAULT 0,
            rule_score           INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS er_history (
            snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id           TEXT NOT NULL,
            snapshot_at       TEXT NOT NULL,
            minutes_since     INTEGER,
            impressions       INTEGER,
            likes             INTEGER,
            retweets          INTEGER,
            replies           INTEGER,
            quotes            INTEGER,
            bookmarks         INTEGER,
            weighted_er       REAL,
            er_per_impression REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_rules (
            rule_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_code      TEXT NOT NULL UNIQUE,
            rule_kind      TEXT NOT NULL,
            rule_text      TEXT NOT NULL,
            weight         REAL DEFAULT 1.0,
            enabled        INTEGER DEFAULT 1,
            last_eval_at   TEXT,
            sample_size    INTEGER DEFAULT 0,
            avg_lift_24h   REAL,
            notes          TEXT
        )
    """)


def score_text(text: str) -> dict:
    """14개 긍정 룰 자동 채점."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    first = lines[0] if lines else ""
    last = lines[-1] if lines else ""
    full = text or ""

    has_url = bool(RE_URL.search(full))
    has_num = bool(RE_NUMBER.search(full))
    emoji_n = len(RE_EMOJI.findall(full))
    hashtag_n = len(RE_HASHTAG.findall(full))
    has_metaphor = any(k in full for k in _METAPHOR_KEYWORDS)
    bookmark_cta = "북마크" in full
    polymarket = (
        "폴리마켓" in full
        or "polymarket" in full.lower()
        or "%" in full
    )

    # raw 메타
    metrics = {
        "char_count":        len(full),
        "first_line_chars":  len(first),
        "line_count":        len(lines),
        "hashtag_count":     hashtag_n,
        "emoji_count":       emoji_n,
        "has_external_link": int(has_url),
        "has_number":        int(has_num),
        "has_metaphor":      int(has_metaphor),
        "bookmark_cta":      int(bookmark_cta),
        "has_self_thread":   0,    # 발행 후 업데이트
        "self_thread_count": 0,
    }

    # 14개 긍정 룰 자동 채점 (0/1 합 = 0~14)
    rule_score = sum([
        int(35 <= len(first) <= 50),                          # C1
        int(bool(RE_NUMBER.search(first))),                   # C2 충격수치
        int(len(lines) >= 2 and lines[1].strip() == "" if len(text.splitlines()) >= 2 else 0),  # C3
        int(4 <= len(lines) <= 8),                            # C4
        int(any(k in last for k in _KOREA_KEYWORDS)),         # C5
        int(not has_url),                                     # C6
        0,                                                    # C7 self_thread (발행 후)
        int(has_num),                                         # C8
        int(has_metaphor),                                    # C9
        int(len(lines) >= 2 and bool(first.strip()) and bool(last.strip())),  # C10
        int(emoji_n <= 1),                                    # C11
        int(hashtag_n <= 1),                                  # C12
        int(bookmark_cta),                                    # C13
        int(polymarket),                                      # C14
    ])
    metrics["rule_score"] = rule_score
    return metrics


def save_post(post_id: str, text: str, slot: str = "") -> None:
    """발행한 포스트를 DB에 저장 (운영자 수동 등록 후 호출)."""
    if not post_id or not text:
        logger.warning("[PatternDB] save_post: post_id/text 비어있음")
        return
    m = score_text(text)
    now = datetime.now(KST) if KST else datetime.utcnow()
    now_kst = now.isoformat()
    weekday = now.weekday()
    try:
        conn = sqlite3.connect(_sqlite_path())
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR IGNORE INTO posting_patterns
            (post_id, posted_at_kst, slot, weekday, text,
             char_count, first_line_chars, line_count,
             has_external_link, has_number, has_metaphor,
             emoji_count, hashtag_count, bookmark_cta,
             rule_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            post_id, now_kst, slot, weekday, text,
            m["char_count"], m["first_line_chars"], m["line_count"],
            m["has_external_link"], m["has_number"], m["has_metaphor"],
            m["emoji_count"], m["hashtag_count"], m["bookmark_cta"],
            m["rule_score"],
        ))
        conn.commit()
        conn.close()
        logger.info(
            f"[PatternDB] 저장: {post_id} rule_score={m['rule_score']}/14"
        )
    except Exception as e:
        logger.warning(f"[PatternDB] save_post 실패: {e}")


def get_active_rules() -> list[dict]:
    """활성 룰 목록 반환 (가중치 절댓값 큰 순)."""
    try:
        conn = sqlite3.connect(_sqlite_path())
        _ensure_tables(conn)
        cur = conn.execute("""
            SELECT rule_code, rule_kind, rule_text, weight
            FROM pattern_rules
            WHERE enabled = 1
            ORDER BY ABS(weight) DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "code":   r[0],
                "kind":   r[1],
                "text":   r[2],
                "weight": float(r[3] or 0),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[PatternDB] get_active_rules 실패: {e}")
        return []
