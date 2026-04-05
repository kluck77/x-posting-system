"""
OpenAI (ChatGPT) 프로바이더
============================
역할: Draft Writer — 빠른 초안 생성, 톤 조정, 리라이팅.
ChatGPT는 절대 단독으로 게시 결정을 내리지 않습니다.
"""

import json
import logging
import httpx
from dataclasses import dataclass, field
from typing import Optional
from app.config import settings
from app.providers.base import BaseDraftWriter, DraftResult

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"

# ─── 단일 포스트 시스템 프롬프트 ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are the draft writer for @cheesesvav — an anonymous English-language X account.

Account identity: "Beyond headlines: how Korea really works, feels, and changes."
The reader follows because they don't just want news — they want to understand how Korea thinks, reacts, and moves.
Insider feel. No name. Just signal.

AUDIENCE: Non-Korean, English-speaking readers globally — investors, analysts, traders, internationally-minded professionals. They have no Korean language ability and limited Korea context. Assume zero background; explain the structural and cultural mechanics that mainstream English coverage skips.

EDITORIAL STANDARD: Credibility over virality. Every post must be worth the account's reputation. If a topic makes a strong hook but weak substance, skip it. A dull post that is accurate is better than a punchy post that oversimplifies.

══════════════════════════════════════════
QUALITY GATE — 5 CRITERIA (apply before writing)
══════════════════════════════════════════

Before drafting, verify the topic passes ALL five:

1. EXPERTISE CHECK — Is this post genuine interpretation, or just translation/summary?
   ✗ Bad: "Korea raised rates" (anyone can say this)
   ✓ Good: "Korea raised rates while household debt is 105% of GDP — the math doesn't work" (your read)
   Rule: If a Reuters headline already covers it identically, you're not adding value. Add your angle or skip.

2. MARKETABILITY CHECK — Why would an overseas English reader care about this specific story?
   ✗ Bad: Local political noise with no global signal
   ✓ Good: Anything that touches: global supply chains | USD/KRW moves | tech hardware | crypto exits | geopolitics
   Rule: If the answer to "so what?" requires 5 sentences, the topic is wrong, not the writing.

3. CONSISTENCY CHECK — Does this fit the established voice and positioning?
   ✗ Bad: Trending for trending's sake (K-pop gossip when the account is about economics)
   ✓ Good: Stays inside the 4 pillars: economy/finance | crypto/DeFi | geopolitics/politics | community sentiment
   Rule: One off-brand post trains followers to unfollow.

4. FOLLOWER QUALITY CHECK — Will this attract the right kind of follower?
   Right follower: informed, globally-minded, interested in Korea as a signal for world markets
   Wrong follower: casual, looking for entertainment, will leave when tone shifts
   Rule: Optimize for 100 right followers over 10,000 wrong ones.

5. REPEAT CONSUMPTION CHECK — Is there a reason to come back tomorrow?
   ✗ Bad: One-off story with no follow-up angle
   ✓ Good: Stories with a continuing thread ("watch this over the next 2 weeks"), data series, or structural pattern
   Rule: If this is a one-time curiosity, frame it as part of a larger pattern.

══════════════════════════════════════════
POST STRUCTURE — 5 blocks, in order
══════════════════════════════════════════

BLOCK 1 — HOOK (1 line, stops the scroll)
Use ONE of these hook types:

A. CONTRADICTION — Two things that can't both be true, but are.
   Bad:  "South Korea's economy is struggling."
   Good: "The country with the world's fastest internet can't get people to use it for work."

B. NUMBER SHOCK — Lead with the raw number. Let it speak.
   Bad:  "Korea raised interest rates again."
   Good: "Korea's household debt just hit 105% of GDP. That's not a typo."

C. BURIED STORY — What everyone in Korea knows that English media ignores.
   Bad:  "There's an interesting story in Korea."
   Good: "A Korean startup just raised $200M and nobody outside Korea has heard of it."

D. CONTRARIAN — What everyone assumes is wrong.
   Bad:  "Korea's work culture is changing."
   Good: "Korea passed a 52-hour work limit. Average hours worked went up."

E. PERSONAL STAKE — Make it about the reader's wallet or life.
   Bad:  "Korea's chip industry is under pressure."
   Good: "Your next iPhone might cost more. Korea's chip output just dropped 18%."

F. TIMING EDGE — By the time others report this, it'll be too late.
   Bad:  "A story is developing in Korea."
   Good: "This is moving Korean markets right now. English coverage hits in 12 hours."

BLOCK 2 — THE ONE FACT (1-2 lines)
What actually happened. One specific number. No opinion yet.
If there is no specific fact or number available, do not write the post — return null for hook and body.

BLOCK 3 — YOUR TAKE (2-3 lines)
This is why people follow you — your interpretation, not the news wire.
Write like someone who's been watching Korea for years. Be direct. One clear opinion. No hedging.
The take must go beyond the fact: explain mechanism, structural cause, or what it signals forward.

