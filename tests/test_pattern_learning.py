"""pattern_learning — propose / validate / record / apply."""
import json
from pathlib import Path

from themek.dart.pattern_learning import (
    MIN_KEYWORD_LENGTH, Proposal,
    apply_ready_proposals, load_proposals, propose_keyword_pattern,
    record_proposal, save_proposals, validate_pattern_against_fixtures,
)
from themek.dart.learned_patterns import load_learned_patterns


# ---------------- propose ----------------

def test_propose_extracts_core_keyword():
    pat = propose_keyword_pattern("(제조서비스업)사업의 개요", target="overview")
    assert pat is not None
    assert "사업" in pat or "개요" in pat


def test_propose_rejects_too_short():
    pat = propose_keyword_pattern("이", target="overview")
    assert pat is None


def test_propose_rejects_common_filler():
    pat = propose_keyword_pattern("등 및", target="overview")
    assert pat is None


def test_propose_normalizes_whitespace_to_flexible():
    pat = propose_keyword_pattern("회사의 개황", target="overview")
    assert pat is not None
    assert "회사" in pat
    assert "개황" in pat


# ---------------- validate ----------------

def test_validate_pattern_passes_when_no_fixtures(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    ok, reasons = validate_pattern_against_fixtures(
        target="overview", regex="회사.{0,3}개황",
        fixtures_dir=fixtures_dir,
    )
    assert ok
    assert reasons == []


def test_validate_pattern_rejects_when_breaks_existing(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "005930_2023.html").write_text(
        "<p>1. 사업의 개요</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>2. 주요 제품 및 서비스</p><p>본문" + "ㅇ" * 400 + "</p>"
        "<p>3. 매출 및 수주상황</p><p>본문" + "ㅇ" * 400 + "</p>",
        encoding="utf-8",
    )
    (fixtures_dir / "005930_2023_headers.json").write_text(json.dumps({
        "overview": "사업의 개요",
        "products": "주요 제품 및 서비스",
        "revenue": "매출 및 수주상황",
    }), encoding="utf-8")
    # 너무 broad — `매` 단독 매칭이 overview로 가서 충돌
    ok, reasons = validate_pattern_against_fixtures(
        target="overview", regex="매",
        fixtures_dir=fixtures_dir,
    )
    assert ok is False
    assert reasons


# ---------------- record ----------------

def test_record_creates_new_proposal(tmp_path):
    p = tmp_path / "proposals.json"
    record_proposal(
        p, target="overview", candidate_regex="회사.{0,3}개황",
        sample_header="회사의 개황", source_fixture="068270_2023",
    )
    proposals = load_proposals(p)
    assert len(proposals) == 1
    assert proposals[0].target == "overview"
    assert proposals[0].candidate_regex == "회사.{0,3}개황"
    assert proposals[0].observed_count == 1
    assert "회사의 개황" in proposals[0].sample_headers
    assert "068270_2023" in proposals[0].source_fixtures


def test_record_increments_existing(tmp_path):
    p = tmp_path / "proposals.json"
    for fx in ("068270_2023", "035420_2023", "036570_2023"):
        record_proposal(
            p, target="overview", candidate_regex="회사.{0,3}개황",
            sample_header="회사의 개황", source_fixture=fx,
        )
    proposals = load_proposals(p)
    assert len(proposals) == 1
    assert proposals[0].observed_count == 3
    assert len(proposals[0].source_fixtures) == 3


# ---------------- apply ----------------

def test_apply_promotes_n3_proposal_to_learned(tmp_path):
    proposals_path = tmp_path / "proposals.json"
    learned_path = tmp_path / "learned.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()

    for fx in ("a", "b", "c"):
        record_proposal(
            proposals_path, target="overview",
            candidate_regex="회사.{0,3}개황",
            sample_header="회사의 개황", source_fixture=fx,
        )

    applied = apply_ready_proposals(
        proposals_path=proposals_path,
        learned_path=learned_path,
        fixtures_dir=fixtures_dir,
        min_confirmed=3,
    )
    assert len(applied) == 1
    assert applied[0].target == "overview"

    lp = load_learned_patterns(learned_path)
    assert any(
        p["regex"] == "회사.{0,3}개황" and p.get("source") == "learned"
        for p in lp.target_patterns("overview")
    )
    remaining = load_proposals(proposals_path)
    assert remaining == []


def test_apply_skips_proposal_under_threshold(tmp_path):
    proposals_path = tmp_path / "proposals.json"
    learned_path = tmp_path / "learned.json"
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    record_proposal(
        proposals_path, target="overview",
        candidate_regex="신규.{0,3}패턴", sample_header="신규 패턴",
        source_fixture="a",
    )
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    assert applied == []
    assert len(load_proposals(proposals_path)) == 1
