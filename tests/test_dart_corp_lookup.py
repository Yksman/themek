"""corp_lookup 단위 + 통합 테스트."""
from __future__ import annotations
import zipfile
from io import BytesIO
from pathlib import Path
import pytest
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import (
    parse_corp_code_zip, sync_corp_master, lookup_corp_code,
)


REAL_CORP_ZIP = (
    Path(__file__).parent / "fixtures" / "dart_cassettes"
    / "corp_code_zip_success.bin"
)


def _make_corp_zip(rows: list[tuple[str, str, str]]) -> bytes:
    """rows: [(corp_code, corp_name, stock_code), ...] → corpCode zip."""
    xml = "<?xml version='1.0' encoding='UTF-8'?>\n<result>"
    for c, n, s in rows:
        xml += (
            f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name>"
            f"<stock_code>{s}</stock_code><modify_date>20240101</modify_date></list>"
        )
    xml += "</result>"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buf.getvalue()


def test_parse_corp_code_zip_extracts_rows():
    zip_bytes = _make_corp_zip([
        ("00126380", "삼성전자", "005930"),
        ("00164742", "현대자동차", "005380"),
        ("01234567", "비상장A", ""),
    ])
    rows = parse_corp_code_zip(zip_bytes)
    assert len(rows) == 3
    assert rows[0]["corp_code"] == "00126380"
    assert rows[0]["corp_name"] == "삼성전자"
    assert rows[0]["stock_code"] == "005930"
    assert rows[2]["stock_code"] == ""


def test_parse_corp_code_zip_handles_modify_date():
    zip_bytes = _make_corp_zip([("00126380", "samsung", "005930")])
    rows = parse_corp_code_zip(zip_bytes)
    assert rows[0]["modify_date"] == "20240101"


def test_sync_corp_master_saves_to_cache(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    zip_bytes = _make_corp_zip([
        ("00126380", "삼성전자", "005930"),
        ("00164742", "현대차", "005380"),
    ])

    class FakeClient:
        def fetch_corp_code_zip(self):
            return zip_bytes

    n = sync_corp_master(FakeClient(), cache)
    assert n == 2
    loaded = cache.load_corp_master()
    assert loaded[0]["corp_code"] == "00126380"
    assert loaded[1]["stock_code"] == "005380"


def test_lookup_corp_code_hit(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    cache.save_corp_master([
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930"},
        {"corp_code": "00164742", "corp_name": "현대차",
         "stock_code": "005380"},
    ])
    assert lookup_corp_code(cache, ticker="005930") == "00126380"
    assert lookup_corp_code(cache, ticker="005380") == "00164742"


def test_lookup_corp_code_miss(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    cache.save_corp_master([
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930"},
    ])
    with pytest.raises(LookupError, match="999999"):
        lookup_corp_code(cache, ticker="999999")


def test_lookup_corp_code_no_master_raises(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    with pytest.raises(LookupError, match="sync-corp"):
        lookup_corp_code(cache, ticker="005930")


# ---------- 실 fixture 통합 ----------

@pytest.mark.skipif(
    not REAL_CORP_ZIP.exists(),
    reason="실 corpCode.zip fixture 없음",
)
def test_parse_real_corpcode_zip_has_samsung():
    """실 DART corpCode.zip 파싱 → 삼성전자(005930) 매치."""
    rows = parse_corp_code_zip(REAL_CORP_ZIP.read_bytes())
    # T0 정찰 시점 118,145 row — 임계는 보수적으로 80,000
    assert len(rows) >= 80_000
    samsung = [r for r in rows if r["stock_code"] == "005930"]
    assert len(samsung) >= 1
    assert samsung[0]["corp_code"] == "00126380"
    assert "삼성전자" in samsung[0]["corp_name"]


@pytest.mark.skipif(
    not REAL_CORP_ZIP.exists(),
    reason="실 corpCode.zip fixture 없음",
)
def test_sync_and_lookup_with_real_zip(tmp_path):
    """실 zip → sync → 005930/005380/277810 모두 lookup 가능."""
    cache = DartCache(base_dir=tmp_path / "dart")

    class FakeClient:
        def fetch_corp_code_zip(self):
            return REAL_CORP_ZIP.read_bytes()

    n = sync_corp_master(FakeClient(), cache)
    assert n >= 80_000
    # 삼성전자
    assert lookup_corp_code(cache, ticker="005930") == "00126380"
    # 현대차
    hyundai = lookup_corp_code(cache, ticker="005380")
    assert hyundai and len(hyundai) == 8
    # 레인보우로보틱스
    rainbow = lookup_corp_code(cache, ticker="277810")
    assert rainbow and len(rainbow) == 8