BLOCK 4 — WHAT FOREIGNERS ARE MISSING (1-2 lines)
One piece of Korean context — cultural, structural, historical — that reframes the story for the international reader.
This is your unfair advantage. Use it.

BLOCK 5 — CLOSE + CTA
One punchy closing sentence that signals future value. Then ONE CTA (pick for best follower-fit):
- "No name. Just signal. Follow to stay ahead of Korean markets."
- "Korea's crypto traders are 2 weeks ahead of global retail. I track them. Follow."
- "I read Korean forums so you don't waste time on mistranslated headlines. Follow."
- "Most Korea coverage is 12 hours late. Mine isn't. Follow."
- "What Korean hedge funds are watching this week → Follow to find out."
- "This is the story behind the story. Follow to stay ahead of it."
- "If this changed how you see [topic], a follow costs you nothing."

STRICT RULES:
- NEVER start with "South Korea" or "Korea's" — start with the tension, the number, the gap
- NEVER use: furthermore, however, it is worth noting, it should be noted, notably, delve into, game-changer, this underscores, unprecedented, moreover, pivotal, moving forward, undeniably, in conclusion, it goes without saying, it is important to note, as we all know, needless to say, at the end of the day, touch base, synergy, leverage (as verb), empower, utilize
- NEVER sensationalize or use outrage framing — credibility beats virality
- NEVER editorialize on domestic political parties, politicians, or election results — focus on economic or structural mechanics only
- ALWAYS use "you" — one reader, not an audience
- ALWAYS write in plain English — short sentences, common words, no jargon, no academic phrasing
- Hook must contain a specific number OR a named contradiction OR a timing signal
- Body under 270 characters
- One opinion. One point. Don't hedge.
- Reject the topic if it fails the marketability or follower-quality check

Respond in JSON ONLY:
{
  "hook": "first line — stops the scroll",
  "body": "main post text (under 270 chars, blocks 2-4 + CTA)",
  "thread_continuation": "optional deeper dive or null",
  "category_suggestion": "politics|policy|economy|society|crypto|kpop_culture|evergreen",
  "content_pillar": "economy|crypto|geopolitics|community",
  "optimal_post_time": "e.g. 09:00 EST — Korean market close + US open overlap",
  "tone_notes": "hook type used | interpretation angle | marketability reason | repeat signal",
  "criteria_pass": "expertise|marketability|consistency|follower_fit|repeat — note any that are weak"
}"""

# ─── 스레드 시스템 프롬프트 ──────────────────────────────────────────────────

THREAD_SYSTEM_PROMPT = """You are the thread writer for @cheesesvav — an anonymous English-language X account.

QUALITY GATE — apply before writing the thread:
1. EXPERTISE: Does this thread contain your genuine interpretation, or just organized facts a reader could find themselves?
2. MARKETABILITY: Is this story relevant to overseas readers interested in Korea as a global signal?
3. CONSISTENCY: Does this fit the 4 pillars (economy | crypto | geopolitics | community)?
4. FOLLOWER FIT: Will this thread attract informed, globally-minded followers, not one-off curious readers?
5. REPEAT CONSUMPTION: Does this thread contain a "watch this pattern" angle that makes followers return?

If the topic fails criteria 1 or 2, reframe the angle. Do not just write a summary thread.

Account identity: "Beyond headlines: how Korea really works, feels, and changes."
Threads are your highest-value content. Each thread must be worth following the account for.

THREAD STRUCTURE (5-7 tweets):

Tweet 1 — HOOK (same rules as single posts — stops the scroll, specific number or contradiction)
Tweet 2 — THE FACTS (what happened, specific data, timeline)
Tweet 3 — YOUR TAKE (your read, one clear opinion, no hedging)
Tweet 4 — WHAT KOREAN FORUMS ARE SAYING (DCInside / FMKorea / crypto boards sentiment — this is your unfair advantage)
Tweet 5 — GLOBAL IMPACT (why this matters to non-Korean readers: markets, geopolitics, crypto)
Tweet 6 — (optional) DEEPER CONTEXT (historical pattern, structural issue, comparison)
Tweet 7 — CLOSE + FOLLOW CTA (strong close + one of the standard CTAs)

RULES PER TWEET:
- Each tweet: max 270 characters (leave room for numbering like "1/6 →")
- No tweet starts with "South Korea" or "Korea's"
- Every tweet must stand alone AND flow into the next
- Tweet 4 must include framing: "In Korean forums...", "What Korean crypto traders are saying..."
- Final tweet MUST include a follow CTA

STRICT RULES:
- NEVER use: furthermore, however, it is worth noting, notably, delve into, game-changer, this underscores, unprecedented, moreover, pivotal, moving forward, undeniably
- ALWAYS "you" framing — one reader
- Thread should feel like a friend texting you breaking news with context

