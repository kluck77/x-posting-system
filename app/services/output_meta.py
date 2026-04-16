"""
출력 메타데이터 빌더
===================
PR 9 (Reader Reward) / PR 10 (Findability) / PR 17 (Entity Alias) /
PR 12D (Market/Stake) / PR 12E (Evaluation) / PR 15 (Learning) /
PR 18 (Outcome Capture) / PR 20 (Distribution Package)

content_pack.py 에서 분리. 로직 변경 없음.
"""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.content_pack import FinalPost, CandidateCard

# ─── PR 9: Reader Reward Layer ────────────────────────────────────────────
#
# 독자 보상 시그널 = 마지막 문장에서 "왜 저장/공유/팔로우해야 하는지"가 드러
# 나는 표현. 결정론 키워드 매칭으로 3유형 중 하나로 태깅한다.
#
# - SAVE   : 앞으로 비슷한 사안을 판단할 때 참조할 프레임/기준점
# - SHARE  : 간명한 한 줄로 바로 나눌 수 있는 단언
# - FOLLOW : 후속 데이터/발표 시 다시 돌아올 이유 (검증 조건 포함)
#
# VERIFY 템플릿 A/B/C 예시 끝줄("검증 가능" / "살아 있다" / "수사에 가깝다"
# / "그쳤다")은 전부 FOLLOW 계열로 이미 잡힘 → VERIFY 안전성 훼손 없음.
_REWARD_FOLLOW_PATTERNS = [
    "이 나오면",
    "이 공개되면",
    "이 포착되면",
    "가 나오면",
    "가 공개되면",
    "가 포착되면",
    "이 이어지면",
    "가 이어지면",
    "가 드러난다",
    "진짜가 드러난다",
    "후속 데이터",
    "후속 발표",
    "다음 발표",
    "다음 공식",
    "다음 CPI",
    "다음 지표",
    "다음 집계",
    "다음 숫자",
    "추적",
    "검증 가능",
    "확인 가능",
    # 질문형 FOLLOW — "~느냐/는지/될지" 로 닫는 후속 관측 질문.
    # 관건은 ~느냐다 계열은 SAVE marker + FOLLOW closure 겸용이지만
    # 여기선 FOLLOW 로 태깅 (다음 지켜볼 질문이 더 강한 축).
    "느냐다",
    "는지다",
    "될지다",
    "느냐에",
    "는지에",
    # VERIFY 템플릿 B/C 예시 끝줄 — FOLLOW 로 태깅
    "살아 있다",
    "수사에 가깝다",
    "그쳤다",
    "얼 수 있다",
    # 조건부 결과 ("X면 Y 줄어든다/늘어난다/오른다/떨어진다/바뀐다")
    "면 줄어든다",
    "면 늘어난다",
    "면 오른다",
    "면 떨어진다",
    "면 바뀐다",
    "면 갈린다",
    "면 맞는",
]

# SAVE 강한 마커 — 문장에 있으면 FOLLOW 신호와 겹쳐도 SAVE 우선.
# "답은 다음 CPI가 기준이다" 처럼 SAVE marker + FOLLOW 소재 공존 시
# 독자 의도가 '기준점 저장' 쪽이므로 SAVE 태깅이 맞다.
_REWARD_SAVE_STRONG_PATTERNS = [
    "답은 ",
    "결국 먼저 ",
    "먼저 봐야 할 건",
    "먼저 맞는 건",
    "먼저 움직",
    "입금 시점",
    "입금이 먼저",
]

# SAVE 약한 마커 — FOLLOW 와 겹치면 FOLLOW 우선.
_REWARD_SAVE_WEAK_PATTERNS = [
    "핵심은 ",
    "진짜 ",
]

_REWARD_SHARE_PATTERNS = [
    "말보다 숫자가",
    "말보다 출처가",
    "주장보다 출처",
    "주장보다 원본",
    "발표보다 원본",
    "발표보다 데이터",
    "보다 숫자가 먼저",
    "보다 출처가 먼저",
    "그냥 SNS 주장",
    "그냥 주장이다",
    "출처가 안 나오면",
    "원본 데이터가 먼저",
]

# 마지막 문장 전용 — 닫힌 분석가 마감 phrase. reward 시그널 없이 이걸로 끝나면
# NO_READER_REWARD (WARN-only) 를 강하게 찍는다. "기준이다" 도 여기 포함:
# reward 키워드가 같은 문장에 있으면 허용, 없으면 경고.
_CLOSED_ANALYST_LAST_LINE = [
    "기준이다",
    "변수다",
    "핵심 변수다",
    "파장이다",
    "대목이다",
    "쟁점이다",
]


def _extract_last_sentence(text: str) -> str:
    """post 에서 마지막 문장만 뽑는다. 마침표/줄바꿈 기준."""
    if not text:
        return ""
    t = text.strip().rstrip(".!?")
    # 줄바꿈과 마침표 둘 다 splitter 로 취급
    normalized = t.replace("\n", ".")
    parts = [p.strip() for p in normalized.split(".") if p.strip()]
    if not parts:
        return ""
    return parts[-1]


def _detect_reward_type(text: str) -> Optional[str]:
    """
    텍스트에서 독자 보상 시그널을 찾아 'SAVE'/'SHARE'/'FOLLOW'/None 반환.

    결정론. AI 호출 없음. 체크 순서:
      1. SAVE 강한 마커 ("답은 ", "결국 먼저 " 등) — 최우선
         → "답은 다음 CPI가 기준이다" 처럼 FOLLOW 와 겹쳐도 SAVE.
      2. FOLLOW 시그널 (VERIFY 템플릿 포함해 가장 일반적)
      3. SAVE 약한 마커 ("핵심은 ", "진짜 ")
      4. SHARE 시그널
    """
    if not text:
        return None
    for pat in _REWARD_SAVE_STRONG_PATTERNS:
        if pat in text:
            return "SAVE"
    for pat in _REWARD_FOLLOW_PATTERNS:
        if pat in text:
            return "FOLLOW"
    for pat in _REWARD_SAVE_WEAK_PATTERNS:
        if pat in text:
            return "SAVE"
    for pat in _REWARD_SHARE_PATTERNS:
        if pat in text:
            return "SHARE"
    return None


