"""
시작 자가 진단
==============
앱 시작 시 영속 상태 파일을 검사하고 요약을 로깅합니다.
/recover 커맨드에서도 동일 정보를 반환합니다.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILES: dict[str, Path] = {
    "post_queue":        Path("data/post_queue.json"),
    "processed_replies": Path("data/processed_replies.json"),
    "activity":          Path("data/activity.json"),
    "monitor_state":     Path("data/monitor_state.json"),
}

_LABELS: dict[str, str] = {
    "post_queue":        "게시 큐",
    "processed_replies": "처리된 답글 ID",
    "activity":          "활동 추적기",
    "monitor_state":     "답글 모니터 상태",
}


def _check_file(label: str, path: Path) -> dict:
    """
    단일 파일 상태 검사.
    Returns:
        exists      — 파일 존재 여부
        valid_json  — None(없음) / True(정상) / False(손상)
        info        — 사람이 읽을 수 있는 상태 요약
        error       — 오류 메시지 (손상 시에만)
    """
    if not path.exists():
        return {"exists": False, "valid_json": None, "info": "파일 없음 (정상)", "error": None}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if label == "post_queue":
            q = data.get("queue", [])
            pending = sum(1 for p in q if not p.get("published_at"))
            info = f"{pending}개 대기 / {len(q)}개 전체"

        elif label == "processed_replies":
            if isinstance(data, list):
                info = f"{len(data)}개 처리 완료 ID"
            else:
                info = "형식 오류 (list 아님)"

        elif label == "activity":
            last = data.get("last_activity_at", "없음")
            trimmed = last[:19] if isinstance(last, str) and last != "없음" else "없음"
            info = f"마지막 활동: {trimmed}"

        elif label == "monitor_state":
            paused = data.get("reply_monitor_paused", False)
            info = f"답글 모니터: {'정지' if paused else '실행 중'}"

        else:
            info = f"{path.stat().st_size} bytes"

        return {"exists": True, "valid_json": True, "info": info, "error": None}

    except json.JSONDecodeError as e:
        return {
            "exists": True,
            "valid_json": False,
            "info": "JSON 파싱 오류",
            "error": str(e)[:120],
        }
    except Exception as e:
        return {
            "exists": True,
            "valid_json": False,
            "info": "읽기 오류",
            "error": str(e)[:120],
        }


def run_startup_check() -> dict[str, dict]:
    """
    모든 영속 상태 파일을 검사합니다.
    손상된 파일이 있으면 WARNING 로그 — 앱 시작은 계속됩니다.

    Returns:
        label → check result dict (exists, valid_json, info, error)
    """
    results = {label: _check_file(label, path) for label, path in _STATE_FILES.items()}

    bad = [k for k, r in results.items() if r["valid_json"] is False]
    if bad:
        logger.warning(
            f"[Startup] 상태 파일 손상 감지: {bad} — "
            "해당 파일을 삭제하면 자동 재생성됩니다."
        )

    logger.info(
        "[Startup] 상태 파일 점검 완료 — "
        + ", ".join(f"{k}: {r['info']}" for k, r in results.items())
    )
    return results


def format_recovery_summary(results: dict[str, dict]) -> str:
    """
    run_startup_check() 결과를 Telegram HTML 포맷으로 변환.
    /recover 커맨드에서 사용.
    """
    lines = ["🔍 <b>운영 상태 점검</b>\n"]

    for key, result in results.items():
        label = _LABELS.get(key, key)
        if not result["exists"]:
            icon = "⚪"
        elif result["valid_json"]:
            icon = "✅"
        else:
            icon = "❌"

        lines.append(f"{icon} <b>{label}:</b> {result['info']}")
        if result["error"]:
            lines.append(f"   ⚠️ <code>{result['error'][:80]}</code>")

    lines.append(
        "\n손상 파일은 <code>data/</code> 디렉터리에서 삭제하면 자동 재생성됩니다."
    )
    return "\n".join(lines)
