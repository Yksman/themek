"""코어(nodes/edges/financial_facts) → Obsidian vault markdown 투영.

회사 노트 = frontmatter + 섹터/세그먼트/고객/지역 wikilink + 재무 시계열 표
(+ 파생비율 + Dataview 인라인 필드). 생성 폴더만 비우고 재기록(멱등).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge, FinancialFact

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_WS = re.compile(r"\s+")
_FISCAL_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
_KPI_ORDER = ["revenue", "operating_income", "net_income",
              "assets", "liabilities", "equity"]
_KPI_LABEL = {"revenue": "매출액", "operating_income": "영업이익",
              "net_income": "당기순이익", "assets": "자산총계",
              "liabilities": "부채총계", "equity": "자본총계"}


def _safe(name: str) -> str:
    return _WS.sub(" ", _UNSAFE.sub(" ", name)).strip()


def _wikilink(label: str) -> str:
    return f"[[{_safe(label)}]]"


def _period_sort_key(year: str, fp: str) -> tuple[int, int]:
    return (int(year), _FISCAL_ORDER.get(fp, 0))


def _eok(amount: float) -> str:
    """원 → 억원 표기."""
    return f"{amount / 1e8:,.0f}억"


def _company_financials(session: Session, company_id: str) -> dict:
    """{(year,fp): {metric: amount}} (CFS 우선)."""
    rows = session.execute(
        select(FinancialFact).where(FinancialFact.company_id == company_id)
    ).scalars().all()
    out: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        # CFS 우선: 같은 (period, metric)에 OFS는 CFS 없을 때만
        key = (r.bsns_year, r.fiscal_period)
        cur = out.setdefault(key, {})
        if r.metric_key not in cur or r.fs_div == "CFS":
            cur[r.metric_key] = float(r.amount)
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
    # 파생비율
    ratio_rows = []
    for p in periods:
        d = fin[p]
        if "operating_income" in d and d.get("revenue"):
            opm = d["operating_income"] / d["revenue"] * 100
        else:
            opm = None
        if "liabilities" in d and d.get("equity"):
            der = d["liabilities"] / d["equity"] * 100
        else:
            der = None
        if "net_income" in d and d.get("equity"):
            roe = d["net_income"] / d["equity"] * 100
        else:
            roe = None
        ratio_rows.append((opm, der, roe))
    def _fmt(v):
        return f"{v:.1f}%" if v is not None else "—"
    lines.append("| 영업이익률 | " + " | ".join(_fmt(r[0]) for r in ratio_rows) + " |")
    lines.append("| 부채비율 | " + " | ".join(_fmt(r[1]) for r in ratio_rows) + " |")
    lines.append("| ROE | " + " | ".join(_fmt(r[2]) for r in ratio_rows) + " |")
    # Dataview 인라인 필드
    lines.append("")
    for (y, fp) in periods:
        for key in _KPI_ORDER:
            if key in fin[(y, fp)]:
                lines.append(f"{key}_{y}{fp}:: {fin[(y, fp)][key]:.0f}")
    return lines


def _company_label(node: Node) -> str:
    return node.label


def build_vault(session: Session, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    companies = session.execute(
        select(Node).where(Node.kind == "company").order_by(Node.label)
    ).scalars().all()

    out_dir.mkdir(parents=True, exist_ok=True)
    cdir = out_dir / "companies"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir(parents=True)

    for c in companies:
        edges = session.execute(
            select(Edge).where(Edge.subject_id == c.id)
        ).scalars().all()
        seg = [e for e in edges if e.predicate == "HAS_SEGMENT"]
        cust = [e for e in edges if e.predicate == "SELLS_TO"]
        reg = [e for e in edges if e.predicate == "EXPOSED_TO"]
        sector = next((e for e in edges if e.predicate == "IN_SECTOR"), None)

        def _label(node_id):
            n = session.get(Node, node_id)
            return n.label if n else node_id

        parts = [
            "---", 'type: "company"',
            f'dart_code: "{c.attrs.get("dart_code", "")}"',
            f'name: "{c.label}"', "tags: [company]", "---",
            f"# {c.label}\n",
        ]
        if sector:
            parts.append(f"> 섹터: {_wikilink(_label(sector.object_id))}\n")
        parts.append("\n## 세그먼트\n")
        for e in seg:
            sp = e.qualifier.get("share_pct")
            suffix = f" — {sp:g}%" if sp is not None else ""
            parts.append(f"- {_wikilink(_label(e.object_id))}{suffix}")
        parts.append("\n## 고객사\n")
        for e in cust:
            parts.append(f"- {_wikilink(_label(e.object_id))}")
        parts.append("\n## 지역 노출\n")
        for e in reg:
            sp = e.qualifier.get("share_pct")
            suffix = f" — {sp:g}%" if sp is not None else ""
            parts.append(f"- {_wikilink(_label(e.object_id))}{suffix}")

        parts += _render_financials(_company_financials(session, c.id))

        text = "\n".join(parts) + "\n"
        (cdir / f"{_safe(c.label)}.md").write_text(text, encoding="utf-8")

    return {"companies": len(companies)}
