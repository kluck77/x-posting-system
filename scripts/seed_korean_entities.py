"""한국 맥락 엔티티 시드 데이터 적재 스크립트.

사용법: python -m scripts.seed_korean_entities

멱등성 보장: kr_short / group_name / corp_name UNIQUE 제약 활용,
이미 존재하면 skip.
"""
from __future__ import annotations

from app.db import get_db, init_db
from app.models.korean_entities import (
    KoreanAICompany,
    KoreanCryptoExposure,
    KoreanPolicy,
)


AI_COMPANIES = [
    {
        "group_name": "Naver",
        "ticker_kr": "035420",
        "ai_model_name": "HyperCLOVA X / HCX Think / Agent N",
        "us_partners": "AWS, Intel",
        "msit_sovereign_ai_status": "finalist",
        "notes": "2025-11 Agent N 출시",
    },
    {
        "group_name": "Kakao",
        "ticker_kr": "035720",
        "ai_model_name": "Kanana",
        "us_partners": "OpenAI, Google",
        "msit_sovereign_ai_status": "dropped",
        "notes": "2025-02 OpenAI 전략제휴, 2026-02 Google 온디바이스",
    },
    {
        "group_name": "SKT",
        "ticker_kr": "017670",
        "ai_model_name": "A.X 4.0",
        "us_partners": "AWS, Rebellions",
        "msit_sovereign_ai_status": "finalist",
        "notes": "Qwen2.5-72B base. 10M 구독자",
    },
    {
        "group_name": "LG",
        "ticker_kr": "003550",
        "ai_model_name": "Exaone 4.0 / Deep / ChatExaone",
        "us_partners": "Microsoft",
        "msit_sovereign_ai_status": "finalist",
        "notes": "CES 2025 MS 제휴",
    },
    {
        "group_name": "KT",
        "ticker_kr": "030200",
        "ai_model_name": "Mi:dm",
        "us_partners": "Microsoft (Azure)",
        "msit_sovereign_ai_status": "dropped",
    },
    {
        "group_name": "NCSOFT",
        "ticker_kr": "036570",
        "ai_model_name": "VARCO",
        "us_partners": None,
        "msit_sovereign_ai_status": "finalist",
    },
    {
        "group_name": "Upstage",
        "ticker_kr": None,
        "ai_model_name": "Solar",
        "us_partners": "AWS, Databricks",
        "msit_sovereign_ai_status": "finalist",
    },
]


POLICIES = [
    {
        "kr_short": "VAUPA",
        "kr_name": "가상자산이용자보호법",
        "en_name": "Virtual Asset User Protection Act",
        "kr_regulator": "FSC",
        "global_peer_name": "MiCA",
        "global_regulator": "EU",
        "status": "effective",
        "effective_date": "2024-07-19",
        "summary": "이용자 예치금 보호, 불공정거래 규제. 2단계(DABA)로 확장 중.",
    },
    {
        "kr_short": "DABA",
        "kr_name": "디지털자산기본법",
        "en_name": "Digital Asset Basic Act",
        "kr_regulator": "FSC",
        "global_peer_name": "GENIUS Act / Clarity Act",
        "global_regulator": "US Congress",
        "status": "proposed",
        "effective_date": None,
        "summary": "스테이블코인 발행·공시·감독 체계. 2025-06 국회 통과 발의.",
    },
    {
        "kr_short": "특금법",
        "kr_name": "특정금융정보법",
        "en_name": "Act on Reporting and Use of Specific Financial Transaction Information",
        "kr_regulator": "FIU",
        "global_peer_name": "BSA / FinCEN rules",
        "global_regulator": "US FinCEN",
        "status": "effective",
        "effective_date": "2021-03-25",
        "summary": "VASP 신고제, 실명계좌, 트래블룰. FIU 관할.",
    },
    {
        "kr_short": "AI기본법",
        "kr_name": "인공지능 기본법",
        "en_name": "AI Basic Act",
        "kr_regulator": "MSIT",
        "global_peer_name": "EU AI Act",
        "global_regulator": "EU",
        "status": "effective",
        "effective_date": "2026-01-22",
        "summary": "AI 등급제·고위험 AI 사전검증·생성형 AI 표시의무.",
    },
    {
        "kr_short": "자본시장법",
        "kr_name": "자본시장과 금융투자업에 관한 법률",
        "en_name": "Financial Investment Services and Capital Markets Act",
        "kr_regulator": "FSC",
        "global_peer_name": "Securities Act (1933/1934)",
        "global_regulator": "SEC",
        "status": "effective",
        "effective_date": "2009-02-04",
        "summary": "유사투자자문업·증권형 토큰 규제 근거.",
    },
    {
        "kr_short": "외환거래법",
        "kr_name": "외국환거래법",
        "en_name": "Foreign Exchange Transactions Act",
        "kr_regulator": "MOEF / BOK",
        "global_peer_name": "OFAC rules",
        "global_regulator": "US Treasury",
        "status": "effective",
        "effective_date": "1999-04-01",
        "summary": "해외 크립토 송금·김치프리미엄 차익거래 규제 근거.",
    },
    {
        "kr_short": "전자금융거래법",
        "kr_name": "전자금융거래법",
        "en_name": "Electronic Financial Transactions Act",
        "kr_regulator": "FSC",
        "global_peer_name": "PSD2",
        "global_regulator": "EU",
        "status": "effective",
        "effective_date": "2007-01-01",
        "summary": "전자지급수단·핀테크 인허가. 카카오페이·토스 근거.",
    },
    {
        "kr_short": "K-ISMS",
        "kr_name": "정보보호 관리체계 인증",
        "en_name": "Korea Information Security Management System",
        "kr_regulator": "KISA",
        "global_peer_name": "NIST CSF",
        "global_regulator": "US NIST",
        "status": "effective",
        "effective_date": "2013-02-18",
        "summary": "거래소·VASP·기관 정보보안 인증 의무.",
    },
]


