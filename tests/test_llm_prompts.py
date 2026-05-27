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


from themek.llm.prompts import build_header_classification_prompt


def test_header_classification_prompt_includes_1based_indices():
    prompt = build_header_classification_prompt(
        candidates=["가. 회사의 비전", "나. 영업현황"],
        missing_targets=["products", "revenue"],
    )
    assert "[1] 가. 회사의 비전" in prompt
    assert "[2] 나. 영업현황" in prompt
    assert '"overview"' in prompt
    assert '"products"' in prompt
    assert '"revenue"' in prompt
    assert "JSON" in prompt


def test_header_classification_prompt_handles_empty_candidates():
    prompt = build_header_classification_prompt([], ["overview"])
    # 후보가 없어도 JSON-only 응답 지침은 유지
    assert "JSON" in prompt
