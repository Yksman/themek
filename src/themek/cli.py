"""themek CLI entry point."""
from __future__ import annotations
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import typer
from sqlalchemy.orm import Session
from themek.config import get_settings
from themek.db.engine import make_engine, make_session_factory
from themek.seeds import seed_basic
from themek.dart.parser import (
    extract_business_content,
    extract_business_sections,
    llm_classify_headers,
)
from themek.dart.client import DartClient, DartAuthError, DartApiError
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import sync_corp_master, lookup_corp_code
from themek.db.models import Corporation
from themek.dart.fetch import (
    fetch_business_report_html, BusinessReportFetchError,
)
from themek.ingest.business_report import ingest_business_report
from themek.query.e5 import query_e5
from themek.query.synthesize import synthesize_e5_answer
from themek.llm.schemas import BusinessExtraction
from themek.llm.claude_cli import CallResult
from themek.eval.e5 import (
    evaluate_e5, load_ground_truth, format_eval_result_text,
    aggregate_runs, format_aggregated_result_text,
)

app = typer.Typer(help="themek — 한국 테마주 ontology CLI")
query_app = typer.Typer(help="Run competency queries")
app.add_typer(query_app, name="query")
eval_app = typer.Typer(help="Run extraction quality evaluation")
app.add_typer(eval_app, name="eval")
dart_app = typer.Typer(help="DART OpenAPI 명령")
app.add_typer(dart_app, name="dart")

DEFAULT_LEARNED_PATTERNS_PATH = "data/dart/learned_header_patterns.json"
DEFAULT_PROPOSALS_PATH = "data/dart/pattern_proposals.json"
DEFAULT_FIXTURES_DIR = "tests/fixtures/dart_variants"


def _session() -> Session:
    factory = make_session_factory(make_engine())
    return factory()


@app.command()
def seed():
    """샘플 데이터 시드."""
    with _session() as s:
        seed_basic(s)
        s.commit()
    typer.echo("Seeded 3 stocks, 3 corporations, sectors, regions.")


def _stub_extractor_from_env():
    path = os.environ.get("THEMEK_STUB_EXTRACTION_FILE")
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    extraction = BusinessExtraction.model_validate(payload)

    def stub(text: str, period_hint: str) -> BusinessExtraction:
        return extraction

    return stub


@app.command()
def ingest(
    rcept_no: str = typer.Option(..., "--rcept-no"),
    corp: str = typer.Option(..., "--corp", help="DART corporation code (8자리)"),
    report_type: str = typer.Option(..., "--report-type",
                                    help="사업보고서|반기보고서|분기보고서"),
    period: str = typer.Option(..., "--period", help="예: 2023, 2024Q3"),
    filing_date: str = typer.Option(..., "--filing-date", help="YYYY-MM-DD"),
    html_file: Path = typer.Option(..., "--html-file",
                                   help="DART 사업보고서 HTML 파일"),
    url: Optional[str] = typer.Option(None, "--url"),
):
    """사업보고서 1건을 ingest."""
    html = html_file.read_text(encoding="utf-8")
    text = extract_business_content(html)
    extractor = _stub_extractor_from_env()
    with _session() as s:
        kwargs = dict(
            dart_rcept_no=rcept_no,
            corporation_id=corp,
            report_type=report_type,
            period=period,
            filing_date=date.fromisoformat(filing_date),
            raw_text_excerpt=text,
            url=url,
        )
        if extractor is not None:
            kwargs["extractor"] = extractor
        ingest_business_report(s, **kwargs)
        s.commit()
    typer.echo(f"Ingested report {rcept_no}")


@query_app.command("e5")
def query_e5_cmd(ticker: str = typer.Option(..., "--ticker")):
    """E5: 이 회사 뭐 만들어?"""
    with _session() as s:
        try:
            result = query_e5(s, ticker=ticker)
        except LookupError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1)
    typer.echo(synthesize_e5_answer(result))


