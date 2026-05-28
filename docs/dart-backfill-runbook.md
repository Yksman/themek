# DART Backfill Runbook

> Plan #5 (Multi-Corp Backfill) 운영 매뉴얼.

## 1. Universe 정의 (단일 source of truth)

- `data/universe/active.txt` — corp_code 1줄당 1개. `#` 주석 + 빈 줄 허용.
- 이 파일이 backfill `init`과 `incremental` scan filter 둘 다의 정의.
- 운영자가 종목을 추가/제거하면 다음 cron부터 자동 반영.
- `active.txt`는 `.gitignore` 되어 있다 — 운영자가 환경별로 관리.

예시:

```
# KOSPI 대형주
00126380   # 005930 삼성전자
00164742   # 005380 현대자동차

# KOSDAQ
01133217   # 277810 레인보우로보틱스
```

## 2. 초기 setup

```bash
# corp_master 1회 (분기 수동 refresh)
uv run themek dart sync-corp

# universe 작성
mkdir -p data/universe
$EDITOR data/universe/active.txt

# BackfillTarget 생성 (dry-run → confirm)
uv run themek dart backfill init \
    --universe-file data/universe/active.txt --periods 2024:2025
# 예상 처리/호출/비용 확인 후
uv run themek dart backfill init \
    --universe-file data/universe/active.txt --periods 2024:2025 --confirm

# 진행 상황 확인
uv run themek dart backfill status
```

## 3. cron 등록

```cron
# 매일 5시 KST (DART 한도 reset 후)
0 5 * * *  /path/to/themek/scripts/themek_backfill.sh
```

`scripts/themek_backfill.sh`는 3 단계로 구성:

1. `dart incremental --since yesterday --until today --purge-zip-after-extract`
2. `dart backfill run --purge-zip-after-extract` (한도까지)
3. `dart backfill status` (1줄 요약 로그)

## 4. 일일 모니터링

```bash
uv run themek dart backfill status --verbose
# → escalation 분포 (regex / regex+llm / full_text) + 비용 top-10
tail -f data/log/backfill_$(date +%Y%m%d).log
tail -f data/log/incremental_$(date +%Y%m%d).log
uv run themek dart parser-stats   # Plan #4 학습 누적
```

## 5. 사고 대응

- **Budget 초과 (exit 6)**: 정상 종료 시그널 — 다음날 cron이 자동 재개. 수동 개입 불필요.
- **in_progress 180분+ 멈춤**: 다음 cron이 자동 reset (`reset_stale_minutes=180` default).
  즉시 복구는 `uv run themek dart backfill run --reset-stale-minutes 0`.
- **failed row 누적**:
  ```sql
  SELECT corp_code, period, last_error
    FROM backfill_targets WHERE status='failed';
  ```
  분석. C5 정책상 LLM/schema 에러는 자동 재시도 안 함 (재시도 무의미).
  수동 재시도: `UPDATE backfill_targets SET status='pending', attempts=0 WHERE …`.
- **escalation_level=full_text 비율 높음**: Plan #4 학습 사이클 필요.
  `themek dart parser-learn` + `parser-consolidate`.
- **DART 한도 변경**: `--daily-cap 38000` flag 또는 cron wrapper 수정.

## 6. Universe 확장 절차

```bash
echo "00126380   # 005930 삼성전자" >> data/universe/active.txt
uv run themek dart backfill init \
    --universe-file data/universe/active.txt --periods 2024:2025 --confirm
# 기존 (corp, period) 조합은 UNIQUE 충돌로 skip,
# 새 (corp, period)만 pending 추가
```

## 7. 정정보고서 정책

- 동일 (corp, period)에 정정보고서가 새 `rcept_no`로 들어오면:
  - **BusinessReport**에 새 row 추가 (덮어쓰기 X — append-only)
  - **BackfillTarget**는 그대로 (universe 진행 추적용, 기존 row 유지)
- `query e5`는 `filing_date DESC LIMIT 1`로 최신 보고서를 선택.
- 같은 `filing_date` 동률 시 row 선택 정확성은 Plan #5.1로 검증 예정.

## 8. 디스크 관리

