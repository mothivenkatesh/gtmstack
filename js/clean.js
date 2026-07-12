/* NoBounce (clean) module */
import { API_BASE, Icon, h, html, useEffect, useMemo, useRef, useState } from './core.js';


/* ════════════════════════ TOOL 5 — CLEAN DATA ════════════════════════ */
export const VERDICT_PILL = {deliverable:'pill-green', valid:'pill-green', risky:'pill-amber',
  undeliverable:'pill-red', invalid:'pill-red'};

export const CLEAN_SAMPLE = ['founder@acme.com','FOUNDER@acme.com','info@stripe.com',
  'sales@mailinator.com','jane@gmial.com','not-an-email','hello@cashfree.com'].join('\n');


export function CleanTool({seed}){
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [cleanOnly, setCleanOnly] = useState(false);
  const [query, setQuery] = useState('');
  const [copied, setCopied] = useState(false);
  const [deliver, setDeliver] = useState(false);
  const fileRef = useRef();
  const bodyRef = useRef();

  async function run(opts = {}){
    const t = (opts.text ?? text).trim();
    if(!t){ setError('Paste or upload some email addresses first.'); return; }
    setLoading(true); setError(null); if(opts.text) setText(t);
    try{
      const r = await fetch(`${API_BASE}/api/clean`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ text: t }) });
      const j = await r.json();
      if(!r.ok){ setError(j.error || 'Validation failed.'); }
      else { setData(j); setCleanOnly(false); setQuery(''); if(bodyRef.current) bodyRef.current.scrollTop = 0; }
    }catch(e){ setError('Could not reach the validator. Is the local server running on :5000?'); }
    setLoading(false);
  }
  function onFile(e){
    const f = e.target.files && e.target.files[0]; if(!f) return;
    const reader = new FileReader();
    reader.onload = () => { setText(String(reader.result || '')); setError(null); };
    reader.readAsText(f); e.target.value = '';
  }

  useEffect(()=>{ if(seed && seed.tool==='clean' && seed.payload){ run({text:seed.payload.text}); } }, [seed]);

  const rows = data?.rows || [];
  const sm = data?.summary;
  const q = query.trim().toLowerCase();
  const shown = useMemo(()=>{
    let r = cleanOnly ? rows.filter(x=>x.valid) : rows;
    return q ? r.filter(x=>(x.email||'').toLowerCase().includes(q)) : r;
  }, [rows, cleanOnly, q]);

  function csvText(only){
    const f = data.fields;
    const esc = v => { v = v==null?'':String(v); return /[",\n]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v; };
    const rr = only ? rows.filter(x=>x.valid) : rows;
    return [f.join(','), ...rr.map(r=>f.map(k=>esc(r[k])).join(','))].join('\n');
  }
  function dl(kind){
    const only = cleanOnly;
    const body = kind==='csv' ? csvText(only)
      : JSON.stringify(only ? rows.filter(x=>x.valid) : rows, null, 2);
    const blob = new Blob([body], {type: kind==='csv'?'text/csv;charset=utf-8':'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `clean-emails${only?'.sendable':''}.${kind}`;
    a.click(); URL.revokeObjectURL(a.href);
  }
  function apiSnippet(){
    const base = API_BASE || location.origin;
    const body = { text: 'founder@acme.com, info@stripe.com, x@mailinator.com' };
    return `curl -X POST ${base}/api/clean \\\n  -H 'Content-Type: application/json' \\\n`
      + `  -d '${JSON.stringify(body)}'\n\n`
      + `# Add ?format=csv&only=clean to download just the sendable rows (deliverable + risky).`;
  }
  function copySnippet(){ navigator.clipboard.writeText(apiSnippet()); setCopied(true); setTimeout(()=>setCopied(false),1400); }

  const v = sm?.by_verdict || {};
  const undeliv = (v.undeliverable||0) + (v.invalid||0);

  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Never let a bad address burn your sending domain</h1>
      <p class="view-sub">Paste a list and get one verdict per address: syntax, live MX, disposable, role, and typos, de-duped. No mail is sent.</p>
    </div>

    <div class="glass-card" style="padding:24px;margin-bottom:16px">
      <label class="field-label">Paste emails, or upload a CSV</label>
      <textarea class="copy-area" style="min-height:128px" placeholder="One email per line, or paste a whole CSV — addresses are pulled out of any column."
        value=${text} onInput=${e=>setText(e.target.value)}></textarea>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px">
        <button class="btn btn-primary btn-lg" disabled=${loading} onClick=${()=>run()}>
          ${loading ? html`<${Icon} name="loader" size=15 cls="spin" /> Validating` : html`<${Icon} name="broom" size=15 /> Clean list`}
        </button>
        <button class="btn btn-ghost btn-lg" onClick=${()=>fileRef.current.click()}><${Icon} name="upload" size=15 /> Upload CSV</button>
        <input ref=${fileRef} type="file" accept=".csv,.txt,.tsv" style="display:none" onChange=${onFile} />
        <button class="btn btn-ghost btn-lg" disabled=${loading} onClick=${()=>run({text:CLEAN_SAMPLE})} style="margin-left:auto">Try a sample</button>
      </div>
    </div>

    <div class="deliver">
      <div class="deliver-h" onClick=${()=>setDeliver(d=>!d)}>
        <${Icon} name="code" size=15 /> Call it from an agent
        <span style="margin-left:auto;color:var(--ink-gray-4)"><${Icon} name=${deliver?'minus':'plus'} size=14 /></span>
      </div>
      ${deliver && html`<div class="deliver-b">
        <div class="dlv-block">
          <div class="dlv-lab"><${Icon} name="code" size=13 /> POST a list, get back validated rows</div>
          <div class="code-blk">
            <button class="copy-mini" onClick=${copySnippet}><${Icon} name=${copied?'check':'copy'} size=12 /> ${copied?'Copied':'Copy'}</button>
            <pre>${apiSnippet()}</pre>
          </div>
          <div class="sig-hint">The JSON response carries one row per address (valid, verdict, score, mx_ok, disposable, role, typo) — the same data this page renders.</div>
        </div>
      </div>`}
    </div>

    ${error && html`<div class="errbox" style="margin:16px 0">
      <${Icon} name="alert" size=18 />
      <div><div style="font-weight:600;margin-bottom:4px">Couldn't clean that list</div>
      <div style="font-size:14px;opacity:.85">${error}</div></div>
    </div>`}

    ${loading && !data && html`<div class="kpi-grid" style="margin:16px 0">
      ${[0,1,2,3].map(()=>html`<div class="glass-card kpi"><div class="skel" style="height:13px;width:55%"></div><div class="skel" style="height:24px;width:40%"></div></div>`)}
    </div>`}

    ${data && sm && html`
      <div class="kpi-grid" style="margin:16px 0 8px">
        ${[
          ['Deliverable', v.deliverable||0, 'sealCheck', 'pill-green'],
          ['Risky',       v.risky||0,     'alert',     'pill-amber'],
          ['Undeliverable', undeliv,       'alert',     'pill-red'],
          ['Duplicates removed', sm.duplicates_removed, 'copy', 'pill-gray'],
        ].map(([l,val,ic,pc])=>html`<div class="glass-card kpi">
          <div class="kpi-top"><span class="kpi-label">${l}</span><span class="chip"><${Icon} name=${ic} size=14 /></span></div>
          <div class="kpi-value">${(val||0).toLocaleString()}</div>
        </div>`)}
      </div>
      <p style="font-size:12px;color:var(--ink-gray-5);margin:0 4px 16px">
        ${sm.unique.toLocaleString()} unique address${sm.unique===1?'':'es'} from ${sm.submitted.toLocaleString()} found${sm.truncated?html` · capped at ${sm.max_emails.toLocaleString()}`:''}.
      </p>

      <div class="glass-card">
        <div class="panel-head">
          <div class="seg">
            <button class=${cleanOnly?'':'on'} onClick=${()=>setCleanOnly(false)}>All ${rows.length}</button>
            <button class=${cleanOnly?'on':''} onClick=${()=>setCleanOnly(true)}><${Icon} name="sealCheck" size=13 /> Sendable ${sm.valid}</button>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <div class="search"><${Icon} name="search" size=14 />
              <input placeholder="Search…" value=${query} onInput=${e=>setQuery(e.target.value)} /></div>
            <button class="btn btn-ghost btn-sm" onClick=${()=>dl('csv')}><${Icon} name="download" size=13 /> CSV</button>
            <button class="btn btn-ghost btn-sm" onClick=${()=>dl('json')}><${Icon} name="download" size=13 /> JSON</button>
          </div>
        </div>
        <div class="tbody" ref=${bodyRef}>
          ${shown.length===0 && html`<div style="padding:24px;text-align:center;color:var(--ink-gray-5);font-size:14px">No addresses to show${q?html` for “${query}”`:''}.</div>`}
          ${shown.map(r=>html`<div style="display:flex;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid var(--outline-gray-1)">
            <span class="mono" style="flex:1;min-width:0;font-size:12px;overflow-wrap:anywhere">${r.email}</span>
            ${r.typo_suggestion && html`<span class="pill pill-amber">did you mean ${r.typo_suggestion}?</span>`}
            ${r.disposable && html`<span class="pill pill-red">disposable</span>`}
            ${r.role_based && html`<span class="pill pill-gray">role</span>`}
            ${r.free_provider && html`<span class="pill pill-gray">free</span>`}
            <span class=${'pill '+(VERDICT_PILL[r.verdict]||'pill-gray')}>${r.verdict}</span>
          </div>`)}
        </div>
      </div>
      <p style="font-size:12px;color:var(--ink-gray-4);margin-top:8px;text-align:center">
        ${sm.validated.toLocaleString()} validated · ${sm.smtp_checked?'with SMTP probe':'MX + heuristics, no mailbox contacted'} · download is agent-ready CSV or JSON
      </p>`}

    ${!data && !loading && !error && html`
      <div class="note note-blue" style="margin-top:16px"><${Icon} name="zap" size=16 />
        <div>Deliverable means valid syntax and a live MX record with no junk-domain flags. Risky usually means a role inbox
          (info@, sales@) or a catch-all. Undeliverable is a broken address, a dead domain, or a disposable burner. Sendable
          is everything except undeliverable (deliverable plus risky) — the list an agent can actually send to.</div>
      </div>`}
  </div>`;
}

/* ════════════════════════ HOME — use-case templates ════════════════════════ */
/* Each card opens the right tool with a real example already loaded and run, so
   one click shows exactly what an agent would get back. Mapped only to features
   that work today — no roadmap cards. The four data plays mirror the work GTM
   teams wire up by hand in tools like Clay and Crustdata: find the people, map
   the account, catch the signal, clean the list. */

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'clean', icon:'sealCheck', name:'NoBounce', desc:'Validate and de-dupe an email list for agents', component: CleanTool };
