"""DART 사업보고서 HTML → 본문 텍스트 추출.

- extract_business_content: 전체 본문 (legacy, 하위 호환)
- extract_business_sections: II. 사업의 내용 sub-section만 선별 추출 +
  3-tier escalation (regex → LLM → full_text)
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from bs4 import BeautifulSoup

from themek.dart.learned_patterns import (
    LearnedPatterns, load_learned_patterns,
)


MIN_SECTION_CHARS = 300
DEFAULT_LEARNED_PATTERNS_PATH = "data/dart/learned_header_patterns.json"


def extract_business_content(html: str) -> str:
    """HTML 본문에서 사람이 읽을 수 있는 텍스트를 추출."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style"]):
        tag.decompose()

    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("\t".join(cells))
        table.replace_with("\n".join(rows) + "\n")

    text = soup.get_text(separator="\n", strip=True)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Section-level filter
# ──────────────────────────────────────────────────────────────────────────

_HEADER_LINE_RE = re.compile(
    r"^\s*(?:\d{1,2}|[가-힣])\.\s+(\S.{0,48})\s*$"
)
_NUMERIC_HEADER_PREFIX_RE = re.compile(r"^\s*\d{1,2}\.\s+")


@dataclass
class SectionResolution:
    regex_matched: dict[str, str] = field(default_factory=dict)
    llm_called: bool = False
    llm_input_candidates: list[str] = field(default_factory=list)
    llm_decision: dict[str, Optional[int]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    output_chars: int = 0
    # Phase 1: escalation
    escalation_level: str = "regex"
    body_chars_per_target: dict[str, int] = field(default_factory=dict)
    invalid_targets: list[str] = field(default_factory=list)
    # Phase 2: learning
    learned_samples: list[dict] = field(default_factory=list)


def _current_learned_patterns() -> LearnedPatterns:
    path = os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    )
    return load_learned_patterns(path)


def _build_target_regex_map(lp: LearnedPatterns) -> dict[str, list[re.Pattern]]:
    return {
        t: [re.compile(p["regex"]) for p in lp.target_patterns(t)]
        for t in ("overview", "products", "revenue")
    }


def _content_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return [line for line in text.splitlines() if line.strip()]


def _find_header_indices(lines: list[str]) -> list[tuple[int, str]]:
    matches: list[tuple[int, str, bool]] = []
    for i, line in enumerate(lines):
        m = _HEADER_LINE_RE.match(line)
        if m:
            is_numeric = bool(_NUMERIC_HEADER_PREFIX_RE.match(line))
            matches.append((i, m.group(1), is_numeric))
    numeric_count = sum(1 for _, _, is_num in matches if is_num)
    if numeric_count >= 2:
        return [(i, t) for (i, t, is_num) in matches if is_num]
    return [(i, t) for (i, t, _) in matches]


def _classify_header_by_regex(
    header: str, target_keywords: dict[str, list[re.Pattern]],
) -> Optional[str]:
    for target, patterns in target_keywords.items():
        if any(p.search(header) for p in patterns):
            return target
    return None


def _section_body(
    lines: list[str], headers: list[tuple[int, str]], idx: int,
) -> str:
    start = headers[idx][0] + 1
    end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
    return "\n".join(lines[start:end])


def _measure_and_validate(
    matched_target_to_idx: dict[str, int],
    headers: list[tuple[int, str]],
    lines: list[str],
) -> tuple[dict[str, int], list[str]]:
    body_chars: dict[str, int] = {}
    invalid: list[str] = []
    for target, idx in matched_target_to_idx.items():
        body = _section_body(lines, headers, idx)
        body_chars[target] = len(body)
        if len(body) < MIN_SECTION_CHARS:
            invalid.append(target)
    return body_chars, sorted(invalid)


