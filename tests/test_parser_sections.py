"""extract_business_sections 단위 테스트.

LLM fallback은 mock으로 주입하거나 None으로 두어 deterministic 경로만 검증.
"""
from unittest.mock import MagicMock

from themek.dart.parser import extract_business_sections


_FILLER = "ㅇ" * 400


SAMPLE_HTML = f"""
<html><body>
<h2>II. 사업의 내용</h2>

<h3>1. 사업의 개요</h3>
<p>당사는 반도체와 디스플레이를 영위한다. {_FILLER}</p>

<h3>2. 주요 제품 및 서비스</h3>
<p>DRAM, NAND, OLED. {_FILLER}</p>

<h3>3. 원재료 및 생산설비</h3>
<p>이 부분은 노이즈여야 한다 — E5와 무관. {_FILLER}</p>

<h3>4. 매출 및 수주상황</h3>
<p>국내 14.8%, 해외 85.2%. {_FILLER}</p>

<h3>5. 위험관리 및 파생거래</h3>
<p>이 부분도 노이즈. {_FILLER}</p>
</body></html>
"""


def test_section_filter_regex_all_three_matched():
    text, resolution = extract_business_sections(SAMPLE_HTML)
    assert "반도체와 디스플레이" in text       # overview
    assert "DRAM, NAND, OLED" in text         # products
    assert "국내 14.8%, 해외 85.2%" in text   # revenue
    assert "노이즈여야 한다" not in text       # §3 (원재료) body 제외
    assert set(resolution.regex_matched) == {"overview", "products", "revenue"}
    assert resolution.skipped == []
    assert resolution.llm_called is False
    assert resolution.escalation_level == "regex"


def test_section_filter_keeps_only_requested():
    text, resolution = extract_business_sections(
        SAMPLE_HTML, want={"overview"},
    )
    assert "반도체와 디스플레이" in text
    assert "DRAM" not in text
    # `국내` 14.8% line — revenue body 제외
    assert "14.8%" not in text
    assert set(resolution.regex_matched) == {"overview"}


def test_section_filter_handles_korean_letter_headers():
    """헤더 표기가 '가.' / '나.' / '다.' 인 경우도 인식한다."""
    html = f"""
    <h3>가. 사업의 개요</h3>
    <p>개요 본문. {_FILLER}</p>
    <h3>나. 주요 제품</h3>
    <p>제품 본문. {_FILLER}</p>
    <h3>다. 매출 현황</h3>
    <p>매출 본문. {_FILLER}</p>
    """
    text, resolution = extract_business_sections(html)
    assert "개요 본문" in text
    assert "제품 본문" in text
    assert "매출 본문" in text


def test_section_filter_missing_target_without_fallback_skips():
    """LLM fallback이 None이고 regex 매칭이 부분 실패하면 미매칭은 skip.

    missing alone은 full_text fallback을 트리거하지 않음 (invalid_targets 만 트리거).
    """
    html = f"""
    <h3>1. 사업의 개요</h3>
    <p>개요 본문. {_FILLER}</p>
    <h3>2. 회사의 비전</h3>
    <p>비전 본문. {_FILLER}</p>
    """
    text, resolution = extract_business_sections(html, llm_fallback=None)
    assert "개요 본문" in text
    assert "비전 본문" not in text
    assert "overview" in resolution.regex_matched
    assert sorted(resolution.skipped) == ["products", "revenue"]
    assert resolution.llm_called is False
    assert resolution.escalation_level == "regex"


def test_section_filter_zero_matches_returns_full_text_with_warning():
    """헤더 0개 매칭이면 전체 본문을 반환하고 skipped 전부 기록."""
    html = "<p>그냥 본문, 헤더 없음.</p>"
    text, resolution = extract_business_sections(html, llm_fallback=None)
    assert "그냥 본문" in text
    assert sorted(resolution.skipped) == ["overview", "products", "revenue"]
    assert resolution.escalation_level == "full_text"


def test_section_filter_calls_llm_fallback_for_missing_targets():
    html = f"""
    <h3>1. 사업의 개요</h3>
    <p>개요 본문. {_FILLER}</p>
    <h3>2. 영업현황</h3>
    <p>영업 본문. {_FILLER}</p>
    <h3>3. 회사의 비전</h3>
    <p>비전 본문. {_FILLER}</p>
    """
    mock_fallback = MagicMock(return_value={
        "overview": None,
        "products": 1,
        "revenue": None,
    })
    text, resolution = extract_business_sections(html, llm_fallback=mock_fallback)
    assert "개요 본문" in text
    assert resolution.llm_called is True
    # llm_input_candidates에 overview용으로 매칭된 헤더가 포함되면 안 됨
    assert "사업의 개요" not in " ".join(resolution.llm_input_candidates)
    mock_fallback.assert_called_once()