def _validate_last_line_reward(
    post: str,
    short: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    PR 9 — 마지막 줄 독자 보상 검사.

    판정 우선순위 (사용자 지시):
      1. final_post 마지막 문장 → reward_type 잡히면 그걸로 확정.
      2. final_post 에 reward 없을 때만 final_short 보조로 본다.
      3. 둘 다 reward 없을 때만 NO_READER_REWARD 경고 발생.

    반환: (reward_type, warn_reason)
      reward_type : "SAVE"|"SHARE"|"FOLLOW"|None
      warn_reason : None 또는 NO_READER_REWARD 사유 문자열

    주의: 경고는 WARN-only. _STRONG_FAIL_TAGS 에 넣지 말 것. 재생성 루프
    유발 금지.
    """
    if not post:
        return None, None

    last_sent = _extract_last_sentence(post)

    # 1차: post 마지막 문장
    reward = _detect_reward_type(last_sent)
    if reward is not None:
        return reward, None

    # 2차 (보조): short 전체
    if short:
        reward_s = _detect_reward_type(short)
        if reward_s is not None:
            return reward_s, None

    # 3차: closed analyst last-line 이면 강한 사유 부여, 아니면 일반 사유
    last_clean = last_sent.rstrip(".!?").rstrip()
    for pat in _CLOSED_ANALYST_LAST_LINE:
        if last_clean.endswith(pat):
            return None, (
                f"마지막 문장 '{pat}' — 독자 보상(SAVE/SHARE/FOLLOW) 시그널 없음"
            )

    return None, "마지막 문장에 독자 보상(SAVE/SHARE/FOLLOW) 시그널 없음"


def _resolve_reward_type(post: str, short: str) -> Optional[str]:
    """FinalPost.reward_type 계산 — post 마지막 문장 우선, short 보조.

    _validate_last_line_reward 가 경고 판정에만 쓰이므로,
    reward_type 필드 주입은 이 헬퍼로 분리해 재사용한다.
    """
    last_sent = _extract_last_sentence(post)
    rt = _detect_reward_type(last_sent)
    if rt is not None:
        return rt
    if short:
        return _detect_reward_type(short)
    return None


# ─── PR 10: Findability Layer ─────────────────────────────────────────────
#
# 첫 2문장 안에 "검색 가능한 구체 앵커"(숫자/영문 약어/고유명사) 가 충분히
# 있는지 휴리스틱으로 검사한다.  v1 은 WARN-only — _STRONG_FAIL_TAGS 미편입.
#
# 앵커 ≥ 2 → 통과,  1 → 경고만,  0 → LOW_FINDABILITY gate tag + 경고.

_FINDABILITY_KNOWN_ENTITIES = [
    # 한국 주요 기업/브랜드
    "삼성", "현대", "기아", "포스코", "카카오", "네이버", "쿠팡", "롯데",
    "한화", "두산", "신한", "하나", "우리", "토스",
    # 한국 정부/기관
    "국세청", "관세청", "금감원", "한국은행", "기재부", "산자부", "국방부",
    "외교부", "통일부", "과기부", "교육부", "환경부", "법무부", "행안부",
    "대통령", "국회", "여당", "야당", "헌법재판소", "대법원", "검찰",
    # 국가
    "미국", "중국", "일본", "러시아", "북한", "우크라이나", "이란",
    "대만", "사우디", "인도", "독일", "영국", "프랑스", "호주",
    # 한국 도시/지역
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "제주",
    "강남", "강북", "서초", "송파", "여의도", "판교",
    # 주요 인물 (검색 빈도 높은)
    "트럼프", "바이든", "시진핑", "푸틴", "젤렌스키", "윤석열", "이재명",
]

_FINDABILITY_ANCHOR_RE = re.compile(
    r"\d[\d,.]*"              # 숫자 (날짜/금액/비율)
    r"|[A-Z][A-Za-z0-9]{1,}"  # 영문 약어/티커 2자+ (CPI, GDP, KOSPI, SK)
)


# ── PR 17: Entity Alias / Query Expansion Layer ──
# 정식 명칭이 아니어도 findability anchor 로 인정.
# key=alias, value=정식 명칭 (KNOWN_ENTITIES 에 있는 것).
# 양방향: "코인게코"→"CoinGecko" 와 "CoinGecko"→"코인게코" 모두 등록 가능.
_ENTITY_ALIAS_MAP: dict[str, str] = {
    # 기업/브랜드 약칭
    "삼성전자": "삼성",
    "삼성SDI": "삼성",
    "현대차": "현대",
    "현대자동차": "현대",
    "기아차": "기아",
    "포스코홀딩스": "포스코",
    "카카오뱅크": "카카오",
    "카카오페이": "카카오",
    "네이버웹툰": "네이버",
    "라인": "네이버",
    "롯데케미칼": "롯데",
    "한화에어로스페이스": "한화",
    "두산에너빌리티": "두산",
    "신한금융": "신한",
    "하나금융": "하나",
    "우리금융": "우리",
    "토스뱅크": "토스",
    # 기관 약칭/영문
    "NTS": "국세청",
    "한은": "한국은행",
    "BOK": "한국은행",
    "금융감독원": "금감원",
    "FSS": "금감원",
    "기획재정부": "기재부",
    "MOEF": "기재부",
    "산업통상자원부": "산자부",
    "관세청": "관세청",
    "KCS": "관세청",
    # 데이터/플랫폼
    "코인게코": "CoinGecko",
    "CoinGecko": "코인게코",
    "코인마켓캡": "CoinMarketCap",
    "CoinMarketCap": "코인마켓캡",
    "CMC": "CoinMarketCap",
    # 정책/제도 약칭
    "토허제": "토지거래허가구역",
    "토지거래허가구역": "토허제",
    "DSR": "총부채원리금상환비율",
    "LTV": "주택담보대출비율",
    # 국가 약칭
    "UAE": "아랍에미리트",
    "EU": "유럽연합",
}


def _extract_first_two_sentences(text: str) -> str:
    """post 에서 첫 2문장만 뽑는다. 줄바꿈/마침표 기준."""
    if not text:
        return ""
    normalized = text.replace("\n", ".")
    parts = [p.strip() for p in normalized.split(".") if p.strip()]
    return ". ".join(parts[:2])


def _count_findability_anchors(text: str) -> int:
    """텍스트에서 검색 가능한 구체 앵커(숫자/약어/고유명사) 수를 센다.

    PR 17: alias 사전도 anchor 로 인정 — alias 키가 텍스트에 있으면
    정식 명칭을 anchor set 에 추가.
    """
    if not text:
        return 0
    anchors: set = set()
    for m in _FINDABILITY_ANCHOR_RE.finditer(text):
        anchors.add(m.group())
    for ent in _FINDABILITY_KNOWN_ENTITIES:
        if ent in text:
            anchors.add(ent)
    # PR 17: alias 매칭
    for alias, canonical in _ENTITY_ALIAS_MAP.items():
        if alias in text:
            anchors.add(canonical)
    return len(anchors)


def _validate_findability(post: str) -> tuple[int, Optional[str]]:
    """
    PR 10 — 첫 2문장 Findability 검사.

    반환: (anchor_count, warn_reason)
      anchor_count : 감지된 구체 앵커 수
      warn_reason  : None 이면 통과, 문자열이면 경고/게이트 사유

    게이트 정책:
      anchor ≥ 2 → 통과 (None)
      anchor = 1 → 경고만 (gate tag 는 호출측에서 판단)
      anchor = 0 → LOW_FINDABILITY 사유 반환
    """
    if not post:
        return 0, None
    head = _extract_first_two_sentences(post)
    count = _count_findability_anchors(head)
    if count >= 2:
        return count, None
    if count == 1:
        return count, (
            f"첫 2문장 검색 앵커 {count}개 — "
            "고유명사/숫자/기관명/지표 최소 2개 권장"
        )
    return count, (
        "첫 2문장에 검색 가능한 고유명사/숫자/기관명/지표 없음 — "
        "추상명사만으로 시작"
    )


# ─── PR 12 Layer D: Market/Stake Layer v2 ─────────────────────────────────
#
# 최종 글이 시장/생활 반영 경로를 남기는지 점검.
# market_angle_type 필드 자동 태깅 + 마지막 2~3문장 validator.
# WARN-only — _STRONG_FAIL_TAGS 미편입.

_MARKET_ANGLE_PATTERNS: dict[str, list[str]] = {
    "COST": ["원가", "비용", "단가", "인건비", "물가", "가격 인상",
             "가격 인하", "생산 비용", "운송비"],
    "DEMAND": ["수요", "소비", "판매", "주문", "소비자", "매출",
               "구매", "고객"],
    "SUPPLY": ["공급", "생산", "가동률", "재고", "물량",
               "공급망", "납품", "수입"],
    "POLICY": ["시행", "집행", "규제", "법안", "정책", "조치",
               "제도", "시행일", "적용"],
    "FLOW": ["입금", "공시", "실적", "결산", "배당",
             "투자", "자금", "유입", "유출"],
    "CHECKPOINT": ["확인 가능", "검증 가능", "나오면", "공개되면",
                   "집계되면", "참여율", "발표 예정"],
}

_MARKET_ANGLE_VALID_TYPES = frozenset(
    list(_MARKET_ANGLE_PATTERNS.keys()) + ["NONE"]
)


def _detect_market_angle_type(
    post: str, mode: str,
) -> str:
    """
    PR 12 Layer D — 최종 post 에서 시장/생활 반영 경로 유형 감지.

    반환: COST / DEMAND / SUPPLY / POLICY / FLOW / CHECKPOINT / NONE
    VERIFY 모드에서는 CHECKPOINT 만 허용 (예언 금지 원칙).
    """
    if not post:
        return "NONE"

    # 뒤에서 3문장만 검사 (시장 시각은 본문 후반부에 위치)
    sentences = [s.strip() for s in post.replace("\n", " ").split(".") if s.strip()]
    tail = ". ".join(sentences[-3:]) if len(sentences) >= 3 else post

    best_type = "NONE"
    best_count = 0

    for angle_type, patterns in _MARKET_ANGLE_PATTERNS.items():
        if mode == "VERIFY" and angle_type not in ("CHECKPOINT", "NONE"):
            continue
        hits = sum(1 for p in patterns if p in tail)
        if hits > best_count:
            best_count = hits
            best_type = angle_type

    return best_type


def _validate_market_stake(
    post: str, mode: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    PR 12 Layer D — 마지막 2~3문장에 시장/생활 반영 표현 존재 여부 검사.

    반환: (warning_message, gate_tag)
      gate_tag 는 "NO_MARKET_STAKE" — WARN-only.
    """
    if not post:
        return None, None

    sentences = [s.strip() for s in post.replace("\n", " ").split(".") if s.strip()]
    tail = ". ".join(sentences[-3:]) if len(sentences) >= 3 else post

    # VERIFY 는 예언 금지이므로 CHECKPOINT 패턴만 검사
    if mode == "VERIFY":
        check_patterns = _MARKET_ANGLE_PATTERNS.get("CHECKPOINT", [])
    else:
        check_patterns = []
        for patterns in _MARKET_ANGLE_PATTERNS.values():
            check_patterns.extend(patterns)

    if any(p in tail for p in check_patterns):
        return None, None

    return (
        "마지막 2~3문장에 시장/생활 반영 경로 표현 없음 — "
        "'그래서 어디에 먼저 반영되나' 시각 부재",
        "NO_MARKET_STAKE",
    )


# ── PR 15: Learning Dataset Layer — 학습 데이터셋 레코드 ──

OUTCOME_ADOPTED = "ADOPTED"       # 그대로 채택
OUTCOME_MODIFIED = "MODIFIED"     # 수정 후 채택
OUTCOME_DISCARDED = "DISCARDED"   # 폐기

_VALID_OUTCOMES = frozenset({OUTCOME_ADOPTED, OUTCOME_MODIFIED, OUTCOME_DISCARDED})

# ── PR 18: Human Outcome Capture Layer — 수정 사유 표준화 ──
# 운영자가 MODIFIED 판정 시 붙이는 사유 코드.
# 자유 텍스트도 허용하되, 이 enum은 빈도 분석/필터에 사용.

MOD_REASON_ABSTRACT = "ABSTRACT"                 # 추상적 표현
MOD_REASON_NO_MARKET = "NO_MARKET_STAKE"         # 시장/생활 반영 부재
MOD_REASON_UNRESOLVED = "UNRESOLVED_QUESTION"    # 핵심 질문 미해결
MOD_REASON_WEAK_HOOK = "WEAK_HOOK"               # 훅/첫 문장 약함
MOD_REASON_LOW_FIND = "LOW_FINDABILITY"          # 검색 가능 명사 부족
MOD_REASON_SUMMARY = "TOO_SUMMARY_LIKE"          # 요약체/칼럼체
MOD_REASON_OTHER = "OTHER"                       # 기타

_VALID_MOD_REASONS = frozenset({
    MOD_REASON_ABSTRACT, MOD_REASON_NO_MARKET, MOD_REASON_UNRESOLVED,
    MOD_REASON_WEAK_HOOK, MOD_REASON_LOW_FIND, MOD_REASON_SUMMARY,
    MOD_REASON_OTHER,
})


def _validate_learning_label(
    outcome: str,
    modification_reason: str = "",
) -> list[str]:
    """
    PR 18 — outcome + modification_reason 유효성 검증.

    반환: 경고 메시지 리스트 (빈 리스트 = 통과).
    """
    warnings: list[str] = []
    if outcome and outcome not in _VALID_OUTCOMES:
        warnings.append(f"알 수 없는 outcome: {outcome}")
    if outcome == OUTCOME_MODIFIED and not modification_reason:
        warnings.append("MODIFIED 판정에 modification_reason 누락")
    if (
        modification_reason
        and modification_reason not in _VALID_MOD_REASONS
        and not modification_reason.startswith("OTHER:")
    ):
        warnings.append(
            f"비표준 modification_reason: {modification_reason} "
            f"(표준: {sorted(_VALID_MOD_REASONS)})"
        )
    return warnings


# ── PR 20: Distribution Packaging Layer ──
#
# 하나의 FinalPost 에서 3종 패키지를 규칙 기반으로 추출:
#   1. 메인 포스트  → final_post (이미 존재)
#   2. 공유형 짧은 문장 → dist_share_line
#   3. 후속 추적용 답글 → dist_follow_up

# 후속 답글 추출 신호: FOLLOW 보상의 마지막 문장이 "~면/~냐/~나오면" 등
# 조건 분기 형태이면 그대로 후속 답글로 사용.
_FOLLOW_UP_SIGNALS = [
    "나오면", "안 나오면", "되면", "된다면", "갈린다",
    "확정이다", "확정.", "확인이다", "이다.",
    "이냐다.", "느냐다.", "드러난다.",
]


def _build_distribution_package(
    final: "FinalPost",
    mode: str,
) -> tuple[str, str]:
    """
    PR 20 — 메인 포스트에서 공유형 + 후속 답글 추출.

    규칙 기반. AI 호출 없음.

    공유형 (dist_share_line):
      - final_short 이 있으면 그대로 사용
      - 없으면 final_post 첫 문장

    후속 답글 (dist_follow_up):
      - final_post 마지막 문장이 조건 분기 형태면 사용
      - 아니면 final_short 과 다른 마지막 문장 사용
      - 마지막 수단: 빈 문자열

    반환: (share_line, follow_up)
    """
    post = final.final_post or ""
    short = final.final_short or ""

    # ── share_line ──
    share_line = short if short else ""
    if not share_line and post:
        first = post.split("\n")[0].strip()
        share_line = first.split(".")[0].strip() if first else ""

    # ── follow_up ──
    follow_up = ""
    if post:
        lines = [ln.strip() for ln in post.split("\n") if ln.strip()]
        if lines:
            last_line = lines[-1]
            # 마지막 줄에서 마지막 문장 추출
            sents = [s.strip() for s in last_line.split(".") if s.strip()]
            last_sent = sents[-1] if sents else last_line

            # FOLLOW_UP_SIGNALS 에 해당하면 후속 답글로 채택
            for sig in _FOLLOW_UP_SIGNALS:
                if last_sent.endswith(sig) or last_line.endswith(sig):
                    follow_up = last_sent
                    break

            # 신호 미감지 + 2줄 이상이면 마지막 줄 자체를 답글로
            if not follow_up and len(lines) >= 2:
                candidate = lines[-1]
                # share_line 과 겹치지 않으면 사용
                if candidate != share_line:
                    follow_up = candidate

    return share_line, follow_up


# ── PR 22: Duplicate / Similarity Guard Layer ──
#
# final_post / final_short / dist_share_line / dist_follow_up 4종 간
# 유사중복 검사. 동일 게시물 내 출력물끼리 지나치게 비슷하면 X 검색
# 품질이 떨어진다 (중복 노출 → 계정 신뢰 하락).
#
# WARN-only — _STRONG_FAIL_TAGS 미편입.

_SIMILARITY_WARN_THRESHOLD = 0.70   # Jaccard ≥ 70% → 경고


def _tokenize_ko(text: str) -> set[str]:
    """한국어 텍스트를 공백 + 조사 제거 토큰 셋으로 변환."""
    if not text:
        return set()
    # 공백 분리 후 1자 이하 토큰 제거
    tokens = set()
    for tok in text.lower().replace("\n", " ").split():
        tok = tok.strip(".,!?·…\"'""''()[]{}~")
        if len(tok) > 1:
            tokens.add(tok)
    return tokens


def _jaccard_similarity(a: str, b: str) -> float:
    """두 텍스트의 Jaccard 유사도 (0.0~1.0)."""
    ta = _tokenize_ko(a)
    tb = _tokenize_ko(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _first_line(text: str) -> str:
    """텍스트의 첫 줄만 추출."""
    if not text:
        return ""
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def _validate_output_similarity(
    post: str,
    short: str,
    share_line: str = "",
    follow_up: str = "",
) -> list[str]:
    """
    PR 22 — 4종 출력물 간 유사중복 검사.

    검사 항목:
      1. final_post 첫 줄 vs final_short 첫 줄 (완전 동일)
      2. final_short vs dist_share_line (Jaccard ≥ 70%)
      3. final_post 마지막 줄 vs dist_follow_up (완전 동일)
      4. final_short vs dist_follow_up (Jaccard ≥ 70%)

    반환: 경고 목록 (WARN-only, 게이트 태그 없음)
    """
    warnings: list[str] = []

    # 1. post 첫 줄 vs short 첫 줄 — 완전 동일 체크
    # (기존 _validate_final_post에 이미 있으나 여기서 첫줄 동일도 추가 체크)
    post_first = _first_line(post)
    short_first = _first_line(short)

    # 2. short vs share_line — 유사도
    if short and share_line and short != share_line:
        sim = _jaccard_similarity(short, share_line)
        if sim >= _SIMILARITY_WARN_THRESHOLD:
            warnings.append(
                f"final_short ↔ dist_share_line 유사도 {int(sim*100)}% — "
                "공유 문구가 짧은 버전과 거의 동일"
            )

    # 3. post 마지막 줄 vs follow_up — 완전 동일
    if post and follow_up:
        post_lines = [ln.strip() for ln in post.strip().splitlines() if ln.strip()]
        if post_lines:
            last_line = post_lines[-1]
            if last_line == follow_up:
                warnings.append(
                    "dist_follow_up이 final_post 마지막 줄과 완전 동일 — "
                    "답글 차별화 필요"
                )

    # 4. short vs follow_up — 유사도
    if short and follow_up:
        sim = _jaccard_similarity(short, follow_up)
        if sim >= _SIMILARITY_WARN_THRESHOLD:
            warnings.append(
                f"final_short ↔ dist_follow_up 유사도 {int(sim*100)}% — "
                "짧은 버전과 후속 답글이 거의 동일"
            )

    # 5. post 첫 줄 vs share_line — 첫 줄 완전 복제
    if post_first and share_line:
        if post_first == share_line:
            warnings.append(
                "dist_share_line이 final_post 첫 줄의 완전 복제 — "
                "공유 문구 차별화 필요"
            )

    return warnings


# ── PR 22: Search Surface Layer ──
#
# X 검색에서 계정/게시글이 발견되려면 핵심 엔티티/키워드가
# 첫 2문장, 짧은 버전, 공유 문구에 최소 1회 이상 등장해야 한다.
# findability 가 "앵커 개수"를 세는 반면, search surface 는
# "핵심어가 어디에 빠졌는지"를 검사한다.

def _extract_surface_keywords(post: str) -> set[str]:
    """
    final_post 전체에서 검색 표면 핵심어를 추출.

    추출 대상:
      - _FINDABILITY_KNOWN_ENTITIES 에 매칭되는 고유명사
      - _ENTITY_ALIAS_MAP 의 alias 키
      - 영문 약어/티커 (2자+)
    """
    if not post:
        return set()
    keywords: set[str] = set()
    for ent in _FINDABILITY_KNOWN_ENTITIES:
        if ent in post:
            keywords.add(ent)
    for alias in _ENTITY_ALIAS_MAP:
        if alias in post:
            keywords.add(alias)
    for m in _FINDABILITY_ANCHOR_RE.finditer(post):
        tok = m.group()
        if len(tok) >= 2 and tok[0].isupper():
            keywords.add(tok)
    return keywords


def _validate_search_surface(
    post: str,
    short: str,
    share_line: str = "",
) -> list[str]:
    """
    PR 22 — 핵심 엔티티/키워드의 출력물별 등장 검사.

    post 전체에서 추출한 핵심어가 short / share_line 에도
    최소 1개 이상 남아있는지 확인한다.

    반환: 경고 목록 (WARN-only)
    """
    warnings: list[str] = []

    surface_kw = _extract_surface_keywords(post)
    if len(surface_kw) < 2:
        # 핵심어 1개 이하면 오탐 위험 — 스킵
        return warnings

    # short에 핵심어 존재 확인
    if short:
        short_hits = {kw for kw in surface_kw if kw in short}
        if not short_hits:
            warnings.append(
                f"final_short에 핵심 검색어 없음 — "
                f"post 핵심어: {sorted(surface_kw)[:3]}"
            )

    # share_line에 핵심어 존재 확인
    if share_line:
        share_hits = {kw for kw in surface_kw if kw in share_line}
        if not share_hits:
            warnings.append(
                f"dist_share_line에 핵심 검색어 없음 — "
                f"post 핵심어: {sorted(surface_kw)[:3]}"
            )

    return warnings


# ── PR 23: Offline Gold Eval Layer ──
#
# 운영자가 "좋은 글"/"나쁜 글" 기준 라벨을 붙여 품질 기준셋(gold set)을
# 축적한다. _build_learning_record 의 출력 + 사람 판정을 포함하는 상위 구조.
# DB 저장/UI 없이 dict 스키마만 정의. 호출자가 JSON 로그로 기록.

GOLD_QUALITY_GOOD = "GOOD"
GOLD_QUALITY_BAD = "BAD"
GOLD_QUALITY_BORDERLINE = "BORDERLINE"

_VALID_GOLD_QUALITIES = frozenset({
    GOLD_QUALITY_GOOD, GOLD_QUALITY_BAD, GOLD_QUALITY_BORDERLINE,
})

# 품질 판정 근거 태그 — 복수 선택 가능
GOLD_REASON_FINDABLE = "MORE_FINDABLE"
GOLD_REASON_MARKET = "BETTER_MARKET_STAKE"
GOLD_REASON_REWARD = "BETTER_REWARD"
GOLD_REASON_NOT_SUMMARY = "LESS_SUMMARY_LIKE"
GOLD_REASON_QUESTION = "BETTER_QUESTION_RESOLUTION"
GOLD_REASON_OTHER = "OTHER"

_VALID_GOLD_REASONS = frozenset({
    GOLD_REASON_FINDABLE, GOLD_REASON_MARKET, GOLD_REASON_REWARD,
    GOLD_REASON_NOT_SUMMARY, GOLD_REASON_QUESTION, GOLD_REASON_OTHER,
})


def _validate_gold_label(
    quality: str,
    reasons: list[str],
) -> list[str]:
    """
    PR 23 — gold eval 라벨 유효성 검증.

    반환: 경고 메시지 리스트 (빈 리스트 = 통과).
    """
    warnings: list[str] = []
    if quality and quality not in _VALID_GOLD_QUALITIES:
        warnings.append(f"알 수 없는 gold quality: {quality}")
    if not reasons:
        warnings.append("gold eval 판정 근거(reasons) 누락")
    for r in reasons:
        if r not in _VALID_GOLD_REASONS and not r.startswith("OTHER:"):
            warnings.append(f"비표준 gold reason: {r}")
    return warnings


def _build_gold_eval_record(
    post: str,
    short: str,
    mode: str,
    *,
    quality: str = "",
    reasons: list[str] | None = None,
    evaluator_note: str = "",
) -> dict:
    """
    PR 23 — Offline Gold Eval 레코드 빌드.

    단일 포스트에 대한 품질 기준셋 레코드.
    _build_learning_record 와 별개로 독립 dict 를 반환한다.
    호출자가 JSON 로그로 기록하거나 파일로 내보낸다.

    AI 호출 없음. rule-first.
    """
    reasons = reasons or []
    # 자동 계산 메트릭
    anchor_count, _ = _validate_findability(post)
    reward = _detect_reward_type(_extract_last_sentence(post))
    market = _detect_market_angle_type(post, mode)

    return {
        "record_type": "gold_eval",
        "quality": quality,
        "reasons": list(reasons),
        "evaluator_note": evaluator_note,
        # 자동 메트릭 스냅샷 — 나중에 기준셋 비교용
        "mode": mode,
        "post_length": len(post),
        "short_length": len(short),
        "anchor_count": anchor_count,
        "reward_type": reward,
        "market_angle_type": market,
        # 텍스트 스냅샷
        "post_snapshot": post[:200],
        "short_snapshot": short[:100],
    }


# ── PR 23: Human Pairwise Review Layer ──
#
# 동일 소스에서 생성된 2개 안(A/B)을 운영자가 비교 판정.
# A_BETTER / B_BETTER / TIE + 선택 이유 태그.
# UI 없이 dict 스키마만 정의. 호출자가 텔레그램 봇 등에서 호출.

PAIRWISE_A_BETTER = "A_BETTER"
PAIRWISE_B_BETTER = "B_BETTER"
PAIRWISE_TIE = "TIE"

_VALID_PAIRWISE_VERDICTS = frozenset({
    PAIRWISE_A_BETTER, PAIRWISE_B_BETTER, PAIRWISE_TIE,
})

# 선택 이유 — _VALID_GOLD_REASONS 와 동일 셋 재사용
_VALID_PAIRWISE_REASONS = _VALID_GOLD_REASONS


def _validate_pairwise_label(
    verdict: str,
    reasons: list[str],
) -> list[str]:
    """
    PR 23 — pairwise review 라벨 유효성 검증.

    반환: 경고 메시지 리스트 (빈 리스트 = 통과).
    """
    warnings: list[str] = []
    if verdict and verdict not in _VALID_PAIRWISE_VERDICTS:
        warnings.append(f"알 수 없는 pairwise verdict: {verdict}")
    if not verdict:
        warnings.append("pairwise verdict 누락")
    if verdict != PAIRWISE_TIE and not reasons:
        warnings.append("A_BETTER/B_BETTER 판정에 reasons 누락")
    for r in reasons:
        if r not in _VALID_PAIRWISE_REASONS and not r.startswith("OTHER:"):
            warnings.append(f"비표준 pairwise reason: {r}")
    return warnings


def _build_pairwise_review_record(
    post_a: str,
    short_a: str,
    post_b: str,
    short_b: str,
    mode: str,
    *,
    verdict: str = "",
    reasons: list[str] | None = None,
    evaluator_note: str = "",
) -> dict:
    """
    PR 23 — Human Pairwise Review 레코드 빌드.

    동일 소스의 A안/B안 비교 판정 레코드.
    AI 호출 없음. rule-first.
    """
    reasons = reasons or []

    # A안 자동 메트릭
    a_anchor, _ = _validate_findability(post_a)
    a_reward = _detect_reward_type(_extract_last_sentence(post_a))
    a_market = _detect_market_angle_type(post_a, mode)

    # B안 자동 메트릭
    b_anchor, _ = _validate_findability(post_b)
    b_reward = _detect_reward_type(_extract_last_sentence(post_b))
    b_market = _detect_market_angle_type(post_b, mode)

    return {
        "record_type": "pairwise_review",
        "verdict": verdict,
        "reasons": list(reasons),
        "evaluator_note": evaluator_note,
        "mode": mode,
        # A안
        "a_post_length": len(post_a),
        "a_short_length": len(short_a),
        "a_anchor_count": a_anchor,
        "a_reward_type": a_reward,
        "a_market_angle_type": a_market,
        "a_post_snapshot": post_a[:200],
        "a_short_snapshot": short_a[:100],
        # B안
        "b_post_length": len(post_b),
        "b_short_length": len(short_b),
        "b_anchor_count": b_anchor,
        "b_reward_type": b_reward,
        "b_market_angle_type": b_market,
        "b_post_snapshot": post_b[:200],
        "b_short_snapshot": short_b[:100],
    }


# ── PR 26: Online Production Eval Layer ──
#
# 최근 N건의 eval_meta 를 메모리 내 집계하여 품질 분포/경고를 실시간 제공.
# DB 없이 리스트 버퍼 방식. 호출자가 generate_final_post 후 feed.

_ONLINE_EVAL_BUFFER: list[dict] = []
_ONLINE_EVAL_MAX_SIZE = 100


def _feed_online_eval(eval_meta: dict) -> None:
    """
    PR 26 — eval_meta 1건을 온라인 버퍼에 적재.

    최대 _ONLINE_EVAL_MAX_SIZE 건 유지 (FIFO).
    """
    _ONLINE_EVAL_BUFFER.append(eval_meta)
    if len(_ONLINE_EVAL_BUFFER) > _ONLINE_EVAL_MAX_SIZE:
        _ONLINE_EVAL_BUFFER.pop(0)


def _get_online_eval_summary() -> dict:
    """
    PR 26 — 현재 버퍼 기준 품질 분포 요약.

    반환 dict:
      total: 버퍼 내 총 건수
      reward_type_dist: {SAVE: n, SHARE: n, FOLLOW: n, None: n}
      market_angle_dist: {COST: n, DEMAND: n, ..., NONE: n}
      mode_dist: {EXPLAIN: n, JUDGMENT: n, VERIFY: n}
      avg_strong_fail: 평균 strong_fail_count
      avg_unresolved: 평균 unresolved_count
      gate_fail_dist: {WEAK_OPENER: n, ...}
      alerts: 경고 목록
    """
    buf = _ONLINE_EVAL_BUFFER
    total = len(buf)
    if total == 0:
        return {"total": 0, "alerts": []}

    from collections import Counter

    reward_dist: Counter = Counter()
    market_dist: Counter = Counter()
    mode_dist: Counter = Counter()
    gate_dist: Counter = Counter()
    strong_sum = 0
    unresolved_sum = 0

    for m in buf:
        reward_dist[m.get("reward_type")] += 1
        market_dist[m.get("market_angle_type", "NONE")] += 1
        mode_dist[m.get("mode", "UNKNOWN")] += 1
        strong_sum += m.get("strong_fail_count", 0)
        unresolved_sum += m.get("unresolved_count", 0)
        for gf in m.get("gate_fails", []):
            gate_dist[gf] += 1

    avg_strong = round(strong_sum / total, 2)
    avg_unresolved = round(unresolved_sum / total, 2)

    # ── 자동 경고 생성 ──
    alerts: list[str] = []
    none_reward = reward_dist.get(None, 0)
    if total >= 5 and none_reward / total > 0.5:
        alerts.append(
            f"reward_type None 비율 {none_reward}/{total} "
            f"({int(none_reward/total*100)}%) — 50% 초과"
        )
    none_market = market_dist.get("NONE", 0)
    if total >= 5 and none_market / total > 0.5:
        alerts.append(
            f"market_angle NONE 비율 {none_market}/{total} "
            f"({int(none_market/total*100)}%) — 50% 초과"
        )
    if avg_strong > 0.5:
        alerts.append(f"avg strong_fail {avg_strong} — 0.5 초과")
    if avg_unresolved > 2.0:
        alerts.append(f"avg unresolved {avg_unresolved} — 2.0 초과")

    return {
        "total": total,
        "reward_type_dist": dict(reward_dist),
        "market_angle_dist": dict(market_dist),
        "mode_dist": dict(mode_dist),
        "avg_strong_fail": avg_strong,
        "avg_unresolved": avg_unresolved,
        "gate_fail_dist": dict(gate_dist),
        "alerts": alerts,
    }


def _reset_online_eval() -> None:
    """PR 26 — 버퍼 초기화 (테스트용)."""
    _ONLINE_EVAL_BUFFER.clear()


# ── PR 26: Topic Graph / Query Expansion Layer ──
#
# entity → topic → related keyword 관계를 dict 로 정의.
# 그래프 DB 없이 인메모리 dict. query expansion 시 관련 키워드 자동 추가.

# ── 토픽 그래프: entity → {topics, checkpoints, market_angles, doc_keywords} ──
_TOPIC_GRAPH: dict[str, dict] = {
    # ── 한국 금융 ──
    "한국은행": {
        "topics": ["금리", "통화정책", "금통위", "기준금리"],
        "checkpoints": ["금통위 의결", "기준금리 발표", "통화정책방향"],
        "market_angles": ["POLICY", "FLOW"],
        "doc_keywords": ["통화정책방향", "금융통화위원회", "의결서"],
    },
    "기재부": {
        "topics": ["세제", "예산", "재정", "경제정책"],
        "checkpoints": ["세법 시행일", "추경 편성", "경제전망"],
        "market_angles": ["POLICY", "COST"],
        "doc_keywords": ["세법 개정안", "경제정책방향", "추경안"],
    },
    "통계청": {
        "topics": ["물가", "고용", "인구", "경제지표"],
        "checkpoints": ["CPI 발표", "고용동향", "인구동향"],
        "market_angles": ["CHECKPOINT"],
        "doc_keywords": ["소비자물가지수", "경제활동인구조사", "잠정치"],
    },
    "금감원": {
        "topics": ["금융감독", "검사", "제재", "소비자보호"],
        "checkpoints": ["검사 결과 발표", "제재 의결"],
        "market_angles": ["POLICY"],
        "doc_keywords": ["검사보고서", "제재조치", "금융감독원장"],
    },
    # ── 한국 기업 ──
    "삼성전자": {
        "topics": ["반도체", "HBM", "파운드리", "메모리"],
        "checkpoints": ["분기 실적", "IR", "설비투자"],
        "market_angles": ["SUPPLY", "DEMAND"],
        "doc_keywords": ["사업보고서", "잠정실적", "공시"],
    },
    "SK하이닉스": {
        "topics": ["반도체", "HBM", "NAND", "메모리"],
        "checkpoints": ["분기 실적", "HBM 출하량"],
        "market_angles": ["SUPPLY", "DEMAND"],
        "doc_keywords": ["잠정실적", "IR", "공시"],
    },
    "현대차": {
        "topics": ["자동차", "전기차", "수소차", "수출"],
        "checkpoints": ["월간 판매", "분기 실적"],
        "market_angles": ["DEMAND", "SUPPLY"],
        "doc_keywords": ["판매실적", "수출실적"],
    },
    # ── 미국 ──
    "Federal Reserve": {
        "topics": ["금리", "인플레이션", "고용", "QT"],
        "checkpoints": ["FOMC", "dot plot", "beige book"],
        "market_angles": ["POLICY", "FLOW"],
        "doc_keywords": ["FOMC statement", "minutes", "summary of projections"],
    },
    "SEC": {
        "topics": ["증권규제", "공시", "ETF", "크립토규제"],
        "checkpoints": ["ETF 승인", "규제 의견서", "enforcement action"],
        "market_angles": ["POLICY"],
        "doc_keywords": ["filing", "enforcement", "rule proposal"],
    },
    # ── 국제 ──
    "IMF": {
        "topics": ["세계경제", "성장률", "재정건전성"],
        "checkpoints": ["WEO 발표", "Article IV"],
        "market_angles": ["CHECKPOINT"],
        "doc_keywords": ["World Economic Outlook", "Article IV", "Staff Report"],
    },
}


def _get_topic_context(entity: str) -> Optional[dict]:
    """
    PR 26 — entity 로 토픽 그래프 조회.

    반환: {topics, checkpoints, market_angles, doc_keywords} 또는 None
    """
    return _TOPIC_GRAPH.get(entity)


def _expand_query_keywords(
    entities: list[str],
    alias_map: Optional[dict] = None,
) -> list[str]:
    """
    PR 26 — entity 목록에서 검색 확장 키워드 생성.

    확장 순서:
      1. alias → canonical name
      2. topic graph → related topics + doc_keywords
      3. 중복 제거, 최대 15개

    AI 호출 없음.
    """
    if alias_map is None:
        alias_map = _ENTITY_ALIAS_MAP

    expanded: list[str] = []
    seen: set[str] = set()

    for ent in entities:
        # 원래 엔티티 추가
        if ent not in seen:
            expanded.append(ent)
            seen.add(ent)

        # alias 확장
        canonical = alias_map.get(ent)
        if canonical and canonical not in seen:
            expanded.append(canonical)
            seen.add(canonical)

        # topic graph 확장
        ctx = _get_topic_context(ent)
        if not ctx:
            # alias 로 한번 더 시도
            if canonical:
                ctx = _get_topic_context(canonical)
        if ctx:
            for topic in ctx.get("topics", [])[:3]:
                if topic not in seen:
                    expanded.append(topic)
                    seen.add(topic)
            for dk in ctx.get("doc_keywords", [])[:2]:
                if dk not in seen:
                    expanded.append(dk)
                    seen.add(dk)

    return expanded[:15]


def _build_topic_context_for_post(
    entities: list[str],
) -> dict:
    """
    PR 26 — 게시물 엔티티 목록에서 토픽 컨텍스트 빌드.

    반환:
      related_topics: 관련 토픽 목록
      expected_checkpoints: 예상 확인 시점
      expected_market_angles: 예상 시장 반영 경로
      expanded_keywords: 확장된 검색 키워드
    """
    all_topics: list[str] = []
    all_checkpoints: list[str] = []
    all_angles: list[str] = []
    seen_t: set[str] = set()
    seen_c: set[str] = set()
    seen_a: set[str] = set()

    for ent in entities:
        ctx = _get_topic_context(ent)
        if not ctx:
            # alias fallback
            canonical = _ENTITY_ALIAS_MAP.get(ent)
            if canonical:
                ctx = _get_topic_context(canonical)
        if not ctx:
            continue

        for t in ctx.get("topics", []):
            if t not in seen_t:
                all_topics.append(t)
                seen_t.add(t)
        for c in ctx.get("checkpoints", []):
            if c not in seen_c:
                all_checkpoints.append(c)
                seen_c.add(c)
        for a in ctx.get("market_angles", []):
            if a not in seen_a:
                all_angles.append(a)
                seen_a.add(a)

    return {
        "related_topics": all_topics[:10],
        "expected_checkpoints": all_checkpoints[:5],
        "expected_market_angles": all_angles[:5],
        "expanded_keywords": _expand_query_keywords(entities),
    }
