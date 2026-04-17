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
    # Naver 뉴스
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
    # 앱/랜딩 페이지 UI
    "메뉴 바로 가기",
    "메뉴 바로가기",
    "앱을 통해 만나보세요",
    "앱에서 보기",
    "앱에서 만나보세요",
    "앱 다운로드",
    "앱으로 보기",
    # Naver PICK / 언론사 안내
    "언론사가 주요기사로 선정한 기사입니다.",
    "언론사가 주요기사로 선정한 기사입니다",
    "언론사별 바로가기",
    "PICK 안내",
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
    # 앱/웹 공통 UI 단독 행
    re.compile(r"^\s*로그인\s*$"),
    re.compile(r"^\s*회원가입\s*$"),
    re.compile(r"^\s*프리미엄\s*$"),
    re.compile(r"^\s*멤버십\s*$"),
    re.compile(r"^\s*방송\s*멤버십\s*$"),
    re.compile(r"^\s*보관함\s*$"),
    re.compile(r"^\s*테마\s*모드\s*$"),
    re.compile(r"^\s*설정\s*$"),
    re.compile(r"^\s*검색\s*$"),
    re.compile(r"^\s*마이페이지\s*$"),
    re.compile(r"^\s*알림\s*$"),
    re.compile(r"^\s*공유하기\s*$"),
    re.compile(r"^\s*댓글\s*\d*\s*$"),
    re.compile(r"^\s*목록\s*$"),
    re.compile(r"^\s*관련\s*(기사|뉴스|글)\s*$"),
    re.compile(r"^\s*광고\s*$"),
    re.compile(r"^\s*AD\s*$", re.IGNORECASE),
    re.compile(r"^\s*LIVE\s*$", re.IGNORECASE),
    re.compile(r"^\s*HOME\s*$", re.IGNORECASE),
    # App Store / Play 스토어
    re.compile(r"^\s*(App Store|Google Play|Play 스토어)", re.IGNORECASE),
    re.compile(r"^\s*다운로드\s*$"),
    # Naver PICK / 언론사 안내
    re.compile(r"^\s*\S+\s+PICK\s*(안내)?\s*$"),
    re.compile(r"^\s*닫기\s*$"),
]

_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

# 인라인 제거 대상 (줄 경계 무관, 텍스트 내부에서도 제거)
_JUNK_INLINE_RES: list[re.Pattern] = [
    # "서다희 기자 서다희 기자" — 기자명 중복 패턴
    re.compile(r"\S{2,5}\s*기자\s+\S{2,5}\s*기자"),
    # "입력 2026.04.13." — Naver 입력/수정 시각 (인라인)
    re.compile(r"입력\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?"),
    re.compile(r"수정\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?"),
    # "닫기" 앞에 공백만 있을 때 (UI 버튼 텍스트)
    re.compile(r"\s+닫기\s+"),
]


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

    # 3. 인라인 잡문 제거 (줄 경계 무관)
    for p in _JUNK_INLINE_RES:
        text = p.sub(" ", text)

    # 4. 공백 정규화
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    text = _MULTI_SPACE_RE.sub(" ", text)

    return text.strip()


# ─────────────────────────────────────────────────────────────────────
# A-2. 콘텐츠 밀도 체크 — 기사형 vs 앱/랜딩 페이지 판별
# ─────────────────────────────────────────────────────────────────────

# 기사가 아닌 페이지에서 자주 등장하는 UI/메뉴 키워드
_NON_ARTICLE_SIGNALS: list[str] = [
    "로그인", "회원가입", "앱 다운로드", "앱에서 보기", "앱으로 보기",
    "프리미엄", "멤버십", "마이페이지", "고객센터", "이용약관",
    "개인정보", "보관함", "구독", "무료체험", "App Store", "Google Play",
    "테마 모드", "다크 모드", "알림 설정", "방송 멤버십",
]

# 최소 기사 문장 길이 (정제 후)
_MIN_ARTICLE_CHARS = 150
_MIN_ARTICLE_SENTENCES = 2


