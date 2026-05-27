"""llm_classify_headers — call_claude를 mock으로 막고 결과 dict 생성 로직만 검증."""
import json
import pytest
from themek.llm.claude_cli import CallResult, ClaudeCallError


def _mock_callresult(text: str) -> CallResult:
    return CallResult(text=text, input_tokens=10, output_tokens=5,
                      cost_usd=0.0001, duration_ms=200, raw_payload={})


def test_llm_classify_returns_decision_dict(mocker):
    from themek.dart.parser import llm_classify_headers
    mocker.patch(
        "themek.dart.parser.call_claude",
        return_value=_mock_callresult(
            json.dumps({"overview": 1, "products": 2, "revenue": None}),
        ),
    )
    decision = llm_classify_headers(
        candidates=["가. 사업개요", "나. 제품 라인업", "다. R&D 조직"],
        missing_targets=["overview", "products", "revenue"],
    )
    assert decision == {"overview": 1, "products": 2, "revenue": None}


def test_llm_classify_parses_fenced_json(mocker):
    from themek.dart.parser import llm_classify_headers
    mocker.patch(
        "themek.dart.parser.call_claude",
        return_value=_mock_callresult(
            "결과:\n```json\n{\"overview\": null, \"products\": 1, \"revenue\": 2}\n```",
        ),
    )
    decision = llm_classify_headers(["a", "b"], ["overview", "products", "revenue"])
    assert decision == {"overview": None, "products": 1, "revenue": 2}


def test_llm_classify_raises_on_bad_payload(mocker):
    from themek.dart.parser import llm_classify_headers
    mocker.patch(
        "themek.dart.parser.call_claude",
        return_value=_mock_callresult("아무말이나"),
    )
    with pytest.raises(ClaudeCallError):
        llm_classify_headers(["a"], ["overview"])


def test_llm_classify_normalizes_missing_keys(mocker):
    """LLM이 일부 키를 빼먹어도 None으로 채운다."""
    from themek.dart.parser import llm_classify_headers
    mocker.patch(
        "themek.dart.parser.call_claude",
        return_value=_mock_callresult(json.dumps({"overview": 1})),
    )
    decision = llm_classify_headers(["a"], ["overview", "products", "revenue"])
    assert decision == {"overview": 1, "products": None, "revenue": None}
