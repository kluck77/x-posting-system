-- Phase ops-automation
--   posted_tweets : 발행 후 ER 추적 대상 (운영자 등록)
--   post_metrics  : 1h / 6h / 24h ER 스냅샷
--   api_costs     : 영속 비용 기록 (cost_monitor 사용)
-- 모듈 내부에서도 IF NOT EXISTS 로 자동 생성. 본 SQL 은 수동 적용용.

CREATE TABLE IF NOT EXISTS posted_tweets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id         TEXT UNIQUE,
    draft_id         INTEGER,
    posted_at        REAL,
    measure_complete INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS post_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id        TEXT,
    snapshot_type   TEXT,                -- 1h / 6h / 24h
    impressions     INTEGER,
    likes           INTEGER,
    replies         INTEGER,
    retweets        INTEGER,
    bookmarks       INTEGER,
    profile_visits  INTEGER,
    engagement_rate REAL,
    measured_at     REAL
);

CREATE TABLE IF NOT EXISTS api_costs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider      TEXT,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    called_at     REAL
);

CREATE INDEX IF NOT EXISTS idx_metrics_tweet
    ON post_metrics(tweet_id, snapshot_type);

CREATE INDEX IF NOT EXISTS idx_costs_month
    ON api_costs(called_at, provider);

CREATE INDEX IF NOT EXISTS idx_posted_pending
    ON posted_tweets(measure_complete, posted_at);
