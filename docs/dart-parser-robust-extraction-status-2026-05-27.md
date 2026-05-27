# Plan #4 (DART Parser Robust Extraction) — Completion Status

**완료일:** 2026-05-27
**Plan:** `docs/superpowers/plans/2026-05-26-dart-parser-robust-extraction.md`
**Spec:** `docs/superpowers/specs/2026-05-26-dart-parser-robust-extraction-design.md`

## 1. Goal Recap

DART 사업보고서의 어떤 형식 변형이든 E5의 3개 섹션(`overview` / `products` /
`revenue`)을 안정 추출. 3-tier escalation (A regex → B LLM → C full text) +
매 ingest마다 학습되는 self-improving regex.

Plan #3가 (ticker, period) → cache HTML을 만들었다면, Plan #4는 그 HTML 안에서
"실제로 LLM에 넘길 본문"을 안정적으로 잘라낸다.

## 2. Deliverables

### 2.1 코드

| 파일 | 라인 | 역할 |
|------|------|------|
| `src/themek/dart/parser.py` | +241 | `SectionResolution` escalation 필드, `MIN_SECTION_CHARS` sanity, A→B→C 분기, `llm_classify_headers`, learned patterns runtime 로드 |
| `src/themek/dart/learned_patterns.py` | +155 신규 | `LearnedPatterns` dataclass + baseline/learned merge + `load_learned_patterns` / `save_learned_patterns` / `consolidate` |
| `src/themek/dart/pattern_learning.py` | +194 신규 | `propose_keyword_pattern` / `validate_pattern_against_fixtures` / `Proposal` / `record_proposal` / `apply_ready_proposals` |
| `src/themek/dart/fixture_mirror.py` | +37 신규 | `mirror_fixture` — cache HTML → `tests/fixtures/dart_variants/` 복사 + expected_headers JSON 생성 |
| `src/themek/llm/prompts.py` | +30 | `build_header_classification_prompt` — 미매칭 헤더 후보를 LLM이 분류 |
| `src/themek/cli.py` | +400 (Plan #3와 공유) | `dart parser-stats` / `parser-learn` / `parser-consolidate` + `dart ingest` 자동 mirror·학습 hook + escalation_level 출력 |

### 2.2 테스트 (전체 198 passed)

| 파일 | 테스트 | 비고 |
|------|--------|------|
| `tests/test_parser_escalation.py` | 8 | escalation_level, sanity check, A→B→C 분기, learned_samples |
| `tests/test_parser_sections.py` | 11 | 회귀 + learned patterns 통합 |
| `tests/test_learned_patterns.py` | 5 | JSON schema, loader, baseline merge |
| `tests/test_pattern_learning.py` | 10 | propose / validate / record / apply |
| `tests/test_fixture_mirror.py` | 2 | mirror copy + expected_headers 생성 |
| `tests/test_llm_header_classification.py` | 4 | LLM 분류 결과 파싱 |
| `tests/test_llm_prompts.py` | +1 (5) | header_classification prompt |
| `tests/test_cli_parser_commands.py` | 3 | parser-stats / -learn / -consolidate |
| `tests/test_cli_dart.py` | +4 (11) | ingest 자동 mirror·학습 hook 검증 |
| `tests/test_cli_eval.py` | +1 (6) | escalation_level 출력 |

**Plan #4 신규 테스트 ≈ 48건** (전체 198 중).

### 2.3 데이터 / fixture

| 파일 | 내용 |
|------|------|
| `data/dart/learned_header_patterns.json` | baseline 5 pattern (overview×1, products×2, revenue×2) + prefix 2 |
| `data/dart/pattern_proposals.json` | 빈 proposals (학습 시작 전) |
| `tests/fixtures/dart_variants/005380_2023.html` | **실 cache mirror** (현대차, 7.3MB) |
| `tests/fixtures/dart_variants/005380_2023_headers.json` | `(제조서비스업)사업의 개요/주요 제품 및 서비스/매출 및 수주상황` |
| `tests/fixtures/dart_variants/005930_2023.html` | stub (228B) — 실 mirror 미실행 |
| `tests/fixtures/dart_variants/277810_2023.html` | stub (228B) — 실 mirror 미실행 |

### 2.4 문서

| 파일 | 내용 |
|------|------|
| `docs/superpowers/specs/2026-05-26-dart-parser-robust-extraction-design.md` | 설계 |
| `docs/superpowers/plans/2026-05-26-dart-parser-robust-extraction.md` | 21 task TDD plan + completion notes |
| `docs/dart-parser-robust-extraction-status-2026-05-27.md` | (이 문서) |
| `README.md` | Plan #4 ✅ + 다음 작업 갱신 (별도 commit) |

## 3. 핵심 의사결정 / 설계

### Escalation 분기

```
A) regex 매칭 (learned + baseline patterns)
   ├─ all targets matched & body ≥ MIN_SECTION_CHARS → 종료
   └─ invalid / missing → B
B) LLM 분류 (남은 후보를 1-based index로 매핑)
   ├─ 모든 missing target 잡힘 & body OK → 종료
   └─ 여전히 invalid → C
C) full_text fallback (extract_business_content)
```

기존 `extract_business_sections` API는 그대로 (`text, SectionResolution`),
behavior만 escalation으로 확장. `eval/e5.py`나 `ingest_business_report`는 시그니처
변경 없음.

### Self-improving regex 학습 사이클

```
ingest → SectionResolution.learned_samples (B에서 매칭된 헤더 텍스트)
       → propose_keyword_pattern (텍스트 → 일반화 regex)
       → record_proposal (pattern_proposals.json에 누적)
       → N=3 도달 시 validate_pattern_against_fixtures
       → 통과 시 learned_header_patterns.json으로 promote
       → 다음 ingest부터 baseline + learned 합쳐 사용
```

핵심 안전장치: **모든 학습 패턴은 기존 fixture에 회귀 검증**. expected_headers를
깨면 reject + 그 proposal에 `__rejected_by:<fixture>` 마킹.

### fixture pool 자동 확장

`dart ingest`가 끝나면 cache HTML을 `tests/fixtures/dart_variants/`로 mirror.
mirror 시점에 `extract_business_sections` 한 번 더 돌려 `regex_matched`를
expected_headers JSON으로 저장. 다음 ingest의 학습 패턴은 이 fixture pool에
대해 회귀 검증.

mirror·학습 hook은 둘 다 **non-fatal**: 예외 발생 시 ingest는 성공 종료하고
stdout에 skip 사유만 출력.

## 4. CLI 사용 예시

```bash
# 학습 누적 상태 확인
uv run themek dart parser-stats
# fixtures: 3
# learned patterns:
#   overview: baseline=1, learned=0
#   products: baseline=2, learned=0
#   revenue: baseline=2, learned=0
# proposals (pending): 0

# proposal 중 N=3 도달 항목을 learned로 promote (ingest hook이 자동 호출)
uv run themek dart parser-learn

# 중복 패턴 머지·dedup
uv run themek dart parser-consolidate

# ingest 시 escalation_level 노출
uv run themek dart ingest --ticker 005930 --period 2023
# [section_filter] escalation=regex output_chars=38085 invalid=[]
# [parser-learn] applied 0 new patterns: []
# Ingested report 20240312000736
```

## 5. Acceptance Criteria

| # | 조건 | 결과 |
|---|------|------|
| 1 | `SectionResolution`에 escalation_level / body_chars / invalid_targets / learned_samples 필드 | ✅ |
| 2 | regex만으로 모든 target 정상 추출 시 escalation_level=="regex" | ✅ |
| 3 | invalid target에 한해 LLM 자동 escalation, 결과 정상 시 "regex+llm" | ✅ |
| 4 | LLM도 실패 시 full_text fallback, escalation_level=="full_text" | ✅ |
| 5 | learned_header_patterns.json에 새 pattern 추가 시 다음 호출에서 반영 | ✅ |
| 6 | propose → record → N=3 → validate → promote 전체 사이클 동작 | ✅ |
| 7 | 학습 패턴이 기존 fixture를 깨면 reject + rejection 기록 | ✅ |
| 8 | `dart ingest` 후 fixture mirror + 학습 hook 자동 실행 | ✅ |
| 9 | `dart parser-stats/-learn/-consolidate` 3 CLI 동작 | ✅ |
| 10 | 전체 회귀 + Plan #4 신규 테스트 모두 통과 | ✅ 198 passed |
| 11 | 신규 5종목 ingest로 fixture coverage 확장 (Task 20) | ❌ deferred |

## 6. 알려진 한계 / Follow-up

1. **fixture pool 부족** — 현재 005380만 실 cache mirror, 005930·277810은 stub.
   실 `claude` CLI 기반 baseline run 시점에 동시 진행 권장.
2. **Task 20 deferred** — 신규 5종목 추가 fixture coverage 확장은 별도 작업.
   실 운영 ingest를 N회 돌리면 자동으로 채워짐(`dart ingest`가 mirror).
3. **LLM 분류 fixture 없음** — `llm_classify_headers`는 unit test는 있지만
   실 cassette playback 없이 mock 기반. 실 운영 데이터로 검증 필요.
4. **현대차 7.3MB fixture** — git tracked되어 repo 사이즈 증가. 향후 Git LFS
   또는 대표 fixture만 commit하는 정책 검토.
5. **학습 패턴 metric 자동화 미구현** — precision/recall 자동 측정 보고서는
   L3 영역 (out-of-scope).
6. **자동 git commit 안 됨** — 학습 패턴 promote는 JSON 파일 write까지만.
   commit/push는 사람이.

## 7. 다음 권장 작업

**우선순위**:
1. **실 `claude` CLI 기반 E5 baseline 측정** (Plan #6 follow-up — plan 파일 이미
   commit됨) — stub LLM이 아닌 실 추출 결과로 segment/customer/region 점수 측정.
   삼성·현대·레인보우 3종목 × N runs로 분산까지 측정. `--save-runs`로 결과 저장.
2. **Plan #4 Task 20** — 베이스라인 측정 중 추가 5종목 ingest → fixture 자동
   확장 → 학습 사이클 1회 검증.
3. **Plan #5 다종목 backfill** — token bucket 활성, 동시 N개 fetch, 진행상황
   logging, 실패 재시도.

## 8. 검증 명령

```bash
# 전체 회귀 (198 tests)
uv run pytest -q

# 학습 상태 확인
uv run themek dart parser-stats

# 실 API end-to-end + 자동 학습 hook (DART_API_KEY + claude CLI 필요)
uv run themek dart ingest --ticker 005930 --period 2023
# [section_filter] escalation=... output_chars=... invalid=...

# 누적된 proposal을 수동으로 학습 trigger
uv run themek dart parser-learn

# Plan #6 follow-up 결과로 실 LLM baseline 측정
uv run themek eval e5 \
  --html-file data/dart/raw/20240312000736/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/baseline
```

## 9. Commit 매핑

| Commit | 범위 |
|--------|------|
| `b0491e8 feat(eval)` | Plan #6 follow-up — CallResult + --runs aggregation scaffolding |
| `4b4ff27 feat(dart)` | Plan #3 — OpenAPI client + cache + corp lookup + fetch |
| `af935a5 feat(parser)` | Plan #4 Phase 1 — escalation skeleton |
| `a7f643f feat(parser)` | Plan #4 Phase 2-3 — learning loop + fixture mirror |
| `2b2276e feat(cli)` | Plan #3 + #4 CLI integration |
| (다음) `docs` | Plan #4 status + plan checkboxes + README |
