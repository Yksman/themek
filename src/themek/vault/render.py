"""VaultGraph → markdown 렌더. 파일명 안전화 + frontmatter + wikilink + 노드 렌더."""
from __future__ import annotations

import hashlib
import re

from themek.vault.model import (
    VaultGraph, CompanyNode, SegmentNode, CustomerNode, RegionNode, SectorNode,
)
from themek.vault.qa import Issue

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_WS = re.compile(r"\s+")


def safe_filename(name: str) -> str:
    """Obsidian/파일시스템에서 안전한 basename으로 변환 (확장자 제외)."""
    s = _UNSAFE.sub(" ", name)
    return _WS.sub(" ", s).strip()


def customer_slug(raw: str, max_len: int = 40) -> str:
    """고객사 파일 basename. 길면 잘라내고 원문 해시 6자를 접미 → 충돌 방지·안정적."""
    base = safe_filename(raw)
    if len(base) <= max_len:
        return base
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
    return f"{base[:max_len].strip()} {h}"


def _clean_link_text(s: str) -> str:
    # wikilink 내부에서 위험한 [ ] | 는 모두 공백으로 치환 후 공백 단일화.
    return _WS.sub(" ", s.replace("[", " ").replace("]", " ").replace("|", " ")).strip()


def wikilink(target: str, display: str | None = None) -> str:
    """[[target]] 또는 [[target|display]]. 대괄호/파이프 제거."""
    t = _clean_link_text(target)
    if display is not None and display != target:
        return f"[[{t}|{_clean_link_text(display)}]]"
    return f"[[{t}]]"


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def frontmatter(d: dict) -> str:
    """dict → YAML frontmatter 블록 (--- 포함, 끝에 개행)."""
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            inner = ", ".join(_yaml_scalar(x) for x in v)
            lines.append(f"{k}: [{inner}]")
        else:
            lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _fmt_pct(v: float | None) -> str:
    return f"{v:g}%" if v is not None else "—"


def render_company(node: CompanyNode, issues: list[Issue]) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({
        "type": "company",
        "dart_code": node.dart_code,
        "name_ko": node.name_ko,
        "name_en": node.name_en or "",
        "ticker": node.ticker or "",
        "market": node.market or "",
        "sector": node.sector_name or "",
        "periods": node.periods,
        "report_count": len(node.reports),
        "segment_count": len(node.segments),
        "issue_count": len(issues),
        "tags": ["company"],
    })
    parts = [fm, f"# {node.name_ko}\n"]

    crumb = []
    if node.sector_name:
        crumb.append(wikilink(safe_filename(node.sector_name), node.sector_name))
    if node.market and node.ticker:
        crumb.append(f"{node.market} {node.ticker}")
    crumb.append(f"DART {node.dart_code}")
    parts.append("> " + " · ".join(crumb) + "\n")

    parts.append("\n## 세그먼트\n")
    for s in node.segments:
        link = wikilink(safe_filename(s.name_ko), s.name_ko)
        parts.append(f"- {link} — {_fmt_pct(s.share_pct)}")
    if not node.segments:
        parts.append("- (없음)")

    parts.append("\n## 고객사\n")
    for c in node.customers:
        link = wikilink(customer_slug(c.raw), c.raw)
        meta = []
        if c.tier and c.tier != "unknown":
            meta.append(c.tier)
        if c.revenue_share_pct is not None:
            meta.append(_fmt_pct(c.revenue_share_pct))
        flag = "" if c.resolved else " ⚠️ 미연결"
        suffix = f" ({', '.join(meta)})" if meta else ""
        parts.append(f"- {link}{suffix}{flag}")
    if not node.customers:
        parts.append("- (없음)")

    parts.append("\n## 지역 노출\n")
    for r in node.regions:
        parts.append(f"- {wikilink(safe_filename(r.name_ko), r.name_ko)} — {_fmt_pct(r.share_pct)}")
    if not node.regions:
        parts.append("- (없음)")

    if issues:
        parts.append("\n## ⚠️ 품질 이슈\n")
        for it in issues:
            parts.append(f"- **{it.kind}** ({it.severity}): {it.detail}")

    parts.append("\n## 출처\n")
    for r in node.reports:
        label = f"{r.report_type} {r.period}"
        if r.url:
            parts.append(f"- [{label}]({r.url}) · rcept_no {r.rcept_no}")
        else:
            parts.append(f"- {label} · rcept_no {r.rcept_no}")

    return f"companies/{fname}.md", "\n".join(parts) + "\n"


