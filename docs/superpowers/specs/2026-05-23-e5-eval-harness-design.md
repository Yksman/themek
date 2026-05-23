---
title: E5 Eval Harness — Design Spec
date: 2026-05-23
status: Draft v1 (brainstorm 합의 완료, 구현 plan은 별도)
scope: 1종목 × 4 metric × 실 LLM 호출 모드. ground truth 1건(삼성전자) 포함. sample-based eval framework의 첫 sample.
---

# E5 Eval Harness — Design Spec

## 1. Vision & Goal

themek는 한국 전 상장종목에 대해 ontology를 구축하는 것이 최종 목표. ingest 파이프라인(parser → Claude CLI → Pydantic → DB)이 LLM의 추출 품질에 의존하므로, **추출 품질을 객관적으로 측정하는 framework**이 필수.

이 spec은 첫 evaluation harness를 정의한다. 1개 종목(삼성전자)에 대한 ground truth를 사람이 작성하고, 실 LLM 호출 결과를 ground truth와 비교해 4개 metric을 산출한다.

### 1.1 측정 목적

- **prompt/모델 변경 시 회귀 감지** — `prompts.py` 수정 또는 다른 모델 비교 시 점수 비교
- **현재 추출 품질의 baseline 기록** — 후속 개선 작업의 진척도 측정
- **이슈 발견 도구** — Missed/Extra 리스트로 어떤 segment·customer·region이 누락·환각되는지 즉시 확인

### 1.2 측정 비대상

- 다른 CQ (E1~E4, E6~E8) — sibling evaluator로 후속
- ingest 파이프라인 회귀 (이미 pytest가 stub로 검증 중)
- 종목 종합 점수 — 1종목짜리 sample
- CI 자동 fail — manual 실행 전제

## 2. Sample-Based Eval Framework 전체 그림

전 상장종목 ground truth는 *생산 불가능* (LLM이 하는 일을 사람이 하는 것). 따라서 eval은:

- 손으로 만든 ground truth set에 대해서만 점수 산출
- 첫 sample은 삼성전자 (가장 복잡한 cross-segment 케이스)
- sample 추가는 후속 plan에서 sector별로 점진적
- 점수는 *sample 집합의 평균 추출 품질을 대표*

본 spec은 **첫 sample 1건 + framework 골격**까지만 다룬다.

## 3. Scope

### 3.1 In-scope

- CLI: `themek eval e5 --html-file <path> --period <str> --ground-truth <path>`
- Python 모듈: `src/themek/eval/e5.py` (1개 evaluator + metric 함수)
- Ground truth: `data/eval/ground_truth/samsung_e5_2023.json` (사용자 작성)
- 4 metric: segment recall/precision, customer recall/precision, region recall/precision, share_pct MAE
- CLI text 점수표 + Missed/Extra 진단 리스트
- Unit + integration + CLI 테스트 (~20 케이스, LLM 없음)
- Error handling (모든 에러는 exit code != 0)
- Stub extractor 호환 — `THEMEK_STUB_EXTRACTION_FILE` 환경변수로 LLM 우회 (ingest 명령과 동일 패턴, CLI 테스트에서 필수)

### 3.2 Out-of-scope (후속 plan)

- 실 LLM 호출 자동 테스트 (CI 토큰 소비 + 비결정적)
- N회 run 평균 / 통계적 신뢰구간
- CI 통합 (GitHub Actions 등)
- 다른 CQ용 evaluator
- pass/fail 임계값 정책
- 종목/시기별 history 저장 + 회귀 추적
- fuzzy customer name matching (Apple Inc. vs 애플)
- evaluation 결과 dashboard / visualization
- ground truth 자동 검증 (HTML과의 정합성)
- 다종목 batch eval (`themek eval e5-all`)
- JSON output 모드 (`--json`)

## 4. Architecture

### 4.1 File structure

```
themek/
├── src/themek/
│   └── eval/
│       ├── __init__.py
│       └── e5.py
├── tests/
│   ├── test_eval_e5_metrics.py
│   ├── test_eval_e5_integration.py
│   └── test_cli_eval.py
├── data/
│   └── eval/
│       └── ground_truth/
│           └── samsung_e5_2023.json
└── (src/themek/cli.py — eval 서브커맨드 추가)
```

`data/eval/ground_truth/`는 git tracked. `tests/fixtures/`와 분리 — eval은 testing이 아닌 production 평가.

### 4.2 Component 의존성

```
cli.py (eval e5 명령)
   │
   ▼
eval/e5.py: evaluate_e5(extracted, ground_truth) → EvalResult
   │   ▲                  ▲
   │   │                  └── ground_truth: BusinessExtraction (재사용)
   │   │
   │   └── extracted: BusinessExtraction (재사용)
   │
   ▼
metric 함수들 (pure):
   - segment_recall, segment_precision
   - customer_recall, customer_precision
   - region_recall, region_precision
   - share_pct_mae
```

