"""
Core transcript logic — shared by the local Flask server (app.py) and the
Vercel serverless function (api/transcript.py). Keep this framework-free so it
imports cleanly in both places.

Primary path: youtube-transcript-api reads YouTube's own caption tracks via
InnerTube / timedtext (no API key, no quota).

Fallback path (_scrape_transcript): when YouTube blocks the datacenter IP
(RequestBlocked / IpBlocked), we fetch the video page directly with
curl_cffi browser-grade TLS fingerprinting (the same transport _signals.py
uses), extract ytInitialPlayerResponse, and download the JSON3 caption file.
No proxy required for the fallback — curl_cffi impersonates a real Chrome
browser at the TLS/JA3 layer, which is enough for most videos.
"""
import json as _json
import os
import re

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, CouldNotRetrieveTranscript,
)

YT_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})")
YT_COOKIE = os.getenv("YT_COOKIE", "CONSENT=YES+1; SOCS=CAI; PREF=hl=en&gl=US")


# ── optional residential proxy (turns on reliable + translation fetches) ──────
def build_api():
    user = os.getenv("WEBSHARE_PROXY_USER")
    if user:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        return YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(
            proxy_username=user, proxy_password=os.getenv("WEBSHARE_PROXY_PASS", "")))
    generic = os.getenv("YT_PROXY")
    if generic:
        from youtube_transcript_api.proxies import GenericProxyConfig
        return YouTubeTranscriptApi(proxy_config=GenericProxyConfig(
            http_url=generic, https_url=generic))
    return YouTubeTranscriptApi()


def extract_id(url: str):
    url = (url or "").strip()
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    m = YT_ID.search(url)
    return m.group(1) if m else None


def _track_meta(t):
    return {
        "lang": t.language,
        "code": t.language_code,
        "kind": "auto" if t.is_generated else "manual",
        "translatable": t.is_translatable,
    }


def fmt_ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ── JSON brace-matcher (same logic as _signals._yt_json) ─────────────────────
def _yt_json(html, marker):
    if not html:
        return None
    i = html.find(marker)
    if i < 0:
        return None
    i = html.find("{", i)
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return _json.loads(html[i:j + 1])
                except Exception:
                    return None
    return None


