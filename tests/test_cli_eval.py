import json
from pathlib import Path

from typer.testing import CliRunner

from themek.cli import app


runner = CliRunner()


def _write_stub(tmp_path: Path, extraction: dict) -> Path:
    p = tmp_path / "stub.json"
    p.write_text(json.dumps(extraction), encoding="utf-8")
    return p


def _write_ground_truth(tmp_path: Path, extraction: dict) -> Path:
    p = tmp_path / "gt.json"
    p.write_text(json.dumps({
        "metadata": {
            "ticker": "005930", "name_ko": "삼성전자",
            "period": "2023", "source_rcept_no": "x",
            "fixture_path": "x", "created_at": "2026-05-23", "notes": "",
        },
        "extraction": extraction,
    }), encoding="utf-8")
    return p


def _write_html(tmp_path: Path) -> Path:
    p = tmp_path / "report.html"
    p.write_text("<html><body><p>본문</p></body></html>", encoding="utf-8")
    return p


def test_cli_eval_e5_perfect_score(monkeypatch, tmp_path):
    payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [{"name_raw": "Apple Inc.", "tier": "1차"}],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = _write_stub(tmp_path, payload)
    gt = _write_ground_truth(tmp_path, payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
    ])
    assert result.exit_code == 0, result.stdout
    assert "삼성전자" in result.stdout
    assert "1.000" in result.stdout
    assert "0.00 %p" in result.stdout


def test_cli_eval_e5_missing_ground_truth(monkeypatch, tmp_path):
    stub = _write_stub(tmp_path, {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    })
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(tmp_path / "nope.json"),
    ])
    assert result.exit_code != 0
    assert "ground truth not found" in (result.stdout + (result.stderr or ""))


def test_cli_eval_e5_runs_3_with_stub_outputs_aggregated_table(monkeypatch, tmp_path):
    payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [{"name_raw": "Apple Inc.", "tier": "1차"}],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = _write_stub(tmp_path, payload)
    gt = _write_ground_truth(tmp_path, payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "3",
    ])
    assert result.exit_code == 0, result.stdout
    assert "(N=3)" in result.stdout
    assert "Token usage" in result.stdout
    assert "Section filter" in result.stdout


def test_cli_eval_e5_default_runs_one_keeps_existing_format(monkeypatch, tmp_path):
    """--runs 미지정 시 N=1, 기존 포맷 유지 (회귀 가드)."""
    payload = {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    }
    stub = _write_stub(tmp_path, payload)
    gt = _write_ground_truth(tmp_path, payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))
    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
    ])
    assert result.exit_code == 0
    assert "(N=" not in result.stdout       # N=1 포맷에는 N=N 표시 없음
    assert "Token usage" not in result.stdout


def test_cli_eval_e5_runs_3_shows_escalation_level(monkeypatch, tmp_path):
    """N>1 출력의 Section filter 블록에 escalation_level 라인이 포함된다."""
    payload = {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    }
    stub = _write_stub(tmp_path, payload)
    gt = _write_ground_truth(tmp_path, payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))
    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "3",
    ])
    assert result.exit_code == 0, result.stdout
    assert "escalation" in result.stdout.lower()


def test_cli_eval_e5_reports_missed(monkeypatch, tmp_path):
    truth_payload = {
        "period": "2023",
        "segments": [
            {"name_ko": "메모리", "share_pct": 20.0, "products": []},
            {"name_ko": "Harman", "share_pct": 5.0, "products": []},
        ],
        "customers": [],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub_payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = _write_stub(tmp_path, stub_payload)
    gt = _write_ground_truth(tmp_path, truth_payload)
    html = _write_html(tmp_path)
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
    ])
    assert result.exit_code == 0, result.stdout
    assert "Harman" in result.stdout
