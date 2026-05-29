"""KRX 상장사 → Stock 테이블 sync."""
from __future__ import annotations

from typing import Protocol


class _KrxClientLike(Protocol):
    def list_tickers(
        self, *, market: str, date: str | None = None,
    ) -> list[str]: ...


def fetch_listed_universe(
    client: _KrxClientLike,
    *,
    date: str | None = None,
) -> dict[str, str]:
    """KOSPI + KOSDAQ 통합. {ticker: market} 반환.

    date=None이면 최근 영업일.
    """
    out: dict[str, str] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for t in client.list_tickers(market=market, date=date):
            out[t] = market
    return out


from dataclasses import dataclass, field
from datetime import date as _date
from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.corp_models import Stock, Corporation
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import build_ticker_index


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    delisted: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)


def sync_listed_stocks(
    session: Session,
    *,
    krx_client: _KrxClientLike,
    cache: DartCache,
    today: _date,
) -> SyncResult:
    """KRX KOSPI+KOSDAQ ticker list → Stock 테이블 upsert + delisting 감지.

    동작:
    - listed에 있는 ticker:
      - corp_master 매칭: Corporation upsert + Stock upsert (last_seen_at=today)
      - delisted_at set인 row면 None으로 복원 (재상장)
      - corp_master 미매칭: unlinked로 기록, Stock 미생성
    - listed에 없는 기존 Stock + delisted_at=None: delisted_at=today set
    """
    listed = fetch_listed_universe(krx_client)
    idx = build_ticker_index(cache)
    existing = {s.ticker: s for s in session.scalars(select(Stock)).all()}

    result = SyncResult()
    for ticker, market in listed.items():
        corp = idx.get(ticker)
        if corp is None:
            result.unlinked.append(ticker)
            continue
        corp_code = corp["corp_code"]
        name = corp.get("corp_name") or ticker

        if session.get(Corporation, corp_code) is None:
            session.add(Corporation(dart_code=corp_code, name_ko=name))
            session.flush()

        row = existing.get(ticker)
        if row is None:
            session.add(Stock(
                ticker=ticker, name_ko=name, market=market,
                share_class="common", issued_by_id=corp_code,
                last_seen_at=today,
            ))
            result.added.append(ticker)
        else:
            row.market = market
            row.last_seen_at = today
            if row.delisted_at is not None:
                row.delisted_at = None
            result.updated.append(ticker)

    listed_set = set(listed.keys())
    for ticker, row in existing.items():
        if ticker not in listed_set and row.delisted_at is None:
            row.delisted_at = today
            result.delisted.append(ticker)

    session.commit()
    return result
