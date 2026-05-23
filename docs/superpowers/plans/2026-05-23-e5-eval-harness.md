# E5 Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사업보고서에서 LLM이 추출한 결과를 사람이 작성한 ground truth와 비교해 4개 metric(segment / customer / region 정확도 + share_pct MAE)을 산출하는 CLI 명령(`themek eval e5`)을 구현한다.

**Architecture:** 새 패키지 `src/themek/eval/`에 `e5.py` 한 파일로 모든 metric 함수 + `EvalResult` dataclass + `evaluate_e5()` 통합 함수를 두고, CLI는 ingest의 stub-extractor 패턴(`THEMEK_STUB_EXTRACTION_FILE` env var)을 재사용해 LLM 호출 단계를 테스트 가능하게 한다. ground truth는 `data/eval/ground_truth/<ticker>_e5_<period>.json` — metadata wrapper + `BusinessExtraction` schema 재사용.

**Tech Stack:** Python 3.12+, pytest, typer, Pydantic v2, Jinja2 (text formatter는 단순 f-string, Jinja 불필요).

**Spec:** `docs/superpowers/specs/2026-05-23-e5-eval-harness-design.md` (commit 6a798bc)

---

## Prerequisites

- Walking skeleton (Plan #1) 완료 — `src/themek/ingest/business_report.py`, `src/themek/llm/schemas.py`, `src/themek/cli.py` 이미 존재
- 이슈 #1 (conftest 격리) + 이슈 #2 (region dedup) commit 완료
- claude CLI 로그인 상태 (T12 smoke run에서만 필요)

## Scope (in / out)

**In:**
- `src/themek/eval/e5.py` 1개 파일: 7개 metric 함수 + `EvalResult` dataclass + `evaluate_e5()` + `load_ground_truth()` + `format_eval_result_text()`
- `themek eval e5` CLI 서브커맨드
- ground truth 1건 (`data/eval/ground_truth/samsung_e5_2023.json`)
- ~20개 unit / integration / CLI 테스트
- smoke run baseline 기록

**Out:** N회 run 평균 / pass-fail 임계값 / 다른 CQ evaluator / CI 통합 / JSON output / fuzzy matching / 다종목 batch — 모두 spec section 3.2 참조.

## File Structure

```
themek/
├── src/themek/
│   ├── eval/
│   │   ├── __init__.py            # 빈 패키지 파일
│   │   └── e5.py                  # EvalResult + metric 함수 + evaluate_e5
│   └── cli.py                     # 수정: eval 서브커맨드 추가
├── tests/
│   ├── test_eval_e5_metrics.py    # pure 함수 unit test
│   ├── test_eval_e5_integration.py # evaluate_e5 통합
│   └── test_cli_eval.py           # CLI typer test (stub mode)
├── data/
│   └── eval/
│       └── ground_truth/
│           └── samsung_e5_2023.json  # 사용자 작성, git tracked
├── docs/
│   └── eval-e5-smoke-run-notes.md # baseline 기록
└── README.md                       # 수정: Plan #6 항목 갱신
```

---

## Task 1: eval 모듈 골격 + EvalResult dataclass

**Files:**
- Create: `src/themek/eval/__init__.py`
- Create: `src/themek/eval/e5.py`
- Create: `tests/test_eval_e5_metrics.py`

- [ ] **Step 1: 빈 패키지 파일 생성**

```bash
mkdir -p src/themek/eval
touch src/themek/eval/__init__.py
```

- [ ] **Step 2: EvalResult 사용을 검증하는 실패 테스트**

`tests/test_eval_e5_metrics.py`:

```python
from themek.eval.e5 import EvalResult


def test_eval_result_default_construction():
    r = EvalResult()
    assert r.segment_recall is None
    assert r.segment_precision is None
    assert r.customer_recall is None
    assert r.customer_precision is None
    assert r.region_recall is None
    assert r.region_precision is None
    assert r.share_pct_mae is None
    assert r.matched_segment_count == 0
    assert r.truth_segment_count == 0
    assert r.extracted_segment_count == 0
    assert r.missed_segments == []
    assert r.extra_segments == []
    assert r.missed_customers == []
    assert r.extra_customers == []
    assert r.missed_regions == []
    assert r.extra_regions == []
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
uv run pytest tests/test_eval_e5_metrics.py::test_eval_result_default_construction -v
```
Expected: `ImportError` — `EvalResult`가 아직 정의 안 됨.

- [ ] **Step 4: `src/themek/eval/e5.py` 작성**

```python
"""E5 evaluation harness — 추출 결과를 ground truth와 비교한다.

Spec: docs/superpowers/specs/2026-05-23-e5-eval-harness-design.md
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EvalResult:
    """E5 evaluation 결과 컨테이너."""
    segment_recall: Optional[float] = None
    segment_precision: Optional[float] = None
    customer_recall: Optional[float] = None
    customer_precision: Optional[float] = None
    region_recall: Optional[float] = None
    region_precision: Optional[float] = None
    share_pct_mae: Optional[float] = None
    matched_segment_count: int = 0
    truth_segment_count: int = 0
    extracted_segment_count: int = 0
    missed_segments: list[str] = field(default_factory=list)
    extra_segments: list[str] = field(default_factory=list)
    missed_customers: list[str] = field(default_factory=list)
    extra_customers: list[str] = field(default_factory=list)
    missed_regions: list[str] = field(default_factory=list)
    extra_regions: list[str] = field(default_factory=list)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/test_eval_e5_metrics.py::test_eval_result_default_construction -v
```
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/themek/eval/__init__.py src/themek/eval/e5.py tests/test_eval_e5_metrics.py
git commit -m "feat(eval): add EvalResult dataclass skeleton (Plan #6 T1)"
```

---

## Task 2: segment recall / precision

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_e5_metrics.py`

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_eval_e5_metrics.py`):

```python
from themek.llm.schemas import BusinessExtraction
from themek.eval.e5 import segment_metrics


def _ext(segments):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": segments,
        "customers": [], "geographic": [],
    })


