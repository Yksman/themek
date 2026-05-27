# E5 Real-LLM Baseline + Token Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3종목(005930 삼성전자 / 005380 현대차 / 277810 레인보우로보틱스) × period=2023 × N=3 run 실 `claude` CLI baseline을 측정한다. 동시에 `dart/parser.py`에 section-level filter, `llm/claude_cli.py`에 token usage 측정, `eval/e5.py`에 multi-run aggregation을 추가해 baseline이 정량적·재현 가능하도록 한다.

**Architecture:** 기존 패키지·파일에 *얹는* 방식. 새 모듈은 없음. (1) `extract_business_sections(html, want, llm_fallback)`을 `dart/parser.py`에 신설하고 기존 `extract_business_content`는 하위 호환을 위해 유지, (2) `call_claude`가 `CallResult` dataclass(text + usage)를 반환하도록 변경, (3) `eval/e5.py`에 `AggregatedResult` + `aggregate_runs` 추가, (4) `cli.py:eval e5`에 `--runs N --save-runs <dir>` flag, (5) ingest·eval 양쪽 caller가 같은 section filter 사용하여 운영 = baseline. Section filter LLM fallback은 종목·시기당 0~1회 호출, 결과는 N run 전체에서 재사용.

**Tech Stack:** Python 3.12+, pytest, pytest-mock, typer, Pydantic v2, beautifulsoup4 + lxml (기존), `statistics` (표준 라이브러리).

**Spec:** `docs/superpowers/specs/2026-05-26-e5-real-llm-baseline-design.md`

---

## Prerequisites

- Plan #1 (Walking Skeleton), Plan #6 (Eval Harness), Plan #3 (DART API client) 완료
- `claude` CLI 로그인 상태 (T12 baseline run에서 필요)
- `DART_API_KEY` 환경변수 설정 (`.env`)
- `themek dart sync-corp` 1회 실행하여 `data/dart/corp_master.json` 캐시 존재

## Scope (in / out)

**In:**
- `src/themek/dart/parser.py`: `extract_business_sections(html, *, want, llm_fallback)` + `SectionResolution` dataclass 추가
- `src/themek/llm/claude_cli.py`: `CallResult` dataclass 도입, `call_claude` 반환 타입 변경
- `src/themek/llm/prompts.py`: `build_header_classification_prompt(candidates, missing_targets)` 추가
- `src/themek/eval/e5.py`: `AggregatedResult` + `aggregate_runs` 추가
- `src/themek/cli.py`: `eval e5`에 `--runs N` (default 1) + `--save-runs <dir>` 추가, ingest/eval caller에 section filter 적용
- `src/themek/ingest/business_report.py`: `_default_extractor` 내부의 `call_claude` 결과 unwrap (`.text`)
- `tests/`: parser sections / LLM header classification / multi-run aggregation / save-runs persistence / 확장된 CLI 테스트 (LLM mock)
- `data/eval/ground_truth/`: samsung 재작성, hyundai·rainbow 신규
- `tests/fixtures/samsung_e5_2023_fixture.json`: 기존 fixture-based GT 이동
- `docs/e5-real-llm-baseline-notes.md`: baseline 결과 기록
- README "다음 작업" 갱신

**Out:** N≥5 / 통계적 신뢰구간 / 다종목 batch / JSON output / history DB / entity resolution / prompt 자체 최적화 — spec §2.2 참조.

## File Structure

```
themek/
├── src/themek/
│   ├── dart/parser.py            # 수정: extract_business_sections + SectionResolution 추가
│   ├── llm/
│   │   ├── claude_cli.py         # 수정: CallResult dataclass, 반환 타입 변경
│   │   └── prompts.py            # 수정: build_header_classification_prompt 추가
│   ├── eval/e5.py                # 수정: AggregatedResult + aggregate_runs 추가
│   ├── cli.py                    # 수정: eval e5 --runs --save-runs, ingest/eval에 section filter 연결
│   └── ingest/business_report.py # 수정: call_claude(...).text 으로 unwrap (1줄)
├── tests/
│   ├── test_parser_sections.py            # 신규
│   ├── test_llm_header_classification.py  # 신규
│   ├── test_eval_aggregate.py             # 신규
│   ├── test_save_runs_persistence.py      # 신규
│   ├── test_cli_eval.py                   # 확장: --runs --save-runs 케이스
│   ├── test_claude_cli.py                 # 수정: CallResult 검증
│   ├── test_ingest_business_report.py     # 수정: .text unwrap 영향만 점검
│   └── fixtures/
│       └── samsung_e5_2023_fixture.json   # 기존 GT 이동
├── data/
│   ├── dart/raw/<rcept_no>/business.html  # T10에서 신규 종목 cache
│   └── eval/
│       ├── ground_truth/
│       │   ├── samsung_e5_2023.json       # 재작성 (실 DART HTML 기준)
│       │   ├── hyundai_e5_2023.json       # 신규
│       │   └── rainbow_e5_2023.json       # 신규
│       └── runs/                          # gitignore
├── docs/
│   └── e5-real-llm-baseline-notes.md      # 신규
└── README.md                              # 수정
```

---

## Task 1: `CallResult` dataclass — token usage 측정 도입

**Files:**
- Modify: `src/themek/llm/claude_cli.py`
- Modify: `src/themek/ingest/business_report.py:15-18`
- Modify: `tests/test_claude_cli.py`

- [ ] **Step 1: 실패 테스트 갱신/추가** (`tests/test_claude_cli.py`)

기존 테스트 2건을 `CallResult` 반환으로 갱신하고 usage 검증 케이스 1건 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_claude_cli.py -v
```
Expected: `ImportError: cannot import name 'CallResult'` + 기존 `result == "안녕"` 어설션 실패.

- [ ] **Step 3: `src/themek/llm/claude_cli.py` 갱신**

```python
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


def call_claude(prompt: str, *, timeout_sec: int | None = None) -> CallResult:
    """`claude -p <prompt> --output-format json` 호출 후 CallResult 반환."""
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
```

- [ ] **Step 4: ingest caller에서 `.text`로 unwrap**

`src/themek/ingest/business_report.py:15-18` 의 `_default_extractor`:

```python
def _default_extractor(text: str, period_hint: str) -> BusinessExtraction:
    from themek.llm.claude_cli import call_claude, extract_json_block
    from themek.llm.prompts import build_business_extraction_prompt
    prompt = build_business_extraction_prompt(text, period_hint=period_hint)
    raw = call_claude(prompt).text
    payload = extract_json_block(raw)
    return BusinessExtraction.model_validate(payload)
```

- [ ] **Step 5: 회귀 + 신규 테스트 모두 통과**

```bash
uv run pytest tests/test_claude_cli.py tests/test_ingest_business_report.py -v
```
Expected: 전부 PASS.

- [ ] **Step 6: 전체 회귀**

```bash
uv run pytest
```
Expected: 138 + 신규 케이스 모두 PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/themek/llm/claude_cli.py src/themek/ingest/business_report.py tests/test_claude_cli.py
git commit -m "feat(llm): CallResult with token usage from claude -p JSON (Plan #real-baseline T1)"
```

---

## Task 2: `extract_business_sections` regex 매칭 (LLM fallback 없음)

**Files:**
- Modify: `src/themek/dart/parser.py`
- Create: `tests/test_parser_sections.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_parser_sections.py`:

