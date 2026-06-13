import urllib.request, urllib.error
B = "https://gtmforce-ashen.vercel.app"


def g(p):
    try:
        r = urllib.request.urlopen(urllib.request.Request(B + p, headers={"User-Agent": "t"}), timeout=25)
        return r.status, r.headers.get("content-type", "")[:25]
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return "ERR", str(e)[:60]


paths = [
    ("/README.md", "md NOT-ignored"),
    ("/CLAUDE.md", "md IGNORED"),
    ("/RISK.md", "md IGNORED"),
    ("/requirements.txt", "txt NOT-ignored"),
    ("/vercel.json", "json NOT-ignored"),
    ("/app.py", "py IGNORED"),
    ("/tests/test_auth.py", "tests/ IGNORED"),
    ("/.vercelignore", "ignored-ish"),
]
out = []
for p, note in paths:
    s, ct = g(p)
    out.append(f"{str(s):>4}  {p:<26} ({note})  {ct}")
text = "\n".join(out)
print(text)
with open("C:/Users/mothi/_probe.txt", "w", encoding="utf-8") as f:
    f.write(text + "\n")
