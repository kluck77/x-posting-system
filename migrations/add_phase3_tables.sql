-- Phase 3: 경쟁자 모니터링 + A/B 훅 선택 로그
-- 모듈 내 save_to_db / log_choice 가 동적 CREATE TABLE IF NOT EXISTS
-- 로 자동 생성하므로 이 SQL 은 수동 적용용 보조 (운영자가 한 번 실행).

CREATE TABLE IF NOT EXISTS competitor_posts (
    post_id        TEXT PRIMARY KEY,
    account        TEXT NOT NULL,
    content        TEXT,
    hook_type      TEXT,
    noun_keywords  TEXT,
    is_viral       INTEGER DEFAULT 0,
    fetched_at     REAL
);

CREATE TABLE IF NOT EXISTS ab_choices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id      TEXT,
    choice       TEXT,
    tone         TEXT,
    category     TEXT,
    viral_score  INTEGER,
    chosen_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_competitor_account
    ON competitor_posts(account, fetched_at);

CREATE INDEX IF NOT EXISTS idx_ab_choice
    ON ab_choices(choice, tone, category);
