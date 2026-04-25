-- Phase quality-95: 패턴 DB + ER 시계열 + 룰셋
-- 모든 테이블 모듈 내부에서도 IF NOT EXISTS 자동 생성. 본 SQL 은 수동 적용용.

-- 경쟁계정 벤치마크
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
);

-- 발행한 모든 포스트 (운영자 수동 등록)
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
    rule_score           INTEGER DEFAULT 0,
    FOREIGN KEY (account_id) REFERENCES account_benchmarks(account_id)
);

CREATE INDEX IF NOT EXISTS idx_patterns_slot
    ON posting_patterns(slot);
CREATE INDEX IF NOT EXISTS idx_patterns_kst
    ON posting_patterns(posted_at_kst);

-- ER 시계열 스냅샷 (T+30분 / T+24시간 / T+7일)
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
    er_per_impression REAL,
    FOREIGN KEY (post_id) REFERENCES posting_patterns(post_id)
);

CREATE INDEX IF NOT EXISTS idx_er_post
    ON er_history(post_id);

-- 패턴 룰셋 (24개 시드 + 피드백 루프 자동 가중치)
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
);

INSERT OR IGNORE INTO pattern_rules
    (rule_code, rule_kind, rule_text, weight)
VALUES
('C1_first_line_50ch',    'positive','첫 줄 35~50자 키워드 2개 이상',2.0),
('C2_first_line_shock',   'positive','첫 줄 충격수치 또는 시점 못박기',2.0),
('C3_blank_second_line',  'positive','둘째 줄 빈 줄 삽입',1.0),
('C4_body_4_6_lines',     'positive','본문 4~6줄 각 30~80자',1.5),
('C5_last_korea_stake',   'positive','마지막 줄 한국 시장 연결',2.0),
('C6_no_ext_link_body',   'positive','외부 링크는 셀프 답글에만',3.0),
('C7_self_thread_2_3',    'positive','셀프 답글 2~3개 스레드',2.5),
('C8_number_timestamped', 'positive','숫자에 한국시간 명시',1.5),
('C9_identity_metaphor',  'positive','굴삭기·현장 정체성 비유 1개',1.0),
('C10_conclusion_bookend','positive','결론 첫 줄·마지막 줄 양쪽',1.0),
('C11_emoji_0_1',         'positive','이모지 0~1개',0.5),
('C12_hashtag_0_1',       'positive','해시태그 0~1개',0.5),
('C13_bookmark_cta',      'positive','가치형 글에 북마크 1줄',1.0),
('C14_polymarket_odds',   'positive','Polymarket odds 1개 이상 인용',1.5),
('N1_no_diary',           'negative','1인칭 일상 금지',-2.0),
('N2_no_body_link',       'negative','본문 외부링크 금지',-3.0),
('N3_no_3hashtag',        'negative','해시태그 3개 이상 금지',-2.0),
('N4_no_burst',           'negative','5분 안 3개 이상 포스팅 금지',-2.0),
('N5_no_rt_beg',          'negative','RT 부탁 노골적 요청 금지',-2.5),
('N6_no_dump',            'negative','결론 없는 시황 나열 금지',-1.5),
('N7_no_keyword_miss',    'negative','첫 줄 키워드 부재 금지',-2.0),
('N8_no_kk_serious',      'negative','진지한 글에 ㅋㅋ/ㅎㅎ 금지',-1.0),
('N9_no_afk_30min',       'negative','발행 후 첫 30분 자리 비움 금지',-2.5),
('N10_no_conclusion_miss','negative','결론 없이 사실 나열만 금지',-1.5);
