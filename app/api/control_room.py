"""
Control Room API
================
대시보드에서 소비하는 집계 엔드포인트.
기존 데이터(queue, rate-limiter, activity, drafts)를 하나의 뷰로 합칩니다.
새 데이터 구조는 추가하지 않습니다.
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from sqlalchemy import text

from app.config import settings
from app.db import get_db

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

router = APIRouter(prefix="/control", tags=["control-room"])


# ── 대시보드 HTML 페이지 ──────────────────────────────────────────────────────

@router.get("/", include_in_schema=False)
async def dashboard_page():
    """Control Room HTML 대시보드를 반환합니다."""
    html_path = Path("static/dashboard.html")
    if not html_path.exists():
        return {"error": "대시보드 파일이 없습니다. static/dashboard.html 을 확인하세요."}
    return FileResponse(html_path, media_type="text/html")


# ── 에셋 업로드 (캐릭터 이미지) ────────────────────────────────────────────────

_ALLOWED_ASSETS = {
    "hero_blonde_assistant.png",
    "draftwriter.png",
    "reviewer.png",
    "researcher.png",
    "factchecker.png",
    "trendhunter_black.png",
}

@router.post("/upload-asset", include_in_schema=False)
async def upload_asset(file: UploadFile = File(...)):
    """
    대시보드 캐릭터 이미지 업로드.
    허용된 파일명만 수락합니다 (화이트리스트).
    """
    if file.filename not in _ALLOWED_ASSETS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않은 파일명입니다. 허용 목록: {sorted(_ALLOWED_ASSETS)}",
        )
    static_dir = Path("static")
    static_dir.mkdir(exist_ok=True)
    dest = static_dir / file.filename
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB 제한
        raise HTTPException(status_code=400, detail="파일 크기가 10MB를 초과합니다.")
    dest.write_bytes(content)
    logger.info("asset uploaded: %s (%d bytes)", file.filename, len(content))
    return {"ok": True, "filename": file.filename, "size": len(content)}


# ── 비즈니스 스택 단일 집계 ──────────────────────────────────────────────────

@router.get("/business-summary")
async def get_business_summary():
    """
    완성된 비즈니스 운영 레이어를 단일 JSON으로 반환합니다.
    Premium / Brief / B2B / Newsletter / Lead / Weekly highlights / CTA performance.
    각 섹션은 독립적으로 실패할 수 있으며, 실패 시 빈 값으로 대체됩니다.
    """
    db = get_db()
    try:
        result = {
            "premium": _safe_premium(db),
            "brief": _safe_brief(db),
            "b2b": _safe_b2b(db),
            "newsletter": _safe_newsletter(db),
            "weekly": _safe_weekly_compact(db),
            "cta_perf": _safe_cta_perf(db),
        }
        return result
    finally:
        db.close()


def _safe_premium(db) -> dict:
    try:
        from app.services.premium_candidate_service import PremiumCandidateService
        svc = PremiumCandidateService(db)
        counts = svc.count_by_status()
        # limit=20 로 상향 — 시트 스크롤로 전체 후보 브라우징 가능
        top = svc.get_candidates(limit=20)
        return {
            "total": sum(counts.values()),
            "status": counts,
            "top": [
                {
                    "id": d.id,
                    "hook": (d.hook or "")[:70],
                    "status": d.premium_status or "new",
                    "score": d.monetization_score,
                }
                for d in top
            ],
        }
    except Exception as e:
        logger.warning(f"business-summary premium 오류: {e}")
        return {"total": 0, "status": {}, "top": []}


def _safe_brief(db) -> dict:
    try:
        from app.services.brief_offer_service import BriefOfferService
        svc = BriefOfferService(db)
        counts = svc.count_by_status()
        briefs = svc.get_briefs(limit=20)
        types: dict[str, int] = {}
        tiers: dict[str, int] = {}
        for d in briefs:
            if d.brief_type:
                types[d.brief_type] = types.get(d.brief_type, 0) + 1
            if d.brief_price_tier:
                tiers[d.brief_price_tier] = tiers.get(d.brief_price_tier, 0) + 1
        ready = [d for d in briefs if (d.premium_status or "") == "ready"]
        return {
            "total": sum(counts.values()),
            "status": counts,
            "types": types,
            "tiers": tiers,
            "ready_count": len(ready),
        }
    except Exception as e:
        logger.warning(f"business-summary brief 오류: {e}")
        return {"total": 0, "status": {}, "types": {}, "tiers": {}, "ready_count": 0}


def _safe_b2b(db) -> dict:
    try:
        from app.services.b2b_candidate_service import B2BCandidateService
        svc = B2BCandidateService(db)
        counts = svc.count_by_status()
        return {
            "total": sum(counts.values()),
            "status": counts,
            "audience": svc.group_by_audience(),
            "use_case": svc.group_by_use_case(),
        }
    except Exception as e:
        logger.warning(f"business-summary b2b 오류: {e}")
        return {"total": 0, "status": {}, "audience": {}, "use_case": {}}


def _safe_newsletter(db) -> dict:
    try:
        from app.services.newsletter_routine_service import NewsletterRoutineService
        svc = NewsletterRoutineService(db)
        bk = svc.count_by_bucket()
        leads = svc.count_lead_assets()
        return {
            "newsletter_total": sum(bk.values()),
            "lead_total": sum(leads.values()),
            "bucket": bk,
            "lead_types": leads,
        }
    except Exception as e:
        logger.warning(f"business-summary newsletter 오류: {e}")
        return {"newsletter_total": 0, "lead_total": 0, "bucket": {}, "lead_types": {}}


def _safe_weekly_compact(db) -> dict:
    try:
        from app.services.weekly_report_service import WeeklyReportService
        svc = WeeklyReportService(db)
        rep = svc.generate_report(days=7)
        cs = rep.get("content_summary", {})
        return {
            "period_days": rep.get("period_days", 7),
            "total_drafts": cs.get("total_drafts", 0),
            "published": cs.get("published", 0),
            "approved": cs.get("approved", 0),
            "rejected": cs.get("rejected", 0),
            "pending": cs.get("pending", 0),
            "highlights": rep.get("highlights", [])[:3],
            "followup_count": len(rep.get("followup_items", [])),
        }
    except Exception as e:
        logger.warning(f"business-summary weekly 오류: {e}")
        return {
            "period_days": 7, "total_drafts": 0, "published": 0,
            "approved": 0, "rejected": 0, "pending": 0,
            "highlights": [], "followup_count": 0,
        }


def _safe_cta_perf(db) -> dict:
    try:
        from app.services.cta_copy_service import CtaCopyService
        svc = CtaCopyService(db)
        all_perf = svc.get_all_perf()
        linked = [p for p in all_perf if p["total_linked"] > 0]
        notable = [
            p for p in linked
            if (
                p["avg_monetization"] >= 70
                or (p["total_linked"] >= 2 and p["published"] / p["total_linked"] >= 0.5)
            )
        ]
        return {
            "total_copies": len(all_perf),
            "linked_copies": len(linked),
            "unlinked_copies": len(all_perf) - len(linked),
            "total_linked_drafts": sum(p["total_linked"] for p in all_perf),
            "total_published": sum(p["published"] for p in all_perf),
            "top": [
                {
                    "id": p["copy_id"],
                    "type": p["cta_type"],
                    "text": p["copy_text"][:80],
                    "linked": p["total_linked"],
                    "published": p["published"],
                    "score": p["avg_monetization"],
                    "active": p["is_active"],
                }
                for p in linked[:3]
            ],
            "notable_count": len(notable),
        }
    except Exception as e:
        logger.warning(f"business-summary cta 오류: {e}")
        return {
            "total_copies": 0, "linked_copies": 0, "unlinked_copies": 0,
            "total_linked_drafts": 0, "total_published": 0,
            "top": [], "notable_count": 0,
        }


# ── 시스템 상태 스냅샷 ────────────────────────────────────────────────────────

@router.get("/status")
async def get_control_status():
    """
    Control Room 메인 패널 데이터.
    시스템 전반 상태를 단일 JSON으로 반환합니다.
    """
    now_utc = datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)

    # --- 큐 ---
    queue_data = _get_queue_status()

    # --- 일일 사용량 ---
    usage_data = _get_usage()

    # --- 활동 추적 ---
    activity_data = _get_activity(now_utc)

    # --- 멘션 모니터 ---
    monitor_data = _get_monitor_status()

    # --- 뉴스 모니터 ---
    news_data = _get_news_monitor_status()

    # --- 헬스 ---
    health_data = _get_health()

    return {
        "generated_at": now_utc.isoformat(),
        "generated_at_kst": now_kst.strftime("%Y-%m-%d %H:%M KST"),
        "health": health_data,
        "queue": queue_data,
        "usage": usage_data,
        "activity": activity_data,
        "monitor": monitor_data,
        "news": news_data,
    }


# ── 최근 플로우 트레이스 ──────────────────────────────────────────────────────

@router.get("/flow-trace")
async def get_flow_trace(limit: int = 20):
    """
    최근 초안 N개의 플로우 상태를 반환합니다.
    소스 입력 → 초안 생성 → 검토 → 승인/거절/발행 흐름을 보여줍니다.
    """
    db = get_db()
    try:
        from sqlalchemy.orm import joinedload
        from app.models.content import Draft
        rows = (
            db.query(Draft)
            .options(joinedload(Draft.source_item))
            .order_by(Draft.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_format_draft_trace(d) for d in rows]
    except Exception as e:
        logger.warning(f"flow-trace 오류: {e}")
        return []
    finally:
        db.close()


# ── AI 프로바이더 현황 ────────────────────────────────────────────────────────

@router.get("/providers")
async def get_providers():
    """
    AI 워크스테이션 뷰: 역할별 상태 + 최근 작업 + provider health + activity feed.

    구조:
      roles[]            각 AI 역할 (DraftWriter, Reviewer, Researcher, FactChecker,
                         TrendHunter=수동, HookReviewer=자동 Grok)
      activity[]         최근 처리된 Draft 5건 (활동 피드)
      provider_health[]  provider별 configured + 오늘 호출수
      stats              대기/활성/마지막 활동 요약
    """
    ai_status = settings.ai_status_summary()
    effective = {
        "draft_writer":  settings.get_effective_draft_provider(),
        "reviewer":      "anthropic",
        "researcher":    settings.get_effective_research_provider(),
        "fact_checker":  settings.get_effective_factcheck_provider(),
        "trend_hunter":  settings.get_effective_trend_provider(),
    }
    configured = {
        "openai":      bool(settings.openai_api_key),
        "anthropic":   bool(settings.anthropic_api_key),
        "gemini":      bool(settings.gemini_api_key),
        "grok":        bool(settings.grok_api_key),
        "perplexity":  bool(settings.perplexity_api_key),
        "naver":       bool(settings.naver_client_id and settings.naver_client_secret),
    }

    today_drafts = _today_draft_count()

    # provider별 실제 호출수 (api_cost_tracker, 재시작 시 리셋)
    try:
        from app.services.api_cost_tracker import get_today_provider_stats
        prov_stats = get_today_provider_stats()
    except Exception:
        prov_stats = {}

    # 최근 Draft 5건 → last_run / last_task / activity feed / 대기열
    last_run_iso = None
    last_task = None
    pending_count = 0
    activity: list[dict] = []
    try:
        from app.models.content import Draft, ApprovalStatus
        from sqlalchemy.orm import joinedload
        db = get_db()
        try:
            recent = (
                db.query(Draft)
                .options(joinedload(Draft.source_item))
                .order_by(Draft.created_at.desc())
                .limit(5)
                .all()
            )
            if recent:
                top = recent[0]
                if top.created_at:
                    last_run_iso = top.created_at.astimezone(KST).isoformat()
                try:
                    if top.source_item and top.source_item.title:
                        last_task = top.source_item.title[:70]
                except Exception:
                    pass
                for d in recent:
                    if not d.created_at:
                        continue
                    try:
                        title = (d.source_item.title if d.source_item and d.source_item.title else "").strip()[:60]
                    except Exception:
                        title = ""
                    activity.append({
                        "time": d.created_at.astimezone(KST).strftime("%H:%M"),
                        "role": "DraftWriter",
                        "action": "초안 생성",
                        "title": title,
                        "status": str(d.approval_status.value) if d.approval_status else "",
                    })
            # 작업 큐 = 오늘 생성됐지만 아직 승인 안 된 초안 (누적 backlog 제외)
            from datetime import datetime as _dt, timedelta as _td
            today_kst_start = _dt.now(tz=KST).replace(hour=0, minute=0, second=0, microsecond=0)
            pending_count = (
                db.query(Draft)
                .filter(Draft.approval_status == ApprovalStatus.PENDING)
                .filter(Draft.created_at >= today_kst_start.astimezone(timezone.utc))
                .count()
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[providers] recent/pending 조회 실패: {e}")

    # Grok auto (HookReviewer) 추정: api_cost_tracker grok calls - 수동 추적이 없으므로 전체로 처리
    grok_calls_today = int(prov_stats.get("grok", {}).get("calls", 0))

    def _mkrole(
        role: str, role_kr: str, role_desc: str, provider: str,
        conf: bool, runs: int, note: str, manual: bool = False,
        track_last: bool = True,
    ):
        status = "blocked" if not conf else ("manual" if manual else ("working" if runs > 0 else "idle"))
        return {
            "role": role,
            "role_kr": role_kr,
            "role_desc": role_desc,
            "provider": provider,
            "configured": conf,
            "runs_today": None if manual else runs,
            "runs_today_manual": 0 if manual else None,
            "last_run": last_run_iso if (track_last and runs > 0) else None,
            "last_task": last_task if (track_last and runs > 0) else None,
            "status": status,
            "note": note,
        }

    roles = [
        _mkrole(
            "DraftWriter", "초안 작성가", "기사 → X 초안 변환",
            effective["draft_writer"], configured.get(effective["draft_writer"], False),
            today_drafts,
            f"{today_drafts}건 처리" if today_drafts else "대기 중",
        ),
        _mkrole(
            "Reviewer", "검토가", "Resonance + 리스크 평가",
            "anthropic (Claude)", configured["anthropic"],
            today_drafts,
            f"{today_drafts}건 검토" if today_drafts else "대기 중",
        ),
        _mkrole(
            "Researcher", "리서처", "사실 수집 및 컨텍스트 보강",
            effective["researcher"], configured.get(effective["researcher"], False),
            today_drafts,
            f"{today_drafts}건 리서치" if today_drafts else "대기 중",
        ),
        _mkrole(
            "FactChecker", "팩트체커", "인용/수치 검증",
            effective["fact_checker"], configured.get(effective["fact_checker"], False),
            today_drafts,
            f"{today_drafts}건 체크" if today_drafts else "대기 중",
        ),
        _mkrole(
            "HookReviewer", "훅 감각 검토", "전송 직전 X 감각 자동 평가",
            "grok", configured["grok"],
            grok_calls_today,
            f"{grok_calls_today}회 평가" if grok_calls_today else "대기 중",
            track_last=bool(grok_calls_today),
        ),
        _mkrole(
            "TrendHunter", "트렌드 탐색", "/trends 수동 — X 트렌드 조회",
            "grok", configured["grok"],
            0, "/trends 명령 전용",
            manual=True, track_last=False,
        ),
    ]

    # provider health strip (실제 호출수 기반)
    provider_health = []
    for p in ("openai", "anthropic", "gemini", "perplexity", "grok"):
        provider_health.append({
            "name": p,
            "configured": configured.get(p, False),
            "calls_today": int(prov_stats.get(p, {}).get("calls", 0)),
        })

    active_count = sum(1 for r in roles if r["status"] == "working")
    total_runs = sum((r.get("runs_today") or 0) for r in roles)

    return {
        "roles": roles,
        "activity": activity,
        "provider_health": provider_health,
        "stats": {
            "active_count": active_count,
            "total_roles": len(roles),
            "today_runs": total_runs,
            "pending": pending_count,
            "last_run": last_run_iso,
            "last_task": last_task,
        },
        "ai_status_summary": ai_status,
        "mock_mode": settings.is_full_mock_mode,
        "today_draft_count": today_drafts,
    }


# ── 최근 뉴스 기사 제목 ───────────────────────────────────────────────────────

@router.get("/recent-news")
async def get_recent_news(limit: int = 8):
    """
    최근 수집된 기사 목록을 반환합니다.
    _recent_items 버퍼 기반 — overnight_buffer 클리어와 독립.

    응답 필드:
      title     기사 제목
      time      수집 시각 HH:MM
      url       원문 URL (Alerts 탭 피드 행 탭 → 새 탭 열기용)
      category  네이버 카테고리 (배지 표시용)
    """
    try:
        from app.services.news_monitor import get_recent_items
        items = get_recent_items(limit=limit)
        return [
            {
                "title": str(a.get("title", "")).strip()[:120],
                "time": str(a.get("added_at", ""))[11:16],
                "url": a.get("url") or "",
                "category": a.get("category") or "",
            }
            for a in items if a.get("title")
        ]
    except Exception as e:
        logger.warning(f"recent-news 오류: {e}")
        return []


@router.get("/rejected-drafts")
async def get_rejected_drafts(limit: int = 20):
    """
    최근 거절된 초안 목록을 반환합니다.
    대시보드 "거절 이력" 섹션에서 소비 — AI 가 거절한 초안과
    사용자가 거절한 초안을 동일 목록에 시간 역순으로 보여준다.

    응답 필드:
      id            draft id
      title         source 제목
      url           원문 URL (있으면)
      body          초안 본문 미리보기 (최대 100자)
      hook          초안 hook
      rejected_at   거절된 시각 (updated_at)
      fallback      resonance fallback 사용 여부 (AI 구조 실패 신호)
    """
    from app.db import SessionLocal
    from app.models.content import Draft, SourceItem, ApprovalStatus

    s = SessionLocal()
    try:
        rows = (
            s.query(Draft, SourceItem)
            .outerjoin(SourceItem, SourceItem.id == Draft.source_item_id)
            .filter(Draft.approval_status == ApprovalStatus.REJECTED)
            .order_by(Draft.updated_at.desc().nullslast(), Draft.id.desc())
            .limit(limit)
            .all()
        )
        out = []
        for d, src in rows:
            body = (d.body or "").strip()
            out.append({
                "id": d.id,
                "title": (src.title if src else "") or "",
                "url": (src.url if src else "") or "",
                "hook": (d.hook or "")[:80],
                "body": body[:100] + ("…" if len(body) > 100 else ""),
                "rejected_at": (
                    d.updated_at.isoformat() if d.updated_at else
                    (d.created_at.isoformat() if d.created_at else "")
                ),
                "fallback": bool(getattr(d, "resonance_fallback_used", False)),
            })
        return out
    except Exception as e:
        logger.warning(f"rejected-drafts 오류: {e}")
        return []
    finally:
        s.close()


@router.get("/scored-candidates")
async def get_scored_candidates(limit: int = 15):
    """
    최근 수집 기사를 키워드 점수로 정렬하여 반환합니다.
    AI 비용 없음 — 로컬 키워드 매칭만 사용.
    이미 DB에 URL이 있는 기사는 제외합니다.
    """
    try:
        from app.services.news_monitor import get_recent_items
        from app.services.morning_digest import _importance_score
        items = get_recent_items(limit=50)
        for a in items:
            a["_score"] = _importance_score(a)
            lang = a.get("region", "KR")
            if lang == "KR":
                a["_score"] += 5
        items.sort(key=lambda x: x["_score"], reverse=True)
        db = get_db()
        try:
            from app.models.content import SourceItem
            existing_urls = set()
            for a in items:
                u = (a.get("url") or "").strip()
                if u:
                    existing_urls.add(u)
            if existing_urls:
                found = db.query(SourceItem.url).filter(
                    SourceItem.url.in_(existing_urls)
                ).all()
                used = {r[0] for r in found}
            else:
                used = set()
        finally:
            db.close()
        result = []
        cat_counts: dict[str, int] = {}
        for a in items:
            u = (a.get("url") or "").strip()
            if u and u in used:
                continue
            cat = a.get("category", "기타")
            cnt = cat_counts.get(cat, 0)
            if cnt >= 3:
                continue
            cat_counts[cat] = cnt + 1
            # 기사 원본 발행 시각(published_at) 우선, 없으면 수집 시각(added_at)
            pub = a.get("published_at") or a.get("added_at") or ""
            result.append({
                "title": str(a.get("title", "")).strip()[:100],
                "url": u,
                "summary": (a.get("summary", "") or "")[:200],
                "score": a["_score"],
                "category": a.get("category", ""),
                "time": str(pub)[11:16],
            })
            if len(result) >= limit:
                break
        return result
    except Exception as e:
        logger.warning(f"scored-candidates 오류: {e}")
        return []


# ── Premium 텔레그램 발송 ─────────────────────────────────────────────────────

@router.post("/premium/{draft_id}/send-telegram")
async def send_premium_to_telegram(draft_id: int):
    """
    프리미엄 후보 초안을 텔레그램 승인 카드로 전송합니다.
    대시보드에서 "텔레그램 발송" 버튼을 눌렀을 때 호출됨.

    Hook/본문이 영문이면 Gemini 로 한국어 번역해서 카드에 표시한다.
    한국 독자/운영자가 카드만 보고 빠르게 판단할 수 있게 하기 위함.
    """
    db = get_db()
    try:
        from app.services.premium_candidate_service import PremiumCandidateService
        from app.services.telegram_service import (
            send_approval_card, _is_korean, _translate_to_korean,
        )
        svc = PremiumCandidateService(db)
        draft = svc.get_candidate_by_id(draft_id)
        if not draft:
            return {"success": False, "error": f"premium 후보 없음: {draft_id}"}
        source_url = None
        try:
            if draft.source_item:
                source_url = draft.source_item.url
        except Exception:
            pass

        # 영문 → 한국어 번역 (실패하면 원문 그대로 전송)
        hook_ko = None
        body_ko = None
        orig_hook = draft.hook or ""
        orig_body = draft.body or ""
        if orig_hook and not _is_korean(orig_hook):
            hook_ko = await _translate_to_korean(orig_hook) or orig_hook
        if orig_body and not _is_korean(orig_body):
            body_ko = await _translate_to_korean(orig_body) or orig_body

        msg_id = await send_approval_card(
            draft, source_url=source_url,
            hook_override=hook_ko, body_override=body_ko,
        )
        if msg_id:
            svc.update_status(draft_id, "reviewing")
            return {
                "success": True,
                "message_id": msg_id,
                "draft_id": draft_id,
                "translated": bool(hook_ko or body_ko),
            }
        return {
            "success": False,
            "error": "텔레그램 전송 실패 (설정/네트워크 확인)",
        }
    except Exception as e:
        logger.warning(f"premium send-telegram 오류: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ── Naver 할당량 ──────────────────────────────────────────────────────────────

@router.get("/naver")
async def get_naver_quota():
    """오늘의 Naver API 사용량 현황을 반환합니다."""
    from app.services.naver_usage import get_status
    return get_status()


@router.get("/editorial-summary")
async def get_editorial_summary():
    """
    PR 34 — Editorial Score + Routing Queue 집계.
    대시보드 Pulse/Alerts 탭 데이터 소스.
    """
    db = get_db()
    try:
        from app.services.eval_store import (
            load_recent_records, count_records,
            load_routing_queue, count_routing_queue,
        )
        # routing queue 건수
        queue_counts = {}
        for rt in ("IMMEDIATE", "DAY_DIGEST", "TOP10_5AM", "WEEKLY_POOL"):
            queue_counts[rt] = count_routing_queue(db, rt)

        # 최근 IMMEDIATE 항목
        immediate_items = load_routing_queue(db, "IMMEDIATE", limit=5)

        # eval_records 건수
        eval_counts = {}
        for et in ("eval_meta", "gold_eval", "pairwise_review", "learning_record"):
            eval_counts[et] = count_records(db, et)

        # 최근 eval_meta에서 editorial scores 평균
        recent_evals = load_recent_records(db, "eval_meta", limit=20)
        avg_post = 0
        avg_trust = 0
        if recent_evals:
            scores = [e.get("editorial_scores", {}) for e in recent_evals]
            post_scores = [s.get("postability_score", 0) for s in scores if s]
            trust_scores = [s.get("trust_score", 0) for s in scores if s]
            if post_scores:
                avg_post = round(sum(post_scores) / len(post_scores))
            if trust_scores:
                avg_trust = round(sum(trust_scores) / len(trust_scores))

        return {
            "routing_queue": queue_counts,
            "immediate_items": immediate_items,
            "eval_counts": eval_counts,
            "avg_postability": avg_post,
            "avg_trust": avg_trust,
            "recent_eval_count": len(recent_evals),
        }
    except Exception as e:
        logger.warning(f"editorial-summary 오류: {e}")
        return {
            "routing_queue": {}, "immediate_items": [],
            "eval_counts": {}, "avg_postability": 0, "avg_trust": 0,
            "recent_eval_count": 0,
        }
    finally:
        db.close()


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _get_queue_status() -> dict:
    try:
        from app.services.growth.post_queue import get_post_queue
        q = get_post_queue()
        pending = q.list_pending()
        all_posts = q.list_all()
        last_pub = q._last_published
        return {
            "pending_count": len(pending),
            "total_count": len(all_posts),
            "last_published_at": last_pub.isoformat() if last_pub else None,
            "pending_items": [
                {
                    "text": p.text[:80] + ("…" if len(p.text) > 80 else ""),
                    "added_at": p.added_at.isoformat(),
                    "notified": p.notified_at is not None,
                }
                for p in pending[:5]
            ],
        }
    except Exception as e:
        logger.warning(f"queue status 오류: {e}")
        return {"error": str(e)}


def _get_usage() -> dict:
    db = get_db()
    try:
        from app.services.rate_limiter import RateLimiter
        limiter = RateLimiter(db)
        return limiter.get_daily_summary()
    except Exception as e:
        logger.warning(f"usage 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()


def _get_activity(now_utc: datetime) -> dict:
    try:
        from app.services.growth.activity_tracker import get_last_activity, IDLE_HOURS
        last = get_last_activity()
        if last is None:
            return {"last_activity_at": None, "hours_idle": None, "is_idle": False}
        elapsed_h = (now_utc - last).total_seconds() / 3600
        last_kst = last.astimezone(KST)
        return {
            "last_activity_at": last.isoformat(),
            "last_activity_kst": last_kst.strftime("%m/%d %H:%M KST"),
            "hours_idle": round(elapsed_h, 1),
            "is_idle": elapsed_h >= IDLE_HOURS,
        }
    except Exception as e:
        logger.warning(f"activity 오류: {e}")
        return {"error": str(e)}


def _get_monitor_status() -> dict:
    try:
        from app.services.growth.monitor_state import is_paused
        from app.services.growth.reply_monitor import _pending_reply_drafts
        return {
            "reply_monitor_paused": is_paused(),
            "pending_reply_drafts": len(_pending_reply_drafts),
        }
    except Exception as e:
        logger.warning(f"monitor status 오류: {e}")
        return {"error": str(e)}


def _get_news_monitor_status() -> dict:
    try:
        from app.services.news_monitor import (
            _pending_articles, _story_clusters, _alerted_stories, overnight_buffer
        )
        return {
            "pending_articles": len(_pending_articles),
            "story_clusters": len(_story_clusters),
            "alerted_stories": len(_alerted_stories),
            "overnight_buffer": len(overnight_buffer),
        }
    except Exception as e:
        logger.warning(f"news monitor status 오류: {e}")
        return {"error": str(e)}


def _get_health() -> dict:
    try:
        db_ok = False
        try:
            db = get_db()
            db.execute(text("SELECT 1"))
            db_ok = True
            db.close()
        except Exception:
            pass
        return {
            "db_ok": db_ok,
            "telegram_configured": settings.has_telegram_config,
            "x_configured": False,  # 자동 게시 제거됨
            "mock_mode": settings.is_full_mock_mode,
            "auto_post_enabled": settings.enable_auto_post_low_risk,
        }
    except Exception as e:
        return {"error": str(e)}


def _today_draft_count() -> int:
    db = get_db()
    try:
        from app.services.rate_limiter import RateLimiter
        return RateLimiter(db).get_today_draft_count()
    except Exception:
        return 0
    finally:
        db.close()


def _format_draft_trace(d) -> dict:
    """Draft DB 행을 플로우 트레이스 항목으로 변환."""
    kst_created = d.created_at.astimezone(KST).strftime("%m/%d %H:%M") if d.created_at else None
    kst_published = d.published_at.astimezone(KST).strftime("%m/%d %H:%M") if d.published_at else None
    src_url = None
    try:
        if d.source_item and d.source_item.url:
            src_url = d.source_item.url
    except Exception:
        pass
    from app.services.draft_service import is_broken_draft
    broken = is_broken_draft(d.body)
    res_score = 0
    try:
        from app.services.content_pack import compute_resonance_score
        res = compute_resonance_score(d.body or "")
        res_score = res.get("total", 0)
    except Exception:
        pass
    return {
        "id": d.id,
        "hook": (d.hook or "")[:80],
        "category": d.category.value if d.category else None,
        "risk_level": d.risk_level.value if d.risk_level else None,
        "status": d.approval_status.value if d.approval_status else None,
        "version": d.version,
        "created_kst": kst_created,
        "published_kst": kst_published,
        "has_x_post": bool(d.x_post_id),
        "x_post_id": d.x_post_id,
        "monetization_score": d.monetization_score,
        "source_url": src_url,
        "broken": broken,
        "resonance": res_score,
    }
