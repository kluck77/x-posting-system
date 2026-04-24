-- Phase youtube: yt_quotes 테이블
-- 모듈 내 save_quotes_to_db 가 동적 CREATE TABLE IF NOT EXISTS 로 자동 생성.
-- 본 SQL 은 수동 적용용 보조.

CREATE TABLE IF NOT EXISTS yt_quotes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_hash        TEXT UNIQUE,
    text              TEXT NOT NULL,
    speaker           TEXT,
    channel           TEXT,
    video_id          TEXT,
    video_title       TEXT,
    timestamp         TEXT,
    timestamp_sec     INTEGER,
    topic_tag         TEXT,
    importance_score  INTEGER,
    context_before    TEXT,
    context_after     TEXT,
    url               TEXT,
    used              INTEGER DEFAULT 0,
    extracted_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_yt_video
    ON yt_quotes(video_id, timestamp_sec);

CREATE INDEX IF NOT EXISTS idx_yt_used
    ON yt_quotes(used, importance_score DESC);
