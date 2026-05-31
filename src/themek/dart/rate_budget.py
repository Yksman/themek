"""DART API 일일 호출 한도 tracker.

state 파일 schema (JSON):
  {"date": "YYYY-MM-DD", "used": int}

`date`는 KST 기준. 자정(KST 0시)에 자동 reset된다.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


class RateBudgetExceeded(RuntimeError):
    """일일 호출 한도 초과."""


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


class RateBudget:
    def __init__(
        self,
        *,
        daily_cap: int,
        state_file: Path,
        today: Optional[date] = None,
    ):
        self.daily_cap = daily_cap
        self.state_file = Path(state_file)
        self._today = today or _today_kst()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_and_maybe_reset()

    def _load_and_maybe_reset(self) -> None:
        if not self.state_file.exists():
            self._used = 0
            self._persist()
            return
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        if data.get("date") != self._today.isoformat():
            self._used = 0
            self._persist()
        else:
            self._used = int(data.get("used", 0))

    def _persist(self) -> None:
        self.state_file.write_text(
            json.dumps({
                "date": self._today.isoformat(),
                "used": self._used,
            }),
            encoding="utf-8",
        )

    def remaining(self) -> int:
        return max(0, self.daily_cap - self._used)

    def consume(self, n: int = 1) -> None:
        if self._used + n > self.daily_cap:
            raise RateBudgetExceeded(
                f"daily_cap={self.daily_cap} used={self._used} requested={n}"
            )
        self._used += n
        self._persist()
