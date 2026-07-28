#!/usr/bin/env python3
"""
Scheduled runner for standing watches. This is what makes GTMstack work while
nobody is looking, which is the whole difference between a toolkit and a product.

    python watch_run.py            # fire only the watches that are due
    python watch_run.py --all      # fire everything now
    python watch_run.py --status   # is the unattended side alive

Wire it to launchd (macOS) or any cron. Delivery downstream is idempotent, so
firing more often than needed is safe: it will simply find nothing new to send.

No em dashes.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "api"))


def _load_dotenv(path):
    """Same minimal loader app.py uses, so a scheduled run sees the same creds."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


def main():
    _load_dotenv(os.path.join(HERE, ".env"))
    import _watch
    if "--status" in sys.argv:
        s = _watch.status()
        print(f"watches={s['watches']} enabled={s['enabled']} healthy={s['healthy']}"
              f" last_run={s['hours_since']}h ago stale={s['stale']}")
        return 0 if s["healthy"] or not s["watches"] else 1
    # Read the sheet BEFORE running, so outcomes recorded since the last run are
    # applied before new alerts land. A user who marked five rows yesterday
    # should see that reflected, not buried under today's batch.
    try:
        import _deliver
        pulled = _deliver.pull_outcomes()
        if pulled.get("applied"):
            print(f"read {pulled['applied']} outcomes back from the sheet")
    except Exception:                                            # noqa: BLE001
        pass

    out = _watch.run_all() if "--all" in sys.argv else _watch.run_due()
    print(f"ran {out['ran']} watches, {out.get('found', 0)} new signals")
    # Keep the public graph number honest without anyone remembering to.
    if out.get("found") and "--no-stats" not in sys.argv:
        try:
            import subprocess
            subprocess.run([sys.executable, os.path.join(HERE, "scripts", "graph_stats.py")],
                           capture_output=True, timeout=60)
        except Exception:                                        # noqa: BLE001
            pass
    for r in out.get("results", []):
        print(f"   {r.get('watch')}: {r.get('found', 0)} found "
              f"({'ok' if r.get('ok') else 'FAILED ' + str(r.get('error', ''))[:80]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
