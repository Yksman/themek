"""dart parser-* 명령 단위 테스트."""
from pathlib import Path
from typer.testing import CliRunner

from themek.cli import app
from themek.dart.learned_patterns import (
    LearnedPatterns, save_learned_patterns, load_learned_patterns,
)
from themek.dart.pattern_learning import save_proposals, Proposal


runner = CliRunner()


def test_parser_stats_outputs_counts(monkeypatch, tmp_path):
    learned_path = tmp_path / "learned.json"
    proposals_path = tmp_path / "proposals.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "a_2023.html").write_text("<p>x</p>", encoding="utf-8")
    (fixtures_dir / "b_2023.html").write_text("<p>x</p>", encoding="utf-8")

    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern(
        "overview", regex="회사.{0,3}개황", source="learned",
        samples=["x"], confirmed_count=3,
    )
    save_learned_patterns(learned_path, lp)

    save_proposals(proposals_path, [
        Proposal(
            target="products", candidate_regex="영업.{0,3}현황",
            sample_headers=["영업 현황"], observed_count=2,
        ),
    ])

    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(learned_path))
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(proposals_path))
    monkeypatch.setenv("THEMEK_FIXTURES_DIR", str(fixtures_dir))

    result = runner.invoke(app, ["dart", "parser-stats"])
    assert result.exit_code == 0, result.stdout
    assert "fixtures: 2" in result.stdout
    assert "learned" in result.stdout
    assert "proposals" in result.stdout


def test_parser_learn_applies_pending_proposals(monkeypatch, tmp_path):
    learned_path = tmp_path / "learned.json"
    proposals_path = tmp_path / "proposals.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()

    save_proposals(proposals_path, [
        Proposal(
            target="overview", candidate_regex="회사.{0,3}개황",
            sample_headers=["회사의 개황"], observed_count=3,
            source_fixtures=["a", "b", "c"],
        ),
    ])

    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(learned_path))
    monkeypatch.setenv("THEMEK_PROPOSALS_PATH", str(proposals_path))
    monkeypatch.setenv("THEMEK_FIXTURES_DIR", str(fixtures_dir))

    result = runner.invoke(app, ["dart", "parser-learn"])
    assert result.exit_code == 0, result.stdout
    assert "applied 1" in result.stdout


def test_parser_consolidate_dedups_identical_regex(monkeypatch, tmp_path):
    learned_path = tmp_path / "learned.json"
    lp = LearnedPatterns.from_baseline()
    lp.add_target_pattern(
        "overview", regex="회사.{0,3}개황", source="learned",
        samples=["a"], confirmed_count=3,
    )
    lp.add_target_pattern(
        "overview", regex="회사.{0,3}개황", source="learned",
        samples=["b"], confirmed_count=2,
    )
    save_learned_patterns(learned_path, lp)

    monkeypatch.setenv("THEMEK_LEARNED_PATTERNS_PATH", str(learned_path))
    result = runner.invoke(app, ["dart", "parser-consolidate"])
    assert result.exit_code == 0, result.stdout
    lp2 = load_learned_patterns(learned_path)
    overview = lp2.target_patterns("overview")
    learned_only = [p for p in overview if p.get("source") == "learned"]
    assert len(learned_only) == 1
    assert "a" in learned_only[0].get("samples", [])
    assert "b" in learned_only[0].get("samples", [])
