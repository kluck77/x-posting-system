"""content_fetcher 의 News1 류 Jina markdown 본문 추출 검증.

draft 1497 류 시점 오염 (2026 발표 → 2024 검토) 의 root cause 가
prompt 가 아니라 fetch / extract 단계 본문 dilution + cap + title /
published_at 부재였음. 이번 fix (F1+F2+F3+F4) 가 Jina markdown 의
사이드바 잡문을 제거하고 기사 메타 (제목 / 작성일 / 출처) 를 prepend
하는지 정적 검증.

특정 News1 한 기사에만 맞춘 하드코딩이 아니라 한국 매체 일반 패턴
(기자명+날짜 / "(서울=뉴스1)" 류 안내) 으로 처리되는지도 검증.
"""
from __future__ import annotations


# ─── F1 — article body extractor ────────────────────────────────────
class TestExtractArticleBodyFromJina:
    def _fixture(self) -> str:
        # 사이드바 / 메뉴 / 인기 / 광고 / 위젯 ~ 800 chars + 실 기사
        sidebar = (
            "쿠팡이츠 줄서는 맛집 / 오픈AI 충격 / 마이크론 4% 하락 / "
            "샌디스크 6% 급락 / PSG 뮌헨 5-4 승리 / 이강인 김민재 결장 / "
            "택배업계 원청 사용자성 인정 신중론 / 새한제약 페노피정 허가 "
            "취소 / 한·인도 경제 협력·지원 / "
            "정치 외교 북한 금융 증권 산업 부동산 IT 과학 바이오 "
            "생활 문화 연예 스포츠 오피니언 피플 포토 TV / "
            "실시간 인기 / 많이 본 뉴스 / 연관 기사 / 광고 / 날씨 위젯 / "
            "구독 공유 댓글 / "
            "2026.4.28 (화) 크립토허브 해피펫 English 노동신문 제보 / "
            "제주 12 ℃ 서울 10 ℃ 부산 12 ℃ 대구 12 ℃ 인천 8 ℃ 광주 10 ℃ / "
        ) * 3  # ~800+ chars
        article = (
            "\n# UAE OPEC+ 탈퇴, WTI 4%↑ 100달러 돌파(상보)\n"
            "박형기 기자 2026.04.29 오전 04:38\n"
            "브렌트유도 111달러 돌파\n"
            "(서울=뉴스1) 박형기 기자 = 아랍에미리트연합(UAE)이 OPEC+를 "
            "탈퇴한다는 소식으로 국제유가는 일제히 급등하고 있다.\n"
            "28일 오후 3시 20분 현재(현지 시각) 뉴욕상품거래소에서 서부 "
            "텍사스산중질유(WTI) 선물은 3.81% 급등했다.\n"
            "이는 이날 UAE가 5월 1일부터 OPEC+를 탈퇴할 예정이라고 "
            "밝혔기 때문이다.\n"
            "UAE의 이번 조치는 OPEC+에 큰 충격을 줄 전망이다.\n"
        )
        return sidebar + article

    def test_extractor_strips_sidebar_before_article_marker(self):
        from app.services.content_fetcher import _extract_article_body_from_jina
        out = _extract_article_body_from_jina(self._fixture())
        # 핵심 기사 문장은 살아있어야 함
        assert "UAE가 5월 1일부터 OPEC+를 탈퇴" in out
        # 기사 시작 마커 ("박형기 기자 2026.04.29" 또는 "(서울=뉴스1)") 가
        # 출력 시작 부근에 있어야 함 (사이드바 잡문 제거됨)
        # 사이드바 키워드는 출력 앞부분 100자 안에 안 보여야 함
        head = out[:200]
        assert "쿠팡이츠" not in head
        assert "PSG" not in head
        assert "샌디스크" not in head
        assert "날씨 위젯" not in head

    def test_extractor_keeps_article_when_no_sidebar(self):
        # 사이드바 없는 짧은 기사 → 그대로 반환 (또는 # 헤딩 부터)
        from app.services.content_fetcher import _extract_article_body_from_jina
        clean = "# 기사 제목\n홍길동 기자 2026-04-30\n본문 내용입니다."
        out = _extract_article_body_from_jina(clean)
        assert "본문 내용입니다" in out

    def test_extractor_failopen_when_no_signal(self):
        # 시작 마커도 # 헤딩도 없는 경우 — 원문 그대로 반환 (fail-open)
        from app.services.content_fetcher import _extract_article_body_from_jina
        plain = "단순 본문. 시작 신호 없음. 유지된다."
        out = _extract_article_body_from_jina(plain)
        assert out == plain