def test_segment_perfect_match():
    truth = _ext([{"name_ko": "메모리", "share_pct": 20.0}])
    ext = _ext([{"name_ko": "메모리", "share_pct": 20.0}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 1.0
    assert matched == ["메모리"]
    assert missed == []
    assert extra == []


def test_segment_missing():
    truth = _ext([{"name_ko": "메모리"}, {"name_ko": "MX"}])
    ext = _ext([{"name_ko": "메모리"}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 0.5
    assert precision == 1.0
    assert missed == ["MX"]
    assert extra == []


def test_segment_extra():
    truth = _ext([{"name_ko": "메모리"}])
    ext = _ext([{"name_ko": "메모리"}, {"name_ko": "환각"}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 0.5
    assert extra == ["환각"]


def test_segment_empty_extracted():
    truth = _ext([{"name_ko": "메모리"}])
    ext = _ext([])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 0.0
    assert precision is None  # 0/0
    assert missed == ["메모리"]


def test_segment_empty_truth():
    truth = _ext([])
    ext = _ext([{"name_ko": "환각"}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall is None  # 0/0
    assert precision == 0.0
    assert extra == ["환각"]
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_eval_e5_metrics.py -v -k segment_
```
Expected: 5건 ImportError on `segment_metrics`.

- [ ] **Step 3: 구현 추가** (`src/themek/eval/e5.py`):

```python
from themek.llm.schemas import BusinessExtraction


def _safe_div(num: int, den: int) -> Optional[float]:
    return None if den == 0 else num / den


def segment_metrics(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], Optional[float], list[str], list[str], list[str]]:
    """segment recall/precision + matched/missed/extra 이름 리스트.

    매칭 기준: name_ko exact match.
    Returns: (recall, precision, matched_names, missed_names, extra_names)
    """
    truth_names = [s.name_ko for s in truth.segments]
    ext_names = [s.name_ko for s in extracted.segments]
    truth_set = set(truth_names)
    ext_set = set(ext_names)
    matched = sorted(truth_set & ext_set)
    missed = sorted(truth_set - ext_set)
    extra = sorted(ext_set - truth_set)
    recall = _safe_div(len(matched), len(truth_set))
    precision = _safe_div(len(matched), len(ext_set))
    return recall, precision, matched, missed, extra
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_eval_e5_metrics.py -v -k segment_
```
Expected: 5 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/eval/e5.py tests/test_eval_e5_metrics.py
git commit -m "feat(eval): segment recall/precision (Plan #6 T2)"
```

---

## Task 3: customer recall / precision (case-insensitive)

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_e5_metrics.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from themek.eval.e5 import customer_metrics


def _cust_ext(customers):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": [],
        "customers": customers, "geographic": [],
    })


def test_customer_case_insensitive_match():
    truth = _cust_ext([{"name_raw": "Apple Inc.", "tier": "1차"}])
    ext = _cust_ext([{"name_raw": "apple inc.", "tier": "1차"}])
    recall, precision, matched, missed, extra = customer_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 1.0
    assert matched == ["Apple Inc."]  # truth 표기 유지


def test_customer_missing():
    truth = _cust_ext([
        {"name_raw": "Apple Inc.", "tier": "1차"},
        {"name_raw": "삼성디스플레이", "tier": "1차"},
    ])
    ext = _cust_ext([{"name_raw": "Apple Inc.", "tier": "1차"}])
    recall, precision, _, missed, extra = customer_metrics(ext, truth)
    assert recall == 0.5
    assert missed == ["삼성디스플레이"]


def test_customer_extra():
    truth = _cust_ext([{"name_raw": "Apple Inc.", "tier": "1차"}])
    ext = _cust_ext([
        {"name_raw": "Apple Inc.", "tier": "1차"},
        {"name_raw": "환각고객사", "tier": "unknown"},
    ])
    recall, precision, _, _, extra = customer_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 0.5
    assert extra == ["환각고객사"]


def test_customer_empty_both():
    truth = _cust_ext([])
    ext = _cust_ext([])
    recall, precision, _, missed, extra = customer_metrics(ext, truth)
    assert recall is None
    assert precision is None
    assert missed == []
    assert extra == []
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_eval_e5_metrics.py -v -k customer_
```
Expected: ImportError.

- [ ] **Step 3: 구현 추가**

```python
def customer_metrics(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], Optional[float], list[str], list[str], list[str]]:
    """customer recall/precision + 진단 리스트.

    매칭 기준: name_raw case-insensitive exact.
    missed/extra 리스트는 truth/extracted의 원래 표기를 보존한다.
    """
    truth_pairs = [(c.name_raw.lower(), c.name_raw) for c in truth.customers]
    ext_pairs = [(c.name_raw.lower(), c.name_raw) for c in extracted.customers]
    truth_keys = {k for k, _ in truth_pairs}
    ext_keys = {k for k, _ in ext_pairs}
    matched_keys = truth_keys & ext_keys
    matched_names = sorted({orig for k, orig in truth_pairs if k in matched_keys})
    missed = sorted({orig for k, orig in truth_pairs if k not in matched_keys})
    extra = sorted({orig for k, orig in ext_pairs if k not in matched_keys})
    recall = _safe_div(len(matched_keys), len(truth_keys))
    precision = _safe_div(len(matched_keys), len(ext_keys))
    return recall, precision, matched_names, missed, extra
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_eval_e5_metrics.py -v -k customer_
```

```bash
git add src/themek/eval/e5.py tests/test_eval_e5_metrics.py
git commit -m "feat(eval): customer recall/precision case-insensitive (Plan #6 T3)"
```

---

## Task 4: region recall / precision

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_e5_metrics.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from themek.eval.e5 import region_metrics


def _geo_ext(geo):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": [],
        "customers": [], "geographic": geo,
    })


def test_region_perfect_match():
    truth = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "ROW", "share_pct": 19.2},
    ])
    ext = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "ROW", "share_pct": 19.2},
    ])
    recall, precision, matched, missed, extra = region_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 1.0
    assert sorted(matched) == ["KR", "ROW"]


def test_region_missing_and_extra():
    truth = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "US", "share_pct": 35.6},
    ])
    ext = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "ROW", "share_pct": 50.0},  # 환각
    ])
    recall, precision, _, missed, extra = region_metrics(ext, truth)
    assert recall == 0.5
    assert precision == 0.5
    assert missed == ["US"]
    assert extra == ["ROW"]
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현 추가**

```python
def region_metrics(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], Optional[float], list[str], list[str], list[str]]:
    """region recall/precision + 진단 리스트. 매칭: region_code exact."""
    truth_codes = {g.region_code for g in truth.geographic}
    ext_codes = {g.region_code for g in extracted.geographic}
    matched = sorted(truth_codes & ext_codes)
    missed = sorted(truth_codes - ext_codes)
    extra = sorted(ext_codes - truth_codes)
    recall = _safe_div(len(matched), len(truth_codes))
    precision = _safe_div(len(matched), len(ext_codes))
    return recall, precision, matched, missed, extra
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/themek/eval/e5.py tests/test_eval_e5_metrics.py
git commit -m "feat(eval): region recall/precision (Plan #6 T4)"
```

---

## Task 5: share_pct MAE

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_e5_metrics.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from themek.eval.e5 import share_pct_mae


def test_share_pct_mae_basic():
    truth = _ext([
        {"name_ko": "메모리", "share_pct": 20.0},
        {"name_ko": "MX", "share_pct": 40.0},
    ])
    ext = _ext([
        {"name_ko": "메모리", "share_pct": 21.5},  # +1.5
        {"name_ko": "MX", "share_pct": 35.5},      # -4.5
    ])
    mae, matched_count = share_pct_mae(ext, truth)
    assert abs(mae - 3.0) < 0.001  # (1.5+4.5)/2
    assert matched_count == 2


def test_share_pct_mae_no_matched_segments():
    truth = _ext([{"name_ko": "메모리", "share_pct": 20.0}])
    ext = _ext([{"name_ko": "환각", "share_pct": 99.0}])
    mae, matched_count = share_pct_mae(ext, truth)
    assert mae is None
    assert matched_count == 0


def test_share_pct_mae_excludes_null_truth_share():
    truth = _ext([
        {"name_ko": "메모리", "share_pct": 20.0},
        {"name_ko": "기타", "share_pct": None},
    ])
    ext = _ext([
        {"name_ko": "메모리", "share_pct": 22.0},  # +2.0
        {"name_ko": "기타", "share_pct": 5.0},
    ])
    mae, matched_count = share_pct_mae(ext, truth)
    assert mae == 2.0  # 기타는 분모/분자 둘 다 제외
    assert matched_count == 1


def test_share_pct_mae_excludes_null_extracted_share():
    # truth는 있는데 extracted가 null인 경우도 MAE 분모에서 제외
    truth = _ext([
        {"name_ko": "메모리", "share_pct": 20.0},
        {"name_ko": "MX", "share_pct": 40.0},
    ])
    ext = _ext([
        {"name_ko": "메모리", "share_pct": 22.0},  # +2.0
        {"name_ko": "MX", "share_pct": None},
    ])
    mae, matched_count = share_pct_mae(ext, truth)
    assert mae == 2.0
    assert matched_count == 1
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현 추가**

```python
def share_pct_mae(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], int]:
    """matched segment의 share_pct 평균 절대 오차.

    truth.share_pct 또는 extracted.share_pct가 null이면 그 segment는 제외.
    matched(양쪽 share_pct 모두 존재) segment가 0개이면 (None, 0) 반환.
    """
    truth_share = {s.name_ko: s.share_pct for s in truth.segments}
    ext_share = {s.name_ko: s.share_pct for s in extracted.segments}
    diffs: list[float] = []
    for name_ko, t_share in truth_share.items():
        if t_share is None:
            continue
        e_share = ext_share.get(name_ko)
        if e_share is None:
            continue
        diffs.append(abs(float(e_share) - float(t_share)))
    if not diffs:
        return None, 0
    return sum(diffs) / len(diffs), len(diffs)
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/themek/eval/e5.py tests/test_eval_e5_metrics.py
git commit -m "feat(eval): share_pct MAE with null-share exclusion (Plan #6 T5)"
```

---

## Task 6: evaluate_e5() 통합 함수

**Files:**
- Modify: `src/themek/eval/e5.py`
- Create: `tests/test_eval_e5_integration.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_eval_e5_integration.py`:

```python
from themek.llm.schemas import BusinessExtraction
from themek.eval.e5 import evaluate_e5, EvalResult


def _full(segments, customers, geo):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": segments,
        "customers": customers, "geographic": geo,
    })