def _format_section_log(resolution) -> str:
    matched_regex = sorted(resolution.regex_matched)
    matched_llm = sorted(t for t, v in resolution.llm_decision.items()
                         if v is not None)
    body_chars_str = ", ".join(
        f"{t}={n}" for t, n in sorted(resolution.body_chars_per_target.items())
    ) or "-"
    lines = [
        f"escalation_level: {resolution.escalation_level}",
        f"regex matched:    {', '.join(matched_regex) or '-'}",
        f"llm fallback:     {'called' if resolution.llm_called else 'not called'}",
        f"llm matched:      {', '.join(matched_llm) or '-'}",
        f"invalid_targets:  {', '.join(resolution.invalid_targets) or '-'}",
        f"body_chars:       {body_chars_str}",
        f"skipped:          {', '.join(resolution.skipped) or '-'}",
        f"output chars:     {resolution.output_chars}",
    ]
    return "\n".join(lines)


@eval_app.command("e5")
def eval_e5_cmd(
    html_file: Path = typer.Option(..., "--html-file"),
    period: str = typer.Option(..., "--period"),
    ground_truth: Path = typer.Option(..., "--ground-truth"),
    runs: int = typer.Option(1, "--runs", min=1, max=20),
    save_runs: Optional[Path] = typer.Option(None, "--save-runs"),
):
    """E5 추출 품질을 ground truth와 비교해 점수표 출력."""
    try:
        truth, metadata = load_ground_truth(ground_truth)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    html = html_file.read_text(encoding="utf-8")
    stub = _stub_extractor_from_env()

    text, section_resolution = extract_business_sections(
        html, llm_fallback=None if stub else llm_classify_headers,
    )

    eval_runs: list = []
    usages: list[CallResult] = []
    raw_extractions: list = []
    for _ in range(runs):
        extraction, call = _run_extractor_with_usage(text, period, stub)
        eval_runs.append(evaluate_e5(extraction, truth))
        usages.append(call)
        raw_extractions.append(extraction)

    section_log = _format_section_log(section_resolution)

    agg = None
    if runs == 1:
        typer.echo(format_eval_result_text(
            eval_runs[0],
            metadata=metadata,
            ground_truth_path=str(ground_truth),
            html_path=str(html_file),
        ))
    else:
        agg = aggregate_runs(eval_runs, usages)
        typer.echo(format_aggregated_result_text(
            agg,
            metadata=metadata,
            ground_truth_path=str(ground_truth),
            html_path=str(html_file),
            section_log=section_log,
        ))

    if save_runs is not None:
        _persist_runs(
            save_runs, metadata=metadata,
            section_resolution=section_resolution,
            usages=usages, extractions=raw_extractions,
            eval_results=eval_runs, agg=agg,
        )


def _run_extractor_with_usage(text: str, period: str, stub_fn):
    if stub_fn is not None:
        return stub_fn(text, period), CallResult(
            text="", input_tokens=0, output_tokens=0,
            cost_usd=0.0, duration_ms=0, raw_payload={},
        )
    from themek.llm.claude_cli import call_claude, extract_json_block
    from themek.llm.prompts import build_business_extraction_prompt
    prompt = build_business_extraction_prompt(text, period_hint=period)
    call = call_claude(prompt)
    payload = extract_json_block(call.text)
    extraction = BusinessExtraction.model_validate(payload)
    return extraction, call