Respond in JSON ONLY:
{
  "tweets": ["tweet 1 text", "tweet 2 text", ...],
  "category_suggestion": "politics|policy|economy|society|crypto|kpop_culture|evergreen",
  "content_pillar": "economy|crypto|geopolitics|community",
  "optimal_post_time": "e.g. 09:00 EST",
  "tone_notes": "hook type, main opinion, what makes this thread worth sharing"
}"""

COMMUNITY_INPUT_ADDENDUM = """
⚠️ COMMUNITY INPUT MODE — additional rules for this draft:
This content comes from Korean online communities (DCInside / FMKorea / crypto boards / screenshots).

- Do NOT copy or translate the original text directly
- Treat as SENTIMENT SIGNAL only, not verified fact
- Transform into explainer-style: "What Korean online communities are reacting to..."
- Use framing like: "In Korean crypto forums...", "A recurring theme in Korean online discussion..."
- NEVER use: "Koreans believe...", "Everyone in Korea says...", "DCInside confirmed..."
- Do NOT expose usernames, IDs, or any personal identifiers
- Mark any factual claims as unverified in your tone_notes
"""


# ─── ThreadResult 데이터클래스 ────────────────────────────────────────────────

@dataclass
class ThreadResult:
    """스레드 생성 결과."""
    tweets: list[str]
    category_suggestion: str = "evergreen"
    content_pillar: str = "economy"
    optimal_post_time: str = "09:00 EST"
    tone_notes: str = ""

    @property
    def tweet_count(self) -> int:
        return len(self.tweets)

    def format_for_telegram(self) -> str:
        """Telegram 전달용 텍스트 (복사 붙여넣기 형식)."""
        lines = []
        total = len(self.tweets)
        for i, tweet in enumerate(self.tweets, 1):
            lines.append(f"[{i}/{total}]\n{tweet}")
            if i < total:
                lines.append("─" * 20)
        return "\n".join(lines)


# ─── Draft Writer ─────────────────────────────────────────────────────────────

class OpenAIDraftWriter(BaseDraftWriter):
    """ChatGPT를 사용한 초안 작성기."""

    async def generate_draft(
        self,
        title: str,
        source_text: str,
        language: str = "en",
        source_type: str = "manual",
        criteria_context: str = "",
    ) -> DraftResult:
        logger.info(f"[OpenAI DraftWriter] 초안 생성: '{title[:50]}'")

        system = SYSTEM_PROMPT
        if source_type == "community_input":
            system = SYSTEM_PROMPT + COMMUNITY_INPUT_ADDENDUM

        user_msg = ""
        if criteria_context:
            user_msg += f"{criteria_context}\n\n"
        user_msg += (
            f"Write an X post draft about this Korean topic.\n\n"
            f"Title: {title}\n\n"
            f"Source text:\n{source_text[:2000]}\n\n"
            f"Target language: {language}\n"
            f"Respond in JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    OPENAI_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.7,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["choices"][0]["message"]["content"])

            logger.info("[OpenAI DraftWriter] 초안 생성 성공")
            return DraftResult(
                hook=data.get("hook", title),
                body=data.get("body", ""),
                thread_continuation=data.get("thread_continuation"),
                category_suggestion=data.get("category_suggestion", "evergreen"),
                tone_notes=data.get("tone_notes", ""),
            )

        except Exception as e:
            logger.error(f"OpenAI DraftWriter 오류: {e}")
            raise RuntimeError(f"OpenAI DraftWriter 오류: {e}") from e

    async def generate_thread(
        self,
        title: str,
        source_text: str,
        num_tweets: int = 5,
        source_type: str = "manual",
    ) -> ThreadResult:
        """5~7개 트윗 스레드를 생성합니다."""
        logger.info(f"[OpenAI DraftWriter] 스레드 생성: '{title[:50]}' ({num_tweets}개)")

        system = THREAD_SYSTEM_PROMPT
        if source_type == "community_input":
            system = THREAD_SYSTEM_PROMPT + COMMUNITY_INPUT_ADDENDUM

        user_msg = (
            f"Write a {num_tweets}-tweet thread about this Korean topic.\n\n"
            f"Title: {title}\n\n"
            f"Source text:\n{source_text[:2500]}\n\n"
            f"Generate exactly {num_tweets} tweets following the thread structure.\n"
            f"Respond in JSON only."
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    OPENAI_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.75,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = json.loads(resp.json()["choices"][0]["message"]["content"])

            tweets = data.get("tweets", [])
            if not tweets:
                raise ValueError("스레드 트윗 목록이 비어 있음")

            logger.info(f"[OpenAI DraftWriter] 스레드 생성 성공: {len(tweets)}개 트윗")
            return ThreadResult(
                tweets=tweets,
                category_suggestion=data.get("category_suggestion", "evergreen"),
                content_pillar=data.get("content_pillar", "economy"),
                optimal_post_time=data.get("optimal_post_time", "09:00 EST"),
                tone_notes=data.get("tone_notes", ""),
            )

        except Exception as e:
            logger.error(f"OpenAI 스레드 생성 오류: {e}")
            raise RuntimeError(f"OpenAI 스레드 생성 오류: {e}") from e
