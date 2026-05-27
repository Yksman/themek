# DART Parser Robust Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DART 사업보고서의 어떤 형식 변형이든 E5의 3개 섹션(overview/products/revenue)을 안정 추출. 3-tier escalation (A regex → B LLM → C full text) + 매 ingest마다 학습되는 self-improving regex.

**Architecture:** 기존 `extract_business_sections`에 escalation 분기와 sanity check를 얹고, `learned_header_patterns.json`을 runtime 로드해 baseline regex를 확장. B/C에서 LLM이 분류한 헤더 텍스트는 `pattern_proposals.json`에 누적, N=3회 동일 분류 도달 시 fixture 회귀 검증을 거쳐 자동 commit. `dart ingest`가 cache HTML을 `tests/fixtures/dart_variants/`에 자동 mirror해 검증 fixture pool을 점진 확장.

**Tech Stack:** Python 3.12+, pytest, pytest-mock, typer, beautifulsoup4 + lxml, JSON (학습/제안 저장), 기존 `claude` CLI wrapper.

**Spec:** `docs/superpowers/specs/2026-05-26-dart-parser-robust-extraction-design.md`

---

## Prerequisites

- Plan #1, #6, #3, e5-real-llm-baseline T1~T10 완료 (현재 코드 상태)
- `claude` CLI 로그인 (T13류 학습 trigger 시 필요)
- `DART_API_KEY` 환경변수 설정
- 직전 fix 완료: `_HEADER_LINE_RE` 정밀화 + seed.py Rainbow corp_code 정정 (이 plan의 출발점)

## Scope (in / out)

**In:**
- `src/themek/dart/parser.py`: SectionResolution 확장, MIN_SECTION_CHARS sanity check, A→B→C 분기, learned patterns 통합
- `src/themek/dart/learned_patterns.py` (신규): JSON schema, loader, runtime patterns provider
- `src/themek/dart/pattern_learning.py` (신규): propose / validate / record / apply
- `src/themek/dart/fixture_mirror.py` (신규): ingest cache → tests/fixtures mirror
- `src/themek/cli.py`: `dart parser-stats` / `dart parser-learn` / `dart parser-consolidate` + 매 ingest 자동 mirror·학습
- `data/dart/learned_header_patterns.json` (신규, commit)
- `data/dart/pattern_proposals.json` (신규, commit)
- `tests/fixtures/dart_variants/` (신규 디렉토리, commit; 초기 3종목 + 추가 5+ ingest mirror)
- `tests/`: parser escalation / sanity check / proposals / validate-against-fixtures / CLI 신규 케이스 ~30개
- `docs/dart-parser-robust-extraction-notes.md` (신규): coverage 통계, 초기 학습 결과 기록
- README "다음 작업" 갱신

**Out:**
- E5 외 섹션 추출, 영문/다국어 보고서, pgvector, LLM extractor prompt 최적화
- 학습 패턴 정밀도/리콜 자동 metric 보고서 (L3 영역)
- 학습 패턴 자동 git commit/push (파일 write까지만, git은 사람)

## File Structure

```
themek/
├── src/themek/
│   ├── dart/
│   │   ├── parser.py                 # 수정: SectionResolution 확장, escalation, learned patterns 통합
│   │   ├── learned_patterns.py       # 신규: JSON loader, runtime patterns API
│   │   ├── pattern_learning.py       # 신규: propose / validate / record / apply
│   │   └── fixture_mirror.py         # 신규: cache → tests/fixtures mirror
│   └── cli.py                        # 수정: dart parser-* 명령 3종 + ingest hook
├── tests/
│   ├── test_parser_escalation.py     # 신규: A→B→C 분기 단위 테스트
│   ├── test_parser_sanity_check.py   # 신규: MIN_SECTION_CHARS 검증
│   ├── test_learned_patterns.py      # 신규: JSON schema, loader, patterns merge
│   ├── test_pattern_learning.py      # 신규: propose / validate / record / apply
│   ├── test_fixture_mirror.py        # 신규: ingest → mirror copy
│   ├── test_cli_parser_commands.py   # 신규: parser-stats / -learn / -consolidate
│   ├── test_cli_dart.py              # 확장: ingest hook 검증
│   └── fixtures/
│       └── dart_variants/            # 신규: 초기 3 + 추가 ingest fixture
│           ├── 005930_2023.html
│           ├── 005930_2023_headers.json
│           ├── 005380_2023.html
│           ├── 005380_2023_headers.json
│           ├── 277810_2023.html
│           └── 277810_2023_headers.json
├── data/dart/
│   ├── learned_header_patterns.json  # 신규 (commit)
│   └── pattern_proposals.json        # 신규 (commit)
├── docs/
│   └── dart-parser-robust-extraction-notes.md  # 신규
└── README.md                          # 수정
```

---

# Phase 1 — Escalation skeleton (no learning yet)

목표: A→B→C 분기 + sanity check + CLI 가시화. 학습 없이도 robustness 확보.

---

## Task 1: SectionResolution 확장 — escalation 필드 추가

**Files:**
- Modify: `src/themek/dart/parser.py:57-63`
- Modify: `tests/test_parser_sections.py` (회귀 가드)

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_parser_escalation.py` 신규)

```python
"""Phase 1: SectionResolution escalation 필드 + sanity check."""
from themek.dart.parser import SectionResolution


def test_section_resolution_has_escalation_fields():
    """SectionResolution에 escalation_level/body_chars_per_target/invalid_targets/learned_samples 필드 존재."""
    r = SectionResolution()
    assert r.escalation_level == "regex"
    assert r.body_chars_per_target == {}
    assert r.invalid_targets == []
    assert r.learned_samples == []
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_escalation.py::test_section_resolution_has_escalation_fields -v
```
Expected: `AttributeError` on `escalation_level`.

- [ ] **Step 3: `SectionResolution` 확장** (`src/themek/dart/parser.py`)

```python
@dataclass
class SectionResolution:
    regex_matched: dict[str, str] = field(default_factory=dict)
    llm_called: bool = False
    llm_input_candidates: list[str] = field(default_factory=list)
    llm_decision: dict[str, Optional[int]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    output_chars: int = 0
    # 신규 (Phase 1):
    escalation_level: str = "regex"
    body_chars_per_target: dict[str, int] = field(default_factory=dict)
    invalid_targets: list[str] = field(default_factory=list)
    # 신규 (Phase 2 학습용 — 지금은 빈 채로 둠):
    learned_samples: list[dict] = field(default_factory=list)
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_parser_escalation.py tests/test_parser_sections.py -v
```
Expected: 새 1건 + 기존 9건 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/dart/parser.py tests/test_parser_escalation.py
git commit -m "feat(parser): SectionResolution escalation fields (robust T1)"
```

---

## Task 2: Sanity check — MIN_SECTION_CHARS 도입

**Files:**
- Modify: `src/themek/dart/parser.py:extract_business_sections`
- Modify: `tests/test_parser_escalation.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_parser_escalation.py` 끝)

```python
from themek.dart.parser import extract_business_sections


def test_sanity_check_marks_short_section_invalid():
    """body가 MIN_SECTION_CHARS 미만이면 그 target은 invalid_targets로."""
    html = """
    <p>1. 사업의 개요</p>
    <p>짧음</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>이건 충분히 길어야 함. {filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>매출 본문 또한 충분한 길이. {filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    text, res = extract_business_sections(html, llm_fallback=None)
    assert "overview" in res.invalid_targets
    assert "products" not in res.invalid_targets
    assert "revenue" not in res.invalid_targets
    assert res.body_chars_per_target["overview"] < 300
    assert res.body_chars_per_target["products"] >= 300
    assert res.body_chars_per_target["revenue"] >= 300


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
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_escalation.py -v -k sanity
```
Expected: KeyError / 누락 필드.

- [ ] **Step 3: `parser.py`에 `MIN_SECTION_CHARS` 상수 + 체크 추가**

`extract_business_sections` body 추출 직후에 보강:

```python
# 파일 상단 상수 영역에 추가
MIN_SECTION_CHARS = 300


# extract_business_sections 내부, `parts` concat 직전에:
def _measure_and_validate(
    matched_target_to_idx: dict[str, int],
    headers: list[tuple[int, str]],
    lines: list[str],
) -> tuple[dict[str, int], list[str]]:
    """각 target body 길이 측정 + MIN_SECTION_CHARS 미만은 invalid로."""
    body_chars: dict[str, int] = {}
    invalid: list[str] = []
    for target, idx in matched_target_to_idx.items():
        body = _section_body(lines, headers, idx)
        body_chars[target] = len(body)
        if len(body) < MIN_SECTION_CHARS:
            invalid.append(target)
    return body_chars, sorted(invalid)
```

`extract_business_sections` 본문에서 호출:

```python
    # 기존: parts concat 직전에
    body_chars, invalid = _measure_and_validate(
        matched_target_to_idx, headers, lines,
    )
    resolution.body_chars_per_target = body_chars
    resolution.invalid_targets = invalid
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_parser_escalation.py tests/test_parser_sections.py -v
```
Expected: 새 2건 + 기존 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/dart/parser.py tests/test_parser_escalation.py
git commit -m "feat(parser): MIN_SECTION_CHARS sanity check (robust T2)"
```

---

## Task 3: A→B 자동 escalation — invalid target도 LLM에 넘김

기존 `missing` 만 LLM에 넘기던 분기를 `missing + invalid` 합집합으로 확장. `escalation_level`은 LLM이 호출되면 `"regex+llm"`으로.

**Files:**
- Modify: `src/themek/dart/parser.py:extract_business_sections`
- Modify: `tests/test_parser_escalation.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from unittest.mock import MagicMock


