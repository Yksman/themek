"""universe.py: active.txt에서 corp_code list 로드."""
import pytest

from themek.dart.universe import load_universe


def test_load_universe_basic(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text("00126380\n00164742\n01133217\n", encoding="utf-8")
    assert load_universe(p) == ["00126380", "00164742", "01133217"]


def test_load_universe_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text(
        "# Header comment\n"
        "00126380\n"
        "\n"
        "  # indented comment\n"
        "00164742  \n"
        "\n",
        encoding="utf-8",
    )
    assert load_universe(p) == ["00126380", "00164742"]


def test_load_universe_dedupe(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text("00126380\n00164742\n00126380\n", encoding="utf-8")
    assert load_universe(p) == ["00126380", "00164742"]


def test_load_universe_validates_corp_code_format(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text("12345\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corp_code"):
        load_universe(p)


def test_load_universe_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_universe(tmp_path / "missing.txt")


def test_load_universe_inline_comment(tmp_path):
    """인라인 주석 허용 (runbook 예시 패턴)."""
    p = tmp_path / "active.txt"
    p.write_text(
        "00126380   # 삼성전자\n"
        "00164742   # 현대자동차\n",
        encoding="utf-8",
    )
    assert load_universe(p) == ["00126380", "00164742"]


from datetime import date

from themek.db.corp_models import Stock, Corporation


def test_load_universe_from_stocks_returns_corp_codes(db_session):
    from themek.dart.universe import load_universe_from_stocks

    db_session.add_all([
        Corporation(dart_code="00126380", name_ko="삼성전자"),
        Corporation(dart_code="00164742", name_ko="현대자동차"),
    ])
    db_session.flush()
    db_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="005380", name_ko="현대자동차", market="KOSPI",
              share_class="common", issued_by_id="00164742",
              last_seen_at=date(2026, 5, 27)),
    ])
    db_session.commit()

    corps = load_universe_from_stocks(db_session)
    assert sorted(corps) == ["00126380", "00164742"]


def test_load_universe_from_stocks_excludes_delisted_by_default(db_session):
    from themek.dart.universe import load_universe_from_stocks

    db_session.add_all([
        Corporation(dart_code="00126380", name_ko="삼성전자"),
        Corporation(dart_code="00009999", name_ko="구상장사"),
    ])
    db_session.flush()
    db_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="888888", name_ko="구상장사", market="KOSPI",
              share_class="common", issued_by_id="00009999",
              delisted_at=date(2026, 1, 1)),
    ])
    db_session.commit()

    assert sorted(load_universe_from_stocks(db_session)) == ["00126380"]
    assert sorted(load_universe_from_stocks(
        db_session, include_delisted=True,
    )) == ["00009999", "00126380"]


def test_load_universe_from_stocks_distinct_when_multiple_share_classes(db_session):
    """동일 corp가 보통주+우선주 발행해도 corp_code는 1번만."""
    from themek.dart.universe import load_universe_from_stocks

    db_session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    db_session.flush()
    db_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="005935", name_ko="삼성전자우", market="KOSPI",
              share_class="preferred", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
    ])
    db_session.commit()
    assert load_universe_from_stocks(db_session) == ["00126380"]
