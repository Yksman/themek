"""
ad-hoc: 25 random pending BackfillTarget(period=2025) 처리 + 모니터링.

production code path (`run_one_target`) 그대로 사용. CLI의 FIFO 우회만.
"""
from __future__ import annotations

import time
from datetime import datetime
from sqlalchemy import select, func

from themek.cli import _dart_client_and_cache, _stub_extractor_from_env
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import BackfillTarget, Corporation
from themek.dart.backfill import run_one_target
from themek.dart.rate_budget import RateBudget, RateBudgetExceeded
from themek.config import get_settings


SAMPLE_SIZE = 25
PERIOD_FILTER = "2025"


def main() -> int:
    s = get_settings()
    client, cache = _dart_client_and_cache()
    extractor = _stub_extractor_from_env()
    budget = RateBudget(
        daily_cap=38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )

    Session = make_session_factory(make_engine())
    with Session() as sess:
        # 1) random sample 25 from pending
        targets = sess.execute(
            select(BackfillTarget)
            .where(BackfillTarget.status == "pending")
            .where(BackfillTarget.period == PERIOD_FILTER)
            .order_by(func.random())
            .limit(SAMPLE_SIZE)
        ).scalars().all()

        if not targets:
            print(f"No pending targets with period={PERIOD_FILTER}")
            return 1

        print(f"\n=== Random sample {len(targets)} (period={PERIOD_FILTER}) ===")
        for i, t in enumerate(targets, 1):
            corp = sess.get(Corporation, t.corp_code)
            name = corp.name_ko if corp else "?"
            print(f"  {i:2d}. {t.corp_code} ({name}) {t.period}")

        # 2) 처리
        print(f"\n=== Processing ===")
        t0 = time.time()
        counts = {"done": 0, "skipped": 0, "failed": 0}
        per_target_log = []

        for i, t in enumerate(targets, 1):
            corp = sess.get(Corporation, t.corp_code)
            name = corp.name_ko if corp else "?"
            ts = time.time()
            try:
                r = run_one_target(
                    target=t, session=sess,
                    client=client, cache=cache,
                    rate_budget=budget, extractor=extractor,
                    purge_zip=True,
                )
                elapsed = time.time() - ts
                counts[r.status] = counts.get(r.status, 0) + 1
                esc = getattr(t, "escalation_level", None) or "-"
                cost = float(t.cost_estimate_usd or 0)
                line = (
                    f"  {i:2d}/{len(targets)} {t.corp_code} ({name}) "
                    f"{r.status:8s} esc={esc:10s} cost=${cost:.4f} "
                    f"chars={t.input_chars or 0:6d} time={elapsed:5.1f}s"
                )
                if r.status == "failed":
                    line += f" err={(t.last_error or '')[:60]}"
                print(line)
                per_target_log.append((t.corp_code, name, r.status, esc, cost, elapsed))
            except RateBudgetExceeded:
                print(f"  {i:2d}/{len(targets)} BUDGET EXCEEDED — stop")
                break
            except Exception as e:
                print(f"  {i:2d}/{len(targets)} {t.corp_code} ({name}) UNHANDLED: {e}")
                counts["failed"] = counts.get("failed", 0) + 1

        # 3) summary
        total_time = time.time() - t0
        total_cost = sum(row[4] for row in per_target_log)
        print(f"\n=== Summary ===")
        print(f"  processed:   {sum(counts.values())}")
        print(f"  done:        {counts.get('done', 0)}")
        print(f"  skipped:     {counts.get('skipped', 0)}")
        print(f"  failed:      {counts.get('failed', 0)}")
        print(f"  total cost:  ${total_cost:.4f}")
        print(f"  total time:  {total_time:.1f}s ({total_time/60:.1f}min)")
        print(f"  budget left: {budget.remaining()}")

        # 4) escalation 분포 (이번 batch)
        esc_dist: dict = {}
        for _, _, status, esc, _, _ in per_target_log:
            if status == "done":
                esc_dist[esc] = esc_dist.get(esc, 0) + 1
        print(f"\n=== Escalation (done only) ===")
        for k, v in sorted(esc_dist.items()):
            print(f"  {k:10s}: {v}")

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
