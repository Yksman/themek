"""CLI dart 서브앱 통합 테스트.

DartClient를 monkeypatch로 가짜 응답으로 대체. 실 API 호출 0회.
"""
from __future__ import annotations
import json
import zipfile
from io import BytesIO
from pathlib import Path
from typer.testing import CliRunner
from themek.cli import app
from themek.dart import client as client_mod


runner = CliRunner()
FIXTURE_JSON = (
    Path(__file__).parent / "fixtures" / "samsung_extraction_expected.json"
)


def _make_corp_zip(rows: list[tuple[str, str, str]]) -> bytes:
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


def _make_doc_zip() -> bytes:
    """T0 정찰 후 — DART zip은 HTML이 아닌 dart4.xsd 기반 XML."""
    main_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="dart4.xsd">\n'
        '<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>\n'
        '<COMPANY-NAME AREGCIK="00126380">삼성전자</COMPANY-NAME>\n'
        '<BODY>\n'
        '<SECTION-1>'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ATOCID="3">I. 회사의 개요</TITLE>'
        '<P>회사 본문</P>'
        '</SECTION-1>\n'
        '<SECTION-1 ACLASS="MANDATORY">'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-2-0-0" ATOCID="9">II. 사업의 내용</TITLE>'
        '<P>샘플 사업 본문</P>'
        '</SECTION-1>\n'
        '</BODY>\n'
        '</DOCUMENT>'
    ).encode("utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20240312000736.xml", main_xml)
    return buf.getvalue()


# ---------- sync-corp ----------

def test_cli_dart_sync_corp_no_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DART_API_KEY", "")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    result = runner.invoke(app, ["dart", "sync-corp"])
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "DART_API_KEY" in combined or "미설정" in combined


def test_cli_dart_sync_corp_writes_master(monkeypatch, tmp_path):
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    zip_bytes = _make_corp_zip([
        ("00126380", "삼성전자", "005930"),
        ("00164742", "현대차", "005380"),
    ])
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_corp_code_zip",
        lambda self: zip_bytes,
    )
    result = runner.invoke(app, ["dart", "sync-corp"])
    assert result.exit_code == 0, result.stdout
    assert "synced 2" in result.stdout
    assert (tmp_path / "dart" / "corp_master.json").exists()


# ---------- fetch ----------

def test_cli_dart_fetch_writes_html(monkeypatch, tmp_path):
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))

    # 미리 corp_master를 준비
    cache_dir = tmp_path / "dart"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "raw").mkdir(exist_ok=True)
    (cache_dir / "corp_master.json").write_text(
        json.dumps([{
            "corp_code": "00126380", "corp_name": "삼성전자",
            "stock_code": "005930", "modify_date": "20240101",
        }]),
        encoding="utf-8",
    )

    doc_zip = _make_doc_zip()
    monkeypatch.setattr(
        client_mod.DartClient, "list_periodic_reports",
        lambda self, **kw: {"status": "000", "list": [
            {"rcept_no": "20240314000123",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        ]},
    )
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_document_zip",
        lambda self, *, rcept_no: doc_zip,
    )

    result = runner.invoke(
        app, ["dart", "fetch", "--ticker", "005930", "--period", "2023"]
    )
    assert result.exit_code == 0, result.stdout
    assert "business.html" in result.stdout
    assert (cache_dir / "raw" / "20240314000123" / "business.html").exists()


def test_cli_dart_fetch_no_corp_master(monkeypatch, tmp_path):
    """corp_master 없으면 sync-corp 안내."""
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    result = runner.invoke(
        app, ["dart", "fetch", "--ticker", "005930", "--period", "2023"]
    )
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "sync-corp" in combined


def test_cli_dart_fetch_unknown_ticker(monkeypatch, tmp_path):
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    cache_dir = tmp_path / "dart"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "raw").mkdir(exist_ok=True)
    (cache_dir / "corp_master.json").write_text(
        json.dumps([{
            "corp_code": "00126380", "corp_name": "삼성전자",
            "stock_code": "005930", "modify_date": "20240101",
        }]),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["dart", "fetch", "--ticker", "999999", "--period", "2023"]
    )
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "999999" in combined


# ---------- ingest ----------