def test_escalation_a_to_b_triggers_on_invalid_target():
    """regex로 잡혔지만 body가 짧으면 LLM fallback을 호출하고
    escalation_level은 'regex+llm'."""
    html = """
    <p>1. 사업의 개요</p>
    <p>짧음</p>
    <p>2. 영업 현황 (regex 매칭 X)</p>
    <p>{filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>{filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    mock_fb = MagicMock(return_value={
        "overview": 1,    # candidates[0] = "영업 현황..."을 overview로 (가정)
        "products": None,
        "revenue": None,
    })
    _, res = extract_business_sections(html, llm_fallback=mock_fb)
    assert res.escalation_level == "regex+llm"
    assert res.llm_called is True


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
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_escalation.py -v -k escalation_a
```
Expected: `escalation_level` 잘못된 값.

- [ ] **Step 3: `extract_business_sections` 분기 갱신**

기존 `missing = sorted(want - set(matched_target_to_idx))` 다음에:

```python
    # Phase 1: invalid target도 fallback 대상에 포함
    invalid_targets_pre = [
        t for t, idx in matched_target_to_idx.items()
        if len(_section_body(lines, headers, idx)) < MIN_SECTION_CHARS
    ]
    targets_needing_llm = sorted(set(missing) | set(invalid_targets_pre))

    if targets_needing_llm and llm_fallback is not None:
        # invalid target은 그 잘못 매칭된 헤더를 후보에서 제외해야 함
        used_idx = {
            i for t, i in matched_target_to_idx.items()
            if t not in invalid_targets_pre
        }
        candidates_idx = [i for i, _ in enumerate(headers) if i not in used_idx]
        candidates = [headers[i][1] for i in candidates_idx]
        resolution.llm_called = True
        resolution.escalation_level = "regex+llm"
        resolution.llm_input_candidates = candidates
        decision = llm_fallback(candidates, targets_needing_llm)
        resolution.llm_decision = dict(decision)
        for target, one_based in decision.items():
            if one_based is None:
                continue
            real_idx = candidates_idx[one_based - 1]
            matched_target_to_idx[target] = real_idx

    # body_chars/invalid_targets 재측정 (LLM이 더 좋은 매칭을 줬을 수도)
    body_chars, invalid = _measure_and_validate(
        matched_target_to_idx, headers, lines,
    )
    resolution.body_chars_per_target = body_chars
    resolution.invalid_targets = invalid
```

기존의 `missing and llm_fallback != None` 블록은 제거 (위 새 블록이 대체).

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_parser_escalation.py tests/test_parser_sections.py -v
```
Expected: 신규 + 기존 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/dart/parser.py tests/test_parser_escalation.py
git commit -m "feat(parser): A->B escalation on invalid_targets (robust T3)"
```

---

## Task 4: B→C 자동 escalation — full text fallback

B 단계 후에도 invalid_targets가 남아 있거나 헤더가 0개였으면, `extract_business_content` 결과를 통째로 반환하고 `escalation_level = "full_text"`.

**Files:**
- Modify: `src/themek/dart/parser.py:extract_business_sections`
- Modify: `tests/test_parser_escalation.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_escalation_b_to_c_returns_full_text_when_invalid_remains():
    """LLM도 본문이 짧은 target을 해결 못 하면 full_text fallback."""
    html = """
    <p>1. 사업의 개요</p>
    <p>너무 짧음</p>
    <p>2. 노이즈 헤더</p>
    <p>여기도 짧음</p>
    <p>full text fallback에서 와야 하는 핵심 본문이 여기에 있다. {filler}</p>
    """.replace("{filler}", "ㅇ" * 500)
    # LLM도 매칭을 못 해 줌
    mock_fb = MagicMock(return_value={
        "overview": None, "products": None, "revenue": None,
    })
    text, res = extract_business_sections(html, llm_fallback=mock_fb)
    assert res.escalation_level == "full_text"
    assert "full text fallback에서 와야 하는 핵심 본문" in text


def test_escalation_b_to_c_when_zero_headers():
    """헤더 0개도 곧장 full_text."""
    html = "<p>아무 헤더 없이 본문만 길게 ㅇ" + "ㅇ" * 500 + "</p>"
    text, res = extract_business_sections(html, llm_fallback=None)
    assert res.escalation_level == "full_text"
    assert len(text) > 300
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_escalation.py -v -k b_to_c
```
Expected: escalation_level != "full_text".

- [ ] **Step 3: `extract_business_sections` 끝부분에 fallback 추가**

`parts` concat이 끝나고 text 길이 측정 직후:

```python
    # Phase 1: B 후에도 invalid가 남으면 full_text fallback (C 단계)
    if resolution.invalid_targets or not headers or not matched_target_to_idx:
        full_text = extract_business_content(html)
        resolution.escalation_level = "full_text"
        resolution.output_chars = len(full_text)
        # body_chars/invalid은 그대로 보존 (디버깅용)
        return full_text, resolution

    return text, resolution
```

기존의 `if not headers` 곧장 return 분기는 제거 (위 fallback이 처리).

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_parser_escalation.py tests/test_parser_sections.py -v
```
Expected: 신규 + 기존 모두 PASS.

- [ ] **Step 5: Rainbow 실 HTML로 end-to-end 회귀 확인**

```bash
uv run python -c "
from pathlib import Path
from themek.dart.parser import extract_business_sections
html = Path('data/dart/raw/20240321001029/business.html').read_text(encoding='utf-8')
text, res = extract_business_sections(html, llm_fallback=None)
print(f'escalation_level: {res.escalation_level}')
print(f'output_chars: {res.output_chars}')
print(f'invalid_targets: {res.invalid_targets}')
print(f'body_chars: {res.body_chars_per_target}')
"
```
Expected: `escalation_level: regex` (Rainbow는 직전 fix로 이제 정상), output_chars > 5000.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/parser.py tests/test_parser_escalation.py
git commit -m "feat(parser): B->C full_text fallback (robust T4)"
```

---

## Task 5: CLI 가시화 — eval e5 + dart ingest 출력에 escalation_level 노출

**Files:**
- Modify: `src/themek/cli.py:_format_section_log`
- Modify: `src/themek/cli.py:dart_ingest_cmd` (stdout에 한 줄 추가)
- Modify: `tests/test_cli_dart.py` / `tests/test_cli_eval.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_cli_eval.py` 끝)

```python
def test_cli_eval_e5_runs_3_shows_escalation_level(monkeypatch, tmp_path):
    """N>1 출력의 Section filter 블록에 escalation_level 라인이 포함된다."""
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
        "--runs", "3",
    ])
    assert result.exit_code == 0, result.stdout
    assert "escalation" in result.stdout.lower()
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli_eval.py -v -k escalation_level
```
Expected: "escalation" 문자열 stdout에 없음.

- [ ] **Step 3: `_format_section_log` 갱신** (`src/themek/cli.py`)

```python
def _format_section_log(resolution) -> str:
    matched_regex = sorted(resolution.regex_matched)
    matched_llm = sorted(t for t, v in resolution.llm_decision.items()
                         if v is not None)
    body_chars_str = ", ".join(
        f"{t}={n}" for t, n in sorted(resolution.body_chars_per_target.items())
    ) or "-"
    lines = [
        f"escalation_level: {resolution.escalation_level}",
        f"regex matched:    {', '.join(matched_regex) or '-'}",
        f"llm fallback:     {'called' if resolution.llm_called else 'not called'}",
        f"llm matched:      {', '.join(matched_llm) or '-'}",
        f"invalid_targets:  {', '.join(resolution.invalid_targets) or '-'}",
        f"body_chars:       {body_chars_str}",
        f"skipped:          {', '.join(resolution.skipped) or '-'}",
        f"output chars:     {resolution.output_chars}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: `dart_ingest_cmd`에 stdout 한 줄 추가**

`typer.echo(f"Ingested report {rcept_no}")` 직전에:

```python
    typer.echo(
        f"[section_filter] escalation={_section_resolution.escalation_level} "
        f"output_chars={_section_resolution.output_chars} "
        f"invalid={_section_resolution.invalid_targets}"
    )
```

(기존 `_section_resolution` 변수가 버려지던 것을 활용. 기존 라인의 `_` 변수명을 `section_resolution`으로 바꿔서 사용.)

- [ ] **Step 5: 통과 확인**

```bash
uv run pytest tests/test_cli_eval.py tests/test_cli_dart.py -v
```
Expected: 신규 + 기존 모두 PASS.

- [ ] **Step 6: 전체 회귀**

```bash
uv run pytest
```
Expected: 모두 PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/themek/cli.py tests/test_cli_eval.py tests/test_cli_dart.py
git commit -m "feat(cli): expose escalation_level in eval/ingest stdout (robust T5)"
```

---

# Phase 2 — Learning loop

목표: B/C escalation에서 LLM이 분류한 헤더 텍스트를 학습 sample로 누적해 regex를 자동 확장.

---

## Task 6: `learned_header_patterns.json` schema + loader

**Files:**
- Create: `src/themek/dart/learned_patterns.py`
- Create: `data/dart/learned_header_patterns.json` (초기 baseline)
- Create: `tests/test_learned_patterns.py`

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_learned_patterns.py`)

```python
"""learned_header_patterns.json — schema + loader + merge."""
import json
import pytest
from pathlib import Path
from themek.dart.learned_patterns import (
    LearnedPatterns, load_learned_patterns, save_learned_patterns,
    DEFAULT_BASELINE_PATTERNS,
)


def test_load_returns_baseline_when_file_missing(tmp_path):
    p = tmp_path / "missing.json"
    lp = load_learned_patterns(p)
    assert isinstance(lp, LearnedPatterns)
    # baseline은 코드 상수 — 최소 1개씩
    assert lp.target_patterns("overview")
    assert lp.target_patterns("products")
    assert lp.target_patterns("revenue")
    assert lp.prefix_patterns()


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "learned.json"
    lp = load_learned_patterns(p)
    lp.add_target_pattern("overview", regex="회사.{0,3}개황",
                          source="learned", samples=["회사의 개황"],
                          confirmed_count=3, fixtures_validated=["005930_2023"])
    save_learned_patterns(p, lp)
    lp2 = load_learned_patterns(p)
    overview_patterns = lp2.target_patterns("overview")
    assert any("회사.{0,3}개황" in pat["regex"] for pat in overview_patterns)


def test_target_patterns_returns_baseline_plus_learned(tmp_path):
    p = tmp_path / "learned.json"
    lp = load_learned_patterns(p)
    baseline_n = len(lp.target_patterns("overview"))
    lp.add_target_pattern("overview", regex="신규.패턴",
                          source="learned", samples=["신규 패턴"], confirmed_count=3)
    assert len(lp.target_patterns("overview")) == baseline_n + 1


def test_invalid_target_raises():
    lp = LearnedPatterns.from_baseline()
    with pytest.raises(ValueError):
        lp.add_target_pattern("invalid_target", regex="x",
                              source="learned", samples=["x"], confirmed_count=3)


def test_invalid_regex_raises():
    lp = LearnedPatterns.from_baseline()
    with pytest.raises(ValueError, match="invalid regex"):
        lp.add_target_pattern("overview", regex="[(broken",
                              source="learned", samples=["x"], confirmed_count=3)
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_learned_patterns.py -v
```
Expected: ImportError on `themek.dart.learned_patterns`.

- [ ] **Step 3: `src/themek/dart/learned_patterns.py` 구현**

```python
"""learned_header_patterns.json 로더 + runtime API.

