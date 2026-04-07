# 예측 최적 게시 시간 (Prediction Time) 기능 구현 태스크

## 목적
X 포스팅 시스템에 콘텐츠 카테고리·리스크 레벨·현재 UTC 시각을 기반으로
최적 게시 시간을 예측하는 기능을 추가한다.

## 구현 범위

### 1. `app/services/prediction_service.py` (신규 생성)

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.models.content import ContentCategory, RiskLevel

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

# 카테고리별 KST 목표 시간 (hour)
CATEGORY_TARGET_HOUR_KST = {
    ContentCategory.POLITICS:     8,   # 08:00 KST 출근 뉴스
    ContentCategory.POLICY:       8,   # 08:00 KST
    ContentCategory.ECONOMY:      9,   # 09:00 KST 증시 개장 전
    ContentCategory.SOCIETY:     12,   # 12:00 KST 점심
    ContentCategory.KPOP_CULTURE: 19,  # 19:00 KST 저녁 여가
    ContentCategory.EVERGREEN:   10,   # 10:00 KST
}

def predict_publish_time(
    category: ContentCategory,
    risk_level: RiskLevel,
    now: datetime,   # UTC aware
) -> tuple[datetime, str]:
    """
    최적 게시 시간 예측.
    - 카테고리별 KST 목표 시간 선택
    - HIGH 리스크: +1시간 지연
    - 오늘 목표 시각이 이미 지났으면 내일
    - UTC aware datetime 반환
    """
    ...
```

### 2. `app/models/content.py` — Draft 모델에 컬럼 추가
- `predicted_publish_at`: DateTime nullable
- `prediction_reasoning`: Text nullable
- `DraftResponse` Pydantic 스키마에도 동일 필드 추가

### 3. `app/db.py` — `run_schema_migrations()` 구현
- `Base.metadata.create_all()` 은 기존 테이블 컬럼을 추가 안 함
- PRAGMA table_info + ALTER TABLE 패턴으로 안전하게 추가
- `init_db()` 내에서 `create_all()` 다음에 호출

### 4. `app/orchestrator.py` — 초안 저장 후 예측 호출
- `create_draft()` 호출 직후
- `predict_publish_time(draft.category, draft.risk_level, datetime.now(UTC))` 호출
- `draft.predicted_publish_at`, `draft.prediction_reasoning` 저장 후 commit

### 5. `app/services/telegram_service.py` — 승인 카드에 예측 시간 표시
- `build_approval_card()` 함수 내부
- `predicted_publish_at` 있으면 KST로 변환해서 표시

## 기술 스택
- Python 3.9+ (zoneinfo 표준 라이브러리, pytz 불필요)
- KST = UTC+9, DST 없음 (Asia/Seoul)
- SQLite + SQLAlchemy

## 참고 데이터 (X/Twitter 최적 포스팅 시간 연구)
- 정치/경제 뉴스: 평일 UTC 12–16 (미국 동부 피크)
- 영국+미국 교차점: UTC 12:00–13:00
- K-pop: UTC 00–02 (KST 09–11) 또는 UTC 12–14 (KST 21–23)
- 주말: 뉴스 계정은 토·일 참여율 낮음
- 출처: Buffer 870만 트윗, SocialPilot 70만 트윗 분석

## 검증
1. `python scripts/init_db.py` — 마이그레이션 확인
2. `POST /ingest` → 응답에 `predicted_publish_at` 존재 확인
3. 텔레그램 승인 카드에 예측 시간 줄 표시 확인
4. `pytest tests/` — 기존 76개 테스트 통과
5. `tests/test_prediction_service.py` 신규 단위 테스트
