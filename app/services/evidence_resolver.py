"""
소스 무결성 / 1차 출처 감지 / 외부 증거 해결 모듈
==================================================
PR 12 Layer A/C, PR 13 — source_text 상태 점검,
1차 출처 유형 감지, 외부 evidence 로 질문 재해결.
AI 호출 없음 — rule-first.

content_pack.py 에서 분리됨 (PR 21).
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.content_pack import CandidateCard
    from app.services.question_resolver import ReaderQuestion


# ─── PR 12 Layer A: Source Integrity Layer ────────────────────────────────
#
# source_text 상태를 최종 글 생성 전에 점검한다.
# 빈 값 / 너무 짧음 / 존재하나 질문 해결 불가 — 원인을 라벨링.
# MISSING_SOURCE_TEXT / SOURCE_TEXT_TOO_SHORT 는 WARN-only.

# 최소 유의미 source_text 길이 (한국어 기사 기준 ~2문장)
_SOURCE_TEXT_MIN_LEN = 80


def _check_source_integrity(
    source_text: str,
) -> Optional[str]:
    """
    PR 12 Layer A — source_text 상태 라벨 반환.

    반환값:
      None                          — 정상 (길이 충분)
      "MISSING_SOURCE_TEXT"         — 빈 문자열 / None / 공백만
      "SOURCE_TEXT_TOO_SHORT"       — 존재하지만 _SOURCE_TEXT_MIN_LEN 미만
    """
    if not source_text or not source_text.strip():
        return "MISSING_SOURCE_TEXT"
    if len(source_text.strip()) < _SOURCE_TEXT_MIN_LEN:
        return "SOURCE_TEXT_TOO_SHORT"
    return None


# ─── PR 13: External Evidence Layer ───────────────────────────────────────
#
# source_text 내부만 보지 말고, source_url / key_facts / source_text 에서
# 1차 출처 유형을 감지한다. 감지된 외부 evidence 로 UNRESOLVED 질문을
# 재해결 시도한다. AI 호출 없음 — rule-first.
#
# primary_source_type 유형:
#   GOVERNMENT   — 정부/기관 공지, 정책 발표
#   REPORT       — 공식 보고서 (IMF, OECD, 한은, 통계청 등)
#   DISCLOSURE   — 기업 공시, 실적 발표
#   DATA_SOURCE  — 원 데이터 제공처 (CoinGecko, FRED, 통계청 DB 등)
#   DIRECT_STMT  — 회사/노조/당국 직접 발표문
#   None         — 1차 출처 감지 실패

# URL 도메인 → 출처 유형 매핑
_PRIMARY_SOURCE_URL_PATTERNS: dict[str, list[str]] = {
    "GOVERNMENT": [
        "go.kr", "gov.kr", "moef.go.kr", "mof.go.kr", "moel.go.kr",
        "nts.go.kr", "korea.kr", "whitehouse.gov", "congress.gov",
        "state.gov", "treasury.gov", "europa.eu", "gov.uk",
    ],
    "REPORT": [
        "imf.org", "oecd.org", "worldbank.org", "bis.org",
        "bok.or.kr", "kostat.go.kr", "kosis.kr",
        "federalreserve.gov", "ecb.europa.eu", "boj.or.jp",
    ],
    "DISCLOSURE": [
        "dart.fss.or.kr", "kind.krx.co.kr", "sec.gov",
        "ir.", "investor.", "investors.",
    ],
    "DATA_SOURCE": [
        "coingecko.com", "coinmarketcap.com", "fred.stlouisfed.org",
        "tradingview.com", "bloomberg.com", "reuters.com",
        "data.go.kr", "ecos.bok.or.kr",
    ],
}

# 텍스트 키워드 → 출처 유형 매핑 (source_text / key_facts 에서 탐지)
_PRIMARY_SOURCE_TEXT_PATTERNS: dict[str, list[str]] = {
    "GOVERNMENT": [
        "정부 발표", "국무회의", "기재부", "기획재정부", "국세청",
        "국토부", "국토교통부", "고용노동부", "산업부", "산업통상자원부",
        "금융위", "금융위원회", "공정위", "공정거래위원회",
        "대통령실", "국회", "백악관", "재무부", "상무부",
        "White House", "Treasury", "Congress",
    ],
    "REPORT": [
        "IMF", "OECD", "세계은행", "World Bank", "BIS",
        "한국은행", "한은", "통계청", "보고서", "연차보고",
        "Federal Reserve", "ECB", "BOJ", "중앙은행",
    ],
    "DISCLOSURE": [
        "공시", "실적 발표", "IR", "분기 보고서", "사업보고서",
        "감사보고서", "유가증권", "코스닥", "거래소 공시",
        "SEC filing", "10-K", "10-Q", "earnings",
    ],
    "DATA_SOURCE": [
        "CoinGecko", "CoinMarketCap", "TradingView",
        "Bloomberg", "Reuters", "FRED",
        "원본 데이터", "원 데이터", "raw data",
    ],
    "DIRECT_STMT": [
        "직접 발표", "공식 입장", "보도자료", "성명",
        "노조 발표", "경영진 발표", "대변인", "대표이사",
        "CEO", "press release", "statement",
        "밝혔다", "발표했다", "공개했다",
    ],
}

# 유효한 primary_source_type 값
_PRIMARY_SOURCE_VALID_TYPES = frozenset([
    "GOVERNMENT", "REPORT", "DISCLOSURE", "DATA_SOURCE", "DIRECT_STMT",
])


def _detect_primary_source(
    card: "CandidateCard",
    source_text: str = "",
) -> tuple[Optional[str], int]:
    """
    PR 13 — 1차 출처 유형 감지.

    card.source_url / card.key_facts / source_text 에서 rule-first 로
    primary source 유형을 탐지한다. AI 호출 없음.

    반환: (primary_source_type, external_evidence_count)
      primary_source_type: GOVERNMENT / REPORT / DISCLOSURE / DATA_SOURCE / DIRECT_STMT / None
      external_evidence_count: 감지된 외부 근거 패턴 수 (0 이상)
    """
    detected_type: Optional[str] = None
    evidence_count = 0

    # ── 1단계: source_url 도메인 매칭 (가장 신뢰도 높음) ──
    url = (card.source_url or "").lower()
    if url:
        for src_type, domains in _PRIMARY_SOURCE_URL_PATTERNS.items():
            for domain in domains:
                if domain in url:
                    detected_type = src_type
                    evidence_count += 1
                    break
            if detected_type:
                break

    # ── 2단계: key_facts + source_text 텍스트 매칭 ──
    combined = " ".join(card.key_facts or []) + " " + (source_text or "")
    type_hits: dict[str, int] = {}
    for src_type, patterns in _PRIMARY_SOURCE_TEXT_PATTERNS.items():
        hits = sum(1 for p in patterns if p in combined)
        if hits > 0:
            type_hits[src_type] = hits
            evidence_count += hits

    # URL 에서 이미 감지했으면 텍스트 hits 는 evidence_count 만 보강
    if not detected_type and type_hits:
        # 가장 많이 매칭된 유형 채택
        detected_type = max(type_hits, key=type_hits.get)

    return detected_type, evidence_count


def _resolve_questions_from_external(
    questions: list["ReaderQuestion"],
    primary_source_type: Optional[str],
    evidence_count: int,
) -> list["ReaderQuestion"]:
    """
    PR 13 — 외부 evidence 로 UNRESOLVED 질문 재해결 시도.

    source_text 내부 매칭에서 놓친 질문을, 감지된 1차 출처 유형을
    근거로 추가 해결한다. 억지 해석 금지 — 출처 유형이 질문 카테고리와
    직접 연관될 때만 RESOLVED.
    """
    if not primary_source_type or evidence_count == 0:
        return questions

    for q in questions:
        if q.status == "RESOLVED":
            continue

        if q.category == "SOURCE":
            # 1차 출처가 감지되면 SOURCE 질문은 해결 가능
            q.status = "RESOLVED"
            q.evidence = f"외부 1차 출처 감지: {primary_source_type}"
            q.evidence_snippet = primary_source_type
            q.evidence_source = "EXTERNAL"

        elif q.category == "SCOPE" and primary_source_type in (
            "REPORT", "DISCLOSURE", "DATA_SOURCE",
        ):
            # 보고서/공시/데이터 소스면 구체 수치가 있을 가능성 높음
            if evidence_count >= 2:
                q.status = "RESOLVED"
                q.evidence = f"외부 데이터 출처 감지: {primary_source_type}"
                q.evidence_snippet = f"{primary_source_type}×{evidence_count}"
                q.evidence_source = "EXTERNAL"

        elif q.category == "CHECKPOINT" and primary_source_type in (
            "GOVERNMENT", "DISCLOSURE",
        ):
            # 정부 발표/기업 공시면 다음 확인 시점이 있을 가능성 높음
            if evidence_count >= 2:
                q.status = "RESOLVED"
                q.evidence = f"외부 공식 일정 출처 감지: {primary_source_type}"
                q.evidence_snippet = f"{primary_source_type}×{evidence_count}"
                q.evidence_source = "EXTERNAL"

    return questions
