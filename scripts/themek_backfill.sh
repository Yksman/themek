#!/bin/bash
# Plan #5 + #5.2 — daily cron wrapper
# 매일 KST 5시 권장 (DART 한도가 KST 0시에 reset된 후 안정화 시간).

set -euo pipefail

# repo dir — cron 등록 시 절대 경로로 수정
THEMEK_DIR="${THEMEK_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$THEMEK_DIR"

if [ -f .env ]; then
    # shellcheck disable=SC1091
    source .env
fi

DATE=$(date +%Y%m%d)
mkdir -p data/log

# 0. KRX 상장사 sync (Plan #5.2)
#    신규 상장은 자동 BackfillTarget enroll (2023:current 3년치 백필)
CURRENT_YEAR=$(date +%Y)
uv run themek krx sync-listed \
    --auto-enroll --periods "2023:${CURRENT_YEAR}" \
    >> "data/log/krx_sync_${DATE}.log" 2>&1

# 1. DART corp_master refresh (90일 이내면 skip)
uv run themek dart sync-corp --if-stale-days 90 \
    >> "data/log/corp_sync_${DATE}.log" 2>&1

# 2. daily incremental (가벼움 — 시즌 외에는 ingested ≈ 0)
uv run themek dart incremental \
    --universe-source stocks \
    --since yesterday --until today \
    --purge-zip-after-extract \
    >> "data/log/incremental_${DATE}.log" 2>&1

# 3. backfill 남은 작업 진행 (한도까지)
uv run themek dart backfill run \
    --purge-zip-after-extract \
    >> "data/log/backfill_${DATE}.log" 2>&1 \
    || echo "backfill ended (budget or done)"

# 4. status 요약 (lifecycle 포함)
uv run themek dart backfill status --verbose \
    >> "data/log/status_${DATE}.log" 2>&1