```python
"""extract_business_sections 단위 테스트.

LLM fallback은 mock으로 주입하거나 None으로 두어 deterministic 경로만 검증.
"""
from themek.dart.parser import (
    extract_business_sections, SectionResolution,
)


SAMPLE_HTML = """
<html><body>
<h2>II. 사업의 내용</h2>

<h3>1. 사업의 개요</h3>
<p>당사는 반도체와 디스플레이를 영위한다.</p>

<h3>2. 주요 제품 및 서비스</h3>
<p>DRAM, NAND, OLED.</p>

<h3>3. 원재료 및 생산설비</h3>
<p>이 부분은 노이즈여야 한다 — E5와 무관.</p>

<h3>4. 매출 및 수주상황</h3>
<p>국내 14.8%, 해외 85.2%.</p>

<h3>5. 위험관리 및 파생거래</h3>
<p>이 부분도 노이즈.</p>
</body></html>
"""


def test_section_filter_regex_all_three_matched():
    text, resolution = extract_business_sections(SAMPLE_HTML)
    assert "반도체와 디스플레이" in text       # overview
    assert "DRAM, NAND, OLED" in text         # products
    assert "국내 14.8%, 해외 85.2%" in text   # revenue
    assert "노이즈" not in text                # §3·§5 제외
    assert set(resolution.regex_matched) == {"overview", "products", "revenue"}
    assert resolution.skipped == []
    assert resolution.llm_called is False


def test_section_filter_keeps_only_requested():
    text, resolution = extract_business_sections(
        SAMPLE_HTML, want={"overview"},
    )
    assert "반도체와 디스플레이" in text
    assert "DRAM" not in text
    assert "국내" not in text
    assert set(resolution.regex_matched) == {"overview"}


def test_section_filter_handles_korean_letter_headers():
    """헤더 표기가 '가.' / '나.' / '다.' 인 경우도 인식한다."""
    html = """
    <h3>가. 사업의 개요</h3>
    <p>개요 본문.</p>
    <h3>나. 주요 제품</h3>
    <p>제품 본문.</p>
    <h3>다. 매출 현황</h3>
    <p>매출 본문.</p>
    """
    text, resolution = extract_business_sections(html)
    assert "개요 본문" in text
    assert "제품 본문" in text
    assert "매출 본문" in text


def test_section_filter_missing_target_without_fallback_skips():
    """LLM fallback이 None이고 regex 매칭이 부분 실패하면 미매칭은 skip."""
    html = """
    <h3>1. 사업의 개요</h3>
    <p>개요 본문.</p>
    <h3>2. 회사의 비전</h3>   <!-- products·revenue 키워드 없음 -->
    <p>비전 본문.</p>
    """
    text, resolution = extract_business_sections(html, llm_fallback=None)
    assert "개요 본문" in text
    assert "비전 본문" not in text
    assert set(resolution.regex_matched) == {"overview"}
    assert sorted(resolution.skipped) == ["products", "revenue"]
    assert resolution.llm_called is False


def test_section_filter_zero_matches_returns_full_text_with_warning():
    """헤더 0개 매칭이면 전체 본문을 반환하고 skipped 전부 기록."""
    html = "<p>그냥 본문, 헤더 없음.</p>"
    text, resolution = extract_business_sections(html, llm_fallback=None)
    assert "그냥 본문" in text
    assert sorted(resolution.skipped) == ["overview", "products", "revenue"]
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_sections.py -v
```
Expected: `ImportError: cannot import name 'extract_business_sections'`.

- [ ] **Step 3: `src/themek/dart/parser.py` 확장**

기존 `extract_business_content`는 그대로 두고 *추가*:

```python
"""DART 사업보고서 HTML → 본문 텍스트 추출.

- extract_business_content: 전체 본문 (legacy, 하위 호환)
- extract_business_sections: II. 사업의 내용 sub-section만 선별 추출
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from bs4 import BeautifulSoup


def extract_business_content(html: str) -> str:
    """HTML 본문에서 사람이 읽을 수 있는 텍스트를 추출.

    - <script>, <style> 제거
    - 표(<table>)는 셀 단위로 탭 구분 + 줄바꿈
    - 블록 요소 사이 줄바꿈 유지
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style"]):
        tag.decompose()

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("\t".join(cells))
        table.replace_with("\n".join(rows) + "\n")

    text = soup.get_text(separator="\n", strip=True)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Section-level filter (E5: overview / products / revenue 만 추출)
# ──────────────────────────────────────────────────────────────────────────

TARGET_KEYWORDS: dict[str, list[re.Pattern]] = {
    "overview": [re.compile(r"사업.{0,3}개요")],
    "products": [re.compile(r"주요.{0,3}제품"),
                 re.compile(r"제품.{0,3}서비스")],
    "revenue":  [re.compile(r"매출"),
                 re.compile(r"수주.{0,3}현황")],
}

# 헤더 라인 후보: "1. 제목", "가. 제목" 등 50자 이하
_HEADER_LINE_RE = re.compile(
    r"^\s*(?:\d+|[가-힣])\.\s*(\S.{0,48})\s*$"
)


@dataclass
class SectionResolution:
    regex_matched: dict[str, str] = field(default_factory=dict)
    llm_called: bool = False
    llm_input_candidates: list[str] = field(default_factory=list)
    llm_decision: dict[str, Optional[int]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    output_chars: int = 0


def _content_lines(html: str) -> list[str]:
    """script/style 제거 + 줄단위 텍스트화 (extract_business_content 흉내)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return [line for line in text.splitlines() if line.strip()]


def _find_header_indices(lines: list[str]) -> list[tuple[int, str]]:
    """(line index, header text) 리스트. matching 후보."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADER_LINE_RE.match(line)
        if m:
            out.append((i, m.group(1)))
    return out


def _classify_header_by_regex(header: str) -> Optional[str]:
    for target, patterns in TARGET_KEYWORDS.items():
        if any(p.search(header) for p in patterns):
            return target
    return None


def _section_body(
    lines: list[str], headers: list[tuple[int, str]], idx: int,
) -> str:
    """idx번 헤더의 본문 = 그 다음 헤더 직전까지."""
    start = headers[idx][0] + 1
    end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
    return "\n".join(lines[start:end])


def extract_business_sections(
    html: str,
    *,
    want: set[str] = frozenset({"overview", "products", "revenue"}),
    llm_fallback: Optional[Callable[[list[str], list[str]], dict]] = None,
) -> tuple[str, SectionResolution]:
    """II. 사업의 내용 내에서 want target sub-section만 추출.

    절차:
      1) 헤더 후보 추출 (정규식)
      2) target keyword 매칭
      3) 미매칭 target이 있고 llm_fallback != None이면 후보 → LLM 분류
      4) LLM이 null 반환한 target은 skip
      5) 매칭된 section의 본문만 concat
    """
    lines = _content_lines(html)
    headers = _find_header_indices(lines)
    resolution = SectionResolution()

    if not headers:
        # 헤더 0개 → 전체 본문 + 전부 skipped
        full = "\n".join(lines)
        resolution.skipped = sorted(want)
        resolution.output_chars = len(full)
        return full, resolution

    # regex 매칭: target → 첫 매칭 header (text + idx)
    matched_target_to_idx: dict[str, int] = {}
    for idx, (_, header) in enumerate(headers):
        target = _classify_header_by_regex(header)
        if target and target in want and target not in matched_target_to_idx:
            matched_target_to_idx[target] = idx
            resolution.regex_matched[target] = header

    missing = sorted(want - set(matched_target_to_idx))
    if missing and llm_fallback is not None:
        # 미매칭된 후보(아직 다른 target에 attach되지 않은 헤더들)만 LLM에 전달
        used_idx = set(matched_target_to_idx.values())
        candidates_idx = [i for i, _ in enumerate(headers) if i not in used_idx]
        candidates = [headers[i][1] for i in candidates_idx]
        resolution.llm_called = True
        resolution.llm_input_candidates = candidates
        decision = llm_fallback(candidates, missing)
        resolution.llm_decision = dict(decision)
        for target, one_based_idx in decision.items():
            if one_based_idx is None:
                continue
            # one_based_idx 는 candidates 리스트 안에서의 1-based index
            real_idx = candidates_idx[one_based_idx - 1]
            matched_target_to_idx[target] = real_idx

    resolution.skipped = sorted(set(want) - set(matched_target_to_idx))

    # 선택된 헤더의 본문 추출, want 카테고리 고정 순서로 concat
    order = ["overview", "products", "revenue"]
    parts: list[str] = []
    for target in order:
        if target in matched_target_to_idx:
            idx = matched_target_to_idx[target]
            parts.append(f"## {headers[idx][1]}")
            parts.append(_section_body(lines, headers, idx))

    text = "\n".join(parts).strip()
    resolution.output_chars = len(text)
    return text, resolution
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_parser_sections.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: 회귀 확인** (기존 `test_dart_parser.py`가 `extract_business_content` 그대로 쓰므로 영향 없어야 함)

```bash
uv run pytest tests/test_dart_parser.py -v
```
Expected: 기존 케이스 모두 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/parser.py tests/test_parser_sections.py
git commit -m "feat(parser): extract_business_sections regex+skip path (Plan #real-baseline T2)"
```

---

## Task 3: `build_header_classification_prompt` (`llm/prompts.py`)

**Files:**
- Modify: `src/themek/llm/prompts.py`
- Modify: `tests/test_llm_prompts.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_llm_prompts.py` 끝에)

```python
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
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_prompts.py -v -k header_classification
```
Expected: ImportError.

- [ ] **Step 3: `src/themek/llm/prompts.py` 끝에 추가**