def test_evaluate_e5_perfect_match():
    payload = {
        "segments": [
            {"name_ko": "메모리", "share_pct": 20.0, "products": []},
            {"name_ko": "MX", "share_pct": 35.0, "products": []},
        ],
        "customers": [{"name_raw": "Apple Inc.", "tier": "1차"}],
        "geo": [{"region_code": "KR", "share_pct": 50.0}],
    }
    truth = _full(payload["segments"], payload["customers"], payload["geo"])
    ext = _full(payload["segments"], payload["customers"], payload["geo"])
    result = evaluate_e5(ext, truth)
    assert isinstance(result, EvalResult)
    assert result.segment_recall == 1.0
    assert result.segment_precision == 1.0
    assert result.customer_recall == 1.0
    assert result.customer_precision == 1.0
    assert result.region_recall == 1.0
    assert result.region_precision == 1.0
    assert result.share_pct_mae == 0.0
    assert result.matched_segment_count == 2
    assert result.truth_segment_count == 2
    assert result.extracted_segment_count == 2
    assert result.missed_segments == []
    assert result.extra_segments == []


def test_evaluate_e5_partial():
    truth = _full(
        [{"name_ko": "메모리", "share_pct": 20.0},
         {"name_ko": "MX", "share_pct": 40.0}],
        [{"name_raw": "Apple Inc.", "tier": "1차"}],
        [{"region_code": "KR", "share_pct": 50.0},
         {"region_code": "US", "share_pct": 50.0}],
    )
    ext = _full(
        [{"name_ko": "메모리", "share_pct": 22.0},  # +2.0
         {"name_ko": "환각", "share_pct": 10.0}],
        [],
        [{"region_code": "KR", "share_pct": 100.0}],
    )
    result = evaluate_e5(ext, truth)
    assert result.segment_recall == 0.5
    assert result.segment_precision == 0.5
    assert result.customer_recall == 0.0
    assert result.customer_precision is None
    assert result.region_recall == 0.5
    assert result.region_precision == 1.0
    assert result.share_pct_mae == 2.0
    assert result.missed_segments == ["MX"]
    assert result.extra_segments == ["환각"]
    assert result.missed_customers == ["Apple Inc."]
    assert result.missed_regions == ["US"]
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_eval_e5_integration.py -v
```
Expected: ImportError on `evaluate_e5`.

- [ ] **Step 3: 구현 추가** (`src/themek/eval/e5.py`):

```python
def evaluate_e5(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> EvalResult:
    """추출 결과와 ground truth를 비교해 EvalResult를 반환한다."""
    seg_r, seg_p, seg_matched, seg_missed, seg_extra = segment_metrics(extracted, truth)
    cust_r, cust_p, _, cust_missed, cust_extra = customer_metrics(extracted, truth)
    reg_r, reg_p, _, reg_missed, reg_extra = region_metrics(extracted, truth)
    mae, mae_count = share_pct_mae(extracted, truth)
    return EvalResult(
        segment_recall=seg_r,
        segment_precision=seg_p,
        customer_recall=cust_r,
        customer_precision=cust_p,
        region_recall=reg_r,
        region_precision=reg_p,
        share_pct_mae=mae,
        matched_segment_count=len(seg_matched),
        truth_segment_count=len(truth.segments),
        extracted_segment_count=len(extracted.segments),
        missed_segments=seg_missed,
        extra_segments=seg_extra,
        missed_customers=cust_missed,
        extra_customers=cust_extra,
        missed_regions=reg_missed,
        extra_regions=reg_extra,
    )
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_eval_e5_integration.py -v
git add src/themek/eval/e5.py tests/test_eval_e5_integration.py
git commit -m "feat(eval): evaluate_e5 integration assembling EvalResult (Plan #6 T6)"
```

---

## Task 7: ground truth JSON loader (metadata wrapper)

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_e5_integration.py`
- Create: `tests/fixtures/sample_ground_truth.json`

- [ ] **Step 1: fixture JSON 만들기**

`tests/fixtures/sample_ground_truth.json`:

```json
{
  "metadata": {
    "ticker": "999999",
    "name_ko": "테스트회사",
    "period": "2023",
    "source_rcept_no": "00000000000000",
    "fixture_path": "n/a",
    "created_at": "2026-05-23",
    "notes": "loader 테스트용"
  },
  "extraction": {
    "period": "2023",
    "segments": [{"name_ko": "테스트부문", "share_pct": 100.0, "products": []}],
    "customers": [],
    "geographic": [{"region_code": "KR", "share_pct": 100.0}]
  }
}
```

- [ ] **Step 2: 실패 테스트 추가** (`tests/test_eval_e5_integration.py`):

```python
from pathlib import Path
from themek.eval.e5 import load_ground_truth

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ground_truth.json"


def test_load_ground_truth_returns_extraction():
    extraction, metadata = load_ground_truth(FIXTURE)
    assert isinstance(extraction, BusinessExtraction)
    assert extraction.period == "2023"
    assert extraction.segments[0].name_ko == "테스트부문"
    assert metadata["ticker"] == "999999"
    assert metadata["name_ko"] == "테스트회사"


def test_load_ground_truth_file_not_found(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_ground_truth(tmp_path / "missing.json")


def test_load_ground_truth_invalid_schema(tmp_path):
    """ground truth가 BusinessExtraction 스키마를 위반하면 ValidationError."""
    import pytest
    from pydantic import ValidationError
    bad = tmp_path / "bad.json"
    bad.write_text("""
    {
      "metadata": {"ticker": "x"},
      "extraction": {
        "period": "2023",
        "segments": [],
        "customers": [],
        "geographic": [{"region_code": "XX", "share_pct": 100.0}]
      }
    }
    """, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_ground_truth(bad)
```

- [ ] **Step 3: 실패 확인**

- [ ] **Step 4: 구현 추가** (`src/themek/eval/e5.py`):

```python
import json
from pathlib import Path


def load_ground_truth(
    path: Path | str,
) -> tuple[BusinessExtraction, dict]:
    """ground truth JSON을 (BusinessExtraction, metadata dict)로 로드."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"ground truth not found: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    metadata = payload.get("metadata", {})
    extraction = BusinessExtraction.model_validate(payload["extraction"])
    return extraction, metadata
```

- [ ] **Step 5: 통과 확인 + 커밋**

```bash
git add src/themek/eval/e5.py tests/test_eval_e5_integration.py tests/fixtures/sample_ground_truth.json
git commit -m "feat(eval): load_ground_truth JSON loader (Plan #6 T7)"
```

---

## Task 8: format_eval_result_text() — CLI 출력 formatter

**Files:**
- Modify: `src/themek/eval/e5.py`
- Modify: `tests/test_eval_e5_integration.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
from themek.eval.e5 import format_eval_result_text


def test_format_eval_result_perfect():
    result = EvalResult(
        segment_recall=1.0, segment_precision=1.0,
        customer_recall=1.0, customer_precision=1.0,
        region_recall=1.0, region_precision=1.0,
        share_pct_mae=0.0,
        matched_segment_count=6,
        truth_segment_count=6, extracted_segment_count=6,
    )
    metadata = {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"}
    text = format_eval_result_text(
        result, metadata=metadata,
        ground_truth_path="data/eval/ground_truth/samsung_e5_2023.json",
        html_path="tests/fixtures/samsung_business_report_excerpt.html",
    )
    assert "삼성전자" in text
    assert "005930" in text
    assert "period=2023" in text
    assert "Segments" in text
    assert "1.000" in text
    assert "0.00 %p" in text
    assert "matched=6" in text


def test_format_eval_result_with_missed_and_extra():
    result = EvalResult(
        segment_recall=0.833, segment_precision=0.714,
        share_pct_mae=2.45,
        matched_segment_count=5,
        truth_segment_count=6, extracted_segment_count=7,
        missed_segments=["Harman"],
        extra_segments=["반도체장비", "디지털전환솔루션"],
    )
    metadata = {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"}
    text = format_eval_result_text(
        result, metadata=metadata,
        ground_truth_path="x", html_path="y",
    )
    assert "Missed" in text
    assert "Harman" in text
    assert "반도체장비" in text


def test_format_eval_result_handles_none_scores():
    result = EvalResult(
        segment_recall=None, segment_precision=None,
        customer_recall=None, customer_precision=None,
        region_recall=None, region_precision=None,
        share_pct_mae=None,
    )
    metadata = {"ticker": "x", "name_ko": "x", "period": "x"}
    text = format_eval_result_text(
        result, metadata=metadata, ground_truth_path="x", html_path="x",
    )
    assert "n/a" in text  # None은 'n/a'로 표시
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현 추가**

```python
def _fmt_score(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _fmt_ratio(num: int, den: int) -> str:
    return f"{num}/{den}" if den > 0 else "0/0"


def format_eval_result_text(
    result: EvalResult,
    *,
    metadata: dict,
    ground_truth_path: str,
    html_path: str,
) -> str:
    """EvalResult를 사람이 읽기 좋은 점수표 텍스트로 변환."""
    ticker = metadata.get("ticker", "?")
    name_ko = metadata.get("name_ko", "?")
    period = metadata.get("period", "?")
    mae_str = "n/a" if result.share_pct_mae is None else f"{result.share_pct_mae:.2f} %p"
    lines = [
        f"=== Eval: E5 — {name_ko} ({ticker}) period={period} ===",
        f"Ground truth:  {ground_truth_path}",
        f"HTML fixture:  {html_path}",
        "",
        f"Segments        recall= "
        f"{_fmt_ratio(result.matched_segment_count, result.truth_segment_count)} "
        f"= {_fmt_score(result.segment_recall)}    "
        f"precision= "
        f"{_fmt_ratio(result.matched_segment_count, result.extracted_segment_count)} "
        f"= {_fmt_score(result.segment_precision)}",
        f"Customers       recall= {_fmt_score(result.customer_recall)}    "
        f"precision= {_fmt_score(result.customer_precision)}",
        f"Regions         recall= {_fmt_score(result.region_recall)}    "
        f"precision= {_fmt_score(result.region_precision)}",
        f"Share_pct MAE   {mae_str} (matched={result.matched_segment_count})",
        "",
        "Missed (truth에 있는데 LLM이 놓침):",
        f"  segments:  {result.missed_segments}",
        f"  customers: {result.missed_customers}",
        f"  regions:   {result.missed_regions}",
        "",
        "Extra (LLM이 만들었는데 truth엔 없음):",
        f"  segments:  {result.extra_segments}",
        f"  customers: {result.extra_customers}",
        f"  regions:   {result.extra_regions}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/themek/eval/e5.py tests/test_eval_e5_integration.py
git commit -m "feat(eval): format_eval_result_text CLI output (Plan #6 T8)"
```

---

## Task 9: CLI 명령 `themek eval e5` 추가 + stub mode

**Files:**
- Modify: `src/themek/cli.py`
- Create: `tests/test_cli_eval.py`

- [ ] **Step 1: CLI 실패 테스트 작성**

`tests/test_cli_eval.py`:

```python
import json
from pathlib import Path
from typer.testing import CliRunner
from themek.cli import app


runner = CliRunner()
STUB_DIR = Path(__file__).parent / "fixtures"


def _write_stub(tmp_path: Path, extraction: dict) -> Path:
    p = tmp_path / "stub.json"
    p.write_text(json.dumps(extraction), encoding="utf-8")
    return p


def _write_ground_truth(tmp_path: Path, extraction: dict) -> Path:
    p = tmp_path / "gt.json"
    p.write_text(json.dumps({
        "metadata": {
            "ticker": "005930", "name_ko": "삼성전자",
            "period": "2023", "source_rcept_no": "x",
            "fixture_path": "x", "created_at": "2026-05-23", "notes": "",
        },
        "extraction": extraction,
    }), encoding="utf-8")
    return p


def _write_html(tmp_path: Path) -> Path:
    p = tmp_path / "report.html"
    p.write_text("<html><body><p>본문</p></body></html>", encoding="utf-8")
    return p


def test_cli_eval_e5_perfect_score(monkeypatch, tmp_path):
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
    ])
    assert result.exit_code == 0, result.stdout
    assert "삼성전자" in result.stdout
    assert "1.000" in result.stdout
    assert "0.00 %p" in result.stdout


def test_cli_eval_e5_missing_ground_truth(monkeypatch, tmp_path):
    stub = _write_stub(tmp_path, {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    })
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(tmp_path / "nope.json"),
    ])
    assert result.exit_code != 0
    assert "ground truth not found" in (result.stdout + (result.stderr or ""))


