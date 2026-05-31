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
from themek.ontology.validate import check_integrity, Issue

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_WS = re.compile(r"\s+")
_NAME_MAX = 60
_FISCAL_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
_KPI_ORDER = ["revenue", "operating_income", "net_income",
              "assets", "liabilities", "equity"]
_KPI_LABEL = {"revenue": "매출액", "operating_income": "영업이익",
              "net_income": "당기순이익", "assets": "자산총계",
              "liabilities": "부채총계", "equity": "자본총계"}
_CF_ORDER = ["cf_operating", "cf_investing", "cf_financing"]
_CF_LABEL = {"cf_operating": "영업활동현금흐름",
             "cf_investing": "투자활동현금흐름",
             "cf_financing": "재무활동현금흐름"}
_INLINE_ORDER = _KPI_ORDER + _CF_ORDER + ["eps", "shares_outstanding"]
_GENERATED_DIRS = ("companies", "segments", "customers", "regions", "sectors",
                   "people")
_KIND_DIR = {"segment": "segments", "customer": "customers",
             "region": "regions", "sector": "sectors"}
_SEVERITY_ORDER = ("error", "warn", "info")


def _render_qa_report(issues: list[Issue]) -> str:
    """무결성 이슈 → `_qa-report.md` 문자열 (순수 렌더, 부작용 없음)."""
    by_sev = {sev: [i for i in issues if i.severity == sev]
              for sev in _SEVERITY_ORDER}
    counts = " · ".join(f"{sev}: {len(by_sev[sev])}" for sev in _SEVERITY_ORDER)
    lines = ["---", 'type: "qa-report"', "tags: [qa-report]", "---",
             "# 온톨로지 무결성 리포트\n",
             f"\n- 총 이슈: {len(issues)}",
             f"- {counts}\n"]
    if not issues:
        lines.append("\n무결성 이슈 없음 ✅\n")
        return "\n".join(lines) + "\n"
    for sev in _SEVERITY_ORDER:
        group = by_sev[sev]
        if not group:
            continue
        lines.append(f"\n## {sev} ({len(group)})\n")
        lines.append("| code | subject | message |")
        lines.append("|------|---------|---------|")
        for i in group:
            subj = i.subject or "—"
            msg = (i.message or "").replace("|", r"\|")
            lines.append(f"| {i.code} | {subj} | {msg} |")
    return "\n".join(lines) + "\n"


def _safe(name: str) -> str:
    return _WS.sub(" ", _UNSAFE.sub(" ", name)).strip()


def _yaml_str(s: str) -> str:
    """YAML 더블쿼트 스칼라로 escape(백슬래시·쿼트). 빈 문자열도 안전."""
    esc = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'


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

    # 현금흐름 소표 (억원) — 단위가 다른 KPI 표와 분리
    if any(k in fin[p] for p in periods for k in _CF_ORDER):
        lines += ["\n## 현금흐름 (단위 억원)\n", header, sep]
        for key in _CF_ORDER:
            if not any(key in fin[p] for p in periods):
                continue
            cells = [(_eok(fin[p][key]) if key in fin[p] else "—") for p in periods]
            lines.append(f"| {_CF_LABEL[key]} | " + " | ".join(cells) + " |")
        lines.append("")

    # EPS 소표 (원/주)
    if any("eps" in fin[p] for p in periods):
        lines += ["\n## 주당 지표\n", header, sep]
        cells = [(f"{fin[p]['eps']:,.0f}원" if "eps" in fin[p] else "—")
                 for p in periods]
        lines.append("| EPS (원/주) | " + " | ".join(cells) + " |")
        lines.append("")

    # 발행주식수 소표 (주)
    if any("shares_outstanding" in fin[p] for p in periods):
        lines += ["\n## 발행주식수\n", header, sep]
        cells = [(f"{fin[p]['shares_outstanding']:,.0f}주"
                  if "shares_outstanding" in fin[p] else "—") for p in periods]
        lines.append("| 발행주식수 | " + " | ".join(cells) + " |")
        lines.append("")

    for (y, fp) in periods:
        for key in _INLINE_ORDER:
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


def _inbound_holders(edges: list[Edge]) -> list[tuple[str, float | None, str | None]]:
    """주주 엣지(OWNS_STAKE_IN, object=회사) → subject별 최신 period.

    반환: [(subject_id, stake_pct, relation)].
    """
    best: dict[str, tuple] = {}
    for e in edges:
        pk = e.period or ""
        cur = best.get(e.subject_id)
        if cur is None or pk > cur[0]:
            best[e.subject_id] = (pk, e.qualifier.get("stake_pct"),
                                  e.qualifier.get("relation"))
    return [(k, v[1], v[2]) for k, v in best.items()]