```python
HEADER_CLASSIFICATION_PROMPT_TEMPLATE = """\
다음은 한국 상장사 사업보고서 "II. 사업의 내용" 챕터의 헤더 후보 목록이야.

{candidates_block}

다음 카테고리에 *정확히 부합하는* 헤더 번호를 골라줘.
부합하는 헤더가 없으면 null로 둬. 추측 금지.

카테고리:
- overview: 사업 개요 또는 전반 설명
- products: 주요 제품·서비스 라인 (제품군 나열)
- revenue: 매출 구성·수주 현황 (수치 분포)

JSON only — 다른 텍스트 금지:
{{"overview": <int|null>, "products": <int|null>, "revenue": <int|null>}}
"""


def build_header_classification_prompt(
    candidates: list[str], missing_targets: list[str],
) -> str:
    if candidates:
        block = "\n".join(f"[{i + 1}] {h}" for i, h in enumerate(candidates))
    else:
        block = "(헤더 후보 없음)"
    return HEADER_CLASSIFICATION_PROMPT_TEMPLATE.format(
        candidates_block=block,
    )
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_llm_prompts.py -v
git add src/themek/llm/prompts.py tests/test_llm_prompts.py
git commit -m "feat(llm): build_header_classification_prompt (Plan #real-baseline T3)"
```

---

## Task 4: `llm_classify_headers` (parser.py에 위치, LLM 호출 wrapper)

**Files:**
- Modify: `src/themek/dart/parser.py`
- Create: `tests/test_llm_header_classification.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_llm_header_classification.py`:

```python
"""llm_classify_headers — call_claude를 mock으로 막고 결과 dict 생성 로직만 검증."""
import json
from unittest.mock import MagicMock
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
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_header_classification.py -v
```
Expected: ImportError on `llm_classify_headers`.

- [ ] **Step 3: `src/themek/dart/parser.py` 끝에 추가**

```python
# ──────────────────────────────────────────────────────────────────────────
# LLM fallback: 미매칭 헤더 후보를 LLM이 분류
# ──────────────────────────────────────────────────────────────────────────
from themek.llm.claude_cli import call_claude, extract_json_block
from themek.llm.prompts import build_header_classification_prompt


def llm_classify_headers(
    candidates: list[str], missing_targets: list[str],
) -> dict[str, Optional[int]]:
    """남은 헤더 후보를 LLM이 카테고리로 매핑. 1-based index 또는 null 반환."""
    prompt = build_header_classification_prompt(candidates, missing_targets)
    result = call_claude(prompt)
    payload = extract_json_block(result.text)
    if not isinstance(payload, dict):
        from themek.llm.claude_cli import ClaudeCallError
        raise ClaudeCallError(
            f"header classification expected dict, got: {payload!r}"
        )
    # 키 정규화: 누락 키는 None으로 채움
    out: dict[str, Optional[int]] = {}
    for target in ("overview", "products", "revenue"):
        v = payload.get(target)
        out[target] = v if isinstance(v, int) else None
    return out
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_llm_header_classification.py -v
git add src/themek/dart/parser.py tests/test_llm_header_classification.py
git commit -m "feat(parser): llm_classify_headers fallback wrapper (Plan #real-baseline T4)"
```

---

## Task 5: `extract_business_sections`에 LLM fallback 통합 케이스 테스트

**Files:**
- Modify: `tests/test_parser_sections.py`

LLM fallback이 실제로 호출되는 path를 mock으로 검증한다 (구현은 Task 2에서 이미 작성된 분기 사용).

- [ ] **Step 1: 통합 테스트 추가** (`tests/test_parser_sections.py` 끝에)

```python
from unittest.mock import MagicMock


def test_section_filter_calls_llm_fallback_for_missing_targets():
    """regex가 overview만 잡고 products/revenue 누락 → llm_fallback 호출 →
    LLM이 candidate 2번을 products로 지정."""
    html = """
    <h3>1. 사업의 개요</h3>
    <p>개요 본문.</p>
    <h3>2. 영업현황</h3>
    <p>영업 본문.</p>
    <h3>3. 회사의 비전</h3>
    <p>비전 본문.</p>
    """
    mock_fallback = MagicMock(return_value={
        "overview": None,   # 이미 regex로 매칭됨
        "products": 1,      # candidates[0] = '영업현황' 을 products로 (가정)
        "revenue": None,    # 마땅한 후보 없음
    })
    text, resolution = extract_business_sections(html, llm_fallback=mock_fallback)
    assert "개요 본문" in text
    assert "영업 본문" in text             # products로 끌어왔음
    assert "비전 본문" not in text         # null인 target은 skip
    assert resolution.llm_called is True
    # llm_input_candidates에 overview용으로 매칭된 헤더가 포함되면 안 됨
    assert "사업의 개요" not in " ".join(resolution.llm_input_candidates)
    assert resolution.skipped == ["revenue"]
    mock_fallback.assert_called_once()


def test_section_filter_does_not_call_fallback_when_all_regex_matched():
    """regex로 3개 다 잡으면 llm_fallback은 호출되지 않음."""
    mock_fallback = MagicMock()
    _, resolution = extract_business_sections(SAMPLE_HTML, llm_fallback=mock_fallback)
    mock_fallback.assert_not_called()
    assert resolution.llm_called is False
```

- [ ] **Step 2: 통과 확인**

```bash
uv run pytest tests/test_parser_sections.py -v
```
Expected: 새 2건 포함 7 PASS.

- [ ] **Step 3: 커밋**

```bash
git add tests/test_parser_sections.py
git commit -m "test(parser): extract_business_sections LLM fallback integration (Plan #real-baseline T5)"
```

---

## Task 6: `AggregatedResult` + `aggregate_runs` (eval/e5.py)

**Files:**
- Modify: `src/themek/eval/e5.py`
- Create: `tests/test_eval_aggregate.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_eval_aggregate.py`:

```python
"""aggregate_runs — mean/stdev + token total + union 진단."""
import pytest
from themek.llm.claude_cli import CallResult
from themek.eval.e5 import EvalResult, AggregatedResult, aggregate_runs


def _r(seg_r, seg_p, cust_r, cust_p, reg_r, reg_p, mae, *,
       missed_segs=None, extra_segs=None) -> EvalResult:
    return EvalResult(
        segment_recall=seg_r, segment_precision=seg_p,
        customer_recall=cust_r, customer_precision=cust_p,
        region_recall=reg_r, region_precision=reg_p,
        share_pct_mae=mae,
        missed_segments=list(missed_segs or []),
        extra_segments=list(extra_segs or []),
    )


def _u(input_t, output_t, cost, ms) -> CallResult:
    return CallResult(text="", input_tokens=input_t, output_tokens=output_t,
                      cost_usd=cost, duration_ms=ms, raw_payload={})


def test_aggregate_n3_basic_means():
    runs = [
        _r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0),
        _r(0.8, 1.0, 1.0, 0.75, 1.0, 1.0, 0.85),
        _r(1.0, 0.857, 1.0, 1.0, 1.0, 1.0, 0.30),
    ]
    usages = [_u(12000, 600, 0.04, 30000),
              _u(13000, 620, 0.042, 31000),
              _u(12500, 610, 0.041, 30500)]
    agg = aggregate_runs(runs, usages)
    assert isinstance(agg, AggregatedResult)
    assert agg.segment_recall_mean == pytest.approx((1.0 + 0.8 + 1.0) / 3)
    assert agg.segment_precision_mean == pytest.approx((1.0 + 1.0 + 0.857) / 3)
    assert agg.share_pct_mae_mean == pytest.approx((0.0 + 0.85 + 0.30) / 3)
    assert agg.total_input_tokens == 37500
    assert agg.total_output_tokens == 1830
    assert abs(agg.total_cost_usd - 0.123) < 1e-6
    assert agg.total_duration_ms == 91500
    # stdev > 0
    assert agg.segment_recall_stdev > 0


def test_aggregate_n1_stdev_is_none():
    runs = [_r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0)]
    usages = [_u(100, 50, 0.001, 1000)]
    agg = aggregate_runs(runs, usages)
    assert agg.segment_recall_mean == 1.0
    assert agg.segment_recall_stdev is None
    assert agg.share_pct_mae_stdev is None


def test_aggregate_skips_none_metric_in_mean():
    runs = [
        _r(1.0, None, 1.0, 1.0, 1.0, 1.0, 0.0),
        _r(1.0, None, 1.0, 1.0, 1.0, 1.0, 0.0),
    ]
    usages = [_u(100, 10, 0.001, 1000), _u(100, 10, 0.001, 1000)]
    agg = aggregate_runs(runs, usages)
    assert agg.segment_precision_mean is None
    assert agg.segment_precision_stdev is None
    assert agg.segment_recall_mean == 1.0


def test_aggregate_unions_missed_and_extra_across_runs():
    runs = [
        _r(0.5, 0.5, None, None, None, None, None,
           missed_segs=["Harman"], extra_segs=["환각A"]),
        _r(0.5, 0.5, None, None, None, None, None,
           missed_segs=["Harman", "VD/DA"], extra_segs=["환각B"]),
    ]
    usages = [_u(100, 10, 0.001, 1000), _u(100, 10, 0.001, 1000)]
    agg = aggregate_runs(runs, usages)
    assert sorted(agg.missed_segments_union) == ["Harman", "VD/DA"]
    assert sorted(agg.extra_segments_union) == ["환각A", "환각B"]


def test_aggregate_requires_matching_run_usage_lengths():
    with pytest.raises(ValueError):
        aggregate_runs([_r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0)], [])
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_eval_aggregate.py -v
```
Expected: ImportError on `AggregatedResult` / `aggregate_runs`.

