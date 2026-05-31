"""RateBudget: 일일 DART 호출 한도 추적 + 디스크 영속화."""
from datetime import date

import pytest

from themek.dart.rate_budget import RateBudget, RateBudgetExceeded


def test_budget_starts_at_zero(tmp_path):
    b = RateBudget(daily_cap=10, state_file=tmp_path / "budget.json")
    assert b.remaining() == 10


def test_budget_consume_decrements(tmp_path):
    b = RateBudget(daily_cap=10, state_file=tmp_path / "budget.json")
    b.consume(3)
    assert b.remaining() == 7


def test_budget_exceeded_raises(tmp_path):
    b = RateBudget(daily_cap=5, state_file=tmp_path / "budget.json")
    b.consume(5)
    with pytest.raises(RateBudgetExceeded):
        b.consume(1)


def test_budget_persists_to_disk(tmp_path):
    """같은 state_file로 재초기화 시 used 누적이 유지된다."""
    state = tmp_path / "budget.json"
    RateBudget(daily_cap=10, state_file=state).consume(3)
    b2 = RateBudget(daily_cap=10, state_file=state)
    assert b2.remaining() == 7


def test_budget_resets_on_new_day(tmp_path):
    """state_file의 date가 오늘과 다르면 used=0으로 reset."""
    state = tmp_path / "budget.json"
    state.write_text('{"date": "2020-01-01", "used": 38000}', encoding="utf-8")
    b = RateBudget(daily_cap=38000, state_file=state, today=date(2026, 5, 27))
    assert b.remaining() == 38000
