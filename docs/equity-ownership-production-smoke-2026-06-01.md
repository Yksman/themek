# 지분구조(Equity Ownership) 프로덕션 스모크 — 2026-06-01

DART 정형 API(최대주주현황 `hyslrSttus` · 타법인출자현황 `otrCprInvstmntSttus`)에서
지분 관계를 추출해 graph core에 `OWNS_STAKE_IN` 엣지 + `person` 노드로 적재하고,
graph core에 등재된 39개 상장사 실데이터를 사업보고서(reprt_code=11011) 기준
2023·2024 사업연도로 적재·검증한 결과.

## 적재 절차

```bash
# 1) 적재 (사업보고서 11011, 2023-2024) — 회사별 try/except, 한 트랜잭션 커밋
#    ingest_equity_all(session, client, years=["2023","2024"])
# 2) 엔티티 해소
uv run themek ontology resolve
# 3) 검증 게이트
uv run themek equity verify
```

- 적재 결과: **companies=39, edges=4431, failed=0**
- 해소 결과: external companies resolved **7** (universe 내 계열사 매칭), unresolved 2045
  (universe 밖 종속·관계사 — 설계상 `company:ext`로 잔존), owners merged **1**,
  integrity errors **0**

## 검증 게이트 (`themek equity verify`) — exit 0 / `ok: True`

```
companies_total: 39
companies_with_ownership: 39
coverage: 1.0
owns_edges: 4424
person_nodes: 399
external_company_nodes: 2045
null_stake_pct_edges: 199
overstake_companies: 0
ok: True
```

| 게이트 | 기준 | 실측 | 판정 |
|---|---|---|---|
| coverage | ≥ 0.85 | **1.0** | ✅ |
| owns_edges | ≥ 200 | **4424** | ✅ |
| person_nodes | ≥ 30 | **399** | ✅ |
| overstake_companies | == 0 | **0** | ✅ |
| ok | True | **True** (exit 0) | ✅ |

> `null_stake_pct_edges: 199` — 공시 원문에서 지분율이 비어 있거나(`-`) 0인 행
> (소액 임원·우리사주 등). 적재는 유지하되 `stake_pct=None`으로 보존.

## 표본 수기 대조 — 삼성전자(00126380), 2024 사업연도

`largest_shareholders(s, "company:00126380")` 상위 (지분율 내림차순):

| 주주 | 지분율 | 비고 |
|---|---|---|
| 삼성생명보험㈜ | **8.51%** | 최대주주 본인 — 공시값 일치 |
| 삼성물산㈜ | 5.01% | 계열회사 — 공시값 일치 |
| 홍라희 | 1.64% | 특수관계인(person) |
| 이재용 | 1.63% | 특수관계인(person) — 공시값 일치 |
| 삼성화재해상보험㈜ | 1.49% | 계열회사 |

타법인 출자(`owned_companies`) 표본: 삼성전기㈜ 23.7%[관계회사], 세메스㈜ 91.5%[자회사],
삼성전자서비스㈜ 99.3%[자회사], 해외 100% 종속법인 다수[자회사].

→ 알려진 최대주주(삼성생명보험 8.51%)·오너(이재용 1.63%)가 **공시값과 ±0.5%p 이내**로 일치.

## vault 투영

```bash
uv run themek vault build
```

- `## 지분구조` 섹션 포함 회사 노트: **2079** (universe 39 + `company:ext` 피출자/주주 노드)
- `vault/people/` person 노트: **376**
- 예) `vault/people/이재용.md` → `## 보유 회사 (1) — [[삼성전자]] — 1.63%`

## 적재 중 발견·수정한 데이터 품질 이슈

실 DART 데이터가 초기 휴리스틱보다 복잡해 3건을 수정(코드+회귀 테스트 추가):

1. **주식종류(stock_knd) 행 붕괴** — 한 주주가 보통주/우선주 2행으로 와서 엣지 키
   (subject,object,period)가 충돌, 마지막(우선주) 행이 보통주를 덮어써 삼성생명보험이
   8.51%→0.01%로 왜곡. → `ingest_largest_shareholders`를 **holder별 최대 지분율
   (보통주=의결권) 행 채택**으로 변경.
2. **합계행(`계`/`소계`/`합계`/`총계`) 오적재** — 표 합계행이 `person:계` 등 가짜
   주주로 적재. → 해당 nm 행 적재 제외.
3. **개인 임원의 company 오분류** — "계열회사 임원"의 `계열회사` 키워드 때문에 이부진·
   이서현 등 개인이 `company:ext`로 분류. → 분류기에 개인 신호(`임원|배우자|자녀|친인척|
   형제|친족`)를 법인 관계 신호보다 우선 적용(단, 이름의 법인 접미사가 있으면 company 유지).

추가로 `resolve_external_companies`가 외부법인을 universe로 병합할 때 **object 엣지만**
재지정해 외부법인이 법인 최대주주(subject)로 등장하면 `DELETE` 시 FK 위반이 나던 버그를
수정(subject 엣지도 `_repoint_subject_edges`로 재지정).

## 비고

- `themek.db`는 `.gitignore` 대상(로컬 재생성 가능 아티팩트). 본 적재는 실 DB에 반영됨.
- 마이그레이션 0008은 enum 허용값이 Python(`NODE_KINDS`/`PREDICATES`) 레벨에서만 강제되고
  컬럼 길이가 충분(`person`/`OWNS_STAKE_IN`)하므로 **no-op**(DDL 없음). 0005의 표현식 기반
  unique 인덱스 `ux_edge_spo` 보존을 위해 `batch_alter_table` 재생성을 제거.

## 부록 — 적재 대상 39개사 (corp_code)

`data/universe/equity_smoke.txt` (gitignore된 로컬 universe; graph core의 dart_code 보유 company 노드 전수):

```
00108746  DKME
00109693  DL
00113410  CJ대한통운
00115694  DB증권
00117726  DYP
00118345  디아이동일
00120030  GS건설
00122579  BYC
00126089  DH오토넥스
00126380  삼성전자
00129013  CJ씨푸드
00138190  GS글로벌
00148540  CJ
00148984  시알홀딩스
00149026  CS홀딩스
00159102  DB손해보험
00160843  DB하이텍
00161383  한미반도체
00163345  DB
00164636  HDC
00164742  현대자동차
00164779  SK하이닉스
00164830  HD한국조선해양
00165583  E1
00258801  카카오
00266961  NAVER
00303873  CJ CGV
00350312  HDC랩스
00356361  LG화학
00357935  HDC현대EP
00365387  AJ네트웍스
00635134  CJ제일제당
00858364  BNK금융지주
01160363  에코프로비엠
01205842  HD건설기계
01261644  레인보우로보틱스
01263022  BGF리테일
01568413  F&F
01882845  GS피앤엘
```