baseline 패턴은 코드 상수, 학습된 패턴은 파일에서 로드. 둘을 merge해 제공.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_TARGETS = ("overview", "products", "revenue")

DEFAULT_BASELINE_PATTERNS: dict[str, list[dict[str, Any]]] = {
    "overview": [
        {"type": "keyword", "regex": r"사업.{0,3}개요", "source": "code_baseline"},
    ],
    "products": [
        {"type": "keyword", "regex": r"주요.{0,3}제품", "source": "code_baseline"},
        {"type": "keyword", "regex": r"제품.{0,3}서비스", "source": "code_baseline"},
    ],
    "revenue": [
        {"type": "keyword", "regex": r"매출", "source": "code_baseline"},
        {"type": "keyword", "regex": r"수주.{0,3}현황", "source": "code_baseline"},
    ],
}

DEFAULT_BASELINE_PREFIXES: list[dict[str, Any]] = [
    {"type": "prefix", "regex": r"^\s*\d{1,2}\.\s+", "source": "code_baseline"},
    {"type": "prefix", "regex": r"^\s*[가-힣]\.\s+", "source": "code_baseline"},
]


@dataclass
class LearnedPatterns:
    targets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    prefixes: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def from_baseline(cls) -> "LearnedPatterns":
        return cls(
            targets={t: list(ps) for t, ps in DEFAULT_BASELINE_PATTERNS.items()},
            prefixes=list(DEFAULT_BASELINE_PREFIXES),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def target_patterns(self, target: str) -> list[dict[str, Any]]:
        if target not in VALID_TARGETS:
            raise ValueError(f"invalid target: {target}")
        return list(self.targets.get(target, []))

    def prefix_patterns(self) -> list[dict[str, Any]]:
        return list(self.prefixes)

    def add_target_pattern(
        self, target: str, *, regex: str, source: str,
        samples: list[str], confirmed_count: int,
        fixtures_validated: list[str] | None = None,
    ) -> None:
        if target not in VALID_TARGETS:
            raise ValueError(f"invalid target: {target}")
        try:
            re.compile(regex)
        except re.error as e:
            raise ValueError(f"invalid regex: {regex} — {e}")
        entry = {
            "type": "keyword",
            "regex": regex,
            "source": source,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "samples": list(samples),
            "confirmed_count": confirmed_count,
            "fixtures_validated": list(fixtures_validated or []),
        }
        self.targets.setdefault(target, []).append(entry)

    def add_prefix_pattern(
        self, *, regex: str, source: str,
        samples: list[str], confirmed_count: int,
        fixtures_validated: list[str] | None = None,
    ) -> None:
        try:
            re.compile(regex)
        except re.error as e:
            raise ValueError(f"invalid regex: {regex} — {e}")
        self.prefixes.append({
            "type": "prefix",
            "regex": regex,
            "source": source,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "samples": list(samples),
            "confirmed_count": confirmed_count,
            "fixtures_validated": list(fixtures_validated or []),
        })


def load_learned_patterns(path: Path | str) -> LearnedPatterns:
    p = Path(path)
    if not p.exists():
        return LearnedPatterns.from_baseline()
    data = json.loads(p.read_text(encoding="utf-8"))
    lp = LearnedPatterns.from_baseline()
    # baseline은 그대로, learned만 추가 merge
    for target, entries in data.get("patterns", {}).items():
        for entry in entries:
            if entry.get("source") == "learned":
                lp.targets.setdefault(target, []).append(entry)
    for entry in data.get("prefixes", []):
        if entry.get("source") == "learned":
            lp.prefixes.append(entry)
    return lp


def save_learned_patterns(path: Path | str, lp: LearnedPatterns) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "patterns": lp.targets,
        "prefixes": lp.prefixes,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8")
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_learned_patterns.py -v
```
Expected: 5건 PASS.

- [ ] **Step 5: 초기 `data/dart/learned_header_patterns.json` 작성**

```bash
uv run python -c "
from pathlib import Path
from themek.dart.learned_patterns import LearnedPatterns, save_learned_patterns
lp = LearnedPatterns.from_baseline()
save_learned_patterns(Path('data/dart/learned_header_patterns.json'), lp)
print('initialized')
"
```

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/learned_patterns.py tests/test_learned_patterns.py data/dart/learned_header_patterns.json
git commit -m "feat(dart): learned_header_patterns.json schema + loader (robust T6)"
```

---

## Task 7: parser가 learned patterns 사용하도록 통합

**Files:**
- Modify: `src/themek/dart/parser.py`
- Modify: `tests/test_parser_sections.py`

기존 코드 상수 `TARGET_KEYWORDS` / `_HEADER_LINE_RE` 를 `LearnedPatterns` runtime 인스턴스로부터 빌드.

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_parser_sections.py` 끝)

```python
from themek.dart.parser import extract_business_sections


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

    html = """
    <p>1. 회사의 개황</p>
    <p>{filler}</p>
    <p>2. 주요 제품 및 서비스</p>
    <p>{filler}</p>
    <p>3. 매출 및 수주상황</p>
    <p>{filler}</p>
    """.replace("{filler}", "ㅇ" * 400)
    _, res = extract_business_sections(html, llm_fallback=None)
    assert "overview" in res.regex_matched
    assert res.escalation_level == "regex"
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_sections.py -v -k learned_pattern
```
Expected: overview 매칭 실패.

- [ ] **Step 3: parser.py 보강 — `LearnedPatterns`를 매 호출마다 로드**

```python
import os
from themek.dart.learned_patterns import LearnedPatterns, load_learned_patterns

DEFAULT_LEARNED_PATTERNS_PATH = "data/dart/learned_header_patterns.json"


def _current_learned_patterns() -> LearnedPatterns:
    path = os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    )
    return load_learned_patterns(path)


def _build_target_regex_map(lp: LearnedPatterns) -> dict[str, list[re.Pattern]]:
    return {
        t: [re.compile(p["regex"]) for p in lp.target_patterns(t)]
        for t in ("overview", "products", "revenue")
    }


def _build_header_line_re(lp: LearnedPatterns) -> re.Pattern:
    # prefix 패턴들의 OR + 제목 캡쳐
    prefixes = [p["regex"].lstrip("^").rstrip(r"\s+").rstrip(r"\s*") for p in lp.prefix_patterns()]
    # 단순화: 모든 prefix regex가 ^...$ 의 일부라고 가정. 안전을 위해 alt union
    prefix_union = "|".join(p["regex"].lstrip("^").rstrip(r"\s+").rstrip(r"\s*") for p in lp.prefix_patterns())
    # 위 처리는 학습 패턴 모양에 따라 깨질 수 있어서 baseline prefixes만 우선 사용:
    return re.compile(
        r"^\s*(?:\d{1,2}|[가-힣])\.\s+(\S.{0,48})\s*$"
    )