CRYPTO_EXPOSURES = [
    {
        "corp_name": "우리기술투자",
        "corp_code_dart": None,
        "ticker_kr": "041190",
        "exposure_kind": "dunamu_shareholder",
        "crypto_entities": "Dunamu, Upbit",
        "exposure_summary": "Dunamu 지분 7.24% 보유. KRX 상장사 중 Upbit 최대 간접 노출.",
    },
    {
        "corp_name": "한화투자증권",
        "corp_code_dart": None,
        "ticker_kr": "003530",
        "exposure_kind": "dunamu_shareholder",
        "crypto_entities": "Dunamu, Upbit",
        "exposure_summary": "Dunamu 지분 5.95%. 한화그룹 디지털자산 진출 교두보.",
    },
    {
        "corp_name": "카카오",
        "corp_code_dart": None,
        "ticker_kr": "035720",
        "exposure_kind": "subsidiary_crypto",
        "crypto_entities": "Klaytn, Kaia, Ground X",
        "exposure_summary": "Kaia(구 Klaytn) 공동운영. 카카오페이 스테이블코인 진출 시 핵심.",
    },
    {
        "corp_name": "네이버",
        "corp_code_dart": None,
        "ticker_kr": "035420",
        "exposure_kind": "subsidiary_crypto",
        "crypto_entities": "LINE Next, Finschia, DOSI",
        "exposure_summary": "LINE 블록체인 자회사 통해 글로벌 크립토·NFT 진출.",
    },
    {
        "corp_name": "위메이드",
        "corp_code_dart": None,
        "ticker_kr": "112040",
        "exposure_kind": "native_token",
        "crypto_entities": "WEMIX",
        "exposure_summary": "WEMIX 발행사. 게임 토큰경제 국내 대표주자.",
    },
    {
        "corp_name": "컴투스",
        "corp_code_dart": None,
        "ticker_kr": "078340",
        "exposure_kind": "native_token",
        "crypto_entities": "XPLA, C2X",
        "exposure_summary": "XPLA 체인. 게임·콘텐츠 온체인 확장.",
    },
    {
        "corp_name": "넷마블",
        "corp_code_dart": None,
        "ticker_kr": "251270",
        "exposure_kind": "subsidiary_crypto",
        "crypto_entities": "MARBLEX",
        "exposure_summary": "MARBLEX 체인 자회사. 게임 토큰 발행.",
    },
]


def seed() -> None:
    init_db()
    db = get_db()
    try:
        # AI companies
        for data in AI_COMPANIES:
            existing = (
                db.query(KoreanAICompany)
                .filter(KoreanAICompany.group_name == data["group_name"])
                .first()
            )
            if existing is None:
                db.add(KoreanAICompany(**data))

        # Policies
        for data in POLICIES:
            existing = (
                db.query(KoreanPolicy)
                .filter(KoreanPolicy.kr_short == data["kr_short"])
                .first()
            )
            if existing is None:
                db.add(KoreanPolicy(**data))

        # Crypto exposures
        for data in CRYPTO_EXPOSURES:
            existing = (
                db.query(KoreanCryptoExposure)
                .filter(KoreanCryptoExposure.corp_name == data["corp_name"])
                .first()
            )
            if existing is None:
                db.add(KoreanCryptoExposure(**data))

        db.commit()
        ai_count = db.query(KoreanAICompany).count()
        pol_count = db.query(KoreanPolicy).count()
        ex_count = db.query(KoreanCryptoExposure).count()
        print(f"✓ seed 완료: AI {ai_count} / Policy {pol_count} / Exposure {ex_count}")
    except Exception as e:
        db.rollback()
        print(f"✗ seed 실패: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