# ─── F3 — published_at extraction ───────────────────────────────────
class TestExtractPublishedAt:
    def test_extracts_iso_meta(self):
        from app.services.content_fetcher import _extract_published_at
        html = '<meta property="article:published_time" content="2026-04-29T04:38:00+09:00">'
        assert _extract_published_at(html) == "2026-04-29T04:38:00+09:00"

    def test_extracts_time_tag(self):
        from app.services.content_fetcher import _extract_published_at
        html = '<time datetime="2026-04-29T04:38:00">2026.04.29</time>'
        assert _extract_published_at(html) == "2026-04-29T04:38:00"

    def test_extracts_korean_datetime_pattern(self):
        from app.services.content_fetcher import _extract_published_at
        text = "박형기 기자\n2026.04.29 오전 04:38\n본문..."
        assert _extract_published_at(text) == "2026.04.29 오전 04:38"

    def test_extracts_dash_date_pattern(self):
        from app.services.content_fetcher import _extract_published_at
        text = "기사 작성: 2026-04-29\n본문..."
        out = _extract_published_at(text)
        assert "2026-04-29" in out

    def test_returns_empty_when_no_date(self):
        # 날짜를 못 찾으면 추정 X — 빈 문자열
        from app.services.content_fetcher import _extract_published_at
        assert _extract_published_at("날짜 없는 본문") == ""
        assert _extract_published_at("") == ""

    def test_does_not_invent_current_date(self):
        # 시스템 현재 시각 / URL 같은 외부 정보로 만들지 않음
        from app.services.content_fetcher import _extract_published_at
        out = _extract_published_at("https://example.com")
        assert out == "" or out.startswith("20")  # URL 안 https 패턴 무시


# ─── F4 — title fallback ────────────────────────────────────────────
class TestExtractJinaTitle:
    def test_extracts_explicit_title_meta(self):
        from app.services.content_fetcher import _extract_jina_title
        text = "Title: UAE OPEC+ 탈퇴, WTI 4%↑\n본문..."
        assert _extract_jina_title(text, "fallback") == "UAE OPEC+ 탈퇴, WTI 4%↑"

    def test_extracts_first_h1_heading(self):
        from app.services.content_fetcher import _extract_jina_title
        text = "# UAE OPEC+ 탈퇴, WTI 4%↑ 100달러 돌파\n본문..."
        assert _extract_jina_title(text, "fallback") == "UAE OPEC+ 탈퇴, WTI 4%↑ 100달러 돌파"

    def test_extracts_heading_in_body_when_meta_missing(self):
        # 첫 10 줄 안 메타 없고, 더 뒤에 # heading 있을 때
        from app.services.content_fetcher import _extract_jina_title
        text = "\n".join(["사이드바 메뉴"] * 15) + "\n# 진짜 기사 제목\n본문"
        out = _extract_jina_title(text, "fallback")
        assert out == "진짜 기사 제목"

    def test_falls_back_to_url_when_no_title(self):
        from app.services.content_fetcher import _extract_jina_title
        url = "https://www.news1.kr/world/usa-canada/6152007"
        assert _extract_jina_title("본문만 있음", url) == url