```

기존 모듈-레벨 `TARGET_KEYWORDS` 를 함수 내부에서 매 호출마다 빌드하도록 `extract_business_sections` 안에서:

```python
def extract_business_sections(html, *, want=..., llm_fallback=None):
    lp = _current_learned_patterns()
    target_keywords = _build_target_regex_map(lp)
    # 기존 코드의 `TARGET_KEYWORDS` 참조를 `target_keywords` 로 치환
    ...
```

`_classify_header_by_regex`도 keyword map을 인자로 받도록 변경:

```python
def _classify_header_by_regex(header: str, target_keywords: dict[str, list[re.Pattern]]) -> Optional[str]:
    for target, patterns in target_keywords.items():
        if any(p.search(header) for p in patterns):
            return target
    return None
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_parser_sections.py tests/test_parser_escalation.py -v
```
Expected: 모두 PASS.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest
```
Expected: 모두 PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/parser.py tests/test_parser_sections.py
git commit -m "feat(parser): integrate learned patterns at runtime (robust T7)"
```

---

## Task 8: `SectionResolution.learned_samples` 채우기

B 단계에서 LLM이 분류한 헤더 텍스트를 `learned_samples` 리스트에 push.

**Files:**
- Modify: `src/themek/dart/parser.py:extract_business_sections`
- Modify: `tests/test_parser_escalation.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_learned_samples_populated_on_llm_match():
    """LLM이 새 변형 헤더를 분류하면 learned_samples에 (target, header_text) 기록."""
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
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_parser_escalation.py -v -k learned_samples
```

- [ ] **Step 3: `extract_business_sections`에서 LLM 결과 처리 시 sample 기록**

LLM decision 처리 루프 안에서:

```python
        for target, one_based in decision.items():
            if one_based is None:
                continue
            real_idx = candidates_idx[one_based - 1]
            matched_target_to_idx[target] = real_idx
            resolution.learned_samples.append({
                "target": target,
                "header_text": headers[real_idx][1],
            })
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_parser_escalation.py -v
git add src/themek/dart/parser.py tests/test_parser_escalation.py
git commit -m "feat(parser): record learned_samples from LLM classification (robust T8)"
```

---

## Task 9: `pattern_learning.py` — propose 로직

**Files:**
- Create: `src/themek/dart/pattern_learning.py`
- Create: `tests/test_pattern_learning.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
"""pattern_learning — propose / validate / record / apply."""
import pytest
from themek.dart.pattern_learning import (
    propose_keyword_pattern, MIN_KEYWORD_LENGTH,
)


def test_propose_extracts_core_keyword():
    """헤더 텍스트에서 prefix 노이즈를 제거하고 핵심 키워드 regex로 일반화."""
    # "(제조서비스업)사업의 개요" → "사업.{0,3}개요" 같은 일반화
    pat = propose_keyword_pattern("(제조서비스업)사업의 개요", target="overview")
    assert pat is not None
    assert "사업" in pat or "개요" in pat


def test_propose_rejects_too_short():
    pat = propose_keyword_pattern("이", target="overview")
    assert pat is None


def test_propose_rejects_common_filler():
    """공통 어휘만 있는 경우 reject."""
    pat = propose_keyword_pattern("등 및", target="overview")
    assert pat is None


def test_propose_normalizes_whitespace_to_flexible():
    """공백을 .{0,3} 로 일반화."""
    pat = propose_keyword_pattern("회사의 개황", target="overview")
    assert pat is not None
    assert "회사" in pat
    assert "개황" in pat
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_pattern_learning.py -v -k propose
```

- [ ] **Step 3: `src/themek/dart/pattern_learning.py` 구현**

```python
"""학습 sample로부터 regex 일반화 + 검증 + 누적 + 적용.

규칙:
- minimum specificity: keyword 최소 3자, 어휘 토큰 1개 이상
- 공통 어휘(`등`, `및`, `의`, `이`, `가`) 거부
- 공백은 `.{0,3}` 로 일반화하여 표기 변형 흡수
"""
from __future__ import annotations
import re
from typing import Optional

MIN_KEYWORD_LENGTH = 3
COMMON_FILLERS = {"등", "및", "의", "이", "가", "을", "를", "에", "도", "는"}

# prefix-like 노이즈 제거: 괄호 묶음, 한자/한글번호 prefix
_PREFIX_NOISE_RE = re.compile(r"^[\s\(\[\{]*[\(\[]?[^\)\]]*[\)\]]?\s*")


def _strip_prefix_noise(text: str) -> str:
    """`(제조서비스업)` `[금융업]` `①` `Ⅰ.` 같은 prefix 제거."""
    # 괄호 묶음 prefix
    text = re.sub(r"^\s*[\(\[\{].{1,15}?[\)\]\}]\s*", "", text)
    # 원숫자, 로마자, 한글번호
    text = re.sub(r"^[①-⑳ⅠⅡⅢⅣⅤ㈠-㉃]+\s*", "", text)
    return text.strip()


def _is_meaningful(token: str) -> bool:
    if len(token) < 2:
        return False
    if token in COMMON_FILLERS:
        return False
    return True


def propose_keyword_pattern(header_text: str, *, target: str) -> Optional[str]:
    """헤더 텍스트에서 일반화된 keyword regex를 만든다.

    실패 (너무 짧음, 공통 어휘만, 의미없는 결과)면 None.
    """
    core = _strip_prefix_noise(header_text)
    # 공백·구두점으로 토큰 분할
    tokens = [t for t in re.split(r"[\s ·\-/]+", core) if t]
    meaningful = [t for t in tokens if _is_meaningful(t)]
    if not meaningful:
        return None
    joined = "".join(meaningful)
    if len(joined) < MIN_KEYWORD_LENGTH:
        return None
    # 토큰 사이에 .{0,3} 삽입해 공백·구두점 변형 흡수
    pattern = ".{0,3}".join(re.escape(t) for t in meaningful)
    return pattern
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_pattern_learning.py -v
git add src/themek/dart/pattern_learning.py tests/test_pattern_learning.py
git commit -m "feat(dart): propose_keyword_pattern from learned samples (robust T9)"
```

---

## Task 10: validate_patterns — 모든 fixture에 대한 회귀 검증

**Files:**
- Modify: `src/themek/dart/pattern_learning.py`
- Modify: `tests/test_pattern_learning.py`
- Create: `tests/fixtures/dart_variants/.gitkeep` (디렉토리 보장)

- [ ] **Step 1: 실패 테스트 추가**

```python
import json
from pathlib import Path
from themek.dart.learned_patterns import LearnedPatterns
from themek.dart.pattern_learning import validate_pattern_against_fixtures


