from themek.llm.prompts import build_business_extraction_prompt


def test_prompt_contains_text():
    text = "이 회사의 매출은 메모리 50%, 디스플레이 30%, 기타 20%로 구성됨."
    prompt = build_business_extraction_prompt(text, period_hint="2023")
    assert "이 회사의 매출" in prompt
    assert "2023" in prompt


def test_prompt_instructs_json_only_output():
    prompt = build_business_extraction_prompt("x", period_hint="2024Q1")
    assert "JSON" in prompt or "json" in prompt
    assert "segments" in prompt


def test_prompt_lists_allowed_region_codes():
    prompt = build_business_extraction_prompt("x", period_hint="2024")
    for code in ["KR", "US", "EU", "CN", "JP", "ROW"]:
        assert code in prompt
