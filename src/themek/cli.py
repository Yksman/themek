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
from themek.krx.client import KrxClient
from themek.krx.sync import sync_listed_stocks, fetch_listed_universe

app = typer.Typer(help="themek — 한국 테마주 ontology CLI")
query_app = typer.Typer(help="Run competency queries")
app.add_typer(query_app, name="query")
eval_app = typer.Typer(help="Run extraction quality evaluation")
app.add_typer(eval_app, name="eval")
dart_app = typer.Typer(help="DART OpenAPI 명령")
app.add_typer(dart_app, name="dart")
krx_app = typer.Typer(help="KRX 상장사 sync 명령")
app.add_typer(krx_app, name="krx")

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


backfill_app = typer.Typer(help="다종목 backfill 명령")
dart_app.add_typer(backfill_app, name="backfill")

DEFAULT_UNIVERSE_FILE = "data/universe/active.txt"


@backfill_app.command("init")
def backfill_init_cmd(
    universe_file: Optional[Path] = typer.Option(
        None, "--universe-file",
        help="corp_code 1줄당 1개. # 주석 허용. --from-stocks와 배타.",
    ),
    from_stocks: bool = typer.Option(
        False, "--from-stocks",
        help="Stock 테이블의 active 종목을 universe로 사용 (--universe-file 대체).",
    ),
    include_delisted: bool = typer.Option(
        False, "--include-delisted",
        help="--from-stocks 사용 시 delisted_at set된 종목도 포함.",
    ),
    periods: str = typer.Option(
        ..., "--periods",
        help="YYYY 단일 또는 YYYY:YYYY 범위",
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="dry-run 끄고 실제 row 생성",
    ),
):
    """universe × periods → BackfillTarget row 생성 (dry-run 기본)."""
    from sqlalchemy import select

    from themek.dart.backfill import (
        enumerate_targets, enumerate_targets_from_corps,
    )
    from themek.dart.universe import load_universe_from_stocks
    from themek.db.models import BackfillTarget

    if from_stocks and universe_file is not None:
        typer.echo(
            "Error: --from-stocks와 --universe-file 동시 사용 불가",
            err=True,
        )
        raise typer.Exit(code=1)

    if from_stocks:
        with _session() as sess:
            corps = load_universe_from_stocks(
                sess, include_delisted=include_delisted,
            )
        specs = enumerate_targets_from_corps(
            corp_codes=corps, periods=periods,
        )
        universe_label = (
            f"Stock table ({'incl. delisted' if include_delisted else 'active only'})"
        )
    else:
        uf = universe_file or Path(DEFAULT_UNIVERSE_FILE)
        specs = enumerate_targets(universe_file=uf, periods=periods)
        universe_label = str(uf)

    n_targets = len(specs)
    n_calls = n_targets * 2
    est_cost = n_targets * 0.25

    typer.echo("=== Backfill Init Dry-Run ===")
    typer.echo(f"universe: {universe_label}")
    typer.echo(f"periods: {periods}")
    typer.echo(f"예상 처리: {n_targets} target")
    typer.echo(f"예상 DART 호출: ~{n_calls} (limit 38000/day)")
    typer.echo(f"예상 LLM 비용: ~${est_cost:.2f} (평균 단가 기준)")

    if not confirm:
        typer.echo("\n--confirm 추가 시 실제 BackfillTarget row 생성.")
        return

    inserted, skipped = 0, 0
    with _session() as sess:
        for spec in specs:
            existing = sess.scalar(
                select(BackfillTarget)
                .where(BackfillTarget.corp_code == spec.corp_code)
                .where(BackfillTarget.period == spec.period)
            )
            if existing is not None:
                skipped += 1
                continue
            sess.add(BackfillTarget(
                corp_code=spec.corp_code, period=spec.period, status="pending",
            ))
            inserted += 1
        sess.commit()
    typer.echo(f"\ninserted={inserted} skipped (already exists)={skipped}")


@backfill_app.command("run")
def backfill_run_cmd(
    max_targets: int = typer.Option(500, "--max-targets"),
    daily_cap: Optional[int] = typer.Option(None, "--daily-cap"),
    reset_stale_minutes: int = typer.Option(180, "--reset-stale-minutes"),
    purge_zip: bool = typer.Option(
        False, "--purge-zip-after-extract",
        help="business.html 추출 후 document.zip 삭제 (디스크 절약)",
    ),
):
    """pending BackfillTarget을 한도 안에서 처리."""
    from themek.dart.backfill import run_batch
    from themek.dart.rate_budget import RateBudget, RateBudgetExceeded

    s = get_settings()
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    budget = RateBudget(
        daily_cap=daily_cap or 38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )
    extractor = _stub_extractor_from_env()
    try:
        with _session() as sess:
            summary = run_batch(
                session=sess, client=client, cache=cache,
                rate_budget=budget, extractor=extractor,
                max_targets=max_targets,
                reset_stale_minutes=reset_stale_minutes,
                purge_zip=purge_zip,
            )
    except RateBudgetExceeded as e:
        typer.echo(f"Budget exceeded: {e}", err=True)
        raise typer.Exit(code=6)

    typer.echo(
        f"processed={summary.processed} done={summary.done} "
        f"skipped={summary.skipped} failed={summary.failed} "
        f"pending_remaining={summary.pending_remaining} "
        f"budget_remaining={summary.budget_remaining}"
    )