def test_cli_eval_e5_reports_missed(monkeypatch, tmp_path):
    truth_payload = {
        "period": "2023",
        "segments": [
            {"name_ko": "메모리", "share_pct": 20.0, "products": []},
            {"name_ko": "Harman", "share_pct": 5.0, "products": []},
        ],
        "customers": [],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub_payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = _write_stub(tmp_path, stub_payload)
    gt = _write_ground_truth(tmp_path, truth_payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
    ])
    assert result.exit_code == 0, result.stdout
    assert "Harman" in result.stdout
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli_eval.py -v
```
Expected: `Error: No such command 'eval'`.

- [ ] **Step 3: cli.py에 eval 서브커맨드 추가**

`src/themek/cli.py` 상단 import 추가:

```python
from themek.eval.e5 import evaluate_e5, load_ground_truth, format_eval_result_text
```

`app` 정의 직후, `query_app` 옆에 eval_app 추가:

```python
eval_app = typer.Typer(help="Run extraction quality evaluation")
app.add_typer(eval_app, name="eval")
```

그리고 새 명령 정의 (`if __name__ == "__main__":` 위):

```python
@eval_app.command("e5")
def eval_e5_cmd(
    html_file: Path = typer.Option(..., "--html-file"),
    period: str = typer.Option(..., "--period"),
    ground_truth: Path = typer.Option(..., "--ground-truth"),
):
    """E5 추출 품질을 ground truth와 비교해 점수표 출력."""
    try:
        truth, metadata = load_ground_truth(ground_truth)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    html = html_file.read_text(encoding="utf-8")
    text = extract_business_content(html)

    extractor = _stub_extractor_from_env()
    if extractor is not None:
        extracted = extractor(text, period)
    else:
        from themek.ingest.business_report import _default_extractor
        extracted = _default_extractor(text, period)

    result = evaluate_e5(extracted, truth)
    typer.echo(format_eval_result_text(
        result,
        metadata=metadata,
        ground_truth_path=str(ground_truth),
        html_path=str(html_file),
    ))
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_cli_eval.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: 전체 회귀 확인**