def is_article_like(text: str) -> bool:
    """정제된 텍스트가 기사 본문으로 충분한 밀도를 가지는지 판별한다.

    Returns:
        True  → 기사형 본문 (게시글 생성 가능)
        False → 앱/랜딩/허브 페이지 (생성 차단 권장)
    """
    if not text:
        return False

    cleaned = clean_article_text(text)
    if len(cleaned) < _MIN_ARTICLE_CHARS:
        return False

    # 문장 수 체크 (마침표/물음표/느낌표 기준)
    sentences = re.split(r"[.?!。]\s+", cleaned)
    meaningful = [s for s in sentences if len(s.strip()) > 10]
    if len(meaningful) < _MIN_ARTICLE_SENTENCES:
        return False

    # UI 신호 밀도 — 비기사 키워드가 전체 텍스트 대비 많으면 기사 아님
    signal_count = sum(1 for kw in _NON_ARTICLE_SIGNALS if kw in text)
    # 원본 text 기준 (정제 전) — UI 키워드 3개 이상이면 의심
    if signal_count >= 3 and len(cleaned) < 500:
        return False

    return True


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


# ─────────────────────────────────────────────────────────────────────
# C. Resonance 구조(⚠️/📌) 최후 방어선
# ─────────────────────────────────────────────────────────────────────
#
# 기본 해결책은 DraftWriter/Reviewer 프롬프트다. 프롬프트가 마커를 출력하면
# 이 함수는 no-op 이다. 프롬프트가 실패한 경우(마커 0개)에만 placeholder 를
# 삽입해 운영자가 승인 전에 재생성하도록 유도한다. 한 개만 누락된 경우는
# 원본을 유지하고 로그만 남긴다(반쪽 구조 보존).

_RES_KO_WARN = "⚠️ 진짜 쟁점:"
_RES_KO_PIN = "📌 지금 봐야 할 포인트:"
_RES_EN_WARN = "⚠️ Real issue:"
_RES_EN_PIN = "📌 Watch for:"


def _has_resonance_markers(body: str) -> tuple[bool, bool]:
    """(has_warn, has_pin) — KO/EN 마커를 모두 커버."""
    has_warn = (_RES_KO_WARN in body) or (_RES_EN_WARN in body)
    has_pin = (_RES_KO_PIN in body) or (_RES_EN_PIN in body)
    return has_warn, has_pin


def ensure_resonance_structure(
    body: str, language: str = "ko",
) -> tuple[str, str]:
    """
    Reviewer/DraftWriter 가 ⚠️/📌 구조를 누락한 경우의 fallback.

    기본 해결책은 프롬프트. 이 함수는 프롬프트 실패에만 작동.
    - 두 마커 모두 존재 → no-op, status="ok"
    - 한 개만 존재 → 원본 유지, status="partial" (반쪽 구조 보존 원칙)
    - 둘 다 없음 → 구조 누락 placeholder 삽입, status="injected"

    placeholder 는 "구조 누락 — 재생성 권장" 문구로 운영자가 승인 전에
    재생성하도록 유도한다.

    Returns:
        (augmented_body, status) — status ∈ {"ok", "partial", "injected", "empty"}
    """
    if not body:
        return body, "empty"

    has_warn, has_pin = _has_resonance_markers(body)
    if has_warn and has_pin:
        return body, "ok"
    if has_warn or has_pin:
        return body, "partial"

    if (language or "ko").lower().startswith("en"):
        addon = (
            "\n\n⚠️ Real issue: (structure missing — regenerate recommended)"
            "\n📌 Watch for: (structure missing — regenerate recommended)"
        )
    else:
        addon = (
            "\n\n⚠️ 진짜 쟁점: (구조 누락 — 재생성 권장)"
            "\n📌 지금 봐야 할 포인트: (구조 누락 — 재생성 권장)"
        )
    return body.rstrip() + addon, "injected"
