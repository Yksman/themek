"""learned_header_patterns.json loader + runtime API.

baseline 패턴은 코드 상수, 학습된 패턴은 파일에서 로드. 둘을 merge해 제공.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_TARGETS = ("overview", "products", "revenue")

DEFAULT_BASELINE_PATTERNS: dict[str, list[dict[str, Any]]] = {
    "overview": [
        {"type": "keyword", "regex": r"사업.{0,3}개요", "source": "code_baseline"},
    ],
    "products": [
        {"type": "keyword", "regex": r"주요.{0,3}제품", "source": "code_baseline"},
        {"type": "keyword", "regex": r"제품.{0,3}서비스", "source": "code_baseline"},
    ],
    "revenue": [
        {"type": "keyword", "regex": r"매출", "source": "code_baseline"},
        {"type": "keyword", "regex": r"수주.{0,3}현황", "source": "code_baseline"},
    ],
}

DEFAULT_BASELINE_PREFIXES: list[dict[str, Any]] = [
    {"type": "prefix", "regex": r"^\s*\d{1,2}\.\s+", "source": "code_baseline"},
    {"type": "prefix", "regex": r"^\s*[가-힣]\.\s+", "source": "code_baseline"},
]


@dataclass
class LearnedPatterns:
    targets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    prefixes: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def from_baseline(cls) -> "LearnedPatterns":
        return cls(
            targets={t: [dict(p) for p in ps]
                     for t, ps in DEFAULT_BASELINE_PATTERNS.items()},
            prefixes=[dict(p) for p in DEFAULT_BASELINE_PREFIXES],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def target_patterns(self, target: str) -> list[dict[str, Any]]:
        if target not in VALID_TARGETS:
            raise ValueError(f"invalid target: {target}")
        return list(self.targets.get(target, []))

    def prefix_patterns(self) -> list[dict[str, Any]]:
        return list(self.prefixes)

    def add_target_pattern(
        self, target: str, *, regex: str, source: str,
        samples: list[str], confirmed_count: int,
        fixtures_validated: list[str] | None = None,
    ) -> None:
        if target not in VALID_TARGETS:
            raise ValueError(f"invalid target: {target}")
        try:
            re.compile(regex)
        except re.error as e:
            raise ValueError(f"invalid regex: {regex} — {e}")
        entry = {
            "type": "keyword",
            "regex": regex,
            "source": source,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "samples": list(samples),
            "confirmed_count": confirmed_count,
            "fixtures_validated": list(fixtures_validated or []),
        }
        self.targets.setdefault(target, []).append(entry)

    def add_prefix_pattern(
        self, *, regex: str, source: str,
        samples: list[str], confirmed_count: int,
        fixtures_validated: list[str] | None = None,
    ) -> None:
        try:
            re.compile(regex)
        except re.error as e:
            raise ValueError(f"invalid regex: {regex} — {e}")
        self.prefixes.append({
            "type": "prefix",
            "regex": regex,
            "source": source,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "samples": list(samples),
            "confirmed_count": confirmed_count,
            "fixtures_validated": list(fixtures_validated or []),
        })


def load_learned_patterns(path: Path | str) -> LearnedPatterns:
    p = Path(path)
    if not p.exists():
        return LearnedPatterns.from_baseline()
    data = json.loads(p.read_text(encoding="utf-8"))
    lp = LearnedPatterns.from_baseline()
    for target, entries in data.get("patterns", {}).items():
        for entry in entries:
            if entry.get("source") == "learned":
                lp.targets.setdefault(target, []).append(entry)
    for entry in data.get("prefixes", []):
        if entry.get("source") == "learned":
            lp.prefixes.append(entry)
    return lp


def save_learned_patterns(path: Path | str, lp: LearnedPatterns) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "patterns": lp.targets,
        "prefixes": lp.prefixes,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def consolidate(lp: LearnedPatterns) -> LearnedPatterns:
    """동일 regex 머지, samples union, confirmed_count 합산."""
    for target, entries in lp.targets.items():
        by_regex: dict[str, dict[str, Any]] = {}
        for e in entries:
            r = e["regex"]
            if r not in by_regex:
                by_regex[r] = dict(e)
                by_regex[r]["samples"] = list(e.get("samples", []))
                by_regex[r]["fixtures_validated"] = list(
                    e.get("fixtures_validated", [])
                )
            else:
                merged = by_regex[r]
                merged["samples"] = sorted(set(
                    merged.get("samples", []) + e.get("samples", [])
                ))
                merged["fixtures_validated"] = sorted(set(
                    merged.get("fixtures_validated", []) +
                    e.get("fixtures_validated", [])
                ))
                merged["confirmed_count"] = (
                    merged.get("confirmed_count", 0)
                    + e.get("confirmed_count", 0)
                )
        lp.targets[target] = list(by_regex.values())
    return lp
