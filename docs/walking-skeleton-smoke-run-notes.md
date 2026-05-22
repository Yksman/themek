# Walking Skeleton — 실 Claude CLI Smoke Run 메모

**실행일:** 2026-05-23
**대상:** Samsung 사업보고서 (synthetic fixture, rcept_no=20240314000123)
**LLM:** Claude Code subscription via `claude -p --output-format json` subprocess

## 실행 명령

```bash
rm -f themek.db
uv run alembic upgrade head
uv run themek seed
uv run themek ingest \
  --rcept-no 20240314000123 \
  --corp 00126380 \
  --report-type 사업보고서 \
  --period 2023 \
  --filing-date 2024-03-14 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123"
uv run themek query e5 --ticker 005930
```

## 결과

### Pipeline Health (A1~A4)
- A1 End-to-end 완주: ✓ exit 0 모두
- A2 Test suite green: ✓ 46/46 passed
- A3 Migration 정합성: ✓ (drop_all+create_all + alembic upgrade 모두 정상)
- A4 Idempotency: ✓ test_ingest_is_idempotent 통과

### Extraction Accuracy (B1~B7) — 1건 fixture 기준 eyeball

Ground truth = fixture에 명시된 표.

| 항목 | Ground truth | Extracted | 판정 |
|---|---|---|---|
| Segments 수 | 6 (DS-메모리, DS-S.LSI/파운드리, DX-MX, DX-VD/DA, Harman, 기타) | 6 (동일) | ✓ recall=1.0, precision=1.0 |
| Segment share_pct | 21.5/9.0/35.5/14.5/5.0/14.5 합=100 | 동일 (1:1 match) | ✓ MAE=0.0%p |
| Customers 수 | 3 명시된 매출처 + 기타 | 3 명시된 매출처 | ✓ recall=1.0 |
| Apple share_pct | 13.6% | 13.6% | ✓ |
| Geographic 지역 | KR/US/EU/CN/아시아(→ROW)/기타(→?) | KR/US/EU/CN/ROW 5종 (top5 limit) | ⚠ "아시아" + "기타" 매핑 처리 — 일부 결합/누락 |
| Geographic share 합 | 100% (KR 14.8 + US 35.6 + EU 13.4 + CN 17.0 + 아시아 13.2 + 기타 6.0) | top5: 35.6+17.0+14.8+13.4+13.2=94% | ⚠ "기타 6.0%"가 top5 밖 (정상) |
| Hallucination | 추출 항목 중 ground truth 외 항목 없음 | 없음 | ✓ B7=0 |

### Answer Quality (C1~C4)
- C1 Citation: ✓ DART rcept_no + URL + period 모두 답변에 포함
- C2 Structural completeness: ✓ 사업부문/고객사/지역 3 섹션 모두 출력
- C3 Empty-data fallback: ✓ unit test 통과
- C4 답변 길이: ~750 char (300~3000 범위 내)

### Performance (E1~E4)
- E1 Ingestion latency: ~30-60s (claude CLI subprocess; 정상 범위)
- E2 Query latency: <1s (DB 쿼리 + 템플릿)
- E3 Test suite: 0.59s
- E4 DB size: <50KB after 1 ingest

## 발견 사항 / 후속 작업

1. **Top-N limit으로 인한 지역 누락** — 현재 `top_n_regions=5`이라 6개 region이 있으면 "기타" 같은 작은 비중은 누락. 운영 시 사용자가 N을 조정 가능하게 하거나 합계가 100%에 못 미치면 "기타 X%" 라인을 자동 추가하는 게 좋음.
2. **"아시아" 같은 비표준 지역명 매핑** — LLM이 "아시아 (중국·일본 외)"를 ROW로 매핑함 (적절). 다만 prompt에서 더 명시적인 매핑 가이드 강화 가능.
3. **Customer resolved=False 기본값** — 모든 추출 customer가 buyer_raw로만 들어감 (Corporation 매핑 없음). 후속 plan에서 corp resolution layer 추가.
4. **합성 fixture의 한계** — 실제 DART HTML은 더 복잡 (XBRL 임베드, 다중 표 등). 후속 plan에서 실 DART 다운로드 + parser 강건성 검증.

## 결론

Walking skeleton 목적 달성: end-to-end pipeline이 실 Claude CLI를 통해 정확하게 작동. 추출 품질·답변 품질·citation 모두 정상. 다음 plan에서 다른 CQs (E1~E4·E6~E8) + Theme/Narrative/Membership layer 추가 가능.
