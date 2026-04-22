"""Hard Rule Checker (L1 — 결정론적 강제).

editorial/banned_terms.yaml 을 로드해서 초안 텍스트에 결정론적
규칙 위반을 검사한다.

1. regex/surface 패턴 (문자열 일치)
2. morpheme 패턴 (kiwipiepy 로드 가능할 때만)
3. 문체 혼용 (존댓말/반말/음슴체 종결어미 mix — kiwipiepy)
4. 마크다운 별표
5. 이모지 4개 이상

kiwipiepy 로드 실패 시 regex/별표/이모지 체크만 동작 (fail-soft).
"""
from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

try:
    from kiwipiepy import Kiwi  # type: ignore
    _KIWI = Kiwi(model_type="cong")
    _KIWI_AVAILABLE = True
except Exception as _e:
    logger.warning(f"[HardRule] kiwipiepy 로드 실패 (regex 전용 모드): {_e}")
    _KIWI = None
    _KIWI_AVAILABLE = False

HONORIFIC_EF = {"습니다", "ㅂ니다", "해요", "예요", "이에요", "세요", "어요", "네요"}
PLAIN_EF = {"다", "ㄴ다", "는다", "지", "군", "구나"}


@lru_cache(maxsize=1)
def _load_patterns() -> list[dict]:
    path = Path("editorial/banned_terms.yaml")
    if not path.exists():
        logger.warning(f"[HardRule] banned_terms.yaml 없음: {path}")
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("patterns", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.warning(f"[HardRule] banned_terms.yaml 로드 실패: {e}")
        return []


@dataclass
class Violation:
    rule_id: str
    surface: str
    category: str
    severity: str


@dataclass
class HardRuleResult:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    duration_ms: float = 0.0
    rewrite_instruction: str = ""


def check(text: str) -> HardRuleResult:
    """초안 텍스트에 hard rule 검사. passed=True 면 block 위반 없음."""
    t0 = time.perf_counter()
    violations: list[Violation] = []
    if not text:
        return HardRuleResult(passed=True, violations=[], duration_ms=0.0)
    patterns = _load_patterns()

    # 1. regex / surface 금지어
    for p in patterns:
        mode = p.get("match_mode", "surface")
        if mode not in ("surface", "regex"):
            continue
        rx = p.get("regex")
        if not rx:
            continue
        try:
            for m in re.finditer(rx, text, re.IGNORECASE):
                ctx = p.get("context_rules") or {}
                allow = ctx.get("allow_if_contains", []) if isinstance(ctx, dict) else []
                window = text[max(0, m.start() - 40): m.end() + 40]
                if any(k in window for k in allow):
                    continue
                violations.append(Violation(
                    rule_id=p.get("id", "?"),
                    surface=m.group(0),
                    category=p.get("category", "misc"),
                    severity=p.get("severity", "warn"),
                ))
        except re.error:
            pass

    # 2. 형태소 기반 (kiwipiepy 필요)
    if _KIWI_AVAILABLE:
        try:
            tokens = _KIWI.tokenize(text)
            for p in patterns:
                if p.get("match_mode") != "morpheme":
                    continue
                lemma = p.get("lemma")
                if not lemma:
                    continue
                pos_filter = p.get("pos_filter", []) or []
                for tok in tokens:
                    if tok.form != lemma:
                        continue
                    if pos_filter and tok.tag not in pos_filter:
                        continue
                    violations.append(Violation(
                        rule_id=p.get("id", "?"),
                        surface=tok.form,
                        category=p.get("category", "misc"),
                        severity=p.get("severity", "warn"),
                    ))
        except Exception as e:
            logger.warning(f"[HardRule] morpheme 검사 실패 (무시): {e}")

    # 3. 문체 혼용 (존댓말 / 반말 / 음슴체 종결어미 mix)
    if _KIWI_AVAILABLE:
        try:
            sents = _KIWI.split_into_sents(text, return_tokens=True)
            styles: set[str] = set()
            for s in sents:
                for tok in reversed(s.tokens):
                    if tok.tag == "EF":
                        if tok.form in HONORIFIC_EF:
                            styles.add("honorific")
                            break
                        if tok.form in PLAIN_EF:
                            styles.add("plain")
                            break
            if len(styles) > 1:
                violations.append(Violation(
                    rule_id="style_mix",
                    surface=",".join(sorted(styles)),
                    category="consistency",
                    severity="block",
                ))
        except Exception as e:
            logger.warning(f"[HardRule] 문체 검사 실패 (무시): {e}")

    # 4. 마크다운 별표 (정규식 직접 — banned_terms.yaml 에도 있지만 이중 방어)
    if re.search(r"\*\*[^\*]+\*\*", text):
        violations.append(Violation(
            rule_id="markdown_bold",
            surface="**...**",
            category="ai_syntax",
            severity="block",
        ))

    # 5. 이모지 4개 이상
    emoji_count = len(re.findall(
        r"[\U0001F300-\U0001FAD6"
        r"\U0001F600-\U0001F64F"
        r"\U0001F680-\U0001F6FF"
        r"☀-➿]",
        text,
    ))
    if emoji_count >= 4:
        violations.append(Violation(
            rule_id="emoji_overflow",
            surface=f"이모지 {emoji_count}개",
            category="ai_syntax",
            severity="block",
        ))

    blocked = any(v.severity == "block" for v in violations)
    rewrite = ""
    if violations:
        vids = [v.rule_id for v in violations if v.severity == "block"]
        if vids:
            rewrite = f"다음 규칙 위반 수정 필수: {', '.join(vids)}"

    return HardRuleResult(
        passed=not blocked,
        violations=violations,
        duration_ms=(time.perf_counter() - t0) * 1000,
        rewrite_instruction=rewrite,
    )