def _persist_runs(
    base: Path, *, metadata: dict, section_resolution,
    usages: list[CallResult], extractions: list,
    eval_results: list, agg,
) -> None:
    from dataclasses import asdict
    ticker = metadata.get("ticker", "unknown")
    period = metadata.get("period", "unknown")
    target = base / f"{ticker}_{period}"
    target.mkdir(parents=True, exist_ok=True)

    for i, (extraction, usage, eval_r) in enumerate(
        zip(extractions, usages, eval_results), start=1,
    ):
        run_path = target / f"run_{i}.json"
        run_path.write_text(json.dumps({
            "run_index": i,
            "parsed_extraction": extraction.model_dump(),
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": usage.cost_usd,
                "duration_ms": usage.duration_ms,
            },
            "eval_result": asdict(eval_r),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    sec_path = target / "section_resolution.json"
    sec_path.write_text(json.dumps(
        asdict(section_resolution), ensure_ascii=False, indent=2,
    ), encoding="utf-8")

    summary_path = target / "summary.json"
    if agg is None:
        summary = {
            "n_runs": 1,
            "segment_recall_mean": eval_results[0].segment_recall,
            "total_input_tokens": usages[0].input_tokens,
            "total_output_tokens": usages[0].output_tokens,
            "total_cost_usd": usages[0].cost_usd,
            "total_duration_ms": usages[0].duration_ms,
        }
    else:
        summary = asdict(agg)
        summary.pop("runs", None)
        summary.pop("usages", None)
        summary["n_runs"] = len(eval_results)
    summary_path.write_text(json.dumps(
        summary, ensure_ascii=False, indent=2, default=str,
    ), encoding="utf-8")


def _dart_client_and_cache() -> tuple[DartClient, DartCache]:
    s = get_settings()
    client = DartClient(
        api_key=s.dart_api_key, timeout_sec=s.dart_http_timeout_sec,
    )
    cache = DartCache(base_dir=s.dart_cache_dir)
    return client, cache


@dart_app.command("sync-corp")
def dart_sync_corp_cmd():
    """corp_code 마스터를 DART에서 받아 캐시."""
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        n = sync_corp_master(client, cache)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)
    typer.echo(f"synced {n} corporations to {cache.corp_master_path}")


@dart_app.command("fetch")
def dart_fetch_cmd(
    ticker: str = typer.Option(..., "--ticker"),
    period: str = typer.Option(..., "--period", help="연도 (예: 2023)"),
):
    """ticker+period → 사업보고서 HTML을 캐시에 저장 후 경로 출력."""
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        corp_code = lookup_corp_code(cache, ticker=ticker)
    except LookupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        html_path, rcept_no = fetch_business_report_html(
            client, cache,
            ticker=ticker, year=int(period), corp_code=corp_code,
        )
    except BusinessReportFetchError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=5)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)
    typer.echo(str(html_path))


def _ensure_corporation(session: Session, *, corp_code: str,
                        cache: DartCache) -> None:
    existing = session.get(Corporation, corp_code)
    if existing is not None:
        return
    name_ko = corp_code
    rows = cache.load_corp_master()
    if rows is not None:
        for r in rows:
            if r.get("corp_code") == corp_code:
                name_ko = r.get("corp_name") or corp_code
                break
    session.add(Corporation(dart_code=corp_code, name_ko=name_ko))
    session.flush()


def _learn_from_resolution(
    section_resolution, *, ticker: str, period: str,
) -> None:
    """ingest 후 learned_samples를 proposal에 누적 + N=3 promote 시도."""
    from themek.dart.pattern_learning import (
        propose_keyword_pattern, record_proposal, apply_ready_proposals,
    )
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))

    for sample in section_resolution.learned_samples:
        regex = propose_keyword_pattern(
            sample["header_text"], target=sample["target"],
        )
        if regex is None:
            continue
        record_proposal(
            proposals_path, target=sample["target"],
            candidate_regex=regex, sample_header=sample["header_text"],
            source_fixture=f"{ticker}_{period}",
        )
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    if applied:
        typer.echo(
            f"[parser-learn] applied {len(applied)} new patterns: "
            f"{[(p.target, p.candidate_regex) for p in applied]}"
        )