def extract_business_sections(
    html: str,
    *,
    want: set[str] = frozenset({"overview", "products", "revenue"}),
    llm_fallback: Optional[Callable[[list[str], list[str]], dict]] = None,
) -> tuple[str, SectionResolution]:
    """3-tier escalation:
      A) regex 매칭
      B) invalid/missing target은 LLM에 분류 요청
      C) 그래도 invalid이거나 헤더 없으면 full_text fallback
    """
    lp = _current_learned_patterns()
    target_keywords = _build_target_regex_map(lp)

    lines = _content_lines(html)
    headers = _find_header_indices(lines)
    resolution = SectionResolution()

    # ── A) regex 매칭
    matched_target_to_idx: dict[str, int] = {}
    for idx, (_, header) in enumerate(headers):
        target = _classify_header_by_regex(header, target_keywords)
        if target and target in want and target not in matched_target_to_idx:
            matched_target_to_idx[target] = idx
            resolution.regex_matched[target] = header

    # invalid (body too short) target 사전 측정
    invalid_pre = [
        t for t, idx in matched_target_to_idx.items()
        if len(_section_body(lines, headers, idx)) < MIN_SECTION_CHARS
    ]
    missing = sorted(want - set(matched_target_to_idx))
    targets_needing_llm = sorted(set(missing) | set(invalid_pre))

    # ── B) LLM fallback
    if targets_needing_llm and llm_fallback is not None and headers:
        used_idx = {
            i for t, i in matched_target_to_idx.items()
            if t not in invalid_pre
        }
        candidates_idx = [
            i for i, _ in enumerate(headers) if i not in used_idx
        ]
        candidates = [headers[i][1] for i in candidates_idx]
        resolution.llm_called = True
        resolution.escalation_level = "regex+llm"
        resolution.llm_input_candidates = candidates
        decision = llm_fallback(candidates, targets_needing_llm)
        resolution.llm_decision = dict(decision)
        for target, one_based in decision.items():
            if one_based is None:
                continue
            if not isinstance(one_based, int):
                continue
            if one_based < 1 or one_based > len(candidates_idx):
                continue
            real_idx = candidates_idx[one_based - 1]
            matched_target_to_idx[target] = real_idx
            resolution.learned_samples.append({
                "target": target,
                "header_text": headers[real_idx][1],
            })

    # body 길이 재측정 + invalid 갱신
    body_chars, invalid = _measure_and_validate(
        matched_target_to_idx, headers, lines,
    )
    resolution.body_chars_per_target = body_chars
    resolution.invalid_targets = invalid
    resolution.skipped = sorted(set(want) - set(matched_target_to_idx))

    # 본문 concat (B 종료 시점 정상 매칭만)
    order = ["overview", "products", "revenue"]
    parts: list[str] = []
    for target in order:
        if target in matched_target_to_idx and target not in invalid:
            idx = matched_target_to_idx[target]
            parts.append(f"## {headers[idx][1]}")
            parts.append(_section_body(lines, headers, idx))

    text = "\n".join(parts).strip()
    resolution.output_chars = len(text)

    # ── C) full text fallback
    if (
        resolution.invalid_targets
        or not headers
        or not matched_target_to_idx
    ):
        full_text = extract_business_content(html)
        resolution.escalation_level = "full_text"
        resolution.output_chars = len(full_text)
        return full_text, resolution

    return text, resolution


# ──────────────────────────────────────────────────────────────────────────
# LLM fallback: 미매칭 헤더 후보를 LLM이 분류
# ──────────────────────────────────────────────────────────────────────────
from themek.llm.claude_cli import call_claude, extract_json_block, ClaudeCallError
from themek.llm.prompts import build_header_classification_prompt


def llm_classify_headers(
    candidates: list[str], missing_targets: list[str],
) -> dict[str, Optional[int]]:
    """남은 헤더 후보를 LLM이 카테고리로 매핑. 1-based index 또는 null 반환."""
    prompt = build_header_classification_prompt(candidates, missing_targets)
    result = call_claude(prompt, escalation="llm")
    payload = extract_json_block(result.text)
    if not isinstance(payload, dict):
        raise ClaudeCallError(
            f"header classification expected dict, got: {payload!r}"
        )
    out: dict[str, Optional[int]] = {}
    for target in ("overview", "products", "revenue"):
        v = payload.get(target)
        out[target] = v if isinstance(v, int) else None
    return out
