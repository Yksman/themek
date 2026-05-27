"""learned_header_patterns.json — schema + loader + merge."""
import pytest

from themek.dart.learned_patterns import (
    LearnedPatterns, load_learned_patterns, save_learned_patterns,
)


def test_load_returns_baseline_when_file_missing(tmp_path):
    p = tmp_path / "missing.json"
    lp = load_learned_patterns(p)
    assert isinstance(lp, LearnedPatterns)
    assert lp.target_patterns("overview")
    assert lp.target_patterns("products")
    assert lp.target_patterns("revenue")
    assert lp.prefix_patterns()


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "learned.json"
    lp = load_learned_patterns(p)
    lp.add_target_pattern(
        "overview", regex=r"회사.{0,3}개황",
        source="learned", samples=["회사의 개황"],
        confirmed_count=3, fixtures_validated=["005930_2023"],
    )
    save_learned_patterns(p, lp)
    lp2 = load_learned_patterns(p)
    overview_patterns = lp2.target_patterns("overview")
    assert any(pat["regex"] == "회사.{0,3}개황" for pat in overview_patterns)


def test_target_patterns_returns_baseline_plus_learned(tmp_path):
    p = tmp_path / "learned.json"
    lp = load_learned_patterns(p)
    baseline_n = len(lp.target_patterns("overview"))
    lp.add_target_pattern(
        "overview", regex="신규.패턴",
        source="learned", samples=["신규 패턴"], confirmed_count=3,
    )
    assert len(lp.target_patterns("overview")) == baseline_n + 1


def test_invalid_target_raises():
    lp = LearnedPatterns.from_baseline()
    with pytest.raises(ValueError):
        lp.add_target_pattern(
            "invalid_target", regex="x",
            source="learned", samples=["x"], confirmed_count=3,
        )


def test_invalid_regex_raises():
    lp = LearnedPatterns.from_baseline()
    with pytest.raises(ValueError, match="invalid regex"):
        lp.add_target_pattern(
            "overview", regex="[(broken",
            source="learned", samples=["x"], confirmed_count=3,
        )
