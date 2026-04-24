-- Phase youtube: yt_quotes (v1 레거시) + yt_transcripts (v2 현행)
-- 두 테이블 모두 모듈 내부 IF NOT EXISTS 로 자동 생성되며
-- 본 SQL 은 수동 적용용 참조.

-- v1: yt_quotes (발언 단위 — 레거시 호환용)
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


-- v2: yt_transcripts (영상 단위 전체 자막 — 현행)
CREATE TABLE IF NOT EXISTS yt_transcripts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       TEXT UNIQUE,
    url            TEXT,
    channel        TEXT,
    speaker        TEXT,
    full_text      TEXT,
    summary        TEXT,
    duration_min   INTEGER,
    extracted_at   REAL,
    used           INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_yt_transcripts_video_id
    ON yt_transcripts(video_id);