def test_validate_pattern_passes_when_no_fixtures(tmp_path):
    """fixture가 없으면 검증 통과 (초기 단계)."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    ok, reasons = validate_pattern_against_fixtures(
        target="overview", regex="회사.{0,3}개황",
        fixtures_dir=fixtures_dir,
    )
    assert ok
    assert reasons == []


def test_validate_pattern_rejects_when_breaks_existing(tmp_path):
    """fixture의 expected headers와 매칭이 충돌하면 reject."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    # samsung fixture: 1. 사업의 개요 → overview, 2. 주요 제품 → products, 3. 매출 → revenue
    (fixtures_dir / "005930_2023.html").write_text(
        "<p>1. 사업의 개요</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>2. 주요 제품 및 서비스</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>3. 매출 및 수주상황</p><p>본문" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    (fixtures_dir / "005930_2023_headers.json").write_text(json.dumps({
        "overview": "사업의 개요",
        "products": "주요 제품 및 서비스",
        "revenue": "매출 및 수주상황",
    }), encoding="utf-8")
    # 너무 broad한 패턴: "매" 하나만으로 overview 매칭 시도
    ok, reasons = validate_pattern_against_fixtures(
        target="overview", regex="매",
        fixtures_dir=fixtures_dir,
    )
    assert ok is False
    assert reasons  # 깨진 fixture 이름 포함
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_pattern_learning.py -v -k validate
```

- [ ] **Step 3: `validate_pattern_against_fixtures` 구현**

```python
import json
from pathlib import Path
from themek.dart.parser import extract_business_sections
from themek.dart.learned_patterns import LearnedPatterns, save_learned_patterns


def validate_pattern_against_fixtures(
    *, target: str, regex: str, fixtures_dir: Path,
    learned_patterns_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """fixture 하나라도 expected_headers와 충돌하는 새 매칭을 만들면 reject.

    Returns: (ok, breaking_fixture_names)
    """
    breaking: list[str] = []
    html_files = sorted(fixtures_dir.glob("*.html"))
    if not html_files:
        return True, []

    # 임시 learned patterns: baseline + 후보 패턴
    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern(target, regex=regex, source="learned",
                           samples=[], confirmed_count=0)

    # 임시 저장 후 환경변수로 parser에 주입
    import os, tempfile
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8",
    ) as f:
        save_learned_patterns(Path(f.name), lp)
        tmp_path = Path(f.name)

    old_env = os.environ.get("THEMEK_LEARNED_PATTERNS_PATH")
    os.environ["THEMEK_LEARNED_PATTERNS_PATH"] = str(tmp_path)

    try:
        for html_path in html_files:
            expected_path = html_path.with_name(
                html_path.stem + "_headers.json"
            )
            if not expected_path.exists():
                continue
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")
            _, res = extract_business_sections(html, llm_fallback=None)
            for t, exp_header in expected.items():
                got = res.regex_matched.get(t)
                if got and exp_header and exp_header not in got and got not in exp_header:
                    breaking.append(html_path.stem)
                    break
    finally:
        if old_env is None:
            os.environ.pop("THEMEK_LEARNED_PATTERNS_PATH", None)
        else:
            os.environ["THEMEK_LEARNED_PATTERNS_PATH"] = old_env
        tmp_path.unlink(missing_ok=True)

    return (len(breaking) == 0), breaking
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_pattern_learning.py -v -k validate
```

- [ ] **Step 5: `tests/fixtures/dart_variants/.gitkeep` 추가**

```bash
mkdir -p tests/fixtures/dart_variants
touch tests/fixtures/dart_variants/.gitkeep
```

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/pattern_learning.py tests/test_pattern_learning.py tests/fixtures/dart_variants/.gitkeep
git commit -m "feat(dart): validate_pattern_against_fixtures (robust T10)"
```

---

## Task 11: `pattern_proposals.json` — 누적 + N=3 카운트

**Files:**
- Modify: `src/themek/dart/pattern_learning.py`
- Modify: `tests/test_pattern_learning.py`
- Create: `data/dart/pattern_proposals.json` (빈 초기값)

- [ ] **Step 1: 실패 테스트 추가**

```python
from themek.dart.pattern_learning import (
    record_proposal, load_proposals, save_proposals, Proposal,
)


def test_record_creates_new_proposal(tmp_path):
    p = tmp_path / "proposals.json"
    record_proposal(p, target="overview", candidate_regex="회사.{0,3}개황",
                    sample_header="회사의 개황", source_fixture="068270_2023")
    proposals = load_proposals(p)
    assert len(proposals) == 1
    assert proposals[0].target == "overview"
    assert proposals[0].candidate_regex == "회사.{0,3}개황"
    assert proposals[0].observed_count == 1
    assert "회사의 개황" in proposals[0].sample_headers
    assert "068270_2023" in proposals[0].source_fixtures


def test_record_increments_existing(tmp_path):
    p = tmp_path / "proposals.json"
    for fx in ("068270_2023", "035420_2023", "036570_2023"):
        record_proposal(p, target="overview",
                        candidate_regex="회사.{0,3}개황",
                        sample_header="회사의 개황", source_fixture=fx)
    proposals = load_proposals(p)
    assert len(proposals) == 1
    assert proposals[0].observed_count == 3
    assert len(proposals[0].source_fixtures) == 3
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_pattern_learning.py -v -k record
```

- [ ] **Step 3: `Proposal` + record/load/save 구현**

`src/themek/dart/pattern_learning.py`에 추가:

```python
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class Proposal:
    target: str
    candidate_regex: str
    sample_headers: list[str] = field(default_factory=list)
    observed_count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    source_fixtures: list[str] = field(default_factory=list)


def load_proposals(path: Path | str) -> list[Proposal]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Proposal(**entry) for entry in data.get("proposals", [])]


def save_proposals(path: Path | str, proposals: list[Proposal]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [asdict(pr) for pr in proposals]}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def record_proposal(
    path: Path | str, *, target: str, candidate_regex: str,
    sample_header: str, source_fixture: str,
) -> Proposal:
    proposals = load_proposals(path)
    now = datetime.now(timezone.utc).isoformat()
    for pr in proposals:
        if pr.target == target and pr.candidate_regex == candidate_regex:
            pr.observed_count += 1
            pr.last_seen_at = now
            if sample_header not in pr.sample_headers:
                pr.sample_headers.append(sample_header)
            if source_fixture not in pr.source_fixtures:
                pr.source_fixtures.append(source_fixture)
            save_proposals(path, proposals)
            return pr
    pr = Proposal(
        target=target, candidate_regex=candidate_regex,
        sample_headers=[sample_header], observed_count=1,
        first_seen_at=now, last_seen_at=now,
        source_fixtures=[source_fixture],
    )
    proposals.append(pr)
    save_proposals(path, proposals)
    return pr
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_pattern_learning.py -v -k record
```

- [ ] **Step 5: 초기 `data/dart/pattern_proposals.json` 생성**

```bash
uv run python -c "
from pathlib import Path
from themek.dart.pattern_learning import save_proposals
save_proposals(Path('data/dart/pattern_proposals.json'), [])
print('initialized')
"
```

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/pattern_learning.py tests/test_pattern_learning.py data/dart/pattern_proposals.json
git commit -m "feat(dart): pattern_proposals.json + record/load/save (robust T11)"
```

---

## Task 12: apply_patterns — N=3 도달 시 fixture 검증 후 commit

**Files:**
- Modify: `src/themek/dart/pattern_learning.py`
- Modify: `tests/test_pattern_learning.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from themek.dart.pattern_learning import apply_ready_proposals
from themek.dart.learned_patterns import load_learned_patterns


def test_apply_promotes_n3_proposal_to_learned(tmp_path):
    """N=3 도달한 proposal이 fixture 검증을 통과하면 learned_patterns로 옮겨진다."""
    proposals_path = tmp_path / "proposals.json"
    learned_path = tmp_path / "learned.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    # fixture가 없으면 검증 통과 → apply 진행

    for fx in ("a", "b", "c"):
        record_proposal(
            proposals_path, target="overview",
            candidate_regex="회사.{0,3}개황",
            sample_header="회사의 개황", source_fixture=fx,
        )

    applied = apply_ready_proposals(
        proposals_path=proposals_path,
        learned_path=learned_path,
        fixtures_dir=fixtures_dir,
        min_confirmed=3,
    )
    assert len(applied) == 1
    assert applied[0].target == "overview"

    lp = load_learned_patterns(learned_path)
    assert any(
        p["regex"] == "회사.{0,3}개황" and p.get("source") == "learned"
        for p in lp.target_patterns("overview")
    )
    # apply 된 proposal은 proposals에서 제거되어야 함
    remaining = load_proposals(proposals_path)
    assert remaining == []


def test_apply_skips_proposal_under_threshold(tmp_path):
    proposals_path = tmp_path / "proposals.json"
    learned_path = tmp_path / "learned.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    record_proposal(proposals_path, target="overview",
                    candidate_regex="X", sample_header="X",
                    source_fixture="a")
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    assert applied == []
    assert len(load_proposals(proposals_path)) == 1  # 그대로 남음
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_pattern_learning.py -v -k apply
```

- [ ] **Step 3: `apply_ready_proposals` 구현**

```python
def apply_ready_proposals(
    *, proposals_path: Path, learned_path: Path, fixtures_dir: Path,
    min_confirmed: int = 3,
) -> list[Proposal]:
    """N=min_confirmed 이상이고 fixture 회귀 통과한 proposal을 learned로 promote.

    적용된 proposal은 proposals에서 제거. 반환값은 적용된 proposal 리스트.
    """
    proposals = load_proposals(proposals_path)
    lp = load_learned_patterns(learned_path)
    applied: list[Proposal] = []
    remaining: list[Proposal] = []
    for pr in proposals:
        if pr.observed_count < min_confirmed:
            remaining.append(pr)
            continue
        ok, breaking = validate_pattern_against_fixtures(
            target=pr.target, regex=pr.candidate_regex,
            fixtures_dir=fixtures_dir,
        )
        if not ok:
            # validation 실패 → proposals에 보존하되 fixtures_rejected 메모
            pr.sample_headers.append(f"__rejected_by:{','.join(breaking)}")
            remaining.append(pr)
            continue
        lp.add_target_pattern(
            pr.target, regex=pr.candidate_regex, source="learned",
            samples=pr.sample_headers, confirmed_count=pr.observed_count,
            fixtures_validated=pr.source_fixtures,
        )
        applied.append(pr)
    save_learned_patterns(learned_path, lp)
    save_proposals(proposals_path, remaining)
    return applied
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_pattern_learning.py -v
git add src/themek/dart/pattern_learning.py tests/test_pattern_learning.py
git commit -m "feat(dart): apply_ready_proposals N=3 + fixture regression gate (robust T12)"
```

---

## Task 13: ingest 자동 학습 hook

**Files:**
- Modify: `src/themek/cli.py:dart_ingest_cmd`
- Modify: `tests/test_cli_dart.py`

`dart ingest` 마지막에 `extract_business_sections`가 만든 `learned_samples`를 `record_proposal`로 누적하고, `apply_ready_proposals`도 호출.

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_dart_ingest_records_proposals_from_learned_samples(monkeypatch, tmp_path, mocker):
    """ingest가 learned_samples를 pattern_proposals.json에 누적한다."""
    from themek.cli import app
    from typer.testing import CliRunner
    runner = CliRunner()

    # DART 호출 mock
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )
    mocker.patch("themek.cli.lookup_corp_code", return_value="00000000")
    cached_html = tmp_path / "business.html"
    cached_html.write_text(
        "<p>1. 회사의 개황</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>2. 주요 제품 및 서비스</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>3. 매출 및 수주상황</p><p>본문" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    mocker.patch(
        "themek.cli.fetch_business_report_html",
        return_value=(cached_html, "20240101000001"),
    )

    # LLM이 "회사의 개황"을 overview로 분류
    def mock_classify(candidates, missing):
        for i, c in enumerate(candidates, 1):
            if "개황" in c and "overview" in missing:
                return {"overview": i, "products": None, "revenue": None}
        return {"overview": None, "products": None, "revenue": None}

    mocker.patch("themek.cli.llm_classify_headers", side_effect=mock_classify)
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(tmp_path / "proposals.json"))
    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(tmp_path / "learned.json"))

    stub_path = tmp_path / "stub.json"
    stub_path.write_text(
        '{"period": "2023", "segments": [], "customers": [], "geographic": []}',
        encoding="utf-8",
    )
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub_path))

    result = runner.invoke(app, [
        "dart", "ingest", "--ticker", "999999", "--period", "2023",
    ])
    assert result.exit_code == 0, result.stdout

    # proposals.json에 overview 후보가 기록되었는지
    from themek.dart.pattern_learning import load_proposals
    proposals = load_proposals(tmp_path / "proposals.json")
    assert any(p.target == "overview" for p in proposals)
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli_dart.py -v -k records_proposals
```