**핵심 재사용**: extraction 파이프라인(parser → prompts → claude_cli → schemas)은 `ingest_business_report._default_extractor`와 동일. 별도 코드 복제 없음.

**DB 비의존**: SQLAlchemy session 사용 안 함. eval은 ontology DB 상태와 독립.

### 4.3 Data flow

```
[--html-file]                       [--ground-truth JSON]
    │                                       │
    ▼                                       ▼
parser.extract_business_content      json.load → wrapper dict
    │                                       │
    ▼                                       ▼
prompts.build_business_extraction    BusinessExtraction.model_validate(
    _prompt                               dict["extraction"])
    │                                       │
    ▼                                       │
claude_cli.call_claude                      │
    │                                       │
    ▼                                       │
extract_json_block                          │
    │                                       │
    ▼                                       │
BusinessExtraction.model_validate           │
    │                                       │
    └──────────────► evaluate_e5(extracted, truth)
                                            │
                                            ▼
                                    EvalResult:
                                      segment_recall, segment_precision,
                                      customer_recall, customer_precision,
                                      region_recall, region_precision,
                                      share_pct_mae,
                                      missed_segments, extra_segments,
                                      missed_customers, extra_customers,
                                      missed_regions, extra_regions
                                            │
                                            ▼
                                CLI text 점수표
```

**Stub mode**: `THEMEK_STUB_EXTRACTION_FILE` 환경변수가 설정되어 있으면 parser/prompts/claude_cli 단계를 모두 건너뛰고 해당 JSON 파일을 `BusinessExtraction`으로 직접 로드. ingest 명령과 동일한 패턴 (`cli.py:_stub_extractor_from_env`). CLI 테스트가 LLM 호출 없이 동작하기 위함.

## 5. Metric 정의

### 5.1 정확한 공식

| Metric | 공식 | 매칭 기준 |
|---|---|---|
| `segment_recall` | `|matched| / |truth|` | `name_ko` exact match |
| `segment_precision` | `|matched| / |extracted|` | 동일 |
| `customer_recall` | `|matched| / |truth|` | `name_raw` **case-insensitive** exact |
| `customer_precision` | `|matched| / |extracted|` | 동일 |
| `region_recall` | `|matched| / |truth|` | `region_code` exact (KR/US/EU/CN/JP/ROW) |
| `region_precision` | `|matched| / |extracted|` | 동일 |
| `share_pct_mae` | `Σ|ext.share − truth.share| / count(matched_seg)` | matched된 segment만 |

### 5.2 Edge case 처리

- denominator = 0 → `None` 반환 (예: extracted 또는 truth가 빈 list)
- matched segment 없음 → `share_pct_mae = None`
- ground truth의 `share_pct`가 null인 segment → MAE 합산에서 제외하고 MAE 분모(matched 개수)에서도 차감. 즉 MAE = `Σ|ext.share − truth.share| / |{m ∈ matched : truth[m].share_pct is not None}|`
- LLM이 segment 0개 반환 → recall=0.0, precision=None, Missed에 ground truth 전체

### 5.3 fuzzy matching이 *없음*을 명시적으로 표명

첫 버전은 `name_ko` / `name_raw` / `region_code` 모두 정확 매치 (또는 case-insensitive exact). 이유:

- "Apple Inc." vs "애플" 같은 표기 차이는 entity resolution layer(후속 plan)에서 해결할 별도 문제
- fuzzy match가 들어가면 점수의 *해석*이 모호해짐 (어디까지가 "같다"인가)
- 첫 baseline 점수가 100%가 아닌 자체가 정보 — 어떤 추출 차이를 메워야 하는지 사용자가 보게 됨

## 6. Ground Truth Schema

### 6.1 JSON 구조

```json
{
  "metadata": {
    "ticker": "005930",
    "name_ko": "삼성전자",
    "period": "2023",
    "source_rcept_no": "20240314000123",
    "fixture_path": "tests/fixtures/samsung_business_report_excerpt.html",
    "created_at": "2026-05-23",
    "notes": "fixture HTML 본문 표에 명시된 사실만 기록. 추측·해석 없음."
  },
  "extraction": {
    "period": "2023",
    "segments": [
      {"name_ko": "DS - 메모리", "share_pct": 21.5, "description": null, "products": ["DRAM", "NAND", "HBM"]}
    ],
    "customers": [
      {"name_raw": "Apple Inc.", "revenue_share_pct": 13.6, "tier": "1차"}
    ],
    "geographic": [
      {"region_code": "KR", "share_pct": 14.8},
      {"region_code": "ROW", "share_pct": 19.2}
    ]
  }
}
```

### 6.2 `extraction` 부분

기존 `BusinessExtraction` Pydantic 모델 그대로 사용. 별도 `GroundTruth` 모델 안 만듦.

### 6.3 작성 절차 (사용자 task)

