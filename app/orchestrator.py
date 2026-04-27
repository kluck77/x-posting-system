"""
오케스트레이터 (5-역할 AI 파이프라인)
======================================
전체 워크플로를 조율합니다:

1. 소스 입력 → DB 저장
2. Researcher: 리서치 (Gemini / Mock)
3. DraftWriter: 초안 생성 (ChatGPT / Claude / Mock)
4. FactChecker: 팩트체크 (Perplexity / Mock)
5. Reviewer: 리스크 판단 & 최종 다듬기 (Claude / Mock)
6. 분류 & 위험도 확정
7. 텔레그램 승인 카드 전송
8. 승인 → X 게시
9. 결과 DB 저장 & 텔레그램 확인

별도: TrendHunter (Grok / Mock) — /trends 명령으로 트렌드 탐색
모든 게시는 사람의 승인이 필요합니다.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models.content import (
    SourceItem, Draft, ContentCategory, RiskLevel, ApprovalStatus,
    SourceItemCreate,
)
from app.services.source_service import SourceService
from app.services.draft_service import DraftService
from app.services.classifier import (
    classify_category, classify_risk,
    classify_community_risk, build_community_warning,
)
from app.services.prediction_service import predict_publish_time
from app.services.telegram_service import send_approval_card
from app.services.rate_limiter import RateLimiter
from app.services.quality_scorer import (
    score_draft, score_5criteria, format_5criteria_report,
    should_regenerate, REGEN_THRESHOLD,
)
from app.providers.ai_provider import AITeam, create_ai_team
from app.providers.base import DraftResult, ResearchResult, FactCheckResult, TrendResult
from app.services.source_pack import build_source_pack
from app.services.angle_pack import build_angle_pack
from app.services.grok_handoff import (
    format_handoff, compose_enriched_source, compose_pack_context,
)
from app.services.pack_sidecar import save_pack
from app.services.korean_context import build_korean_entity_brief
from app.services.frame_classifier import select_frame
from app.services.thread_structurer import structure as structure_thread
from app.services.hook_variants import generate_variants as generate_hook_variants
from app.services.hard_rule_checker import check as hard_check
from app.services.haiku_judge import judge as haiku_judge
from app.sources.freshness_filter import is_fresh
from app.sources.news_importance_classifier import classify_news
from app.sources.breaking_news_dedup import check_and_register
from app.sources.timing_router import route as psych_route, RouteDecision
from app.psych.emotion_tone_analyzer import analyze as tone_analyze
from app.psych.loss_aversion_rewriter import rewrite as loss_rewrite
from app.psych.virality_scorer import score as viral_score
from app.psych.reply_hook_generator import generate as reply_hook
from app.psych.curiosity_gap_injector import inject as curiosity_inject
from app.sources.x_trending_crypto import get_trending_crypto
from app.psych.thread_arc_generator import decompose as thread_decompose
from app.psych.ab_variant_generator import generate as ab_generate
from app.psych.optimal_timing_predictor import format_timing_hint
from app.sources.polymarket_fetcher import (
    get_top_by_category as poly_top_by_cat,
    format_for_post as poly_format_for_post,
)

logger = logging.getLogger(__name__)


# ─── 재료 품질 차단 캐시 ─────────────────────────────────────────────
# ingest_and_generate 에서 BLOCK_RECOMMENDED 감지 시 draft_id → quality dict 기록.
# send_for_approval 가드에서 참조해서 승인 카드 전송 차단.
# 최근 200 건만 유지 (LRU 대용 간이).
_BLOCK_RECOMMENDED_CACHE: dict[int, dict] = {}


def _mark_block_recommended(draft_id: int, quality: dict) -> None:
    if len(_BLOCK_RECOMMENDED_CACHE) >= 200:
        try:
            oldest = next(iter(_BLOCK_RECOMMENDED_CACHE))
            _BLOCK_RECOMMENDED_CACHE.pop(oldest, None)
        except Exception:
            _BLOCK_RECOMMENDED_CACHE.clear()
    _BLOCK_RECOMMENDED_CACHE[draft_id] = quality


def _get_block_recommended(draft_id: int) -> dict | None:
    return _BLOCK_RECOMMENDED_CACHE.get(draft_id)


async def _send_admin_warning(
    chat_id: int | str | None, text: str,
) -> None:
    """승인 카드 차단 시 운영자에게 간이 경고 메시지 — Telegram Bot API 직접 호출.

    chat_id / telegram_bot_token 없으면 로그만 남기고 fail-open.
    """
    try:
        from app.config import settings as _s
        token = getattr(_s, "telegram_bot_token", "") or ""
        target = chat_id or getattr(_s, "telegram_chat_id", "")
        if not token or not target:
            logger.warning(f"[send-guard] 경고 전송 skip (설정 없음): {text[:80]}")
            return
        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                url,
                json={"chat_id": target, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning(f"[send-guard] 경고 전송 실패 (무시): {e}")


# =============================================================================
# Layer 2 헬퍼 — criteria 신호 → 프롬프트 컨텍스트 빌더
# =============================================================================

def _build_criteria_context(
    research: ResearchResult | None = None,
    factcheck: FactCheckResult | None = None,
    trends: TrendResult | None = None,
) -> str:
    """
    가용한 5-criteria 신호를 프롬프트용 텍스트 블록으로 변환합니다.

    - 비어있는 신호는 생략 (empty dict / empty str / None)
    - 호출 실패 시 "" 반환 (Layer 1 보호)
    - interpretation_gaps는 orchestrator Step 3에서 이미 enriched_source에 포함됨 →
      여기서는 fact_labels(고가치 팩트)와 factcheck 신호만 추가

    반환값: "[UPSTREAM CRITERIA SIGNALS]\\n..." 또는 ""
    """
    lines = []

    # Grok TrendHunter 신호 (main pipeline에서는 보통 None — /trends 명령 전용)
    if trends and trends.criteria_signals.any_populated():
        cs = trends.criteria_signals
        if cs.marketability:
            score = cs.marketability.get("score")
            note = (cs.marketability.get("note") or "").strip()
            score_str = f"{score:.1f}/10" if score is not None else "—"
            lines.append(
                f"- Trend marketability: {score_str}" + (f" ({note})" if note else "")
            )
        if cs.follower_quality:
            score = cs.follower_quality.get("score")
            note = (cs.follower_quality.get("note") or "").strip()
            score_str = f"{score:.1f}/10" if score is not None else "—"
            lines.append(
                f"- Follower quality: {score_str}" + (f" ({note})" if note else "")
            )

    # Gemini Researcher — 고가치 팩트 (challenges_assumption / missing_context)
    # interpretation_gaps는 Step 3의 enriched_source에 이미 포함되므로 중복 생략
    if research and research.fact_labels:
        high_value = [
            k[:80]
            for k, v in research.fact_labels.items()
            if v in ("challenges_assumption", "missing_context")
        ]
        if high_value:
            lines.append(
                f"- High-value facts ({len(high_value)}): {high_value[0]}"
            )

    # Perplexity FactChecker 신호
    if factcheck:
        if factcheck.interpretation_opportunity:
            lines.append(
                f"- Interpretation opportunity: {factcheck.interpretation_opportunity[:120]}"
            )
        if factcheck.marketability_signal:
            lines.append(f"- Marketability: {factcheck.marketability_signal}")

    if not lines:
        return ""

    return "[UPSTREAM CRITERIA SIGNALS]\n" + "\n".join(lines)


# =============================================================================
# Layer 2 헬퍼 — Strategy OS advisory inject (Phase C)
# =============================================================================
# Strategy OS 에 저장된 운영 자산(positioning / hook_library / banned_style /
# lenses) 일부를 프롬프트 힌트로만 주입. provider 인터페이스 / DB / Pack Chain /
# approval 에는 접촉하지 않음. 실패 시 "" 리턴 — Layer 1 경로 100% 유지.

_ADVISORY_CAPS = {"lenses": 3, "hooks": 3, "banned": 5}
_ADVISORY_MAX_LEN = 900      # 블록 전체 문자 상한 (프롬프트 오염 방지)
_ADVISORY_ITEM_MAX = 120     # 각 원소 문자 상한 (토큰 폭주 방지)


def _clip_strs(items, limit: int) -> list[str]:
    """타입 오염 방어 + 상한 적용. 어떤 입력이 와도 예외 없이 list[str] 리턴."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        try:
            if isinstance(it, str):
                s = it.strip()
            elif it is None:
                continue
            else:
                s = str(it).strip()
        except Exception:
            continue
        if not s:
            continue
        if len(s) > _ADVISORY_ITEM_MAX:
            s = s[: _ADVISORY_ITEM_MAX - 1] + "…"
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _build_strategy_os_advisory() -> str:
    """
    Strategy OS 에서 advisory 블록을 만든다.
    실패 / 빈 값 / 타입 오염 → "" 리턴. Layer 1 경로는 절대 막지 않음.
    블록 톤은 "참고 우선순위" — 강제 규칙으로 쓰지 말 것.
    """
    try:
        from app.services.strategy_os import load_strategy_os
        data = load_strategy_os()
        pos_raw = data.get("positioning")
        pos = pos_raw if isinstance(pos_raw, dict) else {}
        one_raw = pos.get("one_liner")
        one = str(one_raw).strip() if isinstance(one_raw, str) else ""
        if len(one) > _ADVISORY_ITEM_MAX * 2:
            one = one[: _ADVISORY_ITEM_MAX * 2 - 1] + "…"
        lenses = _clip_strs(pos.get("lenses"),      _ADVISORY_CAPS["lenses"])
        hooks  = _clip_strs(data.get("hook_library"), _ADVISORY_CAPS["hooks"])
        banned = _clip_strs(data.get("banned_style"), _ADVISORY_CAPS["banned"])
        if not one and not lenses and not hooks and not banned:
            return ""
        lines = ["[STRATEGY OS ADVISORY — optional priorities, not hard rules]"]
        if one:
            lines.append(f"Positioning: {one}")
        if lenses:
            lines.append(f"Lenses: {', '.join(lenses)}")
        if hooks:
            lines.append("Hooks (priority, reference only):")
            lines.extend(f"  - {h}" for h in hooks)
        if banned:
            lines.append("Style to avoid:")
            lines.extend(f"  - {b}" for b in banned)
        block = "\n".join(lines)
        if len(block) > _ADVISORY_MAX_LEN:
            block = block[: _ADVISORY_MAX_LEN - 1] + "…"
        return block
    except Exception as e:
        logger.warning(f"[STRATEGY_OS_ADVISORY_SKIP] {e}")
        return ""


