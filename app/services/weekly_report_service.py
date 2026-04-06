"""
주간 운영 리포트 서비스
========================
최근 7일간 운영 현황을 집계하여 구조화된 리포트를 생성합니다.

섹션:
1. 콘텐츠/비즈니스 태그 요약
2. 뉴스레터/리드 요약
3. 프리미엄 브리프 요약
4. B2B 후보 요약
5. 주요 하이라이트
6. 추천 후속 조치

Layer 2 원칙: 실패해도 Layer 1 파이프라인에 영향 없음.
각 섹션은 독립적으로 실패할 수 있으며, 실패 시 해당 섹션만 빈 값으로 처리됩니다.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.content import Draft, ApprovalStatus

logger = logging.getLogger(__name__)


class WeeklyReportService:
    """주간 운영 리포트 생성 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── 리포트 생성 ──────────────────────────────────────────────

    def generate_report(self, days: int = 7) -> dict:
        """주간 운영 리포트 생성.

        Args:
            days: 집계 기간 (기본 7일)

        Returns:
            구조화된 리포트 딕셔너리
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        report = {
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "content_summary": self._content_summary(cutoff),
            "newsletter_summary": self._newsletter_summary(cutoff),
            "premium_summary": self._premium_summary(),
            "brief_summary": self._brief_summary(),
            "b2b_summary": self._b2b_summary(),
            "highlights": self._highlights(cutoff),
            "followup_items": self._followup_items(),
        }
        return report

    # ── 섹션별 집계 ──────────────────────────────────────────────

    def _content_summary(self, cutoff: datetime) -> dict:
        """콘텐츠/비즈니스 태그 요약."""
        try:
            recent = (
                self.db.query(Draft)
                .filter(Draft.created_at >= cutoff)
                .all()
            )
            total = len(recent)
            published = sum(
                1 for d in recent
                if d.approval_status == ApprovalStatus.PUBLISHED
            )
            approved = sum(
                1 for d in recent
                if d.approval_status == ApprovalStatus.APPROVED
            )
            rejected = sum(
                1 for d in recent
                if d.approval_status == ApprovalStatus.REJECTED
            )
            pending = sum(
                1 for d in recent
                if d.approval_status == ApprovalStatus.PENDING
            )

            # 카테고리 분포
            category_counts: dict[str, int] = {}
            for d in recent:
                cat = d.category.value if d.category else "unknown"
                category_counts[cat] = category_counts.get(cat, 0) + 1

            # 비즈니스 태그 분포
            tag_counts: dict[str, int] = {}
            for d in recent:
                try:
                    tags = json.loads(d.business_tags) if d.business_tags else []
                except (json.JSONDecodeError, TypeError):
                    tags = []
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

            # CTA 분포
            cta_counts: dict[str, int] = {}
            for d in recent:
                if d.cta_type:
                    cta_counts[d.cta_type] = cta_counts.get(d.cta_type, 0) + 1

            return {
                "total_drafts": total,
                "published": published,
                "approved": approved,
                "rejected": rejected,
                "pending": pending,
                "category_distribution": category_counts,
                "business_tag_distribution": tag_counts,
                "cta_distribution": cta_counts,
            }
        except Exception as e:
            logger.warning(f"[WeeklyReport] 콘텐츠 요약 실패: {e}")
            return {
                "total_drafts": 0, "published": 0, "approved": 0,
                "rejected": 0, "pending": 0,
                "category_distribution": {}, "business_tag_distribution": {},
                "cta_distribution": {},
            }

    def _newsletter_summary(self, cutoff: datetime) -> dict:
        """뉴스레터/리드 요약."""
        try:
            from app.services.newsletter_routine_service import (
                NewsletterRoutineService, NEWSLETTER_BUCKETS,
            )
            svc = NewsletterRoutineService(self.db)
            bucket_counts = svc.count_by_bucket()
            lead_counts = svc.count_lead_assets()

            # 최근 기간 뉴스레터 후보 수
            recent_nl = (
                self.db.query(Draft)
                .filter(
                    Draft.created_at >= cutoff,
                    (
                        (Draft.cta_type == "newsletter_signup") |
                        (Draft.asset_goal == "newsletter_push") |
                        (Draft.email_bucket.in_(NEWSLETTER_BUCKETS))
                    ),
                )
                .count()
            )
            recent_lead = (
                self.db.query(Draft)
                .filter(
                    Draft.created_at >= cutoff,
                    (
                        (Draft.lead_asset_name.isnot(None)) |
                        (Draft.cta_type == "lead_magnet") |
                        (Draft.asset_goal == "lead_magnet_push")
                    ),
                )
                .count()
            )

            return {
                "bucket_distribution": bucket_counts,
                "lead_asset_distribution": lead_counts,
                "recent_newsletter_candidates": recent_nl,
                "recent_lead_candidates": recent_lead,
                "total_newsletter": sum(bucket_counts.values()),
                "total_lead_assets": sum(lead_counts.values()),
            }
        except Exception as e:
            logger.warning(f"[WeeklyReport] 뉴스레터 요약 실패: {e}")
            return {
                "bucket_distribution": {}, "lead_asset_distribution": {},
                "recent_newsletter_candidates": 0, "recent_lead_candidates": 0,
                "total_newsletter": 0, "total_lead_assets": 0,
            }

    def _premium_summary(self) -> dict:
        """프리미엄 후보 요약."""
        try:
            from app.services.premium_candidate_service import PremiumCandidateService
            svc = PremiumCandidateService(self.db)
            counts = svc.count_by_status()
            top = svc.get_candidates(limit=3)
            top_items = []
            for d in top:
                top_items.append({
                    "draft_id": d.id,
                    "hook": (d.hook or "")[:80],
                    "premium_status": d.premium_status or "new",
                    "monetization_score": d.monetization_score,
                })
            return {
                "status_distribution": counts,
                "total": sum(counts.values()),
                "top_candidates": top_items,
            }
        except Exception as e:
            logger.warning(f"[WeeklyReport] 프리미엄 요약 실패: {e}")
            return {"status_distribution": {}, "total": 0, "top_candidates": []}

    def _brief_summary(self) -> dict:
        """브리프 오퍼 요약."""
        try:
            from app.services.brief_offer_service import BriefOfferService
            svc = BriefOfferService(self.db)
            counts = svc.count_by_status()

            # 유형 분포
            type_counts: dict[str, int] = {}
            briefs = svc.get_briefs(limit=50)
            for d in briefs:
                if d.brief_type:
                    type_counts[d.brief_type] = type_counts.get(d.brief_type, 0) + 1

            # 티어 분포
            tier_counts: dict[str, int] = {}
            for d in briefs:
                if d.brief_price_tier:
                    tier_counts[d.brief_price_tier] = tier_counts.get(d.brief_price_tier, 0) + 1

            return {
                "status_distribution": counts,
                "total": sum(counts.values()),
                "type_distribution": type_counts,
                "tier_distribution": tier_counts,
            }
        except Exception as e:
            logger.warning(f"[WeeklyReport] 브리프 요약 실패: {e}")
            return {
                "status_distribution": {}, "total": 0,
                "type_distribution": {}, "tier_distribution": {},
            }

    def _b2b_summary(self) -> dict:
        """B2B 후보 요약."""
        try:
            from app.services.b2b_candidate_service import B2BCandidateService
            svc = B2BCandidateService(self.db)
            counts = svc.count_by_status()
            by_aud = svc.group_by_audience()
            by_uc = svc.group_by_use_case()
            return {
                "status_distribution": counts,
                "total": sum(counts.values()),
                "audience_distribution": by_aud,
                "usecase_distribution": by_uc,
            }
        except Exception as e:
            logger.warning(f"[WeeklyReport] B2B 요약 실패: {e}")
            return {
                "status_distribution": {}, "total": 0,
                "audience_distribution": {}, "usecase_distribution": {},
            }

    def _highlights(self, cutoff: datetime) -> list[dict]:
        """주요 하이라이트 (높은 수익화 점수, 게시 완료 등)."""
        try:
            high_value = (
                self.db.query(Draft)
                .filter(
                    Draft.created_at >= cutoff,
                    Draft.monetization_score.isnot(None),
                    Draft.monetization_score >= 70,
                )
                .order_by(Draft.monetization_score.desc())
                .limit(5)
                .all()
            )
            items = []
            for d in high_value:
                items.append({
                    "draft_id": d.id,
                    "hook": (d.hook or "")[:80],
                    "monetization_score": d.monetization_score,
                    "category": d.category.value if d.category else "",
                    "approval_status": d.approval_status.value if d.approval_status else "",
                    "premium_status": d.premium_status,
                    "b2b_candidate": d.b2b_candidate or False,
                })
            return items
        except Exception as e:
            logger.warning(f"[WeeklyReport] 하이라이트 실패: {e}")
            return []

    def _followup_items(self) -> list[dict]:
        """추천 후속 조치 항목."""
        items = []
        try:
            # 1. 리뷰 대기 프리미엄 후보
            from app.services.premium_candidate_service import PremiumCandidateService
            psvc = PremiumCandidateService(self.db)
            new_premium = psvc.get_candidates(status="new", limit=5)
            if new_premium:
                items.append({
                    "action": "review_premium",
                    "label": f"프리미엄 후보 리뷰 대기 {len(new_premium)}건",
                    "count": len(new_premium),
                    "ids": [d.id for d in new_premium],
                })
        except Exception:
            pass

        try:
            # 2. 리뷰 대기 B2B 후보
            from app.services.b2b_candidate_service import B2BCandidateService
            bsvc = B2BCandidateService(self.db)
            new_b2b = bsvc.get_candidates(status="new", limit=5)
            if new_b2b:
                items.append({
                    "action": "review_b2b",
                    "label": f"B2B 후보 리뷰 대기 {len(new_b2b)}건",
                    "count": len(new_b2b),
                    "ids": [d.id for d in new_b2b],
                })
        except Exception:
            pass

        try:
            # 3. 발행 준비된 브리프
            from app.services.brief_offer_service import BriefOfferService
            brsvc = BriefOfferService(self.db)
            ready_briefs = brsvc.get_briefs(status="ready", limit=5)
            if ready_briefs:
                items.append({
                    "action": "publish_brief",
                    "label": f"브리프 발행 준비 {len(ready_briefs)}건",
                    "count": len(ready_briefs),
                    "ids": [d.id for d in ready_briefs],
                })
        except Exception:
            pass

        try:
            # 4. 미설정 리드 자산 (이름 없는 리드자석 후보)
            lead_no_name = (
                self.db.query(Draft)
                .filter(
                    (Draft.cta_type == "lead_magnet") |
                    (Draft.asset_goal == "lead_magnet_push"),
                    Draft.lead_asset_name.is_(None),
                )
                .limit(5)
                .all()
            )
            if lead_no_name:
                items.append({
                    "action": "set_lead_asset",
                    "label": f"리드자석 이름 미설정 {len(lead_no_name)}건",
                    "count": len(lead_no_name),
                    "ids": [d.id for d in lead_no_name],
                })
        except Exception:
            pass

        try:
            # 5. 승인 대기 초안
            pending = (
                self.db.query(Draft)
                .filter(Draft.approval_status == ApprovalStatus.PENDING)
                .limit(5)
                .all()
            )
            if pending:
                items.append({
                    "action": "review_pending",
                    "label": f"승인 대기 초안 {len(pending)}건",
                    "count": len(pending),
                    "ids": [d.id for d in pending],
                })
        except Exception:
            pass

        return items

    # ── 포맷 ──────────────────────────────────────────────────────

    def format_report(self, report: dict) -> str:
        """리포트를 텔레그램 메시지로 포맷."""
        try:
            days = report["period_days"]
            cs = report["content_summary"]
            ns = report["newsletter_summary"]
            ps = report["premium_summary"]
            brs = report["brief_summary"]
            b2b = report["b2b_summary"]
            highlights = report["highlights"]
            followups = report["followup_items"]

            lines = [
                f"📊 <b>주간 운영 리포트</b> (최근 {days}일)",
                f"{'━' * 30}",
                "",
            ]

            # 콘텐츠 요약
            lines.append(f"📝 <b>콘텐츠</b>")
            lines.append(
                f"  총 {cs['total_drafts']}건 | "
                f"게시 {cs['published']} | 승인 {cs['approved']} | "
                f"거절 {cs['rejected']} | 대기 {cs['pending']}"
            )
            if cs["category_distribution"]:
                top_cats = sorted(
                    cs["category_distribution"].items(), key=lambda x: -x[1]
                )[:4]
                cat_str = ", ".join(f"{c}({n})" for c, n in top_cats)
                lines.append(f"  카테고리: {cat_str}")
            if cs["business_tag_distribution"]:
                top_tags = sorted(
                    cs["business_tag_distribution"].items(), key=lambda x: -x[1]
                )[:4]
                tag_str = ", ".join(f"{t}({n})" for t, n in top_tags)
                lines.append(f"  비즈니스 태그: {tag_str}")
            lines.append("")

            # 뉴스레터/리드
            lines.append(f"📰 <b>뉴스레터/리드</b>")
            lines.append(
                f"  뉴스레터: 총 {ns['total_newsletter']}건 "
                f"(최근 {ns['recent_newsletter_candidates']}건)"
            )
            lines.append(
                f"  리드자석: 총 {ns['total_lead_assets']}건 "
                f"(최근 {ns['recent_lead_candidates']}건)"
            )
            if ns["bucket_distribution"]:
                bkt_str = ", ".join(
                    f"{b}({n})"
                    for b, n in sorted(ns["bucket_distribution"].items(), key=lambda x: -x[1])
                )
                lines.append(f"  버킷: {bkt_str}")
            lines.append("")

            # 프리미엄
            lines.append(f"⭐ <b>프리미엄</b> (총 {ps['total']}건)")
            if ps["status_distribution"]:
                st_str = ", ".join(
                    f"{s}({n})"
                    for s, n in sorted(ps["status_distribution"].items(), key=lambda x: -x[1])
                )
                lines.append(f"  상태: {st_str}")
            if ps["top_candidates"]:
                for tc in ps["top_candidates"][:2]:
                    lines.append(
                        f"  • #{tc['draft_id']} [{tc['premium_status']}] "
                        f"💰{tc['monetization_score'] or 0} {tc['hook'][:40]}…"
                    )
            lines.append("")

            # 브리프
            if brs["total"] > 0:
                lines.append(f"📋 <b>브리프</b> (총 {brs['total']}건)")
                if brs["status_distribution"]:
                    st_str = ", ".join(
                        f"{s}({n})"
                        for s, n in sorted(brs["status_distribution"].items(), key=lambda x: -x[1])
                    )
                    lines.append(f"  상태: {st_str}")
                if brs["type_distribution"]:
                    tp_str = ", ".join(
                        f"{t}({n})"
                        for t, n in sorted(brs["type_distribution"].items(), key=lambda x: -x[1])
                    )
                    lines.append(f"  유형: {tp_str}")
                lines.append("")

            # B2B
            if b2b["total"] > 0:
                lines.append(f"🏢 <b>B2B</b> (총 {b2b['total']}건)")
                if b2b["status_distribution"]:
                    st_str = ", ".join(
                        f"{s}({n})"
                        for s, n in sorted(b2b["status_distribution"].items(), key=lambda x: -x[1])
                    )
                    lines.append(f"  상태: {st_str}")
                if b2b["audience_distribution"]:
                    aud_str = ", ".join(
                        f"{a}({n})"
                        for a, n in sorted(
                            b2b["audience_distribution"].items(), key=lambda x: -x[1]
                        )[:3]
                    )
                    lines.append(f"  대상: {aud_str}")
                lines.append("")

            # 하이라이트
            if highlights:
                lines.append(f"🌟 <b>하이라이트</b> (수익화 70+)")
                for h in highlights[:3]:
                    premium_mark = " ⭐" if h.get("premium_status") else ""
                    b2b_mark = " 🏢" if h.get("b2b_candidate") else ""
                    lines.append(
                        f"  • #{h['draft_id']} 💰{h['monetization_score']} "
                        f"[{h['approval_status']}]{premium_mark}{b2b_mark}\n"
                        f"    {h['hook'][:50]}…"
                    )
                lines.append("")

            # 후속 조치
            if followups:
                lines.append(f"➡️ <b>추천 후속 조치</b>")
                for f in followups:
                    ids_str = ", ".join(str(i) for i in f["ids"][:3])
                    more = f" +{f['count'] - 3}" if f["count"] > 3 else ""
                    lines.append(f"  • {f['label']} (#{ids_str}{more})")

            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[WeeklyReport] 포맷 실패: {e}")
            return "📊 주간 리포트 생성 실패"

    def format_compact(self, report: dict) -> str:
        """간략한 요약 (텔레그램 짧은 메시지)."""
        try:
            cs = report["content_summary"]
            ps = report["premium_summary"]
            b2b = report["b2b_summary"]
            ns = report["newsletter_summary"]
            followups = report["followup_items"]
            days = report["period_days"]

            lines = [
                f"📊 <b>주간 요약</b> ({days}일)",
                f"📝 초안 {cs['total_drafts']}건 | 게시 {cs['published']}",
                f"⭐ 프리미엄 {ps['total']}건 | 🏢 B2B {b2b['total']}건",
                f"📰 뉴스레터 {ns['total_newsletter']}건 | "
                f"📄 리드자석 {ns['total_lead_assets']}건",
            ]
            if followups:
                lines.append(f"➡️ 후속 조치 {len(followups)}항목")
            return "\n".join(lines)
        except Exception as e:
            return "📊 주간 요약 생성 실패"

    # ── 내보내기 ──────────────────────────────────────────────────

    def export_report(self, days: int = 7) -> dict:
        """주간 리포트를 구조화된 딕셔너리로 내보내기."""
        return self.generate_report(days)