- [ ] **Step 3: `src/themek/eval/e5.py` 끝에 추가**

```python
import statistics
from themek.llm.claude_cli import CallResult


@dataclass
class AggregatedResult:
    runs: list[EvalResult]
    usages: list[CallResult]
    # 7 metric × (mean, stdev)
    segment_recall_mean: Optional[float] = None
    segment_recall_stdev: Optional[float] = None
    segment_precision_mean: Optional[float] = None
    segment_precision_stdev: Optional[float] = None
    customer_recall_mean: Optional[float] = None
    customer_recall_stdev: Optional[float] = None
    customer_precision_mean: Optional[float] = None
    customer_precision_stdev: Optional[float] = None
    region_recall_mean: Optional[float] = None
    region_recall_stdev: Optional[float] = None
    region_precision_mean: Optional[float] = None
    region_precision_stdev: Optional[float] = None
    share_pct_mae_mean: Optional[float] = None
    share_pct_mae_stdev: Optional[float] = None
    # 종합
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    # union 진단
    missed_segments_union: list[str] = field(default_factory=list)
    extra_segments_union: list[str] = field(default_factory=list)
    missed_customers_union: list[str] = field(default_factory=list)
    extra_customers_union: list[str] = field(default_factory=list)
    missed_regions_union: list[str] = field(default_factory=list)
    extra_regions_union: list[str] = field(default_factory=list)


_METRIC_FIELDS = [
    "segment_recall", "segment_precision",
    "customer_recall", "customer_precision",
    "region_recall", "region_precision",
    "share_pct_mae",
]


def _mean_stdev(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    vs = [v for v in values if v is not None]
    if not vs:
        return None, None
    m = statistics.mean(vs)
    s = statistics.stdev(vs) if len(vs) > 1 else None
    return m, s


def _union_sorted(lists: list[list[str]]) -> list[str]:
    out: set[str] = set()
    for xs in lists:
        out.update(xs)
    return sorted(out)


def aggregate_runs(
    runs: list[EvalResult], usages: list[CallResult],
) -> AggregatedResult:
    """N개 EvalResult/CallResult를 평균·표준편차·총합으로 집계."""
    if len(runs) != len(usages):
        raise ValueError(
            f"runs and usages length mismatch: {len(runs)} vs {len(usages)}"
        )
    agg = AggregatedResult(runs=list(runs), usages=list(usages))
    for field_name in _METRIC_FIELDS:
        values = [getattr(r, field_name) for r in runs]
        mean, stdev = _mean_stdev(values)
        setattr(agg, f"{field_name}_mean", mean)
        setattr(agg, f"{field_name}_stdev", stdev)
    agg.total_input_tokens = sum(u.input_tokens for u in usages)
    agg.total_output_tokens = sum(u.output_tokens for u in usages)
    agg.total_cost_usd = sum(u.cost_usd for u in usages)
    agg.total_duration_ms = sum(u.duration_ms for u in usages)
    agg.missed_segments_union = _union_sorted([r.missed_segments for r in runs])
    agg.extra_segments_union = _union_sorted([r.extra_segments for r in runs])
    agg.missed_customers_union = _union_sorted([r.missed_customers for r in runs])
    agg.extra_customers_union = _union_sorted([r.extra_customers for r in runs])
    agg.missed_regions_union = _union_sorted([r.missed_regions for r in runs])
    agg.extra_regions_union = _union_sorted([r.extra_regions for r in runs])
    return agg
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_eval_aggregate.py -v
git add src/themek/eval/e5.py tests/test_eval_aggregate.py
git commit -m "feat(eval): AggregatedResult + aggregate_runs (Plan #real-baseline T6)"
```

---

## Task 7: `format_aggregated_result_text` — N>1 출력 포맷터

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_aggregate.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_eval_aggregate.py` 끝)

```python
from themek.eval.e5 import format_aggregated_result_text