class Orchestrator:
    """
    5-역할 AI 파이프라인 오케스트레이터.

    파이프라인 흐름:
    [Source] → [Researcher] → [DraftWriter] → [Reviewer] → [분류/위험도]
            → [DB 저장] → [텔레그램 승인카드] → [승인] → [수동 게시]
    """

    def __init__(self, db: Session | None = None):
        self.db = db or get_db()
        self.source_service = SourceService(self.db)
        self.draft_service = DraftService(self.db)
        self.rate_limiter = RateLimiter(self.db)
        self.ai: AITeam = create_ai_team()

    def _psych_skip_stub(
        self, source_item, reason: str, label: str,
    ) -> Draft:
        """Psych Step 0.x 가 SKIP 결정한 경우 stub Draft 반환.

        Lane early-return 패턴 재사용. AI 미호출, DB 에 마커만 기록.
        호출자는 정상 Draft 반환으로 인식.
        """
        return self.draft_service.create_draft(
            source_item=source_item,
            hook=f"[PSYCH-SKIP:{reason}] {(source_item.title or '')[:80]}",
            body=label,
            category=ContentCategory.SOCIETY,
            risk_level=RiskLevel.LOW,
            risk_reasoning=f"Psych skip: {reason}",
        )

    async def process_youtube_transcript(
        self, analysis, chat_id: int | str | None = None,
    ) -> Draft | None:
        """YoutubeAnalysis → SourceItemCreate 변환 후 5-AI 파이프라인 투입.

        Gemini 직접 영상 분석 → 분석 결과를 body 에 인코딩해서 기존 파이프라인에 투입.
        역할 분담 (body 구조 + 자연 truncation 으로 달성):
          - OpenAI DraftWriter: body 전체 = [STORYTELLING] + [분석 결과]
          - Gemini researcher:  body 앞부분 = 핵심 주장 + 발언
          - Perplexity / Grok:  body[:1000] ≈ downstream_summary 만
          - Haiku Reviewer:     초안만 수신 (변동 없음)

        자동 포스팅 없음. 텔레그램 승인 카드 전송까지만 수행.
        인자명 `analysis` — 과거 `transcript` 유지 목적이 아닌 새 모델 YoutubeAnalysis.
        """
        try:
            from app.sources.youtube_pipeline import (
                YoutubeAnalysis, mark_analysis_used,
            )
        except Exception as e:
            logger.warning(f"[orchestrator YT] 모듈 로드 실패: {e}")
            return None
        if not isinstance(analysis, YoutubeAnalysis):
            logger.warning("[orchestrator YT] YoutubeAnalysis 인스턴스 아님")
            return None

        src = analysis.to_pipeline_input()
        try:
            # source_type="youtube" — Lane early-return _MANUAL_LIKE_SOURCES
            # 화이트리스트에 포함되어 자동수집 오인 없이 AI 파이프라인 진입.
            data = SourceItemCreate(
                title=src["title"],
                url=src["url"],
                source_text=src["body"],
                source_type="youtube",
                language="ko",
            )
        except Exception as e:
            logger.warning(f"[orchestrator YT] SourceItemCreate 실패: {e}")
            return None

        try:
            draft = await self.ingest_and_generate(data)
        except Exception as e:
            logger.warning(f"[orchestrator YT] 파이프라인 실패: {e}")
            return None

        try:
            mark_analysis_used(analysis.video_id)
        except Exception:
            pass

        # 텔레그램 승인 카드 전송 — 수동 트리거이므로 일일 한도 skip
        try:
            sent = await self.send_for_approval(
                draft.id, chat_id=chat_id, skip_telegram_limit=True,
            )
            if not sent:
                logger.warning(
                    f"[orchestrator YT] 승인 카드 전송 실패: draft_id={draft.id}"
                )
        except Exception as e:
            logger.warning(f"[orchestrator YT] send_for_approval 예외: {e}")

        return draft

    async def ingest_and_generate(self, data: SourceItemCreate) -> Draft:
        """
        소스를 입력받아 전체 AI 파이프라인을 실행합니다.

        Steps:
        1. 소스 DB 저장
        2. Researcher: 배경 리서치
        3. DraftWriter: 초안 생성
        4. FactChecker: 팩트체크 (v1: mock)
        5. Reviewer: 최종 판단 & 다듬기
        6. 분류 & 위험도 확정
        7. 초안 DB 저장
        """
        logger.info(f"=== 파이프라인 시작: '{data.title[:50]}' ===")

        # Step 0: (rate check moved to Step 2 — Lane A~C는 AI 비용 없음)
        # BREAKING_NOW / KO-only / Top5 적재 / 주간 즉시 알림은 항상 실행.
        # AI 파이프라인(Steps 2-6)만 레인별 제한 적용.

        # Step 1: 소스 저장
        logger.info("[1/6] 소스 DB 저장")
        source_item = self.source_service.ingest_manual(data)

        # ── Psych Upgrade Phase 1 (Step 0.5~0.8) ────────────────────────
        # 소스 저장 직후 dedup → classify → freshness → routing.
        # skip 결정 시 Lane early-return 패턴(stub Draft) 으로 호출자 contract 보존.
        # 결과는 _psych_meta dict 에 누적 → Step 5.7 에서 editorial_meta 로 머지.
        _psych_meta: dict = {}
        if settings.psych_enabled:
            # Step 0.5: dedup
            # 운영자 수동 입력 lane (manual / youtube / community_input) 은
            # dedup 우회 — simhash + split fallback 의 영어 제목 false
            # positive 차단 + 운영자 의도 우선. 자동 수집 lane (news_link /
            # rss / breaking_news 등) 만 기존 dedup 적용.
            _DEDUP_SKIP_SOURCES = {"manual", "youtube", "community_input"}
            if data.source_type in _DEDUP_SKIP_SOURCES:
                logger.info(
                    f"[Step 0.5 Dedup] 운영자 수동 입력 lane "
                    f"({data.source_type}) — dedup 우회"
                )
            else:
                try:
                    if check_and_register(data.title or ""):
                        logger.info(f"[Step 0.5 Dedup] 중복 스킵: {data.title[:40]}")
                        _psych_meta["psych_skip_reason"] = "duplicate"
                        return self._psych_skip_stub(
                            source_item, "duplicate", "[DEDUP] 중복 뉴스 — AI 미호출"
                        )
                except Exception as _de:
                    logger.warning(f"[Step 0.5 Dedup] 실패 (계속): {_de}")

            # Step 0.6: classify
            _classification = {}
            try:
                _classification = await classify_news(data.title, data.source_text or "")
                _psych_meta["news_classification"] = _classification
                logger.info(
                    f"[Step 0.6 Classifier] importance={_classification.get('importance')} "
                    f"category={_classification.get('category')}"
                )
            except Exception as _ce:
                logger.warning(f"[Step 0.6 Classifier] 실패 (기본값): {_ce}")
                _classification = {"importance": 5, "category": "opinion", "decay_hours": 12}

            _imp = int(_classification.get("importance", 5) or 5)
            _cat = str(_classification.get("category", "opinion") or "opinion")

            # Step 0.7: freshness — source_item.created_at 기준 (live 수집은 거의 통과)
            try:
                _published = getattr(source_item, "created_at", None) or datetime.now(timezone.utc)
                if not is_fresh(_published, _cat, _imp, data.title, data.source_text or ""):
                    logger.info(f"[Step 0.7 Freshness] 오래된 뉴스 스킵 (cat={_cat})")
                    _psych_meta["psych_skip_reason"] = "stale"
                    return self._psych_skip_stub(
                        source_item, "stale", f"[STALE] 오래된 뉴스 (decay 초과, cat={_cat})"
                    )
            except Exception as _fe:
                logger.warning(f"[Step 0.7 Freshness] 실패 (계속): {_fe}")

            # Step 0.8: routing
            try:
                _route = psych_route(data.title or "", _imp, _cat)
                _psych_meta["route_decision"]   = _route.decision.value
                _psych_meta["route_reason"]     = _route.reason
                _psych_meta["route_deadline_m"] = _route.deadline_minutes
                _psych_meta["importance"]       = _imp
                _psych_meta["category"]         = _cat
                if _route.decision == RouteDecision.SKIP:
                    logger.info(f"[Step 0.8 Router] SKIP: {_route.reason}")
                    _psych_meta["psych_skip_reason"] = "low_importance"
                    return self._psych_skip_stub(
                        source_item, "low_importance",
                        f"[SKIP] {_route.reason} — AI 미호출"
                    )
                logger.info(
                    f"[Step 0.8 Router] {_route.decision.value}: {_route.reason}"
                )
            except Exception as _re:
                logger.warning(f"[Step 0.8 Router] 실패 (계속): {_re}")

        # Step 1.5: BREAKING 분류 (fail-open, 메모리 결과만, 알림 미전송)
        # - breaking_classifier 호출만 수행. 텔레그램 / Top5 / DB 저장 연결은 아직 없음.
        # - 실패 시 기존 파이프라인 곃속 진행 (fail-open).
        try:
            from app.services.breaking_classifier import classify_article
            breaking_result = classify_article(
                title=source_item.title,
                body=source_item.source_text,
                publisher=None,
                published_at=source_item.created_at,
                url=source_item.url,
            )
            source_item.breaking_result = breaking_result  # type: ignore[attr-defined]
            logger.info(
                f"[1.5/6] breaking classify: {breaking_result.classification} "
                f"domain={breaking_result.topic_domain} "
                f"urgency={breaking_result.urgency or '-'}"
            )

            # Step 1.5b: CANDIDATE -> Top5 야간 큐 적재 (fail-open)
            if breaking_result.classification == "CANDIDATE":
                try:
                    from app.services.top5_briefing_service import record_candidate
                    record_candidate(
                        title=source_item.title,
                        body=source_item.source_text,
                        url=source_item.url,
                        topic_domain=breaking_result.topic_domain,
                        matched_keywords=breaking_result.matched_keywords,
                        breaking_reason=breaking_result.breaking_reason,
                        urgency=breaking_result.urgency,
                        collected_at=source_item.created_at,
                    )
                except Exception:
                    pass  # fail-open

                # Step 1.5c: 주간 고점수 CANDIDATE 즉시 알림 (fail-open)
                # - 05:00~22:00 KST 에만 동작
                # - 교차검증 4+ / 점수 컴라인 / 즉시성 조건 모두 충송 시 텘렉그램 즉시 알림
                # - Top5 탐 적재(1.5b)와 독립. 둘다 동작해도 충돌 없음.
                try:
                    from app.services.daytime_alert_service import try_daytime_alert
                    _daytime_sent = await try_daytime_alert(
                        title=source_item.title,
                        body=source_item.source_text,
                        url=source_item.url,
                        topic_domain=breaking_result.topic_domain,
                        matched_keywords=breaking_result.matched_keywords,
                        collected_at=source_item.created_at,
                    )
                    if _daytime_sent:
                        logger.info("[1.5c/6] 주간 고점수 CANDIDATE 즉시 알림 전송")
                except Exception:
                    pass  # fail-open

            # Step 1.6: BREAKING_NOW 일 때만 분리된 텔레그램 알림 핸드오프
            if breaking_result.classification == "BREAKING_NOW":
                try:
                    from app.services.breaking_alert_service import send_breaking_alert
                    sent = await send_breaking_alert(
                        breaking_result=breaking_result,
                        title=source_item.title,
                        url=source_item.url,
                        body=source_item.source_text,
                    )
                    logger.info(f"[1.6/6] breaking alert 핸드오프: sent={sent}")
                    # Top5 제외 등록 (BREAKING_NOW 전송분은 Top5에서 제외)
                    if sent:
                        try:
                            from app.services.top5_briefing_service import record_breaking_sent
                            record_breaking_sent(
                                title=source_item.title,
                                topic_domain=breaking_result.topic_domain,
                            )
                        except Exception:
                            pass  # fail-open
                except Exception as e:
                    logger.warning(
                        f"breaking alert 핸드오프 실패 (fail-open, 파이프라인 곃속): {e}"
                    )
        except Exception as e:
            logger.warning(f"breaking classify 실패 (fail-open, 파이프라인 계속): {e}")

        # ── Lane A~C early return (자동수집만) ────────────────────────
        # 자동수집(naver_auto 등)에서 BREAKING_NOW / CANDIDATE 분류된 기사는
        # 알림·적재만 완료하고 AI 파이프라인(Step 2~6)에 진입하지 않는다.
        # 수동 입력(manual / youtube)은 항상 AI 파이프라인을 탄다.
        _br = getattr(source_item, "breaking_result", None)
        _MANUAL_LIKE_SOURCES = {"manual", "youtube"}
        _is_auto = data.source_type not in _MANUAL_LIKE_SOURCES
        if (_is_auto
                and _br is not None
                and _br.classification in ("BREAKING_NOW", "CANDIDATE")):
            logger.info(
                f"[Lane early-return] {_br.classification} 자동수집 — "
                f"AI 파이프라인 건너뜀 (알림/적재만 수행)"
            )
            # 알림 전용 Draft 생성 (AI 미호출, 최소 기록용)
            draft = self.draft_service.create_draft(
                source_item=source_item,
                hook=f"[{_br.classification}] {data.title[:80]}",
                body=f"[{_br.classification}] 알림/적재 완료 — AI 미호출",
                category=classify_category(data.title, data.source_text),
                risk_level=RiskLevel.MEDIUM,
                risk_reasoning=f"Lane {_br.classification}: AI 파이프라인 미진입 (자동수집)",
            )
            logger.info(
                f"=== Lane early-return 완료: draft_id={draft.id}, "
                f"classification={_br.classification} ==="
            )
            return draft

        # Step 1.7: KO-only routing — 한국어 전용 도메인 로그만 남기고
        # AI 파이프라인(Step 2~6)은 정상 진행한다.
        _KO_ONLY_DOMAINS = {"금융", "투자", "크립토", "주식"}
        _KO_ONLY_CLASSES = {"BREAKING_NOW", "CANDIDATE"}
        try:
            if (_br is not None
                    and _br.classification in _KO_ONLY_CLASSES
                    and _br.topic_domain in _KO_ONLY_DOMAINS):
                logger.info(
                    f"[1.7/6] KO-only domain detected: {_br.classification} "
                    f"domain={_br.topic_domain} — AI pipeline continues"
                )
        except Exception as e:
            logger.warning(f"[1.7] KO routing check failed (fail-open): {e}")

        # Step 2 rate check: AI 파이프라인 진입 제한 (비용 보호)
        # - 수동 입력(manual)은 제한 우회 — 운영자 직접 요청
        # - 자동수집만 레인별 제한 적용
        if data.source_type != "manual":
            can_ai, ai_msg = self.rate_limiter.can_run_ai_pipeline(
                source_type=data.source_type,
            )
            if not can_ai:
                raise RuntimeError(f"일일 제한 초과: {ai_msg}")
        else:
            logger.info("[2/6] 수동 입력 — AI rate limit 우회")

        # 한국 맥락 엔티티 프리페치 (Gemini·DraftWriter 공통 주입)
        # YouTube 95% 보존형 lane 은 영상 원문에 없는 외부 KR DB 맥락 자동
        # 주입을 차단 — 영상 자막에 네이버/카카오/스테이블코인 같은 키워드
        # 하나만 있어도 외부 정책/회사 데이터가 GPT 입력에 섞이는 문제
        # 방지. 영상 자체 안의 한국 내용은 source_text 에 그대로 남음.
        _kr_brief = ""
        if data.source_type != "youtube":
            try:
                _kr_brief = build_korean_entity_brief(
                    data.title, data.source_text,
                )
            except Exception as _kc_e:
                logger.warning(f"[korean_context] 프리페치 실패 (무시): {_kc_e}")

        _gemini_ctx = data.source_text[:1000]
        if _kr_brief:
            _gemini_ctx = f"{_kr_brief}\n\n{_gemini_ctx}"
            logger.info(
                f"[korean_context] Gemini 에 KR 엔티티 브리프 주입 ({len(_kr_brief)}자)"
            )

        # Step 2: Researcher — 배경 리서치
        logger.info("[2/6] Researcher: 리서치")
        try:
            research = await self.ai.researcher.research(
                query=data.title, context=_gemini_ctx,
            )
            if research.criteria_signals.any_populated():
                logger.info(
                    f"[Researcher criteria] {research.criteria_signals.to_log_str()}"
                )
        except Exception as e:
            logger.warning(f"리서치 실패, 빈 결과 사용: {e}")
            research = ResearchResult(
                summary=data.source_text[:500],
                sources=[data.url] if data.url else [],
            )

        # Step 2.5: Pack Chain (Grok Handoff, Phase 1) — flag gated
        # research 직후, draft 생성 전에 factcheck 를 선행시켜 source/angle pack 구성.
        # 실패 시 [PACK_CHAIN_FALLBACK] 로그 + legacy 경로로 자연 복귀 (변수 초기화만).
        pack_chain_data: dict | None = None
        _precomputed_factcheck: FactCheckResult | None = None
        if settings.pack_chain_enabled:
            try:
                # 2.5.1 factcheck 선행 (source_text 기준 — legacy 는 draft.body 기준)
                try:
                    _precomputed_factcheck = await self.ai.fact_checker.check_facts(
                        claim=data.source_text[:1500],
                        context=data.title[:500],
                    )
                except Exception as _fc_e:
                    logger.warning(
                        f"[pack_chain] pre-factcheck 실패 (pack 만 heuristic): {_fc_e}"
                    )
                    _precomputed_factcheck = None

                # 2.5.2 source_pack
                _source_pack = build_source_pack(
                    source_item=source_item,
                    input_data=data,
                    research=research,
                    factcheck=_precomputed_factcheck,
                )
                # 2.5.3 angle_pack (Gemini 1회 or heuristic)
                _angle_pack = await build_angle_pack(_source_pack, self.ai)
                _winner = _angle_pack.get("winner_angle") or {}

                # 2.5.4 compose
                _enriched_source = compose_enriched_source(
                    original=data.source_text,
                    source_pack=_source_pack,
                    winner_angle=_winner,
                )
                _pack_context = compose_pack_context(_source_pack, _winner)

                pack_chain_data = {
                    "source_pack":           _source_pack,
                    "angle_pack":            _angle_pack,
                    "enriched_source_pack":  _enriched_source,
                    "pack_context":          _pack_context,
                    "precomputed_factcheck": _precomputed_factcheck,
                }
                logger.info(
                    f"[pack_chain] active — winner={str(_winner.get('angle', ''))[:80]} "
                    f"frame={_angle_pack.get('frame_type', '?')} "
                    f"spine={'/'.join(str(p) for p in (_angle_pack.get('story_spine') or [])[:5])} "
                    f"risk={_angle_pack.get('readability_risk', '?')}"
                )

                # 재료 품질 게이트 — BLOCK_RECOMMENDED 감지 시 후단 차단 플래그 기록.
                # 실제 차단은 send_for_approval 의 block_recommended 가드에서 수행.
                try:
                    from app.services.handoff_quality_guard import run_quality_guard
                    _guard_input = dict(_source_pack)
                    _guard_input["angle_pack"] = _angle_pack
                    _quality = run_quality_guard(_guard_input)
                    pack_chain_data["quality_guard"] = _quality
                    if _quality.get("block_recommended"):
                        logger.warning(
                            f"[pack_chain] BLOCK_RECOMMENDED — HIGH "
                            f"{_quality.get('high_count', 0)}개 감지. "
                            f"승인 카드 전송 차단 대상."
                        )
                except Exception as _qg_e:
                    logger.warning(
                        f"[pack_chain] quality_guard 실패 (무시): {_qg_e}"
                    )
            except Exception as _pc_e:
                logger.warning(
                    f"[PACK_CHAIN_FALLBACK] {type(_pc_e).__name__}: {_pc_e}"
                )
                pack_chain_data = None
                _precomputed_factcheck = None

        # Step 2.7: Frame Classifier — CONSTITUTION v2 섹션 4 12 프레임 중 하나 선택
        # 순서: angle_pack 매핑 → Claude Haiku LLM → default(3). 실패해도 default 반환.
        _frame_selection = None
        try:
            _angle_pack_for_frame = (
                pack_chain_data.get("angle_pack") if pack_chain_data else None
            )
            _frame_selection = await select_frame(
                title=data.title,
                source_text=data.source_text,
                angle_pack=_angle_pack_for_frame,
            )
            logger.info(
                f"[2.7/6] frame: {_frame_selection.frame_id}.{_frame_selection.frame_name} "
                f"(src={_frame_selection.source})"
            )
        except Exception as _fr_e:
            logger.warning(f"[frame_classifier] 호출 실패 (무시): {_fr_e}")
            _frame_selection = None

        # Step 3: DraftWriter — 초안 생성
        logger.info("[3/6] DraftWriter: 초안 생성")

        # Layer 2: research 신호로 DraftWriter 컨텍스트 빌드 (실패 시 "" — Layer 1 보호)
        try:
            draft_criteria_ctx = _build_criteria_context(research=research)
            if draft_criteria_ctx:
                logger.debug(
                    f"[criteria_context] DraftWriter 주입: {len(draft_criteria_ctx)}자"
                )
        except Exception as _ctx_err:
            logger.warning(f"[criteria_context] DraftWriter 빌드 실패 (무시): {_ctx_err}")
            draft_criteria_ctx = ""

        # Layer 2: operator hints (manual_notes → DraftWriter advisory, 실패 시 무시)
        try:
            hints = self.draft_service.get_recent_operator_hints(limit=3)
            if hints:
                hints_block = "[OPERATOR HINTS]\n" + "\n".join(f"- {h}" for h in hints)
                draft_criteria_ctx = (
                    (draft_criteria_ctx + "\n\n" + hints_block).strip()
                    if draft_criteria_ctx
                    else hints_block
                )
                logger.debug(f"[OperatorHints] DraftWriter 주입: {len(hints)}개")
        except Exception as _hint_err:
            logger.warning(f"[OperatorHints] 주입 실패 (무시): {_hint_err}")

        # Layer 2: Strategy OS advisory (Phase C — fail-open)
        try:
            so_advisory = _build_strategy_os_advisory()
            if so_advisory:
                draft_criteria_ctx = (
                    (draft_criteria_ctx + "\n\n" + so_advisory).strip()
                    if draft_criteria_ctx else so_advisory
                )
                logger.debug(f"[StrategyOS] DraftWriter 주입: {len(so_advisory)}자")
        except Exception as _so_err:
            logger.warning(f"[STRATEGY_OS_ADVISORY_SKIP] draft path: {_so_err}")

        try:
            # Gemini interpretation_gaps를 source_text에 추가 → DraftWriter가 해석 각도 활용
            enriched_source = data.source_text
            if research.interpretation_gaps:
                gaps_text = "\n".join(f"- {g}" for g in research.interpretation_gaps[:3])
                enriched_source = (
                    f"{data.source_text}\n\n"
                    f"[Researcher identified interpretation gaps — use these for your angle]:\n"
                    f"{gaps_text}"
                )
            # Pack chain 활성 시 pack 기반 enriched_source / pack_context 로 override
            if pack_chain_data:
                enriched_source = pack_chain_data["enriched_source_pack"]
                _pack_ctx = pack_chain_data["pack_context"]
                draft_criteria_ctx = (
                    (draft_criteria_ctx + "\n\n" + _pack_ctx).strip()
                    if draft_criteria_ctx else _pack_ctx
                )
            # 한국 맥락 엔티티 브리프 prepend (Step 2 에서 생성된 _kr_brief 재사용)
            if _kr_brief:
                draft_criteria_ctx = (
                    f"{_kr_brief}\n\n{draft_criteria_ctx}".strip()
                    if draft_criteria_ctx else _kr_brief
                )
            # Frame 블록은 맨 위에 prepend — DraftWriter 가 본문 구조 고정에 사용
            if _frame_selection is not None:
                _frame_block = _frame_selection.to_context_block()
                draft_criteria_ctx = (
                    f"{_frame_block}\n\n{draft_criteria_ctx}".strip()
                    if draft_criteria_ctx else _frame_block
                )
            # YouTube 95% 보존형 lane 만 source_text cap 8000 (다른 lane 3000 유지)
            _src_cap = 8000 if data.source_type == "youtube" else 3000
            draft_result = await self.ai.draft_writer.generate_draft(
                title=data.title,
                source_text=enriched_source[:_src_cap],
                language=data.language or settings.default_language,
                source_type=data.source_type,
                criteria_context=draft_criteria_ctx,
            )
        except Exception as e:
            logger.warning(f"DraftWriter 실패, 기본 초안 사용: {e}")
            draft_result = DraftResult(
                hook=f"🇰🇷 {data.title[:80]}",
                body=f"Korea update: {data.title[:200]}",
                category_suggestion="society",
            )

        # Step 4: FactChecker — 팩트체크
        logger.info("[4/6] FactChecker: 검증")
        if pack_chain_data and _precomputed_factcheck is not None:
            # pack chain 이 이미 source_text 기준으로 factcheck 수행 — 중복 호출 회피
            factcheck = _precomputed_factcheck
            logger.info("[pack_chain] factcheck 재사용 (pre-computed, source 기준)")
        else:
            try:
                factcheck = await self.ai.fact_checker.check_facts(
                    claim=draft_result.body, context=data.source_text[:500],
                )
                if factcheck and factcheck.criteria_signals.any_populated():
                    logger.info(
                        f"[FactChecker criteria] {factcheck.criteria_signals.to_log_str()}"
                    )
            except Exception as e:
                logger.warning(f"FactChecker 실패: {e}")
                factcheck = None

        # Step 4.5: 5-Criteria 품질 필터 (Reviewer 전 사전 체크)
        criteria_result = score_5criteria(
            draft_result.hook, draft_result.body, data.source_type
        )
        logger.info(
            f"5-Criteria 결과: {criteria_result['total']}/100 [{criteria_result['action']}] "
            f"flags={criteria_result['flags']}"
        )
        if criteria_result["action"] == "reject":
            logger.warning(
                "5-Criteria REJECT — 초안이 품질 기준 미달. "
                "Reviewer 단계(Step 5.5)에서 regenerate 판단에 위임."
            )
            # NOTE: 이전에는 여기서 DraftWriter를 추가 호출했으나,
            # Step 5.5 Reviewer regenerate 루프와 이중 재생성이 되어 비용 낭비.
            # Reviewer가 regenerate 판단을 내리면 그때 재생성한다.

        # Layer 2: research + factcheck 신호로 Reviewer 컨텍스트 빌드 (실패 시 "" — Layer 1 보호)
        try:
            review_criteria_ctx = _build_criteria_context(
                research=research, factcheck=factcheck
            )
            if review_criteria_ctx:
                logger.debug(
                    f"[criteria_context] Reviewer 주입: {len(review_criteria_ctx)}자"
                )
        except Exception as _ctx_err:
            logger.warning(f"[criteria_context] Reviewer 빌드 실패 (무시): {_ctx_err}")
            review_criteria_ctx = ""

        # Layer 2: Strategy OS advisory (Phase C — fail-open)
        try:
            so_advisory = _build_strategy_os_advisory()
            if so_advisory:
                review_criteria_ctx = (
                    (review_criteria_ctx + "\n\n" + so_advisory).strip()
                    if review_criteria_ctx else so_advisory
                )
                logger.debug(f"[StrategyOS] Reviewer 주입: {len(so_advisory)}자")
        except Exception as _so_err:
            logger.warning(f"[STRATEGY_OS_ADVISORY_SKIP] review path: {_so_err}")

        # Pack chain 활성 시 pack_context 를 Reviewer criteria_context 에 합침
        if pack_chain_data:
            _pack_ctx = pack_chain_data["pack_context"]
            review_criteria_ctx = (
                (review_criteria_ctx + "\n\n" + _pack_ctx).strip()
                if review_criteria_ctx else _pack_ctx
            )

        # Step 5: Reviewer — 리스크 판단 & 최종 다듬기
        logger.info("[5/6] Reviewer: 최종 판단")
        try:
            review = await self.ai.reviewer.review_and_refine(
                title=data.title,
                source_text=data.source_text,
                draft=draft_result,
                research=research,
                factcheck=factcheck,
                criteria_context=review_criteria_ctx,
            )
        except Exception as e:
            logger.warning(f"Reviewer 실패, DraftWriter 결과 직접 사용: {e}")
            from app.providers.base import ReviewResult
            review = ReviewResult(
                hook=draft_result.hook,
                body=draft_result.body,
                thread_continuation=draft_result.thread_continuation,
                category=draft_result.category_suggestion,
                risk_level="medium",
                risk_reasoning=f"Reviewer 실패, 안전하게 medium 설정: {e}",
                ai_rationale="Fallback: reviewer unavailable.",
            )

        # Step 5.5: Reviewer regenerate 권고 처리 (루프 + 안전장치)
        # 비용 보호: 1회 재생성으로 통과 못 하면 수동 검토로 넘김
        MAX_REGEN_ATTEMPTS = 1
        regen_attempts = 0

        while review.recommended_action == "regenerate" and regen_attempts < MAX_REGEN_ATTEMPTS:
            # regeneration_hint 우선, 없으면 ai_rationale 사용
            hint = (review.regeneration_hint or review.ai_rationale or "").strip()
            if not hint:
                logger.warning(
                    f"[Regen] regenerate 권고지만 hint 없음 — 무한루프 방지를 위해 건너뜀"
                )
                break

            regen_attempts += 1
            logger.warning(
                f"[Regen {regen_attempts}/{MAX_REGEN_ATTEMPTS}] "
                f"재생성 시도: {hint[:120]}"
            )

            try:
                regen_source = (
                    data.source_text
                    + f"\n\n[REGENERATION GUIDANCE #{regen_attempts}]: {hint}"
                )
                # YouTube 95% 보존형 lane 만 source_text cap 8000 (다른 lane 3000 유지)
                _regen_src_cap = 8000 if data.source_type == "youtube" else 3000
                draft_result = await self.ai.draft_writer.generate_draft(
                    title=data.title,
                    source_text=regen_source[:_regen_src_cap],
                    language=data.language or settings.default_language,
                    source_type=data.source_type,
                    criteria_context=review_criteria_ctx,
                )
                review = await self.ai.reviewer.review_and_refine(
                    title=data.title,
                    source_text=data.source_text,
                    draft=draft_result,
                    research=research,
                    factcheck=factcheck,
                    criteria_context=review_criteria_ctx,
                )
                logger.info(
                    f"[Regen {regen_attempts}] 재평가 완료: "
                    f"action={review.recommended_action}"
                )
            except Exception as e:
                logger.warning(f"[Regen {regen_attempts}] 재생성 실패: {e}")
                break

        # 최대 시도 후에도 regenerate → 수동 검토로 전환
        if review.recommended_action == "regenerate":
            logger.error(
                f"[Regen] 최대 재생성 횟수({MAX_REGEN_ATTEMPTS}회) 도달 — "
                f"수동 검토 필요로 전환"
            )
            review.recommended_action = "review"
            review.ai_rationale = (
                f"[재생성 {regen_attempts}회 후 미통과 — 수동 검토 필요] "
                + review.ai_rationale
            )

        # --- Step 5.7: Thread Structurer + Hook Variants ---
        # review 확정 후 단일포스트/스레드 분해 + 훅 3변형 생성. 모두 fail-soft.
        # 결과는 _step57_meta 에 적재 — 후단 editorial_meta(_meta) 에 setdefault 머지.
        _step57_meta: dict = {}
        _frame_name_for_57 = (
            _frame_selection.frame_name if _frame_selection is not None else ""
        )
        try:
            _thread_result = structure_thread(
                hook=review.hook or draft_result.hook or "",
                body=review.body or draft_result.body or "",
                frame_name=_frame_name_for_57,
            )
            logger.info(
                f"[Step 5.7 Thread] is_thread={_thread_result.is_thread} "
                f"tweets={_thread_result.tweet_count}"
            )
        except Exception as _ts_e:
            logger.warning(f"[Step 5.7 Thread] 실패 (무시): {_ts_e}")
            _thread_result = None

        try:
            _hook_variants = await generate_hook_variants(
                hook=review.hook or draft_result.hook or "",
                body=review.body or draft_result.body or "",
                frame_name=_frame_name_for_57,
            )
            logger.info(
                f"[Step 5.7 Hook] selected={_hook_variants.selected_type} "
                f"hook={_hook_variants.selected[:30]}"
            )
        except Exception as _hv_e:
            logger.warning(f"[Step 5.7 Hook] 실패 (무시): {_hv_e}")
            _hook_variants = None

        if _thread_result is not None:
            _step57_meta["thread_structure"] = {
                "is_thread":    _thread_result.is_thread,
                "tweet_count":  _thread_result.tweet_count,
                "tweets":       _thread_result.tweets,
                "single_post":  _thread_result.single_post,
            }
        if _hook_variants is not None:
            _step57_meta["hook_variants"] = {
                "original":       _hook_variants.original,
                "data_shock":     _hook_variants.data_shock,
                "contrarian":     _hook_variants.contrarian,
                "forcing":        _hook_variants.forcing,
                "selected":       _hook_variants.selected,
                "selected_type":  _hook_variants.selected_type,
            }
        # --- end Step 5.7 ---

        # editorial_meta: Step 5.8/5.9 결과 누적 → 후단 pack_sidecar 에서 _meta 와 merge
        editorial_meta: dict = {}

        # Psych Step 0.5~0.8 결과 머지 (importance/category/route_decision 등)
        try:
            for _pk, _pv in (_psych_meta or {}).items():
                editorial_meta.setdefault(_pk, _pv)
        except Exception:
            pass

        # openai_provider 가 tone_notes 에 archetype 을 실어 옴 — editorial_meta 로 이동
        try:
            _archetype_from_draft = (getattr(draft_result, "tone_notes", "") or "").strip()
            if _archetype_from_draft and _archetype_from_draft in (
                "onchain_1person", "breaking_news", "researcher",
                "policy_definitive", "macro_contrast", "semiconductor", "builder",
            ):
                editorial_meta["archetype"] = _archetype_from_draft
        except Exception:
            pass

        # --- Step 5.8: Hard Rule Checker (L1 결정론적 강제) ---
        # editorial/banned_terms.yaml 기반 regex + morpheme + 문체 검사.
        # fail-soft: 예외 시 _hard_result = None.
        _hard_result = None
        try:
            _draft_text_for_check = "\n\n".join(filter(None, [
                (getattr(review, "hook", "") or getattr(draft_result, "hook", "") or ""),
                (getattr(review, "body", "") or getattr(draft_result, "body", "") or ""),
            ]))
            _hard_result = hard_check(_draft_text_for_check)
            logger.info(
                f"[Step 5.8 HardRule] passed={_hard_result.passed} "
                f"violations={len(_hard_result.violations)} "
                f"ms={_hard_result.duration_ms:.1f}"
            )
            editorial_meta["hard_rule_result"] = {
                "passed": _hard_result.passed,
                "violations": [
                    {"id": v.rule_id, "surface": v.surface, "severity": v.severity}
                    for v in _hard_result.violations
                ],
            }
        except Exception as _hr_e:
            logger.warning(f"[Step 5.8 HardRule] 실패 (무시): {_hr_e}")

        # --- Step 5.85: Emotion Tone Analyzer (KoELECTRA → Haiku fallback) ---
        # Step 5.8 직후. 결과는 editorial_meta["tone"] / ["tone_confidence"].
        if settings.psych_enabled:
            try:
                _tone_text = "\n".join(filter(None, [
                    (getattr(review, "hook", "") or getattr(draft_result, "hook", "") or ""),
                    (getattr(review, "body", "") or getattr(draft_result, "body", "") or ""),
                ]))
                _tone_result = await tone_analyze(_tone_text)
                editorial_meta["tone"]            = _tone_result.get("tone", "neutral")
                editorial_meta["tone_confidence"] = _tone_result.get("confidence", 0.5)
                editorial_meta["tone_source"]     = _tone_result.get("source", "")
                logger.info(
                    f"[Step 5.85 EmotionTone] tone={_tone_result.get('tone','neutral')} "
                    f"conf={float(_tone_result.get('confidence',0.5)):.2f} "
                    f"src={_tone_result.get('source','')}"
                )
            except Exception as _te:
                logger.warning(f"[Step 5.85 EmotionTone] 실패 (무시): {_te}")

        # ── Phase 2 Psych (Step 5.86~5.90) ──────────────────────────────
        # 모두 fail-soft. editorial_meta 에 결과 누적.
        if settings.psych_enabled:
            # Step 5.86 — 손실회피 언어 변환
            try:
                _loss_result = await loss_rewrite(
                    getattr(review, "body", "") or getattr(draft_result, "body", "") or ""
                )
                if _loss_result.get("changed"):
                    logger.info(
                        f"[Step 5.86 LossAversion] "
                        f"변환 {_loss_result.get('changes_count', 0)}건 "
                        f"src={_loss_result.get('source', '')}"
                    )
                    # review.body 가 canonical — 이후 단계도 동기화됨
                    review.body = _loss_result.get("rewritten", review.body)
                    editorial_meta["loss_aversion_changes"] = \
                        _loss_result.get("changes_count", 0)
                    editorial_meta["loss_aversion_source"] = \
                        _loss_result.get("source", "")
            except Exception as _le:
                logger.warning(f"[Step 5.86 LossAversion] 실패 (무시): {_le}")

            # Step 5.87 — 호기심 갭 삽입 (curiosity_gap_enabled=True 일 때만 실제 작동)
            try:
                _gap_result = await curiosity_inject(
                    getattr(review, "body", "") or ""
                )
                if _gap_result.get("changed"):
                    logger.info(
                        f"[Step 5.87 CuriosityGap] "
                        f"pattern={_gap_result.get('pattern', '')} "
                        f"gap={(_gap_result.get('gap_text') or '')[:30]}"
                    )
                    review.body = _gap_result.get("injected_text", review.body)
                    editorial_meta["curiosity_gap"] = _gap_result.get("gap_text", "")
                    editorial_meta["curiosity_pattern"] = _gap_result.get("pattern", "")
            except Exception as _ge:
                logger.warning(f"[Step 5.87 CuriosityGap] 실패 (무시): {_ge}")

            # Step 5.88 — 바이럴 스코어 (0-100, 70 미만 warning)
            try:
                _viral_text = "\n".join(filter(None, [
                    getattr(review, "hook", "") or "",
                    getattr(review, "body", "") or "",
                ]))
                _viral_result = await viral_score(_viral_text)
                editorial_meta["viral_score"]    = _viral_result.get("total_score", 0)
                editorial_meta["viral_warning"]  = _viral_result.get("is_warning", False)
                editorial_meta["viral_feedback"] = _viral_result.get("feedback_ko", "")
                editorial_meta["viral_breakdown"] = _viral_result.get("breakdown", {})
                logger.info(
                    f"[Step 5.88 ViralScore] "
                    f"total={_viral_result.get('total_score', 0)}/100 "
                    f"warning={_viral_result.get('is_warning', False)}"
                )
            except Exception as _ve:
                logger.warning(f"[Step 5.88 ViralScore] 실패 (무시): {_ve}")

            # Step 5.89 — 리플 유도 질문 append
            try:
                _tone = editorial_meta.get("tone", "neutral")
                _hook_result = await reply_hook(
                    getattr(review, "body", "") or "",
                    _tone,
                )
                if _hook_result.get("hook"):
                    editorial_meta["reply_hook"]      = _hook_result.get("hook", "")
                    editorial_meta["reply_hook_type"] = _hook_result.get("type", "")
                    # 본문에 append (이후 save 반영)
                    review.body = _hook_result.get("appended_text", review.body)
                    logger.info(
                        f"[Step 5.89 ReplyHook] "
                        f"type={_hook_result.get('type', '')} "
                        f"hook={(_hook_result.get('hook') or '')[:30]}"
                    )
            except Exception as _he:
                logger.warning(f"[Step 5.89 ReplyHook] 실패 (무시): {_he}")

            # Step 5.90 — X 트렌딩 크립토 (telemetry only, 15분 캐시)
            try:
                _trending = await get_trending_crypto()
                if _trending:
                    editorial_meta["x_trending"] = _trending[:5]
                    logger.info(f"[Step 5.90 XTrending] {_trending[:3]}")
            except Exception as _xe:
                logger.warning(f"[Step 5.90 XTrending] 실패 (무시): {_xe}")

            # Step 5.90B — 폴리마켓 컨텍스트 주입 (카테고리 매핑 + 상위 3개)
            try:
                _ctg_raw = editorial_meta.get("category", "crypto") or "crypto"
                _poly_map = {
                    "crypto":        "crypto",
                    "macro":         "macro",
                    "regulation":    "policy",
                    "dart_critical": "crypto",
                }
                _poly_cat = _poly_map.get(_ctg_raw, "macro")
                _poly_items = poly_top_by_cat(_poly_cat, limit=3)
                if _poly_items:
                    editorial_meta["polymarket_context"] = _poly_items
                    editorial_meta["polymarket_text"] = poly_format_for_post(_poly_items)
                    logger.info(
                        f"[Step 5.90B Polymarket] {len(_poly_items)}개 시장 "
                        f"(cat={_poly_cat})"
                    )
            except Exception as _pe:
                logger.warning(f"[Step 5.90B Polymarket] 실패 (무시): {_pe}")

            # Step 5.91 — 타래 분해 판단 (complexity ≥ 2.0)
            try:
                _thread_src = "\n".join(filter(None, [
                    getattr(review, "hook", "") or "",
                    getattr(review, "body", "") or "",
                ]))
                _td_result = await thread_decompose(_thread_src)
                editorial_meta["is_thread_recommended"] = _td_result.get("is_thread", False)
                editorial_meta["complexity_score"]      = _td_result.get("complexity_score", 0.0)
                if _td_result.get("is_thread"):
                    editorial_meta["thread_tweets_arc"] = _td_result.get("tweets", [])
                    logger.info(
                        f"[Step 5.91 ThreadArc] 타래 추천 "
                        f"complexity={_td_result.get('complexity_score', 0.0):.2f} "
                        f"tweets={len(_td_result.get('tweets') or [])}"
                    )
                else:
                    logger.info(
                        f"[Step 5.91 ThreadArc] 단일 포스트 유지 "
                        f"complexity={_td_result.get('complexity_score', 0.0):.2f}"
                    )
            except Exception as _tde:
                logger.warning(f"[Step 5.91 ThreadArc] 실패 (무시): {_tde}")

            # Step 5.92 — A/B 훅 생성 (ab_test_enabled=True 시에만 실제 호출)
            try:
                _news_id = str(
                    getattr(source_item, "id", None)
                    or getattr(data, "id", None)
                    or hash(data.title or "")
                )
                _ab_src = "\n".join(filter(None, [
                    getattr(review, "hook", "") or "",
                    getattr(review, "body", "") or "",
                ]))
                _ab_result = await ab_generate(_ab_src, _news_id)
                if _ab_result is not None:
                    editorial_meta["ab_variant_a"] = _ab_result.variant_a
                    editorial_meta["ab_variant_b"] = _ab_result.variant_b
                    editorial_meta["ab_news_id"]   = _ab_result.news_id
                    logger.info(
                        f"[Step 5.92 ABVariant] "
                        f"A={_ab_result.variant_a[:20]} "
                        f"B={_ab_result.variant_b[:20]}"
                    )
            except Exception as _abe:
                logger.warning(f"[Step 5.92 ABVariant] 실패 (무시): {_abe}")

            # Step 5.93 — 최적 타이밍 힌트
            try:
                _ctg = editorial_meta.get("category", "crypto") or "crypto"
                _timing_hint = format_timing_hint(_ctg)
                if _timing_hint:
                    editorial_meta["timing_hint"] = _timing_hint
                    logger.info(f"[Step 5.93 Timing] {_timing_hint}")
            except Exception as _time_e:
                logger.warning(f"[Step 5.93 Timing] 실패 (무시): {_time_e}")

        # --- Step 5.9: Haiku Soft Rule Judge (L2 정성 평가 + 최대 2회 재생성) ---
        _judge_result = None
        _MAX_JUDGE_RETRY = 2
        for _judge_attempt in range(_MAX_JUDGE_RETRY + 1):
            try:
                _judge_text = "\n\n".join(filter(None, [
                    (getattr(review, "hook", "") or getattr(draft_result, "hook", "") or ""),
                    (getattr(review, "body", "") or getattr(draft_result, "body", "") or ""),
                ]))
                _judge_result = await haiku_judge(_judge_text)
                logger.info(
                    f"[Step 5.9 Judge] attempt={_judge_attempt} "
                    f"pass={_judge_result.passed} "
                    f"total={_judge_result.total}/130 "
                    f"cached={_judge_result.cached_tokens} "
                    f"ms={_judge_result.duration_ms:.0f}"
                )
                editorial_meta["judge_result"] = {
                    "passed": _judge_result.passed,
                    "total":  _judge_result.total,
                    "scores": _judge_result.scores,
                    "violations":          _judge_result.violations,
                    "must_regenerate_ids": _judge_result.must_regenerate_ids,
                    "attempt": _judge_attempt,
                }
                if _judge_result.passed:
                    break
                if _judge_attempt >= _MAX_JUDGE_RETRY:
                    logger.warning("[Step 5.9 Judge] 최대 재시도 초과. 현재 결과 사용.")
                    break
                # 재생성 지시 조립
                _regen_parts: list[str] = []
                if _judge_result.must_regenerate_ids:
                    _regen_parts.append(
                        f"[Judge 위반 수정 필수]: "
                        f"{', '.join(_judge_result.must_regenerate_ids)}"
                    )
                if _judge_result.targeted_fixes:
                    _regen_parts.append(
                        f"[수정 사항]: {'; '.join(_judge_result.targeted_fixes)}"
                    )
                if _hard_result is not None and not _hard_result.passed:
                    _regen_parts.append(
                        f"[Hard Rule 위반]: {_hard_result.rewrite_instruction}"
                    )
                if _regen_parts:
                    draft_criteria_ctx = (
                        draft_criteria_ctx + "\n\n" + "\n".join(_regen_parts)
                    ).strip()
                # draft_writer 재호출 (review 는 update 하지 않음 → 후단 review 가
                # 새 draft 로 덮일 때까지 유지. 본 구현은 draft_result 만 갱신)
                try:
                    # YouTube 95% 보존형 lane 만 source_text cap 8000 (다른 lane 3000 유지)
                    _judge_src_cap = 8000 if data.source_type == "youtube" else 3000
                    draft_result = await self.ai.draft_writer.generate_draft(
                        title=data.title,
                        source_text=enriched_source[:_judge_src_cap],
                        language=data.language or settings.default_language,
                        source_type=data.source_type,
                        criteria_context=draft_criteria_ctx,
                    )
                    # 다음 Judge 가 새 draft 를 평가하도록 review.hook/body 동기화
                    review.hook = draft_result.hook
                    review.body = draft_result.body
                except Exception as _re:
                    logger.warning(f"[Step 5.9 Judge] 재생성 실패 (현재 결과 유지): {_re}")
                    break
            except Exception as _je:
                logger.warning(f"[Step 5.9 Judge] 오류 (무시): {_je}")
                break

        # --- Phase A: critic pass (voice / hook / ending / fact) ---
        # settings.skip_phase_a = True (기본) 이면 Haiku Judge 로 대체됨.
        # False 로 되돌리면 기존 4 critic 복원.
        _critic_meta: dict = {}
        if not settings.skip_phase_a:
            review_text = f"{review.hook}\n{review.body}"
            try:
                _voice_result = await self.ai.reviewer.voice_critic(review_text)
                _hook_result = await self.ai.reviewer.hook_critic(review_text)
                _ending_result = await self.ai.reviewer.ending_critic(review_text)
                _critic_meta["voice_flags"] = _voice_result
                _critic_meta["hook_score"] = _hook_result
                _critic_meta["ending_score"] = _ending_result
            except Exception as _cr_e:
                logger.warning(f"[critic] voice/hook/ending 호출 실패 (무시): {_cr_e}")
            try:
                _factcheck_dict = (
                    {
                        "verified": getattr(factcheck, "verified", None),
                        "confidence": getattr(factcheck, "confidence", None),
                        "corrections": list(getattr(factcheck, "corrections", []) or []),
                        "sources": list(getattr(factcheck, "sources", []) or []),
                    }
                    if factcheck is not None
                    else {}
                )
                _fact_critic_result = await self.ai.fact_checker.fact_critic(
                    review_text, _factcheck_dict,
                )
                _critic_meta["factcheck_guard"] = _fact_critic_result
                if _fact_critic_result.get("publish_block"):
                    _critic_meta["publish_block"] = True
                    _critic_meta["publish_block_reason"] = _fact_critic_result.get(
                        "publish_block_reason",
                        "fact_critic: unverified claim detected",
                    )
                    logger.warning(
                        "[critic] publish_block=True — approval_status 는 pending 유지, "
                        "자동 차단 아님. Telegram 승인 단계에서 수동 결정."
                    )
                else:
                    _critic_meta["publish_block"] = False
                    _critic_meta["publish_block_reason"] = None
            except Exception as _fc_e:
                logger.warning(f"[critic] fact_critic 호출 실패 (무시): {_fc_e}")
        else:
            logger.info("[Phase A] skip_phase_a=True — Haiku Judge 로 대체됨")
        # --- end Phase A critic pass ---

        # Step 6: 분류 & 위험도 확정
        logger.info("[6/6] 분류 & 위험도 확정")
        try:
            category = ContentCategory(review.category)
        except ValueError:
            category = classify_category(data.title, data.source_text)

        try:
            risk_level = RiskLevel(review.risk_level)
            risk_reasoning = review.risk_reasoning
        except ValueError:
            risk_level, risk_reasoning = classify_risk(
                data.title, data.source_text, category,
            )

        # 커뮤니티 입력 리스크 강제 적용
        is_community = data.source_type == "community_input"
        community_warning = None
        if is_community:
            logger.info("커뮤니티 입력 감지 — 리스크 재평가 적용")
            risk_level, risk_reasoning = classify_community_risk(
                data.title, data.source_text, category, risk_level, risk_reasoning,
            )
            community_warning = build_community_warning(
                data.title, data.source_text, category, risk_level,
            )

        # 중복 체크
        if self.draft_service.is_duplicate_text(review.body):
            logger.warning("중복 텍스트 감지!")

        # Resonance 구조(⚠️/📌) 최후 방어선 — 프롬프트 실패 시에만 동작.
        # YouTube 95% 보존형 장문 lane 은 ⚠️/📌 emoji header 가 부적합
        # (영상 결론 명제로 자연 종결 목표) → 검사 자체를 우회.
        # 우회 안 하면 placeholder 가 삽입되고 send-guard 가 카드 차단해서
        # 사용자가 승인 카드 / Grok 편집 버튼을 못 받게 됨.
        _resonance_fallback_used = False
        if data.source_type != "youtube":
            try:
                from app.services.text_cleaner import ensure_resonance_structure
                _lang = (data.language or settings.default_language or "ko")
                review.body, _res_status = ensure_resonance_structure(
                    review.body, language=_lang,
                )
                if _res_status == "injected":
                    _resonance_fallback_used = True
                    logger.warning(
                        f"[Resonance-fallback] ⚠️/📌 구조 누락 — placeholder 삽입. "
                        f"프롬프트 확인 필요. title='{data.title[:40]}' "
                        f"status={_res_status} fallback_used=True"
                    )
                elif _res_status == "partial":
                    logger.warning(
                        f"[Resonance-fallback] ⚠️/📌 중 한 개만 존재 — 원본 유지. "
                        f"title='{data.title[:40]}' status={_res_status}"
                    )
            except Exception as e:
                logger.warning(f"[Resonance-fallback] 체크 실패 (무시): {e}")

        # 초안 저장
        draft = self.draft_service.create_draft(
            source_item=source_item,
            hook=review.hook,
            body=review.body,
            category=category,
            risk_level=risk_level,
            risk_reasoning=risk_reasoning,
            ai_rationale=review.ai_rationale,
            thread_continuation=review.thread_continuation,
            resonance_fallback_used=_resonance_fallback_used,
        )

        # quality 결과 캐시 — verdict 별 처리:
        #   REJECT             → send_for_approval 차단 (안전 위반)
        #   BLOCK_RECOMMENDED  → 카드 전송 + 경고 메시지
        #   WARN               → 카드 전송 + 가벼운 경고
        #   PASS               → 캐시 안 함
        try:
            _q = pack_chain_data.get("quality_guard") if pack_chain_data else None
            if _q:
                _v = _q.get("verdict") or ""
                if _v in ("REJECT", "BLOCK_RECOMMENDED", "WARN"):
                    _mark_block_recommended(draft.id, _q)
                    if _v == "REJECT":
                        logger.warning(
                            f"[block-guard] draft_id={draft.id} REJECT — "
                            f"안전 위반 (승인 카드 차단 예정)"
                        )
                    else:
                        logger.info(
                            f"[block-guard] draft_id={draft.id} {_v} — "
                            f"카드 전송 + 경고 배지"
                        )
        except Exception as _bg_e:
            logger.debug(f"[block-guard] mark 실패 (무시): {_bg_e}")

        # 커뮤니티 경고 저장
        if community_warning:
            draft.community_warning = community_warning
            self.db.commit()
            logger.info(f"커뮤니티 경고 저장: draft_id={draft.id}")

        # Phase 5: 비즈니스 분류 (Layer 2 — 실패해도 파이프라인 영향 없음)
        try:
            from app.services.business_classifier import (
                classify_business, business_tags_to_json,
            )
            import json as _json

            # topic_tags 파싱
            _topic_tags = None
            if draft.topic_tags:
                try:
                    _topic_tags = _json.loads(draft.topic_tags)
                except Exception:
                    pass

            biz = classify_business(
                title=data.title,
                body=review.body,
                category=category.value,
                risk_level=risk_level.value,
                topic_tags=_topic_tags,
            )
            draft.business_tags = business_tags_to_json(biz.business_tags)
            draft.cta_type = biz.cta_type
            draft.monetization_score = biz.monetization_score
            draft.asset_goal = biz.asset_goal
            draft.premium_reason = biz.premium_reason
            draft.b2b_candidate = biz.b2b_candidate
            draft.b2b_target_audience = biz.b2b_target_audience
            draft.b2b_use_case = biz.b2b_use_case
            # Phase 3: 프리미엄 후보 자동 초기화
            if "premium_candidate" in biz.business_tags:
                draft.premium_status = "new"
                draft.premium_updated_at = datetime.now(timezone.utc)
            # Phase 5-B2B: B2B 후보 자동 초기화
            if biz.b2b_candidate and not draft.b2b_status:
                draft.b2b_status = "new"
                draft.b2b_updated_at = datetime.now(timezone.utc)
            # Phase 7: 이메일 버킷/목표 자동 초기화 (수동 설정 보호)
            if not draft.email_bucket:
                _cta = biz.cta_type
                _asset = biz.asset_goal
                if _cta in ("premium_waitlist", "premium_teaser") or _asset == "premium_teaser":
                    draft.email_bucket = "premium_teaser"
                elif biz.b2b_candidate:
                    draft.email_bucket = "b2b_nurture"
                elif _cta == "lead_magnet" or _asset == "lead_magnet_push":
                    draft.email_bucket = "lead_nurture"
                elif _cta == "newsletter_signup" or _asset == "newsletter_push":
                    draft.email_bucket = "weekly_free"
            if not draft.email_goal:
                _cta = biz.cta_type
                _asset = biz.asset_goal
                if _cta in ("premium_waitlist", "premium_teaser") or _asset == "premium_teaser":
                    draft.email_goal = "tease"
                elif _cta == "lead_magnet" or _asset == "lead_magnet_push":
                    draft.email_goal = "nurture"
                elif _cta == "newsletter_signup" or _asset == "newsletter_push":
                    draft.email_goal = "signup"
                elif biz.b2b_candidate:
                    draft.email_goal = "nurture"
            self.db.commit()
            logger.info(
                f"[BusinessClassifier] draft_id={draft.id} "
                f"tags={biz.business_tags} cta={biz.cta_type} "
                f"score={biz.monetization_score} asset={biz.asset_goal} "
                f"b2b={biz.b2b_candidate}"
            )
        except Exception as e:
            logger.warning(f"[BusinessClassifier] 분류 실패 (무시): {e}")

        # 예측 게시 시간 계산
        try:
            pred_time, pred_reason = predict_publish_time(
                category=draft.category,
                risk_level=draft.risk_level,
                now=datetime.now(timezone.utc),
            )
            draft.predicted_publish_at = pred_time
            draft.prediction_reasoning = pred_reason
            self.db.commit()
            logger.info(f"예측 게시 시간: {pred_time.isoformat()} — {pred_reason}")
        except Exception as e:
            logger.warning(f"예측 게시 시간 계산 실패 (무시): {e}")

        # PR 35: Resonance Score (경로 A)
        try:
            from app.services.content_pack import compute_resonance_score
            _body = (draft.hook or "") + "\n\n" + (draft.body or "")
            _res = compute_resonance_score(_body)
            logger.info(
                f"[ResonanceScore] total={_res['total']} "
                f"breakdown={_res.get('breakdown',{})}"
            )
        except Exception as e:
            logger.warning(f"[ResonanceScore] 계산 실패 (무시): {e}")

        # Pack sidecar 저장 (pack chain 활성 시만, draft.id 확보 이후)
        if pack_chain_data:
            try:
                # Layer 2: Post Linter 를 먼저 계산 (handoff 에 신호로 넣기 위함).
                try:
                    from app.services.post_linter import run_post_linter
                    _labels = run_post_linter(
                        hook=review.hook,
                        body=review.body,
                        pack=pack_chain_data,
                        category=category.value if category else None,
                        title=data.title,
                    )
                except Exception as _lint_e:
                    logger.warning(f"[post_linter] 실패 (무시): {_lint_e}")
                    _labels = {}
                # Layer 2: Strategy OS 도 편집 신호로 전달 (load 는 fail-open).
                try:
                    from app.services.strategy_os import load_strategy_os
                    _so_for_handoff = load_strategy_os()
                except Exception as _so_e:
                    logger.warning(f"[strategy_os] handoff 전달용 로드 실패 (무시): {_so_e}")
                    _so_for_handoff = None
                # Phase 4: editorial_meta (RT 동기 / 숨은 변수 / 살릴 가치) 계산.
                try:
                    from app.services.editorial_meta import build_editorial_meta
                    _meta = build_editorial_meta(
                        hook=review.hook,
                        body=review.body,
                        source_pack=pack_chain_data["source_pack"],
                        angle_pack=pack_chain_data["angle_pack"],
                        linter_labels=_labels,
                        strategy_os=_so_for_handoff,
                        category=category.value if category else None,
                    )
                except Exception as _em_e:
                    logger.warning(f"[editorial_meta] 실패 (무시): {_em_e}")
                    _meta = {}
                # --- Phase A: critic 결과 merge (신규 슬롯만, setdefault 로 기존 키 보호) ---
                try:
                    if isinstance(_meta, dict) and _critic_meta:
                        for _ck, _cv in _critic_meta.items():
                            _meta.setdefault(_ck, _cv)
                except Exception as _cm_e:
                    logger.warning(f"[critic_meta] merge 실패 (무시): {_cm_e}")
                # --- end Phase A merge ---
                # --- Step 5.7: thread/hook 결과 merge (setdefault — 기존 키 보호) ---
                try:
                    if isinstance(_meta, dict) and _step57_meta:
                        for _sk, _sv in _step57_meta.items():
                            _meta.setdefault(_sk, _sv)
                except Exception as _s7m_e:
                    logger.warning(f"[step57_meta] merge 실패 (무시): {_s7m_e}")
                # --- end Step 5.7 merge ---
                # --- Step 5.8/5.9 + archetype editorial_meta merge (setdefault) ---
                try:
                    if isinstance(_meta, dict) and editorial_meta:
                        for _ek, _ev in editorial_meta.items():
                            _meta.setdefault(_ek, _ev)
                except Exception as _em_e:
                    logger.warning(f"[editorial_meta] merge 실패 (무시): {_em_e}")
                # --- end editorial_meta merge ---
                _handoff_text = format_handoff(
                    pack_chain_data["source_pack"],
                    pack_chain_data["angle_pack"],
                    review.body,
                    final_hook=review.hook,
                    strategy_os=_so_for_handoff,
                    linter_labels=_labels,
                    editorial_meta=_meta,
                    source_type=data.source_type,
                )
                save_pack(draft.id, {
                    "source":         pack_chain_data["source_pack"],
                    "angle":          pack_chain_data["angle_pack"],
                    "final_body":     review.body,
                    "handoff":        _handoff_text,
                    "labels":         _labels,
                    "editorial_meta": _meta,
                })
            except Exception as _sv_e:
                logger.warning(f"[pack_sidecar] save 실패 (무시): {_sv_e}")

        logger.info(
            f"=== 파이프라인 완료: draft_id={draft.id}, "
            f"category={category.value}, risk={risk_level.value} ==="
        )
        return draft

    async def send_for_approval(
        self, draft_id: int, chat_id: int | str | None = None,
        skip_telegram_limit: bool = False,
    ) -> bool:
        """초안을 텔레그램으로 보내서 승인을 요청합니다."""
        # 일일 텔레그램 전송 제한 확인 (수동 입력 시 skip 가능)
        if not skip_telegram_limit:
            can_send, send_msg = self.rate_limiter.can_send_telegram()
            if not can_send:
                logger.warning(f"텔레그램 전송 제한: {send_msg}")
                return False

        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            logger.error(f"초안 없음: draft_id={draft_id}")
            return False

        # Resonance fallback placeholder 초안은 텔레그램 전송 차단
        # (metadata flag + 문자열 매칭 병행 — 문구 변형 우회 방지)
        from app.services.draft_service import is_resonance_fallback_signal
        if is_resonance_fallback_signal(draft):
            logger.warning(
                f"[send-guard] Resonance fallback 초안 텔레그램 전송 차단: "
                f"draft_id={draft_id} "
                f"meta_flag={bool(getattr(draft, 'resonance_fallback_used', False))}"
            )
            return False

        # 재료 품질 게이트 — verdict 기반 분기:
        #   REJECT             → 카드 차단 + 운영자 경고 (안전 위반)
        #   BLOCK_RECOMMENDED  → 카드 전송 + 경고 메시지 추가 (운영자 판단)
        #   WARN               → 카드 전송 + 가벼운 경고
        #   PASS / 캐시 없음   → 정상 전송
        _quality = _get_block_recommended(draft_id)
        _verdict_str = (_quality or {}).get("verdict") or ""
        if _quality and _verdict_str == "REJECT":
            block_reason = (
                _quality.get("block_reason")
                or " / ".join((_quality.get("reasons") or [])[:3])
                or "안전 룰 위반"
            )
            logger.warning(
                f"[send-guard] REJECT — draft_id={draft_id} → 승인 카드 차단: "
                f"{block_reason}"
            )
            await _send_admin_warning(
                chat_id,
                (
                    f"⛔ <b>draft #{draft_id} 전송 차단</b>\n"
                    f"사유: {block_reason}\n\n"
                    f"강제 진행: <code>/force_{draft_id}</code>"
                ),
            )
            return False

        source_url = draft.source_item.url if draft.source_item else None
        message_id = await send_approval_card(draft, source_url, chat_id=chat_id)

        if message_id:
            self.draft_service.set_telegram_message_id(draft_id, message_id)
            # 카드 전송 후 BLOCK_RECOMMENDED / WARN 인 경우 경고 배지 추가 송출
            if _verdict_str in ("BLOCK_RECOMMENDED", "WARN"):
                try:
                    icon = "⚠️" if _verdict_str == "BLOCK_RECOMMENDED" else "💡"
                    score = (_quality or {}).get("score", 0)
                    issues = (_quality or {}).get("reasons", []) + (_quality or {}).get("warnings", [])
                    issue_text = "\n".join(f"  · {i}" for i in issues[:5]) or "  · 세부 사항 없음"
                    await _send_admin_warning(
                        chat_id,
                        (
                            f"{icon} <b>품질 경고</b> (draft #{draft_id} | {score}점)\n"
                            f"운영자 판단으로 발행 결정.\n\n"
                            f"문제:\n{issue_text}"
                        ),
                    )
                except Exception as _we:
                    logger.debug(f"[send-guard] warn 메시지 실패 (무시): {_we}")
            return True
        elif not settings.has_telegram_config:
            logger.info(f"[Mock 텔레그램] 카드 전송됨 (Mock): draft_id={draft_id}")
            return True
        else:
            logger.error(f"텔레그램 전송 실패: draft_id={draft_id}")
            return False

    async def handle_approval(
        self, draft_id: int, action: str,
        chat_id: int | str | None = None,
    ) -> dict:
        """텔레그램 승인/거절 액션을 처리합니다."""
        logger.info(f"승인 처리: draft_id={draft_id}, action={action}")

        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            return {"success": False, "error": f"초안 없음: {draft_id}"}

        if action == "approve":
            return await self._handle_approve(draft)
        elif action == "reject":
            self.draft_service.update_status(draft_id, ApprovalStatus.REJECTED)
            return {"success": True, "message": "거절됨"}
        elif action == "defer":
            self.draft_service.update_status(draft_id, ApprovalStatus.DEFERRED)
            return {"success": True, "message": "보류됨"}
        elif action == "regenerate":
            self.draft_service.update_status(draft_id, ApprovalStatus.REGENERATE)
            return await self._handle_regenerate(draft, chat_id=chat_id)
        else:
            return {"success": False, "error": f"알 수 없는 액션: {action}"}

    async def _handle_approve(self, draft: Draft) -> dict:
        """승인 처리 (X 자동 게시 없음 — 수동 게시 전용)"""
        from app.services.draft_service import (
            is_broken_draft, broken_reason, is_resonance_fallback_signal,
        )
        # Resonance fallback placeholder 는 승인 절대 금지 — 재생성 유도
        # (metadata flag + 문자열 매칭 병행 — 문구 변형 우회 방지)
        if is_resonance_fallback_signal(draft):
            self.draft_service.update_status(draft.id, ApprovalStatus.FAILED)
            logger.warning(
                f"[approve-guard] Resonance fallback 차단: draft_id={draft.id} "
                f"meta_flag={bool(getattr(draft, 'resonance_fallback_used', False))}"
            )
            return {
                "success": False,
                "error": (
                    "이 초안은 구조 누락 fallback 상태라 재생성 후 승인해야 합니다. "
                    "🔄 재생성 버튼을 눌러 ⚠️/📌 구조가 포함된 본문을 새로 받아주세요."
                ),
            }
        if is_broken_draft(draft.body):
            reason = broken_reason(draft.body)
            self.draft_service.update_status(draft.id, ApprovalStatus.FAILED)
            logger.warning(f"[approve-guard] 깨진 초안 차단: draft_id={draft.id}, reason={reason}")
            return {"success": False, "error": f"이 초안은 전송할 수 없습니다: {reason}"}

        self.draft_service.update_status(draft.id, ApprovalStatus.APPROVED)

        try:
            from app.services.text_cleaner import sanitize_internal_tags
            hook, body = sanitize_internal_tags(
                draft.hook or "", draft.body or "",
            )
        except Exception:
            hook, body = draft.hook or "", draft.body or ""

        if not body:
            return {
                "success": True,
                "message": "승인 완료 — 단, 이 초안은 본문이 없습니다. 🔄 재생성을 눌러 AI 본문을 생성하세요.",
                "draft_id": draft.id, "hook": hook, "body": "",
            }

        # Grok mini-pass (fail-open)
        grok_result = {}
        try:
            if settings.has_grok:
                grok_result = await self.ai.trend_hunter.quick_review(
                    hook, body, draft.category.value if draft.category else "")
                if grok_result.get("grok_used") and grok_result.get("verdict") == "use_grok_hook":
                    alt = grok_result.get("hook_alt")
                    if alt and len(alt) <= 80:
                        logger.info(f"[Grok] hook 교체: '{hook[:30]}' → '{alt[:30]}'")
                        hook = alt
        except Exception as e:
            logger.warning(f"[Grok mini-pass] 실패 (무시): {e}")

        result = {
            "success": True,
            "message": "승인 완료 — 아래 내용을 복사해서 직접 게시하세요.",
            "draft_id": draft.id, "hook": hook, "body": body,
        }
        if grok_result.get("grok_used"):
            result["grok_x_angle"] = grok_result.get("x_angle")
            result["grok_resonance_note"] = grok_result.get("resonance_note")
        return result

    async def _handle_regenerate(
        self, draft: Draft, chat_id: int | str | None = None,
    ) -> dict:
        """재생성 → 같은 소스로 다시 파이프라인 실행"""
        source = draft.source_item
        if not source:
            return {"success": False, "error": "원본 소스 없음"}

        try:
            new_data = SourceItemCreate(
                title=source.title, url=source.url,
                source_text=source.source_text,
                source_type=source.source_type, language=source.language,
            )
            new_draft = await self.ingest_and_generate(new_data)
            await self.send_for_approval(new_draft.id, chat_id=chat_id)
            return {
                "success": True,
                "message": f"재생성 완료! 새 draft ID: {new_draft.id}",
                "new_draft_id": new_draft.id,
            }
        except Exception as e:
            logger.error(f"재생성 실패: {e}")
            return {"success": False, "error": str(e)}

    async def retry_failed(self, draft_id: int) -> dict:
        """실패한 게시를 재시도합니다."""
        draft = self.draft_service.get_by_id(draft_id)
        if not draft:
            return {"success": False, "error": f"초안 없음: {draft_id}"}
        if draft.approval_status != ApprovalStatus.FAILED:
            return {"success": False, "error": "실패 상태가 아닌 초안"}

        self.draft_service.update_status(draft_id, ApprovalStatus.APPROVED)
        draft.x_post_id = None
        return await self._handle_approve(draft)

    async def full_pipeline(self, data: SourceItemCreate) -> dict:
        """전체 파이프라인: 소스 입력 → 분류 → AI 생성 → 승인 카드"""
        try:
            draft = await self.ingest_and_generate(data)
            sent = await self.send_for_approval(draft.id)
            if sent:
                message = "초안 생성 완료. 텔레그램에서 승인해주세요."
            else:
                message = "초안 생성 완료."

            return {
                "success": True,
                "draft_id": draft.id,
                "category": draft.category.value,
                "risk_level": draft.risk_level.value,
                "telegram_sent": sent,
                "hook": draft.hook,
                "body": draft.body,
                "message": message,
            }
        except Exception as e:
            logger.error(f"파이프라인 오류: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_trending_topics(self, topic_area: str = "korea") -> dict:
        """TrendHunter를 사용해 현재 트렌딩 토픽을 탐색합니다."""
        logger.info(f"트렌드 탐색: '{topic_area}'")
        try:
            result = await self.ai.trend_hunter.find_trends(topic_area)
            return {
                "success": True,
                "topics": result.trending_topics,
                "notes": result.relevance_notes,
            }
        except Exception as e:
            logger.error(f"트렌드 탐색 실패: {e}")
            return {"success": False, "error": str(e), "topics": []}

    def close(self):
        if self.db:
            self.db.close()
