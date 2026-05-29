"""코어 → nodes.json / edges.json. financial_facts는 REPORTS measurement 엣지로 투영.

graph-readiness 증명용 export (Neo4j/RDF import 가능 형태). 멱등.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.ids import metric_id, period_id
from themek.ontology.core.models import Node, Edge, FinancialFact


def export_graph(session: Session, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes = [
        {"id": n.id, "kind": n.kind, "label": n.label, "attrs": n.attrs}
        for n in session.execute(select(Node).order_by(Node.id)).scalars().all()
    ]
    edges = [
        {"subject_id": e.subject_id, "predicate": e.predicate,
         "object_id": e.object_id, "period": e.period, "qualifier": e.qualifier,
         "source_type": e.source_type, "confidence": e.confidence}
        for e in session.execute(select(Edge).order_by(Edge.id)).scalars().all()
    ]
    # financial_facts → REPORTS measurement 엣지 (company → metric)
    for f in session.execute(
        select(FinancialFact).order_by(FinancialFact.id)
    ).scalars().all():
        edges.append({
            "subject_id": f.company_id, "predicate": "REPORTS",
            "object_id": metric_id(f.metric_key),
            "period": f"{f.bsns_year}{f.fiscal_period}",
            "qualifier": {"amount": float(f.amount), "fs_div": f.fs_div,
                          "metric": f.metric_key,
                          "period_node": period_id(f.bsns_year, f.fiscal_period)},
            "source_type": f.source_type, "confidence": f.confidence,
        })

    (out_dir / "nodes.json").write_text(
        json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "edges.json").write_text(
        json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"nodes": len(nodes), "edges": len(edges)}
