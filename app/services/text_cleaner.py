"""
텍스트 정제 유틸리티
====================
A. 기사 UI 잡문 제거 — Naver 뉴스 등의 네비게이션/메타 노이즈 제거
B. 내부 라우팅 문구 새니타이즈 — [CANDIDATE], KO-only 등 사용자 노출 차단
"""

import re

# ─────────────────────────────────────────────────────────────────────
# A. 기사 UI 잡문 제거
# ─────────────────────────────────────────────────────────────────────

# 단순 치환 대상 (substring → 빈 문자열)
_JUNK_SUBSTRINGS: list[str] = [
    "본문 바로가기",
    "기사 바로가기",
    "메인 메뉴로 바로가기",
    "뉴스홈으로 가기",
    "뉴스 홈으로 가기",
    "뉴스 듣기",
    "텍스트 음성 변환",
    "이 기사를 추천합니다",
    "좋아요 , , , , ,",
    "이동 통신망을 이용하여",
]

# 줄 단위 제거 대상 (줄 전체가 이 패턴이면 삭제)
_JUNK_LINE_RES: list[re.Pattern] = [
    re.compile(r"^\s*말하기\s*속도\s*$"),
    re.compile(r"^\s*성별\s*$"),
    re.compile(r"^\s*(남성|여성)\s*$"),
    re.compile(r"^\s*(느림|보통|빠름)\s*$"),
    re.compile(r"^\s*(느림|보통|빠름)\s+(느림|보통|빠름)"),
    # 입력/수정 시각
    re.compile(r"^\s*입력\s*\d{4}[.\-/]"),
    re.compile(r"^\s*수정\s*\d{4}[.\-/]"),
    re.compile(r"^\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\s+\d{1,2}:\d{2}.*?(입력|수정)"),
    # 기자명 단독 줄
    re.compile(r"^\s*\S{2,5}\s*(기자|특파원|통신원)\s*$"),
    # 저작권/무단전재
    re.compile(r"^\s*저작권.*무단.*전재"),
    re.compile(r"^\s*무단\s*전재.*금지"),
    re.compile(r"^\s*ⓒ\s*"),
    re.compile(r"^\s*Copyright", re.IGNORECASE),
    re.compile(r"^\s*All\s+[Rr]ights\s+[Rr]eserved"),
    # UI 컨트롤
    re.compile(r"^\s*글자\s*크기"),
    re.compile(r"^\s*인쇄하기\s*$"),
    re.compile(r"^\s*스크랩\s*$"),
    re.compile(r"^\s*보내기\s*$"),
    # 음성 재생 관련 행
    re.compile(r"^\s*음성\s*(재생|변환|듣기)"),
    # 기사 제공 행
    re.compile(r"^\s*기사\s*제공\s*:?\s*"),
    # 추천 반응 행 (좋아요 0 슬퍼요 0 ...)
    re.compile(r"^\s*(좋아요|슬퍼요|화나요|후속기사)\s*\d*\s*$"),
]

_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def clean_article_text(text: str) -> str:
    """뉴스 기사 텍스트에서 UI 잡문/메타 노이즈를 제거한다.

    수집 시점(news_monitor)과 출력 시점(주간 주목 카드, 승인 카드)에서
    모두 호출 가능. 정상 기사 본문에는 영향 없음.
    """
    if not text:
        return ""

    # 1. 잡문 substring 치환
    for junk in _JUNK_SUBSTRINGS:
        text = text.replace(junk, "")

    # 2. 줄 단위 필터
    lines = text.split("\n")
    clean: list[str] = []
    for line in lines:
        if any(p.search(line) for p in _JUNK_LINE_RES):
            continue
        clean.append(line)
    text = "\n".join(clean)

    # 3. 공백 정규화
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    text = _MULTI_SPACE_RE.sub(" ", text)

    return text.strip()


# ─────────────────────────────────────────────────────────────────────
# B. 내부 라우팅 문구 새니타이즈
# ─────────────────────────────────────────────────────────────────────

_INTERNAL_TAG_RE = re.compile(r"^\[(BREAKING_NOW|CANDIDATE)\]\s*")

_INTERNAL_BODY_PREFIXES = (
    "KO-only pipeline",
    "Routed to ",
)

_INTERNAL_REASONING_RES: list[re.Pattern] = [
    re.compile(r"\bKO-only routing\b"),
    re.compile(r"\bEnglish draft skipped\.?\b"),
    re.compile(r"\bRouted to \w+ pipeline\b"),
    re.compile(r"\bdomain=\S+"),
]


def sanitize_internal_tags(hook: str, body: str) -> tuple[str, str]:
    """게시용/카드용 텍스트에서 내부 라우팅 문구를 제거한다.

    DB 기존 레코드에 남아 있는 구형 문자열이 사용자 출력으로
    승격되지 않도록 차단하는 최종 방어선.
    """
    # Hook: [BREAKING_NOW] / [CANDIDATE] 접두사 제거
    hook = _INTERNAL_TAG_RE.sub("", hook).strip()

    # Body: 통째로 placeholder인 경우
    for prefix in _INTERNAL_BODY_PREFIXES:
        if body.startswith(prefix):
            body = ""
            break

    return hook, body


def sanitize_reasoning(text: str) -> str:
    """risk_reasoning / ai_rationale 에서 내부 라우팅 문구를 제거한다."""
    if not text:
        return ""
    for pattern in _INTERNAL_REASONING_RES:
        text = pattern.sub("", text)
    # 정리: 연속 쉼표/마침표/공백
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\.\s*\.", ".", text)
    return text.strip().strip(",").strip()
