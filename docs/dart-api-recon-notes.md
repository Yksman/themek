# DART API Recon — 2026-05-25

실 DART OpenAPI 호출 결과 + spec/plan 가정 차이 정리.

## 1. corpCode.xml — ✅ 가정 일치

- URL: `https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=<KEY>`
- 응답: HTTP 200, `application/x-msdownload;charset=UTF-8`, **3,579,368 bytes** zip
- zip 내부: `CORPCODE.xml` 단일 파일 (29,912,902 bytes)
- 컬럼: `corp_code`(8) / `corp_name` / `stock_code`(6 or 빈 문자열) / `modify_date`(YYYYMMDD)
- 총 118,145 row
- 삼성전자: `corp_code=00126380`, `stock_code=005930`, `corp_name=삼성전자`

→ `parse_corp_code_zip` 휴리스틱(`<list>` 반복 + 4 컬럼) 그대로 작동.

## 2. list.json — ✅ 가정 일치

- URL: `https://opendart.fss.or.kr/api/list.json`
- 파라미터: `crtfc_key`, `corp_code=00126380`, `bgn_de=20240101`, `end_de=20240701`, `pblntf_ty=A`, `page_count=100`
- 응답: HTTP 200, JSON, `status="000"`, `message="정상"`
- list 길이: 2 (반기보고서 + 사업보고서)
- 사업보고서 후보: 1건
  - **rcept_no=`20240312000736`**
  - `report_nm="사업보고서 (2023.12)"`
  - `rcept_dt="20240312"`

→ `find_business_report_rcept_no`의 필터 패턴(`사업보고서` startswith + `(YYYY.12)` token) 그대로 작동.

⚠ Plan 본문 예시의 `20240314000123`은 추정치였음. 실 rcept_no는 `20240312000736`.

## 3. document.xml — ❌ 가정 큰 차이 (D1 정정 필요)

- URL: `https://opendart.fss.or.kr/api/document.xml?crtfc_key=<KEY>&rcept_no=20240312000736`
- 응답: HTTP 200, **596,351 bytes** zip
- zip 내부 파일: **3개의 XML** (HTML 0개)
  - `20240312000736.xml` — 6,150,873 bytes (본 사업보고서)
  - `20240312000736_00760.xml` — 560,092 bytes (감사보고서)
  - `20240312000736_00761.xml` — 660,068 bytes (별도 감사보고서)

⚠ **spec v1.1의 D1 가정 "zip 안에 HTML이 있고 파일명 휴리스틱으로 사업의 내용 선택"이 완전히 틀렸음.** zip은 HTML이 아니라 DART 전용 XML 포맷을 담는다.

### 본 XML 구조 (`<DOCUMENT>` root)

```
<DOCUMENT xsi:noNamespaceSchemaLocation="dart4.xsd">
  <DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>     ← 사업보고서 식별
  <FORMULA-VERSION ADATE="...">5.5</FORMULA-VERSION>
  <COMPANY-NAME AREGCIK="00126380">삼성전자주식회사</COMPANY-NAME>
  <SUMMARY>...</SUMMARY>
  <BODY ATOCID="285">
    <COVER>...표지...</COVER>
    <SECTION-1>                                              ← 각 chapter
      <TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ATOCID="3">I. 회사의 개요</TITLE>
      ...
    </SECTION-1>
    <SECTION-1 ACLASS="MANDATORY" APARTSOURCE="SOURCE">
      <TITLE ATOC="Y" AASSOCNOTE="D-0-2-0-0" ATOCID="9">II. 사업의 내용</TITLE>  ← 타겟
      ...본문...
    </SECTION-1>
    <SECTION-1>
      <TITLE ATOC="Y" AASSOCNOTE="D-0-3-0-0" ATOCID="17">III. 재무에 관한 사항</TITLE>
      ...
    </SECTION-1>
  </BODY>
</DOCUMENT>
```

태그 셋: `BODY`, `COVER`, `COVER-TITLE`, `SECTION-1`, `SECTION-2`, `SECTION-3`, `TITLE`, `LIBRARY`, `TABLE-GROUP`, `TABLE`, `THEAD`, `TBODY`, `TR`, `TD`, `TU`, `TE`, `TH`, `P`, `SPAN`, `PGBRK`, `IMG`, `IMAGE`, `IMG-CAPTION`, `COL`, `COLGROUP`, `A`.

### 사업의 내용 섹션 식별 기준

- **1차 (가장 안정적)**: `<TITLE AASSOCNOTE="D-0-2-0-0" ...>II. 사업의 내용</TITLE>`을 포함하는 `<SECTION-1>` 노드 전체
- **2차 fallback**: TITLE 텍스트에 `사업의 내용` 포함되고 `II` 또는 `Ⅱ`로 시작
- **3차 fallback**: 부모 SECTION-1을 찾을 수 없는 경우 → 다음 chapter TITLE 직전까지 raw 텍스트 슬라이스

### 본 사업보고서 XML 선택 기준 (zip 내 여러 XML 중)

- **1차**: `<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>` 매치
- **2차 fallback**: zip 내 최대 크기 .xml (보통 본 보고서)

## 4. D5 — `Corporation.dart_corp_code` 컬럼 존재 확인

- `src/themek/db/models.py` 확인 결과: `Corporation.dart_code` (varchar(8), primary key) 존재
- spec에서 부른 `dart_corp_code`와 이름만 다름, 의미는 동일
- 결정: **noop** (alembic migration 불필요)

## 5. D2 정정 — vcrpy/cassette 대신 raw fixture

- 본 환경에서 `vcrpy`/`respx`가 dev deps에 없고, httpx 호환 어댑터 추가 비용도 있음
- 채택: **응답 bytes를 fixture 파일로 직접 저장**
  - `tests/fixtures/dart_cassettes/corp_code_zip_success.bin` (3.4 MB zip)
  - `tests/fixtures/dart_cassettes/list_json_samsung_2023.json`
  - `tests/fixtures/dart_cassettes/document_zip_samsung_2023.bin` (582 KB zip)
- 테스트는 `monkeypatch httpx.Client.get` 또는 fixture를 직접 읽어 client 메서드를 모킹
- 효과: cassette playback과 동일 — 실 API 0회 호출, CI/타인 머신 호환

## 6. Plan 수정 사항

| Task | Plan 원안 | 실 응답 반영 |
|------|----------|--------------|
| T0 step 3 | "zip 내부 HTML 파일 5개 inspect" | zip 내부 **XML** 3개, HTML 0개 |
| T2 cassette | `corp_code_zip_success.yaml`(vcr) | `corp_code_zip_success.bin`(raw zip) |
| T6 extract | `extract_business_html_from_zip` 휴리스틱(HTML 파일명 매치 + 정렬) | XML 안 `<TITLE>II. 사업의 내용</TITLE>` 섹션 추출 |
| Cache 파일명 | `business.html` | 동일하게 유지 (내용은 `<html><body>...</body></html>` wrapping된 본문 텍스트) |

## 7. 후속 작업

- [x] T0 recon notes 작성 (이 문서)
- [ ] fetch.py 재설계 — XML 기반 추출
- [ ] 실 fixture 기반 통합 테스트
- [ ] T12 smoke run — 실 API end-to-end
