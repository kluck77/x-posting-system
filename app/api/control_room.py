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
        top = svc.get_candidates(limit=3)
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
    AI 역할별 프로바이더 현황을 반환합니다.
    실제 구성 정보 + 오늘 생성된 초안 수를 기반으로 활동 여부를 추정합니다.
    개별 API 호출 횟수는 추적되지 않으므로 초안 수로 대리 지표를 사용합니다.
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

    # 오늘 초안 수 → 모든 파이프라인 역할이 최소 이만큼 실행됐음을 의미
    today_drafts = _today_draft_count()

    roles = [
        {
            "role": "DraftWriter",
            "provider": effective["draft_writer"],
            "configured": configured.get(effective["draft_writer"], False),
            "runs_today": today_drafts,
            "note": "초안 1개 = 1 실행" if today_drafts else "오늘 활동 없음",
        },
        {
            "role": "Reviewer",
            "provider": "anthropic (Claude)",
            "configured": configured["anthropic"],
            "runs_today": today_drafts,
            "note": "초안 1개 = 1 리뷰" if today_drafts else "오늘 활동 없음",
        },
        {
            "role": "Researcher",
            "provider": effective["researcher"],
            "configured": configured.get(effective["researcher"], False),
            "runs_today": today_drafts,
            "note": "초안 1개 = 1 리서치" if today_drafts else "오늘 활동 없음",
        },
        {
            "role": "FactChecker",
            "provider": effective["fact_checker"],
            "configured": configured.get(effective["fact_checker"], False),
            "runs_today": today_drafts,
            "note": "초안 1개 = 1 팩트체크" if today_drafts else "오늘 활동 없음",
        },
        {
            "role": "TrendHunter",
            "provider": "grok",
            "configured": configured["grok"],
            "runs_today": None,
            "note": "/trends 명령으로만 실행됨 — 자동 카운트 없음",
        },
    ]

    return {
        "roles": roles,
        "ai_status_summary": ai_status,
        "mock_mode": settings.is_full_mock_mode,
        "today_draft_count": today_drafts,
    }


# ── 최근 뉴스 기사 제목 ───────────────────────────────────────────────────────

@router.get("/recent-news")
async def get_recent_news(limit: int = 8):
    """
    최근 수집된 기사 제목 목록을 반환합니다.
    _recent_items 버퍼 기반 — overnight_buffer 클리어와 독립.
    """
    try:
        from app.services.news_monitor import get_recent_items
        items = get_recent_items(limit=limit)
        return [{"title": str(a.get("title", "")).strip()[:100],
                 "time": str(a.get("added_at", ""))[11:16]}
                for a in items if a.get("title")]
    except Exception as e:
        logger.warning(f"recent-news 오류: {e}")
        return []


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
            result.append({
                "title": str(a.get("title", "")).strip()[:100],
                "url": u,
                "summary": (a.get("summary", "") or "")[:200],
                "score": a["_score"],
                "category": a.get("category", ""),
                "time": str(a.get("added_at", ""))[11:16],
            })
            if len(result) >= limit:
                break
        return result
    except Exception as e:
        logger.warning(f"scored-candidates 오류: {e}")
        return []


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
    }
