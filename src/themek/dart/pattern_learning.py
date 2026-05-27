"""학습 sample로부터 regex 일반화 + 검증 + 누적 + 적용."""
from __future__ import annotations
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from themek.dart.learned_patterns import (
    LearnedPatterns, load_learned_patterns, save_learned_patterns,
)

MIN_KEYWORD_LENGTH = 3
COMMON_FILLERS = {
    "등", "및", "의", "이", "가", "을", "를", "에", "도", "는", "은",
    "와", "과",
}


def _strip_prefix_noise(text: str) -> str:
    """`(제조서비스업)` `[금융업]` `①` `Ⅰ.` 같은 prefix 제거."""
    text = re.sub(r"^\s*[\(\[\{].{1,30}?[\)\]\}]\s*", "", text)
    text = re.sub(r"^[①-⑳ⅠⅡⅢⅣⅤ㈠-㉃]+\s*", "", text)
    return text.strip()


def _is_meaningful(token: str) -> bool:
    if len(token) < 2:
        return False
    if token in COMMON_FILLERS:
        return False
    return True


def propose_keyword_pattern(header_text: str, *, target: str) -> Optional[str]:
    """헤더 텍스트에서 일반화된 keyword regex를 만든다."""
    core = _strip_prefix_noise(header_text)
    tokens = [t for t in re.split(r"[\s ·\-/,\.]+", core) if t]
    meaningful = [t for t in tokens if _is_meaningful(t)]
    if not meaningful:
        return None
    joined = "".join(meaningful)
    if len(joined) < MIN_KEYWORD_LENGTH:
        return None
    pattern = ".{0,3}".join(re.escape(t) for t in meaningful)
    return pattern


def validate_pattern_against_fixtures(
    *, target: str, regex: str, fixtures_dir: Path,
) -> tuple[bool, list[str]]:
    """fixture 하나라도 expected_headers와 충돌하는 매칭을 만들면 reject.

    Returns: (ok, breaking_fixture_names)
    """
    from themek.dart.parser import extract_business_sections

    breaking: list[str] = []
    html_files = sorted(Path(fixtures_dir).glob("*.html"))
    if not html_files:
        return True, []

    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern(target, regex=regex, source="learned",
                          samples=[], confirmed_count=0)

    fd, tmp_name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    tmp_path = Path(tmp_name)
    save_learned_patterns(tmp_path, lp)

    old_env = os.environ.get("THEMEK_LEARNED_PATTERNS_PATH")
    os.environ["THEMEK_LEARNED_PATTERNS_PATH"] = str(tmp_path)

    try:
        for html_path in html_files:
            expected_path = html_path.with_name(
                html_path.stem + "_headers.json"
            )
            if not expected_path.exists():
                continue
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")
            _, res = extract_business_sections(html, llm_fallback=None)
            for t, exp_header in expected.items():
                if not exp_header:
                    continue
                got = res.regex_matched.get(t)
                if got is None:
                    # 학습 패턴 추가 후 expected target을 못 잡으면 깨진 것
                    breaking.append(html_path.stem)
                    break
                if exp_header not in got and got not in exp_header:
                    breaking.append(html_path.stem)
                    break
    finally:
        if old_env is None:
            os.environ.pop("THEMEK_LEARNED_PATTERNS_PATH", None)
        else:
            os.environ["THEMEK_LEARNED_PATTERNS_PATH"] = old_env
        tmp_path.unlink(missing_ok=True)

    return (len(breaking) == 0), breaking


@dataclass
class Proposal:
    target: str
    candidate_regex: str
    sample_headers: list[str] = field(default_factory=list)
    observed_count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    source_fixtures: list[str] = field(default_factory=list)


def load_proposals(path: Path | str) -> list[Proposal]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [Proposal(**entry) for entry in data.get("proposals", [])]


def save_proposals(path: Path | str, proposals: list[Proposal]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proposals": [asdict(pr) for pr in proposals]}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def record_proposal(
    path: Path | str, *, target: str, candidate_regex: str,
    sample_header: str, source_fixture: str,
) -> Proposal:
    proposals = load_proposals(path)
    now = datetime.now(timezone.utc).isoformat()
    for pr in proposals:
        if pr.target == target and pr.candidate_regex == candidate_regex:
            pr.observed_count += 1
            pr.last_seen_at = now
            if sample_header not in pr.sample_headers:
                pr.sample_headers.append(sample_header)
            if source_fixture not in pr.source_fixtures:
                pr.source_fixtures.append(source_fixture)
            save_proposals(path, proposals)
            return pr
    pr = Proposal(
        target=target, candidate_regex=candidate_regex,
        sample_headers=[sample_header], observed_count=1,
        first_seen_at=now, last_seen_at=now,
        source_fixtures=[source_fixture],
    )
    proposals.append(pr)
    save_proposals(path, proposals)
    return pr


def apply_ready_proposals(
    *, proposals_path: Path, learned_path: Path, fixtures_dir: Path,
    min_confirmed: int = 3,
) -> list[Proposal]:
    """N=min_confirmed 이상이고 fixture 회귀 통과한 proposal을 promote."""
    proposals = load_proposals(proposals_path)
    lp = load_learned_patterns(learned_path)
    applied: list[Proposal] = []
    remaining: list[Proposal] = []
    for pr in proposals:
        if pr.observed_count < min_confirmed:
            remaining.append(pr)
            continue
        ok, breaking = validate_pattern_against_fixtures(
            target=pr.target, regex=pr.candidate_regex,
            fixtures_dir=fixtures_dir,
        )
        if not ok:
            pr.sample_headers.append(f"__rejected_by:{','.join(breaking)}")
            remaining.append(pr)
            continue
        lp.add_target_pattern(
            pr.target, regex=pr.candidate_regex, source="learned",
            samples=[s for s in pr.sample_headers
                     if not s.startswith("__rejected_by:")],
            confirmed_count=pr.observed_count,
            fixtures_validated=pr.source_fixtures,
        )
        applied.append(pr)
    save_learned_patterns(learned_path, lp)
    save_proposals(proposals_path, remaining)
    return applied
