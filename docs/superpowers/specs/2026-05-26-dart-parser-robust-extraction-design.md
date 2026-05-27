# DART Parser Robust Extraction — Design Spec

**Date:** 2026-05-26
**Status:** Approved
**Author:** themek

## 1. Goal

DART 사업보고서가 **어떤 변형 형식으로 들어와도** E5에 필요한 3개 섹션 (overview / products / revenue)을 안정적으로 추출하는 파이프라인. 동시에 **자동 학습 loop** 로 regex 커버리지를 시간이 갈수록 확장한다.

핵심 명제: "Silent partial failure(잘못 잘린 본문이 그럴듯해 보임)는 noisy retry보다 훨씬 위험하다."

## 2. Motivation

현재 `extract_business_sections`는 regex+keyword anchor에 전적으로 의존한다. 한국 DART 보고서의 헤더 표기 변형은 매우 다양:

- prefix 변형: `1.` / `1)` / `①` / `Ⅰ.` / `가.` / `(가)` / `[1]` / `<제1절>`
- 묶음 prefix: `(제조서비스업)1. 사업의 개요`, `[금융업] 1. 사업의 개요`
- 키워드 변형: `사업의 개요` ↔ `회사의 개황` ↔ `주요 사업의 내용`; `매출` ↔ `수익 구성` ↔ `영업현황` ↔ `수주현황`
- 컨테이너 변형: `<h3>` / `<TITLE>` (XML) / `<TD>` (표 안 헤더) / `<P>` only

이번 plan 직전 Rainbow Robotics(277810)에서 발견된 회귀: `1. 사업의 개요` 직후 sub-bullet `가. 협동로봇`이 또 헤더로 잡혀 body가 빈 줄로 잘림 (output_chars=39). Regex를 강화하는 것만으론 다음 변형에서 또 깨진다.

→ **다층 escalation** 으로 robustness 보장 + **학습 loop** 으로 비용·지연을 점진적으로 0에 수렴시킨다.

## 3. Architecture

### 3.1 Three-tier extraction (defense in depth)

```
HTML → A: regex + keyword anchor (현재 구조 + 확장)
         ↓ A 결과의 sanity check 실패 (body 길이 < threshold 또는 target 누락)
       B: LLM 헤더 분류 (현재 llm_classify_headers 확장)
         ↓ B 결과도 sanity check 실패
       C: raw 본문 통째로 (extract_business_content 그대로 LLM extractor에 위임)

매 단계의 결과는 SectionResolution.escalation_level 필드에 기록:
  "regex" | "regex+llm" | "full_text"
```

**Sanity check rule:**
- 각 target의 body가 `MIN_SECTION_CHARS` (default 300) 미만이면 그 target은 무효 처리
- 무효 target이 1개 이상이면 B로 escalate
- B 후에도 무효 target이 1개 이상이면 C로 escalate

### 3.2 Learning loop

B 또는 C로 escalate된 경우, LLM이 분류한 헤더 텍스트는 **A가 놓친 변형 sample**.

```
escalation 발생 → LLM 분류 결과의 헤더 텍스트 수집 →
  propose_patterns(): keyword 또는 prefix 일반화 →
    validate_patterns(): 기존 fixture 전부 회귀, 결과가 깨지면 reject →
      record_proposal(): proposals/ 에 N=3회 동일 분류 대기 →
        apply_patterns(): N=3 도달 시 learned_header_patterns.json 에 append
```

### 3.3 Fixture mirror

`dart ingest` 가 성공하면 `data/dart/raw/<rcept_no>/business.html` 을 **자동으로** `tests/fixtures/dart_variants/<ticker>_<period>.html` 에 복사. 이 fixture 집합이 회귀 검증의 기반.

## 4. Components

### 4.1 Files modified

