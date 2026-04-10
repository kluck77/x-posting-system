"""
scripts/patch_rate_limit_lanes.py
=================================
서버 orchestrator.py 에 레인별 rate limit 적용.

변경 내용:
1. Step 0 의 can_create_draft() 호출을 제거 (주석 처리)
2. Step 2 직전에 can_run_ai_pipeline(source_type) 호출 삽입

실행 방법:
    /root/x-posting-system/venv/bin/python scripts/patch_rate_limit_lanes.py

롤백:
    cp /tmp/orchestrator.py.bak.lanes app/orchestrator.py
    systemctl restart xdashboard
"""

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORCH = ROOT / "app" / "orchestrator.py"
BACKUP = Path("/tmp/orchestrator.py.bak.lanes")

# rate_limiter.py 도 교체 필요
RATE_LIMITER = ROOT / "app" / "services" / "rate_limiter.py"
RATE_LIMITER_BACKUP = Path("/tmp/rate_limiter.py.bak.lanes")


def patch_orchestrator():
    """orchestrator.py 에서 rate limit 위치를 Step 0 → Step 2 직전으로 이동."""
    text = ORCH.read_text(encoding="utf-8")

    # --- 1) Step 0 의 can_create_draft 호출 비활성화 ---
    # 서버 orchestrator 의 Step 0 패턴:
    #   can_draft, draft_msg = self.rate_limiter.can_create_draft()
    #   if not can_draft:
    #       raise RuntimeError(...)
    pattern_step0 = re.compile(
        r"([ \t]*# Step 0.*일일 제한.*\n)"
        r"([ \t]*can_draft, draft_msg = self\.rate_limiter\.can_create_draft\(\)\n)"
        r"([ \t]*if not can_draft:\n)"
        r"([ \t]*raise RuntimeError\(f\"일일 제한 초과:.*\n)",
        re.MULTILINE,
    )

    match = pattern_step0.search(text)
    if not match:
        # 이미 패치됨 또는 패턴 불일치
        # 대안: 더 느슨한 패턴 시도
        if "can_run_ai_pipeline" in text:
            print("이미 패치됨 — orchestrator.py 스킵")
            return True

        # 더 느슨한 패턴
        if "can_create_draft()" in text:
            # 줄 단위로 주석 처리
            lines = text.split("\n")
            new_lines = []
            in_step0 = False
            replaced = False
            for line in lines:
                if "can_create_draft()" in line and not line.strip().startswith("#"):
                    indent = line[: len(line) - len(line.lstrip())]
                    new_lines.append(
                        f"{indent}# [LANE] rate check moved to Step 2"
                    )
                    new_lines.append(f"{indent}# {line.strip()}")
                    in_step0 = True
                    replaced = True
                elif in_step0 and ("if not can_draft" in line or "raise RuntimeError" in line):
                    indent = line[: len(line) - len(line.lstrip())]
                    new_lines.append(f"{indent}# {line.strip()}")
                    if "raise RuntimeError" in line:
                        in_step0 = False
                else:
                    new_lines.append(line)

            if replaced:
                text = "\n".join(new_lines)
            else:
                print("ERROR: can_create_draft() 패턴을 찾을 수 없습니다", file=sys.stderr)
                return False
        else:
            print("ERROR: Step 0 rate limit 패턴을 찾을 수 없습니다", file=sys.stderr)
            return False
    else:
        # 정규식 매치 — 주석 처리
        indent = match.group(2)[: len(match.group(2)) - len(match.group(2).lstrip())]
        replacement = (
            f"{indent}# Step 0: (rate check moved to Step 2 — Lane A~C는 AI 비용 없음)\n"
            f"{indent}# BREAKING_NOW / KO-only / Top5 적재 / 주간 즉시 알림은 항상 실행.\n"
            f"{indent}# AI 파이프라인(Steps 2-6)만 레인별 제한 적용.\n"
        )
        text = text[: match.start()] + replacement + text[match.end() :]

    # --- 2) Step 2 직전에 can_run_ai_pipeline 삽입 ---
    if "can_run_ai_pipeline" not in text:
        # "Researcher" 또는 "리서치" 를 찾아 그 직전에 삽입
        step2_pattern = re.compile(
            r"([ \t]*# Step 2.*Researcher.*\n[ \t]*logger\.info.*\[2/)",
            re.MULTILINE,
        )
        step2_match = step2_pattern.search(text)
        if not step2_match:
            # 대안 패턴
            step2_pattern = re.compile(
                r"([ \t]*# Step 2.*리서치.*\n)",
                re.MULTILINE,
            )
            step2_match = step2_pattern.search(text)

        if step2_match:
            indent = step2_match.group(1)[
                : len(step2_match.group(1)) - len(step2_match.group(1).lstrip())
            ]
            rate_block = (
                f"{indent}# Step 2 rate check: AI 파이프라인 진입 제한 (비용 보호)\n"
                f"{indent}# - KO-only/BREAKING 는 Step 1.7 에서 이미 리턴\n"
                f"{indent}# - source_type 으로 자동수집/수동입력 레인 분리\n"
                f"{indent}can_ai, ai_msg = self.rate_limiter.can_run_ai_pipeline(\n"
                f"{indent}    source_type=data.source_type,\n"
                f"{indent})\n"
                f"{indent}if not can_ai:\n"
                f"{indent}    raise RuntimeError(f\"일일 제한 초과: {{ai_msg}}\")\n"
                f"\n"
            )
            text = text[: step2_match.start()] + rate_block + text[step2_match.start() :]
        else:
            print("ERROR: Step 2 위치를 찾을 수 없습니다", file=sys.stderr)
            return False

    ORCH.write_text(text, encoding="utf-8")
    return True


def main():
    if not ORCH.exists():
        print(f"ERROR: {ORCH} not found", file=sys.stderr)
        sys.exit(1)

    # 백업
    shutil.copy2(ORCH, BACKUP)
    print(f"백업: {BACKUP}")

    if RATE_LIMITER.exists():
        shutil.copy2(RATE_LIMITER, RATE_LIMITER_BACKUP)
        print(f"백업: {RATE_LIMITER_BACKUP}")

    # orchestrator 패치
    if not patch_orchestrator():
        print("패치 실패 — 롤백하세요")
        sys.exit(1)

    # py_compile 검증
    import py_compile

    try:
        py_compile.compile(str(ORCH), doraise=True)
        print(f"OK: {ORCH} py_compile 통과")
    except py_compile.PyCompileError as e:
        print(f"SYNTAX ERROR: {e}", file=sys.stderr)
        shutil.copy2(BACKUP, ORCH)
        print("롤백 완료")
        sys.exit(1)

    print(
        f"\nOK: {ORCH} 패치 완료\n"
        f"  - Step 0 rate check 비활성화\n"
        f"  - Step 2 직전 can_run_ai_pipeline() 삽입\n"
        f"  - 롤백: cp {BACKUP} {ORCH}"
    )


if __name__ == "__main__":
    main()
