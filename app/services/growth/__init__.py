"""
계정 성장 자동화 파이프라인
============================
@sskorea02 (Gate.io 선물봇 계정) 팔로워 증가를 위한 4개 파이프라인.

Pipeline 1: post_queue     — 최적 시간 승인 알림 큐 (자동 게시 없음)
Pipeline 2: comment_hunter — 댓글 달기 좋은 게시물 탐지
Pipeline 3: reply_monitor  — 내 게시물 답글 모니터 + 자동 초안
Pipeline 4: weekly_report  — 주간 성과 리포트

알고리즘 근거 (X 오픈소스 코드):
- 답글에 재답글: +75 (좋아요 150배)
- 게시 후 첫 30~60분이 노출의 전부
- 외부 링크 본문 삽입 시 도달률 -30~50%
"""