```
src/themek/dart/
├── parser.py                          # 수정: 3-tier escalation, sanity check
├── learned_patterns.py                # 신규: learned_header_patterns.json loader + apply
├── pattern_learning.py                # 신규: propose / validate / record / apply 로직
└── fixture_mirror.py                  # 신규: ingest cache → tests/fixtures mirror

src/themek/
└── cli.py                             # 수정: parser-stats, parser-consolidate, parser-learn 추가

data/dart/
├── learned_header_patterns.json       # 신규 (commit, gitignore 아님)
└── pattern_proposals.json             # 신규 (commit, 학습 대기 중 sample)

tests/fixtures/dart_variants/          # 신규 디렉토리 (ingest mirror 결과 commit)
├── <ticker>_<period>.html             # 실 DART HTML
└── <ticker>_<period>_headers.json     # 그 fixture의 expected header mapping
```

### 4.2 SectionResolution 확장

```python
@dataclass
class SectionResolution:
    regex_matched: dict[str, str] = field(default_factory=dict)
    llm_called: bool = False
    llm_input_candidates: list[str] = field(default_factory=list)
    llm_decision: dict[str, Optional[int]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    output_chars: int = 0
    # 신규:
    escalation_level: str = "regex"            # "regex" | "regex+llm" | "full_text"
    body_chars_per_target: dict[str, int] = field(default_factory=dict)
    invalid_targets: list[str] = field(default_factory=list)  # sanity check 실패한 target
    learned_samples: list[dict] = field(default_factory=list) # {target, header_text} (학습 후보)
```

### 4.3 learned_header_patterns.json schema

```json
{
  "version": 1,
  "updated_at": "2026-05-26T...",
  "patterns": {
    "overview": [
      {
        "type": "keyword",
        "regex": "사업.{0,3}개요",
        "source": "code_baseline",
        "added_at": "2026-05-22"
      },
      {
        "type": "keyword",
        "regex": "회사.{0,3}개황",
        "source": "learned",
        "added_at": "2026-05-27",
        "samples": ["회사의 개황", "회사 개황"],
        "confirmed_count": 3,
        "fixtures_validated": ["005930_2023", "068270_2023", "..."]
      }
    ],
    "products": [...],
    "revenue": [...]
  },
  "prefixes": [
    {
      "type": "prefix",
      "regex": "^\\s*\\d{1,2}\\.\\s+",
      "source": "code_baseline"
    },
    {
      "type": "prefix",
      "regex": "^\\s*\\(\\d{1,2}\\)\\s+",
      "source": "learned",
      "samples": ["(1) 회사의 개황"],
      "confirmed_count": 3
    }
  ]
}
```

### 4.4 pattern_proposals.json schema

```json
{
  "proposals": [
    {
      "target": "overview",
      "type": "keyword",
      "candidate_regex": "회사.{0,3}개황",
      "sample_headers": ["회사의 개황"],
      "observed_count": 1,
      "first_seen_at": "2026-05-27T...",
      "last_seen_at": "2026-05-27T...",
      "source_fixtures": ["068270_2023"]
    }
  ]
}
```

## 5. Decisions (commit log)

