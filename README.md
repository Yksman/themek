# themek

한국 테마주 시장에 최적화된 ontology 기반 정보 서비스 프로젝트.

## Status

**Walking Skeleton (Plan #1) 구현 완료** — 2026-05-23. E5 ("이 회사 뭐 만들어?") 한 CQ를 DART 사업보고서 1건에 대해 end-to-end로 답하는 vertical slice가 동작합니다.

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

# 환경 변수 (SQLite 기본)
cp .env.example .env

# 마이그레이션 적용
uv run alembic upgrade head

# 샘플 시드 (3 종목: 삼성전자 / 현대차 / 레인보우로보틱스)
uv run themek seed
```

### 사업보고서 1건 ingest (실 Claude CLI 호출, 1~2분 소요)

```bash
uv run themek ingest \
  --rcept-no 20240314000123 \
  --corp 00126380 \
  --report-type 사업보고서 \
  --period 2023 \
  --filing-date 2024-03-14 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123"
```

### E5 쿼리

```bash
uv run themek query e5 --ticker 005930
```

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

전 46개 테스트 통과 (실 LLM 호출 없이 fixture/mock 기반).

### 디렉토리 구조

```
src/themek/
├── config.py             # Pydantic Settings (DSN, claude CLI 등)
├── db/
│   ├── engine.py         # SQLAlchemy + SQLite FK PRAGMA
│   └── models.py         # 14개 클래스 (Stock/Corp/...Revenue/Customer/...)
├── dart/
│   └── parser.py         # 사업보고서 HTML → 텍스트
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
└── cli.py                # typer entrypoint
```

## 후속 Plan들 (예정)

이 walking skeleton은 ontology spec의 일부만 구현. 다음 plan들로 확장:

- **Plan #2**: Theme / Narrative / Membership / Activation 클래스 추가 → E1·E2·E3·E6 CQ 지원
- **Plan #3**: DART API client 자동 fetch (현재는 수동 fixture)
- **Plan #4**: pgvector 통합 → E2·E4 semantic 매칭 / Event analog
- **Plan #5**: 24개월 backfill orchestrator
- **Plan #6**: Evaluation rubric harness (`themek eval e5 --ground-truth ...`)
- **Plan #7**: 텔레/블로그/팍스넷 소스 ingestion → social narrative layer

## License

TBD.