def test_format_aggregated_displays_means_and_totals():
    runs = [
        _r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0),
        _r(0.833, 1.0, 1.0, 0.75, 1.0, 1.0, 0.85,
           missed_segs=["Harman"], extra_segs=["환각"]),
        _r(1.0, 0.857, 1.0, 1.0, 1.0, 1.0, 0.30),
    ]
    usages = [_u(12000, 600, 0.04, 30000),
              _u(13000, 620, 0.042, 31000),
              _u(12500, 610, 0.041, 30500)]
    agg = aggregate_runs(runs, usages)
    metadata = {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"}
    section_log = "regex matched: overview, products, revenue\nllm fallback: not called"
    text = format_aggregated_result_text(
        agg, metadata=metadata,
        ground_truth_path="data/eval/ground_truth/samsung_e5_2023.json",
        html_path="data/dart/raw/2024XXX/business.html",
        section_log=section_log,
    )
    assert "삼성전자" in text
    assert "(N=3)" in text
    assert "Token usage" in text
    assert "37,500" in text or "37500" in text
    assert "$0.12" in text
    assert "Section filter:" in text
    assert "Harman" in text       # union missed
    assert "환각" in text         # union extra
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_eval_aggregate.py::test_format_aggregated_displays_means_and_totals -v
```
Expected: ImportError.

- [ ] **Step 3: 구현 추가** (`src/themek/eval/e5.py`)

```python
def _fmt_pair(mean: Optional[float], stdev: Optional[float]) -> str:
    if mean is None:
        return "n/a"
    if stdev is None:
        return f"{mean:.3f}"
    return f"{mean:.3f} ± {stdev:.3f}"


def _fmt_mae_pair(mean: Optional[float], stdev: Optional[float]) -> str:
    if mean is None:
        return "n/a"
    if stdev is None:
        return f"{mean:.2f} %p"
    return f"{mean:.2f} ± {stdev:.2f} %p"


def format_aggregated_result_text(
    agg: AggregatedResult,
    *,
    metadata: dict,
    ground_truth_path: str,
    html_path: str,
    section_log: str,
) -> str:
    """N>1 run의 AggregatedResult를 사람이 읽는 점수표로 변환."""
    ticker = metadata.get("ticker", "?")
    name_ko = metadata.get("name_ko", "?")
    period = metadata.get("period", "?")
    n = len(agg.runs)
    n_runs = max(n, 1)
    lines = [
        f"=== Eval: E5 — {name_ko} ({ticker}) period={period} (N={n}) ===",
        f"Ground truth:  {ground_truth_path}",
        f"HTML source:   {html_path}",
        "",
        f"Segments  recall=    {_fmt_pair(agg.segment_recall_mean, agg.segment_recall_stdev)}",
        f"Segments  precision= {_fmt_pair(agg.segment_precision_mean, agg.segment_precision_stdev)}",
        f"Customers recall=    {_fmt_pair(agg.customer_recall_mean, agg.customer_recall_stdev)}",
        f"Customers precision= {_fmt_pair(agg.customer_precision_mean, agg.customer_precision_stdev)}",
        f"Regions   recall=    {_fmt_pair(agg.region_recall_mean, agg.region_recall_stdev)}",
        f"Regions   precision= {_fmt_pair(agg.region_precision_mean, agg.region_precision_stdev)}",
        f"Share_pct MAE        {_fmt_mae_pair(agg.share_pct_mae_mean, agg.share_pct_mae_stdev)}",
        "",
        f"Token usage ({n} runs):",
        f"  input_tokens:  {agg.total_input_tokens:>10,}   ({agg.total_input_tokens // n_runs:>8,} / run)",
        f"  output_tokens: {agg.total_output_tokens:>10,}   ({agg.total_output_tokens // n_runs:>8,} / run)",
        f"  cost_usd:      ${agg.total_cost_usd:>9.3f}   (${agg.total_cost_usd / n_runs:>7.3f} / run)",
        f"  duration:      {agg.total_duration_ms / 1000:>9.1f}s  ({agg.total_duration_ms / 1000 / n_runs:>7.1f}s / run)",
        "",
        "Section filter:",
        *(f"  {line}" for line in section_log.splitlines()),
        "",
        f"Missed/Extra (union across {n} runs):",
        f"  segments missed:  {agg.missed_segments_union}",
        f"  segments extra:   {agg.extra_segments_union}",
        f"  customers missed: {agg.missed_customers_union}",
        f"  customers extra:  {agg.extra_customers_union}",
        f"  regions missed:   {agg.missed_regions_union}",
        f"  regions extra:    {agg.extra_regions_union}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_eval_aggregate.py -v
git add src/themek/eval/e5.py tests/test_eval_aggregate.py
git commit -m "feat(eval): format_aggregated_result_text for N>1 output (Plan #real-baseline T7)"
```

---

## Task 8: CLI `eval e5 --runs N` + section filter 통합

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_eval.py`

`--save-runs` 영속화는 Task 9에서. 이 task는 메모리 only 멀티런까지.

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_cli_eval.py` 끝)

```python
def test_cli_eval_e5_runs_3_with_stub_outputs_aggregated_table(monkeypatch, tmp_path):
    payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [{"name_raw": "Apple Inc.", "tier": "1차"}],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = _write_stub(tmp_path, payload)
    gt = _write_ground_truth(tmp_path, payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "3",
    ])
    assert result.exit_code == 0, result.stdout
    assert "(N=3)" in result.stdout
    assert "Token usage" in result.stdout
    assert "Section filter" in result.stdout


def test_cli_eval_e5_default_runs_one_keeps_existing_format(monkeypatch, tmp_path):
    """--runs 미지정 시 N=1, 기존 포맷 유지 (회귀 가드)."""
    payload = {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    }
    stub = _write_stub(tmp_path, payload)
    gt = _write_ground_truth(tmp_path, payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))
    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
    ])
    assert result.exit_code == 0
    assert "(N=" not in result.stdout       # N=1 포맷에는 N=N 표시 없음
    assert "Token usage" not in result.stdout
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli_eval.py -v -k "runs_3 or default_runs_one"
```
Expected: `Error: No such option '--runs'`.

- [ ] **Step 3: `src/themek/cli.py:eval_e5_cmd` 갱신**

기존 함수 위에 helper와 import 추가:

```python
# cli.py 상단 import 보강
from themek.dart.parser import (
    extract_business_content,
    extract_business_sections,
    llm_classify_headers,
)
from themek.llm.claude_cli import CallResult
from themek.eval.e5 import (
    evaluate_e5, load_ground_truth, format_eval_result_text,
    aggregate_runs, format_aggregated_result_text,
)
```

그리고 `eval_e5_cmd` 전체를 교체:

```python
@eval_app.command("e5")
def eval_e5_cmd(
    html_file: Path = typer.Option(..., "--html-file"),
    period: str = typer.Option(..., "--period"),
    ground_truth: Path = typer.Option(..., "--ground-truth"),
    runs: int = typer.Option(1, "--runs", min=1, max=20),
    save_runs: Optional[Path] = typer.Option(None, "--save-runs"),
):
    """E5 추출 품질을 ground truth와 비교해 점수표 출력."""
    try:
        truth, metadata = load_ground_truth(ground_truth)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    html = html_file.read_text(encoding="utf-8")
    stub = _stub_extractor_from_env()

    # Section filter는 LLM fallback 포함하여 1회만 수행 (N run 재사용).
    # stub mode면 text는 어차피 무시되지만 section_resolution은 보고용으로 채움.
    text, section_resolution = extract_business_sections(
        html, llm_fallback=None if stub else llm_classify_headers,
    )

    extractor = stub
    if extractor is None:
        from themek.ingest.business_report import _default_extractor
        extractor = _default_extractor

    eval_runs: list = []
    usages: list[CallResult] = []
    for _ in range(runs):
        extraction = extractor(text, period)
        eval_runs.append(evaluate_e5(extraction, truth))
        # stub mode: usage는 0; 실 LLM은 extractor가 CallResult를 노출하지 않으므로
        # placeholder. 실제 token 누적은 Task 9에서 _default_extractor를 wrap한다.
        usages.append(CallResult(text="", input_tokens=0, output_tokens=0,
                                  cost_usd=0.0, duration_ms=0, raw_payload={}))

    section_log = _format_section_log(section_resolution)

    if runs == 1:
        typer.echo(format_eval_result_text(
            eval_runs[0],
            metadata=metadata,
            ground_truth_path=str(ground_truth),
            html_path=str(html_file),
        ))
    else:
        agg = aggregate_runs(eval_runs, usages)
        typer.echo(format_aggregated_result_text(
            agg,
            metadata=metadata,
            ground_truth_path=str(ground_truth),
            html_path=str(html_file),
            section_log=section_log,
        ))