| # | Question | Decision | Rationale |
|---|---|---|---|
| Q1 | 자동화 레벨 | **L2** (회귀 fixture 통과 시 자동 commit-to-file) | safe + 자동. fixture가 안전판. |
| Q2 | 학습 단위 | **키워드 + prefix 둘 다** | 변형이 두 축에서 나옴. |
| Q3 | 저장 위치 | `data/dart/learned_header_patterns.json` **commit** | 팀 공유, git diff로 학습 이력. gitignore 아님. |
| Q4 | Fixture mirror | 매 ingest 시 자동, `tests/fixtures/dart_variants/<ticker>_<period>.html` | 작은 cache 부담. coverage가 안전판의 핵심. |
| Q5 | 비일관성 방어 | **N=3회 동일 분류** 후 commit | LLM 비결정성 흡수. |
| Q6 | 학습 trigger | **매 ingest 자동 학습** + `parser-learn` 명령으로도 수동 trigger 가능 | ingest workflow에 자연스럽게 끼움. |

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM 비일관성으로 patterns 진동 | N=3회 동일 분류 후에만 commit |
| False positive 패턴 전파 (broad regex가 노이즈 헤더 다시 부활) | 모든 fixture에 대해 회귀 검증, 깨지면 reject |
| Fixture coverage 빈약 (학습 sample 자기 자신만 통과) | 초기 fixture build: 다양한 업종 5~10종목 자동 ingest |
| Anti-bloat (학습 패턴 무한 증가) | minimum specificity check (3자 이상, 공통 어휘 reject); 주기적 `parser-consolidate` 명령으로 머지·dedup |
| 학습 시간으로 매 ingest 지연 | 학습은 ingest와 분리 가능, `parser-learn` 별도 명령 |
| 새 fixture의 expected headers JSON 작성 부담 | 자동 생성: ingest 직후 현재 regex의 결과를 expected로 commit; 잘못 잡힌 경우만 사람이 수정 |
| `dart ingest` 가 한 ticker에 corp_code 1:1 매핑이 깨질 위험 (Rainbow seed 사례) | 별도로 처리됨 (이전 fix). 이 plan과 무관. |

## 7. Acceptance Criteria

1. **Robustness**: cached 3종목(Samsung/Hyundai/Rainbow) + 신규 ingest되는 5+종목에서 전부 `output_chars >= 1000` 이고 3개 target 모두 valid.
2. **Escalation 가시화**: 모든 ingest/eval CLI 출력에 `escalation_level` 노출.
3. **학습 동작**: 임의 신규 변형 헤더가 LLM 분류로 처리됐을 때, 3회 반복 ingest 시 `learned_header_patterns.json` 에 patterns가 자동 추가됨.
4. **Anti-regression**: 새 패턴이 기존 fixture 회귀를 깨면 reject. CI 같은 검증 step 명시적 존재.
5. **CLI 가시성**: `themek dart parser-stats` 가 누적 fixture 수, regex / regex+llm / full_text 비율, 학습 패턴 N개를 출력.
6. **Fixture mirror 동작**: `dart ingest` 후 `tests/fixtures/dart_variants/<ticker>_<period>.html` 가 자동 생성됨.
7. **회귀 테스트 카운트**: 기존 165 PASS 유지 + 이번 plan 신규 ~30개 추가.

## 8. Out of Scope

- E5 외 다른 섹션 추출 (재무, 거버넌스 등) — 별도 plan
- 다국어/영문 보고서 — 한국 DART 한정
- pgvector / semantic search 변형 — Plan #4 영역
- LLM extractor 자체 prompt 최적화 — 별도 plan
- 학습 패턴의 정밀도/리콜 metric 자동 보고서 (L3 영역) — 추후

## 9. Implementation Phases (high-level)

**Phase 1 — Escalation skeleton (no learning yet)**
- SectionResolution 확장 + escalation_level
- Sanity check (MIN_SECTION_CHARS)
- A→B 자동 escalation (B 호출 조건 강화)
- B→C 자동 escalation (full_text fallback)
- CLI 가시화

**Phase 2 — Learning loop**
- learned_header_patterns.json schema + loader
- pattern_proposals.json record/update
- propose / validate / apply 로직
- 매 ingest 자동 학습
- `parser-learn` / `parser-stats` / `parser-consolidate` CLI

**Phase 3 — Fixture infrastructure**
- ingest cache → tests/fixtures/dart_variants/ mirror
- expected headers auto-generation
- 회귀 검증을 모든 fixture 대상으로 수행하는 utility

**Phase 4 — Coverage build**
- 신규 5~10종목 `dart ingest` (다양한 업종)
- 초기 학습 sample 확보
- baseline 보고서 갱신

## 10. Reference

- 이전 plan: `docs/superpowers/plans/2026-05-26-e5-real-llm-baseline.md`
- 관련 fix (Rainbow filter bug): `src/themek/dart/parser.py` 직전 commit
- 영향 받는 CLI: `src/themek/cli.py` `dart_ingest_cmd`, `eval_e5_cmd`