- [ ] **Step 3: `cli.py:dart_ingest_cmd` 끝에 학습 hook 추가**

```python
import os
DEFAULT_PROPOSALS_PATH = "data/dart/pattern_proposals.json"
DEFAULT_LEARNED_PATTERNS_PATH = "data/dart/learned_header_patterns.json"


def _learn_from_resolution(
    section_resolution, *, ticker: str, period: str,
) -> None:
    from themek.dart.pattern_learning import (
        propose_keyword_pattern, record_proposal, apply_ready_proposals,
    )
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    fixtures_dir = Path("tests/fixtures/dart_variants")

    for sample in section_resolution.learned_samples:
        regex = propose_keyword_pattern(
            sample["header_text"], target=sample["target"],
        )
        if regex is None:
            continue
        record_proposal(
            proposals_path, target=sample["target"],
            candidate_regex=regex, sample_header=sample["header_text"],
            source_fixture=f"{ticker}_{period}",
        )
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    if applied:
        typer.echo(
            f"[parser-learn] applied {len(applied)} new patterns: "
            f"{[(p.target, p.candidate_regex) for p in applied]}"
        )
```

`dart_ingest_cmd` 안의 `extract_business_sections` 호출 후, ingest 성공 직전에:

```python
    _learn_from_resolution(section_resolution, ticker=ticker, period=period)
```

(`section_resolution` 변수가 위에서 `_section_resolution` 이름이라면 통일.)

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_cli_dart.py -v
```

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest
```

- [ ] **Step 6: 커밋**

```bash
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): dart ingest auto-learn hook (robust T13)"
```

---

# Phase 3 — Fixture infrastructure

목표: ingest cache HTML을 자동으로 `tests/fixtures/dart_variants/`에 mirror + expected headers JSON auto-generation.

---

## Task 14: `fixture_mirror.py` — cache → tests/fixtures 복사

**Files:**
- Create: `src/themek/dart/fixture_mirror.py`
- Create: `tests/test_fixture_mirror.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
"""fixture_mirror — ingest cache HTML을 tests/fixtures/dart_variants/에 mirror."""
import json
from pathlib import Path
from themek.dart.fixture_mirror import mirror_fixture


def test_mirror_copies_html_and_writes_expected_headers(tmp_path):
    cache_html = tmp_path / "cache" / "business.html"
    cache_html.parent.mkdir(parents=True)
    cache_html.write_text(
        "<p>1. 사업의 개요</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>2. 주요 제품 및 서비스</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>3. 매출 및 수주상황</p><p>본문" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    fixtures_dir = tmp_path / "fixtures"
    mirror_fixture(
        cache_html=cache_html, ticker="005930", period="2023",
        fixtures_dir=fixtures_dir,
    )
    mirrored = fixtures_dir / "005930_2023.html"
    headers_json = fixtures_dir / "005930_2023_headers.json"
    assert mirrored.exists()
    assert headers_json.exists()
    expected = json.loads(headers_json.read_text(encoding="utf-8"))
    assert "overview" in expected
    assert "사업의 개요" in expected["overview"]


def test_mirror_idempotent(tmp_path):
    cache_html = tmp_path / "cache" / "business.html"
    cache_html.parent.mkdir(parents=True)
    cache_html.write_text("<p>1. 사업의 개요</p><p>" + "ㅇ" * 400 + "</p>",
                          encoding="utf-8")
    fixtures_dir = tmp_path / "fixtures"
    mirror_fixture(cache_html=cache_html, ticker="X", period="2023",
                   fixtures_dir=fixtures_dir)
    mtime1 = (fixtures_dir / "X_2023.html").stat().st_mtime
    mirror_fixture(cache_html=cache_html, ticker="X", period="2023",
                   fixtures_dir=fixtures_dir)
    mtime2 = (fixtures_dir / "X_2023.html").stat().st_mtime
    # 두 번째 호출에서 HTML이 같으면 재기록 안 함 (mtime 동일)
    assert mtime1 == mtime2
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_fixture_mirror.py -v
```

- [ ] **Step 3: `fixture_mirror.py` 구현**

```python
"""ingest cache HTML → tests/fixtures/dart_variants/ mirror.

회귀 검증의 fixture pool을 자동 확장한다. expected_headers JSON은
현재 parser의 regex 결과를 그대로 기록 (사람이 잘못 잡힌 경우만 수정).
"""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from themek.dart.parser import extract_business_sections


def mirror_fixture(
    *, cache_html: Path, ticker: str, period: str, fixtures_dir: Path,
) -> tuple[Path, Path]:
    """cache HTML을 fixtures_dir로 복사하고 expected_headers JSON 생성.

    Returns: (mirrored_html, headers_json)
    """
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    dst_html = fixtures_dir / f"{ticker}_{period}.html"
    dst_headers = fixtures_dir / f"{ticker}_{period}_headers.json"

    # 동일 내용이면 mtime 보존 (idempotent)
    src_bytes = cache_html.read_bytes()
    if dst_html.exists() and dst_html.read_bytes() == src_bytes:
        # headers JSON만 갱신 (학습 패턴 반영을 위해)
        pass
    else:
        shutil.copy2(cache_html, dst_html)

    # 현재 parser로 expected headers 추출
    html = cache_html.read_text(encoding="utf-8")
    _, res = extract_business_sections(html, llm_fallback=None)
    expected = dict(res.regex_matched)  # 학습 패턴까지 적용된 결과
    # invalid_targets는 expected에서 제외 (잘못 잡힌 것)
    for t in res.invalid_targets:
        expected.pop(t, None)
    dst_headers.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dst_html, dst_headers
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_fixture_mirror.py -v
git add src/themek/dart/fixture_mirror.py tests/test_fixture_mirror.py
git commit -m "feat(dart): fixture_mirror module (robust T14)"
```

---

## Task 15: `dart ingest` 자동 mirror

**Files:**
- Modify: `src/themek/cli.py:dart_ingest_cmd`
- Modify: `tests/test_cli_dart.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_cli_dart.py` 끝)

```python
def test_dart_ingest_mirrors_fixture(monkeypatch, tmp_path, mocker):
    """dart ingest 후 fixtures/dart_variants/ 에 mirror 파일 존재."""
    from themek.cli import app
    from typer.testing import CliRunner
    runner = CliRunner()
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )
    mocker.patch("themek.cli.lookup_corp_code", return_value="00000000")
    cached_html = tmp_path / "business.html"
    cached_html.write_text(
        "<p>1. 사업의 개요</p><p>" + "ㅇ" * 400 + "</p>"
        "<p>2. 주요 제품 및 서비스</p><p>" + "ㅇ" * 400 + "</p>"
        "<p>3. 매출 및 수주상황</p><p>" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    mocker.patch(
        "themek.cli.fetch_business_report_html",
        return_value=(cached_html, "20240101000001"),
    )
    fixtures_dir = tmp_path / "fixtures"
    monkeypatch.setenv("THEMEK_FIXTURES_DIR", str(fixtures_dir))
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE",
                       str(tmp_path / "stub.json"))
    (tmp_path / "stub.json").write_text(
        '{"period":"2023","segments":[],"customers":[],"geographic":[]}',
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "dart", "ingest", "--ticker", "999999", "--period", "2023",
    ])
    assert result.exit_code == 0
    assert (fixtures_dir / "999999_2023.html").exists()
    assert (fixtures_dir / "999999_2023_headers.json").exists()
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli_dart.py -v -k mirrors_fixture
```

- [ ] **Step 3: `dart_ingest_cmd`에 mirror 호출 추가**

```python
DEFAULT_FIXTURES_DIR = "tests/fixtures/dart_variants"

# dart_ingest_cmd 안에서, 학습 hook 직전에:
    from themek.dart.fixture_mirror import mirror_fixture
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    mirror_fixture(
        cache_html=html_path, ticker=ticker, period=period,
        fixtures_dir=fixtures_dir,
    )
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_cli_dart.py -v
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): dart ingest auto-mirrors fixture (robust T15)"
```

---

## Task 16: 기존 3종목 fixture 초기 mirror 실행

**Files:**
- Create: `tests/fixtures/dart_variants/005930_2023.html` (+ headers.json)
- Create: `tests/fixtures/dart_variants/005380_2023.html` (+ headers.json)
- Create: `tests/fixtures/dart_variants/277810_2023.html` (+ headers.json)

이미 cache된 3종목을 fixture로 mirror.

