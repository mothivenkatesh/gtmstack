/* Synthetic Persona module */
import { API_BASE, Icon, html, useEffect, useState } from './core.js';


/* ── persona constants (mirrors api/_personas.py for instant, offline render) ── */
export const PERSONAS = [
  {id:'indie',  emoji:'🛠️', name:'The Indie Hacker',          tag:'Shipping a side project on a tight budget'},
  {id:'cto',    emoji:'🚀', name:'The Startup CTO',           tag:'Technical founder, ships under pressure'},
  {id:'agency', emoji:'🧰', name:'The Agency Dev',            tag:'Builds for paying clients on WordPress / Shopify'},
  {id:'infra',  emoji:'🛡️', name:'The Senior Infra Engineer', tag:'Reads the breach postmortem before integrating'},
  {id:'ai',     emoji:'🤖', name:'The AI-Native Builder',     tag:'Wiring up AI agents, wants an agent-ready layer'},
];

export const CTYPES = [
  ['landing','Landing page'],['email','Cold email'],['ad','Ad'],['social','Social post'],['sales','Sales line'],
];

export const SAMPLE_COPY = "Ship payments in an afternoon, not a sprint.\n\nOne install and a six-line snippet put a working checkout in your app today. No sales call, no sandbox paperwork, no contract to sign first.\n\n• Live in 15 minutes: paste the snippet, drop in your key, take a real payment.\n• Pricing on the page: flat per transaction, no minimums, no 'contact us'.\n• Agent-ready: an MCP endpoint your AI assistant can wire up without reading the docs.\n\nStart free, no card needed. Read the docs, run the example, keep building.";


export const tone = s => s>=70 ? 'green' : s>=45 ? 'amber' : 'red';

export const toneHex = {green:'#137949', amber:'#B35309', red:'#CC2929'};

export const ctypeLabel = c => (CTYPES.find(x=>x[0]===c)||[,c])[1];

export const overallNote = o => o>=70
  ? 'Most of your target developers would give this a look. Tighten the lowest-scoring reactions below and you are ready.'
  : o>=45
  ? 'This lands with some developers and loses others. The fixes below are where the points are.'
  : 'Most developers would scroll past this. Start with the fixes below before you launch.';

/* Shared persona result — gauge + reaction cards from one payload. Used by the
   Persona tool and the video-messaging play so both render identically. */