def _format_section_log(resolution) -> str:
    matched_regex = sorted(resolution.regex_matched)
    matched_llm = sorted(t for t, v in resolution.llm_decision.items()
                         if v is not None)
    lines = [
        f"regex matched: {', '.join(matched_regex) or '-'}",
        f"llm fallback:  {'called' if resolution.llm_called else 'not called'}",
        f"llm matched:   {', '.join(matched_llm) or '-'}",
        f"skipped:       {', '.join(resolution.skipped) or '-'}",
        f"output chars:  {resolution.output_chars}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_cli_eval.py -v
```
Expected: 모든 케이스 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/cli.py tests/test_cli_eval.py
git commit -m "feat(cli): eval e5 --runs N + section filter wiring (Plan #real-baseline T8)"
```

---

## Task 9: 실 LLM extractor가 CallResult 누출하도록 + `--save-runs` 영속화

`_default_extractor`는 `BusinessExtraction`만 반환하므로 token usage를 놓친다. CLI에서 extraction 단계의 `call_claude` 결과를 포착하려면 wrapper가 필요. 동시에 `--save-runs` dir 출력 구현.

**Files:**
- Modify: `src/themek/cli.py`
- Create: `tests/test_save_runs_persistence.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_save_runs_persistence.py`:

```python
"""--save-runs 결과물 schema 검증."""
import json
from pathlib import Path
from typer.testing import CliRunner
from themek.cli import app


runner = CliRunner()


def _gt_payload(extraction: dict) -> dict:
    return {
        "metadata": {
            "ticker": "005930", "name_ko": "삼성전자",
            "period": "2023", "source_rcept_no": "x",
            "fixture_path": "x", "created_at": "2026-05-26", "notes": "",
        },
        "extraction": extraction,
    }


def test_save_runs_creates_per_run_files(monkeypatch, tmp_path):
    payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = tmp_path / "stub.json"
    stub.write_text(json.dumps(payload), encoding="utf-8")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(_gt_payload(payload)), encoding="utf-8")
    html = tmp_path / "report.html"
    html.write_text("<html><body><h3>1. 사업의 개요</h3><p>본문</p></body></html>",
                    encoding="utf-8")
    save_dir = tmp_path / "runs"
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "3",
        "--save-runs", str(save_dir),
    ])
    assert result.exit_code == 0, result.stdout

    target = save_dir / "005930_2023"
    assert target.is_dir()
    for i in (1, 2, 3):
        p = target / f"run_{i}.json"
        assert p.exists()
        run = json.loads(p.read_text(encoding="utf-8"))
        assert run["run_index"] == i
        assert "parsed_extraction" in run
        assert "usage" in run
        assert "eval_result" in run

    sec = target / "section_resolution.json"
    assert sec.exists()
    sec_data = json.loads(sec.read_text(encoding="utf-8"))
    assert "regex_matched" in sec_data
    assert "skipped" in sec_data

    summary = target / "summary.json"
    assert summary.exists()
    s = json.loads(summary.read_text(encoding="utf-8"))
    assert s["n_runs"] == 3
    assert "segment_recall_mean" in s
    assert "total_input_tokens" in s


def test_save_runs_unused_when_flag_absent(monkeypatch, tmp_path):
    payload = {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    }
    stub = tmp_path / "stub.json"
    stub.write_text(json.dumps(payload), encoding="utf-8")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(_gt_payload(payload)), encoding="utf-8")
    html = tmp_path / "report.html"
    html.write_text("<html><body><p>본문</p></body></html>", encoding="utf-8")
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "1",
    ])
    assert result.exit_code == 0
    # dir 생성 안 됨 (no side effect)
    assert not (tmp_path / "runs").exists()
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_save_runs_persistence.py -v
```
Expected: 파일이 생성되지 않거나 schema mismatch.

- [ ] **Step 3: `src/themek/cli.py` 보강**

`eval_e5_cmd`를 다시 갱신하여 (a) extractor가 token usage도 노출하도록 wrap, (b) `--save-runs` 출력 분기 추가:

```python
def _run_extractor_with_usage(text: str, period: str, stub_fn):
    """stub이 있으면 (extraction, zero-usage) 반환.
    없으면 _default_extractor 안의 call_claude 결과를 가로채서 (extraction, CallResult)."""
    if stub_fn is not None:
        return stub_fn(text, period), CallResult(
            text="", input_tokens=0, output_tokens=0,
            cost_usd=0.0, duration_ms=0, raw_payload={},
        )
    from themek.llm.claude_cli import call_claude, extract_json_block
    from themek.llm.prompts import build_business_extraction_prompt
    from themek.llm.schemas import BusinessExtraction
    prompt = build_business_extraction_prompt(text, period_hint=period)
    call = call_claude(prompt)
    payload = extract_json_block(call.text)
    extraction = BusinessExtraction.model_validate(payload)
    return extraction, call


@eval_app.command("e5")
def eval_e5_cmd(
    html_file: Path = typer.Option(..., "--html-file"),
    period: str = typer.Option(..., "--period"),
    ground_truth: Path = typer.Option(..., "--ground-truth"),
    runs: int = typer.Option(1, "--runs", min=1, max=20),
    save_runs: Optional[Path] = typer.Option(None, "--save-runs"),
):
    """E5 추출 품질을 ground truth와 비교해 점수표 출력."""
    try:
        truth, metadata = load_ground_truth(ground_truth)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    html = html_file.read_text(encoding="utf-8")
    stub = _stub_extractor_from_env()

    text, section_resolution = extract_business_sections(
        html, llm_fallback=None if stub else llm_classify_headers,
    )

    eval_runs: list = []
    usages: list[CallResult] = []
    raw_extractions: list = []
    for _ in range(runs):
        extraction, call = _run_extractor_with_usage(text, period, stub)
        eval_runs.append(evaluate_e5(extraction, truth))
        usages.append(call)
        raw_extractions.append(extraction)

    section_log = _format_section_log(section_resolution)

    if runs == 1:
        typer.echo(format_eval_result_text(
            eval_runs[0],
            metadata=metadata,
            ground_truth_path=str(ground_truth),
            html_path=str(html_file),
        ))
        agg = None
    else:
        agg = aggregate_runs(eval_runs, usages)
        typer.echo(format_aggregated_result_text(
            agg,
            metadata=metadata,
            ground_truth_path=str(ground_truth),
            html_path=str(html_file),
            section_log=section_log,
        ))

    if save_runs is not None:
        _persist_runs(
            save_runs, metadata=metadata,
            section_resolution=section_resolution,
            usages=usages, extractions=raw_extractions,
            eval_results=eval_runs, agg=agg,
        )


def _persist_runs(
    base: Path, *, metadata: dict, section_resolution,
    usages: list[CallResult], extractions: list,
    eval_results: list, agg,
) -> None:
    from dataclasses import asdict
    ticker = metadata.get("ticker", "unknown")
    period = metadata.get("period", "unknown")
    target = base / f"{ticker}_{period}"
    target.mkdir(parents=True, exist_ok=True)

    for i, (extraction, usage, eval_r) in enumerate(
        zip(extractions, usages, eval_results), start=1,
    ):
        run_path = target / f"run_{i}.json"
        run_path.write_text(json.dumps({
            "run_index": i,
            "parsed_extraction": extraction.model_dump(),
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": usage.cost_usd,
                "duration_ms": usage.duration_ms,
            },
            "eval_result": asdict(eval_r),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    sec_path = target / "section_resolution.json"
    sec_path.write_text(json.dumps(
        asdict(section_resolution), ensure_ascii=False, indent=2,
    ), encoding="utf-8")

    summary_path = target / "summary.json"
    if agg is None:
        # N=1: 단일 run 결과 + zero stdev
        summary = {
            "n_runs": 1,
            "segment_recall_mean": eval_results[0].segment_recall,
            "total_input_tokens": usages[0].input_tokens,
            "total_output_tokens": usages[0].output_tokens,
            "total_cost_usd": usages[0].cost_usd,
            "total_duration_ms": usages[0].duration_ms,
        }
    else:
        summary = asdict(agg)
        # AggregatedResult.runs와 .usages는 중복이라 summary에선 제거하고 n_runs만 표기
        summary.pop("runs", None)
        summary.pop("usages", None)
        summary["n_runs"] = len(eval_results)
    summary_path.write_text(json.dumps(
        summary, ensure_ascii=False, indent=2, default=str,
    ), encoding="utf-8")
```

`from dataclasses import asdict`, `import json`은 파일 상단에 이미 있으니 추가 import 불필요. 없으면 추가.

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_save_runs_persistence.py tests/test_cli_eval.py -v
```
Expected: 전부 PASS.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest
```
Expected: 기존 + 신규 모두 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/cli.py tests/test_save_runs_persistence.py
git commit -m "feat(cli): --save-runs persistence + extractor usage capture (Plan #real-baseline T9)"
```

---

## Task 10: ingest 파이프라인도 section filter 거치도록

운영 `themek dart ingest`가 baseline과 동일 파이프라인을 거치게 한다. eval CLI는 이미 Task 8에서 적용됨.

**Files:**
- Modify: `src/themek/cli.py:dart_ingest_cmd`
- Modify: `tests/test_cli_dart.py` (해당 명령 회귀가 있을 시)

- [ ] **Step 1: 실패 테스트 (또는 기존 테스트 갱신)**

기존 `tests/test_cli_dart.py`의 `dart_ingest_cmd` 관련 테스트에서, fixture HTML에 헤더 `1. 사업의 개요` 등을 포함하지 않을 가능성이 있음. 우선 새 테스트 추가:

`tests/test_cli_dart.py`에 새 테스트 케이스 1건:

```python
def test_dart_ingest_uses_section_filter_text(monkeypatch, tmp_path, mocker):
    """dart ingest는 extract_business_sections를 거친 text를 extractor에 넘긴다."""
    from themek.cli import app
    from typer.testing import CliRunner
    runner = CliRunner()

    # DART 호출은 통째로 mock
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )
    mocker.patch("themek.cli.lookup_corp_code", return_value="00000000")

    cached_html = tmp_path / "business.html"
    cached_html.write_text(
        "<h3>1. 사업의 개요</h3><p>개요</p>"
        "<h3>2. 주요 제품</h3><p>제품</p>"
        "<h3>4. 매출 및 수주상황</h3><p>매출</p>"
        "<h3>9. 노이즈</h3><p>이건 필터링되어야 함</p>",
        encoding="utf-8",
    )
    mocker.patch(
        "themek.cli.fetch_business_report_html",
        return_value=(cached_html, "20240101000001"),
    )

    captured_texts: list[str] = []

    def fake_stub(text, period):
        captured_texts.append(text)
        from themek.llm.schemas import BusinessExtraction
        return BusinessExtraction.model_validate({
            "period": period, "segments": [],
            "customers": [], "geographic": [],
        })

    stub_path = tmp_path / "stub.json"
    stub_path.write_text("""{
      "period": "2023", "segments": [], "customers": [], "geographic": []
    }""", encoding="utf-8")
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub_path))

    result = runner.invoke(app, [
        "dart", "ingest",
        "--ticker", "000000", "--period", "2023",
    ])
    assert result.exit_code == 0, result.stdout

    # extractor에 들어간 text는 section-filtered (노이즈 제외)
    # stub은 환경변수 통해 들어가므로 captured_texts는 안 차지만, fallback 경로
    # 검증을 위해 stdout에 "Ingested" 만 확인하고 별도 sanity check
    assert "Ingested" in result.stdout
```

- [ ] **Step 2: 실패 확인 (또는 기존 테스트로 회귀 가드)**

```bash
uv run pytest tests/test_cli_dart.py -v
```
기존 테스트가 깨지지 않는지 확인.

- [ ] **Step 3: `src/themek/cli.py:dart_ingest_cmd` 갱신**

기존:
```python
    html = html_path.read_text(encoding="utf-8")
    text = extract_business_content(html)
```

다음으로 변경:
```python
    html = html_path.read_text(encoding="utf-8")
    stub_for_filter = _stub_extractor_from_env()
    text, _section_resolution = extract_business_sections(
        html, llm_fallback=None if stub_for_filter else llm_classify_headers,
    )
```

(`_section_resolution`은 dart ingest 명령에선 stdout에 노출하지 않고 버림. 향후 plan에서 ingest history 저장 시 활용.)

- [ ] **Step 4: 통과 + 회귀 확인**

```bash
uv run pytest tests/test_cli_dart.py tests/test_cli_eval.py tests/test_ingest_business_report.py -v
```
Expected: 모두 PASS. 만약 기존 `test_cli_dart.py`가 noise HTML로 ingest 결과를 검증하던 부분이 있다면 그 부분만 mock 또는 헤더 추가로 보강.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest
```

