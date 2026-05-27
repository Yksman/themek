import json
from unittest.mock import MagicMock
import pytest
from themek.llm.claude_cli import (
    call_claude, extract_json_block, ClaudeCallError, CallResult,
)


def test_call_claude_returns_call_result_with_text_and_usage(mocker):
    mock_run = mocker.patch("themek.llm.claude_cli.subprocess.run")
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "안녕",
            "usage": {"input_tokens": 1234, "output_tokens": 56},
            "total_cost_usd": 0.0042,
            "duration_ms": 17320,
        }),
        stderr="",
    )
    result = call_claude("test prompt")
    assert isinstance(result, CallResult)
    assert result.text == "안녕"
    assert result.input_tokens == 1234
    assert result.output_tokens == 56
    assert result.cost_usd == 0.0042
    assert result.duration_ms == 17320
    assert result.raw_payload["result"] == "안녕"
    mock_run.assert_called_once()
    args, _ = mock_run.call_args
    assert args[0][0] == "claude"
    assert "-p" in args[0]
    assert "--output-format" in args[0]
    assert "json" in args[0]


def test_call_claude_returns_zero_usage_when_fields_missing(mocker):
    """claude payload에 usage/cost/duration이 없어도 안전하게 0."""
    mock_run = mocker.patch("themek.llm.claude_cli.subprocess.run")
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"type": "result", "result": "ok"}),
        stderr="",
    )
    result = call_claude("test")
    assert result.text == "ok"
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.cost_usd == 0.0
    assert result.duration_ms == 0


def test_call_claude_raises_on_nonzero_exit(mocker):
    mocker.patch(
        "themek.llm.claude_cli.subprocess.run",
        return_value=MagicMock(returncode=1, stdout="", stderr="boom"),
    )
    with pytest.raises(ClaudeCallError, match="boom"):
        call_claude("test")


def test_call_claude_raises_on_invalid_json(mocker):
    mocker.patch(
        "themek.llm.claude_cli.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="not json", stderr=""),
    )
    with pytest.raises(ClaudeCallError, match="JSON"):
        call_claude("test")


def test_extract_json_block_from_text():
    text = "여기 결과입니다:\n```json\n{\"a\": 1}\n```\n끝."
    assert extract_json_block(text) == {"a": 1}


def test_extract_json_block_plain_json():
    assert extract_json_block('{"x": "y"}') == {"x": "y"}


def test_extract_json_block_raises_when_no_json():
    with pytest.raises(ClaudeCallError):
        extract_json_block("그냥 텍스트")
