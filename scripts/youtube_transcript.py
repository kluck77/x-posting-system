"""YouTube 자막 추출기 — 로컬 PC 전용.

클라우드 서버에서 실행 금지 (YouTube IP rate-limit / 차단).
운영자 PC 에서 실행 → 결과 JSON 을 서버 /control/youtube/highlights 업로드.

사용법:
    python scripts/youtube_transcript.py --days 1
    python scripts/youtube_transcript.py --channel UChlv4GSd7OQl3js-jkLOnFA
    python scripts/youtube_transcript.py --output ./output/yt_highlights.json

의존성 (로컬):
    pip install youtube-transcript-api yt-dlp
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 타겟 채널 (채널 ID는 yt-dlp 또는 UC... prefix 그대로)
TARGET_CHANNELS = {
    "삼프로TV":   "UChlv4GSd7OQl3js-jkLOnFA",
    "슈카월드":   "UCsJ6RuBiTVWRX156FVbeaGg",
    "언더스탠딩": "UC3I8cX64NKxYZ0EAAXMH6Bw",
}

# 매크로·크립토·반도체 하이라이트 키워드
HIGHLIGHT_KW = re.compile(
    r"fed|연준|기준금리|한은|인플레이션|cpi|ppi|고용|실업률"
    r"|비트코인|btc|이더리움|eth|sec|etf|폴리마켓"
    r"|경기침체|recession|달러|원화|환율|금리|채권"
    r"|반도체|엔비디아|삼성|하이닉스|hbm",
    re.IGNORECASE,
)

# 저작권 / 명예훼손 리스크 키워드 (저장 플래그 후 서버에서 is_risky 항목 drop)
COPYRIGHT_RISK_KW = re.compile(r"욕설|명예훼손|허위사실|개인정보")


def get_recent_videos(channel_id: str, days: int = 1) -> list[str]:
    """yt-dlp 로 최근 N일 영상 ID 목록."""
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        cmd = [
            "yt-dlp",
            "--dateafter", since,
            "--flat-playlist",
            "--print", "id",
            "--no-warnings",
            f"https://www.youtube.com/channel/{channel_id}/videos",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except Exception as e:
        logger.warning(f"[YT] 영상 목록 수집 실패 ({channel_id}): {e}")
        return []


def extract_transcript(video_id: str) -> list[dict]:
    """youtube_transcript_api 로 자막 추출 (ko/en)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        ytt = YouTubeTranscriptApi()
        fetched = ytt.fetch(video_id, languages=["ko", "en"])
        return [
            {
                "start":    float(getattr(s, "start", 0.0) or 0.0),
                "duration": float(getattr(s, "duration", 0.0) or 0.0),
                "text":     str(getattr(s, "text", "") or ""),
            }
            for s in fetched
        ]
    except Exception as e:
        logger.warning(f"[YT] {video_id} 자막 실패: {e}")
        return []


def extract_highlights(
    snippets: list[dict],
    video_id: str,
    channel_name: str,
    max_per_video: int = 3,
) -> list[dict]:
    """키워드 매칭 하이라이트 (최대 max_per_video 개)."""
    highlights: list[dict] = []
    for i, snip in enumerate(snippets):
        if not HIGHLIGHT_KW.search(snip["text"]):
            continue
        if len(highlights) >= max_per_video:
            break
        start_idx = max(0, i - 3)
        end_idx = min(len(snippets), i + 4)
        context = snippets[start_idx:end_idx]
        full_text = " ".join(s["text"] for s in context)
        is_risky = bool(COPYRIGHT_RISK_KW.search(full_text))
        duration = sum(float(s["duration"]) for s in context)
        if duration > 30:
            continue
        ts = int(snip["start"])
        h, m, s = ts // 3600, (ts % 3600) // 60, ts % 60
        timestamp = f"{h:02d}:{m:02d}:{s:02d}"
        highlights.append({
            "channel":       channel_name,
            "video_id":      video_id,
            "timestamp":     timestamp,
            "timestamp_sec": ts,
            "text":          full_text[:200],
            "url":           f"https://youtu.be/{video_id}?t={ts}",
            "duration_sec":  duration,
            "is_risky":      is_risky,
            "fetched_at":    time.time(),
        })
    return highlights


def format_markdown(highlights: list[dict]) -> str:
    lines = [
        "# 유튜브 자막 하이라이트",
        f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M')} KST\n",
    ]
    for h in highlights:
        if h["is_risky"]:
            lines.append(f"⚠️ [리스크 플래그] {h['channel']} / {h['timestamp']}")
            continue
        lines.append(f"### [{h['channel']}] {h['timestamp']}")
        lines.append(f'원문: "{h["text"][:100]}..."')
        lines.append(f"출처: {h['channel']} / {h['url']}\n")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",    type=int, default=1)
    parser.add_argument("--channel", type=str, default=None)
    parser.add_argument("--output",  type=str, default="./output/yt_highlights.json")
    args = parser.parse_args()

    channels = TARGET_CHANNELS
    if args.channel:
        name = next(
            (k for k, v in TARGET_CHANNELS.items() if v == args.channel),
            args.channel,
        )
        channels = {name: args.channel}

    all_highlights: list[dict] = []
    for ch_name, ch_id in channels.items():
        logger.info(f"[YT] {ch_name} 수집 중...")
        video_ids = get_recent_videos(ch_id, days=args.days)
        logger.info(f"[YT] {ch_name}: {len(video_ids)}개 영상 (최대 5개 처리)")
        for vid_id in video_ids[:5]:
            snippets = extract_transcript(vid_id)
            if not snippets:
                continue
            all_highlights.extend(
                extract_highlights(snippets, vid_id, ch_name)
            )
            time.sleep(1)  # rate limit

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".md":
        out_path.write_text(format_markdown(all_highlights), encoding="utf-8")
    else:
        out_path.write_text(
            json.dumps(all_highlights, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 마크다운도 함께 저장
        md_path = out_path.with_suffix(".md")
        md_path.write_text(format_markdown(all_highlights), encoding="utf-8")

    logger.info(
        f"[YT] 완료. 하이라이트 {len(all_highlights)}개 → {args.output}"
    )
    logger.info(
        "업로드: curl -X POST http://<server>/control/youtube/highlights "
        f"-F 'file=@{args.output}'"
    )


if __name__ == "__main__":
    main()