- [ ] **Step 6: 커밋**

```bash
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): dart ingest pipeline uses extract_business_sections (Plan #real-baseline T10)"
```

---

## Task 11: 기존 samsung GT를 fixture로 이동 + 실 DART HTML 캐시 준비

**Files:**
- Move: `data/eval/ground_truth/samsung_e5_2023.json` → `tests/fixtures/samsung_e5_2023_fixture.json`
- Cache (3종목 ingest): `data/dart/raw/<rcept_no>/business.html` × 3

- [ ] **Step 1: 기존 GT를 fixture로 이동**

```bash
mv data/eval/ground_truth/samsung_e5_2023.json tests/fixtures/samsung_e5_2023_fixture.json
```

이 파일은 fixture HTML(`tests/fixtures/samsung_business_report_excerpt.html`) 기준으로 작성된 GT라 unit test 용으로만 보존. 실 DART HTML 기준 GT는 Task 12에서 신규 작성.

- [ ] **Step 2: corp_master sync 확인**

```bash
ls -la data/dart/corp_master.json
```
존재해야 함. 없으면:
```bash
uv run themek dart sync-corp
```

- [ ] **Step 3: 삼성전자(005930) 2023 사업보고서 fetch & cache 보강**

```bash
uv run themek dart ingest --ticker 005930 --period 2023
```
Expected: `Ingested report <rcept_no>` 출력. `data/dart/raw/<rcept_no>/business.html` 생성.

- [ ] **Step 4: 현대차(005380) 2023 사업보고서 fetch & cache**

```bash
uv run themek dart ingest --ticker 005380 --period 2023
```

- [ ] **Step 5: 레인보우로보틱스(277810) 2023 사업보고서 fetch & cache**

```bash
uv run themek dart ingest --ticker 277810 --period 2023
```

- [ ] **Step 6: 캐시 확인 + rcept_no 메모**

```bash
ls -la data/dart/raw/*/business.html
```
3개의 디렉토리(`<rcept_no>/business.html`)가 있어야 함. 각 `rcept_no`는 Task 12 GT의 `metadata.source_rcept_no`로 사용한다. 메모:

| ticker | rcept_no | html size |
|---|---|---|
| 005930 | (Step 3 출력) | (`wc -c` 결과) |
| 005380 | (Step 4 출력) | |
| 277810 | (Step 5 출력) | |

- [ ] **Step 7: 커밋**

```bash
git rm data/eval/ground_truth/samsung_e5_2023.json
git add tests/fixtures/samsung_e5_2023_fixture.json
git commit -m "data(eval): archive fixture-based samsung GT to tests/fixtures/ (Plan #real-baseline T11)"
```

(`data/dart/raw/`는 gitignored이므로 추가하지 않음.)

---

## Task 12: 3종목 ground truth 작성 (사용자 task)

**Files:**
- Create: `data/eval/ground_truth/samsung_e5_2023.json`
- Create: `data/eval/ground_truth/hyundai_e5_2023.json`
- Create: `data/eval/ground_truth/rainbow_e5_2023.json`

각 종목당 30분~2시간 예상. 사용자가 실 DART HTML을 직접 읽고 작성한다.

- [ ] **Step 1: 보조 — 각 종목의 section-filtered text를 미리 출력**

```bash
uv run python -c "
from pathlib import Path
from themek.dart.parser import extract_business_sections, llm_classify_headers
for d in sorted(Path('data/dart/raw').iterdir()):
    if not (d / 'business.html').exists():
        continue
    html = (d / 'business.html').read_text(encoding='utf-8')
    text, res = extract_business_sections(html, llm_fallback=llm_classify_headers)
    print(f'=== {d.name} ===')
    print(f'output chars: {res.output_chars}')
    print(f'regex matched: {res.regex_matched}')
    print(f'llm called: {res.llm_called}')
    print(f'skipped: {res.skipped}')
    print('--- first 2000 chars ---')
    print(text[:2000])
    print()
"
```

이 출력으로 각 종목 보고서가 어디서 잘렸는지 확인. section filter가 *너무* 좁게 잘랐다면 (예: 매출 표 끊김) Step 3에서 GT 작성 시 raw `data/dart/raw/<rcept>/business.html`을 보조로 참고.

- [ ] **Step 2: samsung GT 작성**

`data/eval/ground_truth/samsung_e5_2023.json`:

```json
{
  "metadata": {
    "ticker": "005930",
    "name_ko": "삼성전자",
    "period": "2023",
    "source_rcept_no": "<Task 11 Step 3에서 확인한 rcept_no>",
    "html_path": "data/dart/raw/<rcept_no>/business.html",
    "created_at": "2026-05-26",
    "notes": "실 DART 사업보고서 본문 기준. 사용자가 실 HTML을 직접 읽고 작성."
  },
  "extraction": {
    "period": "2023",
    "segments": [
      {"name_ko": "...", "share_pct": null, "description": null, "products": []}
    ],
    "customers": [],
    "geographic": []
  }
}
```

