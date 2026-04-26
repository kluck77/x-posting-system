-- Phase 1: 심리학 업그레이드용 보조 테이블
-- 메인 파이프라인은 editorial_meta JSON 에 저장하지만, 추후 분석/대시보드용
-- 영속화를 위해 별도 테이블 신설.

CREATE TABLE IF NOT EXISTS news_classifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    title_hash  TEXT NOT NULL,
    importance  INTEGER,
    category    TEXT,
    decay_hours INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tone_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_hash  TEXT NOT NULL,
    tone        TEXT,
    confidence  REAL,
    source      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_title_hash
    ON news_classifications(title_hash);