def _outbound_holdings(edges: list[Edge]) -> list[tuple[str, float | None, str | None]]:
    """타법인 출자 엣지(OWNS_STAKE_IN, subject=회사) → object별 최신 period.

    반환: [(object_id, stake_pct, affiliation_type)].
    """
    best: dict[str, tuple] = {}
    for e in edges:
        pk = e.period or ""
        cur = best.get(e.object_id)
        if cur is None or pk > cur[0]:
            best[e.object_id] = (pk, e.qualifier.get("stake_pct"),
                                 e.qualifier.get("affiliation_type"))
    return [(k, v[1], v[2]) for k, v in best.items()]


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

    # C9: 무결성 체크 1회 호출 → QA 리포트 emit (이후 frontmatter issue_count에서 공유)
    issues = check_integrity(session)
    (out_dir / "_qa-report.md").write_text(
        _render_qa_report(issues), encoding="utf-8")
    issues_by_company: dict[str, int] = {}
    for i in issues:
        if i.subject:
            issues_by_company[i.subject] = issues_by_company.get(i.subject, 0) + 1

    node_label = dict(session.execute(select(Node.id, Node.label)).all())
    companies = session.execute(
        select(Node).where(Node.kind == "company").order_by(Node.label)
    ).scalars().all()

    # 개념 노드 → 백링크 수집: {concept_node_id: [(company_label, predicate, share)]}
    backlinks: dict[str, list[tuple[str, str, float | None]]] = {}
    # 주주(person) → 보유 회사 백링크: {holder_node_id: [(company_label, stake_pct)]}
    people_backlinks: dict[str, list[tuple[str, float | None]]] = {}

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

        # C10: frontmatter 보강 — 종목/섹터/기간/카운트/이슈
        stock_edge = next((e for e in edges if e.predicate == "ISSUES_STOCK"), None)
        stock_node = (session.get(Node, stock_edge.object_id)
                      if stock_edge else None)
        ticker = stock_node.attrs.get("ticker", "") if stock_node else ""
        market = stock_node.attrs.get("market", "") if stock_node else ""
        sector_label = _lbl(sector.object_id) if sector else ""
        fin = _company_financials(session, c.id)
        periods = sorted(fin.keys(), key=lambda k: _period_sort_key(*k))
        period_list = ", ".join(f"{y}{fp}" for y, fp in periods)

        parts = [
            "---", 'type: "company"',
            f'dart_code: "{c.attrs.get("dart_code", "")}"',
            f"name: {_yaml_str(c.label)}",
            f"ticker: {_yaml_str(ticker)}",
            f"market: {_yaml_str(market)}",
            f"sector: {_yaml_str(sector_label)}",
            f"periods: [{period_list}]",
            f"report_count: {len(periods)}",
            f"segment_count: {len(seg)}",
            f"customer_count: {len(cust)}",
            f"issue_count: {issues_by_company.get(c.id, 0)}",
            "tags: [company]", "---",
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

        # 지분구조 — 주주(inbound) + 타법인 출자(outbound)
        inbound_edges = session.execute(
            select(Edge).where(Edge.predicate == "OWNS_STAKE_IN",
                               Edge.object_id == c.id)
        ).scalars().all()
        holders = _inbound_holders(inbound_edges)
        holdings = _outbound_holdings(
            [e for e in edges if e.predicate == "OWNS_STAKE_IN"])
        parts.append("\n## 지분구조\n")
        parts.append("### 주주 (최대주주·특수관계인)\n")
        for sid, pct, rel in holders:
            rel_part = f" ({rel})" if rel else ""
            pct_part = f" — {pct:g}%" if pct is not None else ""
            parts.append(f"- {_wikilink(_lbl(sid))}{rel_part}{pct_part}")
            people_backlinks.setdefault(sid, []).append((c.label, pct))
        if not holders:
            parts.append("- (없음)")
        parts.append("\n### 타법인 출자\n")
        for oid, pct, aff in holdings:
            aff_part = f" [{aff}]" if aff else ""
            pct_part = f" — {pct:g}%" if pct is not None else ""
            parts.append(f"- {_wikilink(_lbl(oid))}{aff_part}{pct_part}")
        if not holdings:
            parts.append("- (없음)")

        parts += _render_financials(fin)
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

    # person 노트 — 보유 회사 백링크 포함
    persons = session.execute(
        select(Node).where(Node.kind == "person").order_by(Node.label)
    ).scalars().all()
    for p in persons:
        refs = people_backlinks.get(p.id, [])
        parts = ["---", 'type: "person"', f"name: {_yaml_str(p.label)}",
                 f"owned_count: {len(refs)}", "tags: [person]", "---",
                 f"# {p.label}\n", f"\n## 보유 회사 ({len(refs)})\n"]
        for comp_label, pct in sorted(set(refs)):
            suffix = f" — {pct:g}%" if pct is not None else ""
            parts.append(f"- {_wikilink(comp_label)}{suffix}")
        if not refs:
            parts.append("- (없음)")
        (out_dir / "people" / f"{_note_name(p.label)}.md").write_text(
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

    return {"companies": len(companies), "concepts": len(concept_nodes),
            "people": len(persons), "issues": len(issues)}
