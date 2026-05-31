# DART Backfill Recon — 2026-05-27 (Plan #5 T0)

Plan #5 Layer B 알고리즘이 의존하는 3개 가정을 1회 실 호출로 검증한다.

## Recon 호출

```
GET https://opendart.fss.or.kr/api/list.json
    ?crtfc_key=<KEY>
    &bgn_de=20240301
    &end_de=20240331
    &pblntf_ty=A
    &page_count=100
    &page_no=1
```

(2026-03 정기 시즌은 본 plan 작성 시점에서 아직 미래이므로 데이터가 안정적으로 존재하는 2024-03 정기공시 시즌으로 검증)

## 가정 1: corp_code 없이 list.json 동작 — ✅ PASS

- 결과: `status="000"`, `total_count=3378`, `list_len=100`
- 의미: `corp_code` 파라미터 없이 `bgn_de`/`end_de`/`pblntf_ty`만으로 호출 가능. DART OpenAPI가 시간 범위 내 전체 정기공시 list를 페이지네이션으로 반환.

→ Layer B의 핵심 알고리즘(시간 범위 단일 호출 + universe filter)이 성립.

## 가정 2: 호출 한도 reset 시점 — KST 0시

- 측정 방법: DART OpenDART 운영 가이드(공식 FAQ) 명시. 본 recon 호출 시점(2026-05-27 KST 오후)에서 별도 한도 초과 응답 없음.
- 결과: KST 0시 (Asia/Seoul 자정 기준)

→ `RateBudget._today_kst()` 가 `ZoneInfo("Asia/Seoul")` 의 date 기준으로 reset 판단.

## 가정 3: `total_page` 필드 존재 — ✅ PASS

- 결과: `payload["total_page"] = 34` (not None)
- 의미: 페이지네이션 종료 조건을 `page_no >= total_page` 로 안전하게 결정 가능.

→ `scan_new_reports` while-loop의 종료 조건이 결정적.

## 사업보고서 비율 (참고)

- 2024-03 정기공시 첫 페이지(100건) 중 사업보고서 형태: **48/100 (48%)**
- 정기 시즌(3월 말 마감) 기간 평균. 시즌 외에는 사업보고서 비율 ≈ 0.

→ 페이지네이션 비용은 시즌 외에는 매우 낮음. 시즌 내 약 34페이지 × 100건/페이지 = 3,378건 정기공시 / 사업보고서만 보면 ~1,600건. universe filter로 줄여진다.

## Cassette 저장

`tests/fixtures/dart_cassettes/list_json_corp_code_optional_2024.yaml`

→ 실제 응답 JSON dump 저장. 향후 incremental scanner 단위 테스트가 이 fixture 일부를 활용 가능 (full payload 대신 list[:N] 슬라이스).

## 후속 영향

- 가정 1·3 모두 PASS — Layer B 알고리즘(Plan T6/T7) 그대로 진행.
- T0 critical gate 통과. 본 plan 진행 가능.
