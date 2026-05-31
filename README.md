# YouTube Transcript Generator (Frappe-Preact)

A NoteGPT-style landing page + thin API that extracts YouTube captions the **keyless**
way — reads YouTube's own InnerTube/`timedtext` tracks (manual *and* auto-generated
ASR), no Data-API key, no quota. One static `index.html` (Preact + Frappe Design
System tokens) calling one Python endpoint that runs both as a local Flask server
**and** as a Vercel serverless function.

## Run locally
```bash
pip install -r requirements.txt
python app.py            # -> http://localhost:5000
```
Paste any YouTube URL (watch / youtu.be / shorts / embed / live) or a raw 11-char ID.

## Layout
```
index.html          static SPA (hero + tabbed tool + how-it-works + features + use-cases + FAQ + footer)
app.py              local Flask dev server  (serves index.html + /api/transcript)
api/_core.py        shared transcript logic (single source of truth)
api/transcript.py   Vercel serverless function -> /api/transcript
vercel.json         function config + root rewrite
requirements.txt    flask, flask-cors, youtube-transcript-api
```

## API
`GET /api/transcript?url=<link>[&lang=<code>][&translate=<code>]` → JSON
`{ video_id, language, code, kind, translated_to, tracks[], cues[{ts,start,dur,text}], plain, word_count, duration, duration_ts }`

## Deploy to Vercel
```bash
npm i -g vercel
vercel            # from this folder; static index.html + api/transcript.py auto-wire
```
`index.html` serves at `/`; `api/transcript.py` answers `/api/transcript`. The browser
calls a same-origin relative path, so no CORS or config change is needed.

**Two real caveats before you ship the YouTube tab to Vercel:**
1. **Datacenter IP block.** YouTube rate-limits/IP-gates cloud ranges (Vercel included)
   *harder* than a home connection. Plain caption fetches may work intermittently;
   `&translate=` almost always gets blocked. Set a **residential proxy** in the Vercel
   project's Environment Variables (`WEBSHARE_PROXY_USER` + `WEBSHARE_PROXY_PASS`, or
   `YT_PROXY=http://user:pass@host:port`) — the code already reads them.
2. **Cache to cut calls + cost** (this is what NoteGPT does: fetch once, store, serve from
   CDN). Add a KV/Redis layer (Vercel KV or Upstash) keyed by `video_id|lang|translate`.

## The Video / Audio tabs are structure only
An uploaded file has **no caption track to read**, so the keyless path doesn't apply.
Transcribing media needs real speech-to-text (Whisper / Deepgram / AssemblyAI), a
separate and usually paid service. Heavy local Whisper won't fit a standard Vercel
function (size + time limits) — call a hosted ASR API instead. The tabs show exactly
where that wires in; only the YouTube caption path is implemented here.

## Translation
`translate=hi` uses YouTube's `&tlang=` machine translation. IP-blocked from datacenter
IPs, so it needs the residential proxy above to work reliably.

## Why a backend (can't this be pure HTML?)
No. The browser can't fetch `timedtext` directly: (1) YouTube sends no CORS headers,
and (2) it IP-gates the endpoint. The server does the fetch so the page just renders.

## Limits
Captions disabled by uploader / no speech → no transcript. Accuracy = YouTube's own ASR
quality. Uses YouTube's undocumented endpoints (against ToS, can break), so keep it to
personal / educational use and respect copyright.