```bash
uv run pytest
```
Expected: 기존 51 + 신규 (~20) 모두 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/cli.py tests/test_cli_eval.py
git commit -m "feat(cli): themek eval e5 command with stub mode (Plan #6 T9)"
```

---

## Task 10: 삼성전자 ground truth JSON 작성 (사용자 task)

**Files:**
- Create: `data/eval/ground_truth/samsung_e5_2023.json`

이 task는 **코드 작성이 아니라 사용자가 fixture HTML을 읽고 정답을 손으로 적는 작업**이다. 절차:

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p data/eval/ground_truth
```

- [ ] **Step 2: fixture HTML을 직접 읽음**

```bash
open tests/fixtures/samsung_business_report_excerpt.html
# 또는 cat / 에디터로 열기
```

표/문장에서 다음을 확인:
- 사업부문 6개 (DS-메모리, DS-S.LSI/파운드리, DX-MX, DX-VD/DA, Harman, 기타) + 각 share_pct
- 매출처 3개 + share_pct + tier
- 지역 6개 (한국/미주/유럽/중국/아시아(중국·일본 외)/기타) — 동일 region_code끼리 합산 (아시아 13.2% + 기타 6.0% = ROW 19.2%)

- [ ] **Step 3: `data/eval/ground_truth/samsung_e5_2023.json` 작성**