def test_cli_dart_ingest_runs_full_pipeline(
    monkeypatch, tmp_path, engine, fresh_db
):
    """dart ingest → DB에 BusinessReport 행이 생성됨 (stub LLM)."""
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(FIXTURE_JSON))

    # seed로 corporations 등록
    runner.invoke(app, ["seed"])

    cache_dir = tmp_path / "dart"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "raw").mkdir(exist_ok=True)
    (cache_dir / "corp_master.json").write_text(
        json.dumps([{
            "corp_code": "00126380", "corp_name": "삼성전자",
            "stock_code": "005930", "modify_date": "20240101",
        }]),
        encoding="utf-8",
    )

    doc_zip = _make_doc_zip()
    monkeypatch.setattr(
        client_mod.DartClient, "list_periodic_reports",
        lambda self, **kw: {"status": "000", "list": [
            {"rcept_no": "20240314000123",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        ]},
    )
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_document_zip",
        lambda self, *, rcept_no: doc_zip,
    )

    result = runner.invoke(
        app, ["dart", "ingest", "--ticker", "005930", "--period", "2023"]
    )
    assert result.exit_code == 0, result.stdout
    assert "20240314000123" in result.stdout

    # query e5로 ingest 결과 확인
    qresult = runner.invoke(
        app, ["query", "e5", "--ticker", "005930"]
    )
    assert qresult.exit_code == 0, qresult.stdout
    assert "20240314000123" in qresult.stdout


def test_cli_dart_ingest_auto_creates_unknown_corporation(
    monkeypatch, tmp_path, engine, fresh_db,
):
    """seed에 없는 corp_code(예: 277810)도 corp_master 정보로 자동 upsert."""
    from themek.db.models import Corporation
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(FIXTURE_JSON))

    # seed는 호출 — sectors/regions/기존 corporations 등록 (FK 의존성).
    # 단 01261644(레인보우로보틱스)는 seed에 없는 신규 corp.
    runner.invoke(app, ["seed"])

    cache_dir = tmp_path / "dart"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "raw").mkdir(exist_ok=True)
    (cache_dir / "corp_master.json").write_text(
        json.dumps([{
            "corp_code": "01261644",
            "corp_name": "레인보우로보틱스",
            "stock_code": "277810",
            "modify_date": "20240101",
        }]),
        encoding="utf-8",
    )

    doc_zip = _make_doc_zip()
    monkeypatch.setattr(
        client_mod.DartClient, "list_periodic_reports",
        lambda self, **kw: {"status": "000", "list": [
            {"rcept_no": "20240321001029",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240321"},
        ]},
    )
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_document_zip",
        lambda self, *, rcept_no: doc_zip,
    )

    result = runner.invoke(
        app, ["dart", "ingest", "--ticker", "277810", "--period", "2023"]
    )
    assert result.exit_code == 0, result.stdout
    assert "20240321001029" in result.stdout

    # 새 Corporation row가 자동 upsert되어 있어야 함
    from themek.db.engine import make_session_factory
    with make_session_factory(engine)() as s:
        corp = s.get(Corporation, "01261644")
        assert corp is not None
        assert "레인보우" in corp.name_ko


def test_dart_ingest_uses_section_filter_text(monkeypatch, tmp_path, mocker,
                                              engine, fresh_db):
    """dart ingest는 extract_business_sections를 거친 text를 extractor에 넘긴다.

    section filter가 적용되면 노이즈 헤더 본문은 추출에서 제외되어야 함.
    """
    from themek.cli import app as _app

    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))

    # seed로 005930 = 00126380 등록
    runner.invoke(_app, ["seed"])

    cache_dir = tmp_path / "dart"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "corp_master.json").write_text(
        json.dumps([{
            "corp_code": "00126380", "corp_name": "삼성전자",
            "stock_code": "005930", "modify_date": "20240101",
        }]),
        encoding="utf-8",
    )

    cached_html = tmp_path / "business.html"
    filler = "ㅇ" * 400
    cached_html.write_text(
        f"<h3>1. 사업의 개요</h3><p>개요 본문 {filler}</p>"
        f"<h3>2. 주요 제품</h3><p>제품 본문 {filler}</p>"
        f"<h3>4. 매출 및 수주상황</h3><p>매출 본문 {filler}</p>"
        f"<h3>9. 노이즈</h3><p>이건 필터링되어야 함 {filler}</p>",
        encoding="utf-8",
    )
    mocker.patch(
        "themek.cli.fetch_business_report_html",
        return_value=(cached_html, "20240101000001"),
    )

    # extract_business_sections 호출 추적
    from themek.dart import parser as parser_mod
    original_extract = parser_mod.extract_business_sections
    captured: dict = {"text": None}

    def wrapped(html, **kwargs):
        text, res = original_extract(html, **kwargs)
        captured["text"] = text
        return text, res

    mocker.patch("themek.cli.extract_business_sections", side_effect=wrapped)

    stub_path = tmp_path / "stub.json"
    stub_path.write_text(json.dumps({
        "period": "2023", "segments": [], "customers": [], "geographic": []
    }), encoding="utf-8")
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub_path))

    result = runner.invoke(_app, [
        "dart", "ingest",
        "--ticker", "005930", "--period", "2023",
    ])
    assert result.exit_code == 0, result.stdout
    assert "Ingested" in result.stdout
    # section filter 효과: '노이즈' 헤더 본문은 제외돼야 함
    assert captured["text"] is not None
    assert "개요" in captured["text"]
    assert "제품" in captured["text"]
    assert "매출" in captured["text"]
    assert "이건 필터링되어야 함" not in captured["text"]


