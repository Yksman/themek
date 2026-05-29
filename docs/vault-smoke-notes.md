# Vault Smoke Build — 검증 메모 (2026-05-29)

## 명령
`uv run themek vault build --out vault`

## 결과 (실 themek.db)
- companies: 44
- customers(미연결 포함): 155
- segments: 151 / regions: 6 / sectors: 2
- 검출 이슈: 57
  - missing_geo 17
  - segment_no_revenue 15
  - missing_customer 13
  - geo_duplicate 5
  - low_segment_count 4
  - revenue_sum_anomaly 2
  - unresolved_customer 1 (전역 요약: 155건 entity/descriptive 분류)

## 자동 무결성 점검
- wikilink 무결성: total link targets 353, **missing files: 0** (모든 wikilink 대상 노트 실재)
- 삼성전자 노트: `미주` 지역 노출 렌더 확인 (`samsung geo OK`)
- `_qa-report.md`에 `geo_duplicate` 2건 출현(삼성 미주 중복 포함)

## Obsidian 확인
1. Obsidian → "Open folder as vault" → `themek/vault` 선택
2. Graph View(Ctrl/Cmd+G): 회사–세그먼트–고객–지역 노드 망 렌더 확인
3. `Apple Inc.` 노트: 백링크 패널에 다수 회사 → 공급망 허브 확인
4. `_qa-report.md`: 삼성전자 `미주` 중복 등 이슈 나열 확인
5. (선택) Settings → Appearance/Graph → tag `unresolved/entity` vs `unresolved/descriptive` 색상 그룹 지정 시 실회사 후보/설명문 구분

## 알려진 한계
- 세그먼트 dedupe는 name_ko 정확 일치 기준 ("기타" 등 일반명 과병합 가능 — QA info 아님, 후속 검토)
- 매출비중 합 100 초과는 중첩 세그먼트(DX⊃스마트폰 등) 구조상 정상일 수 있음 — warn은 점검 유도용