export function PersonaResult(d){
  const tn = tone(d.overall);
  return html`
      <div class="stack">
        <div class="glass-card gauge">
          <div style="text-align:center;flex-shrink:0">
            <div class="gauge-num" style=${`color:${toneHex[tn]}`}>${d.overall}</div>
            <div style="font-size:12px;color:var(--ink-gray-5);margin-top:4px">out of 100</div>
          </div>
          <div style="flex:1;min-width:210px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
              <span class=${'pill pill-'+tn} style="font-size:14px;padding:4px 16px">${d.verdict}</span>
              <span class="pill pill-gray"><${Icon} name=${d.engine==='ai'?'sparkles':'cpu'} size=12 /> ${d.engine==='ai'?'Live AI reactions':'Built-in model'}</span>
              <span class="pill pill-gray">${ctypeLabel(d.content_type)}</span>
            </div>
            <div class="gauge-bar"><div class="gauge-fill" style=${`width:${d.overall}%;background:${toneHex[tn]}`}></div></div>
            <div style="font-size:12px;color:var(--ink-gray-6);line-height:1.55;margin-top:8px">${overallNote(d.overall)}</div>
          </div>
        </div>

        ${d.structure && html`
        <div class="glass-card" style="padding:16px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
            <span style="font-weight:600;font-size:14px">Structure of a strong ${d.structure.label}</span>
            <span class=${'pill pill-'+tone(d.structure.score)}>${d.structure.have} of ${d.structure.total} parts</span>
          </div>
          <div class="gauge-bar" style="margin-bottom:16px"><div class="gauge-fill" style=${`width:${d.structure.score}%;background:${toneHex[tone(d.structure.score)]}`}></div></div>
          <div style="display:flex;flex-direction:column;gap:8px">
            ${d.structure.parts.map(p=>html`
              <div style="display:flex;align-items:flex-start;gap:8px;font-size:13px">
                <span style=${`color:${p.present?'var(--ink-green-2)':'var(--ink-gray-4)'};flex-shrink:0;margin-top:4px`}><${Icon} name=${p.present?'check':'minus'} size=14/></span>
                <div style="min-width:0;overflow-wrap:anywhere"><b style=${p.present?'':'color:var(--ink-gray-6)'}>${p.label}</b>
                  <span style="color:var(--ink-gray-5)"> — ${p.note}</span></div>
              </div>`)}
          </div>
          ${d.structure.missing.length>0 && html`<div style="font-size:12px;color:var(--ink-amber-2);margin-top:8px"><${Icon} name="wrench" size=12/> To complete this ${d.structure.label}: ${d.structure.missing.join(', ')}</div>`}
        </div>`}

        <div class="pcard-grid">
          ${d.results.map(r=>{ const t=tone(r.score); return html`
            <div class="glass-card pcard">
              <div class="pcard-head">
                <span class="pcard-emoji">${r.emoji}</span>
                <div style="flex:1;min-width:0">
                  <div class="pcard-name">${r.name}</div>
                  <div class="pcard-tag">${r.tagline}</div>
                </div>
                <span class=${'pill pill-'+t}>${r.verdict}</span>
              </div>
              <div>
                <div class="scorebar" style="margin-bottom:4px"><div class="scorefill" style=${`width:${r.score}%;background:${toneHex[t]}`}></div></div>
                <div class="score-meta"><span>Fit score</span><span class="mono" style=${`color:${toneHex[t]};font-weight:600`}>${r.score}/100</span></div>
              </div>
              <div class="quote" style=${`border-left-color:${toneHex[t]}`}>${r.reaction}</div>
              <div class="kv"><span class="kv-ic" style="color:var(--ink-green-2)"><${Icon} name="check" size=15 /></span>
                <div><b>What landed:</b> ${r.worked}</div></div>
              <div class="kv"><span class="kv-ic" style="color:var(--ink-amber-2)"><${Icon} name="wrench" size=14 /></span>
                <div><b>Biggest fix:</b> ${r.fix}</div></div>
            </div>`; })}
        </div>

        <p style="font-size:12px;color:var(--ink-gray-4);text-align:center;margin:4px 0 0">
          Reactions are simulated to help you sharpen copy, not a substitute for real users.
          Connect an AI key to upgrade from the built-in model to live reactions.
        </p>
      </div>`;
}


