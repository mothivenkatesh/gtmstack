"""Thorough per-tool test of a GTMstack deployment.

Goes beyond HTTP 200: inspects each tool's actual payload and prints a
PASS / WARN / FAIL verdict so we catch tools that answer 200 but are broken
or degraded. WARN = working-as-designed degraded (e.g. a source that needs a
credential the serverless env does not have).
"""
import json, sys, urllib.request, urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://gtmforce-ashen.vercel.app"
UA = {"User-Agent": "gtmstack-fulltest/1.0", "Content-Type": "application/json"}
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def call(method, path, body=None, timeout=55):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=UA, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw), raw
            except Exception:
                return r.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        try:
            return e.code, json.loads(raw), raw
        except Exception:
            return e.code, None, raw
    except Exception as e:
        return "ERR", None, type(e).__name__ + ": " + str(e)[:200]


rows = []


def log(tool, verdict, detail):
    rows.append((tool, verdict, detail))
    print(f"[{verdict}] {tool}: {detail}")


# 1. Home (static SPA)
s, j, raw = call("GET", "/")
if s == 200 and "<!doctype html" in raw.lower():
    log("Home (SPA)", PASS, f"200, {len(raw)} bytes of HTML")
else:
    log("Home (SPA)", FAIL, f"status={s}, not HTML")

# 2. Signals readiness
s, j, raw = call("GET", "/api/signals")
if s == 200 and isinstance(j, dict) and "sources" in j:
    srcs = j["sources"]
    state = ", ".join(k + "=" + ("ready" if v.get("ready") else "no") for k, v in srcs.items())
    log("Signals /readiness", PASS, "sources: " + state)
else:
    log("Signals /readiness", FAIL, f"status={s}")

# 3. Signals person lookup (GitHub should be ok)
s, j, raw = call("POST", "/api/signals", {"query": "torvalds", "unit": "person"})
if s == 200 and isinstance(j, dict):
    by = {x.get("platform"): x.get("status") for x in j.get("sources", [])}
    gh = by.get("github")
    if gh == "ok":
        log("Signals person", PASS, f"github=ok; all: {by}")
    else:
        log("Signals person", FAIL, f"github={gh}; all: {by}")
else:
    log("Signals person", FAIL, f"status={s} {raw[:120]}")

# 4. Signals keyword feed
s, j, raw = call("POST", "/api/signals", {"query": "mcp servers", "unit": "keyword"})
if s == 200 and isinstance(j, dict):
    feed = j.get("feed") or j.get("items") or j.get("mentions") or []
    n = len(feed) if isinstance(feed, list) else 0
    log("Signals keyword", PASS if n else WARN, f"{n} mentions" + ("" if n else " (empty from this IP)"))
else:
    log("Signals keyword", FAIL, f"status={s}")

