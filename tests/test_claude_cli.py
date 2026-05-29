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


def test_call_claude_uses_regex_timeout(mocker, monkeypatch):
    """escalation='regex' → 60s timeout."""
    monkeypatch.delenv("CLAUDE_CLI_REGEX_TIMEOUT_SEC", raising=False)
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = json.dumps({"result": "{}"})
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p", escalation="regex")
    assert fake.call_args.kwargs["timeout"] == 60


def test_call_claude_uses_full_text_timeout(mocker, monkeypatch):
    """escalation='full_text' → 600s timeout."""
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = json.dumps({"result": "{}"})
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p", escalation="full_text")
    assert fake.call_args.kwargs["timeout"] == 600


def test_call_claude_explicit_timeout_overrides_escalation(mocker):
    """timeout_sec 직접 지정이 escalation default보다 우선."""
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = json.dumps({"result": "{}"})
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p", escalation="regex", timeout_sec=300)
    assert fake.call_args.kwargs["timeout"] == 300


def test_call_claude_no_escalation_keeps_default(mocker):
    """escalation 미지정 시 기존 settings default 사용."""
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = json.dumps({"result": "{}"})
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p")  # no escalation
    assert fake.call_args.kwargs["timeout"] == 120  # config default


def test_call_claude_retries_on_empty_body_exit_1(mocker, monkeypatch):
    """exit 1 + empty stdout/stderr + 빠른 종료 → short retry 시도."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "3")
    sleep_mock = mocker.patch("themek.llm.claude_cli.time.sleep")
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    # 첫 2회는 transient 실패, 3번째는 성공
    fake.side_effect = [
        mocker.Mock(returncode=1, stdout="", stderr=""),
        mocker.Mock(returncode=1, stdout="", stderr=""),
        mocker.Mock(returncode=0, stdout='{"result":"ok","usage":{}}', stderr=""),
    ]
    from themek.llm.claude_cli import call_claude
    r = call_claude("p", escalation="regex")
    assert r.text == "ok"
    assert fake.call_count == 3
    # back-off 두 번 호출 (10s, 60s)
    assert sleep_mock.call_args_list == [
        mocker.call(10), mocker.call(60),
    ]


def test_call_claude_non_transient_exit_skips_retry(mocker, monkeypatch):
    """exit 1 이지만 stderr 메시지 있으면 retry 안 함 (real error로 간주)."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "3")
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value = mocker.Mock(returncode=1, stdout="", stderr="auth failed")
    from themek.llm.claude_cli import call_claude, ClaudeCallError
    with pytest.raises(ClaudeCallError, match="auth failed"):
        call_claude("p", escalation="regex")
    assert fake.call_count == 1  # 즉시 fail, retry 안 함