```json
{
  "metadata": {
    "ticker": "005930",
    "name_ko": "삼성전자",
    "period": "2023",
    "source_rcept_no": "20240314000123",
    "fixture_path": "tests/fixtures/samsung_business_report_excerpt.html",
    "created_at": "2026-05-23",
    "notes": "fixture HTML 표에 명시된 사실만. 아시아(중국·일본 외) 13.2% + 기타 6.0% → ROW 19.2% (이슈 #2 dedup 룰)."
  },
  "extraction": {
    "period": "2023",
    "segments": [
      {"name_ko": "DS - 메모리", "share_pct": 21.5, "description": null, "products": ["DRAM", "NAND", "HBM"]},
      {"name_ko": "DS - S.LSI/파운드리", "share_pct": 9.0, "description": null, "products": ["모바일 AP", "이미지센서", "파운드리 위탁생산"]},
      {"name_ko": "DX - MX", "share_pct": 35.5, "description": null, "products": ["스마트폰 갤럭시 시리즈", "태블릿", "웨어러블"]},
      {"name_ko": "DX - VD/DA", "share_pct": 14.5, "description": null, "products": ["QLED/OLED TV", "냉장고", "세탁기", "에어컨"]},
      {"name_ko": "Harman", "share_pct": 5.0, "description": null, "products": ["전장용 디지털 콕핏", "카오디오", "오디오 솔루션"]},
      {"name_ko": "기타", "share_pct": 14.5, "description": null, "products": []}
    ],
    "customers": [
      {"name_raw": "Apple Inc.", "revenue_share_pct": 13.6, "tier": "1차"},
      {"name_raw": "글로벌 통신사업자 A (비공개)", "revenue_share_pct": 5.2, "tier": "1차"},
      {"name_raw": "글로벌 OEM B (비공개)", "revenue_share_pct": 3.1, "tier": "1차"}
    ],
    "geographic": [
      {"region_code": "KR", "share_pct": 14.8},
      {"region_code": "US", "share_pct": 35.6},
      {"region_code": "EU", "share_pct": 13.4},
      {"region_code": "CN", "share_pct": 17.0},
      {"region_code": "ROW", "share_pct": 19.2}
    ]
  }
}
```