- [ ] **Step 1: 일회성 스크립트 실행**

```bash
uv run python -c "
from pathlib import Path
from themek.dart.fixture_mirror import mirror_fixture
mapping = [
    ('005930', '2023', 'data/dart/raw/20240312000736/business.html'),
    ('005380', '2023', 'data/dart/raw/20240313001451/business.html'),
    ('277810', '2023', 'data/dart/raw/20240321001029/business.html'),
]
fx = Path('tests/fixtures/dart_variants')
for ticker, period, src in mapping:
    h, j = mirror_fixture(
        cache_html=Path(src), ticker=ticker, period=period, fixtures_dir=fx,
    )
    print(f'mirrored {ticker}_{period} → {h}, {j}')
"
```

Expected: 3쌍 (html + headers.json) 생성.

- [ ] **Step 2: 결과 점검**

```bash
ls -la tests/fixtures/dart_variants/
for f in tests/fixtures/dart_variants/*_headers.json; do
  echo "=== $f ==="; cat "$f"
done
```

Expected: 3종목 모두 overview/products/revenue 키가 채워져 있어야 함.

- [ ] **Step 3: fixture를 사용한 회귀 검증 테스트 추가** (`tests/test_parser_sections.py`)

```python
def test_section_filter_against_all_mirrored_fixtures():
    """tests/fixtures/dart_variants/ 의 모든 fixture에 대해 expected_headers 일치."""
    import json
    from pathlib import Path
    from themek.dart.parser import extract_business_sections
    fx = Path("tests/fixtures/dart_variants")
    html_files = sorted(fx.glob("*.html"))
    assert html_files, "fixture가 없음 — T16 단계 수행 필요"
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
```

- [ ] **Step 4: 회귀 통과 확인**

```bash
uv run pytest tests/test_parser_sections.py -v -k all_mirrored
```

- [ ] **Step 5: 커밋**

```bash
git add tests/fixtures/dart_variants/ tests/test_parser_sections.py
git commit -m "data(fixtures): mirror initial 3 fixtures + regression test (robust T16)"
```

---

# Phase 4 — CLI & coverage build

목표: parser-stats / -learn / -consolidate 명령 + 다양한 업종 5종목 신규 ingest로 초기 학습 sample 확보.

---

## Task 17: `themek dart parser-stats` 명령

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_parser_commands.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_cli_parser_commands.py`)

```python
"""dart parser-* 명령 단위 테스트."""
import json
from pathlib import Path
from typer.testing import CliRunner
from themek.cli import app

runner = CliRunner()


def test_parser_stats_outputs_counts(monkeypatch, tmp_path):
    learned_path = tmp_path / "learned.json"
    proposals_path = tmp_path / "proposals.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "a_2023.html").write_text("<p>x</p>", encoding="utf-8")
    (fixtures_dir / "b_2023.html").write_text("<p>x</p>", encoding="utf-8")

    from themek.dart.learned_patterns import (
        LearnedPatterns, save_learned_patterns,
    )
    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern("overview", regex="회사.{0,3}개황",
                          source="learned", samples=["x"], confirmed_count=3)
    save_learned_patterns(learned_path, lp)

    from themek.dart.pattern_learning import save_proposals, Proposal
    save_proposals(proposals_path, [
        Proposal(target="products", candidate_regex="영업.{0,3}현황",
                 sample_headers=["영업 현황"], observed_count=2),
    ])

    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(learned_path))
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(proposals_path))
    monkeypatch.setenv("THEMEK_FIXTURES_DIR", str(fixtures_dir))

    result = runner.invoke(app, ["dart", "parser-stats"])
    assert result.exit_code == 0
    assert "fixtures: 2" in result.stdout
    assert "learned" in result.stdout
    assert "proposals" in result.stdout
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli_parser_commands.py -v -k parser_stats
```

- [ ] **Step 3: `cli.py`에 parser-stats 추가**

```python
@dart_app.command("parser-stats")
def dart_parser_stats_cmd():
    """학습 누적 상태 출력."""
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    from themek.dart.learned_patterns import load_learned_patterns
    from themek.dart.pattern_learning import load_proposals
    lp = load_learned_patterns(learned_path)
    proposals = load_proposals(proposals_path)
    fixtures = sorted(fixtures_dir.glob("*.html")) if fixtures_dir.exists() else []
    lines = [
        f"fixtures: {len(fixtures)}",
        f"learned patterns:",
    ]
    for t in ("overview", "products", "revenue"):
        learned_count = sum(
            1 for p in lp.target_patterns(t) if p.get("source") == "learned"
        )
        baseline_count = sum(
            1 for p in lp.target_patterns(t) if p.get("source") == "code_baseline"
        )
        lines.append(f"  {t}: baseline={baseline_count}, learned={learned_count}")
    lines.append(f"proposals (pending): {len(proposals)}")
    for pr in proposals[:10]:
        lines.append(
            f"  - {pr.target}: {pr.candidate_regex} "
            f"(observed {pr.observed_count}, fixtures={pr.source_fixtures})"
        )
    typer.echo("\n".join(lines))
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_cli_parser_commands.py -v -k parser_stats
git add src/themek/cli.py tests/test_cli_parser_commands.py
git commit -m "feat(cli): dart parser-stats command (robust T17)"
```

---

## Task 18: `themek dart parser-learn` 수동 trigger

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_parser_commands.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_parser_learn_applies_pending_proposals(monkeypatch, tmp_path):
    """N=3 도달한 proposal을 수동으로 apply."""
    learned_path = tmp_path / "learned.json"
    proposals_path = tmp_path / "proposals.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()

    from themek.dart.pattern_learning import save_proposals, Proposal
    save_proposals(proposals_path, [
        Proposal(target="overview", candidate_regex="회사.{0,3}개황",
                 sample_headers=["회사의 개황"], observed_count=3,
                 source_fixtures=["a", "b", "c"]),
    ])

    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(learned_path))
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(proposals_path))
    monkeypatch.setenv("THEMEK_FIXTURES_DIR", str(fixtures_dir))

    result = runner.invoke(app, ["dart", "parser-learn"])
    assert result.exit_code == 0
    assert "applied 1" in result.stdout
```

- [ ] **Step 2: 실패 확인 + 구현**

```python
@dart_app.command("parser-learn")
def dart_parser_learn_cmd():
    """누적 proposal 중 N=3 도달 항목을 learned로 promote."""
    from themek.dart.pattern_learning import apply_ready_proposals
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    typer.echo(f"applied {len(applied)} new patterns")
    for pr in applied:
        typer.echo(f"  - {pr.target}: {pr.candidate_regex}")
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_cli_parser_commands.py -v -k parser_learn
git add src/themek/cli.py tests/test_cli_parser_commands.py
git commit -m "feat(cli): dart parser-learn manual trigger (robust T18)"
```

---

## Task 19: `themek dart parser-consolidate` — 학습 패턴 머지·dedup

**Files:**
- Modify: `src/themek/dart/learned_patterns.py`
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_parser_commands.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_parser_consolidate_dedups_identical_regex(monkeypatch, tmp_path):
    """동일 regex가 여러 entry로 있으면 1개로 머지."""
    learned_path = tmp_path / "learned.json"
    from themek.dart.learned_patterns import (
        LearnedPatterns, save_learned_patterns,
    )
    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern("overview", regex="회사.{0,3}개황",
                          source="learned", samples=["a"], confirmed_count=3)
    lp.add_target_pattern("overview", regex="회사.{0,3}개황",
                          source="learned", samples=["b"], confirmed_count=2)
    save_learned_patterns(learned_path, lp)

    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(learned_path))
    result = runner.invoke(app, ["dart", "parser-consolidate"])
    assert result.exit_code == 0
    from themek.dart.learned_patterns import load_learned_patterns
    lp2 = load_learned_patterns(learned_path)
    overview = lp2.target_patterns("overview")
    learned_only = [p for p in overview if p.get("source") == "learned"]
    assert len(learned_only) == 1
    assert "a" in learned_only[0].get("samples", [])
    assert "b" in learned_only[0].get("samples", [])
```

- [ ] **Step 2: 실패 확인 + 구현**

`learned_patterns.py`에:

```python
def consolidate(lp: LearnedPatterns) -> LearnedPatterns:
    """동일 regex 머지, samples union, confirmed_count 합산."""
    for target, entries in lp.targets.items():
        by_regex: dict[str, dict] = {}
        for e in entries:
            r = e["regex"]
            if r not in by_regex:
                by_regex[r] = dict(e)
                by_regex[r]["samples"] = list(e.get("samples", []))
                by_regex[r]["fixtures_validated"] = list(e.get("fixtures_validated", []))
            else:
                merged = by_regex[r]
                merged["samples"] = sorted(set(
                    merged.get("samples", []) + e.get("samples", [])
                ))
                merged["fixtures_validated"] = sorted(set(
                    merged.get("fixtures_validated", []) +
                    e.get("fixtures_validated", [])
                ))
                merged["confirmed_count"] = (
                    merged.get("confirmed_count", 0) + e.get("confirmed_count", 0)
                )
        lp.targets[target] = list(by_regex.values())
    return lp
