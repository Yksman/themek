"""Claude Code CLI (claude -p) subprocess wrapper.

구독 기반 사용: ANTHROPIC_API_KEY 불필요. claude CLI가 사용자 인증된 상태여야 함.
"""
from __future__ import annotations
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from themek.config import get_settings


class ClaudeCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class CallResult:
    """claude -p --output-format json 의 응답 + 사용량 메타."""
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    raw_payload: dict


def call_claude(
    prompt: str,
    *,
    timeout_sec: int | None = None,
    escalation: str | None = None,
) -> CallResult:
    """`claude -p <prompt> --output-format json` 호출 후 CallResult 반환.

    timeout 우선순위:
      1) 명시적 timeout_sec
      2) escalation 별 default (regex=60s, llm=120s, full_text=600s)
      3) settings.claude_cli_timeout_sec (legacy default)
    """
    settings = get_settings()
    if timeout_sec is not None:
        timeout = timeout_sec
    elif escalation == "regex":
        timeout = settings.claude_cli_timeout_regex_sec
    elif escalation == "full_text":
        timeout = settings.claude_cli_timeout_full_text_sec
    elif escalation == "llm":
        timeout = settings.claude_cli_timeout_llm_sec
    else:
        timeout = settings.claude_cli_timeout_sec
    try:
        proc = subprocess.run(
            [settings.claude_cli_bin, "-p", prompt,
             "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCallError(f"claude CLI timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise ClaudeCallError(
            f"claude CLI not found at '{settings.claude_cli_bin}'"
        ) from e

    if proc.returncode != 0:
        raise ClaudeCallError(
            f"claude CLI exited {proc.returncode}: {proc.stderr.strip()}"
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCallError(
            f"claude CLI output is not valid JSON: {proc.stdout[:300]}"
        ) from e

    if not isinstance(payload, dict) or "result" not in payload:
        raise ClaudeCallError(f"unexpected claude payload: {payload!r}")

    usage = payload.get("usage") or {}
    return CallResult(
        text=payload["result"],
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
        duration_ms=int(payload.get("duration_ms") or 0),
        raw_payload=payload,
    )


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json_block(text: str) -> Any:
    """LLM 응답에서 JSON 객체를 추출.

    1) 응답이 통째로 valid JSON이면 그대로 parse
    2) ```json ... ``` 코드블록 안에 있으면 그 안만 parse
    3) 둘 다 실패 시 ClaudeCallError
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_FENCE_RE.search(text)
    if match:
        return json.loads(match.group(1))
    raise ClaudeCallError(f"no JSON block found in claude output: {text[:200]}")
