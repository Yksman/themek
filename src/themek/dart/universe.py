"""Universe 단일 source of truth — active.txt 로더.

format:
  corp_code 1줄당 1개 (8자리). #로 시작하는 주석 + 빈 줄 허용.
  중복은 자동 dedup (순서 보존).
"""
from __future__ import annotations
import re
from pathlib import Path

_CORP_CODE_RE = re.compile(r"^\d{8}$")


def load_universe(path: Path) -> list[str]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"universe file 없음: {path}")
    seen: set[str] = set()
    out: list[str] = []
    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1,
    ):
        line = raw.strip()
        # 인라인 주석 허용: "00126380   # 삼성전자" → corp_code만 추출
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if not _CORP_CODE_RE.match(line):
            raise ValueError(
                f"{path}:{lineno} corp_code 형식 오류 (8자리 숫자 필요): {raw!r}"
            )
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


from sqlalchemy import select
from sqlalchemy.orm import Session


def load_universe_from_stocks(
    session: Session,
    *,
    include_delisted: bool = False,
) -> list[str]:
    """Stock 테이블 → distinct corp_code list. delisted 기본 제외."""
    from themek.db.corp_models import Stock

    q = select(Stock.issued_by_id).distinct()
    if not include_delisted:
        q = q.where(Stock.delisted_at.is_(None))
    return list(session.scalars(q).all())
