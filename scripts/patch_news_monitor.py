#!/usr/bin/env python3
"""
news_monitor.py 서버 패치 스크립트
==================================
old direct telegram alert 를 비활성화하고,
개별 기사를 full_pipeline 으로 전달하는 코드를 삽입한다.

사용법 (서버에서):
    cd /root/x-posting-system
    cp app/services/news_monitor.py /tmp/news_monitor.py.bak.pipeline
    python3 scripts/patch_news_monitor.py
    python3 -m py_compile app/services/news_monitor.py
    systemctl restart xdashboard
"""

import re
import sys

TARGET = "/root/x-posting-system/app/services/news_monitor.py"

# --- old block (to be replaced) ---
OLD_PATTERN = r"""(            # 교차 확인 클러스터 업데이트
            ready_key = _ingest_article\(article\)

            # 수면 시간이 아닐 때만 알림 전송
            if not sleeping and ready_key:
                cluster = _story_clusters\.get\(ready_key\)
                if cluster and alerts_sent < settings\.monitor_max_alerts_per_run:
                    await _send_news_alert\(cluster\)
                    await asyncio\.sleep\(0\.5\)
                    alerts_sent \+= 1)"""

# --- new block ---
NEW_BLOCK = """            # 교차 확인 클러스터 업데이트 (기존 유지)
            ready_key = _ingest_article(article)

            # [NEW] 개별 기사를 full_pipeline 으로 전달 (BREAKING/CANDIDATE 만)
            try:
                from app.services.breaking_classifier import classify_article
                _br = classify_article(
                    title=article.title,
                    body=article.summary or "",
                    url=article.url,
                )
                if _br.classification in ("BREAKING_NOW", "CANDIDATE"):
                    from app.models.content import SourceItemCreate
                    from app.orchestrator import Orchestrator
                    _payload = SourceItemCreate(
                        title=article.title,
                        source_text=article.summary or article.title,
                        url=article.url,
                        source_type="naver_auto",
                        language="ko",
                    )
                    _orch = Orchestrator()
                    try:
                        _result = await _orch.full_pipeline(_payload)
                        logger.info(
                            f"[Monitor→Pipeline] {article.title[:40]}: "
                            f"{_br.classification}/{_br.topic_domain}"
                        )
                    finally:
                        _orch.close()
            except Exception as _e:
                logger.debug(f"[Monitor→Pipeline] fail-open: {_e}")

            # [DISABLED] old direct telegram alert — full_pipeline 이 대체
            # if not sleeping and ready_key:
            #     cluster = _story_clusters.get(ready_key)
            #     if cluster and alerts_sent < settings.monitor_max_alerts_per_run:
            #         await _send_news_alert(cluster)
            #         await asyncio.sleep(0.5)
            #         alerts_sent += 1"""


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()

    # Simple string match (not regex) for safety
    old_text = (
        "            # 교차 확인 클러스터 업데이트\n"
        "            ready_key = _ingest_article(article)\n"
        "\n"
        "            # 수면 시간이 아닐 때만 알림 전송\n"
        "            if not sleeping and ready_key:\n"
        "                cluster = _story_clusters.get(ready_key)\n"
        "                if cluster and alerts_sent < settings.monitor_max_alerts_per_run:\n"
        "                    await _send_news_alert(cluster)\n"
        "                    await asyncio.sleep(0.5)\n"
        "                    alerts_sent += 1"
    )

    if old_text not in content:
        print("ERROR: 패치 대상 블록을 찾을 수 없음. news_monitor.py 구조가 다름.")
        print("수동 확인 필요.")
        sys.exit(1)

    new_content = content.replace(old_text, NEW_BLOCK, 1)

    if new_content == content:
        print("ERROR: 치환 실패")
        sys.exit(1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"OK: {TARGET} 패치 완료")
    print(f"  - old direct telegram alert 비활성화")
    print(f"  - full_pipeline 연결 삽입 (BREAKING/CANDIDATE only)")
    print(f"  - 롤백: cp /tmp/news_monitor.py.bak.pipeline {TARGET}")


if __name__ == "__main__":
    main()
