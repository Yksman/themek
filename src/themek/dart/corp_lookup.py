"""DART corp_code 마스터 sync + ticker 조회."""
from __future__ import annotations
import zipfile
from io import BytesIO
from lxml import etree
from themek.dart.cache import DartCache


def parse_corp_code_zip(zip_bytes: bytes) -> list[dict]:
    """corpCode.xml zip → [{corp_code, corp_name, stock_code, modify_date}, ...]"""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        xml_bytes = z.read("CORPCODE.xml")
    root = etree.fromstring(xml_bytes)
    rows: list[dict] = []
    for item in root.findall("list"):
        rows.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        })
    return rows


def sync_corp_master(client, cache: DartCache) -> int:
    """client.fetch_corp_code_zip → parse → cache.save_corp_master. row count 반환."""
    zip_bytes = client.fetch_corp_code_zip()
    rows = parse_corp_code_zip(zip_bytes)
    cache.save_corp_master(rows)
    return len(rows)


def lookup_corp_code(cache: DartCache, *, ticker: str) -> str:
    """ticker(6자리) → corp_code(8자리). 못 찾으면 LookupError."""
    rows = cache.load_corp_master()
    if rows is None:
        raise LookupError(
            "corp_master 없음. `themek dart sync-corp` 먼저 실행하세요."
        )
    for r in rows:
        if r.get("stock_code") == ticker:
            return r["corp_code"]
    raise LookupError(f"ticker={ticker} corp_master에 없음")


def build_ticker_index(cache: DartCache) -> dict[str, dict]:
    """corp_master.json → {stock_code: row}. stock_code 빈 값은 제외.

    O(1) lookup 필요할 때 (예: sync_listed_stocks 2,500종목 조회).
    """
    rows = cache.load_corp_master()
    if rows is None:
        raise LookupError(
            "corp_master 없음. `themek dart sync-corp` 먼저 실행하세요."
        )
    return {r["stock_code"]: r for r in rows if r.get("stock_code")}
