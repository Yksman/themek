"""코어(nodes/edges/financial_facts) → Obsidian vault markdown 투영.

산출:
- companies/*.md : frontmatter + 섹터/세그먼트/고객/지역 wikilink + 재무 시계열 표
  (+ 파생비율 + Dataview 인라인 필드). 세그먼트/고객/지역은 기간 중복 제거(최신 기간).
- segments/·customers/·regions/·sectors/*.md : 개념 노드 노트 + 백링크(이 노드를 가리키는 회사).
- _index.md : 회사 목록 표.

링크 텍스트와 노트 파일명은 `_note_name`으로 항상 일치(장문은 해시 truncate + alias)시켜
깨진 wikilink가 없도록 한다. build마다 생성 폴더·index를 비우고 재기록(멱등, .obsidian 보존).
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge, FinancialFact

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_WS = re.compile(r"\s+")
_NAME_MAX = 60
_FISCAL_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
_KPI_ORDER = ["revenue", "operating_income", "net_income",
              "assets", "liabilities", "equity"]
_KPI_LABEL = {"revenue": "매출액", "operating_income": "영업이익",
              "net_income": "당기순이익", "assets": "자산총계",
              "liabilities": "부채총계", "equity": "자본총계"}
_GENERATED_DIRS = ("companies", "segments", "customers", "regions", "sectors")
_KIND_DIR = {"segment": "segments", "customer": "customers",
             "region": "regions", "sector": "sectors"}


def _safe(name: str) -> str:
    return _WS.sub(" ", _UNSAFE.sub(" ", name)).strip()


def _note_name(label: str) -> str:
    """노트 basename. 안전화 + 길이 상한(초과 시 원문 해시 6자 접미 → 안정·충돌 방지)."""
    s = _safe(label)
    if len(s) <= _NAME_MAX:
        return s
    h = hashlib.sha1(label.encode("utf-8")).hexdigest()[:6]
    return f"{s[:_NAME_MAX].strip()} {h}"


def _wikilink(label: str) -> str:
    """[[name]] 또는 [[name|safe_label]] — 노트 파일명과 항상 매칭."""
    name = _note_name(label)
    safe_label = _safe(label)
    if name == safe_label:
        return f"[[{name}]]"
    return f"[[{name}|{safe_label}]]"


def _period_sort_key(year: str, fp: str) -> tuple[int, int]:
    return (int(year), _FISCAL_ORDER.get(fp, 0))


def _eok(amount: float) -> str:
    return f"{amount / 1e8:,.0f}억"


def _company_financials(session: Session, company_id: str) -> dict:
    """{(year,fp): {metric: amount}} (CFS 우선)."""
    rows = session.execute(
        select(FinancialFact).where(FinancialFact.company_id == company_id)
    ).scalars().all()
    out: dict[tuple[str, str], dict[str, float]] = {}
    fs_seen: dict[tuple, str] = {}
    for r in rows:
        key = (r.bsns_year, r.fiscal_period)
        cur = out.setdefault(key, {})
        mk = r.metric_key
        if mk not in cur or (r.fs_div == "CFS" and fs_seen.get((key, mk)) != "CFS"):
            cur[mk] = float(r.amount)
            fs_seen[(key, mk)] = r.fs_div
    return out


def _render_financials(fin: dict) -> list[str]:
    if not fin:
        return []
    periods = sorted(fin.keys(), key=lambda k: _period_sort_key(*k))
    header = "| 지표 | " + " | ".join(f"{y} {fp}" for y, fp in periods) + " |"
    sep = "|------|" + "------|" * len(periods)
    lines = ["\n## 재무 (연결 우선, 단위 억원)\n", header, sep]
    for key in _KPI_ORDER:
        if not any(key in fin[p] for p in periods):
            continue
        cells = [(_eok(fin[p][key]) if key in fin[p] else "—") for p in periods]
        lines.append(f"| {_KPI_LABEL[key]} | " + " | ".join(cells) + " |")
    ratio_rows = []
    for p in periods:
        d = fin[p]
        opm = (d["operating_income"] / d["revenue"] * 100
               if "operating_income" in d and d.get("revenue") else None)
        der = (d["liabilities"] / d["equity"] * 100
               if "liabilities" in d and d.get("equity") else None)
        roe = (d["net_income"] / d["equity"] * 100
               if "net_income" in d and d.get("equity") else None)
        ratio_rows.append((opm, der, roe))

    def _fmt(v):
        return f"{v:.1f}%" if v is not None else "—"

    lines.append("| 영업이익률 | " + " | ".join(_fmt(r[0]) for r in ratio_rows) + " |")
    lines.append("| 부채비율 | " + " | ".join(_fmt(r[1]) for r in ratio_rows) + " |")
    lines.append("| ROE | " + " | ".join(_fmt(r[2]) for r in ratio_rows) + " |")
    lines.append("")
    for (y, fp) in periods:
        for key in _KPI_ORDER:
            if key in fin[(y, fp)]:
                lines.append(f"{key}_{y}{fp}:: {fin[(y, fp)][key]:.0f}")
    return lines


def _dedup_latest(edges: list[Edge]) -> list[tuple[str, float | None]]:
    """object_id별 최신 period 엣지만 남겨 (object_id, share_pct) 리스트 반환."""
    best: dict[str, tuple] = {}
    for e in edges:
        pk = (e.period or "")
        share = e.qualifier.get("share_pct")
        cur = best.get(e.object_id)
        if cur is None or pk > cur[0]:
            best[e.object_id] = (pk, share)
    return [(oid, v[1]) for oid, v in best.items()]


def build_vault(session: Session, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 생성 폴더 전체 초기화(잔재 제거) + 인덱스/리포트 stale 제거
    for d in _GENERATED_DIRS:
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)
    for stale in ("_index.md", "_qa-report.md"):
        sp = out_dir / stale
        if sp.exists():
            sp.unlink()

    node_label = dict(session.execute(select(Node.id, Node.label)).all())
    companies = session.execute(
        select(Node).where(Node.kind == "company").order_by(Node.label)
    ).scalars().all()

    # 개념 노드 → 백링크 수집: {concept_node_id: [(company_label, predicate, share)]}
    backlinks: dict[str, list[tuple[str, str, float | None]]] = {}

    def _lbl(node_id: str) -> str:
        return node_label.get(node_id, node_id)

    for c in companies:
        edges = session.execute(
            select(Edge).where(Edge.subject_id == c.id)
        ).scalars().all()
        seg = _dedup_latest([e for e in edges if e.predicate == "HAS_SEGMENT"])
        cust = _dedup_latest([e for e in edges if e.predicate == "SELLS_TO"])
        reg = _dedup_latest([e for e in edges if e.predicate == "EXPOSED_TO"])
        sector = next((e for e in edges if e.predicate == "IN_SECTOR"), None)

        parts = [
            "---", 'type: "company"',
            f'dart_code: "{c.attrs.get("dart_code", "")}"',
            f'name: "{c.label}"', "tags: [company]", "---",
            f"# {c.label}\n",
        ]
        if sector:
            parts.append(f"> 섹터: {_wikilink(_lbl(sector.object_id))}\n")
            backlinks.setdefault(sector.object_id, []).append((c.label, "소속", None))
        parts.append("\n## 세그먼트\n")
        for oid, share in seg:
            suffix = f" — {share:g}%" if share is not None else ""
            parts.append(f"- {_wikilink(_lbl(oid))}{suffix}")
            backlinks.setdefault(oid, []).append((c.label, "세그먼트", share))
        if not seg:
            parts.append("- (없음)")
        parts.append("\n## 고객사\n")
        for oid, _ in cust:
            parts.append(f"- {_wikilink(_lbl(oid))}")
            backlinks.setdefault(oid, []).append((c.label, "고객", None))
        if not cust:
            parts.append("- (없음)")
        parts.append("\n## 지역 노출\n")
        for oid, share in reg:
            suffix = f" — {share:g}%" if share is not None else ""
            parts.append(f"- {_wikilink(_lbl(oid))}{suffix}")
            backlinks.setdefault(oid, []).append((c.label, "지역", share))
        if not reg:
            parts.append("- (없음)")

        parts += _render_financials(_company_financials(session, c.id))
        (out_dir / "companies" / f"{_note_name(c.label)}.md").write_text(
            "\n".join(parts) + "\n", encoding="utf-8")

    # 개념 노드 노트 (segment/customer/region/sector) — 백링크 포함
    concept_nodes = session.execute(
        select(Node).where(Node.kind.in_(list(_KIND_DIR.keys())))
    ).scalars().all()
    for n in concept_nodes:
        sub = _KIND_DIR[n.kind]
        refs = backlinks.get(n.id, [])
        parts = ["---", f'type: "{n.kind}"', f'name: "{n.label}"',
                 f"tags: [{n.kind}]", "---", f"# {n.label}\n",
                 f"\n## 이 {n.kind}를 가리키는 회사 ({len(refs)})\n"]
        for comp_label, rel, share in sorted(set(refs)):
            suffix = f" — {share:g}%" if share is not None else ""
            parts.append(f"- {_wikilink(comp_label)} ({rel}){suffix}")
        if not refs:
            parts.append("- (참조 없음)")
        (out_dir / sub / f"{_note_name(n.label)}.md").write_text(
            "\n".join(parts) + "\n", encoding="utf-8")

    # _index.md — 회사 목록
    idx = ["---", 'type: "index"', "tags: [index]", "---",
           "# themek 온톨로지 vault\n",
           f"\n- 회사: {len(companies)}",
           f"- 개념 노드(segment/customer/region/sector): {len(concept_nodes)}\n",
           "\n## 회사 목록\n", "| 회사 | 섹터 | 재무기간 |", "|------|------|------|"]
    for c in companies:
        sector_edge = session.execute(
            select(Edge).where(Edge.subject_id == c.id,
                               Edge.predicate == "IN_SECTOR")
        ).scalars().first()
        sector_label = _lbl(sector_edge.object_id) if sector_edge else "—"
        fin = _company_financials(session, c.id)
        fyrs = ",".join(sorted({y for (y, _fp) in fin.keys()})) or "—"
        parts_link = _wikilink(c.label)
        idx.append(f"| {parts_link} | {sector_label} | {fyrs} |")
    (out_dir / "_index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

    return {"companies": len(companies), "concepts": len(concept_nodes)}
