"""LLM 추출 prompt 빌더."""
from __future__ import annotations


BUSINESS_EXTRACTION_PROMPT_TEMPLATE = """\
다음은 한국 상장사의 사업보고서 본문 일부입니다 (period: {period}).
이 내용에서 사업 구조를 추출해 JSON으로만 응답하세요. 설명이나 markdown 없이 valid JSON 객체 1개만.

[추출 대상 구조]
{{
  "period": "{period}",
  "segments": [
    {{"name_ko": "사업부문명", "share_pct": 0~100 또는 null, "description": "한 줄 설명 또는 null", "products": ["주요 제품/서비스명", ...]}}
  ],
  "customers": [
    {{"name_raw": "보고서에 적힌 그대로의 고객사 이름 또는 설명", "revenue_share_pct": 0~100 또는 null, "tier": "1차" | "2차" | "unknown"}}
  ],
  "geographic": [
    {{"region_code": "KR" | "US" | "EU" | "CN" | "JP" | "ROW", "share_pct": 0~100}}
  ]
}}

[지침]
- 보고서에 명시되지 않은 수치는 null로 두세요. 추측 금지.
- region_code는 위 6종만 사용. "아시아"는 CN/JP 외엔 ROW. "유럽 전체"는 EU.
- 동일한 region_code로 매핑되는 항목이 여러 개면 share_pct를 합산해 한 줄로만 보고하세요. (예: "아시아 13%" + "기타 6%"가 둘 다 ROW면 → ROW 19%로 한 번만)
- 고객사가 비공개("주요 고객 A" 등)면 name_raw에 그대로 적고 tier="unknown".
- segments의 share_pct 총합이 ~100이 되지 않아도 됩니다 (보고서 기준 그대로).
- products는 보고서에서 직접 언급된 제품/서비스명만 (브랜드명 OK).

[보고서 본문]
{text}

[출력 — JSON only]
"""


def build_business_extraction_prompt(text: str, period_hint: str) -> str:
    return BUSINESS_EXTRACTION_PROMPT_TEMPLATE.format(text=text, period=period_hint)
