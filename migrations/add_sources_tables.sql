-- Phase polymarket + youtube: 신규 소스 테이블
-- 각 모듈이 동적 CREATE TABLE IF NOT EXISTS 도 하므로 본 SQL 은 수동 적용용 보조.

CREATE TABLE IF NOT EXISTS polymarket_markets (
    condition_id  TEXT PRIMARY KEY,
    question      TEXT,
    slug          TEXT,
    yes_prob      REAL,
    no_prob       REAL,
    volume_24h    REAL,
    liquidity     REAL,
    end_date      TEXT,
    category      TEXT,
    change_24h    REAL DEFAULT 0,
    fetched_at    REAL
);

CREATE TABLE IF NOT EXISTS yt_highlights (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    channel        TEXT,
    video_id       TEXT,
    timestamp      TEXT,
    timestamp_sec  INTEGER,
    text           TEXT,
    url            TEXT,
    is_risky       INTEGER DEFAULT 0,
    fetched_at     REAL,
    used           INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_poly_category
    ON polymarket_markets(category, volume_24h DESC);

CREATE INDEX IF NOT EXISTS idx_yt_used
    ON yt_highlights(used, fetched_at DESC);
