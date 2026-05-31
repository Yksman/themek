"""마이그레이션 체인 자립성 회귀 테스트.

`alembic upgrade head`가 빈 DB에서 코어(nodes/edges/financial_facts/concept_aliases)
+ 운영 테이블을 모두 만들고, 잔재 테이블은 남기지 않으며, 0005/0007 산출물(인덱스·확장
enum)까지 적용되는지 검증한다. (0004a_core_tables 누락 회귀 방지.)
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_fresh_db_alembic_upgrade_head_is_self_contained(tmp_path):
    db = tmp_path / "fresh.db"
    env = dict(os.environ)
    env["POSTGRES_DSN"] = f"sqlite:///{db}"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"alembic failed:\n{proc.stderr}"

    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}

    assert {"nodes", "edges", "financial_facts", "concept_aliases"} <= tables
    assert {"corporations", "stocks", "business_reports",
            "backfill_targets"} <= tables
    legacy = {"business_segments", "customer_relations",
              "geographic_exposures", "revenue_compositions", "products"}
    assert not (legacy & tables), f"legacy tables present: {legacy & tables}"
    assert "ux_edge_spo" in indexes  # 0005

    # 0007: 확장된 metric_key enum로 eps insert 가능
    con.execute("INSERT INTO nodes(id,kind,label,attrs) "
                "VALUES('company:t','company','t','{}')")
    con.execute(
        "INSERT INTO financial_facts(company_id,bsns_year,fiscal_period,"
        "fs_div,metric_key,amount,currency,source_type,method,confidence) "
        "VALUES('company:t','2024','FY','CFS','eps',1,'KRW','dart_api','api',1.0)")
    con.close()


def test_alembic_single_head():
    """브랜칭 없이 head가 정확히 1개여야 한다."""
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    head_lines = [ln for ln in proc.stdout.splitlines() if "(head)" in ln]
    assert len(head_lines) == 1, f"expected 1 head, got: {proc.stdout}"
