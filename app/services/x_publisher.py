"""
X(트위터) 게시 서비스
=====================
승인된 콘텐츠를 X API를 통해 게시합니다.

X API v2를 사용하며, OAuth 1.0a 인증이 필요합니다.
포스팅에 필요한 인증정보:
- X_API_KEY (Consumer Key)
- X_API_SECRET (Consumer Secret)
- X_ACCESS_TOKEN (사용자 Access Token)
- X_ACCESS_TOKEN_SECRET (사용자 Access Token Secret)
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from requests_oauthlib import OAuth1
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.models.content import Draft, PostLog, ApprovalStatus

logger = logging.getLogger(__name__)

# X API v2 트윗 작성 엔드포인트
X_API_CREATE_TWEET = "https://api.x.com/2/tweets"


@dataclass
class PublishResult:
    """게시 결과를 담는 데이터 클래스"""
    success: bool
    post_id: str | None = None
    post_url: str | None = None
    error_message: str | None = None


class XPublisher:
    """X 게시 서비스"""

    def __init__(self, db: Session):
        self.db = db
        self._mock_mode = not settings.has_x_credentials

        if self._mock_mode:
            logger.info("X Publisher: Mock 모드로 실행됩니다 (X API 키 없음)")
        else:
            logger.info("X Publisher: 실제 X API 모드로 실행됩니다")

    def _get_oauth(self) -> OAuth1:
        """OAuth 1.0a 인증 객체를 생성합니다."""
        return OAuth1(
            client_key=settings.x_api_key,
            client_secret=settings.x_api_secret,
            resource_owner_key=settings.x_access_token,
            resource_owner_secret=settings.x_access_token_secret,
        )

    def _log_attempt(
        self,
        draft_id: int,
        action: str,
        success: bool,
        x_post_id: str | None = None,
        error_message: str | None = None,
        request_payload: str | None = None,
        response_payload: str | None = None,
    ) -> None:
        """게시 시도를 로그에 기록합니다."""
        log_entry = PostLog(
            draft_id=draft_id,
            action=action,
            success=success,
            x_post_id=x_post_id,
            error_message=error_message,
            request_payload=request_payload,
            response_payload=response_payload,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(log_entry)
        self.db.commit()

    async def publish(self, draft: Draft) -> PublishResult:
        """
        초안을 X에 게시합니다.

        안전 규칙:
        1. 승인 상태가 APPROVED인 경우에만 게시
        2. 이미 게시된 경우 중복 방지
        3. 실패 시 에러 기록

        Args:
            draft: 게시할 초안

        Returns:
            PublishResult 객체
        """
        # 안전 체크: 승인된 것만 게시
        if draft.approval_status != ApprovalStatus.APPROVED:
            error = f"승인되지 않은 초안입니다 (현재 상태: {draft.approval_status.value})"
            logger.error(error)
            return PublishResult(success=False, error_message=error)

        # 중복 게시 방지
        if draft.x_post_id:
            error = f"이미 게시된 초안입니다 (x_post_id: {draft.x_post_id})"
            logger.warning(error)
            return PublishResult(success=False, error_message=error)

        # 게시할 텍스트 준비
        post_text = draft.full_text

        # 글자 수 체크 (X는 최대 280자, 하지만 Premium은 더 많을 수 있음)
        if len(post_text) > 280:
            logger.warning(f"포스트가 280자를 초과합니다 ({len(post_text)}자). 게시를 시도합니다.")

        # Mock 모드인 경우
        if self._mock_mode:
            return await self._mock_publish(draft, post_text)

        # 실제 X API 호출
        return await self._real_publish(draft, post_text)

    async def _mock_publish(self, draft: Draft, post_text: str) -> PublishResult:
        """Mock 모드에서의 게시 (실제 API 호출 없음)"""
        import random
        mock_id = f"mock_{random.randint(1000000000, 9999999999)}"
        mock_url = f"https://x.com/user/status/{mock_id}"

        logger.info(
            f"[MOCK X 게시] draft_id={draft.id}\n"
            f"텍스트: {post_text[:100]}...\n"
            f"Mock ID: {mock_id}"
        )

        self._log_attempt(
            draft_id=draft.id,
            action="mock_publish",
            success=True,
            x_post_id=mock_id,
            request_payload=json.dumps({"text": post_text[:200]}),
            response_payload=json.dumps({"mock": True, "id": mock_id}),
        )

        return PublishResult(
            success=True,
            post_id=mock_id,
            post_url=mock_url,
        )

    async def _real_publish(self, draft: Draft, post_text: str) -> PublishResult:
        """실제 X API를 호출하여 게시합니다."""
        payload = {"text": post_text}
        request_json = json.dumps(payload)

        try:
            # OAuth 1.0a 인증으로 X API 호출
            # httpx는 requests_oauthlib의 OAuth1을 직접 지원하지 않으므로
            # requests 라이브러리를 사용합니다
            import requests

            auth = self._get_oauth()
            response = requests.post(
                X_API_CREATE_TWEET,
                json=payload,
                auth=auth,
                timeout=30,
            )

            response_text = response.text
            logger.info(f"X API 응답 코드: {response.status_code}")

            if response.status_code in (200, 201):
                result = response.json()
                post_id = result.get("data", {}).get("id", "")
                post_url = f"https://x.com/i/status/{post_id}" if post_id else ""

                self._log_attempt(
                    draft_id=draft.id,
                    action="publish",
                    success=True,
                    x_post_id=post_id,
                    request_payload=request_json,
                    response_payload=response_text,
                )

                logger.info(f"X 게시 성공: draft_id={draft.id}, post_id={post_id}")
                return PublishResult(
                    success=True,
                    post_id=post_id,
                    post_url=post_url,
                )
            else:
                error_msg = f"X API 오류 ({response.status_code}): {response_text[:500]}"
                self._log_attempt(
                    draft_id=draft.id,
                    action="publish",
                    success=False,
                    error_message=error_msg,
                    request_payload=request_json,
                    response_payload=response_text,
                )

                logger.error(f"X 게시 실패: {error_msg}")
                return PublishResult(success=False, error_message=error_msg)

        except requests.RequestException as e:
            error_msg = f"X API 요청 오류: {str(e)}"
            self._log_attempt(
                draft_id=draft.id,
                action="publish",
                success=False,
                error_message=error_msg,
                request_payload=request_json,
            )
            logger.error(error_msg)
            return PublishResult(success=False, error_message=error_msg)

        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            self._log_attempt(
                draft_id=draft.id,
                action="publish",
                success=False,
                error_message=error_msg,
            )
            logger.error(error_msg)
            return PublishResult(success=False, error_message=error_msg)