1. fixture HTML 파일을 열어 표/문장에 명시된 사실 확인
2. fixture 본문에 *없는* 항목은 ground truth에 포함하지 않음 (외부 지식 금지)
3. 동일 `region_code`로 매핑되는 항목은 합산 (예: "아시아 13.2%" + "기타 6.0%" → ROW 19.2%)
4. share_pct가 명시되지 않은 segment는 `null`
5. metadata에 `notes`로 모호한 결정 기록 (예: "fixture 표에 '아시아(중국·일본 외)' 13.2%로 적혀 있어 JP 제외 ROW로 매핑함", "Apple Inc. 13.6%는 '메모리 및 디스플레이 패널 공급'으로 cross-segment여서 customer로만 분류", "'기타' 사업부문 14.5% 등 정성 설명이 모호한 항목은 그대로 적음")

## 7. CLI 출력 형식

정상 출력:

```
=== Eval: E5 — 삼성전자 (005930) period=2023 ===
Ground truth:  data/eval/ground_truth/samsung_e5_2023.json
HTML fixture:  tests/fixtures/samsung_business_report_excerpt.html

Segments        recall= 6/6 = 1.000    precision= 6/6 = 1.000
Customers       recall= 3/3 = 1.000    precision= 3/3 = 1.000
Regions         recall= 5/5 = 1.000    precision= 5/5 = 1.000
Share_pct MAE   0.00 %p (matched=6)

Missed (truth에 있는데 LLM이 놓침):
  segments:  []
  customers: []
  regions:   []

Extra (LLM이 만들었는데 truth엔 없음):
  segments:  []
  customers: []
  regions:   []
```

오류·누락 사례 예시:

```
Segments        recall= 5/6 = 0.833    precision= 5/7 = 0.714
Share_pct MAE   2.45 %p (matched=5)

Missed (truth에 있는데 LLM이 놓침):
  segments:  ["Harman"]

Extra (LLM이 만들었는데 truth엔 없음):
  segments:  ["반도체장비", "디지털전환솔루션"]
```

## 8. Error Handling

| 상황 | 처리 |
|---|---|
| `--html-file` 경로 없음 | typer 자동 검증 → exit 2 |
| `--ground-truth` JSON 파일 없음 | `FileNotFoundError` wrap → exit 1 + stderr |
| ground truth JSON schema 위반 | Pydantic `ValidationError` → exit 1 |
| Claude CLI 호출 실패 | `ClaudeCallError` → exit 1 |
| LLM JSON 파싱 불가 | `ClaudeCallError("no JSON block found")` → exit 1 |
| extracted 또는 truth가 빈 list | 점수 `None` 또는 `0.0`으로 표시, 정상 종료 (exit 0) |

원칙: 어떤 silent fail도 없음. 모든 에러는 exit code != 0 + stderr.

## 9. Testing

### 9.1 Unit tests — `tests/test_eval_e5_metrics.py`

- 각 metric 함수에 대해 4 케이스 (perfect / missing / extra / empty)
- share_pct MAE 3 케이스 (정상 / matched 없음 / share=null 제외)
- customer case-insensitive 검증 ("Apple Inc." vs "apple inc.")
- division-by-zero → `None` 반환

### 9.2 Integration test — `tests/test_eval_e5_integration.py`

stub extractor와 stub ground truth로 `evaluate_e5()` end-to-end:

- 100% 일치 → 모든 점수 1.0
- 의도적 누락 → Missed 리스트 검증
- 의도적 환각 → Extra 리스트 검증

### 9.3 CLI test — `tests/test_cli_eval.py`

typer `CliRunner`로 (LLM 호출 없이 `THEMEK_STUB_EXTRACTION_FILE` 환경변수로 stub):

- 정상 호출 → exit 0, stdout에 점수표 포함
- `--ground-truth` 경로 없음 → exit 1 + stderr 에러 메시지
- ground truth가 stub extraction과 100% 일치 → 점수표에 `1.000` 표시 검증

### 9.4 실 LLM 자동 테스트는 *없음*

CI 토큰 소비 + 비결정적. 실 LLM 동작은 manual smoke run 메모(`docs/eval-e5-smoke-run-notes.md` — 본 plan 마지막 task)에 기록.

## 10. Acceptance Criteria

이 spec 기반의 plan이 완료되었다는 조건:

1. `uv run themek eval e5 --html-file tests/fixtures/samsung_business_report_excerpt.html --period 2023 --ground-truth data/eval/ground_truth/samsung_e5_2023.json` 명령이 점수표를 출력하고 exit 0
2. `data/eval/ground_truth/samsung_e5_2023.json`이 git에 있음 (사용자 작성, fixture HTML에 명시된 사실만)
3. 모든 신규 unit/integration/CLI 테스트 통과 + 기존 51개 테스트 회귀 없음
4. `docs/eval-e5-smoke-run-notes.md`에 실 LLM 1회 run의 점수 기록 (baseline)
5. README의 "후속 plan" 섹션에서 Plan #6 항목이 ✓ 또는 갱신
