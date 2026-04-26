-- Phase rule-simplification (2026.04)
-- 170+ 룰 → 6 룰 (안전 3 + 글쓰기 3) 으로 축소.
-- 모든 기존 룰 enabled=0, S1~S3/W1~W3 6개만 활성화.

-- 기존 활성 룰 전부 비활성화
UPDATE pattern_rules
SET enabled = 0,
    notes = '룰 대폭 축소 v2 (2026.04 rule-simplification)'
WHERE enabled = 1;

-- 6개 핵심 룰 시드 (이미 있으면 weight/enabled 만 갱신)
INSERT INTO pattern_rules
    (rule_code, rule_kind, rule_text, weight, enabled)
VALUES
    ('S1_no_invention',    'safety',  '사실·인용·수치 발명 금지',  5.0, 1),
    ('S2_no_solicitation', 'safety',  '매수·매도·투자 권유 금지',  5.0, 1),
    ('S3_no_conspiracy',   'safety',  '음모론·허위정보 차단',       5.0, 1),
    ('W1_strong_opener',   'writing', '첫 줄 멈추는 힘 (참고용)',   1.0, 1),
    ('W2_show_dont_tell',  'writing', '설명 말고 보여줘라 (참고용)', 1.0, 1),
    ('W3_nut_graf',        'writing', '마지막 줄에 의미 (참고용)',  1.0, 1)
ON CONFLICT(rule_code) DO UPDATE SET
    rule_kind  = excluded.rule_kind,
    rule_text  = excluded.rule_text,
    weight     = excluded.weight,
    enabled    = 1,
    notes      = '룰 대폭 축소 v2 활성 (2026.04)';
