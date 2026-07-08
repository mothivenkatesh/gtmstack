#!/usr/bin/env python3
"""
GTMstack - daily Signals report runner (called by launchd at 9am IST).

Runs two jobs:
  1. run_report() for every keyword group -> in-app Reports tab.
  2. run_monitor() -> competitive intelligence scan (Reddit, Quora, G2,
     Capterra, TrustPilot, LinkedIn, X) pushed to Google Sheets.

Pass a group id to run just the report for that group.
Pass --monitor to run only the monitor job.

    python daily_report.py                 # all groups + monitor
    python daily_report.py payment_gateway # one report group only
    python daily_report.py --monitor       # monitor job only

launchd starts processes with a near-empty environment, so this loads the
gitignored .env at the project root first (same loader app.py uses), then makes
api/_*.py importable. Tune the per-group time budget with REPORT_BUDGET_S.
"""
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    """Minimal .env loader (no dependency): KEY=VALUE lines, # comments, optional
    surrounding quotes. Does not overwrite values already in the environment."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


def _run_reports(groups, budget):
    from _report import run_report
    print(f"=== GTMstack daily report :: {datetime.now().isoformat(timespec='seconds')} "
          f":: {len(groups)} group(s) :: budget {budget:.0f}s each ===", flush=True)
    for g in groups:
        t0 = time.time()
        try:
            rep, st = run_report(g["id"], budget_s=budget)
        except Exception as e:
            print(f"  [{g['id']}] FAILED: {type(e).__name__}: {e}", flush=True)
            continue
        if st != 200:
            print(f"  [{g['id']}] status {st}: {rep.get('error')}", flush=True)
            continue
        s = rep["sentiment"]
        print(f"  [{g['id']}] {rep['totals']['mentions']} mentions across "
              f"{','.join(rep['totals']['sources_hit']) or 'none'} | "
              f"pos {s['positive']} / neg {s['negative']} / neu {s['neutral']} | "
              f"engine {rep['engine']} | {time.time() - t0:.1f}s", flush=True)
    print("=== reports done ===", flush=True)


def _run_monitor(catchup=False):
    from _monitor import run_monitor
    print(f"=== GTMstack competitive monitor :: "
          f"{datetime.now().isoformat(timespec='seconds')}"
          f"{' (catch-up)' if catchup else ''} ===", flush=True)
    result = run_monitor(push_to_sheets=True, catchup=catchup)
    if result.get("skipped"):
        print(f"=== monitor skipped :: {result['skipped']} ===", flush=True)
    else:
        print(f"=== monitor done :: {result['total']} mentions, "
              f"{result.get('inserted', 0)} new in {result['elapsed_s']}s ===", flush=True)
    return result


def main():
    _load_dotenv(os.path.join(HERE, ".env"))
    sys.path.insert(0, os.path.join(HERE, "api"))
    from _groups import list_groups

    args = sys.argv[1:]
    monitor_only = "--monitor" in args
    catchup = "--catchup" in args          # 13:00 launchd catch-up: only if 9am missed
    args = [a for a in args if a not in ("--monitor", "--catchup")]
    only = args[0] if args else None

    budget = float(os.getenv("REPORT_BUDGET_S", "60"))

    if catchup:                            # catch-up runs the monitor only
        _run_monitor(catchup=True)
        print("=== all done ===", flush=True)
        return 0

    if not monitor_only:
        groups = [g for g in list_groups() if not only or g["id"] == only]
        if only and not groups:
            print(f"no group matched {only!r}")
            return 1
        _run_reports(groups, budget)

    if not only:
        _run_monitor()

    print("=== all done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
