"""Phase 1: SectionResolution escalation 필드 + sanity check + A→B→C."""
from unittest.mock import MagicMock

from themek.dart.parser import SectionResolution, extract_business_sections


def test_section_resolution_has_escalation_fields():
    r = SectionResolution()
    assert r.escalation_level == "regex"
    assert r.body_chars_per_target == {}
    assert r.invalid_targets == []
    assert r.learned_samples == []


def test_sanity_check_marks_short_section_invalid():
    """body가 MIN_SECTION_CHARS 미만이면 그 target은 invalid_targets에."""
    html = """
    <p>1. 사업의 개요</p>
    <p>짧음</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>이건 충분히 길어야 함. {filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>매출 본문 또한 충분한 길이. {filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    text, res = extract_business_sections(html, llm_fallback=None)
    # short overview → invalid → full_text fallback
    assert "overview" in res.invalid_targets
    assert res.body_chars_per_target["overview"] < 300
    assert res.body_chars_per_target["products"] >= 300
    assert res.body_chars_per_target["revenue"] >= 300
    assert res.escalation_level == "full_text"


def test_sanity_check_body_chars_recorded_for_all_matched():
    html = """
    <p>1. 사업의 개요</p>
    <p>충분히 긴 개요 본문. {filler}</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>충분히 긴 제품 본문. {filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>충분히 긴 매출 본문. {filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    _, res = extract_business_sections(html, llm_fallback=None)
    assert res.invalid_targets == []
    for t in ("overview", "products", "revenue"):
        assert t in res.body_chars_per_target
        assert res.body_chars_per_target[t] > 0
    assert res.escalation_level == "regex"


def test_escalation_a_to_b_triggers_on_invalid_target():
    """regex로 잡혔지만 body가 짧으면 LLM fallback이 호출되고 escalation=regex+llm."""
    html = """
    <p>1. 사업의 개요</p>
    <p>짧음</p>
    <p>2. 영업 현황 (regex 매칭 X)</p>
    <p>{filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>{filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    mock_fb = MagicMock(return_value={
        "overview": 1,
        "products": None,
        "revenue": None,
    })
    _, res = extract_business_sections(html, llm_fallback=mock_fb)
    # LLM 호출은 일어남
    assert res.llm_called is True
    # escalation은 regex+llm 또는 full_text (LLM이 fix 했으면 regex+llm)
    assert res.escalation_level in ("regex+llm", "full_text")


def test_escalation_stays_regex_when_all_valid_and_matched():
    html = """
    <p>1. 사업의 개요</p>
    <p>{filler}</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>{filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>{filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    _, res = extract_business_sections(html, llm_fallback=lambda c, m: {})
    assert res.escalation_level == "regex"
    assert res.llm_called is False


def test_escalation_b_to_c_returns_full_text_when_invalid_remains():
    html = """
    <p>1. 사업의 개요</p>
    <p>너무 짧음</p>
    <p>2. 노이즈 헤더</p>
    <p>여기도 짧음</p>
    <p>full text fallback에서 와야 하는 핵심 본문이 여기에 있다. {filler}</p>
    """.replace("{filler}", "ㅇ" * 500)
    mock_fb = MagicMock(return_value={
        "overview": None, "products": None, "revenue": None,
    })
    text, res = extract_business_sections(html, llm_fallback=mock_fb)
    assert res.escalation_level == "full_text"
    assert "full text fallback에서 와야 하는 핵심 본문" in text


def test_escalation_b_to_c_when_zero_headers():
    html = "<p>아무 헤더 없이 본문만 길게 " + "ㅇ" * 500 + "</p>"
    text, res = extract_business_sections(html, llm_fallback=None)
    assert res.escalation_level == "full_text"
    assert len(text) > 300


def test_learned_samples_populated_on_llm_match():
    """LLM이 새 변형 헤더를 분류하면 learned_samples에 기록."""
    html = """
    <p>1. 회사의 개황</p>
    <p>{filler}</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>{filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>{filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    mock_fb = MagicMock(return_value={
        "overview": 1, "products": None, "revenue": None,
    })
    _, res = extract_business_sections(html, llm_fallback=mock_fb)
    assert any(
        s["target"] == "overview" and "회사의 개황" in s["header_text"]
        for s in res.learned_samples
    )