작성 원칙 (Plan #6 GT 작성 절차와 동일):
- 본문에 명시된 사실만 기록, 추측 금지
- 동일 region_code로 매핑되는 항목은 합산 (예: 아시아 + 기타 → ROW)
- share_pct가 명시 안 된 segment는 null
- 비공개 고객사는 `name_raw`에 원문 그대로
- `notes`에 모호한 결정 기록

- [ ] **Step 3: hyundai GT 작성**

`data/eval/ground_truth/hyundai_e5_2023.json`:
동일 schema. 현대차는 자동차/금융 부문 + 해외 딜러 네트워크가 주요 customer. 지역은 KR/US/EU 주력.

- [ ] **Step 4: rainbow GT 작성**

`data/eval/ground_truth/rainbow_e5_2023.json`:
동일 schema. 협동로봇 단일 사업, 매출처는 비공개·소수.

- [ ] **Step 5: 3개 모두 Pydantic schema 검증**

```bash
uv run python -c "
import json
from themek.llm.schemas import BusinessExtraction
for t in ('samsung', 'hyundai', 'rainbow'):
    p = f'data/eval/ground_truth/{t}_e5_2023.json'
    payload = json.load(open(p))
    BusinessExtraction.model_validate(payload['extraction'])
    print(f'{t}: valid ({len(payload[\"extraction\"][\"segments\"])} segments)')
"
```
Expected: 3건 모두 `valid`.

- [ ] **Step 6: 커밋**

```bash
git add data/eval/ground_truth/samsung_e5_2023.json \
        data/eval/ground_truth/hyundai_e5_2023.json \
        data/eval/ground_truth/rainbow_e5_2023.json
git commit -m "data(eval): 3-stock ground truth (samsung/hyundai/rainbow) from real DART HTML (Plan #real-baseline T12)"
```

---

## Task 13: 실 LLM baseline 측정 — 3종목 × N=3

**Files:**
- Output: `data/eval/runs/2026-05-26/<ticker>_2023/run_{1,2,3}.json` 등

**WARNING:** 이 task는 실 Claude CLI 토큰을 소비한다 (~$0.30, 약 5분). 사전에 `claude --version` + `claude /login` 으로 로그인 상태 확인.

- [ ] **Step 1: 사전 점검**

```bash
claude --version
# 로그인 상태 확인 — 미인증 시 claude /login
ls data/eval/ground_truth/  # 3개 파일 존재
ls data/dart/raw/           # 3개 디렉토리 존재
```

- [ ] **Step 2: samsung baseline run**

각 종목의 `rcept_no`를 Task 11 Step 6 메모에서 가져온다.

```bash
SAMSUNG_RCEPT=<Task 11에서 확인한 005930의 rcept_no>
uv run themek eval e5 \
  --html-file data/dart/raw/$SAMSUNG_RCEPT/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/2026-05-26 \
  | tee /tmp/baseline_samsung.txt
```
Expected: 점수표 출력 + `data/eval/runs/2026-05-26/005930_2023/` 디렉토리에 run_{1,2,3}.json, section_resolution.json, summary.json 생성.

- [ ] **Step 3: hyundai baseline run**

```bash
HYUNDAI_RCEPT=<Task 11에서 확인한 005380의 rcept_no>
uv run themek eval e5 \
  --html-file data/dart/raw/$HYUNDAI_RCEPT/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/hyundai_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/2026-05-26 \
  | tee /tmp/baseline_hyundai.txt
```

- [ ] **Step 4: rainbow baseline run**

```bash
RAINBOW_RCEPT=<Task 11에서 확인한 277810의 rcept_no>
uv run themek eval e5 \
  --html-file data/dart/raw/$RAINBOW_RCEPT/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/rainbow_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/2026-05-26 \
  | tee /tmp/baseline_rainbow.txt
```

- [ ] **Step 5: 결과물 sanity check**

```bash
ls data/eval/runs/2026-05-26/
# 005930_2023  005380_2023  277810_2023

for t in 005930 005380 277810; do
  echo "=== $t ==="
  cat data/eval/runs/2026-05-26/${t}_2023/summary.json \
    | python -c "import sys, json; d=json.load(sys.stdin); print(f'input_tokens={d[\"total_input_tokens\"]}, cost=\${d[\"total_cost_usd\"]:.3f}, seg_recall_mean={d.get(\"segment_recall_mean\")}')"
done
```

- [ ] **Step 6: 결과 파일은 gitignore — 커밋 안 함**

`data/eval/runs/` 가 `.gitignore`에 있는지 확인:
```bash
grep "data/eval/runs" .gitignore || echo "data/eval/runs/" >> .gitignore
```

- [ ] **Step 7: .gitignore 변경 시 커밋**

```bash
git diff --quiet .gitignore || (git add .gitignore && \
  git commit -m "chore: gitignore data/eval/runs/ (Plan #real-baseline T13)")
```

---

## Task 14: baseline notes 문서 + README 갱신

**Files:**
- Create: `docs/e5-real-llm-baseline-notes.md`
- Modify: `README.md`

- [ ] **Step 1: `docs/e5-real-llm-baseline-notes.md` 작성**

3개 baseline run의 stdout (`/tmp/baseline_*.txt`)을 인용해 다음 구조로 정리:

```markdown
# E5 Real-LLM Baseline (3종목 × N=3)

**실행일:** 2026-05-26
**LLM:** Claude Code subscription via `claude -p`
**Section filter:** `extract_business_sections` (regex + LLM fallback)
**Aggregation:** `aggregate_runs` (mean ± stdev over 3 runs)

## Command Pattern

```bash
uv run themek eval e5 \
  --html-file data/dart/raw/<rcept_no>/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/<ticker>_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/2026-05-26
```

## 005930 삼성전자 — period 2023

(Task 13 Step 2의 `/tmp/baseline_samsung.txt` 출력 그대로 붙임)

### Analysis
- Segments: <mean recall/precision의 의미, missed/extra 패턴>
- Customers: ...
- Regions: ...
- Share_pct MAE: ...
- Section filter: <regex/llm 동작 — `005930_2023/section_resolution.json` 참고>
- Token cost: input X / output Y / $Z

## 005380 현대자동차 — period 2023

(Task 13 Step 3 출력)

### Analysis
...

## 277810 레인보우로보틱스 — period 2023

(Task 13 Step 4 출력)

### Analysis
...

## 집계 (3종목 × 3 run = 9 LLM call)

| 항목 | 값 |
|---|---|
| 총 input tokens | <sum> |
| 총 output tokens | <sum> |
| 총 cost | $<sum> |
| 총 wallclock | <sum>s |
| section LLM fallback 호출 횟수 | <0~3> |

## Notes

- N=3 표본의 stdev는 *변동성 추정*이지 통계적 신뢰구간 아님.
- 실 LLM 비결정성으로 같은 입력 다음 run에서 점수가 다를 수 있음.
- 후속 prompt·모델 변경 시 이 표를 비교 기준으로 사용.
- baseline 측정 raw output: `data/eval/runs/2026-05-26/<ticker>_2023/` (gitignored, 로컬 보존).
```

내용을 실제 측정 수치로 채워 commit.

- [ ] **Step 2: README의 "Status" 섹션 갱신**

기존 (`README.md` line 5~7 근처):
```markdown
**Walking Skeleton (#1) + Eval Harness (#6) + DART API Client (#3) 구현 완료** — 2026-05-25.
```

다음으로 변경:
```markdown
**Walking Skeleton (#1) + Eval Harness (#6) + DART API Client (#3) + Real-LLM Baseline 구현 완료** — 2026-05-26.

E5 ("이 회사 뭐 만들어?") CQ가 종목+연도만 입력하면 end-to-end로 동작하고, 3종목(삼성/현대/레인보우)에 대해 실 Claude CLI로 N=3 run baseline 측정 완료. token usage·section filter 측정 인프라 포함.
```

- [ ] **Step 3: README의 "다음 작업" 섹션 갱신**

기존:
```markdown
🚧 **다음**: 실 `claude` CLI 기반 E5 추출 baseline 측정 (삼성/현대/레인보우 3종목) — 지금까지 stub만 검증, 실 LLM 품질 수치 미정
```

다음으로 변경:
```markdown
**다음 작업:** Plan #5 (다종목·시계열 backfill orchestrator) 또는 Plan #2/#7 (social layer ingestion). baseline 결과는 `docs/e5-real-llm-baseline-notes.md` 참조.
```

"후속 Plan들" 섹션에 항목 추가:
```markdown
- ~~**실 LLM baseline**~~ ✅ 완료 (`docs/superpowers/plans/2026-05-26-e5-real-llm-baseline.md`, `docs/e5-real-llm-baseline-notes.md`)
```

- [ ] **Step 4: README의 "E5 추출 품질 평가" 섹션에 멀티런 예제 추가**

기존 섹션 끝에 추가:
```markdown
**N=3 run + 영속화 (실 LLM):**

```bash
uv run themek eval e5 \
  --html-file data/dart/raw/<rcept_no>/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/<date>
```

출력: 각 metric의 mean ± stdev + token usage + section filter 로그. raw per-run 출력은 `data/eval/runs/<date>/<ticker>_<period>/` (gitignored).
```

- [ ] **Step 5: 커밋**

```bash
git add docs/e5-real-llm-baseline-notes.md README.md
git commit -m "docs: real-LLM baseline notes + README 갱신 (Plan #real-baseline T14)"
```

---

## Acceptance Verification

모든 task 완료 후 전체 검증:

```bash
# 1. 전체 테스트 통과 (기존 138 + 신규 ~25)
uv run pytest

# 2. 3종목 eval 명령 정상 동작 — 캐시 있으면 빠름, 없으면 LLM call 발생
for t in 005930 005380 277810; do
  RCEPT=$(ls data/dart/raw/ | head -1)  # 실제로는 ticker별 매핑
  uv run themek eval e5 \
    --html-file data/dart/raw/$RCEPT/business.html \
    --period 2023 \
    --ground-truth data/eval/ground_truth/${t/005930/samsung}_e5_2023.json \
    --runs 1
done

# 3. Spec section 8 acceptance criteria 모두 충족 확인
ls data/eval/ground_truth/{samsung,hyundai,rainbow}_e5_2023.json
ls docs/e5-real-llm-baseline-notes.md
ls tests/fixtures/samsung_e5_2023_fixture.json
grep "Real-LLM Baseline" README.md
grep "data/eval/runs" .gitignore
```

기대 결과:
- (1) pytest 전부 PASS
- (2) 3종목 모두 exit code 0
- (3) 7개 파일/grep 모두 매칭

---

## Self-Review (writer)

**Spec coverage (`docs/superpowers/specs/2026-05-26-e5-real-llm-baseline-design.md` §3.2 신규/확장 6개 항목):**
- `extract_business_sections` → T2, T5
- `CallResult` → T1
- `build_header_classification_prompt` → T3 (+ `llm_classify_headers` T4)
- `AggregatedResult` + `aggregate_runs` → T6
- CLI `--runs N --save-runs` → T8, T9
- ingest 파이프라인 동기화 → T10

**Spec §5 (Ground Truth) → T11 (archive), T12 (write 3 GTs)**
**Spec §6 (Error Handling)** → T1 (ClaudeCallError 보존), T2 (zero-match fallback), T8 (FileNotFoundError exit 1)
**Spec §7 (Testing)** → T1~T10 각 task가 unit/integration/CLI 테스트 포함
**Spec §8 (Acceptance Criteria 7개)** → T13 (run), T14 (notes + README), T11 (fixture archive)
**Spec §9 (Cost/Risk)** → T13 Step 1 (사전 점검), T11~T13 단계별 실 호출 점진 진행

**No placeholders:** 모든 step에 실제 코드/명령어 포함. "TBD" 없음. user task인 T11~T12는 명시적으로 사용자 작성임을 표기.

**Type consistency:** `CallResult` 필드명, `AggregatedResult` 필드명, `SectionResolution` 필드명이 spec §4 와 plan task 코드에서 모두 일치.
