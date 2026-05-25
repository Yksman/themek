# E5 Eval Harness — Smoke Run Baseline

**실행일:** 2026-05-25
**Ground truth:** `data/eval/ground_truth/samsung_e5_2023.json`
**Fixture:** `tests/fixtures/samsung_business_report_excerpt.html`
**LLM:** Claude Code subscription via `claude -p`

## Command

```bash
uv run themek eval e5 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  | tee /tmp/eval_run.txt
```

## Output (1회 run)

```
=== Eval: E5 — 삼성전자 (005930) period=2023 ===
Ground truth:  data/eval/ground_truth/samsung_e5_2023.json
HTML fixture:  tests/fixtures/samsung_business_report_excerpt.html

Segments        recall= 6/6 = 1.000    precision= 6/6 = 1.000
Customers       recall= 1.000    precision= 1.000
Regions         recall= 1.000    precision= 1.000
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

## Analysis

- **Segments (recall 1.000 / precision 1.000):** truth의 6개 사업부문(DS - 메모리 / DS - S.LSI/파운드리 / DX - MX / DX - VD/DA / Harman / 기타) 모두 LLM이 name_ko exact match로 추출. 누락/환각 없음.
- **Customers (recall 1.000 / precision 1.000):** Apple Inc., 글로벌 통신사업자 A (비공개), 글로벌 OEM B (비공개) 3건이 case-insensitive name_raw exact로 일치.
- **Regions (recall 1.000 / precision 1.000):** KR / US / EU / CN / ROW 5개 region_code 모두 일치. 특히 fixture HTML의 "아시아(중국·일본 외) 13.2%"과 "기타 지역 6.0%"이 둘 다 `ROW`로 매핑되고 ingest 단계의 dedup(이슈 #2 fix)을 거치면 19.2%로 합산 — eval은 region_code set 비교라 합산 전 1건씩 매핑한 LLM 출력으로도 set 일치는 만족.
- **Share_pct MAE (0.00 %p, matched=6):** matched 6개 segment의 share_pct가 truth와 완전 일치 (LLM이 fixture 표의 "약 21.5%" 같은 표기를 21.5로 정규화).

## Notes

- 실 LLM은 비결정적이므로 같은 입력 두 번째 run에서 점수가 다를 수 있음. 이번 결과는 1회 run 기준이며 향후 prompt/모델 변경 시 비교 baseline.
- HBM 표기는 ground truth에 `"HBM"`, fixture HTML에 `"HBM (고대역폭메모리)"`이지만 share_pct/segment 매칭은 name_ko 기준이라 영향 없음. products 배열은 현재 metric에 포함되지 않음.
- 후속: sample 추가(sector별 대표 종목), N회 run 평균, CI 통합, fuzzy customer matching — 모두 spec section 3.2 참조.
