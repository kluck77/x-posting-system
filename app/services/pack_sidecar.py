"""
Pack Sidecar
============
Draft 의 out-of-DB 메타 (source_pack, angle_pack, grok_handoff) 를
`/root/x-posting-system/runtime_x/packs/{draft_id}.json` 에 저장한다.

설계 원칙:
- DB 스키마 변경 금지 → JSON 사이드카 파일.
- atomic write (tempfile.NamedTemporaryFile + os.replace) 로 중간 파일 보장.
- repo 밖 경로 (`runtime_x/`) 사용. 로컬 개발 안전장치로 .gitignore 에도 등록됨.
- 로드 실패(파일 없음/파싱 오류)는 None 을 반환. 호출 측에서 "레거시 초안" 분기 처리.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

PACK_DIR = Path("/root/x-posting-system/runtime_x/packs")


def _ensure_dir() -> Path:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    return PACK_DIR


def save_pack(draft_id: int, pack: dict) -> Path | None:
    """
    draft_id 기준 sidecar JSON 저장.

    반환:
      최종 파일 경로 (성공) / None (실패 — 로그만 남기고 삼킨다, 호출측 안전장치).
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        logger.warning(f"[pack_sidecar] invalid draft_id: {draft_id!r}")
        return None
    try:
        pack_dir = _ensure_dir()
        target = pack_dir / f"{draft_id}.json"
        with tempfile.NamedTemporaryFile(
            "w", dir=str(pack_dir), delete=False, encoding="utf-8", suffix=".tmp",
        ) as f:
            json.dump(pack, f, ensure_ascii=False, indent=2)
            tmp_path = f.name
        os.replace(tmp_path, target)
        logger.info(f"[pack_sidecar] saved: {target}")
        return target
    except Exception as e:
        logger.warning(f"[pack_sidecar] save failed (draft_id={draft_id}): {e}")
        return None


def load_pack(draft_id: int) -> dict | None:
    """
    draft_id 기준 sidecar 로드. 파일 없음/파싱 오류 → None.
    """
    if not isinstance(draft_id, int) or draft_id <= 0:
        return None
    try:
        target = PACK_DIR / f"{draft_id}.json"
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[pack_sidecar] load failed (draft_id={draft_id}): {e}")
        return None