/* ════════════════════════ TOOL 1 — PERSONA PREVIEW ════════════════════════ */
export function PersonaTool({seed}){
  const [ctype, setCtype]   = useState('landing');
  const [copy, setCopy]     = useState('');
  const [selected, setSel]  = useState(PERSONAS.map(p=>p.id));
  const [loading, setLoad]  = useState(false);
  const [data, setData]     = useState(null);
  const [error, setErr]     = useState(null);

  const toggle = id => setSel(s => s.includes(id) ? s.filter(x=>x!==id) : [...s, id]);

  async function preview(opts = {}){
    const text = (opts.text ?? copy).trim();
    const type = opts.type || ctype;
    const who  = opts.personas || selected;
    if(!text){ setErr('Paste some copy first.'); return; }
    if(who.length===0){ setErr('Pick at least one developer to react.'); return; }
    setLoad(true); setErr(null);
    if(opts.text){ setCopy(text); setCtype(type); }
    try{
      const r = await fetch(`${API_BASE}/api/persona`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({text, type, personas:who}),
      });
      const j = await r.json();
      if(!r.ok){ setErr(j.error || 'Request failed.'); setData(null); }
      else setData(j);
    }catch(e){ setErr('Could not reach the engine. Is the local server running on :5000?'); }
    setLoad(false);
  }

  useEffect(()=>{ if(seed && seed.tool==='persona' && seed.payload){
    preview({text:seed.payload.copy, type:seed.payload.ctype||'landing'}); } }, [seed]);

  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Catch the copy that kills your launch, before launch day</h1>
      <p class="view-sub">Paste a headline, email, or ad. Five synthetic developers tell you what they’d think, and the fix worth the most.</p>
    </div>

    <div class="glass-card" style="padding:24px;margin-bottom:16px">
      <label class="field-label">1 · What kind of copy is this?</label>
      <div class="seg" style="margin-bottom:16px">
        ${CTYPES.map(([id,label])=>html`
          <button class=${ctype===id?'on':''} onClick=${()=>setCtype(id)}>${label}</button>`)}
      </div>

      <label class="field-label">2 · Paste your copy</label>
      <textarea class="copy-area" placeholder="e.g. Add payments to your app in 15 minutes. One install, six lines of code, live today..."
        value=${copy} onInput=${e=>setCopy(e.target.value)}></textarea>
      <div style="margin-top:8px;font-size:12px;color:var(--ink-gray-5)">
        Not sure what to try?
        <a style="color:var(--ink-blue-2);cursor:pointer;text-decoration:underline"
           onClick=${()=>{setCopy(SAMPLE_COPY);setCtype('landing');}}>Load sample landing-page copy</a>
      </div>

      <label class="field-label" style="margin-top:16px">3 · Who should react? <span style="font-weight:400;color:var(--ink-gray-5)">(${selected.length} selected)</span></label>
      <div class="pchips">
        ${PERSONAS.map(p=>html`
          <div class=${'pchip'+(selected.includes(p.id)?' on':'')} onClick=${()=>toggle(p.id)} title=${p.tag}>
            <span class="pe">${p.emoji}</span><span class="pn">${p.name}</span>
            <span class="pck"><${Icon} name="check" size=14 /></span>
          </div>`)}
      </div>

      <div style="display:flex;align-items:center;gap:16px;margin-top:24px;flex-wrap:wrap">
        <button class="btn btn-primary btn-lg" disabled=${loading} onClick=${preview}>
          ${loading ? html`<${Icon} name="loader" size=15 cls="spin" /> Reading reactions` : html`<${Icon} name="sparkles" size=15 /> Preview reactions`}
        </button>
        <span style="font-size:12px;color:var(--ink-gray-5)">Simulated reactions to sharpen your copy. Not real people.</span>
      </div>
    </div>

    ${error && html`<div class="errbox" style="margin-bottom:16px">
      <${Icon} name="alert" size=18 />
      <div><div style="font-weight:600;margin-bottom:4px">Couldn’t run the preview</div>
      <div style="font-size:14px;opacity:.85">${error}</div></div>
    </div>`}

    ${loading && !data && html`
      <div class="glass-card" style="padding:24px;margin-bottom:16px;display:flex;gap:16px">
        <div class="skel" style="height:48px;width:48px;border-radius:var(--radius)"></div>
        <div style="flex:1;display:flex;flex-direction:column;gap:8px;justify-content:center">
          <div class="skel" style="height:14px;width:40%"></div><div class="skel" style="height:10px;width:70%"></div></div>
      </div>
      <div class="pcard-grid">
        ${[0,1,2].map(()=>html`<div class="glass-card pcard"><div class="skel" style="height:46px;width:60%"></div>
          <div class="skel" style="height:7px;width:100%"></div><div class="skel" style="height:40px;width:100%"></div></div>`)}
      </div>`}

    ${data && PersonaResult(data)}
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'persona', icon:'users', name:'Synthetic Persona', desc:'See how developers react to your copy', component: PersonaTool };
