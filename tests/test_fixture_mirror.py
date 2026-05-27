"""fixture_mirror — ingest cache HTML을 tests/fixtures/dart_variants/에 mirror."""
import json
from pathlib import Path

from themek.dart.fixture_mirror import mirror_fixture


def test_mirror_copies_html_and_writes_expected_headers(tmp_path):
    cache_html = tmp_path / "cache" / "business.html"
    cache_html.parent.mkdir(parents=True)
    cache_html.write_text(
        "<p>1. 사업의 개요</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>2. 주요 제품 및 서비스</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>3. 매출 및 수주상황</p><p>본문" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    fixtures_dir = tmp_path / "fixtures"
    mirror_fixture(
        cache_html=cache_html, ticker="005930", period="2023",
        fixtures_dir=fixtures_dir,
    )
    mirrored = fixtures_dir / "005930_2023.html"
    headers_json = fixtures_dir / "005930_2023_headers.json"
    assert mirrored.exists()
    assert headers_json.exists()
    expected = json.loads(headers_json.read_text(encoding="utf-8"))
    assert "overview" in expected
    assert "사업의 개요" in expected["overview"]


def test_mirror_idempotent(tmp_path):
    cache_html = tmp_path / "cache" / "business.html"
    cache_html.parent.mkdir(parents=True)
    cache_html.write_text(
        "<p>1. 사업의 개요</p><p>" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    fixtures_dir = tmp_path / "fixtures"
    mirror_fixture(
        cache_html=cache_html, ticker="X", period="2023",
        fixtures_dir=fixtures_dir,
    )
    mtime1 = (fixtures_dir / "X_2023.html").stat().st_mtime
    mirror_fixture(
        cache_html=cache_html, ticker="X", period="2023",
        fixtures_dir=fixtures_dir,
    )
    mtime2 = (fixtures_dir / "X_2023.html").stat().st_mtime
    assert mtime1 == mtime2
