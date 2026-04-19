"""
Control Room API
================
대시보드 전용 읽기 엔드포인트 모음. Phase A 에선 /strategy-os 만 노출된다.
이 라우터는 app/api/admin.py 에서 include_router 로 연결된다.
"""
import logging
from fastapi import APIRouter

from app.services.strategy_os import default_strategy_os, load_strategy_os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/control", tags=["control"])


@router.get("/strategy-os")
async def get_strategy_os():
    """Strategy OS 읽기 전용. 실패해도 default 반환(대시보드 보호)."""
    try:
        return load_strategy_os()
    except Exception as e:
        logger.warning(f"[control_room] strategy-os 응답 실패, default 반환: {e}")
        return default_strategy_os()
