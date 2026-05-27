"""--save-runs 결과물 schema 검증."""
import json
from typer.testing import CliRunner
from themek.cli import app


runner = CliRunner()


def _gt_payload(extraction: dict) -> dict:
    return {
        "metadata": {
            "ticker": "005930", "name_ko": "삼성전자",
            "period": "2023", "source_rcept_no": "x",
            "fixture_path": "x", "created_at": "2026-05-26", "notes": "",
        },
        "extraction": extraction,
    }


def test_save_runs_creates_per_run_files(monkeypatch, tmp_path):
    payload = {
        "period": "2023",
        "segments": [{"name_ko": "메모리", "share_pct": 20.0, "products": []}],
        "customers": [],
        "geographic": [{"region_code": "KR", "share_pct": 100.0}],
    }
    stub = tmp_path / "stub.json"
    stub.write_text(json.dumps(payload), encoding="utf-8")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(_gt_payload(payload)), encoding="utf-8")
    html = tmp_path / "report.html"
    html.write_text("<html><body><h3>1. 사업의 개요</h3><p>본문</p></body></html>",
                    encoding="utf-8")
    save_dir = tmp_path / "runs"
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "3",
        "--save-runs", str(save_dir),
    ])
    assert result.exit_code == 0, result.stdout

    target = save_dir / "005930_2023"
    assert target.is_dir()
    for i in (1, 2, 3):
        p = target / f"run_{i}.json"
        assert p.exists()
        run = json.loads(p.read_text(encoding="utf-8"))
        assert run["run_index"] == i
        assert "parsed_extraction" in run
        assert "usage" in run
        assert "eval_result" in run

    sec = target / "section_resolution.json"
    assert sec.exists()
    sec_data = json.loads(sec.read_text(encoding="utf-8"))
    assert "regex_matched" in sec_data
    assert "skipped" in sec_data

    summary = target / "summary.json"
    assert summary.exists()
    s = json.loads(summary.read_text(encoding="utf-8"))
    assert s["n_runs"] == 3
    assert "segment_recall_mean" in s
    assert "total_input_tokens" in s


def test_save_runs_unused_when_flag_absent(monkeypatch, tmp_path):
    payload = {
        "period": "2023", "segments": [], "customers": [], "geographic": [],
    }
    stub = tmp_path / "stub.json"
    stub.write_text(json.dumps(payload), encoding="utf-8")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(_gt_payload(payload)), encoding="utf-8")
    html = tmp_path / "report.html"
    html.write_text("<html><body><p>본문</p></body></html>", encoding="utf-8")
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(stub))

    result = runner.invoke(app, [
        "eval", "e5",
        "--html-file", str(html),
        "--period", "2023",
        "--ground-truth", str(gt),
        "--runs", "1",
    ])
    assert result.exit_code == 0
    # dir 생성 안 됨 (no side effect)
    assert not (tmp_path / "runs").exists()
