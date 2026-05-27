"""ingest cache HTML → tests/fixtures/dart_variants/ mirror."""
from __future__ import annotations
import json
import shutil
from pathlib import Path


def mirror_fixture(
    *, cache_html: Path, ticker: str, period: str, fixtures_dir: Path,
) -> tuple[Path, Path]:
    """cache HTML을 fixtures_dir로 복사하고 expected_headers JSON 생성.

    Returns: (mirrored_html, headers_json)
    """
    from themek.dart.parser import extract_business_sections

    fixtures_dir = Path(fixtures_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    dst_html = fixtures_dir / f"{ticker}_{period}.html"
    dst_headers = fixtures_dir / f"{ticker}_{period}_headers.json"

    src_bytes = Path(cache_html).read_bytes()
    if dst_html.exists() and dst_html.read_bytes() == src_bytes:
        pass
    else:
        shutil.copy2(cache_html, dst_html)

    html = Path(cache_html).read_text(encoding="utf-8")
    _, res = extract_business_sections(html, llm_fallback=None)
    expected = dict(res.regex_matched)
    for t in res.invalid_targets:
        expected.pop(t, None)
    dst_headers.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dst_html, dst_headers