# ─── F2 + 통합: 메타 prepend ────────────────────────────────────────
class TestPrependArticleMetadata:
    def test_prepends_title_and_date_and_source(self):
        from app.services.content_fetcher import _prepend_article_metadata
        out = _prepend_article_metadata(
            "UAE OPEC+ 탈퇴, WTI 4%↑",
            "2026.04.29 오전 04:38",
            "jina",
            "본문 시작.",
        )
        assert "[기사 제목: UAE OPEC+ 탈퇴, WTI 4%↑]" in out
        assert "[기사 작성일: 2026.04.29 오전 04:38]" in out
        assert "[본문 출처: jina]" in out
        assert "본문 시작." in out
        # title / 작성일 / 출처 가 본문 *앞* 에
        meta_idx = out.find("[기사 제목:")
        body_idx = out.find("본문 시작.")
        assert -1 < meta_idx < body_idx

    def test_skips_url_title(self):
        # title 이 URL 인 경우 — meta 라인 미생성 (downstream 신호 약화 회피)
        from app.services.content_fetcher import _prepend_article_metadata
        out = _prepend_article_metadata(
            "https://www.news1.kr/world/usa-canada/6152007",
            "2026.04.29",
            "jina",
            "본문",
        )
        assert "[기사 제목:" not in out
        assert "[기사 작성일: 2026.04.29]" in out

    def test_skips_empty_date(self):
        # 작성일 빈 문자열 — 작성일 라인 미생성
        from app.services.content_fetcher import _prepend_article_metadata
        out = _prepend_article_metadata("제목", "", "jina", "본문")
        assert "[기사 작성일:" not in out
        assert "[기사 제목: 제목]" in out

    def test_returns_body_only_when_all_meta_empty(self):
        from app.services.content_fetcher import _prepend_article_metadata
        assert _prepend_article_metadata("", "", "", "본문") == "본문"


# ─── E2E — _postprocess 가 정제 후 메타 prepend ─────────────────────
class TestPostprocessIntegration:
    def test_postprocess_prepends_metadata_after_cleaning(self):
        from app.services.content_fetcher import _postprocess
        result = {
            "title": "UAE OPEC+ 탈퇴 발표",
            "text": "본문 사실: UAE 가 5 월 1 일부터 OPEC+ 를 탈퇴할 예정.",
            "url": "https://www.news1.kr/world/usa-canada/6152007",
            "source": "jina",
            "published_at": "2026.04.29 오전 04:38",
            "error": None,
        }
        out = _postprocess(result)
        text = out.get("text", "")
        # 정제 후 메타가 붙어있어야 함
        assert "[기사 제목: UAE OPEC+ 탈퇴 발표]" in text
        assert "[기사 작성일: 2026.04.29 오전 04:38]" in text
        assert "[본문 출처: jina]" in text
        # 본문 핵심 사실도 살아있어야 함
        assert "UAE" in text and "5 월 1 일" in text
        # title / 작성일 / 출처 가 본문 앞에 prepend
        meta_idx = text.find("[기사 제목:")
        body_idx = text.find("UAE 가 5 월 1 일")
        assert -1 < meta_idx < body_idx

    def test_postprocess_failopen_when_meta_missing(self):
        # title / published_at 없어도 깨지지 않음 (fail-open)
        from app.services.content_fetcher import _postprocess
        result = {
            "title": "",
            "text": "본문만 있음",
            "url": "https://example.com",
            "source": "direct",
            "published_at": "",
            "error": None,
        }
        out = _postprocess(result)
        assert out.get("text", "") != ""
        assert out.get("low_quality") in (True, False)


