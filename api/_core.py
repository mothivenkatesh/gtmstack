"""
Core transcript logic — shared by the local Flask server (app.py) and the
Vercel serverless function (api/transcript.py). Keep this framework-free so it
imports cleanly in both places.

The keyless method: youtube-transcript-api reads YouTube's own caption tracks
via the internal InnerTube / timedtext endpoints (no API key, no quota).
"""
import os
import re

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, CouldNotRetrieveTranscript,
)

YT_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})")


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
        msg = (str(e).splitlines() or [etype])[0]
        if "IpBlocked" in etype or "blocked" in msg.lower():
            msg = ("YouTube rate-limited this server IP. Set a residential proxy "
                   "(WEBSHARE_PROXY_USER/PASS or YT_PROXY) to fix — see README.")
        return {"error": msg, "etype": etype}, 502
    except Exception as e:
        return {"error": str(e) or type(e).__name__, "etype": type(e).__name__}, 500