작성 후 본인이 fixture HTML과 한 번 더 대조하여 누락·오타 없는지 확인.

- [ ] **Step 4: JSON 유효성 검증**

```bash
uv run python -c "import json; json.load(open('data/eval/ground_truth/samsung_e5_2023.json'))"
```
Expected: 무출력 (오류 없음).

- [ ] **Step 5: Pydantic 스키마 검증**

```bash
uv run python -c "
import json
from themek.llm.schemas import BusinessExtraction
payload = json.load(open('data/eval/ground_truth/samsung_e5_2023.json'))
BusinessExtraction.model_validate(payload['extraction'])
print('valid')
"
```
Expected: `valid`.

- [ ] **Step 6: 커밋**

```bash
git add data/eval/ground_truth/samsung_e5_2023.json
git commit -m "data(eval): samsung_e5_2023 ground truth (Plan #6 T10)"
```

---

## Task 11: 실 LLM smoke run + baseline notes

**Files:**
- Create: `docs/eval-e5-smoke-run-notes.md`

- [ ] **Step 1: 시드 + ingest 상태 확보** (pytest가 production DB를 비웠을 수 있음 — 이슈 #1 격리 후엔 안전하지만 한 번 더 확인)

```bash
uv run themek seed
sqlite3 themek.db "SELECT COUNT(*) FROM corporations;"
```
Expected: `3`.

- [ ] **Step 2: 실 LLM eval 실행 (1~2분, Claude 토큰 소비)**

```bash
uv run themek eval e5 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  | tee /tmp/eval_run.txt
```
Expected: 점수표가 stdout에 출력되고 exit code 0.

- [ ] **Step 3: `docs/eval-e5-smoke-run-notes.md` 작성**

```markdown
# E5 Eval Harness — Smoke Run Baseline

**실행일:** 2026-05-23
**Ground truth:** `data/eval/ground_truth/samsung_e5_2023.json`
**Fixture:** `tests/fixtures/samsung_business_report_excerpt.html`
**LLM:** Claude Code subscription via `claude -p`

## Command

(위 step 2 명령 그대로)

## Output (1회 run)

```
<step 2의 /tmp/eval_run.txt 내용을 여기 그대로 붙임>
```

## Analysis

- Segments: <점수 + 누락/환각 해설>
- Customers: <점수 + 해설>
- Regions: <점수 + 해설 — 특히 ROW dedup이 정상 동작했는지>
- share_pct MAE: <% 오차의 의미>

## Notes

- 실 LLM은 비결정적이므로 같은 입력 두 번째 run에서 점수가 다를 수 있음.
- 이번 baseline은 prompt/모델 변경 시 비교 기준.
- 후속: sample 추가 (sector별 대표 종목), CI 통합, fuzzy customer matching.
```

- [ ] **Step 4: 커밋**

```bash
git add docs/eval-e5-smoke-run-notes.md
git commit -m "docs(eval): E5 eval harness smoke run baseline (Plan #6 T11)"
```

---

## Task 12: README 업데이트

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README의 "후속 plan" 또는 "Status" 섹션을 갱신**

기존 (`README.md` line 5~7 부근):

```markdown
**Walking Skeleton (Plan #1) 구현 완료** — 2026-05-23.
```

다음으로 변경:

```markdown
**Walking Skeleton (Plan #1) + Eval Harness (Plan #6) 구현 완료** — 2026-05-23.
E5 ("이 회사 뭐 만들어?") CQ가 DART 사업보고서 1건에 대해 end-to-end로 동작하고,
삼성전자 ground truth로 추출 품질 4 metric을 측정할 수 있습니다.
```

그리고 "후속 Plan들" 섹션에서 Plan #6 줄을 변경:

기존:
```markdown
- **Plan #6**: Evaluation rubric harness (`themek eval e5 --ground-truth ...`)
```

다음으로 (위치 옮기거나 표시 추가):
```markdown
- ~~**Plan #6**: Evaluation rubric harness~~ ✅ 완료 (`docs/superpowers/plans/2026-05-23-e5-eval-harness.md`)
```

`### E5 쿼리` 섹션 다음에 새 섹션 추가:

```markdown
### E5 추출 품질 평가 (Plan #6)

```bash
uv run themek eval e5 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json
```

출력: segment / customer / region recall+precision + share_pct MAE 점수표 + Missed/Extra 진단. baseline 기록은 `docs/eval-e5-smoke-run-notes.md`.
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: README Plan #6 eval harness 사용법 + 상태 갱신 (Plan #6 T12)"
```

---

## Acceptance Verification

모든 task 완료 후 다음 명령으로 전체 검증:

```bash
# 1. 전체 테스트 통과 (기존 51 + 신규 ~20)
uv run pytest

# 2. eval 명령 정상 동작 (1~2분 소요)
uv run themek seed
uv run themek eval e5 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json

# 3. Spec section 10의 5개 acceptance criteria 모두 충족 확인
ls data/eval/ground_truth/samsung_e5_2023.json
ls docs/eval-e5-smoke-run-notes.md
grep "Plan #6" README.md
```