@backfill_app.command("status")
def backfill_status_cmd(
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="escalation 분포 + 비용 top-10 표시",
    ),
):
    """BackfillTarget status 분포 + 누적 LLM 비용."""
    from sqlalchemy import select, func, desc

    from themek.db.models import BackfillTarget

    with _session() as sess:
        rows = sess.execute(
            select(BackfillTarget.status, func.count())
            .group_by(BackfillTarget.status)
        ).all()
        counts = {status: n for status, n in rows}
        total = sum(counts.values())
        total_cost = sess.scalar(
            select(func.sum(BackfillTarget.cost_estimate_usd))
        ) or 0

    typer.echo("=== BackfillTarget summary ===")
    for status in ("pending", "in_progress", "done", "failed", "skipped"):
        typer.echo(f"  {status:12s}: {counts.get(status, 0):6d}")
    typer.echo(f"  {'total':12s}: {total:6d}")
    typer.echo(f"\nTotal LLM cost (done): ${float(total_cost):.2f}")

    if not verbose:
        return

    with _session() as sess:
        esc_rows = sess.execute(
            select(BackfillTarget.escalation_level, func.count())
            .where(BackfillTarget.status == "done")
            .group_by(BackfillTarget.escalation_level)
        ).all()
        typer.echo("\n=== Escalation distribution (done) ===")
        for level, n in esc_rows:
            typer.echo(f"  {str(level):12s}: {n:6d}")

        top = sess.execute(
            select(
                BackfillTarget.corp_code, BackfillTarget.period,
                BackfillTarget.input_chars, BackfillTarget.cost_estimate_usd,
            )
            .where(BackfillTarget.status == "done")
            .order_by(desc(BackfillTarget.cost_estimate_usd))
            .limit(10)
        ).all()
        typer.echo("\n=== Top 10 by cost ===")
        for cc, p, ic, cost in top:
            typer.echo(
                f"  {cc} {p}: input_chars={ic} cost=${float(cost or 0):.4f}"
            )


@dart_app.command("incremental")
def dart_incremental_cmd(
    since: str = typer.Option("yesterday", "--since"),
    until: str = typer.Option("today", "--until"),
    universe_file: Path = typer.Option(
        DEFAULT_UNIVERSE_FILE, "--universe-file",
        help="active.txt 경로 (backfill과 동일)",
    ),
    purge_zip: bool = typer.Option(False, "--purge-zip-after-extract"),
):
    """Layer B: scan → universe filter → 신규만 ingest."""
    from datetime import timedelta

    from themek.dart.incremental import run_incremental
    from themek.dart.universe import load_universe
    from themek.dart.rate_budget import RateBudget

    s = get_settings()
    today = date.today()
    since_d = (
        today - timedelta(days=1) if since == "yesterday"
        else date.fromisoformat(since)
    )
    until_d = (
        today if until == "today" else date.fromisoformat(until)
    )

    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    universe = set(load_universe(universe_file))
    budget = RateBudget(
        daily_cap=38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )
    extractor = _stub_extractor_from_env()

    with _session() as sess:
        result = run_incremental(
            client=client, cache=cache, session=sess,
            universe=universe, rate_budget=budget, extractor=extractor,
            since=since_d, until=until_d,
            purge_zip=purge_zip,
        )
    typer.echo(
        f"scanned={result.scanned} in_universe={result.in_universe} "
        f"already_ingested={result.already_ingested} "
        f"to_ingest={result.to_ingest} ingested={result.ingested} "
        f"failed={len(result.failed)}"
    )


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


@krx_app.command("sync-listed")
def krx_sync_listed_cmd(
    auto_enroll: bool = typer.Option(
        False, "--auto-enroll",
        help="신규 상장 종목마다 BackfillTarget pending row 자동 생성",
    ),
    periods: Optional[str] = typer.Option(
        None, "--periods",
        help="--auto-enroll 사용 시 BackfillTarget 생성 period 범위 (예: 2023:2024)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="KRX 호출까지만 하고 DB 미변경, ticker 수만 출력",
    ),
):
    """KOSPI/KOSDAQ 상장사를 Stock 테이블에 sync."""
    from sqlalchemy import select

    from themek.db.models import BackfillTarget, Stock
    from themek.dart.backfill import _parse_periods

    try:
        _, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    client = KrxClient()

    if dry_run:
        listed = fetch_listed_universe(client)
        typer.echo(
            f"[dry-run] KOSPI/KOSDAQ {len(listed)} listed tickers "
            f"(KOSPI={sum(1 for v in listed.values() if v == 'KOSPI')}, "
            f"KOSDAQ={sum(1 for v in listed.values() if v == 'KOSDAQ')})"
        )
        return

    with _session() as sess:
        r = sync_listed_stocks(
            sess, krx_client=client, cache=cache, today=date.today(),
        )
    typer.echo(
        f"added={len(r.added)} delisted={len(r.delisted)} "
        f"updated={len(r.updated)} unlinked={len(r.unlinked)}"
    )

    if auto_enroll and r.added:
        if not periods:
            typer.echo(
                "Warning: --auto-enroll 사용 시 --periods 필요 — skip",
                err=True,
            )
            return
        period_list = _parse_periods(periods)
        inserted = 0
        with _session() as sess:
            for ticker in r.added:
                stock = sess.get(Stock, ticker)
                if stock is None:
                    continue
                for p in period_list:
                    existing = sess.scalar(
                        select(BackfillTarget)
                        .where(BackfillTarget.corp_code == stock.issued_by_id)
                        .where(BackfillTarget.period == p)
                    )
                    if existing is not None:
                        continue
                    sess.add(BackfillTarget(
                        corp_code=stock.issued_by_id, period=p,
                        status="pending",
                    ))
                    inserted += 1
            sess.commit()
        typer.echo(f"auto-enrolled {inserted} new BackfillTarget rows")


if __name__ == "__main__":
    app()