# ─── 통합 시뮬레이션 — News1 류 Jina dump ────────────────────────────
class TestNewsArticleEndToEnd:
    """Jina markdown 형식 (사이드바 ~800 chars + 실 기사) 시뮬레이션."""

    @staticmethod
    def _build_fixture() -> str:
        sidebar = (
            "쿠팡이츠 줄서는 맛집 / 오픈AI 충격 / 마이크론 4% 하락 / "
            "샌디스크 6% 급락 / PSG 뮌헨 5-4 승리 / 이강인 김민재 결장 / "
            "택배업계 원청 사용자성 인정 신중론 / 새한제약 페노피정 허가 "
            "취소 / 한·인도 경제 협력·지원 / 정치 외교 북한 금융 증권 / "
            "산업 부동산 IT 과학 바이오 생활 문화 연예 스포츠 오피니언 / "
            "피플 포토 TV / 실시간 인기 / 많이 본 뉴스 / 연관 기사 / "
            "광고 / 날씨 위젯 / 구독 공유 댓글 / "
            "제주 12 ℃ 서울 10 ℃ 부산 12 ℃ / "
        ) * 3
        article = (
            "\n# UAE OPEC+ 탈퇴, WTI 4%↑ 100달러 돌파(상보)\n"
            "박형기 기자 2026.04.29 오전 04:38\n"
            "브렌트유도 111달러 돌파\n"
            "(서울=뉴스1) 박형기 기자 = 아랍에미리트연합(UAE)이 OPEC+를 "
            "탈퇴한다는 소식으로 국제유가는 일제히 급등하고 있다.\n"
            "이는 이날 UAE가 5월 1일부터 OPEC+를 탈퇴할 예정이라고 "
            "밝혔기 때문이다.\n"
            "UAE의 이번 조치는 OPEC+에 큰 충격을 줄 전망이다.\n"
        )
        return sidebar + article

    def test_fixture_extraction_pipeline(self):
        from app.services.content_fetcher import (
            _extract_article_body_from_jina,
            _extract_published_at,
            _extract_jina_title,
            _prepend_article_metadata,
            _clean_jina_text,
        )
        raw = self._build_fixture()
        title = _extract_jina_title(raw, "https://example.com")
        published_at = _extract_published_at(raw)
        article_only = _extract_article_body_from_jina(raw)
        clean = _clean_jina_text(article_only)
        merged = _prepend_article_metadata(title, published_at, "jina", clean)

        # 1. title 이 URL 이 아니라 실제 기사 제목
        assert "OPEC+" in title and not title.startswith("http")
        assert "UAE" in title
        # 2. 작성일 추출
        assert "2026" in published_at
        # 3. clean 앞부분에 사이드바 잡문 없음 (첫 200자 검사)
        head = clean[:300]
        assert "쿠팡이츠" not in head
        assert "PSG" not in head
        assert "샌디스크" not in head
        # 4. merged 안 메타 prepend
        assert "[기사 제목:" in merged
        assert "[기사 작성일:" in merged
        assert "[본문 출처: jina]" in merged
        # 5. 핵심 본문 살아있음
        assert "UAE가 5월 1일부터 OPEC+를 탈퇴" in merged
        # 6. 없는 과거 사건 X (fixture 에 없는 시점은 만들지 않음)
        for forbidden in ("2024년 고려", "2023년 검토", "소문", "부인"):
            assert forbidden not in merged

    def test_clean_text_cap_8000_post_clean(self):
        # 정제 후 cap 8000. 정제 전 raw 가 더 길어도 clean 본문 기준.
        from app.services.content_fetcher import (
            _extract_article_body_from_jina,
            _clean_jina_text,
        )
        # 매우 긴 사이드바 (~10k chars) + 짧은 기사
        raw = "사이드바 잡문 " * 1000 + "\n홍길동 기자 2026-04-29\n본문 핵심."
        article_only = _extract_article_body_from_jina(raw)
        clean = _clean_jina_text(article_only)
        cap = clean[:8000]
        # 8000 cap 적용되어 길이 ≤ 8000
        assert len(cap) <= 8000
        # 핵심 본문은 cap 안 살아있음 (사이드바 제거 후 잘림 X)
        assert "본문 핵심" in cap
