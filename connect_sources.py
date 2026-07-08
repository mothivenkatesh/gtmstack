#!/usr/bin/env python3
"""
Connect Reddit, LinkedIn, and X for GTMstack on macOS.

Reddit already works for the keyword report with no login (arctic-shift).
LinkedIn and X need YOUR logged-in session, and the built-in profile decrypt is
Windows-only, so on macOS we capture cookies straight from a real login: this
opens a browser, you sign in, and it writes the exact cookies GTMstack reads to
~/.gtmstack/*_cookies.json and points .env at them.

    python connect_sources.py              # linkedin + x
    python connect_sources.py linkedin
    python connect_sources.py x
    python connect_sources.py reddit       # paste a free Reddit app's id/secret

Needs Playwright:  .venv/bin/pip install playwright  (chromium is already cached)

After it finishes, reload so the new session is used:
    pkill -f app.py && .venv/bin/python app.py      # local server
    ./launchd/install.sh                             # the 8am job
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / ".env"
GT = Path.home() / ".gtmstack"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# What each platform needs, and which cookies prove a real login.
PLATFORMS = {
    "linkedin": {"url": "https://www.linkedin.com/login", "domain": "linkedin.com",
                 "need": ("li_at", "JSESSIONID"), "env": "LINKEDIN_COOKIES",
                 "file": "li_cookies.json"},
    "x":        {"url": "https://x.com/login", "domain": "x.com",
                 "need": ("auth_token", "ct0"), "env": "X_COOKIES",
                 "file": "x_cookies.json"},
}


def set_env(updates):
    """Upsert KEY=VALUE pairs into ./.env without disturbing other lines."""
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if ("=" in ln and not ln.lstrip().startswith("#")) else None
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(ln)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV.write_text("\n".join(out).strip() + "\n")
    print(f"  .env updated: {', '.join(updates)}")


def capture(platform):
    cfg = PLATFORMS[platform]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright missing. Run:  .venv/bin/pip install playwright && .venv/bin/playwright install chromium")
        return None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1360, "height": 900})
        ctx.new_page().goto(cfg["url"], wait_until="domcontentloaded")
        print(f"\n  A browser opened. Log in to {platform.upper()}, reach your normal home feed,")
        input("  then come back here and press ENTER to capture... ")
        cookies = ctx.cookies()
        browser.close()
    jar = {c["name"]: c["value"] for c in cookies if cfg["domain"] in (c.get("domain") or "")}
    missing = [k for k in cfg["need"] if not jar.get(k)]
    if missing:
        print(f"  Could not find {missing}. Make sure you are fully logged in, then re-run.")
        return None
    GT.mkdir(exist_ok=True)
    path = GT / cfg["file"]
    path.write_text(json.dumps(jar))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    set_env({cfg["env"]: str(path)})
    print(f"  {platform.upper()} connected: {len(jar)} cookies -> {path}")
    return jar


def reddit():
    print("\n  Reddit already powers the keyword report via arctic-shift (no login).")
    print("  For the official API (and person/company lookups), make a free 'script' app")
    print("  at https://www.reddit.com/prefs/apps, then paste its credentials:")
    cid = input("  REDDIT_CLIENT_ID (blank to skip): ").strip()
    if not cid:
        print("  Skipped. arctic-shift stays active for the report.")
        return
    csec = input("  REDDIT_CLIENT_SECRET: ").strip()
    if csec:
        set_env({"REDDIT_CLIENT_ID": cid, "REDDIT_CLIENT_SECRET": csec})
        print("  Reddit OAuth configured.")


def main():
    targets = [a.lower() for a in sys.argv[1:]] or ["linkedin", "x"]
    for t in targets:
        if t in PLATFORMS:
            capture(t)
        elif t == "reddit":
            reddit()
        else:
            print(f"  unknown target: {t} (use linkedin | x | reddit)")
    print("\n  Done. Now reload to use the new session:")
    print("    pkill -f app.py ; .venv/bin/python app.py     # local server (http://localhost:5000)")
    print("    ./launchd/install.sh                           # the 8am job")


if __name__ == "__main__":
    main()