def render_segment(node: SegmentNode) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({"type": "segment", "name_ko": node.name_ko,
                      "company_count": len(node.companies), "tags": ["segment"]})
    parts = [fm, f"# {node.name_ko}\n", "\n## 이 세그먼트를 가진 회사\n"]
    for name in node.companies:
        parts.append(f"- {wikilink(safe_filename(name), name)}")
    return f"segments/{fname}.md", "\n".join(parts) + "\n"


def render_customer(node: CustomerNode) -> tuple[str, str]:
    fname = customer_slug(node.raw)
    fm = frontmatter({
        "type": "customer", "resolved": node.resolved, "kind": node.kind,
        "raw": node.raw, "named_by": node.named_by,
        "tags": ["unresolved", f"unresolved/{node.kind}"] if not node.resolved
                else ["customer"],
    })
    parts = [fm, f"# {node.raw}\n",
             f"\n> 미연결 고객사 ({node.kind})\n" if not node.resolved else "\n",
             "\n## 이 고객사를 지목한 회사\n"]
    for name in node.named_by:
        parts.append(f"- {wikilink(safe_filename(name), name)}")
    return f"customers/{fname}.md", "\n".join(parts) + "\n"


def render_region(node: RegionNode) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({"type": "region", "code": node.code, "name_ko": node.name_ko,
                      "tags": ["region"]})
    parts = [fm, f"# {node.name_ko}\n", "\n## 이 지역에 노출된 회사\n"]
    for name, share in node.companies:
        parts.append(f"- {wikilink(safe_filename(name), name)} — {_fmt_pct(share)}")
    return f"regions/{fname}.md", "\n".join(parts) + "\n"


def render_sector(node: SectorNode) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({"type": "sector", "fics_code": node.fics_code,
                      "name_ko": node.name_ko, "parent": node.parent_name or "",
                      "tags": ["sector"]})
    parts = [fm, f"# {node.name_ko}\n"]
    if node.parent_name:
        parts.append(f"> 상위: {wikilink(safe_filename(node.parent_name), node.parent_name)}\n")
    parts.append("\n## 소속 회사\n")
    for name in node.companies:
        parts.append(f"- {wikilink(safe_filename(name), name)}")
    return f"sectors/{fname}.md", "\n".join(parts) + "\n"


def render_index(graph: VaultGraph, issues: list[Issue]) -> tuple[str, str]:
    counts: dict[str, int] = {}
    for it in issues:
        if it.company:
            counts[it.company] = counts.get(it.company, 0) + 1
    fm = frontmatter({"type": "index", "tags": ["index"]})
    parts = [fm, "# themek 온톨로지 vault\n",
             f"\n- 회사: {len(graph.companies)}",
             f"- 세그먼트: {len(graph.segments)}",
             f"- 고객사(미연결 포함): {len(graph.customers)}",
             f"- 지역: {len(graph.regions)} · 섹터: {len(graph.sectors)}",
             f"- 검출 이슈: {len(issues)}",
             f"\n관련: [[_qa-report]]\n",
             "\n## 회사 목록\n",
             "| 회사 | 섹터 | 기간 | 세그먼트 | 이슈 |",
             "|------|------|------|----------|------|"]
    for c in sorted(graph.companies, key=lambda x: x.name_ko):
        parts.append(
            f"| {wikilink(safe_filename(c.name_ko), c.name_ko)} "
            f"| {c.sector_name or '—'} | {', '.join(c.periods)} "
            f"| {len(c.segments)} | {counts.get(c.name_ko, 0)} |"
        )
    return "_index.md", "\n".join(parts) + "\n"


def render_qa_report(graph: VaultGraph, issues: list[Issue]) -> tuple[str, str]:
    by_kind: dict[str, list[Issue]] = {}
    for it in issues:
        by_kind.setdefault(it.kind, []).append(it)
    fm = frontmatter({"type": "qa-report", "issue_total": len(issues), "tags": ["qa"]})
    parts = [fm, "# QA 리포트\n", f"\n총 이슈: {len(issues)}\n", "\n## 종류별 집계\n",
             "| 종류 | 건수 |", "|------|------|"]
    for kind in sorted(by_kind):
        parts.append(f"| {kind} | {len(by_kind[kind])} |")
    for kind in sorted(by_kind):
        parts.append(f"\n## {kind}\n")
        for it in by_kind[kind]:
            who = wikilink(safe_filename(it.company), it.company) if it.company else "(전역)"
            parts.append(f"- {who} — {it.detail}")
    return "_qa-report.md", "\n".join(parts) + "\n"
