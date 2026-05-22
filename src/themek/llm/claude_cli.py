"""Claude Code CLI (claude -p) subprocess wrapper.

구독 기반 사용: ANTHROPIC_API_KEY 불필요. claude CLI가 사용자 인증된 상태여야 함.
"""
from __future__ import annotations
import json
import re
import subprocess
from typing import Any
from themek.config import get_settings


class ClaudeCallError(RuntimeError):
    pass


def call_claude(prompt: str, *, timeout_sec: int | None = None) -> str:
    """`claude -p <prompt> --output-format json` 호출 후 result 필드 텍스트 반환."""
    settings = get_settings()
    timeout = timeout_sec or settings.claude_cli_timeout_sec
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

    return payload["result"]


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