- `data/dart/raw/<rcept_no>/document.zip`은 ingest 후 삭제 옵션 (`--purge-zip-after-extract`).
- 운영 cron에서는 on (~90% 디스크 절약, 1년 운영 시 GB 단위).
- 디버깅 / Plan #4 학습 사이클이 필요한 환경에서는 off로 유지.

## 9. 핵심 알고리즘 요약 (Layer A / Layer B)

| Layer | 트리거 | 호출량 | 알고리즘 |
|-------|--------|--------|---------|
| A (backfill) | 명시적 universe × periods | 종목당 ~2 (list + document) | `enumerate_targets` → `run_batch` (pending 순회) |
| B (incremental) | 매일 cron | 시즌 외 ~1, 시즌 내 ~40 | `scan_new_reports` (corp 무관 페이지네이션) → universe filter → DB diff → 신규만 ingest |

두 layer 모두 `RateBudget` (default cap 38000/day)을 공유. budget 초과 시 다음날 자동 재개.

## 11. KRX 자동 universe sync (Plan #5.2)

`active.txt` 수동 관리 대신 KRX KOSPI/KOSDAQ 전체 상장사를 자동 sync하는 모드.

### 일회성 초기 setup (자동 모드 전환)

```bash
# 1. corp_master refresh (분기 1회 또는 stale 90일+)
uv run themek dart sync-corp --if-stale-days 90

# 2. KRX 전체 sync (pykrx → Stock 테이블 ~2,500종목)
uv run themek krx sync-listed --dry-run                 # listed count 확인
uv run themek krx sync-listed                            # 실 sync

# 3. Stock 테이블 → BackfillTarget enroll (최근 2년 슬라이딩 윈도우)
#    매년 자동 최신 2년치: PREV_YEAR=$((CURRENT_YEAR-1)) — 예: 2026년 시점에 2025:2026
uv run themek dart backfill init --from-stocks \
    --periods 2025:2026                                  # dry-run (예시; 운영 시점 연도로 치환)
uv run themek dart backfill init --from-stocks \
    --periods 2025:2026 --confirm                        # 약 5,500 row 생성 (2,770종목 × 2년)

# 4. 첫 backfill (RateBudget 38K/day로 ~2-3일 분산)
uv run themek dart backfill run --purge-zip-after-extract
```

### cron 흐름 (자동 모드)

`scripts/themek_backfill.sh` 갱신본은 5단계:
1. `themek krx sync-listed --auto-enroll --periods PREV:CURRENT` — 신규 상장 자동 enroll (최근 2년치 슬라이딩 윈도우, `PREV=$((CURRENT_YEAR-1))`)
2. `themek dart sync-corp --if-stale-days 90` — 분기 1회 corp_master refresh
3. `themek dart incremental --universe-source stocks` — Stock 테이블 기반 universe
4. `themek dart backfill run --purge-zip-after-extract` — pending 처리
5. `themek dart backfill status --verbose` — lifecycle + 비용 요약

### `--universe-source file` vs `stocks` 선택 가이드

| 상황 | 권장 |
|------|------|
| KOSPI/KOSDAQ 전체 자동 운영 | `stocks` |
| 특정 종목군만 처리 (테마/MVP) | `file` (`active.txt`) |
| 임시 우선순위 백필 | `file` + 별도 universe 파일 |

### 신규 상장 / 상장폐지 모니터링

`themek dart backfill status --verbose` 출력에 다음 섹션이 포함된다:

```
=== Lifecycle (7일) ===
  신규 상장 (7일): 3
  상장폐지 (7일): 1
```

신규 상장 종목은 `--auto-enroll` 사용 시 자동 BackfillTarget enroll. 상장폐지 종목은 `delisted_at` set되며 다음 `--universe-source stocks` 호출부터 자동 제외.

### unlinked 종목 (pykrx ↔ corp_master 미매칭)

신규 상장 직후는 DART corp_master 등록 lag 며칠. `themek krx sync-listed` 결과 `unlinked=N`은 다음 sync에서 자동 retry되므로 무시 가능. 1주 이상 unlinked가 지속되면 `data/dart/corp_master.json`을 수동 refresh.
