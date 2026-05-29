"""build_vault — VaultGraph + issues를 markdown 파일 트리로 멱등 기록."""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from themek.vault.model import build_graph
from themek.vault.qa import detect_issues
from themek.vault import render

_GENERATED_DIRS = ("companies", "segments", "customers", "regions", "sectors")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_vault(session: Session, out_dir: Path) -> dict:
    """현재 DB → out_dir vault. 생성 하위폴더만 비우고 재기록 (멱등, .obsidian 보존)."""
    out_dir = Path(out_dir)
    graph = build_graph(session)
    issues = detect_issues(graph)

    out_dir.mkdir(parents=True, exist_ok=True)
    for d in _GENERATED_DIRS:
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)

    by_company: dict[str, list] = {}
    for it in issues:
        if it.company:
            by_company.setdefault(it.company, []).append(it)

    for c in graph.companies:
        rel, text = render.render_company(c, by_company.get(c.name_ko, []))
        _write(out_dir / rel, text)
    for s in graph.segments:
        rel, text = render.render_segment(s)
        _write(out_dir / rel, text)
    for cust in graph.customers:
        rel, text = render.render_customer(cust)
        _write(out_dir / rel, text)
    for r in graph.regions:
        rel, text = render.render_region(r)
        _write(out_dir / rel, text)
    for sec in graph.sectors:
        rel, text = render.render_sector(sec)
        _write(out_dir / rel, text)

    _, idx = render.render_index(graph, issues)
    _write(out_dir / "_index.md", idx)
    _, qa = render.render_qa_report(graph, issues)
    _write(out_dir / "_qa-report.md", qa)

    return {
        "companies": len(graph.companies),
        "segments": len(graph.segments),
        "customers": len(graph.customers),
        "regions": len(graph.regions),
        "sectors": len(graph.sectors),
        "issues": len(issues),
    }
