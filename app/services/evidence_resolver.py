"""
소스 무결성 / 1차 출처 감지 / 외부 증거 해결 모듈
==================================================
PR 12 Layer A/C, PR 13 — source_text 상태 점검,
1차 출처 유형 감지, 외부 evidence 로 질문 재해결.
PR 24 — Hybrid Retrieval + Metadata Filter Layer 추가.
AI 호출 없음 — rule-first.

content_pack.py 에서 분리됨 (PR 21).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


# ── PR 24: Hybrid Retrieval + Metadata Filter Layer ──
#
# 1차 출처 감지 시 source_type / 기관 / 국가 / 문서유형 같은
# 구조화 메타데이터를 더 풍부하게 남긴다.
# 질문 해결 시 metadata filter를 우선 적용한 뒤 기존 로직 fallback.
# 벡터DB 없이 rule-first 로 구현.

# ── 기관명 → 국가 매핑 ──
_INSTITUTION_COUNTRY_MAP: dict[str, str] = {
    # 한국
    "기재부": "KR", "기획재정부": "KR", "국세청": "KR", "국토부": "KR",
    "국토교통부": "KR", "고용노동부": "KR", "산업부": "KR",
    "산업통상자원부": "KR", "금융위": "KR", "금융위원회": "KR",
    "공정위": "KR", "공정거래위원회": "KR", "한국은행": "KR", "한은": "KR",
    "통계청": "KR", "대통령실": "KR", "국회": "KR", "금감원": "KR",
    "삼성전자": "KR", "SK하이닉스": "KR", "현대차": "KR",
    # 미국
    "백악관": "US", "재무부": "US", "상무부": "US", "연준": "US",
    "White House": "US", "Treasury": "US", "Congress": "US",
    "Federal Reserve": "US", "Fed": "US", "SEC": "US",
    # 국제
    "IMF": "INTL", "OECD": "INTL", "World Bank": "INTL",
    "세계은행": "INTL", "BIS": "INTL",
    # 유럽
    "ECB": "EU", "유럽중앙은행": "EU",
    # 일본
    "BOJ": "JP", "일본은행": "JP",
    # 중국
    "인민은행": "CN", "PBOC": "CN",
}

# ── URL 도메인 → 국가 매핑 ──
_DOMAIN_COUNTRY_MAP: dict[str, str] = {
    "go.kr": "KR", "gov.kr": "KR", "or.kr": "KR",
    "whitehouse.gov": "US", "treasury.gov": "US",
    "sec.gov": "US", "federalreserve.gov": "US",
    "europa.eu": "EU", "ecb.europa.eu": "EU",
    "gov.uk": "UK",
    "boj.or.jp": "JP",
    "imf.org": "INTL", "oecd.org": "INTL", "worldbank.org": "INTL",
    "bis.org": "INTL",
}

# ── 문서유형 키워드 ──
_DOC_TYPE_PATTERNS: dict[str, list[str]] = {
    "POLICY_ANNOUNCEMENT": [
        "시행일", "시행령", "고시", "공포", "개정",
        "발효", "적용 시작", "executive order",
    ],
    "STATISTICAL_RELEASE": [
        "통계", "집계", "속보", "잠정치", "확정치", "지표",
        "CPI", "GDP", "PMI", "고용률", "실업률", "물가",
    ],
    "EARNINGS_REPORT": [
        "실적", "매출", "영업이익", "순이익", "분기",
        "어닝", "earnings", "revenue", "profit",
    ],
    "OFFICIAL_STATEMENT": [
        "보도자료", "성명", "공식 입장", "대변인",
        "press release", "statement", "발표문",
    ],
    "REGULATORY_FILING": [
        "공시", "사업보고서", "감사보고서", "유가증권",
        "10-K", "10-Q", "SEC filing", "dart",
    ],
}

# ── 날짜 패턴 (한국어/영어 — 절대 + 상대) ──
_DATE_RE = re.compile(
    r"\d{4}[-./]\d{1,2}[-./]\d{1,2}"        # 2024-01-15
    r"|\d{1,2}월\s*\d{1,2}일"                # 1월 15일
    r"|\d{4}년\s*\d{1,2}월"                  # 2024년 1월
    r"|\d{1,2}/\d{1,2}/\d{4}"               # 01/15/2024
)

# PR 28: 상대 날짜 패턴
_RELATIVE_DATE_RE = re.compile(
    r"내년|올해|작년|내달|다음\s*달|이번\s*달|지난\s*달"
    r"|이번\s*분기|다음\s*분기|지난\s*분기|상반기|하반기"
    r"|내주|다음\s*주|이번\s*주|지난\s*주"
    r"|내일|모레|어제|그제"
    r"|올\s*\d{1,2}월|내\s*\d{1,2}월"
)

# PR 28: 상대 날짜 → 정규화 라벨
_RELATIVE_DATE_LABELS: dict[str, str] = {
    "내년": "NEXT_YEAR", "올해": "THIS_YEAR", "작년": "LAST_YEAR",
    "내달": "NEXT_MONTH", "상반기": "H1", "하반기": "H2",
    "내주": "NEXT_WEEK", "내일": "TOMORROW", "모레": "DAY_AFTER_TOMORROW",
    "어제": "YESTERDAY", "그제": "DAY_BEFORE_YESTERDAY",
}


def _normalize_relative_dates(text: str) -> list[str]:
    """
    PR 28 — 상대 날짜 표현을 정규화 라벨로 변환.

    "내년 1분기 시행" → ["NEXT_YEAR"]
    "다음 달 발표 예정" → ["NEXT_MONTH"]
    절대 날짜와 별개로 작동. 둘 다 추출 가능.
    """
    matches = _RELATIVE_DATE_RE.findall(text)
    labels = []
    seen = set()
    for m in matches:
        clean = m.strip()
        label = _RELATIVE_DATE_LABELS.get(clean)
        if not label:
            # "다음 달" → NEXT_MONTH, "이번 분기" → THIS_QUARTER 등
            if "다음" in clean and "달" in clean:
                label = "NEXT_MONTH"
            elif "이번" in clean and "달" in clean:
                label = "THIS_MONTH"
            elif "지난" in clean and "달" in clean:
                label = "LAST_MONTH"
            elif "다음" in clean and "분기" in clean:
                label = "NEXT_QUARTER"
            elif "이번" in clean and "분기" in clean:
                label = "THIS_QUARTER"
            elif "지난" in clean and "분기" in clean:
                label = "LAST_QUARTER"
            elif "다음" in clean and "주" in clean:
                label = "NEXT_WEEK"
            elif "이번" in clean and "주" in clean:
                label = "THIS_WEEK"
            elif "지난" in clean and "주" in clean:
                label = "LAST_WEEK"
            else:
                label = f"RELATIVE:{clean}"
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels[:5]


def _extract_source_metadata(
    card: "CandidateCard",
    source_text: str = "",
    primary_source_type: Optional[str] = None,
) -> dict:
    """
    PR 24 — 1차 출처에서 구조화 메타데이터 추출.

    반환 dict 필드:
      source_type, institution, country, doc_type,
      dates (최대 3), entity_keywords (최대 5)

    AI 호출 없음.
    """
    combined = " ".join(card.key_facts or []) + " " + (source_text or "")
    url = (card.source_url or "").lower()

    # ── institution ──
    institution: Optional[str] = None
    country: Optional[str] = None
    for inst, ctry in _INSTITUTION_COUNTRY_MAP.items():
        if inst in combined:
            institution = inst
            country = ctry
            break

    # ── country from URL (fallback) ──
    if not country and url:
        for domain, ctry in _DOMAIN_COUNTRY_MAP.items():
            if domain in url:
                country = ctry
                break

    # ── doc_type ──
    doc_type: Optional[str] = None
    best_doc_hits = 0
    for dtype, patterns in _DOC_TYPE_PATTERNS.items():
        hits = sum(1 for p in patterns if p in combined)
        if hits > best_doc_hits:
            best_doc_hits = hits
            doc_type = dtype

    # ── dates (절대 + 상대) ──
    dates = _DATE_RE.findall(combined)[:3]
    relative_dates = _normalize_relative_dates(combined)

    # ── entity_keywords ──
    entity_keywords: list[str] = []
    for inst_name in _INSTITUTION_COUNTRY_MAP:
        if inst_name in combined and inst_name not in entity_keywords:
            entity_keywords.append(inst_name)
            if len(entity_keywords) >= 5:
                break

    return {
        "source_type": primary_source_type,
        "institution": institution,
        "country": country,
        "doc_type": doc_type,
        "dates": dates,
        "relative_dates": relative_dates,
        "entity_keywords": entity_keywords,
    }


def _resolve_questions_with_metadata(
    questions: list["ReaderQuestion"],
    metadata: dict,
) -> list["ReaderQuestion"]:
    """
    PR 24 — metadata filter 우선 적용 후 기존 로직 fallback.

    _resolve_questions_from_external 보다 먼저 호출.
    institution / doc_type / dates 기반으로 질문 해결.

    AI 호출 없음.
    """
    if not metadata:
        return questions

    institution = metadata.get("institution")
    country = metadata.get("country")
    doc_type = metadata.get("doc_type")
    dates = metadata.get("dates", [])

    for q in questions:
        if q.status == "RESOLVED":
            continue

        if q.category == "SOURCE" and institution:
            q.status = "RESOLVED"
            q.evidence = f"기관 감지: {institution}"
            if country:
                q.evidence += f" ({country})"
            q.evidence_snippet = institution[:50]
            q.evidence_source = "METADATA"

        elif q.category == "SCOPE" and doc_type in (
            "STATISTICAL_RELEASE", "EARNINGS_REPORT",
        ):
            q.status = "RESOLVED"
            q.evidence = f"문서유형 감지: {doc_type}"
            q.evidence_snippet = doc_type[:50]
            q.evidence_source = "METADATA"

        elif q.category == "IMPACT" and dates:
            q.status = "RESOLVED"
            q.evidence = f"일정 감지: {dates[0]}"
            q.evidence_snippet = dates[0][:50]
            q.evidence_source = "METADATA"

        elif q.category == "CHECKPOINT" and doc_type in (
            "POLICY_ANNOUNCEMENT", "REGULATORY_FILING",
        ):
            q.status = "RESOLVED"
            q.evidence = f"정책/규제 문서 감지: {doc_type}"
            q.evidence_snippet = doc_type[:50]
            q.evidence_source = "METADATA"

    return questions


# ── PR 25: Exact Citation + Evidence Rerank Layer ──
#
# 질문 해결 근거를 더 정확히 잡고, 여러 근거 후보 중 가장 적합한 것을 고른다.
# AI 호출 없음 — rule-first rerank.

@dataclass
class EvidenceCandidate:
    """PR 25 — 단일 근거 후보."""
    span: str = ""            # 원문에서 추출한 근거 문자열
    span_start: int = -1      # 원문 내 시작 위치
    span_end: int = -1        # 원문 내 끝 위치
    source: str = ""          # "SOURCE_TEXT" | "KEY_FACTS" | "METADATA"
    relevance_score: int = 0  # 질문 적합도 점수 (높을수록 적합)
    category_match: str = ""  # 매칭된 질문 카테고리


# ── 문장 분리 (PR 28 보강) ──
# 약어 뒤 마침표 오분리 방지: 알려진 약어 패턴을 임시 치환 후 분리
_ABBREV_PATTERNS = re.compile(
    r"(?:Dr|Mr|Mrs|Ms|Prof|Inc|Corp|Ltd|Jr|Sr|vs|etc|No|Vol)\."
    r"|(?:삼성전자|SK하이닉스|LG에너지솔루션)\."  # 한국 기업명+마침표
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n")


def _split_sentences(text: str) -> list[str]:
    """PR 25/28 — 텍스트를 문장 단위로 분리. 약어 오분리 방지."""
    if not text:
        return []
    # 약어 마침표를 임시 치환
    protected = _ABBREV_PATTERNS.sub(lambda m: m.group().replace(".", "§"), text)
    parts = _SENTENCE_SPLIT_RE.split(protected)
    # 복원
    result = []
    for s in parts:
        restored = s.replace("§", ".").strip()
        if restored and len(restored) > 5:
            result.append(restored)
    return result


def _collect_evidence_candidates(
    source_text: str,
    key_facts: list[str],
    category: str,
) -> list[EvidenceCandidate]:
    """
    PR 25 — 주어진 카테고리에 대한 근거 후보 수집.

    source_text 를 문장 단위로 분리한 뒤, 각 문장이 카테고리 패턴에
    매칭되는지 확인. key_facts 도 별도 소스로 검사.

    반환: EvidenceCandidate 리스트 (점수 미계산 상태)
    """
    from app.services.question_resolver import (
        _SOURCE_CITATION_RE, _SCOPE_NUMBER_RE,
        _IMPACT_MARKER_PATTERNS, _CHECKPOINT_EVIDENCE_PATTERNS,
    )

    candidates: list[EvidenceCandidate] = []

    # ── source_text 문장별 검사 ──
    sentences = _split_sentences(source_text)
    offset = 0
    for sent in sentences:
        pos = source_text.find(sent, offset)
        if pos == -1:
            pos = offset
        matched = False

        if category == "SOURCE":
            m = _SOURCE_CITATION_RE.search(sent)
            if m:
                matched = True
        elif category == "SCOPE":
            m = _SCOPE_NUMBER_RE.search(sent)
            if m:
                matched = True
        elif category == "IMPACT":
            hits = [p for p in _IMPACT_MARKER_PATTERNS if p in sent]
            if hits:
                matched = True
        elif category == "CHECKPOINT":
            hits = [p for p in _CHECKPOINT_EVIDENCE_PATTERNS if p in sent]
            if hits:
                matched = True

        if matched:
            candidates.append(EvidenceCandidate(
                span=sent[:100],
                span_start=pos,
                span_end=pos + len(sent),
                source="SOURCE_TEXT",
                category_match=category,
            ))
        offset = pos + len(sent)

    # ── key_facts 검사 ──
    for fact in (key_facts or []):
        matched = False
        if category == "SOURCE":
            if _SOURCE_CITATION_RE.search(fact):
                matched = True
        elif category == "SCOPE":
            if _SCOPE_NUMBER_RE.search(fact):
                matched = True
        elif category == "IMPACT":
            hits = [p for p in _IMPACT_MARKER_PATTERNS if p in fact]
            if hits:
                matched = True
        elif category == "CHECKPOINT":
            hits = [p for p in _CHECKPOINT_EVIDENCE_PATTERNS if p in fact]
            if hits:
                matched = True

        if matched:
            candidates.append(EvidenceCandidate(
                span=fact[:100],
                span_start=-1,
                span_end=-1,
                source="KEY_FACTS",
                category_match=category,
            ))

    return candidates


# PR 28: Tunable score weights
SCORE_SOURCE_TEXT = 10     # source_text 출처 보너스
SCORE_CATEGORY_MATCH = 5   # 카테고리 정확 매칭
SCORE_LONG_SPAN = 3        # span ≥ 20자
SCORE_HEAD_POSITION = 2    # 문서 상단 (start < 500)
SCORE_HAS_NUMBER = 1       # 숫자 포함
SCORE_EXACT_KEYWORD = 4    # 핵심 키워드 정확 매칭 (짧지만 정확)
SCORE_HEAD_POSITION_LIMIT = 500


def _score_candidate(
    candidate: EvidenceCandidate,
    category: str,
) -> int:
    """
    PR 25/28 — 근거 후보 적합도 점수 계산.

    점수 기준 (tunable weights):
      +SCORE_SOURCE_TEXT   source_text 출처
      +SCORE_CATEGORY_MATCH  카테고리 정확 매칭
      +SCORE_LONG_SPAN     span ≥ 20자
      +SCORE_HEAD_POSITION  문서 상단
      +SCORE_HAS_NUMBER    숫자 포함
      +SCORE_EXACT_KEYWORD  핵심 키워드 정확 매칭 (짧은 span도 허용)
    """
    score = 0
    if candidate.source == "SOURCE_TEXT":
        score += SCORE_SOURCE_TEXT
    if candidate.category_match == category:
        score += SCORE_CATEGORY_MATCH
    if len(candidate.span) >= 20:
        score += 3
    if candidate.span_start >= 0 and candidate.span_start < SCORE_HEAD_POSITION_LIMIT:
        score += SCORE_HEAD_POSITION
    if re.search(r"\d", candidate.span):
        score += SCORE_HAS_NUMBER
    # PR 28: 짧지만 핵심 키워드 정확 매칭 보너스
    # 기관명/수치가 span에 직접 포함되면 길이와 무관하게 가산
    from app.services.evidence_resolver import _INSTITUTION_COUNTRY_MAP
    for inst in _INSTITUTION_COUNTRY_MAP:
        if inst in candidate.span:
            score += SCORE_EXACT_KEYWORD
            break
    return score


def _rerank_evidence(
    candidates: list[EvidenceCandidate],
    category: str,
) -> list[EvidenceCandidate]:
    """
    PR 25 — 근거 후보 리랭크.

    점수 계산 후 내림차순 정렬. AI 호출 없음.
    """
    for c in candidates:
        c.relevance_score = _score_candidate(c, category)
    return sorted(candidates, key=lambda c: c.relevance_score, reverse=True)


def _build_citation_record(
    question: "ReaderQuestion",
    candidates: list[EvidenceCandidate],
    source_url: str = "",
    source_type: Optional[str] = None,
) -> dict:
    """
    PR 25 — 질문 단위 citation 레코드 빌드.

    최상위 후보를 best_evidence 로, 나머지를 alternatives 로 기록.
    """
    best = candidates[0] if candidates else None

    return {
        "question": question.question,
        "category": question.category,
        "status": question.status,
        "source_url": source_url,
        "source_type": source_type,
        # best evidence
        "best_evidence": {
            "span": best.span if best else "",
            "span_start": best.span_start if best else -1,
            "span_end": best.span_end if best else -1,
            "source": best.source if best else "",
            "relevance_score": best.relevance_score if best else 0,
        } if best else None,
        # alternatives (최대 2개)
        "alternatives_count": max(0, len(candidates) - 1),
        "alternatives": [
            {
                "span": c.span[:60],
                "source": c.source,
                "relevance_score": c.relevance_score,
            }
            for c in candidates[1:3]
        ],
    }


def _build_citation_report(
    questions: list["ReaderQuestion"],
    source_text: str,
    key_facts: list[str],
    source_url: str = "",
    source_type: Optional[str] = None,
) -> list[dict]:
    """
    PR 25 — 전체 질문에 대한 citation report 빌드.

    각 질문별로 근거 후보 수집 → rerank → citation 레코드 생성.
    best evidence 를 ReaderQuestion.evidence_snippet 에 보강.

    반환: citation 레코드 리스트
    """
    report: list[dict] = []

    for q in questions:
        candidates = _collect_evidence_candidates(
            source_text, key_facts, q.category,
        )
        ranked = _rerank_evidence(candidates, q.category)

        record = _build_citation_record(
            q, ranked, source_url, source_type,
        )
        report.append(record)

        # best evidence 로 snippet 보강 (기존 snippet 이 비어있거나 짧을 때)
        if ranked and q.status == "RESOLVED":
            best = ranked[0]
            # PR 28: 길이뿐 아니라 점수가 높은 span이면 교체 (짧더라도)
            if (best.relevance_score >= SCORE_SOURCE_TEXT
                    or len(best.span) > len(q.evidence_snippet)):
                q.evidence_snippet = best.span[:50]

    return report