@dart_app.command("ingest")
def dart_ingest_cmd(
    ticker: str = typer.Option(..., "--ticker"),
    period: str = typer.Option(..., "--period"),
    report_type: str = typer.Option("사업보고서", "--report-type"),
):
    """dart fetch + 기존 ingest_business_report 통합."""
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        corp_code = lookup_corp_code(cache, ticker=ticker)
    except LookupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        html_path, rcept_no = fetch_business_report_html(
            client, cache,
            ticker=ticker, year=int(period), corp_code=corp_code,
        )
    except BusinessReportFetchError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=5)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)

    html = html_path.read_text(encoding="utf-8")
    extractor = _stub_extractor_from_env()
    # Section filter LLM은 extractor stub과 독립. 학습 hook을 위해 항상 활성.
    text, section_resolution = extract_business_sections(
        html, llm_fallback=llm_classify_headers,
    )

    typer.echo(
        f"[section_filter] escalation={section_resolution.escalation_level} "
        f"output_chars={section_resolution.output_chars} "
        f"invalid={section_resolution.invalid_targets}"
    )

    try:
        filing_dt = datetime.strptime(rcept_no[:8], "%Y%m%d").date()
    except ValueError:
        filing_dt = date.today()
    with _session() as s:
        _ensure_corporation(s, corp_code=corp_code, cache=cache)
        kwargs = dict(
            dart_rcept_no=rcept_no,
            corporation_id=corp_code,
            report_type=report_type,
            period=period,
            filing_date=filing_dt,
            raw_text_excerpt=text,
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        )
        if extractor is not None:
            kwargs["extractor"] = extractor
        ingest_business_report(s, **kwargs)
        s.commit()

    # Fixture mirror + learning hook (post-ingest)
    try:
        from themek.dart.fixture_mirror import mirror_fixture
        fixtures_dir = Path(os.environ.get(
            "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
        ))
        mirror_fixture(
            cache_html=html_path, ticker=ticker, period=period,
            fixtures_dir=fixtures_dir,
        )
    except Exception as e:  # noqa: BLE001 — mirror failure non-fatal
        typer.echo(f"[mirror] skipped: {e}")

    try:
        _learn_from_resolution(
            section_resolution, ticker=ticker, period=period,
        )
    except Exception as e:  # noqa: BLE001 — learn failure non-fatal
        typer.echo(f"[parser-learn] skipped: {e}")

    typer.echo(f"Ingested report {rcept_no}")


@dart_app.command("parser-stats")
def dart_parser_stats_cmd():
    """학습 누적 상태 출력."""
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    from themek.dart.learned_patterns import load_learned_patterns
    from themek.dart.pattern_learning import load_proposals
    lp = load_learned_patterns(learned_path)
    proposals = load_proposals(proposals_path)
    fixtures = (
        sorted(fixtures_dir.glob("*.html")) if fixtures_dir.exists() else []
    )
    lines = [
        f"fixtures: {len(fixtures)}",
        f"learned patterns:",
    ]
    for t in ("overview", "products", "revenue"):
        learned_count = sum(
            1 for p in lp.target_patterns(t) if p.get("source") == "learned"
        )
        baseline_count = sum(
            1 for p in lp.target_patterns(t) if p.get("source") == "code_baseline"
        )
        lines.append(
            f"  {t}: baseline={baseline_count}, learned={learned_count}"
        )
    lines.append(f"proposals (pending): {len(proposals)}")
    for pr in proposals[:10]:
        lines.append(
            f"  - {pr.target}: {pr.candidate_regex} "
            f"(observed {pr.observed_count}, fixtures={pr.source_fixtures})"
        )
    typer.echo("\n".join(lines))


@dart_app.command("parser-learn")
def dart_parser_learn_cmd():
    """누적 proposal 중 N=3 도달 항목을 learned로 promote."""
    from themek.dart.pattern_learning import apply_ready_proposals
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    typer.echo(f"applied {len(applied)} new patterns")
    for pr in applied:
        typer.echo(f"  - {pr.target}: {pr.candidate_regex}")


@dart_app.command("parser-consolidate")
def dart_parser_consolidate_cmd():
    """학습 패턴 머지·dedup."""
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    from themek.dart.learned_patterns import (
        load_learned_patterns, save_learned_patterns, consolidate,
    )
    lp = load_learned_patterns(learned_path)
    before = sum(len(lp.target_patterns(t))
                 for t in ("overview", "products", "revenue"))
    lp = consolidate(lp)
    save_learned_patterns(learned_path, lp)
    after = sum(len(lp.target_patterns(t))
                for t in ("overview", "products", "revenue"))
    typer.echo(f"consolidated: {before} → {after} patterns")


if __name__ == "__main__":
    app()