def test_dart_ingest_records_proposals_from_learned_samples(monkeypatch, tmp_path, mocker):
    """ingest가 learned_samples를 pattern_proposals.json에 누적한다."""
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )
    mocker.patch("themek.cli.lookup_corp_code", return_value="00000000")
    cached_html = tmp_path / "business.html"
    filler = "ㅇ" * 400
    cached_html.write_text(
        f"<p>1. 회사의 개황</p><p>본문 {filler}</p>"
        f"<p>2. 주요 제품 및 서비스</p><p>본문 {filler}</p>"
        f"<p>3. 매출 및 수주상황</p><p>본문 {filler}</p>",
        encoding="utf-8",
    )
    mocker.patch(
        "themek.cli.fetch_business_report_html",
        return_value=(cached_html, "20240101000001"),
    )

    def mock_classify(candidates, missing):
        for i, c in enumerate(candidates, 1):
            if "개황" in c and "overview" in missing:
                return {"overview": i, "products": None, "revenue": None}
        return {"overview": None, "products": None, "revenue": None}

    mocker.patch("themek.cli.llm_classify_headers", side_effect=mock_classify)
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(tmp_path / "proposals.json"))
    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH",
                       str(tmp_path / "learned.json"))
    monkeypatch.setenv("THEMEK_FIXTURES_DIR",
                       str(tmp_path / "fixtures"))

    stub_path = tmp_path / "stub.json"
    stub_path.write_text(
        '{"period": "2023", "segments": [], "customers": [], "geographic": []}',
        encoding="utf-8",
    )
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub_path))

    result = runner.invoke(app, [
        "dart", "ingest", "--ticker", "999999", "--period", "2023",
    ])
    assert result.exit_code == 0, result.stdout

    from themek.dart.pattern_learning import load_proposals
    proposals = load_proposals(tmp_path / "proposals.json")
    assert any(p.target == "overview" for p in proposals)


def test_dart_ingest_mirrors_fixture(monkeypatch, tmp_path, mocker):
    """dart ingest 후 fixtures/dart_variants/ 에 mirror 파일 존재."""
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )
    mocker.patch("themek.cli.lookup_corp_code", return_value="00000000")
    cached_html = tmp_path / "business.html"
    filler = "ㅇ" * 400
    cached_html.write_text(
        f"<p>1. 사업의 개요</p><p>{filler}</p>"
        f"<p>2. 주요 제품 및 서비스</p><p>{filler}</p>"
        f"<p>3. 매출 및 수주상황</p><p>{filler}</p>",
        encoding="utf-8",
    )
    mocker.patch(
        "themek.cli.fetch_business_report_html",
        return_value=(cached_html, "20240101000001"),
    )
    fixtures_dir = tmp_path / "fixtures"
    monkeypatch.setenv("THEMEK_FIXTURES_DIR", str(fixtures_dir))
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(tmp_path / "proposals.json"))
    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH",
                       str(tmp_path / "learned.json"))
    stub_path = tmp_path / "stub.json"
    stub_path.write_text(
        '{"period":"2023","segments":[],"customers":[],"geographic":[]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub_path))

    result = runner.invoke(app, [
        "dart", "ingest", "--ticker", "999999", "--period", "2023",
    ])
    assert result.exit_code == 0, result.stdout
    assert (fixtures_dir / "999999_2023.html").exists()
    assert (fixtures_dir / "999999_2023_headers.json").exists()


def test_cli_dart_ingest_idempotent(
    monkeypatch, tmp_path, engine, fresh_db
):
    """같은 ingest를 두 번 실행해도 DB는 idempotent."""
    monkeypatch.setenv("DART_API_KEY", "test-key")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(FIXTURE_JSON))

    runner.invoke(app, ["seed"])

    cache_dir = tmp_path / "dart"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "raw").mkdir(exist_ok=True)
    (cache_dir / "corp_master.json").write_text(
        json.dumps([{
            "corp_code": "00126380", "corp_name": "삼성전자",
            "stock_code": "005930", "modify_date": "20240101",
        }]),
        encoding="utf-8",
    )

    doc_zip = _make_doc_zip()
    doc_call_count = {"n": 0}

    def fake_doc(self, *, rcept_no):
        doc_call_count["n"] += 1
        return doc_zip

    monkeypatch.setattr(
        client_mod.DartClient, "list_periodic_reports",
        lambda self, **kw: {"status": "000", "list": [
            {"rcept_no": "20240314000123",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        ]},
    )
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_document_zip", fake_doc,
    )

    r1 = runner.invoke(
        app, ["dart", "ingest", "--ticker", "005930", "--period", "2023"]
    )
    assert r1.exit_code == 0, r1.stdout
    assert doc_call_count["n"] == 1

    # 2번째 — document.xml 호출 0회 (cache hit) + DB idempotent (no-op)
    r2 = runner.invoke(
        app, ["dart", "ingest", "--ticker", "005930", "--period", "2023"]
    )
    assert r2.exit_code == 0, r2.stdout
    assert doc_call_count["n"] == 1, "cache hit이면 document.xml 호출 안 함"


