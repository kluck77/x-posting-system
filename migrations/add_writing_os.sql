-- Phase 4 — Writing OS v1
-- 7원칙 + 자료 신선도 + 7원칙 채점 게이트
-- 모듈 내부에서 IF NOT EXISTS 자동 생성. 본 SQL 은 수동 적용용.

-- 7 아키타입 DNA 룰 비활성화 (과최적화)
UPDATE pattern_rules
SET enabled = 0,
    notes = '7 아키타입 DNA 폐기 (writing-os-v1)'
WHERE rule_code LIKE 'ARCHETYPE_%';

-- 기존 28규칙 중 7원칙과 충돌하는 것 비활성화 (있으면 적용)
UPDATE pattern_rules
SET enabled = 0,
    notes = '7원칙으로 흡수됨 (writing-os-v1)'
WHERE rule_code IN (
    'HOOK_PATTERN_OLD',
    'FORBIDDEN_NATURAL_VERB'
);

-- Writing OS v1 — 7원칙 룰 시드 (W1~W7)
INSERT OR IGNORE INTO pattern_rules
    (rule_code, rule_kind, rule_text, weight)
VALUES
('W1_hook_pattern',   'positive', '첫 문장 좌표/모순/임계값/선언', 3.0),
('W2_no_invention',   'safety',   '사실·인물·감정·수치 발명 금지', 5.0),
('W3_scene_convert',  'positive', '장면화=팩트 재배열만',           2.0),
('W4_date_policy',    'safety',   '자료 날짜 정책 준수',            4.0),
('W5_primary_source', 'safety',   '1차 출처 의무',                  3.0),
('W6_nut_graf',       'positive', '마지막 줄 nut graf',             2.0),
('W7_follow_reason',  'positive', '팔로우 이유 = 정보+해석+다음',    2.0);

-- writing_scores 테이블 (draft / post_id 별 채점 결과 영속)
CREATE TABLE IF NOT EXISTS writing_scores (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      TEXT,
    draft_id     INTEGER,
    scored_at    TEXT,
    w1_hook      INTEGER DEFAULT 0,
    w2_safe      INTEGER DEFAULT 0,
    w3_scene     INTEGER DEFAULT 0,
    w4_date      INTEGER DEFAULT 0,
    w5_source    INTEGER DEFAULT 0,
    w6_nut       INTEGER DEFAULT 0,
    w7_follow    INTEGER DEFAULT 0,
    forbidden    INTEGER DEFAULT 0,
    overall      INTEGER DEFAULT 0,
    pass_gate    INTEGER DEFAULT 0,
    issues       TEXT
);

CREATE INDEX IF NOT EXISTS idx_scores_draft
    ON writing_scores(draft_id);

CREATE INDEX IF NOT EXISTS idx_scores_post
    ON writing_scores(post_id);
