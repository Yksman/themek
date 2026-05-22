"""themek CLI entry point."""
from __future__ import annotations
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional
import typer
from sqlalchemy.orm import Session
from themek.db.engine import make_engine, make_session_factory
from themek.seeds import seed_basic
from themek.dart.parser import extract_business_content
from themek.ingest.business_report import ingest_business_report
from themek.query.e5 import query_e5
from themek.query.synthesize import synthesize_e5_answer
from themek.llm.schemas import BusinessExtraction

app = typer.Typer(help="themek — 한국 테마주 ontology CLI")
query_app = typer.Typer(help="Run competency queries")
app.add_typer(query_app, name="query")


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


if __name__ == "__main__":
    app()