def test_dart_incremental_universe_source_stocks(monkeypatch, fresh_db, mocker):
    """--universe-source stocks는 Stock 테이블에서 corp_code set을 만든다."""
    from datetime import date

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import Corporation, Stock
    from themek.dart.incremental import IncrementalRunResult
    from themek.db.engine import make_engine, make_session_factory

    monkeypatch.setenv("DART_API_KEY", "test")
    Session = make_session_factory(make_engine())
    with Session() as s:
        s.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
        s.flush()
        s.add(Stock(
            ticker="005930", name_ko="삼성전자", market="KOSPI",
            share_class="common", issued_by_id="00126380",
            last_seen_at=date(2026, 5, 27),
        ))
        s.commit()

    captured: dict = {}

    def fake_run(*, universe, **kwargs):
        captured["universe"] = universe
        return IncrementalRunResult()

    mocker.patch("themek.cli.run_incremental", fake_run)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )

    local_runner = CliRunner()
    result = local_runner.invoke(app, [
        "dart", "incremental",
        "--universe-source", "stocks",
        "--since", "yesterday", "--until", "today",
    ])
    assert result.exit_code == 0, result.stdout
    assert captured["universe"] == {"00126380"}


def test_dart_incremental_universe_source_file_still_works(mocker, tmp_path):
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.incremental import IncrementalRunResult

    p = tmp_path / "active.txt"
    p.write_text("00126380\n", encoding="utf-8")

    captured: dict = {}

    def fake_run(*, universe, **kwargs):
        captured["universe"] = universe
        return IncrementalRunResult()

    mocker.patch("themek.cli.run_incremental", fake_run)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )

    local_runner = CliRunner()
    result = local_runner.invoke(app, [
        "dart", "incremental",
        "--universe-file", str(p),
    ])
    assert result.exit_code == 0
    assert captured["universe"] == {"00126380"}


def test_dart_sync_corp_skips_when_fresh(tmp_path, mocker):
    """--if-stale-days N: corp_master.json mtime이 N일 이내면 skip."""
    import os
    import time

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.cache import DartCache

    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([{"corp_code": "00000001", "corp_name": "x",
                              "stock_code": "", "modify_date": "20240101"}])
    # 방금 저장되어 mtime이 now
    fake_sync = mocker.patch("themek.cli.sync_corp_master")
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), cache),
    )

    local_runner = CliRunner()
    result = local_runner.invoke(app, ["dart", "sync-corp", "--if-stale-days", "90"])
    assert result.exit_code == 0
    assert "skipped" in result.stdout.lower()
    fake_sync.assert_not_called()


def test_dart_sync_corp_runs_when_stale(tmp_path, mocker):
    import os
    import time

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.cache import DartCache

    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([])
    old_mtime = time.time() - 100 * 86400  # 100일 전
    os.utime(cache.corp_master_path, (old_mtime, old_mtime))

    fake_sync = mocker.patch("themek.cli.sync_corp_master", return_value=42)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), cache),
    )

    local_runner = CliRunner()
    result = local_runner.invoke(app, ["dart", "sync-corp", "--if-stale-days", "90"])
    assert result.exit_code == 0
    fake_sync.assert_called_once()


def test_dart_sync_corp_runs_when_missing(tmp_path, mocker):
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.cache import DartCache

    cache = DartCache(base_dir=tmp_path)
    fake_sync = mocker.patch("themek.cli.sync_corp_master", return_value=42)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), cache),
    )

    local_runner = CliRunner()
    result = local_runner.invoke(app, ["dart", "sync-corp", "--if-stale-days", "90"])
    assert result.exit_code == 0
    fake_sync.assert_called_once()