# 5. Transcript (YouTube; may be IP-blocked on datacenter)
s, j, raw = call("GET", "/api/transcript?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
if s == 200 and isinstance(j, dict) and j.get("plain"):
    log("YouTube Transcript", PASS, f"{j.get('word_count','?')} words, lang={j.get('language')}")
elif isinstance(j, dict) and j.get("error"):
    log("YouTube Transcript", WARN, f"{s}: {str(j.get('error'))[:120]}")
else:
    log("YouTube Transcript", FAIL, f"status={s} {raw[:120]}")

# 6. NoBounce / clean
s, j, raw = call("POST", "/api/clean", {"text": "good@gmail.com\nbademail@@x\nrole@info.com\ngood@gmail.com"})
if s == 200 and isinstance(j, dict) and j.get("summary"):
    sm = j["summary"]
    log("NoBounce (clean)", PASS, f"unique={sm.get('unique')} by_verdict={sm.get('by_verdict')} dupes={sm.get('duplicates_removed')}")
else:
    log("NoBounce (clean)", FAIL, f"status={s} {raw[:160]}")

# 7. Persona
s, j, raw = call("POST", "/api/persona", {"text": "Ship faster with our payments API. One integration, every method.", "type": "landing"})
if s == 200 and isinstance(j, dict) and "overall" in j:
    log("Synthetic Persona", PASS, f"overall={j['overall']} verdict={j.get('verdict')} engine={j.get('engine')} reactions={len(j.get('results',[]))}")
else:
    log("Synthetic Persona", FAIL, f"status={s} {raw[:160]}")

# 8. Plays list
s, j, raw = call("GET", "/api/plays")
play_ids = []
if s == 200 and isinstance(j, dict):
    play_ids = [p.get("id") for p in j.get("plays", [])]
    log("Plays /list", PASS, f"{len(play_ids)} plays: {', '.join(play_ids)}")
else:
    log("Plays /list", FAIL, f"status={s}")

# 9. Play: video_messaging (the documented Phase-1 play)
if "video_messaging" in play_ids:
    s, j, raw = call("POST", "/api/plays", {"play": "video_messaging", "input": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}})
    if s == 200 and isinstance(j, dict):
        steps = j.get("steps", [])
        oks = sum(1 for st in steps if st.get("status") == "ok")
        bad = [st.get("label") for st in steps if st.get("status") == "error"]
        log("Play video_messaging", PASS if j.get("ok") else WARN, f"{oks}/{len(steps)} steps ok" + (f"; errors: {bad}" if bad else ""))
    else:
        log("Play video_messaging", FAIL, f"status={s}")

# 10. Play: creator_teardown
if "creator_teardown" in play_ids:
    s, j, raw = call("POST", "/api/plays", {"play": "creator_teardown", "input": {"handle": "levelsio"}})
    if s == 200 and isinstance(j, dict):
        steps = j.get("steps", [])
        oks = sum(1 for st in steps if st.get("status") == "ok")
        log("Play creator_teardown", PASS if j.get("ok") else WARN, f"{oks}/{len(steps)} steps ok")
    else:
        log("Play creator_teardown", FAIL, f"status={s}")

# 11. Play: trend_discovery
if "trend_discovery" in play_ids:
    s, j, raw = call("POST", "/api/plays", {"play": "trend_discovery", "input": {"keyword": "ai agents"}})
    if s == 200 and isinstance(j, dict):
        steps = j.get("steps", [])
        oks = sum(1 for st in steps if st.get("status") == "ok")
        log("Play trend_discovery", PASS if j.get("ok") else WARN, f"{oks}/{len(steps)} steps ok")
    else:
        log("Play trend_discovery", FAIL, f"status={s}")

# 12. Play: competitor_intel
if "competitor_intel" in play_ids:
    s, j, raw = call("POST", "/api/plays", {"play": "competitor_intel", "input": {"brand": "Cashfree", "competitors": "Razorpay, PayU"}})
    if s == 200 and isinstance(j, dict):
        steps = j.get("steps", [])
        oks = sum(1 for st in steps if st.get("status") == "ok")
        log("Play competitor_intel", PASS if j.get("ok") else WARN, f"{oks}/{len(steps)} steps ok")
    else:
        log("Play competitor_intel", FAIL, f"status={s}")

# 13. Jobs list
s, j, raw = call("GET", "/api/jobs")
if s == 200:
    log("Jobs /list", PASS, "200")
else:
    log("Jobs /list", WARN, f"status={s}")

# 14. Security: secrets must NOT be served
for p in ("/.env", "/CLAUDE.md", "/RISK.md", "/app.py"):
    s, j, raw = call("GET", p)
    if s == 404:
        log(f"Security {p}", PASS, "404 (hidden)")
    else:
        log(f"Security {p}", FAIL, f"status={s} EXPOSED")

# Summary
print("\n" + "=" * 60)
c = {PASS: 0, WARN: 0, FAIL: 0}
for _, v, _ in rows:
    c[v] += 1
print(f"SUMMARY: {c[PASS]} PASS, {c[WARN]} WARN, {c[FAIL]} FAIL  ({BASE})")
