---
title: E5 Real-LLM Baseline + Token Efficiency — Design Spec
date: 2026-05-26
status: Draft v1
scope: 3종목 × N=3 run 실 claude CLI baseline + section-level token filtering + multi-run aggregation. 기존 eval harness(Plan #6) 위에 누적 확장.
references:
  - docs/superpowers/specs/2026-05-23-e5-eval-harness-design.md (전제)
  - docs/superpowers/plans/2026-05-23-e5-eval-harness.md (전제)
  - docs/eval-e5-smoke-run-notes.md (stub baseline)
---

# E5 Real-LLM Baseline + Token Efficiency — Design Spec

## 1. Vision & Goal

기존 E5 eval harness(Plan #6)는 stub LLM 1회 run으로 smoke baseline만 잡았다. 이 spec은 **실 `claude` CLI**로 3종목 × N=3 run을 돌려 정량 baseline을 확보하며, 그 baseline이 의미를 가지려면 필수적인 **토큰 효율화 + 측정 인프라**를 같은 spec에 묶는다.

baseline 측정 자체와 토큰 효율화는 분리 불가:

- 삼성전자 2023 실 사업보고서는 6.7MB / parsed 60K tokens. 현 prompt 구조 그대로 N=3 돌리면 종목 1개에만 ~180K input token. 종목 3개 ≈ ~500K → 비용·지연 부담 큼.
- 1회 run baseline은 LLM 비결정성으로 점수의 noise floor도 모름.
- 토큰 사용량이 측정되지 않으면 후속 prompt·모델 변경의 비용 영향을 알 수 없음.

→ section filter + N-run aggregation + token usage 측정을 baseline spec의 *전제 인프라*로 포함한다.

### 1.1 측정 목적

- 실 LLM의 4 metric (segment/customer/region recall·precision, share_pct MAE) **mean ± stdev** baseline
- 종목 유형별(대형 다부문 vs 중형 단일사업) 추출 품질 격차 관찰
- prompt·모델 변경 시 비교 가능한 **token cost / latency baseline**
- 후속 최적화 작업의 기준선

### 1.2 측정 비대상

- pass/fail 임계값 정책 — baseline만, 합·불 판단 없음
- CI 자동 실행 — manual 실행 전제 (subscription 토큰 소비)
- 다른 CQ (E1~E4, E6~E8) — sibling spec 필요
- prompt 자체의 최적화 — *현재 prompt의 baseline* 측정이지 개선이 아님

## 2. Scope

### 2.1 In-scope

- 종목 3개 × period=2023:
  - 005930 삼성전자 (대형, 6 segment, 다국적)
  - 005380 현대자동차 (대형, 자동차/금융 부문)
  - 277810 레인보우로보틱스 (중형, R&D 중심 협동로봇)
- N=3 run per (ticker, period) — 총 9 LLM extraction call + 0~3 fallback call
- 실 DART API only — fixture 사용 안 함 (캐시 hit 후속 run은 network 0)
- Ground truth 3종 작성 (삼성 GT는 실 DART HTML 기준으로 **재작성**, 현대·레인보우는 신규)
- `dart/parser.py`: `extract_business_sections(html, want, llm_fallback)` 추가
- `llm/claude_cli.py`: `CallResult` dataclass 반환 (text + token usage + cost + duration)
- `llm/prompts.py`: `build_header_classification_prompt` 추가
- `eval/e5.py`: `aggregate_runs(runs) → AggregatedResult` 추가
- `cli.py`: `eval e5 --runs N --save-runs <dir>` flag 추가
- ingest 파이프라인(`_default_extractor`)도 동일 section filter를 거치도록 — 운영 = baseline
- per-run 영속화: raw LLM text + parsed extraction + usage + section resolution 로그
- baseline 문서화: `docs/e5-real-llm-baseline-notes.md`

### 2.2 Out-of-scope (후속)

- N≥5 run 확장 / 통계적 신뢰구간
- 다종목 batch 명령 (`themek eval e5-all`)
- JSON output mode (`--json`)
- baseline 결과 history DB 적재
- entity resolution (Apple Inc. vs 애플)
- prompt 최적화 자체

## 3. 변경 사항 개요

### 3.1 불변

- `BusinessExtraction` Pydantic schema
- `evaluate_e5` / 4 metric 함수 / `EvalResult`
- `extract_business_content` (하위 호환 유지, raw text 필요한 use case 대비)
- DART fetch/cache/corp_lookup
- 기존 stub 패턴 (`THEMEK_STUB_EXTRACTION_FILE`)

### 3.2 신규 / 확장

| 위치 | 변경 |
|---|---|
| `dart/parser.py` | `extract_business_sections(html, *, want, llm_fallback)` 추가 |
| `llm/claude_cli.py` | `call_claude` 반환을 `CallResult` dataclass로. 기존 caller는 `.text` 접근으로 한 줄 수정 |
| `llm/prompts.py` | `build_header_classification_prompt(candidates, missing_targets)` 추가 |
| `eval/e5.py` | `AggregatedResult` + `aggregate_runs(runs, usages)` 추가 |
| `cli.py` | `eval e5` 에 `--runs N` (default 1), `--save-runs <dir>` 추가. N>1일 때 출력 포맷 확장 |
| `ingest/business_report.py` | caller(cli.py) 측에서 section filter 적용. `_default_extractor` 시그니처 불변 |

## 4. Component 세부

### 4.1 Section Filter (`dart/parser.py`)

`II. 사업의 내용` 챕터 내 sub-section에서 E5에 필요한 3개만 추출:

```python
TARGETS: dict[str, list[re.Pattern]] = {
    "overview": [re.compile(r"사업.{0,3}개요")],
    "products": [re.compile(r"주요.{0,3}제품"),
                 re.compile(r"제품.{0,3}서비스")],
    "revenue":  [re.compile(r"매출"),
                 re.compile(r"수주.{0,3}현황")],
}

def extract_business_sections(
    html: str,
    *,
    want: set[str] = frozenset({"overview", "products", "revenue"}),
    llm_fallback: Callable[[list[str], list[str]], dict] | None = None,
) -> tuple[str, SectionResolution]:
    """
    1) 헤더 후보 추출 (정규식 + 구조 마커)
    2) want target ↔ keyword 매칭
    3) 미매칭 target이 있고 llm_fallback != None이면 후보 → LLM 분류
    4) LLM이 null 반환한 target은 skip
    5) 매칭된 section의 본문만 concat하여 반환
    """
```

**헤더 후보 추출:**

- `^\s*\d+\.\s*(.+)$` → 예: `1. 사업의 개요`
- `^\s*[가-힣]\.\s*(.+)$` → 예: `가. 사업의 개요`
- `<h2>`, `<h3>` 텍스트
- 길이 ≤ 50자만 (false positive 방지)

**Section 본문 절단:**

- 한 헤더의 본문은 다음 헤더 직전까지
- 매칭된 target만 concat. 미매칭/skip된 section은 출력에서 제외.

**Return:**

```python
@dataclass
class SectionResolution:
    regex_matched: dict[str, str]            # target → matched header line
    llm_called: bool
    llm_input_candidates: list[str]          # LLM에 던진 후보
    llm_decision: dict[str, int | None]      # target → candidate idx | null
    skipped: list[str]                       # want 중 결국 매칭 못 한 target
    output_chars: int                        # 최종 텍스트 길이
```

### 4.2 LLM Fallback Prompt (`llm/prompts.py`)

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
```

`candidates_block`은 `[1] {header_1}\n[2] {header_2}\n...` 형식.

**호출 조건:** regex 매칭으로 want 3개 중 하나라도 누락 시 1회 호출. 종목·시기당 최대 1회.

**Cost:** 종목당 ≤ ~300 input + ~50 output tokens.

### 4.3 Token Usage Measurement (`llm/claude_cli.py`)

`claude -p --output-format json`의 payload field를 모두 사용:

```python
@dataclass(frozen=True)
class CallResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    raw_payload: dict  # 전체 JSON (디버깅용)

def call_claude(prompt: str, *, timeout_sec: int | None = None) -> CallResult:
    ...
```

기존 `call_claude(prompt) -> str` → caller가 `.text`로 접근. 영향받는 호출처:

- `ingest/business_report.py:_default_extractor` — `raw = call_claude(prompt).text`로 1줄 수정

### 4.4 Multi-Run Aggregation (`eval/e5.py`)

```python
@dataclass
class AggregatedResult:
    runs: list[EvalResult]
    usages: list[CallResult]
    # 7개 metric 각각 (None은 mean 산출에서 제외)
    segment_recall_mean: float | None
    segment_recall_stdev: float | None
    segment_precision_mean: float | None
    segment_precision_stdev: float | None
    customer_recall_mean: float | None
    customer_recall_stdev: float | None
    customer_precision_mean: float | None
    customer_precision_stdev: float | None
    region_recall_mean: float | None
    region_recall_stdev: float | None
    region_precision_mean: float | None
    region_precision_stdev: float | None
    share_pct_mae_mean: float | None
    share_pct_mae_stdev: float | None
    # 종합
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    total_duration_ms: int
    # union 진단 (run별 발생한 missed/extra를 모두 합한 set)
    missed_segments_union: list[str]
    extra_segments_union: list[str]
    missed_customers_union: list[str]
    extra_customers_union: list[str]
    missed_regions_union: list[str]
    extra_regions_union: list[str]

def aggregate_runs(
    runs: list[EvalResult],
    usages: list[CallResult],
) -> AggregatedResult:
    ...
```

- `statistics.mean` / `statistics.stdev` 사용. n=1이면 stdev=None.
- 일부 run이 None metric을 반환해도 None 제외 후 mean 산출.
- 모든 run이 None인 metric은 mean=None, stdev=None.

### 4.5 Raw Run Persistence

`--save-runs <dir>` 지정 시:

```
<dir>/
└── <ticker>_<period>/
    ├── run_1.json
    ├── run_2.json
    ├── run_3.json
    ├── section_resolution.json
    └── summary.json
```

`run_N.json` 스키마:
```json
{
  "run_index": 1,
  "raw_llm_text": "...",
  "parsed_extraction": { /* BusinessExtraction dump */ },
  "usage": { "input_tokens": 12840, "output_tokens": 624, "cost_usd": 0.041, "duration_ms": 29100 },
  "eval_result": { /* EvalResult dump */ }
}
```

`section_resolution.json` 스키마: §4.1 `SectionResolution` dump.

`summary.json` 스키마: `AggregatedResult` dump.

**위치:** `data/eval/runs/`는 gitignore. 사용자가 baseline notes 작성 시 인용·요약하여 docs에 기록.

### 4.6 CLI 변경 (`cli.py`)

```
themek eval e5 \
  --html-file <path> --period <p> --ground-truth <path> \
  [--runs N]              # default 1 (기존 호환)
  [--save-runs <dir>]     # 미지정 시 영속화 안 함
```

N=1일 때 출력은 기존과 동일. N>1일 때:

```
=== Eval: E5 — 삼성전자 (005930) period=2023 (N=3) ===
Ground truth:  data/eval/ground_truth/samsung_e5_2023.json
HTML source:   data/dart/raw/20240313001451/business.html

                          run_1   run_2   run_3   mean ± stdev
Segments  recall=        1.000   0.833   1.000   0.944 ± 0.096
Segments  precision=     1.000   1.000   0.857   0.952 ± 0.082
Customers recall=        1.000   1.000   1.000   1.000 ± 0.000
Customers precision=     1.000   0.750   1.000   0.917 ± 0.144
Regions   recall=        1.000   1.000   1.000   1.000 ± 0.000
Regions   precision=     1.000   1.000   1.000   1.000 ± 0.000
Share_pct MAE            0.00    0.85    0.30    0.38 ± 0.43 %p

Token usage (3 runs):
  input_tokens:    38,521   (12,840 / run)
  output_tokens:    1,873   (   624 / run)
  cost_usd:        $0.124   ($0.041 / run)
  duration:         87.3s   (29.1s / run)

Section filter:
  regex matched:   overview, products, revenue
  llm fallback:    not called
  skipped:         -
  output chars:    47,820   (raw chapter: 241,568)

Missed/Extra (union across 3 runs):
  segments missed:  []
  segments extra:   ["반도체장비"]
  customers missed: []
  customers extra:  []
  regions missed:   []
  regions extra:    []
```

### 4.7 ingest 파이프라인 동기화

운영(`themek dart ingest`)과 baseline 측정이 동일 파이프라인 거치도록:

- `cli.py:dart_ingest_cmd` / `cli.py:eval_e5_cmd` 둘 다 `extract_business_content` 대신 `extract_business_sections(html, llm_fallback=llm_classify_headers)` 호출
- `_default_extractor` 시그니처는 불변; section-filtered text가 들어옴
- ingest 명령에 `--save-runs`는 의미 없으므로 추가 안 함

## 5. Ground Truth

### 5.1 작성 대상

| 파일 | 상태 |
|---|---|
| `data/eval/ground_truth/samsung_e5_2023.json` | 실 DART HTML 기준으로 **재작성** (기존은 fixture 기반) |
| `data/eval/ground_truth/hyundai_e5_2023.json` | 신규 |
| `data/eval/ground_truth/rainbow_e5_2023.json` | 신규 |

기존 fixture-based samsung GT는 `tests/fixtures/samsung_e5_2023_fixture.json`으로 이동 — pytest의 unit/integration용으로 보존.

### 5.2 작성 절차

1. `themek dart sync-corp` (이미 완료 가정)
2. `themek dart ingest --ticker {005930|005380|277810} --period 2023` 실행 → `data/dart/raw/{rcept_no}/business.html` 캐시 보강
3. 사용자가 `business.html` 또는 section-filtered 결과를 직접 읽어 GT 작성
4. Schema는 Plan #6 §6.1 그대로 (수정 없음)
5. `metadata.notes`에 모호한 결정 기록

### 5.3 GT validation hint

작성 보조용으로 다음 명령 권장:

```bash
themek eval e5 \
  --html-file data/dart/raw/<rcept_no>/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/<ticker>_e5_2023.json \
  --runs 1 --save-runs /tmp/gt_check
```

`/tmp/gt_check/<ticker>_2023/run_1.json`의 `parsed_extraction`을 GT와 시각 비교하여 누락·환각 패턴을 GT 검증에 활용.

## 6. Error Handling

| 상황 | 처리 |
|---|---|
| DART API key 없음 | exit 2, 기존 `DartAuthError` 흐름 |
| DART API 호출 실패 | exit 4, 기존 `DartApiError` |
| corp_master 미동기화 | exit 2, 사용자에게 `themek dart sync-corp` 안내 |
| section filter 0개 매칭 (regex + LLM 모두 실패) | 경고 + 전체 chapter 텍스트로 fallback. `--save-runs`에 `skipped: ["overview", "products", "revenue"]` 기록 |
| LLM fallback call 실패 (`ClaudeCallError`) | regex 매칭분으로만 진행, 미매칭 target skip + stderr 경고 |
| 1개 extraction run 실패 | 해당 run의 `EvalResult`/`CallResult`를 None으로 채우고 남은 run으로 aggregation |
| 모든 N run 실패 | exit 1 + stderr |
| `--ground-truth` 경로 없음 | exit 1 (기존) |

원칙: silent fail 없음. 비정상 종료 시 exit code != 0 + stderr.

## 7. Testing

### 7.1 Unit (LLM 없음)

- `tests/test_parser_sections.py`
  - 3개 target 다 regex 매칭
  - 1개 누락 → llm_fallback 호출 (mock)
  - llm_fallback이 null 반환 → skip
  - 헤더 표기 변형 (`1.` / `가.` / `<h3>`)
  - 0개 매칭 시 전체 chapter fallback
- `tests/test_llm_header_classification.py`
  - prompt 빌더 출력 (candidate index 1-based)
  - LLM 응답 → dict 파싱
  - invalid JSON 응답 처리
- `tests/test_eval_aggregate.py`
  - n=3 mean/stdev
  - n=1 stdev=None
  - 일부 metric None인 run 포함
  - usage sum 정확성

### 7.2 Integration

- `tests/test_eval_e5_multirun.py` — stub extractor로 N=3 end-to-end, `AggregatedResult` 검증
- `tests/test_save_runs_persistence.py` — `--save-runs` 결과물(run_N.json, section_resolution.json, summary.json) schema 검증

### 7.3 CLI

- `tests/test_cli_eval.py` 확장:
  - `--runs 3 --save-runs <tmp>` 정상 케이스
  - `--save-runs` 디렉토리 생성 권한 오류 → exit 1
  - N=1 (default) 출력이 기존 포맷 유지

### 7.4 실 LLM 자동 테스트 *없음*

기존 정책 유지. baseline 결과는 manual run으로 `docs/e5-real-llm-baseline-notes.md`에 기록.

## 8. Acceptance Criteria

이 spec 기반 plan 완료 조건:

1. 3종목 모두 다음 명령이 점수표 + token usage + section filter 로그를 출력하고 exit 0:
   ```
   themek eval e5 \
     --html-file data/dart/raw/<rcept_no>/business.html \
     --period 2023 \
     --ground-truth data/eval/ground_truth/<ticker>_e5_2023.json \
     --runs 3 --save-runs data/eval/runs/2026-05-26
   ```
2. `data/eval/ground_truth/{samsung,hyundai,rainbow}_e5_2023.json` 3개 모두 git tracked, 실 DART HTML 기준 작성
3. `docs/e5-real-llm-baseline-notes.md`에 3종목 × N=3 결과 + section filter 동작 로그 + 총 비용 기록
4. ingest 파이프라인(`themek dart ingest`)도 동일 section filter 거침
5. 신규 unit/integration/CLI 테스트 통과 + 기존 138개 회귀 0
6. 기존 fixture-based samsung GT가 `tests/fixtures/`로 archive
7. README "다음 작업" 섹션 갱신 (이 spec 완료 → Plan #5 backfill 또는 Plan #2/#7 social layer)

## 9. Cost & Risk 추정

### 9.1 예상 토큰·비용

| 종목 | parsed 추정 | post-filter 추정 | 3 run input | 3 run output | run당 cost |
|---|---|---|---|---|---|
| 005930 | 60K | ~12K | ~36K | ~1.8K | ~$0.04 |
| 005380 | ~30K (추정) | ~8K | ~24K | ~1.5K | ~$0.03 |
| 277810 | ~10K (추정) | ~4K | ~12K | ~1.0K | ~$0.02 |
| section LLM fallback | — | ~300 / call | 종목당 ≤1 call | ~50 | ~$0.001 |
| **합계 (3 종목 × 3 run)** | | | **~72K input** | **~4.5K output** | **~$0.28** |

Sonnet 4 단가 가정: $3/M input, $15/M output. claude CLI subscription에선 사용량 카운트만 노출(실 청구는 구독).

### 9.2 Risk

- **삼성 실 HTML이 60K 이상일 수 있음** — section filter가 충분히 줄이지 못하면 1 run 비용 증가. mitigation: `--save-runs` 로그로 실 token usage 확인 → 필요 시 prompt 압축이나 추가 filter 후속 plan에서 작업.
- **헤더 표기 다양성** — DART 보고서 회사별 헤더 표기 편차로 LLM fallback이 3종목 모두에 호출될 수 있음. cost 증가 미미하지만 latency ~5초 × 3종목 추가.
- **N=3 통계 신뢰도** — stdev는 표본 변동성 *추정*일 뿐 신뢰구간 아님. baseline notes에 명시.
- **GT 작성 작업량** — 60K token 보고서를 사람이 읽고 GT 작성하는 데 종목당 1~2시간 예상. baseline 측정 task 전에 선행되어야 함.
- **재현성 caveat** — DART 정정공시 시 `rcept_no` 변동 가능. cache는 `rcept_no` pinning이라 OK이지만 baseline notes에 `rcept_no`와 `filing_date` 명시 필요.
