"""
diagnose_quality_guard.py
=========================
draft 1388, 1390 의 실제 sidecar (runtime_x/packs/{id}.json) 를 읽어
quality guard 4개 감지 함수의 동작을 추적한다. false negative 원인을
특정하기 위한 1회성 진단 도구.

Phase 1.5 판단 근거 수집 전용. Phase 1.5 패치 배포 후 삭제 또는
scripts/archive/ 로 이동한다.

실행:
    python scripts/diagnose_quality_guard.py \
        > diagnose_output_$(date +%Y%m%d_%H%M).log 2>&1

주의:
- sidecar JSON 은 서버(/root/x-posting-system/runtime_x/packs/) 에만 있음.
  로컬 개발 환경엔 보통 없음. 그 경우 "pack 파일 없음" 으로 찍힘 — 정상.
  실 진단은 서버 SSH 후 같은 스크립트를 돌려야 한다.
- DB 에는 draft 메타만 저장되고 source_pack/angle_pack 은 sidecar JSON
  에 있으므로 DB 쿼리 대신 pack_sidecar.load_pack 재사용.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트 import 경로 확보
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.handoff_quality_guard import (  # noqa: E402
    detect_angle_pack_heuristic,
    detect_concept_translation_misuse,
    detect_confirmed_facts_empty,
    detect_english_residue,
    run_quality_guard,
)
from app.services.pack_sidecar import load_pack  # noqa: E402

TARGET_DRAFT_IDS = [1388, 1390]
_MAX_WALK_DEPTH = 6


# ─── loaders ────────────────────────────────────────────────────────────

def load_source_pack(draft_id: int) -> dict | None:
    """
    sidecar JSON 에서 (source_pack, angle_pack) 를 꺼내 병합 dict 로 반환.
    파일 없음 / 파싱 실패 시 None.
    """
    pack = load_pack(draft_id)
    if not isinstance(pack, dict):
        return None
    # orchestrator 가 sidecar 에 저장할 때 {"source":..., "angle":..., ...}
    sp = pack.get("source")
    ap = pack.get("angle")
    # quality guard 는 source_pack 하나에 angle_pack 가 내부 키로 있는 형태를 기대.
    # format_handoff 내부에서도 동일한 병합 수행.
    guard_input: dict = dict(sp) if isinstance(sp, dict) else {}
    if isinstance(ap, dict):
        guard_input["angle_pack"] = ap
    # sidecar 에 저장된 원본 필드(final_body/handoff/labels) 도 참고용으로 노출
    for extra in ("final_body", "handoff", "labels"):
        if extra in pack:
            guard_input[f"__{extra}"] = pack[extra]
    return guard_input


# ─── walkers ────────────────────────────────────────────────────────────

def walk_and_find(obj: Any, needle: str, path: str = "", depth: int = 0) -> list[tuple[str, Any]]:
    """
    중첩 dict/list 에서 needle 이 값(str) 또는 key 에 포함된 모든 경로 수집.
    `_MAX_WALK_DEPTH` 이상은 중단하여 무한루프/과도한 출력 방지.
    """
    found: list[tuple[str, Any]] = []
    if depth > _MAX_WALK_DEPTH:
        return found
    low = needle.lower()
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_path = f"{path}.{k}" if path else str(k)
            if low in str(k).lower():
                found.append((key_path, v))
            if isinstance(v, str) and low in v.lower():
                found.append((key_path, v))
            if isinstance(v, (dict, list)):
                found.extend(walk_and_find(v, needle, key_path, depth + 1))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            key_path = f"{path}[{i}]"
            if isinstance(item, str) and low in item.lower():
                found.append((key_path, item))
            if isinstance(item, (dict, list)):
                found.extend(walk_and_find(item, needle, key_path, depth + 1))
    return found


def preview_value(value: Any, max_len: int = 120) -> str:
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        s = value.strip().replace("\n", " ")
        if len(s) > max_len:
            return f"{s[:max_len]}… (len={len(value)})"
        return f"{s!r} (len={len(value)})"
    if isinstance(value, list):
        first = preview_value(value[0], 60) if value else "<empty>"
        return f"list(len={len(value)}) first={first}"
    if isinstance(value, dict):
        keys = list(value.keys())
        return f"dict(keys={keys})"
    return f"<{type(value).__name__}>"


# ─── diagnosis ──────────────────────────────────────────────────────────

def diagnose_draft(draft_id: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"DIAGNOSING DRAFT {draft_id}")
    print(f"{'=' * 70}")

    source_pack = load_source_pack(draft_id)
    if source_pack is None:
        print(f"\n!!! draft {draft_id} sidecar 없음: "
              f"{Path('/root/x-posting-system/runtime_x/packs') / f'{draft_id}.json'}")
        print("    로컬에서 실행했다면 서버에서 동일 스크립트를 돌려야 한다.")
        return

    # [1] top-level keys
    print("\n[1] source_pack top-level keys")
    for key in source_pack.keys():
        print(f"  {key}: {preview_value(source_pack[key])}")

    # [2] heuristic 문자열
    print("\n[2] 'heuristic' 문자열 포함 필드 (angle_heuristic 추적)")
    hits = walk_and_find(source_pack, "heuristic")
    if not hits:
        print("  (발견 없음)")
    for path, value in hits:
        print(f"  {path}: {preview_value(value)}")

    # [3] edit_goal 관련 경로 (중복 제거)
    print("\n[3] edit_goal / goal 관련 필드 경로")
    seen_paths: set[str] = set()
    for candidate_key in ["edit_goal", "editGoal", "editorial_goal", "goal"]:
        for path, value in walk_and_find(source_pack, candidate_key):
            if path in seen_paths:
                continue
            if candidate_key in path.lower():
                seen_paths.add(path)
                print(f"  {path}: {preview_value(value)}")

    # [4] confirmed_facts 후보 필드
    print("\n[4] confirmed_facts 후보 필드")
    seen_paths.clear()
    for key_name in [
        "confirmed_facts", "facts", "absolute_facts",
        "preserve", "do_not_change", "confirmed",
    ]:
        for path, value in walk_and_find(source_pack, key_name):
            if path in seen_paths:
                continue
            if key_name in path.lower():
                seen_paths.add(path)
                print(f"  {path}:")
                if isinstance(value, list):
                    print(f"    length: {len(value)}")
                    for i, item in enumerate(value[:3]):
                        print(f"    [{i}]: {preview_value(item)}")
                else:
                    print(f"    {preview_value(value)}")

    # [5] 감지 함수 개별
    print("\n[5] 감지 함수별 결과")
    detectors = [
        (detect_angle_pack_heuristic, "angle_heuristic"),
        (detect_confirmed_facts_empty, "facts_empty"),
        (detect_english_residue, "english_residue"),
        (detect_concept_translation_misuse, "concept_translation_misuse"),
    ]
    for fn, name in detectors:
        try:
            result = fn(source_pack)
            status = "DETECTED" if result else "NOT_DETECTED"
            print(f"  {name}: {status}")
            if result:
                print(f"    severity: {result['severity']}")
                print(f"    evidence: {result['evidence']}")
        except Exception as e:
            print(f"  {name}: ERROR — {type(e).__name__}: {e}")

    # [6] run_quality_guard 집계
    print("\n[6] run_quality_guard 집계")
    aggregate = run_quality_guard(source_pack)
    print(f"  high_count: {aggregate['high_count']}")
    print(f"  medium_count: {aggregate['medium_count']}")
    print(f"  block_recommended: {aggregate['block_recommended']}")
    print("  rendered_warning_block:")
    for line in (aggregate.get("rendered_warning_block") or "").splitlines():
        print(f"    {line}")


def dump_test_fixture() -> None:
    """단위 테스트에서 사용 중인 draft_1388 fixture 의 구조 출력.
    프로덕션 sidecar 와 구조 비교용."""
    print(f"\n{'=' * 70}")
    print("TEST FIXTURE (tests/test_handoff_quality_guard.py::_draft_1388_pack)")
    print(f"{'=' * 70}")

    try:
        from tests.test_handoff_quality_guard import _draft_1388_pack
        fixture = _draft_1388_pack()
    except Exception as e:
        print(f"  !!! fixture import 실패: {type(e).__name__}: {e}")
        return

    print("\n[fixture top-level keys]")
    for key in fixture.keys():
        print(f"  {key}: {preview_value(fixture[key])}")

    print("\n[fixture 전체 구조 (JSON)]")
    print(json.dumps(fixture, indent=2, ensure_ascii=False, default=str))

    print("\n[fixture 감지 함수 결과 — 기준선]")
    for fn, name in [
        (detect_angle_pack_heuristic, "angle_heuristic"),
        (detect_confirmed_facts_empty, "facts_empty"),
        (detect_english_residue, "english_residue"),
        (detect_concept_translation_misuse, "concept_translation_misuse"),
    ]:
        try:
            r = fn(fixture)
            status = "DETECTED" if r else "NOT_DETECTED"
            evidence = f" evidence={r['evidence']}" if r else ""
            print(f"  {name}: {status}{evidence}")
        except Exception as e:
            print(f"  {name}: ERROR — {type(e).__name__}: {e}")


def main() -> None:
    print(f"env PACK_DIR_EXISTS: {Path('/root/x-posting-system/runtime_x/packs').exists()}")
    print(f"env CWD: {os.getcwd()}")
    dump_test_fixture()
    for draft_id in TARGET_DRAFT_IDS:
        try:
            diagnose_draft(draft_id)
        except Exception as e:
            print(f"\n!!! DRAFT {draft_id} 진단 실패: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
