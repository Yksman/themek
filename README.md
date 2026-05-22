# themek

한국 테마주 시장에 최적화된 ontology 기반 정보 서비스 프로젝트.

## Status

설계 단계 (Draft v1, 2026-05-22).

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

## Next

구현 plan은 별도 문서로 분리 예정 (저장 시스템 · 추출 파이프라인 · 합성 layer · 콜드스타트 · 평가 rubric · 운영 비용 · 법무 · UI).