# ── direct-scrape fallback ────────────────────────────────────────────────────
def _scrape_transcript(vid, want=None):
    """
    Fallback: replicate what youtube_transcript_api does internally, but using
    curl_cffi browser-grade TLS/JA3 fingerprinting for every request.

    youtube_transcript_api uses plain requests.Session (non-browser TLS).
    YouTube's bot detection checks the TLS fingerprint alongside IP reputation,
    so a datacenter IP + plain TLS = blocked, while datacenter IP + Chrome TLS
    (curl_cffi impersonate) = often passes.

    Steps:
      1. GET video page with curl_cffi -> extract INNERTUBE_API_KEY
      2. POST InnerTube player API (ANDROID client) with curl_cffi TLS
      3. Get captionTracks from InnerTube response (no exp=xpe in these URLs)
      4. GET caption XML and parse it
    """
    import re as _re
    import xml.etree.ElementTree as _ET
    from html import unescape as _unescape

    _hdr = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "accept-language": "en-US,en;q=0.9",
        "cookie": YT_COOKIE,
    }

    # Use curl_cffi when available (browser TLS fingerprint), fall back to requests
    try:
        from curl_cffi import requests as _cr
        def _get(url, **kw):  return _cr.get(url,  impersonate="chrome", timeout=15, **kw)
        def _post(url, **kw): return _cr.post(url, impersonate="chrome", timeout=15, **kw)
    except ImportError:
        import requests as _req
        def _get(url, **kw):  return _req.get(url,  timeout=15, **kw)
        def _post(url, **kw): return _req.post(url, timeout=15, **kw)

    # Step 1: fetch video page
    try:
        pr = _get(f"https://www.youtube.com/watch?v={vid}", headers=_hdr)
    except Exception as e:
        return {"error": f"Page fetch failed: {e}"}, 502

    if pr.status_code != 200:
        return {"error": f"YouTube returned HTTP {pr.status_code}."}, 502

    html = pr.text
    m = _re.search(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"', html)
    if not m:
        return {"error": "Could not parse YouTube player data."}, 502
    api_key = m.group(1)

    # Step 2: POST InnerTube player API (same client as youtube_transcript_api)
    try:
        ir = _post(
            f"https://www.youtube.com/youtubei/v1/player?key={api_key}",
            json={
                "context": {"client": {"clientName": "ANDROID", "clientVersion": "20.10.38"}},
                "videoId": vid,
            },
            headers={**_hdr, "content-type": "application/json"},
        )
    except Exception as e:
        return {"error": f"Player API request failed: {e}"}, 502

    data = ir.json()
    playability = data.get("playabilityStatus", {})
    pstatus = playability.get("status", "")
    preason = playability.get("reason", "")

    if pstatus == "LOGIN_REQUIRED":
        return {
            "error": (
                "YouTube is blocking transcript access from this server. "
                "Add a residential proxy (WEBSHARE_PROXY_USER/PASS or YT_PROXY) "
                "in Vercel env vars to fix."
            )
        }, 502
    if pstatus in ("ERROR", "UNPLAYABLE"):
        return {"error": preason or "Video unavailable."}, 404

    caption_tracks = (
        data.get("captions", {})
            .get("playerCaptionsTracklistRenderer", {})
            .get("captionTracks", [])
    )
    if not caption_tracks:
        return {"error": "No transcript track is available for this video."}, 404

    def _code(t): return t.get("languageCode", "")
    def _is_auto(t): return ".auto" in t.get("vssId", "") or t.get("kind", "") == "asr"

    chosen = None
    if want:
        chosen = next((t for t in caption_tracks if _code(t) == want), None)
    if not chosen:
        for bucket in [
            [t for t in caption_tracks if not _is_auto(t) and _code(t).startswith("en")],
            [t for t in caption_tracks if not _is_auto(t)],
            [t for t in caption_tracks if _is_auto(t) and _code(t).startswith("en")],
            caption_tracks,
        ]:
            if bucket:
                chosen = bucket[0]
                break

    base_url = chosen.get("baseUrl", "")
    if not base_url:
        return {"error": "Caption URL missing from player data."}, 502

    if "&exp=xpe" in base_url:
        # PO Token required — only browser sessions can get this
        return {
            "error": (
                "YouTube requires a browser session for this video's captions. "
                "Add a residential proxy (WEBSHARE_PROXY_USER/PASS or YT_PROXY) "
                "in Vercel env vars to fix."
            )
        }, 502

    # Step 3: fetch caption XML
    try:
        cr = _get(base_url, headers=_hdr)
    except Exception as e:
        return {"error": f"Caption fetch failed: {e}"}, 502

    if not cr.text:
        return {"error": "YouTube returned empty caption data."}, 502

    # Step 4: parse timedtext XML  <p t="1360" d="1680">...</p>
    try:
        root = _ET.fromstring(cr.text)
    except Exception:
        return {"error": "Could not parse caption XML returned by YouTube."}, 502

    cues = []
    for p in root.findall(".//p"):
        start = int(p.get("t", 0)) / 1000
        dur   = int(p.get("d", 0)) / 1000
        text  = _unescape("".join(p.itertext())).replace("\n", " ").strip()
        if text:
            cues.append({"start": round(start, 2), "dur": round(dur, 2),
                         "ts": fmt_ts(start), "text": text})

    plain = " ".join(c["text"] for c in cues)
    dur_total = (cues[-1]["start"] + cues[-1]["dur"]) if cues else 0

    tracks = [{
        "lang": (t.get("name") or {}).get("simpleText", _code(t)),
        "code": _code(t),
        "kind": "auto" if _is_auto(t) else "manual",
        "translatable": bool(t.get("translationLanguages")),
    } for t in caption_tracks]

    return {
        "video_id": vid,
        "language": (chosen.get("name") or {}).get("simpleText", _code(chosen)),
        "code": _code(chosen),
        "kind": "auto" if _is_auto(chosen) else "manual",
        "translated_to": None,
        "tracks": tracks,
        "cues": cues,
        "plain": plain,
        "word_count": len(plain.split()),
        "duration": round(dur_total, 1),
        "duration_ts": fmt_ts(dur_total),
    }, 200


# ── main entry point ──────────────────────────────────────────────────────────
def fetch_transcript(url, want=None, tlang=None, api=None):
    """Return (payload_dict, http_status). Never raises for expected failures."""
    vid = extract_id(url)
    if not vid:
        return {"error": "Couldn't find a YouTube video ID in that input."}, 400

    api = api or build_api()
    try:
        tl = api.list(vid)
        tracks = [_track_meta(t) for t in tl]

        chosen = None
        if want:
            chosen = next((t for t in tl if t.language_code == want), None)
        if chosen is None:
            order = (
                [t for t in tl if not t.is_generated and t.language_code.startswith("en")]
                + [t for t in tl if not t.is_generated]
                + [t for t in tl if t.is_generated and t.language_code.startswith("en")]
                + list(tl)
            )
            chosen = order[0]

        translated_to = None
        if tlang and tlang != chosen.language_code:
            if not chosen.is_translatable:
                return {"error": f"Track '{chosen.language_code}' is not translatable."}, 400
            chosen = chosen.translate(tlang)
            translated_to = tlang

        raw = chosen.fetch().to_raw_data()
        cues = [{"start": round(c["start"], 2),
                 "dur": round(c.get("duration", 0) or 0, 2),
                 "ts": fmt_ts(c["start"]),
                 "text": c["text"].replace("\n", " ").strip()} for c in raw]
        plain = " ".join(c["text"] for c in cues)
        dur = (raw[-1]["start"] + (raw[-1].get("duration") or 0)) if raw else 0

        return {
            "video_id": vid,
            "language": chosen.language if hasattr(chosen, "language") else (translated_to or want),
            "code": getattr(chosen, "language_code", translated_to or ""),
            "kind": "translated" if translated_to else ("auto" if getattr(chosen, "is_generated", False) else "manual"),
            "translated_to": translated_to,
            "tracks": tracks,
            "cues": cues,
            "plain": plain,
            "word_count": len(plain.split()),
            "duration": round(dur, 1),
            "duration_ts": fmt_ts(dur),
        }, 200
    except TranscriptsDisabled:
        return {"error": "The uploader disabled captions for this video — nothing to fetch."}, 404
    except NoTranscriptFound:
        return {"error": "No transcript track is available for this video."}, 404
    except VideoUnavailable:
        return {"error": "Video unavailable (private, deleted, or region-locked)."}, 404
    except CouldNotRetrieveTranscript as e:
        etype = type(e).__name__
        lines = str(e).splitlines()
        msg = next((l.strip() for l in lines if l.strip()), etype)
        if "IpBlocked" in etype or "RequestBlocked" in etype or "blocked" in msg.lower():
            # Primary path blocked by YouTube IP filter — try the curl_cffi scrape fallback
            return _scrape_transcript(vid, want)
        return {"error": msg, "etype": etype}, 502
    except Exception as e:
        return {"error": str(e) or type(e).__name__, "etype": type(e).__name__}, 500
