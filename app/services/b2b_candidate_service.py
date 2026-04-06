"""
B2B 리서치 후보 관리 서비스 (Phase 5-B2B)
============================================
b2b_candidate로 태깅된 드래프트를 수집·관리·그룹핑·내보내기합니다.

대상 콘텐츠:
- 커스텀 리서치 브리프
- 기관용 해설자료
- 투자자 대상 한국 브리프
- 정책/규제 스냅샷
- 스폰서/B2B 인텔리전스 자산

Layer 2 원칙: 이 서비스 실패해도 Layer 1 파이프라인에 영향 없음.
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import Draft

logger = logging.getLogger(__name__)

# B2B 후보 상태 (premium과 동일 패턴)
B2B_STATUSES = ("new", "reviewing", "shortlisted", "postponed", "rejected", "promoted")

# 추천 대상 독자
B2B_TARGET_AUDIENCES = (
    "investors",
    "journalists",
    "policy_teams",
    "researchers",
    "market_entry",
    "korea_watchers",
    "sponsors",
)

# 추천 활용 사례
B2B_USE_CASES = (
    "regulation_brief",
    "election_context",
    "labor_market_snapshot",
    "housing_risk_note",
    "demographic_trend",
    "trade_supply_chain",
    "policy_explainer",
    "market_entry_context",
)


class B2BCandidateService:
    """B2B 리서치 후보 관리 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ── 조회 ──────────────────────────────────────────────────────

    def get_candidates(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[Draft]:
        """B2B 후보 목록 조회."""
        try:
            query = self.db.query(Draft).filter(Draft.b2b_candidate == True)
            if status:
                query = query.filter(Draft.b2b_status == status)
            return (
                query
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[B2B] 조회 실패: {e}")
            return []

    def get_candidate_by_id(self, draft_id: int) -> Draft | None:
        """ID로 B2B 후보 조회 (b2b_candidate=True인 것만)."""
        try:
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if draft and draft.b2b_candidate:
                return draft
            return None
        except Exception:
            return None

    def get_by_audience(self, audience: str, limit: int = 20) -> list[Draft]:
        """대상 독자별 B2B 후보 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    Draft.b2b_candidate == True,
                    Draft.b2b_target_audience == audience,
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[B2B] audience 조회 실패: {e}")
            return []

    def get_by_use_case(self, use_case: str, limit: int = 20) -> list[Draft]:
        """활용 사례별 B2B 후보 조회."""
        try:
            return (
                self.db.query(Draft)
                .filter(
                    Draft.b2b_candidate == True,
                    Draft.b2b_use_case == use_case,
                )
                .order_by(Draft.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.warning(f"[B2B] use_case 조회 실패: {e}")
            return []

    def group_by_audience(self) -> dict[str, int]:
        """대상 독자별 B2B 후보 수."""
        try:
            candidates = self.db.query(Draft).filter(
                Draft.b2b_candidate == True,
                Draft.b2b_target_audience != None,
                Draft.b2b_target_audience != "",
            ).all()
            groups = {}
            for d in candidates:
                aud = d.b2b_target_audience
                groups[aud] = groups.get(aud, 0) + 1
            return groups
        except Exception as e:
            logger.warning(f"[B2B] audience 그룹핑 실패: {e}")
            return {}

    def group_by_use_case(self) -> dict[str, int]:
        """활용 사례별 B2B 후보 수."""
        try:
            candidates = self.db.query(Draft).filter(
                Draft.b2b_candidate == True,
                Draft.b2b_use_case != None,
                Draft.b2b_use_case != "",
            ).all()
            groups = {}
            for d in candidates:
                uc = d.b2b_use_case
                groups[uc] = groups.get(uc, 0) + 1
            return groups
        except Exception as e:
            logger.warning(f"[B2B] use_case 그룹핑 실패: {e}")
            return {}

    def count_by_status(self) -> dict[str, int]:
        """상태별 B2B 후보 수."""
        try:
            candidates = self.db.query(Draft).filter(Draft.b2b_candidate == True).all()
            counts = {}
            for d in candidates:
                s = d.b2b_status or "new"
                counts[s] = counts.get(s, 0) + 1
            return counts
        except Exception as e:
            logger.warning(f"[B2B] 카운트 실패: {e}")
            return {}

    # ── 상태/메타데이터 변경 ──────────────────────────────────────

    def update_status(self, draft_id: int, new_status: str) -> Draft | None:
        """B2B 후보 상태 변경."""
        if new_status not in B2B_STATUSES:
            logger.warning(f"[B2B] 유효하지 않은 상태: {new_status}")
            return None
        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None
            draft.b2b_status = new_status
            draft.b2b_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[B2B] 상태 변경: #{draft_id} → {new_status}")
            return draft
        except Exception as e:
            logger.error(f"[B2B] 상태 변경 실패: {e}")
            self.db.rollback()
            return None

    def set_note(self, draft_id: int, note: str) -> Draft | None:
        """B2B 운영자 메모 저장."""
        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None
            draft.b2b_note = note[:500]
            draft.b2b_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[B2B] 메모 저장: #{draft_id}")
            return draft
        except Exception as e:
            logger.error(f"[B2B] 메모 저장 실패: {e}")
            self.db.rollback()
            return None

    def set_target_audience(self, draft_id: int, audience: str) -> Draft | None:
        """B2B 대상 독자 설정."""
        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None
            draft.b2b_target_audience = audience[:200]
            draft.b2b_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[B2B] 대상 독자 설정: #{draft_id} → {audience}")
            return draft
        except Exception as e:
            logger.error(f"[B2B] 대상 독자 설정 실패: {e}")
            self.db.rollback()
            return None

    def set_use_case(self, draft_id: int, use_case: str) -> Draft | None:
        """B2B 활용 사례 설정."""
        try:
            draft = self.get_candidate_by_id(draft_id)
            if not draft:
                return None
            draft.b2b_use_case = use_case[:200]
            draft.b2b_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(draft)
            logger.info(f"[B2B] 활용 사례 설정: #{draft_id} → {use_case}")
            return draft
        except Exception as e:
            logger.error(f"[B2B] 활용 사례 설정 실패: {e}")
            self.db.rollback()
            return None

    def init_new_candidates(self) -> int:
        """b2b_candidate=True이지만 b2b_status가 없는 항목을 'new'로 초기화."""
        try:
            candidates = (
                self.db.query(Draft)
                .filter(
                    Draft.b2b_candidate == True,
                    (Draft.b2b_status == None) | (Draft.b2b_status == ""),
                )
                .all()
            )
            for d in candidates:
                d.b2b_status = "new"
                d.b2b_updated_at = datetime.now(timezone.utc)
            self.db.commit()
            logger.info(f"[B2B] {len(candidates)}개 후보 'new' 초기화")
            return len(candidates)
        except Exception as e:
            logger.error(f"[B2B] 초기화 실패: {e}")
            self.db.rollback()
            return 0

    # ── 내보내기 ──────────────────────────────────────────────────

    def export_candidates(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """B2B 후보를 딕셔너리 리스트로 내보내기."""
        try:
            candidates = self.get_candidates(status=status, limit=limit)
            result = []
            for d in candidates:
                try:
                    tags = json.loads(d.business_tags) if d.business_tags else []
                except (json.JSONDecodeError, TypeError):
                    tags = []

                premium_info = None
                if d.premium_status:
                    premium_info = {
                        "premium_status": d.premium_status,
                        "premium_note": d.premium_note,
                        "target_reader_type": getattr(d, "target_reader_type", None),
                    }

                result.append({
                    "draft_id": d.id,
                    "hook": d.hook or "",
                    "body": (d.body or "")[:300],
                    "category": d.category.value if d.category else "",
                    "risk_level": d.risk_level.value if d.risk_level else "",
                    "business_tags": tags,
                    "monetization_score": d.monetization_score,
                    "b2b_target_audience": d.b2b_target_audience,
                    "b2b_use_case": d.b2b_use_case,
                    "b2b_note": d.b2b_note,
                    "b2b_status": d.b2b_status or "new",
                    "b2b_updated_at": (
                        d.b2b_updated_at.isoformat() if d.b2b_updated_at else None
                    ),
                    "premium_linkage": premium_info,
                    "source_title": (
                        d.source_item.title if d.source_item else None
                    ),
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                })
            return result
        except Exception as e:
            logger.warning(f"[B2B] 내보내기 실패: {e}")
            return []

    # ── 포맷 ──────────────────────────────────────────────────────

    def format_summary(self) -> str:
        """B2B 후보 요약 텔레그램 메시지."""
        try:
            counts = self.count_by_status()
            total = sum(counts.values())

            if total == 0:
                return "🏢 B2B 리서치 후보 없음"

            status_labels = {
                "new": "🆕 신규",
                "reviewing": "🔍 검토중",
                "shortlisted": "⭐ 후보선정",
                "postponed": "⏸️ 보류",
                "rejected": "❌ 제외",
                "promoted": "🚀 진행",
            }

            lines = [
                f"🏢 <b>B2B 리서치 후보 요약</b>",
                f"총 {total}건",
                "",
            ]
            for s, label in status_labels.items():
                count = counts.get(s, 0)
                if count > 0:
                    lines.append(f"  {label}: {count}")

            by_aud = self.group_by_audience()
            if by_aud:
                lines.append("")
                lines.append("<b>대상 독자:</b>")
                for aud, cnt in sorted(by_aud.items(), key=lambda x: -x[1])[:5]:
                    lines.append(f"  👥 {aud}: {cnt}")

            by_uc = self.group_by_use_case()
            if by_uc:
                lines.append("")
                lines.append("<b>활용 사례:</b>")
                for uc, cnt in sorted(by_uc.items(), key=lambda x: -x[1])[:5]:
                    lines.append(f"  📋 {uc}: {cnt}")

            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[B2B] 요약 생성 실패: {e}")
            return "🏢 B2B 요약 생성 실패"

    def format_candidate_detail(self, draft: Draft) -> str:
        """단일 B2B 후보 상세 텔레그램 메시지."""
        try:
            status_label = {
                "new": "🆕 신규",
                "reviewing": "🔍 검토중",
                "shortlisted": "⭐ 후보선정",
                "postponed": "⏸️ 보류",
                "rejected": "❌ 제외",
                "promoted": "🚀 진행",
            }.get(draft.b2b_status or "new", "🆕 신규")

            lines = [
                f"🏢 <b>B2B 후보 #{draft.id}</b>",
                f"{'─' * 30}",
                "",
                f"🎯 <b>Hook:</b> {(draft.hook or '')[:100]}",
                f"📊 상태: {status_label}",
            ]

            if draft.b2b_target_audience:
                lines.append(f"👥 대상: {draft.b2b_target_audience}")
            if draft.b2b_use_case:
                lines.append(f"📋 활용: {draft.b2b_use_case}")
            if draft.monetization_score:
                lines.append(f"💰 수익화 점수: {draft.monetization_score}")
            if draft.b2b_note:
                lines.append(f"📝 메모: {draft.b2b_note}")

            if draft.premium_status:
                lines.append(f"⭐ 프리미엄 연계: {draft.premium_status}")

            lines.append("")

            if draft.category:
                lines.append(f"📂 카테고리: {draft.category.value}")
            if draft.risk_level:
                lines.append(f"⚠️ 위험도: {draft.risk_level.value}")

            if draft.b2b_updated_at:
                lines.append(
                    f"🕐 마지막 수정: {draft.b2b_updated_at.strftime('%Y-%m-%d %H:%M')}"
                )

            return "\n".join(lines)
        except Exception as e:
            return f"🏢 B2B 상세 표시 실패: {e}"
