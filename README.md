# themek

한국 테마주 시장에 최적화된 ontology 기반 정보 서비스 프로젝트.

## Status

**Walking Skeleton (#1) + Eval Harness (#6) + DART API Client (#3) + Parser Robust Extraction (#4) 구현 완료** — 2026-05-27.

E5 ("이 회사 뭐 만들어?") CQ가 **종목+연도만 입력하면** end-to-end로 동작하며, 사업보고서 형식 변형에 robust한 3-tier escalation 추출까지 갖춰진 상태:
DART OpenAPI에서 corp_code 조회 → 사업보고서 자동 fetch → 본문 추출 (regex → LLM → full_text escalation, 학습 누적) → LLM ingest → query → eval.
종목 1개 → N개 확장 backbone + parser self-improving loop 완성.

진행 history:
- Plan #1 (Walking Skeleton, 17 task TDD) ✅ 2026-05-23
- 이슈 #1 (conftest production DB 격리) ✅
- 이슈 #2 (geographic region_code dedup) ✅
- Plan #6 (Eval Harness, 12 task TDD) ✅ 2026-05-25 — stub 1회 smoke baseline: 4 metric 모두 1.000 / MAE 0.00 %p
- Plan #6 follow-up (CallResult + --runs aggregation + --save-runs) ✅ 2026-05-26 — 실 LLM baseline 측정 scaffolding
- Plan #3 (DART API client, 11 task TDD + 실 API 정찰) ✅ 2026-05-25 — 종목 1 → N 확장 backbone, 실 API smoke 3종목 정상
- Plan #4 (Parser Robust Extraction, 21 task TDD; Task 20 deferred) ✅ 2026-05-27 — 3-tier escalation + self-improving regex 학습 사이클
- Plan #5 (Multi-Corp Backfill, 14 task TDD + production smoke 10 종목 × 2024:2025 검증) ✅ 2026-05-27 — Layer A initial backfill + Layer B daily incremental cron + RateBudget 38K/day cap + universe single-source-of-truth (`data/universe/active.txt`)

**다음 작업:** Plan #2 + #7 (social layer ontology + 텔레/블로그/팍스넷 ingestion) 또는 Plan #5.1 (정정보고서 query 최신 선택 검증 + LLM 비용 자동 cap + 시계열 query layer).

## Vision

한국 테마주 시장의 narrative·구조·시계열 사건을 4종 소스(텔레그램 채널 / 네이버 블로그 / 팍스넷 종목토론방 / DART)에서 추출해 **2-layer grounded ontology**(social interpretation + structural fact)로 구조화. 자연어 쿼리에 인용·구조와 함께 답하는 정보 서비스의 핵심 자산.

## Design Spec

→ [`docs/superpowers/specs/2026-05-22-korean-theme-stock-ontology-design.md`](docs/superpowers/specs/2026-05-22-korean-theme-stock-ontology-design.md)

7단계 합의 과정을 거친 ontology 설계 문서:

1. Competency Questions 형식화 (External 8 + Internal 11)
2. 재사용 ontology 매핑 (FIBO light reuse · KRX FICS · DART · XBRL · Wikidata)
3. Term 인벤토리 + Class/Instance 구분
4. Class hierarchy DAG (5종 관계 명시: instance-of / is-a / part-of / member-of / has-role)
5. Slot domain·range·cardinality 명세
6. Reification lifecycle 룰 (append-only bi-temporal)
7. CQ traversal 전수 검증

## Implementation Plan

→ [`docs/superpowers/plans/2026-05-23-e5-walking-skeleton.md`](docs/superpowers/plans/2026-05-23-e5-walking-skeleton.md)

17 task TDD plan, all completed.

## Walking Skeleton — Setup & Usage

### 사전 요구사항

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (package manager)
- Claude Code CLI 설치 + 로그인 (`claude --version`로 확인)
  - 구독 기반: ANTHROPIC_API_KEY 불필요
- (옵션) PostgreSQL — 운영 시 사용. 로컬은 SQLite로 동작.

### 설치 / 초기화

```bash
# 의존성 설치
uv sync

# 환경 변수 (SQLite 기본 + DART API key 발급 필요)
cp .env.example .env
# .env에 DART_API_KEY=<https://opendart.fss.or.kr 발급> 입력

# 마이그레이션 적용
uv run alembic upgrade head

# 샘플 시드 (sectors / regions / 3 종목 corporation 기본 row)
uv run themek seed
```

### DART API 자동 fetch + ingest (Plan #3 + Plan #4, 가장 빈번한 사용 패턴)

```bash
# 1. corp_code 마스터 1회 sync (DART OpenAPI 1회 호출, ~120K 기업)
uv run themek dart sync-corp

# 2. 종목 + 연도로 자동 ingest (cache miss 시 list.json + document.xml 2 호출)
uv run themek dart ingest --ticker 005930 --period 2023
# [section_filter] escalation=regex output_chars=38085 invalid=[]
# 두 번째 실행은 cache hit으로 DART API 0회 + DB idempotent
# ingest 후 자동: tests/fixtures/dart_variants/ mirror + 학습 패턴 누적

# 3. Plan #4 학습 사이클 상태 / 수동 trigger
uv run themek dart parser-stats          # fixtures + learned + pending proposals
uv run themek dart parser-learn          # N=3 도달 proposal을 learned로 promote
uv run themek dart parser-consolidate    # 학습 패턴 머지·dedup
```

### (선택) 수동 fixture로 ingest

DART API key 없이 로컬 HTML로 ingest하고 싶을 때:

```bash
uv run themek ingest \
  --rcept-no 20240312000736 \
  --corp 00126380 \
  --report-type 사업보고서 \
  --period 2023 \
  --filing-date 2024-03-12 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240312000736"
```

### 다종목 backfill (Plan #5)

```bash
# 1. universe 정의 (단일 source of truth) — corp_code 1줄당 1개
mkdir -p data/universe
echo "00126380   # 005930 삼성전자" >> data/universe/active.txt

# 2. 1회: BackfillTarget 생성 (dry-run → confirm)
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025 --confirm

# 3. 매일 cron (scripts/themek_backfill.sh 등록)
uv run themek dart incremental --since yesterday --until today \
  --purge-zip-after-extract
uv run themek dart backfill run --purge-zip-after-extract

# 4. 모니터링 (escalation 분포 + 비용 top-10)
uv run themek dart backfill status --verbose
```

운영 매뉴얼: [`docs/dart-backfill-runbook.md`](docs/dart-backfill-runbook.md)

### E5 쿼리

```bash
uv run themek query e5 --ticker 005930
```

### Obsidian vault 생성 (온톨로지 점검·탐색)

적재된 DART 온톨로지를 Obsidian vault로 생성해 그래프로 둘러보고 데이터 품질을 점검한다.

```bash
uv run themek vault build            # vault/ 에 생성 (멱등 — 재실행 시 최신 DB 반영)
```

- `vault/companies/` 회사 노트(DB 1:1) · `segments/`·`regions/`·`sectors/` 개념 노드 · `customers/` 미연결 고객(설명문 포함 전부 노드화, `kind` 분류)
- `vault/_qa-report.md` 데이터 품질 이슈 자동 집계(지역 중복·매출합 이상·미연결·누락)
- Obsidian에서 "폴더를 vault로 열기" → Graph View로 노드 망 시각화

백필로 적재가 늘면 `themek vault build`만 재실행하면 새 노드가 자동 반영된다.

### E5 추출 품질 평가 (Plan #6)

```bash
# 실 DART fetched HTML 사용
uv run themek eval e5 \
  --html-file data/dart/raw/20240312000736/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json
```

출력: segment / customer / region recall+precision + share_pct MAE 점수표 + Missed/Extra 진단. baseline 기록은 `docs/eval-e5-smoke-run-notes.md`.

출력 예시 (실 Claude 추출 결과):

```
[삼성전자 (005930) — 반도체]
출처: 사업보고서 (period=2023, DART rcept_no=20240314000123)
링크: https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123

## 사업 부문 매출 구성
- DX - MX 35.5% — 모바일 기기 사업
- DS - 메모리 21.5% — 메모리 반도체 사업
- DX - VD/DA 14.5% — 영상디스플레이 및 생활가전
- 기타 14.5% — 네트워크, 디스플레이 패널 외
- DS - S.LSI/파운드리 9.0% — 시스템반도체 및 파운드리 위탁생산
- Harman 5.0% — 전장 및 오디오 솔루션

## 주요 고객사 / 매출처
- Apple Inc. (13.6%) · 1차 협력사
- 글로벌 통신사업자 A (비공개) (5.2%) · 1차 협력사
- 글로벌 OEM B (비공개) (3.1%) · 1차 협력사

## 지역별 매출 노출
- 미주 (US): 35.6%
- 중국 (CN): 17.0%
- 국내 (KR): 14.8%
- 유럽 (EU): 13.4%
- 기타 (ROW): 13.2%
```

### 테스트

```bash
uv run pytest
```

전 **198개** 테스트 통과 (실 LLM 호출 없이 fixture/mock 기반).
- Plan #1 walking skeleton + Plan #6 eval harness: 76
- Plan #3 DART client/cache/lookup/fetch/CLI: 56
- Plan #3 실 fixture playback (corpCode.zip 118k row, list.json, document.xml zip): 8
- Plan #4 parser escalation + learning loop + fixture mirror + parser-* CLI: 48
- Plan #6 follow-up (aggregate, save-runs, CallResult): 10
- config + 회귀: 나머지

### 디렉토리 구조

```
src/themek/
├── config.py             # Pydantic Settings (DSN, claude CLI, DART 등)
├── db/
│   ├── engine.py         # SQLAlchemy + SQLite FK PRAGMA
│   └── models.py         # 14개 클래스 (Stock/Corp/...Revenue/Customer/...)
├── krx/                  # [Plan #5.2] KRX 상장사 sync
│   ├── client.py         # pykrx wrapper
│   └── sync.py           # Stock 테이블 upsert + delisting 감지
├── dart/
│   ├── parser.py         # [Plan #4] 3-tier escalation 추출 (regex→LLM→full_text)
│   ├── learned_patterns.py # [Plan #4] baseline + 학습 패턴 JSON loader
│   ├── pattern_learning.py # [Plan #4] propose → record → validate → promote
│   ├── fixture_mirror.py # [Plan #4] cache → tests/fixtures mirror
│   ├── client.py         # [Plan #3] DART OpenAPI HTTP client
│   ├── cache.py          # [Plan #3] 응답 디스크 캐시
│   ├── corp_lookup.py    # [Plan #3] corp_code 마스터 sync + ticker 조회
│   └── fetch.py          # [Plan #3] document.xml zip → 사업의 내용 XML 추출
├── llm/
│   ├── schemas.py        # BusinessExtraction Pydantic
│   ├── prompts.py        # 추출 prompt 빌더
│   └── claude_cli.py     # `claude -p` subprocess wrapper
├── ingest/
│   └── business_report.py # parser→LLM→DB (idempotent)
├── query/
│   ├── e5.py             # ticker→E5Result traversal
│   ├── synthesize.py     # Jinja answer 합성
│   └── templates/
│       └── e5_answer.txt.j2
├── seeds.py
└── cli.py                # typer entrypoint (seed/ingest/query/eval/dart)

data/dart/
├── corp_master.json              # gitignored — sync-corp 결과 (~120K 기업)
├── learned_header_patterns.json  # [Plan #4] commit — 학습 누적 regex
├── pattern_proposals.json        # [Plan #4] commit — N=3 도달 전 proposal
└── raw/<rcept_no>/               # gitignored
    ├── document.zip              # DART 원본
    └── business.html             # 추출된 'II. 사업의 내용' (XML→HTML wrap)

tests/fixtures/dart_variants/     # [Plan #4] commit — ingest 자동 mirror
├── <ticker>_<period>.html
└── <ticker>_<period>_headers.json  # 회귀 검증용 expected_headers
```

## 후속 Plan들 (예정)

권장 누적 순서: **실 LLM baseline → #5 (시계열·다종목 backfill) → #2 + #7 (social layer) → pgvector**.

- 🚧 **다음**: 실 `claude` CLI 기반 E5 추출 baseline 측정 (3종목 × 3 runs, `--save-runs` 사용) + Plan #5.2 KRX 자동 universe (KOSPI/KOSDAQ 전체 sync + cron 자동화).
- **Plan #5**: 다종목·시계열 backfill orchestrator — token bucket, 동시 fetch, 진행상황 logging, 실패 재시도
- **Plan #2**: Theme / Narrative / Membership / Activation 클래스 추가 → E1·E2·E3·E6 CQ 지원 (스키마 축)
- **Plan #7**: 텔레/블로그/팍스넷 소스 ingestion → social narrative layer (데이터 축, #2와 한 쌍)
- **pgvector 통합**: E2·E4 semantic 매칭 / Event analog
- ~~**Plan #5.2**: KRX 자동 universe (pykrx KOSPI/KOSDAQ sync + Stock 테이블 SSOT + 신규 상장 자동 BackfillTarget enroll)~~ ✅ 완료 (`docs/superpowers/plans/2026-05-27-krx-stock-sync-and-auto-universe.md`)
- ~~**Plan #6**: Evaluation rubric harness~~ ✅ 완료 (`docs/superpowers/plans/2026-05-23-e5-eval-harness.md`)
  - follow-up scaffolding(CallResult + --runs/--save-runs): `docs/superpowers/plans/2026-05-26-e5-real-llm-baseline.md`
- ~~**Plan #3**: DART API client~~ ✅ 완료 (`docs/superpowers/plans/2026-05-25-dart-api-client.md`)
  - 정찰 기록: `docs/dart-api-recon-notes.md`
  - smoke baseline: `docs/dart-fetch-smoke-run-notes.md`
  - status: `docs/dart-api-client-status-2026-05-25.md`
- ~~**Plan #4**: Parser robust extraction~~ ✅ 완료 (`docs/superpowers/plans/2026-05-26-dart-parser-robust-extraction.md`, Task 20 deferred)
  - status: `docs/dart-parser-robust-extraction-status-2026-05-27.md`

## License

TBD.
