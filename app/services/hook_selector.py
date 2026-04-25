"""훅 후보 자동 선정 — 6 패턴 매칭 + 룰 통과 필터.

핸드오프 빌더(grok_handoff)/orchestrator 가 호출. handoff_builder 라는
파일이 프로젝트에 없어 별도 모듈로 분리. handoff_quality_guard.judge()
의 _check_hook_candidates 와 룰 일관성 유지.
"""
from __future__ import annotations

import re

# 6 패턴 — ① 반전 / ② 수치 / ③ 시점 / ④ 모순 / ⑤ 선언 / ⑥ 사실 폭로(default)
HOOK_PATTERNS: dict[str, str] = {
    "①": r".+(는|은)\s.+(이|가)\s아니다",
    "②": r"\d+[\d,]*[원달러억조]\s.+",
    "③": r"(새벽|오후|오전).+\d+시",
    "④": r".+(올랐|상승|증가).+(내렸|하락|감소)",
    "⑤": r".+(끝났다|시작됐다|무너졌다)",
}

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF]"
)


def select_best_hooks(
    candidates: list[str],
    max_count: int = 3,
) -> list[dict]:
    """훅 후보에서 룰 통과한 것만 선택.

    반환: [{"text": "...", "char_count": int, "pattern": "①..⑥"}].
    룰: 14~25자, 마침표 없음, 대시 없음, 이모지 없음.
    """
    selected: list[dict] = []
    for raw in candidates or []:
        cand = (raw or "").strip()
        if not cand:
            continue

        # 번호·패턴·자수 prefix 제거 (혼합 입력 허용)
        cand = re.sub(r"^\s*\d+\.\s*", "", cand)
        cand = re.sub(r"\[패턴.\]\s*", "", cand)
        cand = re.sub(r"\(\d+자\)\s*", "", cand).strip()
        if not cand:
            continue

        char_count = len(cand)
        if char_count > 25 or char_count < 14:
            continue
        if cand.endswith("."):
            continue
        if "—" in cand or " - " in cand:
            continue
        if EMOJI_RE.search(cand):
            continue

        # 패턴 매칭 — 매치 안 되면 ⑥ 사실 폭로 default
        pattern_num = "⑥"
        for num, regex in HOOK_PATTERNS.items():
            if re.search(regex, cand):
                pattern_num = num
                break

        selected.append({
            "text":       cand,
            "char_count": char_count,
            "pattern":    pattern_num,
        })
        if len(selected) >= max_count:
            break

    return selected


def format_hook_candidates(hooks: list[dict]) -> str:
    """훅 후보를 핸드오프 문서 형식으로 포맷."""
    if not hooks:
        return "훅 후보 없음 (모두 룰 위반)"
    lines = []
    for i, h in enumerate(hooks, 1):
        lines.append(
            f"{i}. [패턴{h.get('pattern', '⑥')}] "
            f"({int(h.get('char_count', 0))}자) {h.get('text', '')}"
        )
    return "\n".join(lines)