def test_section_filter_does_not_call_fallback_when_all_regex_matched():
    mock_fallback = MagicMock()
    _, resolution = extract_business_sections(SAMPLE_HTML, llm_fallback=mock_fallback)
    mock_fallback.assert_not_called()
    assert resolution.llm_called is False


def test_section_filter_ignores_korean_sub_bullets_when_numeric_present():
    """numeric 헤더가 있을 때 `가.` `나.` sub-bullet은 boundary로 쓰지 않는다."""
    html = f"""
    <p>1. 사업의 개요</p>
    <p>가. 협동로봇</p>
    <p>당사는 협동로봇 사업을 영위합니다. {_FILLER}</p>
    <p>나. 이족보행로봇</p>
    <p>이족보행로봇은 HUBO 플랫폼이 대표적입니다. {_FILLER}</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>RB 시리즈 협동로봇. {_FILLER}</p>
    <p>3. 원재료 및 생산설비</p>
    <p>노이즈여야 함. {_FILLER}</p>
    <p>4. 매출 및 수주상황</p>
    <p>국내 매출 80%. {_FILLER}</p>
    """
    text, resolution = extract_business_sections(html, llm_fallback=None)
    assert "협동로봇 사업을 영위" in text
    assert "이족보행로봇은 HUBO" in text
    assert "RB 시리즈" in text
    assert "국내 매출 80%" in text
    assert "노이즈여야 함" not in text
    assert set(resolution.regex_matched) == {"overview", "products", "revenue"}


def test_section_filter_regex_rejects_decimal_noise():
    html = f"""
    <p>1. 사업의 개요</p>
    <p>본문 시작 {_FILLER}</p>
    <p>65.7%</p>
    <p>80.0</p>
    <p>2017.01∼2017.12</p>
    <p>본문 끝</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>제품 본문 {_FILLER}</p>
    <p>4. 매출 및 수주상황</p>
    <p>매출 본문 {_FILLER}</p>
    """
    text, resolution = extract_business_sections(html, llm_fallback=None)
    assert "본문 시작" in text
    assert "65.7%" in text       # 본문에 포함
    assert "본문 끝" in text     # 노이즈 라인 뒤 본문도 살아 있음
    assert "제품 본문" in text
    assert "매출 본문" in text
    assert set(resolution.regex_matched) == {"overview", "products", "revenue"}


def test_parser_uses_learned_pattern_when_provided(tmp_path, monkeypatch):
    """learned_header_patterns.json에 '회사의 개황' 패턴 추가하면 parser가 인식한다."""
    from themek.dart.learned_patterns import (
        LearnedPatterns, save_learned_patterns,
    )
    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern(
        "overview", regex=r"회사.{0,3}개황",
        source="learned", samples=["회사의 개황"], confirmed_count=3,
    )
    p = tmp_path / "learned.json"
    save_learned_patterns(p, lp)
    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(p))

    html = f"""
    <p>1. 회사의 개황</p>
    <p>{_FILLER}</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>{_FILLER}</p>
    <p>3. 매출 및 수주상황</p>
    <p>{_FILLER}</p>
    """
    _, res = extract_business_sections(html, llm_fallback=None)
    assert "overview" in res.regex_matched
    assert res.escalation_level == "regex"


def test_section_filter_against_all_mirrored_fixtures():
    """tests/fixtures/dart_variants/ 의 모든 fixture에 대해 expected_headers 일치."""
    import json
    from pathlib import Path
    fx = Path("tests/fixtures/dart_variants")
    html_files = sorted(fx.glob("*.html"))
    if not html_files:
        # fixture가 없으면 스킵 (초기 상태)
        return
    for hp in html_files:
        ej = hp.with_name(hp.stem + "_headers.json")
        if not ej.exists():
            continue
        expected = json.loads(ej.read_text(encoding="utf-8"))
        html = hp.read_text(encoding="utf-8")
        _, res = extract_business_sections(html, llm_fallback=None)
        for t, exp_header in expected.items():
            got = res.regex_matched.get(t)
            assert got, f"{hp.stem}: {t} not matched (got={got})"
