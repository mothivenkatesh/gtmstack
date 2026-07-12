/* YouTube Transcript module */
import { API_BASE, Icon, html, useEffect, useMemo, useRef, useState } from './core.js';


/* ════════════════════════ TOOL 2 — CONTENT EXTRACTOR ════════════════════════ */
export const TRANSLATE_TARGETS = [['','Original'],['hi','Hindi'],['es','Spanish'],['fr','French'],['de','German'],['ja','Japanese'],['zh-Hant','Chinese'],['ar','Arabic'],['pt','Portuguese'],['ru','Russian']];


export function ExtractTool({seed}){
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState('stamped');
  const [query, setQuery] = useState('');
  const [tlang, setTlang] = useState('');
  const [copied, setCopied] = useState(false);
  const bodyRef = useRef();

  async function run(opts = {}){
    const u = (opts.url ?? url).trim();
    if(!u){ setError('Paste a YouTube link first.'); return; }
    setLoading(true); setError(null); if(opts.url) setUrl(u);
    const p = new URLSearchParams({ url: u });
    if(opts.lang) p.set('lang', opts.lang);
    if(opts.translate) p.set('translate', opts.translate);
    try{
      const r = await fetch(`${API_BASE}/api/transcript?` + p.toString());
      const j = await r.json();
      if(!r.ok){ setError(j.error || 'Request failed.'); if(!opts.lang && !opts.translate) setData(null); }
      else { setData(j); setQuery(''); if(bodyRef.current) bodyRef.current.scrollTop = 0; }
    }catch(e){ setError('Could not reach the extractor. Is the local server running on :5000?'); }
    setLoading(false);
  }

  useEffect(()=>{ if(seed && seed.tool==='extract' && seed.payload){ run({url:seed.payload.url}); } }, [seed]);

  const cues = data?.cues || [];
  const q = query.trim().toLowerCase();
  const filtered = useMemo(()=> q ? cues.filter(c=>c.text.toLowerCase().includes(q)) : cues, [cues, q]);
  const plainText = useMemo(()=> filtered.map(c=>c.text).join(' '), [filtered]);

  function hl(text){
    if(!q) return text;
    const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`,'ig'));
    return parts.map(p => p.toLowerCase()===q ? html`<mark>${p}</mark>` : p);
  }
  function copyAll(){
    const t = view==='stamped' ? filtered.map(c=>`[${c.ts}] ${c.text}`).join('\n') : plainText;
    navigator.clipboard.writeText(t); setCopied(true); setTimeout(()=>setCopied(false),1400);
  }
  function downloadFile(){
    const t = view==='stamped' ? filtered.map(c=>`[${c.ts}] ${c.text}`).join('\n') : plainText;
    const blob = new Blob([t], {type:'text/plain;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${data.video_id}.${view==='stamped'?'timestamped':'plain'}.txt`;
    a.click(); URL.revokeObjectURL(a.href);
  }

  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Write in your market’s exact words, lifted from any video</h1>
      <p class="view-sub">Paste any link and get a timestamped transcript in seconds, ready to mine for the exact words your market uses.</p>
    </div>

    <div class="glass-card" style="padding:24px;margin-bottom:16px">
      <label class="field-label">Paste a YouTube link</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <input class="input" style="flex:1;min-width:240px" placeholder="A watch, youtu.be, shorts, or embed link (or a video ID)"
          value=${url} onInput=${e=>setUrl(e.target.value)} onKeyDown=${e=>e.key==='Enter'&&run()} />
        <button class="btn btn-primary btn-lg" disabled=${loading} onClick=${()=>run()}>
          ${loading ? html`<${Icon} name="loader" size=15 cls="spin" /> Pulling text` : html`<${Icon} name="captions" size=15 /> Get transcript`}
        </button>
      </div>
      <div style="margin-top:8px;font-size:12px;color:var(--ink-gray-5)">
        Try a sample:
        <a style="color:var(--ink-blue-2);cursor:pointer;text-decoration:underline" onClick=${()=>run({url:'https://www.youtube.com/watch?v=T1Lowy1mnEg'})}>youtube.com/watch?v=T1Lowy1mnEg</a>
      </div>
    </div>

    ${error && html`<div class="errbox" style="margin-bottom:16px">
      <${Icon} name="alert" size=18 />
      <div><div style="font-weight:600;margin-bottom:4px">Couldn’t fetch that transcript</div>
      <div style="font-size:14px;opacity:.85">${error}</div></div>
    </div>`}

    ${loading && !data && html`<div class="kpi-grid" style="margin-bottom:16px">
      ${[0,1,2,3].map(()=>html`<div class="glass-card kpi"><div class="skel" style="height:13px;width:60%"></div><div class="skel" style="height:24px;width:75%"></div></div>`)}
    </div>`}

    ${data && html`
      <div class="kpi-grid" style="margin-bottom:16px">
        ${[
          ['Words', (data.word_count||0).toLocaleString(), 'type'],
          ['Duration', data.duration_ts, 'clock'],
          ['Segments', (data.cues.length||0).toLocaleString(), 'hash'],
        ].map(([l,v,ic])=>html`<div class="glass-card kpi">
          <div class="kpi-top"><span class="kpi-label">${l}</span><span class="chip"><${Icon} name=${ic} size=14 /></span></div>
          <div class="kpi-value">${v}</div>
        </div>`)}
        <div class="glass-card kpi">
          <div class="kpi-top"><span class="kpi-label">Source</span><span class="chip"><${Icon} name="captions" size=14 /></span></div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
            <span class=${'pill '+(data.kind==='manual'?'pill-green':data.kind==='translated'?'pill-amber':'pill-blue')}>
              ${data.kind==='manual'?'Manual subs':data.kind==='translated'?'Translated':'Auto (ASR)'}
            </span>
            <span class="mono" style="font-size:12px;color:var(--ink-gray-6)">${data.code}</span>
          </div>
        </div>
      </div>

      <div class="glass-card" style="padding:16px 16px;margin-bottom:16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
        <span style="font-size:12px;font-weight:600;color:var(--ink-gray-5)">TRACKS</span>
        <div style="display:flex;gap:8px;flex-wrap:wrap;flex:1">
          ${data.tracks.map(t=>html`<button class=${'track'+(t.code===data.code&&!data.translated_to?' on':'')} onClick=${()=>run({lang:t.code})}>
            ${t.code} <span class=${'pill '+(t.kind==='manual'?'pill-green':'pill-blue')} style="padding:4px 8px;font-size:12px">${t.kind==='manual'?'manual':'ASR'}</span>
          </button>`)}
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <${Icon} name="globe" size=14 />
          <select class="input" style="width:auto;padding:8px 24px 8px 8px;font-size:12px" value=${tlang} onChange=${e=>setTlang(e.target.value)}>
            ${TRANSLATE_TARGETS.map(([c,n])=>html`<option value=${c}>${n}</option>`)}
          </select>
          <button class="btn btn-ghost btn-sm" disabled=${loading||!tlang} onClick=${()=>run({translate:tlang})}>Translate</button>
        </div>
      </div>

      <div class="glass-card">
        <div class="panel-head">
          <div class="seg">
            <button class=${view==='stamped'?'on':''} onClick=${()=>setView('stamped')}><${Icon} name="list" size=13 /> Timestamped</button>
            <button class=${view==='plain'?'on':''} onClick=${()=>setView('plain')}><${Icon} name="type" size=13 /> Plain text</button>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <div class="search"><${Icon} name="search" size=14 />
              <input placeholder="Search…" value=${query} onInput=${e=>setQuery(e.target.value)} /></div>
            <button class="btn btn-ghost btn-sm" onClick=${copyAll}>
              <${Icon} name=${copied?'check':'copy'} size=13 /> ${copied?'Copied':'Copy'}
            </button>
            <button class="btn btn-ghost btn-sm" onClick=${downloadFile}><${Icon} name="download" size=13 /> .txt</button>
          </div>
        </div>
        <div class="tbody" ref=${bodyRef}>
          ${filtered.length===0 && html`<div style="padding:24px;text-align:center;color:var(--ink-gray-5);font-size:14px">No lines match “${query}”.</div>`}
          ${view==='stamped'
            ? filtered.map(c=>html`<div class="cue"><span class="cue-ts mono">${c.ts}</span><span class="cue-text">${hl(c.text)}</span></div>`)
            : html`<div class="plain">${query ? hl(plainText) : plainText}</div>`}
        </div>
      </div>
      <p style="font-size:12px;color:var(--ink-gray-4);margin-top:8px;text-align:center">
        video <span class="mono">${data.video_id}</span> · ${data.tracks.length} track(s) available · fetched for you, no API key
      </p>`}

    ${!data && !loading && !error && html`
      <div class="note note-blue"><${Icon} name="zap" size=16 />
        <div>This reads YouTube’s own caption track, so most spoken-word videos return text in a second or two.
          Uploaded video or audio files are not supported here: those need a separate speech-to-text service.</div>
      </div>`}
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'extract', icon:'captions', name:'YouTube Transcript', desc:'Pull clean text from any YouTube video', component: ExtractTool };
