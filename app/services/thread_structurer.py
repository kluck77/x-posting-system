"""Thread Structurer — 초안을 단일 포스트 또는 스레드로 분해.

기준:
- 280자 이내 + 단일 주장 → Single post
- 280자 초과 또는 근거 3개 이상 → Thread (5~7 트윗)

Thread 구조 (7트윗 canonical):
  T1: Hook (28자 이내, 본문 첫 줄)
  T2: Context (배경 1문장)
  T3: Evidence-1 (첫 번째 근거/데이터)
  T4: Evidence-2 (메커니즘 또는 두 번째 데이터)
  T5: Korean Bridge (한국 엔티티 의무 포함)
  T6: Stake (⚠️ 진짜 쟁점)
  T7: Ending (📌 + 브랜드 클로즈)

5트윗 단축: T4 제거
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ThreadResult:
    is_thread: bool
    tweets: list[str] = field(default_factory=list)
    single_post: str = ""
    tweet_count: int = 0

    def to_context_block(self) -> str:
        if not self.is_thread:
            return f"[FORMAT: SINGLE POST]\n{self.single_post}"
        lines = [f"[FORMAT: THREAD {self.tweet_count}트윗]"]
        for i, t in enumerate(self.tweets, 1):
            lines.append(f"{i}/{self.tweet_count} {t}")
        return "\n".join(lines)


def _count_sentences(text: str) -> int:
    """문장 수 추정."""
    return len(re.split(r"[.!?。]\s+", text.strip()))


def _count_evidence(body: str) -> int:
    """근거/데이터 수 추정 — 숫자 포함 문장 카운트."""
    sentences = re.split(r"[.!?。]\s+", body)
    return sum(1 for s in sentences if re.search(r"\d", s))


def _split_body(body: str) -> list[str]:
    """body를 문장 단위로 분리."""
    raw = re.split(r"(?<=[.!?。])\s+", body.strip())
    return [s.strip() for s in raw if s.strip()]


def _extract_sections(body: str) -> dict[str, str]:
    """⚠️ 진짜 쟁점 / 📌 포인트 추출."""
    stake = ""
    point = ""
    lines = body.split("\n")
    for line in lines:
        if line.startswith("⚠️"):
            stake = line
        elif line.startswith("📌"):
            point = line
    return {"stake": stake, "point": point}


def structure(hook: str, body: str, frame_name: str = "") -> ThreadResult:
    """hook + body → ThreadResult."""
    # 단일 포스트 판정
    total_chars = len(hook) + len(body)
    evidence_count = _count_evidence(body)

    if total_chars <= 280 and evidence_count < 3:
        single = f"{hook}\n\n{body}".strip()
        return ThreadResult(
            is_thread=False,
            single_post=single,
            tweet_count=1,
        )

    # 스레드 분해
    sections = _extract_sections(body)
    sentences = _split_body(
        body.replace(sections["stake"], "").replace(sections["point"], "")
    )

    tweets: list[str] = []

    # T1: Hook
    tweets.append(hook.strip())

    # T2: Context (첫 문장)
    if sentences:
        tweets.append(sentences[0])

    # T3: Evidence-1 (두 번째 문장)
    if len(sentences) > 1:
        tweets.append(sentences[1])

    # T4: Evidence-2 (세 번째 문장, 있을 때만)
    if len(sentences) > 2:
        tweets.append(sentences[2])

    # T5: Korean Bridge
    # 남은 문장 중 한국 엔티티 포함 문장 우선
    kr_hints = ["업비트", "빗썸", "금융위", "한은", "DART", "VAUPA", "DABA",
                "카카오", "네이버", "SKT", "김치", "원화", "KRW"]
    bridge = ""
    for s in sentences[3:]:
        if any(h in s for h in kr_hints):
            bridge = s
            break
    if not bridge and len(sentences) > 3:
        bridge = sentences[3]
    if bridge:
        tweets.append(bridge)

    # T6: Stake
    if sections["stake"]:
        tweets.append(sections["stake"])

    # T7: Ending
    if sections["point"]:
        ending = sections["point"]
        if frame_name:
            ending += f"\n— 서울 데스크 [{frame_name}]"
        tweets.append(ending)

    # 트윗 수 정규화 (5~7)
    if len(tweets) > 7:
        tweets = tweets[:7]
    elif len(tweets) < 5:
        # 부족하면 single로 폴백
        single = f"{hook}\n\n{body}".strip()
        return ThreadResult(
            is_thread=False,
            single_post=single,
            tweet_count=1,
        )

    # 번호 붙이기
    n = len(tweets)
    numbered = [f"{i}/{n} {t}" for i, t in enumerate(tweets, 1)]

    return ThreadResult(
        is_thread=True,
        tweets=numbered,
        single_post="",
        tweet_count=n,
    )
