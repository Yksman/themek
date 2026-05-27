# Pre-Backfill Validation Plan

> **For agentic workers:** 이 plan은 코드 변경이 아닌 **운영 검증 절차**. TDD 아님.
> 각 step의 success/failure metric에 따라 다음 step 또는 별도 plan으로 분기.

**Goal:** 현재 E5 추출 stack(Plan #1+#3+#4+#6)이 *프로덕션 backfill(Plan #5)에
넣어도 안전한지* 3단계로 정량 검증한다. GT 0~1건만으로 시작해서, Step별 게이트
통과 시에만 다음 단계 진행.

**Scope:**
- **In:** 3종목(005930·005380·277810) × 2023 단일 period 검증
- **Out:** 다종목 batch 자동화, 시계열 backfill, prompt 최적화 자체

**Prerequisites:**
- ✅ Plan #1/#3/#4/#6 follow-up 완료 (198 tests passing)
- ✅ `.env`에 `DART_API_KEY` 설정
- ✅ `claude` CLI 로그인 (`claude --version` 응답)
- ✅ `themek dart sync-corp` 1회 실행 완료
- 신규 코드 작성: 합의 기반 GT 추출 helper script 1건 (~30 LoC)

**예상 소요:** 사용자 active 3시간 + LLM 호출 대기 1시간 = 반나절

---

## Step 1 — 실 LLM Smoke Run

**목적:** 3종목 모두 실 `claude` CLI로 ingest end-to-end 정상 동작 + cost가
예상 범위 내인지 확인.

### Commands

- [ ] **1-1: 캐시 비우고 fresh ingest 수행** (이미 캐시 있으면 skip 가능)

```bash
# 3종목 ingest (실 LLM 호출 — 종목당 30~60초)
mkdir -p data/eval/smoke
for t in 005930 005380 277810; do
  echo "=== Ingesting $t ==="
  uv run themek dart ingest --ticker $t --period 2023 \
    2>&1 | tee data/eval/smoke/ingest_${t}_2023.log
done
```

- [ ] **1-2: 각 종목의 escalation_level / output_chars 확인**

```bash
grep "section_filter" data/eval/smoke/ingest_*.log
```

기대 출력 예:
```
ingest_005930_2023.log:[section_filter] escalation=regex output_chars=38085 invalid=[]
ingest_005380_2023.log:[section_filter] escalation=regex output_chars=187340 invalid=[]
ingest_277810_2023.log:[section_filter] escalation=regex output_chars=22416 invalid=[]
```

- [ ] **1-3: DB row + idempotency 확인**

```bash
# DB에 3 row 들어갔는지
uv run python -c "
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import BusinessReport
with make_session_factory(make_engine())() as s:
    for r in s.query(BusinessReport).all():
        print(r.corporation_id, r.period, r.dart_rcept_no, len(r.raw_text_excerpt))
"

# 재실행이 cache hit + DB idempotent인지 (DART API 0회 호출되어야 함)
for t in 005930 005380 277810; do
  uv run themek dart ingest --ticker $t --period 2023 \
    2>&1 | grep -E "(section_filter|fetch)"
done
```

### Success Metrics

| 지표 | 임계 | 측정 방법 |
|------|------|----------|
| **종목별 exit code** | 모두 0 | `echo $?` 또는 log 마지막 줄 `Ingested report …` |
| **escalation_level** | 모두 `regex` 또는 `regex+llm` (3종목 OK) | grep `section_filter` |
| **DB row 수** | 3 | sqlite query |
| **재실행 cache hit** | 두 번째 run에서 DART API 0회 | network 모니터링 (또는 ingest 로그에 fetch 메시지 없음) |
| **종목당 LLM 비용** | < $0.10 (T5 spec §9.1 예측 대비 2.5배 여유) | `data/eval/smoke/ingest_*.log` 또는 claude usage |

### Failure 신호 → 대응

| 증상 | 의미 | 다음 행동 |
|------|------|----------|
| exit ≠ 0 | DART API 또는 LLM 호출 실패 | log 확인, 일시 장애면 재시도, 재현되면 별도 issue |
| escalation_level == `full_text` | Plan #4 escalation이 못 잡음 — 추출 품질·비용 모두 위험 | Step 2/3 진행 보류. learned_header_patterns에 수동 패턴 추가 후 ingest 재실행 |
| `invalid_targets` 비어있지 않음 | 일부 target이 MIN_SECTION_CHARS 미달 | section_resolution.json 살펴보고 fixture variant 등록(`dart parser-learn` trigger) |
| 비용 > $0.10/종목 | output_chars 큼 또는 prompt 길어짐 | section filter 결과 점검. 현대차는 특수 case로 별도 분리 검토 |

**Gate**: 5개 success metric 모두 통과 → Step 2. 하나라도 fail → 위 표대로 처리
또는 별도 plan 작성 후 재시도.

---

## Step 2 — Stability (run-to-run 일관성)

**목적:** 동일 입력에 LLM이 결정적인지 정량 측정. GT 없이도 가능.

### Commands

- [ ] **2-1: 빈 GT 파일 1회 생성** (Step 2/3 공용, 점수는 안 보고 save-runs만 사용)

```bash
mkdir -p data/eval/ground_truth
cat > /tmp/empty_gt.json <<'EOF'
{
  "metadata": {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"},
  "extraction": {"period": "2023", "segments": [], "customers": [], "geographic": []}
}
EOF
```

- [ ] **2-2: 삼성 1종목으로 N=5 run** (실 LLM 5회 — ~5분 대기)

```bash
# rcept_no는 Step 1에서 ingest한 결과의 캐시 경로에서 확인
SAMSUNG_HTML=$(ls -t data/dart/raw/*/business.html | head -1)
echo "사용할 HTML: $SAMSUNG_HTML"

uv run themek eval e5 \
  --html-file $SAMSUNG_HTML \
  --period 2023 \
  --ground-truth /tmp/empty_gt.json \
  --runs 5 \
  --save-runs data/eval/runs/stability \
  | tee data/eval/runs/stability/eval_output.txt
```

(점수는 n/a로 나오는 게 정상 — GT가 비어 있음. 우리가 보는 건 `parsed_extraction`)

- [ ] **2-3: 합의 추출 helper script 작성** — `scripts/consensus_gt.py` 신규

```python
"""5개 run의 parsed_extraction에서 모두 등장한 항목만 추출.

usage: python scripts/consensus_gt.py <save-runs-dir>/<ticker>_<period> [threshold]
"""
import json, sys
from pathlib import Path
from collections import Counter

run_dir = Path(sys.argv[1])
threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 5

runs = [json.loads(p.read_text(encoding="utf-8"))["parsed_extraction"]
        for p in sorted(run_dir.glob("run_*.json"))]
n = len(runs)

def consensus(items_per_run, key):
    cnt = Counter()
    for items in items_per_run:
        for it in items:
            cnt[it[key]] += 1
    return sorted([k for k, c in cnt.items() if c >= threshold])

seg_per = [r["segments"] for r in runs]
cust_per = [r["customers"] for r in runs]
geo_per = [r["geographic"] for r in runs]

print(f"=== Stability ({n} runs, threshold={threshold}) ===")
print(f"segments  union={len(set().union(*[{s['name_ko'] for s in r} for r in seg_per]))}"
      f"  consensus={len(consensus(seg_per, 'name_ko'))}"
      f"  : {consensus(seg_per, 'name_ko')}")
print(f"customers union={len(set().union(*[{c['name_raw'].lower() for c in r} for r in cust_per]))}"
      f"  consensus={len(consensus(cust_per, 'name_raw'))}")
print(f"regions   union={len(set().union(*[{g['region_code'] for g in r} for r in geo_per]))}"
      f"  consensus={len(consensus(geo_per, 'region_code'))}"
      f"  : {consensus(geo_per, 'region_code')}")

# share_pct 흔들림 (segment name 기준)
import statistics
share_var = {}
for r in seg_per:
    for s in r:
        if s.get("share_pct") is not None:
            share_var.setdefault(s["name_ko"], []).append(s["share_pct"])
print("\nshare_pct stdev per segment (matched 2회 이상):")
for name, vals in sorted(share_var.items()):
    if len(vals) >= 2:
        print(f"  {name:30s}: mean={statistics.mean(vals):.2f} stdev={statistics.stdev(vals):.2f}  n={len(vals)}")
```

- [ ] **2-4: 합의 분석 실행**

```bash
uv run python scripts/consensus_gt.py data/eval/runs/stability/005930_2023 5
```

기대 출력 예:
```
=== Stability (5 runs, threshold=5) ===
segments  union=7  consensus=6  : ['DS - 메모리', 'DS - S.LSI/파운드리', 'DX - MX', 'DX - VD/DA', 'Harman', '기타']
customers union=3  consensus=3
regions   union=5  consensus=5  : ['CN', 'EU', 'KR', 'ROW', 'US']

share_pct stdev per segment:
  DS - 메모리                       : mean=21.50 stdev=0.00 n=5
  DX - MX                           : mean=35.50 stdev=0.30 n=5
  Harman                            : mean=5.00  stdev=0.00 n=5
  ...
```

### Success Metrics

| 지표 | 임계 | 의미 |
|------|------|------|
| **segment consensus / union** | ≥ 0.8 | run 간 segment 분류 흔들림 적음 |
| **customer consensus / union** | ≥ 0.7 | 고객사는 narrative라 다소 느슨 |
| **region consensus / union** | ≥ 0.9 | 지역 매핑은 결정적이어야 함 |
| **share_pct stdev (per matched segment)** | ≤ 1.0 %p (평균) | 수치 흔들림 작음 |
| **total cost** | < $0.20 (5 runs × 1 종목) | 비용 예측 가능 |

### Failure 신호 → 대응

| 증상 | 의미 | 다음 행동 |
|------|------|----------|
| segment consensus < 0.5 | LLM이 segment를 매 run 다르게 분류 — prompt가 모호 | Step 3 진행 안 함. prompt 보강 별도 plan |
| customer 흔들림 크지만 segment 안정 | customer enumeration이 본질적으로 모호 (DART 본문에 명시 안 됨) | 허용 가능, Step 3에서 customer metric은 정보 용도로만 |
| share_pct stdev > 2 %p | 수치 추출이 흔들림 — 표 파싱 prompt 문제 | prompt 또는 section filter 보강 plan |
| 한 run에서 segments 0개 | LLM이 빈 응답 — section_resolution 보고 진단 | section_resolution.json의 escalation_level 확인 |
| cost > $0.20 | output_chars 큰데 모든 run에서 동일 | 정상 (input 길이가 변하지 않음). prompt 압축 검토는 후속 |

**Gate**: 위 5개 중 4개 이상 통과 → Step 3. 미달 → 보강 plan 작성.

---

## Step 3 — Accuracy Sanity Check

**목적:** 추출 결과가 *실제로* 사업보고서와 일치하는지 1종목 검증.
N=5 합의(Step 2)를 GT 초안으로 사용, 사용자는 그 위에 *명백한 오류*만 수정.

### Commands

- [ ] **3-1: 합의 기반 GT 초안 생성** — `scripts/build_gt_draft.py` 신규
  (Step 2의 consensus_gt.py 확장)

```python
"""run_*.json의 consensus를 GT JSON 포맷으로 변환.

usage: python scripts/build_gt_draft.py <save-runs-dir>/<ticker>_<period> <ticker> <name_ko> <period> <output>
"""
import json, sys
from pathlib import Path
from collections import defaultdict
import statistics

run_dir, ticker, name_ko, period, out_path = sys.argv[1:6]
runs = [json.loads(p.read_text(encoding="utf-8"))["parsed_extraction"]
        for p in sorted(Path(run_dir).glob("run_*.json"))]
n = len(runs)
THRESHOLD = max(3, n - 1)  # 최소 4/5 또는 3/3 일치

def consensus_dict(items_per_run, key):
    cnt = defaultdict(list)
    for items in items_per_run:
        for it in items:
            cnt[it[key]].append(it)
    return {k: v for k, v in cnt.items() if len(v) >= THRESHOLD}

seg_groups = consensus_dict([r["segments"] for r in runs], "name_ko")
cust_groups = consensus_dict([r["customers"] for r in runs], "name_raw")
geo_groups = consensus_dict([r["geographic"] for r in runs], "region_code")

def avg_share(group, field="share_pct"):
    vals = [item[field] for item in group if item.get(field) is not None]
    return round(statistics.mean(vals), 2) if vals else None

segments = [
    {"name_ko": k, "share_pct": avg_share(g),
     "description": None, "products": []}
    for k, g in sorted(seg_groups.items(), key=lambda kv: -(avg_share(kv[1]) or 0))
]
customers = [
    {"name_raw": k, "revenue_share_pct": avg_share(g, "revenue_share_pct"),
     "tier": (g[0].get("tier") or "1차")}
    for k, g in cust_groups.items()
]
geographic = [
    {"region_code": k, "share_pct": avg_share(g)}
    for k, g in sorted(geo_groups.items(), key=lambda kv: -(avg_share(kv[1]) or 0))
]

gt = {
    "metadata": {
        "ticker": ticker, "name_ko": name_ko, "period": period,
        "source": "consensus_draft",
        "consensus_threshold": THRESHOLD, "n_runs": n,
        "notes": "N-run intersection draft. 사람 review 필요.",
    },
    "extraction": {
        "period": period, "segments": segments,
        "customers": customers, "geographic": geographic,
    },
}
Path(out_path).write_text(
    json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"wrote {out_path} — segments={len(segments)} customers={len(customers)} regions={len(geographic)}")
```

```bash
mkdir -p data/eval/ground_truth
uv run python scripts/build_gt_draft.py \
  data/eval/runs/stability/005930_2023 \
  005930 삼성전자 2023 \
  data/eval/ground_truth/samsung_e5_2023_draft.json
```

- [ ] **3-2: 사람 review (10-15분)**

`data/eval/ground_truth/samsung_e5_2023_draft.json` 열고:
- 사업보고서 매출 비중 표 1페이지 직접 확인 (이미 알고 있는 회사라면 기억으로도 가능)
- 명백히 틀린 segment 이름 / share_pct 1-2개 수정
- 명백한 환각 segment 1-2개 삭제
- 누락된 핵심 segment 1-2개 추가
- 파일을 `samsung_e5_2023.json`으로 rename

(목적: 절대 정답이 아니라 *대략적인 진실*. 후속 단계 점수가 baseline)

- [ ] **3-3: 정식 baseline eval** (실 LLM 3 run)

```bash
uv run themek eval e5 \
  --html-file $SAMSUNG_HTML \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  --runs 3 \
  --save-runs data/eval/runs/baseline \
  | tee data/eval/runs/baseline/samsung_eval.txt
```

- [ ] **3-4: 점수표 + missed/extra 검토**

`samsung_eval.txt`의 mean ± stdev 점수표와 union 진단 리스트 확인.

### Success Metrics (절대 기준 아닌 *프로덕션 진입 sanity*)

| 지표 | 임계 | 의미 |
|------|------|------|
| **segment_recall_mean** | ≥ 0.80 | truth segment의 80% 이상 잡음 |
| **segment_precision_mean** | ≥ 0.80 | 환각 segment 20% 미만 |
| **share_pct_mae_mean** | ≤ 2.0 %p | 수치 평균 절대오차 2%p 이내 |
| **region_recall_mean** | ≥ 0.80 | 지역 80% 매핑 |
| **3개 metric의 stdev** | ≤ 0.10 | run 간 안정 |
| **total cost** | < $0.15 (3 runs) | 예측 범위 |

**Note**: customer metric은 정보 용도로만 사용 — DART 본문에 명시되지 않은
경우가 흔해 합의 GT 자체가 부분적.

### Failure 신호 → 대응

| 증상 | 의미 | 다음 행동 |
|------|------|----------|
| segment_recall < 0.6 | LLM이 부문 인식 못함 | prompt에 부문 분류 example 추가 plan |
| precision < 0.6 (recall은 OK) | 환각 심함 | prompt에 "수치 명시된 것만" 강조 |
| share_pct_mae > 5 %p | 수치 잘못 읽음 | 표 파싱 prompt 보강 또는 Layer 3 (DART 표 파서) 도입 plan |
| stdev > 0.20 | run 간 점수 흔들림 — Step 2가 underestimate한 것 | N=5로 재측정 후 prompt 보강 |
| cost > $0.15 | 비용 예측 실패 | section filter 효율 점검 후 trimming plan |
| 점수 만족하지만 missed_union에 핵심 항목 | 사람의 GT review가 부실했을 수도 | review 1회 더 또는 다른 종목으로 sanity 추가 |

**Gate**:
- 6개 metric 모두 통과 → Plan #5 작성 ready
- 1-2개 미달이지만 명확한 원인 있음 → 보강 plan 1개 작성 후 Step 3 재실행
- 다수 미달 → Plan #5 보류, 큰 구조 변경 plan 필요

---

## 전체 완료 기준

이 plan은 다음 산출물 + 결정으로 종료:

1. **데이터**
   - `data/eval/smoke/ingest_*.log` 3건 (Step 1)
   - `data/eval/runs/stability/005930_2023/run_*.json` 5건 (Step 2)
   - `data/eval/runs/baseline/005930_2023/` summary + run × 3 (Step 3)
   - `data/eval/ground_truth/samsung_e5_2023.json` 사람이 검증한 GT 1건

2. **코드** (신규)
   - `scripts/consensus_gt.py` (~30 LoC)
   - `scripts/build_gt_draft.py` (~50 LoC)
   - 위 2건은 `/scripts/`가 gitignore이므로 commit 안 함. 필요 시 별도 plan에서 정식 명령으로 승격.

3. **문서**
   - `docs/dart-e5-prebackfill-validation-2026-05-XX.md` — 3 step 결과 + 비용 합산 + 결정 요약

4. **결정**: 다음 셋 중 하나
   - **GO**: Plan #5 backfill spec 작성 시작 — 본 plan 결과를 입력으로
   - **FIX-AND-RETRY**: 약점 plan 1-2개 작성 후 Step 3만 재실행
   - **HALT**: 구조 변경 필요 — Plan #4 learning 추가 사이클 또는 prompt 재설계

---

## 위험 / Note

- **Step 1-3은 실 LLM 호출 = 구독 토큰 소모**. 총 합산 ~$0.50 예상 (예측 spec §9.1
  대비 1종목으로 한정해 보수적).
- **삼성 1종목만 검증**은 의도된 좁힘. 나머지 2종목(현대차·레인보우)은 Plan #5
  진입 *후* sample 확장 단계에서 다룸.
- **GT 사람 review의 정확도**는 사용자 본인의 도메인 지식에 의존. 의심스러우면
  Step 3-2를 30분으로 늘리고 사업보고서 표를 직접 봄.
- **삼성이 anomaly한 경우**: 6 segment의 다국적 대기업이라 노이즈가 작은 편.
  현대차(자동차+금융 2 부문)에서는 다른 패턴이 나올 수 있음 — Plan #5 안에서
  종목별 점수 분포 측정 필요.
