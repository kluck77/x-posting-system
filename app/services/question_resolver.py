"""
독자 질문 생성/해결/검증 모듈
==============================
PR 11/12/16 — CandidateCard에서 독자 핵심 질문을 생성하고,
source_text에서 답을 찾아 해결 여부를 판정한다.
AI 호출 없음 — 모두 결정론.

content_pack.py 에서 분리됨 (PR 21).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.content_pack import CandidateCard


# ─── PR 11/12/16: ReaderQuestion 데이터클래스 ───────────────────────────────

@dataclass
class ReaderQuestion:
    """PR 11/12/16 — 독자 핵심 질문 1개. 카테고리별 생성 + source 대조."""
    question: str = ""
    category: str = ""        # "SOURCE" | "SCOPE" | "IMPACT" | "CHECKPOINT"
    status: str = "UNRESOLVED"  # "RESOLVED" | "UNRESOLVED"
    evidence: str = ""         # 해결 시 근거 요약
    # PR 16 — Evidence Snippet Layer
    evidence_snippet: str = ""   # 해결 근거 원문 스니펫 (최대 50자)
    evidence_source: str = ""    # "SOURCE_TEXT" | "EXTERNAL" | ""


# ─── PR 12 Layer C: 질문 해결 패턴 ─────────────────────────────────────────

_SOURCE_CITATION_RE = re.compile(
    r"에 따르면|발표했다|밝혔다|보도했다|전했다|공개했다|확인했다|"
    r"공시했다|발간했다|보고서|공식 발표|공식 확인|"
    # PR 12 Layer C — 기관명+동사 조합 강화
    r"announced|according to|said|reported|disclosed"
)

_SCOPE_NUMBER_RE = re.compile(
    r"\d[\d,.]*\s*[%원달러조억만개건호명세대가구]|"
    # PR 12 Layer C — 영문 단위 보강
    r"\$\s*\d[\d,.]*|"
    r"\d[\d,.]*\s*(?:billion|million|trillion|percent|USD|KRW|EUR)"
)

_IMPACT_MARKER_PATTERNS = [
    "월 ", "일부터", "일까지", "분기", "년 ",
    "시행", "적용", "반영", "대상", "해당",
    # PR 12 Layer C — 시장/생활 반영 경로 패턴 추가
    "원가", "수요", "공급", "매출", "가동률", "수익성",
    "생활비", "집행", "입금", "공시",
]

# PR 12 Layer C — CHECKPOINT evidence 패턴
_CHECKPOINT_EVIDENCE_PATTERNS = [
    "시행일", "발표 예정", "공개 예정", "집계",
    "나오면", "공개되면", "집계되면", "시행되면", "확인되면",
    "실제 참여율", "원본 데이터", "공식 발표",
    "예정이다", "예정이며", "예정으로",
]


# ─── PR 12 v2: 독자 질문 생성 ──────────────────────────────────────────────

def _generate_reader_questions(
    card: "CandidateCard", mode: str,
) -> list["ReaderQuestion"]:
    """
    PR 12 v2 — 카드 데이터에서 독자 핵심 질문 4개 생성.

    카테고리:
      SOURCE     — 핵심 팩트의 구체적 근거/원본 출처
      SCOPE      — 구체적 수치/규모/대상
      IMPACT     — 영향 경로/다음 확인 시점
      CHECKPOINT — 다음에 뭘 보면 진짜/가짜가 갈리나

    mode별 우선순위:
      VERIFY:   SOURCE → CHECKPOINT → SCOPE → IMPACT
      EXPLAIN:  SOURCE → SCOPE → IMPACT → CHECKPOINT
      JUDGMENT: SOURCE → SCOPE → IMPACT → CHECKPOINT

    AI 호출 없음. 카드 필드에서 결정론으로 생성.
    """
    kf = card.key_facts if card.key_facts else []
    tc = card.thesis_cards if card.thesis_cards else []
    tens = card.tensions if card.tensions else []

    # ── Q-SOURCE: 출처/근거 ──
    if kf:
        core = kf[0][:40].rstrip(".")
        if mode == "VERIFY":
            q_source = f"'{core}' — 이 주장의 원본 출처/공식 확인은?"
        else:
            q_source = f"'{core}' — 이 사실의 구체적 근거/수치는?"
    else:
        q_source = "핵심 주장의 구체적 근거/원본 출처는?"

    # ── Q-SCOPE: 범위/구체성 ──
    if mode == "JUDGMENT" and tens:
        core_t = tens[0][:30].rstrip(".")
        q_scope = f"'{core_t}' — 양측 근거의 데이터 차이는?"
    elif tc and tc[0].reader_stake:
        stake = tc[0].reader_stake[:30].rstrip(".")
        q_scope = f"'{stake}' — 구체적 수치/규모/대상은?"
    elif len(kf) > 1:
        core2 = kf[1][:30].rstrip(".")
        q_scope = f"'{core2}' — 구체적 범위/대상은?"
    else:
        q_scope = "구체적 수치/규모/대상이 특정됐는가?"

    # ── Q-IMPACT: 영향/시점 ──
    if mode == "VERIFY":
        q_impact = "다음 공식 발표/확인 시점은?"
    elif tc and tc[0].thesis:
        t_core = tc[0].thesis[:30].rstrip(".")
        q_impact = f"'{t_core}' 가 맞으면 어디에 먼저 반영되나?"
    else:
        q_impact = "이게 맞으면 어디에 먼저 반영되나?"

    # ── Q-CHECKPOINT: 다음 확인 신호 ──
    if mode == "VERIFY":
        q_checkpoint = "어떤 공식 데이터/발표가 나오면 사실 확인이 되나?"
    elif mode == "JUDGMENT" and tens:
        ck_t = tens[0][:25].rstrip(".")
        q_checkpoint = f"'{ck_t}' — 어느 쪽이 맞는지 갈리는 다음 신호는?"
    elif tc and tc[0].thesis:
        ck_core = tc[0].thesis[:25].rstrip(".")
        q_checkpoint = f"'{ck_core}' — 다음에 뭘 보면 확인되나?"
    else:
        q_checkpoint = "다음에 어떤 데이터/발표가 나오면 확인 가능한가?"

    # ── mode별 순서 조립 ──
    rq = lambda q, cat: ReaderQuestion(question=q, category=cat)
    if mode == "VERIFY":
        # VERIFY: SOURCE → CHECKPOINT → SCOPE → IMPACT
        questions = [
            rq(q_source, "SOURCE"),
            rq(q_checkpoint, "CHECKPOINT"),
            rq(q_scope, "SCOPE"),
            rq(q_impact, "IMPACT"),
        ]
    else:
        # EXPLAIN / JUDGMENT: SOURCE → SCOPE → IMPACT → CHECKPOINT
        questions = [
            rq(q_source, "SOURCE"),
            rq(q_scope, "SCOPE"),
            rq(q_impact, "IMPACT"),
            rq(q_checkpoint, "CHECKPOINT"),
        ]

    return questions


def _resolve_questions_from_source(
    questions: list["ReaderQuestion"],
    source_text: str,
) -> list["ReaderQuestion"]:
    """
    PR 12 v2 — source_text 에서 각 질문의 답을 검색.

    AI 호출 없음. 패턴 매칭으로 해결 여부만 판정.
    못 찾으면 UNRESOLVED 유지 — 억지 해석 금지.
    evidence resolver 에서 해석 생성 금지 — 근거 탐지와 해결 여부만.
    """
    if not source_text:
        return questions

    for q in questions:
        if q.category == "SOURCE":
            m = _SOURCE_CITATION_RE.search(source_text)
            if m:
                q.status = "RESOLVED"
                q.evidence = "원문 출처 인용 존재"
                q.evidence_snippet = m.group()[:50]
                q.evidence_source = "SOURCE_TEXT"
        elif q.category == "SCOPE":
            m = _SCOPE_NUMBER_RE.search(source_text)
            if m:
                q.status = "RESOLVED"
                q.evidence = "원문 구체 수치 존재"
                q.evidence_snippet = m.group()[:50]
                q.evidence_source = "SOURCE_TEXT"
        elif q.category == "IMPACT":
            hits = [p for p in _IMPACT_MARKER_PATTERNS if p in source_text]
            if len(hits) >= 2:
                q.status = "RESOLVED"
                q.evidence = "원문 시점/대상 특정"
                q.evidence_snippet = ", ".join(hits[:3])[:50]
                q.evidence_source = "SOURCE_TEXT"
        elif q.category == "CHECKPOINT":
            hits = [p for p in _CHECKPOINT_EVIDENCE_PATTERNS if p in source_text]
            if len(hits) >= 1:
                q.status = "RESOLVED"
                q.evidence = "원문 검증 시점/조건 특정"
                q.evidence_snippet = hits[0][:50]
                q.evidence_source = "SOURCE_TEXT"
    return questions


def _build_question_prompt_section(
    questions: list["ReaderQuestion"],
) -> str:
    """
    PR 12 v2 — 질문 해결 상태를 finalize user_prompt 에 삽입할 섹션으로 조립.

    원칙: source_text 원문은 전달하지 않는다(요약 회귀 방지).
    해결/미해결 라벨만 전달해 AI 가 참고하게 한다.
    """
    if not questions:
        return ""
    _CAT_LABELS = {
        "SOURCE": "출처/근거",
        "SCOPE": "범위/규모",
        "IMPACT": "영향/시점",
        "CHECKPOINT": "다음 확인 신호",
    }
    section = "\n━━━ 독자 핵심 질문 (Reader Questions) ━━━\n"
    section += "이 기사에서 독자가 실제로 궁금해할 질문:\n"
    for i, q in enumerate(questions, 1):
        label = "해결됨" if q.status == "RESOLVED" else "미해결"
        cat_label = _CAT_LABELS.get(q.category, q.category)
        section += f"  Q{i} [{label}·{cat_label}]: {q.question}\n"
    section += (
        "\n원칙:\n"
        "- 해결된 질문 = 본문에 근거 기반으로 반영하라.\n"
        "- 미해결 질문 = 억지 해석 금지. "
        "'아직 확인 안 됨' 또는 '원문 미확인' 으로 남겨라.\n"
        "- CHECKPOINT 질문 = 마지막 문장에 '다음 확인 신호' 로 반영하라.\n"
    )
    return section


def _validate_question_coverage(
    post: str,
    questions: list["ReaderQuestion"],
    mode: str,
) -> tuple[list[str], list[str]]:
    """
    PR 11 — 최종 post 가 독자 질문을 얼마나 반영했는지 검사.

    반환: (warnings, gate_tags)
      UNRESOLVED_READER_QUESTION 는 WARN-only.
      _STRONG_FAIL_TAGS 에 넣지 않는다 (재생성 루프 금지).
    """
    warnings: list[str] = []
    gate_tags: list[str] = []

    if not questions:
        return warnings, gate_tags

    unresolved = [q for q in questions if q.status == "UNRESOLVED"]
    total = len(questions)

    if len(unresolved) >= 2:
        severity = "강한 경고" if mode == "VERIFY" else "경고"
        warnings.append(
            f"[{severity}] 독자 핵심 질문 {len(unresolved)}/{total}개 미해결 "
            "— 원문에 근거 부족"
        )
        gate_tags.append("UNRESOLVED_READER_QUESTION")
    elif len(unresolved) == 1:
        warnings.append(
            f"독자 핵심 질문 1/{total}개 미해결: "
            f"{unresolved[0].question[:40]}"
        )

    return warnings, gate_tags