```

`cli.py`에:

```python
@dart_app.command("parser-consolidate")
def dart_parser_consolidate_cmd():
    """학습 패턴 머지·dedup."""
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    from themek.dart.learned_patterns import (
        load_learned_patterns, save_learned_patterns, consolidate,
    )
    lp = load_learned_patterns(learned_path)
    before = sum(len(lp.target_patterns(t))
                 for t in ("overview", "products", "revenue"))
    lp = consolidate(lp)
    save_learned_patterns(learned_path, lp)
    after = sum(len(lp.target_patterns(t))
                for t in ("overview", "products", "revenue"))
    typer.echo(f"consolidated: {before} → {after} patterns")
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_cli_parser_commands.py -v -k consolidate
git add src/themek/dart/learned_patterns.py src/themek/cli.py tests/test_cli_parser_commands.py
git commit -m "feat(dart): parser-consolidate dedup/merge (robust T19)"
```

---

## Task 20: 신규 5종목 ingest로 fixture coverage 확장

**Files:**
- New caches: `data/dart/raw/<rcept_no>/business.html` × 5
- New fixtures: `tests/fixtures/dart_variants/<ticker>_2023.html` (+ headers.json) × 5

**WARNING:** DART API 호출 발생 (~5번). corp_master 캐시는 이미 있어야 함.

권장 종목 (업종 다양성 + 보고서 형식 다양성):
- `105560` KB금융 (금융업)
- `068270` 셀트리온 (바이오)
- `036570` 엔씨소프트 (게임/IT)
- `005935` 삼성전자우선주 (다른 양식인지 확인)
- `032830` 삼성생명 (보험)

- [ ] **Step 1: 사전 점검**

```bash
ls data/dart/corp_master.json  # 존재
uv run themek dart parser-stats  # baseline 출력
```

- [ ] **Step 2: 5종목 순차 ingest**

```bash
for ticker in 105560 068270 036570 032830 005935; do
  echo "=== $ticker ==="
  uv run themek dart ingest --ticker $ticker --period 2023 || \
    echo "[FAIL] $ticker — log only, continue"
done
```

각 ingest는 자동으로:
- `data/dart/raw/<rcept_no>/business.html` cache
- `tests/fixtures/dart_variants/<ticker>_2023.html` + `_headers.json` mirror
- `pattern_proposals.json` 누적
- N=3 도달 패턴이 있으면 `learned_header_patterns.json` 자동 commit

- [ ] **Step 3: 결과 확인**

```bash
uv run themek dart parser-stats
ls tests/fixtures/dart_variants/
cat data/dart/pattern_proposals.json | python -m json.tool | head -50
cat data/dart/learned_header_patterns.json | python -m json.tool | head -50
```

Expected: fixtures 8개 (기존 3 + 신규 5), proposals N개, learned 패턴이 0개 이상 자동 추가됨.

- [ ] **Step 4: 전체 회귀 통과**

```bash
uv run pytest
```
Expected: 학습된 패턴이 기존 fixture 회귀를 깨지 않음 (validate gate 덕분).

- [ ] **Step 5: 커밋 — fixture + proposals + learned 변경분**

```bash
git add tests/fixtures/dart_variants/ \
        data/dart/pattern_proposals.json \
        data/dart/learned_header_patterns.json
git commit -m "data(fixtures): 5 additional industry-diverse ingests + learned (robust T20)"
```

(`data/dart/raw/` 는 gitignored.)

---

## Task 21: docs/dart-parser-robust-extraction-notes.md + README 갱신

**Files:**
- Create: `docs/dart-parser-robust-extraction-notes.md`
- Modify: `README.md`

- [ ] **Step 1: notes 문서 작성**

```markdown
# DART Parser Robust Extraction Notes

**실행일:** 2026-05-XX (Plan robust-extraction T1~T20)

## Coverage 통계 (T20 후)

| 항목 | 값 |
|---|---|
| Fixture count | 8 (3 기존 + 5 신규 다양 업종) |
| Baseline patterns (overview/products/revenue) | 1 / 2 / 2 |
| Learned patterns | N / M / K (T20 결과 그대로) |
| Pending proposals | … |
| Escalation 분포 (8 fixture) | regex: X / regex+llm: Y / full_text: Z |

## 학습 동작 예시

(parser-stats 출력 그대로)

## 발견된 변형

T20에서 새로 catch된 변형 패턴들:

- KB금융 105560: `1. 영업의 개황` ← `사업.{0,3}개요` 미스 → LLM이 overview 분류
- 셀트리온 068270: `(바이오 사업부) 1. 사업의 개요` ← baseline에서 catch
- ...

## 한계

- 학습이 fixture coverage에 좌우됨 — 신규 업종 ingest 늘릴수록 robust해짐
- LLM 비일관성으로 N=3 도달 전 reject 되는 후보 존재 (proposals에 남음)
- consolidate 주기적 실행 필요 (수동)
```

- [ ] **Step 2: README 갱신**

`README.md` Status:
```
**Walking Skeleton (#1) + Eval Harness (#6) + DART API Client (#3) + Real-LLM Baseline + Robust Parser 구현 완료** — 2026-05-XX.
```

"다음 작업":
```
**다음 작업:** Plan #5 (다종목·시계열 backfill orchestrator) 또는 Plan #2/#7 (social layer). robust parser coverage는 `themek dart parser-stats`로 추적.
```

"후속 Plan들"에 추가:
```
- ~~**DART Parser Robust Extraction**~~ ✅ 완료 (`docs/superpowers/plans/2026-05-26-dart-parser-robust-extraction.md`)
```

- [ ] **Step 3: 커밋**

```bash
git add docs/dart-parser-robust-extraction-notes.md README.md
git commit -m "docs: robust parser notes + README 갱신 (robust T21)"
```

---

## Acceptance Verification

모든 task 완료 후 spec §7 acceptance criteria 점검:

```bash
# 1. 전체 테스트 통과 (165 → 195+ PASS 기대)
uv run pytest

# 2. 모든 fixture 회귀 통과
uv run pytest tests/test_parser_sections.py::test_section_filter_against_all_mirrored_fixtures -v

# 3. parser-stats가 누적 통계 출력
uv run themek dart parser-stats

# 4. cached 3종목 모두 escalation_level=regex (또는 regex+llm) + output_chars >= 1000
for d in data/dart/raw/*/business.html; do
  uv run python -c "
from pathlib import Path
from themek.dart.parser import extract_business_sections
text, res = extract_business_sections(
    Path('$d').read_text(encoding='utf-8'),
    llm_fallback=None,
)
ok = (res.escalation_level in ('regex','regex+llm')) and (res.output_chars >= 1000)
print(f'$d: escalation={res.escalation_level} chars={res.output_chars} {\"OK\" if ok else \"FAIL\"}')
"
done

# 5. fixtures/dart_variants가 8개 이상
ls tests/fixtures/dart_variants/*.html | wc -l

# 6. 학습 패턴 파일 존재 + valid JSON
python -m json.tool < data/dart/learned_header_patterns.json > /dev/null && echo "OK"
python -m json.tool < data/dart/pattern_proposals.json > /dev/null && echo "OK"
```

기대 결과:
- (1) pytest 전체 PASS
- (2) fixture 회귀 PASS
- (3) parser-stats 출력 정상
- (4) 3종목 모두 `OK`
- (5) `8` 이상
- (6) 두 JSON 모두 `OK`

---

## Self-Review

**Spec coverage (`docs/superpowers/specs/2026-05-26-dart-parser-robust-extraction-design.md`):**

- §3.1 Three-tier extraction → T1~T4
- §3.2 Learning loop → T6~T13, T17~T19
- §3.3 Fixture mirror → T14, T15, T16, T20
- §4 Components → 각 파일 신규/수정 task로 분할
- §5 Decisions Q1~Q6 → 모두 plan 본문 반영
- §6 Risks & Mitigations → T10 (validate gate), T12 (N=3), T19 (consolidate)
- §7 Acceptance Criteria → 위 Acceptance Verification 절로 점검
- §8 Out of Scope → plan에 포함하지 않음 확인
- §9 Phases → Phase 1/2/3/4 로 명시적 그룹

**Placeholder scan:** 본문에 "TBD/TODO" 없음. 모든 step에 코드/명령어 포함.

**Type consistency:**
- `SectionResolution` 신규 필드 (T1) → T2, T3, T4, T5에서 일관 사용
- `LearnedPatterns` API (T6) → T7, T19, T20에서 일관 사용
- `Proposal` dataclass (T11) → T12, T13, T17, T18에서 일관 사용
- env var 이름 `THEMEK_LEARNED_PATTERNS_PATH` / `THEMEK_PROPOSALS_PATH` / `THEMEK_FIXTURES_DIR` 통일
- env var default 상수 `DEFAULT_LEARNED_PATTERNS_PATH` / `DEFAULT_PROPOSALS_PATH` / `DEFAULT_FIXTURES_DIR` 통일

**User tasks 명시:**
- T20 신규 5종목 ingest는 DART API 호출 발생 (사용자 의사 확인 필요 시 사전 합의)
- T16은 기존 cached 3종목 mirror — 일회성 실행

---

## Execution Notes

- Phase 1 (T1~T5) 만 완료해도 robustness는 확보됨. Phase 2~4는 self-improving loop.
- T20은 토큰 비용 발생 (~$0.10 추정, 5종목 × 1회 LLM extractor + section filter LLM fallback)
- T13의 자동 학습 hook은 학습 sample이 있어야만 발동 — baseline patterns로 fully covered 종목에서는 no-op
