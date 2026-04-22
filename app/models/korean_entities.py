"""한국 맥락 엔티티 DB.

글로벌 크립토·정책·AI 뉴스를 한국 독자 맥락으로 연결하기 위한
사전 구축 엔티티 테이블 3종.

- KoreanAICompany: 한국 AI/클라우드 7사 (Naver/Kakao/SKT/LG/KT/NCSOFT/Upstage)
- KoreanPolicy: 한국-글로벌 정책 연결맵 (VAUPA/DABA/특금법 등 8개)
- KoreanCryptoExposure: 한국 상장사 크립토 노출 (Dunamu 지분 포함)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.models.content import Base


class KoreanAICompany(Base):
    """한국 AI/클라우드 기업 맵."""

    __tablename__ = "korean_ai_companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(64), nullable=False, unique=True, index=True)  # Naver, Kakao 등
    ticker_kr = Column(String(16), nullable=True)  # 035420 등
    ai_model_name = Column(String(128), nullable=True)  # HyperCLOVA X, Kanana 등
    us_partners = Column(Text, nullable=True)  # AWS, OpenAI, Google 등 쉼표구분
    msit_sovereign_ai_status = Column(String(32), nullable=True)  # finalist / dropped / none
    notes = Column(Text, nullable=True)
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )

    def __repr__(self) -> str:
        return f"<KoreanAICompany {self.group_name} {self.ai_model_name}>"


class KoreanPolicy(Base):
    """한국-글로벌 정책 연결맵."""

    __tablename__ = "korean_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kr_short = Column(String(64), nullable=False, unique=True, index=True)  # VAUPA, DABA
    kr_name = Column(String(256), nullable=False)  # 가상자산이용자보호법
    en_name = Column(String(256), nullable=True)
    kr_regulator = Column(String(32), nullable=True)  # FSC, FIU, BOK, MOEF
    global_peer_name = Column(String(256), nullable=True)  # MiCA, GENIUS Act
    global_regulator = Column(String(32), nullable=True)  # SEC, EU, FinCEN
    status = Column(String(32), nullable=True)  # enacted, proposed, effective
    effective_date = Column(String(16), nullable=True)  # YYYY-MM-DD, 문자열로 단순화
    summary = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<KoreanPolicy {self.kr_short}>"


class KoreanCryptoExposure(Base):
    """한국 상장사 크립토 노출."""

    __tablename__ = "korean_crypto_exposures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    corp_name = Column(String(128), nullable=False, index=True)
    corp_code_dart = Column(String(16), nullable=True)  # DART 고유번호 8자리
    ticker_kr = Column(String(16), nullable=True, index=True)  # KRX 6자리
    exposure_kind = Column(String(64), nullable=True)  # dunamu_shareholder, treasury_btc 등
    crypto_entities = Column(Text, nullable=True)  # Dunamu, Upbit, BTC 등 쉼표구분
    exposure_summary = Column(Text, nullable=True)
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )

    def __repr__(self) -> str:
        return f"<KoreanCryptoExposure {self.corp_name} {self.exposure_kind}>"
