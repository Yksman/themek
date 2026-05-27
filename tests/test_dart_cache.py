"""DartCache 단위 테스트."""
from __future__ import annotations
import json
from themek.dart.cache import DartCache


def test_cache_init_creates_subdirs(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    assert (tmp_path / "dart").is_dir()
    assert (tmp_path / "dart" / "raw").is_dir()


def test_cache_save_and_load_corp_master(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    payload = [
        {"corp_code": "00126380", "corp_name": "samsung", "stock_code": "005930"},
    ]
    p = cache.save_corp_master(payload)
    assert p.exists()
    assert cache.load_corp_master() == payload


def test_cache_load_corp_master_returns_none_when_missing(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    assert cache.load_corp_master() is None


def test_cache_save_raw_zip_writes_file(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    p = cache.save_raw_zip("20240314000123", b"PK\x03\x04dummy")
    assert p.exists()
    assert p.read_bytes() == b"PK\x03\x04dummy"
    assert p.parent.name == "20240314000123"


def test_cache_save_business_html_writes_file(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    p = cache.save_business_html("20240314000123", b"<html><body>x</body></html>")
    assert p.exists()
    assert p.read_bytes().startswith(b"<html>")


def test_cache_has_and_get_business_html(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    rcept = "20240314000123"
    assert not cache.has_business_html(rcept)
    cache.save_business_html(rcept, b"<html>body</html>")
    assert cache.has_business_html(rcept)
    p = cache.get_business_html_path(rcept)
    assert p.exists()
    assert p.read_bytes() == b"<html>body</html>"


def test_cache_corp_master_unicode_preserved(tmp_path):
    """ensure_ascii=False — 한글 corp_name 보존."""
    cache = DartCache(base_dir=tmp_path / "dart")
    payload = [
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930"},
    ]
    cache.save_corp_master(payload)
    raw = cache.corp_master_path.read_text(encoding="utf-8")
    assert "삼성전자" in raw
    loaded = cache.load_corp_master()
    assert loaded[0]["corp_name"] == "삼성전자"
