/* Reports + competitive monitor module */
import { API_BASE, DateRange, Icon, Picker, SENT_PILL, agoFrom, drActive, h, html, inDateRange, platIcon, useEffect, useState } from './core.js';


/* ── Competitive monitor panel (lives inside the Reports tab) ── */
export const TRACK_PILL = {ok:'pill-green', quiet:'pill-gray', blocked:'pill-red',
  error:'pill-red', timeout:'pill-amber', needs_connection:'pill-amber'};

export const TRACK_LABEL = {ok:'live', quiet:'quiet', blocked:'blocked', error:'error',
  timeout:'timed out', needs_connection:'not connected'};


export const lines = a => (a||[]).join('\n');

export const toList = s => (s||'').split(/[\n,]/).map(x=>x.trim()).filter(Boolean);


export function GroupEditor({group, onSaved}){
  const seed = g => ({...g, _kw:lines(g.keywords), _comp:lines(g.competitors),
    _subs:lines(g.subreddits), _rev:lines(g.review_brands), _quora:lines(g.quora_questions)});
  const [f,setF]=useState(seed(group));
  const [busy,setBusy]=useState(false);
  const [msg,setMsg]=useState('');
  useEffect(()=>{ setF(seed(group)); setMsg(''); },[group&&group.id]);
  function set(k,v){ setF(o=>({...o,[k]:v})); }
  async function save(){
    setBusy(true); setMsg('');
    const body={ id:f.id, name:f.name, window_days:Number(f.window_days)||10,
      include_comments:!!f.include_comments,
      keywords:toList(f._kw), competitors:toList(f._comp),
      subreddits:toList(f._subs), review_brands:toList(f._rev),
      quora_questions:toList(f._quora) };
    try{
      const r=await fetch(`${API_BASE}/api/groups`,{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(r.status===401) setMsg('Editing is disabled on the hosted site. Edit api/_store/groups.json on the Mac.');
      else { const j=await r.json(); if(j.error) setMsg(j.error); else { setMsg('Saved.'); onSaved&&onSaved(); } }
    }catch(e){ setMsg('Save failed.'); }
    setBusy(false);
  }
  const ta=(label,key,ph)=>html`<label style="display:block;margin-bottom:8px">
    <span style="font-size:12px;color:var(--ink-gray-6)">${label}</span>
    <textarea rows=2 value=${f[key]!==undefined?f[key]:''} onInput=${e=>set(key,e.target.value)}
      placeholder=${ph} style="width:100%;margin-top:4px;padding:8px;border:1px solid var(--outline-gray-2);border-radius:var(--radius);font-size:12px;font-family:inherit;resize:vertical"></textarea></label>`;
  return html`<div style="padding:4px 4px">
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px">
      <label style="font-size:12px;color:var(--ink-gray-6)">Window (days)
        <input type="number" min=1 max=90 value=${f.window_days} onInput=${e=>set('window_days',e.target.value)}
          style="width:64px;margin-left:8px;padding:4px;border:1px solid var(--outline-gray-2);border-radius:var(--radius-sm)"/></label>
      <label style="font-size:12px;color:var(--ink-gray-6);display:flex;align-items:center;gap:8px">
        <input type="checkbox" checked=${!!f.include_comments} onChange=${e=>set('include_comments',e.target.checked)}/> include Reddit comments</label>
    </div>
    ${ta('Keywords (one per line or comma-separated)','_kw','razorpay\\npayment gateway india')}
    ${ta('Competitor brands','_comp','razorpay, payu, ccavenue')}
    ${ta('Subreddits','_subs','developersIndia, IndiaStartups')}
    ${ta('Review brands (G2/Capterra/TrustPilot)','_rev','cashfree, razorpay')}
    ${ta('Quora question URLs (the reliable Quora path)','_quora','https://www.quora.com/...')}
    <div style="display:flex;align-items:center;gap:8px;margin-top:8px">
      <button onClick=${save} disabled=${busy} class="pill pill-blue" style="cursor:pointer;border:none">
        <${Icon} name=${busy?'loader':'check'} size=12 cls=${busy?'spin':''}/> ${busy?'Saving...':'Save group'}</button>
      ${msg && html`<span style="font-size:12px;color:${msg==='Saved.'?'var(--ink-green-2)':'var(--ink-gray-6)'}">${msg}</span>`}
    </div>
  </div>`;
}


export function MonitorPanel(){
  const [ov,setOv]=useState(null);
  const [gid,setGid]=useState(null);
  const [busy,setBusy]=useState(false);
  const [err,setErr]=useState('');
  const [note,setNote]=useState('');
  const [edit,setEdit]=useState(false);
  const [mrange,setMrange]=useState({preset:'all'});

  useEffect(()=>{ load(); },[]);
  async function load(){
    try{
      const j = await fetch(`${API_BASE}/api/monitor`).then(r=>r.json());
      setOv(j); if(j.groups && j.groups[0] && !gid) setGid(j.groups[0].id);
    }catch(e){ setErr('Could not load the monitor (is the backend running?).'); }
  }
  async function runNow(){
    setBusy(true); setErr(''); setNote('');
    try{
      const r = await fetch(`${API_BASE}/api/monitor`,{method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({only:gid})});
      if(r.status===401){ setErr('Run-now is disabled on the hosted site. The 9am job on the Mac populates this (it needs the local session + residential IP).'); }
      else { const j=await r.json(); if(j.error) setErr(j.error);
        else { setNote(`Scan done: ${j.total||0} found, ${j.inserted||0} new in ${j.elapsed_s||0}s.`); await load(); } }
    }catch(e){ setErr('Run failed.'); }
    setBusy(false);
  }

  if(!ov) return html`<div class="glass-card" style="padding:24px;color:var(--ink-gray-5)">
    ${err||'Loading the monitor...'}</div>`;

  const g = (ov.groups||[]).find(x=>x.id===gid) || (ov.groups||[])[0];
  const mentions = (ov.mentions && g && ov.mentions[g.id]) || [];
  const lr = ov.last_run;
  const grpRun = lr && (lr.groups||[]).find(x=>x.group_id===(g&&g.id));
  const ts = mentions.reduce((a,m)=>{a[m.sentiment]=(a[m.sentiment]||0)+1;return a;},{});
  const staleH = lr && lr.finished_at ? ((Date.now()-new Date(lr.finished_at))/3.6e6) : null;
  const stale = staleH!==null && staleH>26;
  const sheetGid = grpRun && grpRun.sheets && grpRun.sheets.gid;
  const sheetLink = ov.sheet_url ? (ov.sheet_url + (sheetGid!=null?('#gid='+sheetGid):'')) : '';

  return html`<div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
      <${Picker} icon="binoculars" label="Group" caption=${g?`${g.name} · ${g.window_days}d`:'Pick a group'} active=${!!(g&&g.id)} minW=240 title="Monitor group">
        ${close=>html`<div>${(ov.groups||[]).map(x=>{ const on=x.id===(g&&g.id);
          return html`<button type="button" class="pk-item" role="menuitemradio" aria-checked=${on}
            onClick=${()=>{ setGid(x.id); close(); }}>${x.name}
            <span style="color:var(--ink-gray-5)">· ${x.window_days}d</span>
            ${on?html`<span class="pk-ck"><${Icon} name="check" size=14/></span>`:''}</button>`; })}</div>`}
      </${Picker}>
      <span style="flex:1"></span>
      ${sheetLink && html`<a href=${sheetLink} target="_blank" rel="noopener" class="pk-btn" style="text-decoration:none"><${Icon} name="sheet" size=15/> Google Sheet</a>`}
      <button onClick=${runNow} disabled=${busy} class="pk-btn">
        <${Icon} name=${busy?'loader':'refresh'} size=15 cls=${busy?'spin':''} /> ${busy?'Scanning...':'Run now'}</button>
    </div>

    ${err && html`<div class="glass-card" style="padding:16px;margin-bottom:16px;color:var(--ink-red-3)"><${Icon} name="alert" size=14/> ${err}</div>`}
    ${note && html`<div class="glass-card" style="padding:16px;margin-bottom:16px;color:var(--ink-green-2)"><${Icon} name="check" size=14/> ${note}</div>`}

    ${!lr ? html`<div class="glass-card" style="padding:16px;margin-bottom:16px;color:var(--ink-gray-6);font-size:12px">
        No run recorded yet. The monitor runs daily at 9am IST on the Mac. Below is whatever is already in the store.</div>`
      : stale ? html`<div class="glass-card" style="padding:16px;margin-bottom:16px;color:var(--ink-amber-2)">
        <${Icon} name="alert" size=14/> Last run was ${Math.round(staleH)}h ago (over 26h). Check the Mac is awake and logged in.</div>`
      : html`<div style="font-size:12px;color:var(--ink-gray-5);margin-bottom:16px">Last scan ${agoFrom(lr.finished_at)} · ${lr.total||0} mentions, ${lr.inserted||0} new · ${lr.elapsed_s}s</div>`}

    ${grpRun && grpRun.track_status && html`<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      ${Object.entries(grpRun.track_status).map(([src,st])=>html`
        <span class=${'pill '+(TRACK_PILL[st]||'pill-gray')}><${Icon} name=${platIcon(src)} size=11/> ${src}: ${TRACK_LABEL[st]||st}</span>`)}
    </div>`}

    ${grpRun && (grpRun.spikes||[]).length>0 && html`<div class="glass-card" style="padding:16px;margin-bottom:16px;border-left:3px solid var(--ink-red-3)">
      <div style="font-weight:600;color:var(--ink-red-3);margin-bottom:4px"><${Icon} name="zap" size=14/> Moment marketing: a competitor is taking heat</div>
      ${grpRun.spikes.map(sp=>html`<div style="font-size:14px;color:var(--ink-gray-7)">${sp.brand}: ${sp.last24} negative mentions in 24h (baseline ${sp.daily_baseline}/day)</div>`)}
    </div>`}

    <div class="glass-card" style="padding:0;margin-bottom:16px">
      <div onClick=${()=>setEdit(o=>!o)} style="display:flex;align-items:center;gap:8px;padding:16px 16px;cursor:pointer">
        <${Icon} name="wrench" size=14/> <span style="font-weight:600;font-size:14px">Edit what ${g&&g.name} tracks</span>
        <span style="flex:1"></span><${Icon} name=${edit?'minus':'plus'} size=13/>
      </div>
      ${edit && g && html`<div style="padding:0 16px 16px"><${GroupEditor} group=${g} onSaved=${load}/></div>`}
    </div>

    <div class="kpi-grid" style="margin-bottom:16px">
      <div class="glass-card kpi"><div class="kpi-label">Mentions in store</div><div class="kpi-value">${mentions.length}</div></div>
      <div class="glass-card kpi"><div class="kpi-label">Positive</div><div class="kpi-value" style="color:var(--ink-green-2)">${ts.positive||0}</div></div>
      <div class="glass-card kpi"><div class="kpi-label">Negative</div><div class="kpi-value" style="color:var(--ink-red-3)">${ts.negative||0}</div></div>
      <div class="glass-card kpi"><div class="kpi-label">Neutral</div><div class="kpi-value">${ts.neutral||0}</div></div>
    </div>

    ${!ov.sheets_configured && html`<div style="font-size:12px;color:var(--ink-gray-5);margin-bottom:16px"><${Icon} name="alert" size=12/> Google Sheets export is off. Set GOOGLE_SA_JSON + GTMSTACK_SHEET_URL to push rows to a shared sheet.</div>`}

    ${(()=>{ const shown=mentions.filter(m=>inDateRange(m.post_ts, mrange));
      return html`<div class="glass-card" style="padding:16px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <span style="font-weight:600">Recent mentions</span>
        <span style="font-size:12px;color:var(--ink-gray-5)">${drActive(mrange)?`${shown.length} of ${mentions.length}`:mentions.length}</span>
        <span style="flex:1;min-width:20px"></span>
        ${mentions.length>0 && html`<${DateRange} value=${mrange} onChange=${setMrange}/>`}
      </div>
      <div style="font-size:12px;color:var(--ink-gray-5);margin-bottom:8px">Instagram + Facebook are out of scope (not compliantly scrapeable). G2 needs a licensed API.</div>
      ${mentions.length===0 ? html`<div style="color:var(--ink-gray-5)">No mentions stored yet for ${g&&g.name}.</div>`
      : shown.length===0 ? html`<div style="color:var(--ink-gray-5)">No mentions in this date range. Widen it to see the rest.</div>`
      : shown.slice(0,80).map(m=>html`
        <div style="padding:8px 0;border-top:1px solid var(--outline-gray-2)">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
            <span class="pill pill-gray"><${Icon} name=${platIcon(m.platform)} size=12/> ${m.platform}</span>
            ${m.kind && m.kind!=='post' && html`<span class="pill pill-gray"><${Icon} name=${m.kind==='comment'?'comment':'review'} size=11/> ${m.kind}</span>`}
            <span class=${'pill '+(SENT_PILL[m.sentiment]||'pill-gray')}>${m.sentiment||'?'}</span>
            ${m.enrich_mode==='model' && html`<span class="pill pill-blue" title="tagged by the model"><${Icon} name="sparkles" size=10/> model</span>`}
            ${m.company && m.company!=='Unknown' && html`<span class="pill pill-blue"><${Icon} name="building" size=11/> ${m.company}</span>`}
            ${m.brand && html`<span class="pill pill-gray">${m.brand}</span>`}
            ${m.rating && html`<span class="pill pill-amber"><${Icon} name="star" size=10/> ${m.rating}</span>`}
            ${m.author && html`<span style="font-size:12px;color:var(--ink-gray-6)">${m.author}</span>`}
            ${m.post_ts && html`<span style="font-size:12px;color:var(--ink-gray-5)">· ${agoFrom(m.post_ts)}</span>`}
            ${m.from_archive && html`<span class="pill pill-gray" title="from a Wayback snapshot"><${Icon} name="archive" size=10/> as-of ${m.snapshot_ts||'archive'}</span>`}
          </div>
          <div style="font-size:14px;line-height:1.5;color:var(--ink-gray-8);overflow-wrap:anywhere">${(m.body||m.text||'').slice(0,300)}</div>
          ${m.url && html`<a href=${m.url} target="_blank" rel="noopener" style="font-size:12px;color:var(--ink-violet-1);text-decoration:none"><${Icon} name="externalLink" size=11 /> open</a>`}
        </div>`)}
    </div>`; })()}
  </div>`;
}


export function ReportsTool(){
  const [mode,setMode]=useState('briefs');
  const [groups,setGroups]=useState([]);
  const [gid,setGid]=useState(null);
  const [rep,setRep]=useState(null);
  const [busy,setBusy]=useState(false);
  const [err,setErr]=useState('');
  const [showLog,setShowLog]=useState(false);
  const [topRange,setTopRange]=useState({preset:'all'});

  useEffect(()=>{ fetch(`${API_BASE}/api/report?groups=1`).then(r=>r.json())
    .then(j=>{ const gs=j.groups||[]; setGroups(gs); if(gs[0]) setGid(gs[0].id); })
    .catch(()=>setErr('Could not load groups (is the backend running?).')); },[]);
  useEffect(()=>{ if(gid) loadLatest(gid); },[gid]);

  async function loadLatest(id){
    setErr('');
    try{
      const j = await fetch(`${API_BASE}/api/report?group=${encodeURIComponent(id)}`).then(r=>r.json());
      setRep(j && !j.error ? j : null);
    }catch(e){ setErr('Could not load the report.'); }
  }
  async function runNow(){
    if(!gid) return; setBusy(true); setErr('');
    try{
      const r = await fetch(`${API_BASE}/api/report`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({group:gid, budget_s:45})});
      if(r.status===401){ setErr('Run-now is disabled on the hosted site. The 8am job populates this tab.'); }
      else { const j=await r.json(); if(j.error) setErr(j.error); else setRep(j); }
    }catch(e){ setErr('Run failed.'); }
    setBusy(false);
  }

  const g = groups.find(x=>x.id===gid);
  const s = (rep && rep.sentiment) || {positive:0,negative:0,neutral:0};

  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">${mode==='monitor'?'Competitive monitor':'Daily signal briefs, one per keyword group'}</h1>
      <p class="view-sub">${mode==='monitor'
        ? html`Every morning at 9am IST the monitor scans Reddit, Quora, review sites (TrustPilot, Capterra), and X for competitor and Cashfree mentions, tags sentiment and company, and pushes deduped rows to a Google Sheet. The store here is the source of truth.`
        : html`Every morning at 9am IST a Carlsen-ordered scan reads each group across GitHub, YouTube, Reddit, X, and LinkedIn, tags sentiment and the author's company, and files the brief here. Pick a group, or run one now.`}</p>
    </div>

    <div style="display:inline-flex;gap:4px;padding:4px;border:1px solid var(--outline-gray-2);border-radius:var(--radius);margin-bottom:16px">
      <button onClick=${()=>setMode('briefs')} class=${'pill '+(mode==='briefs'?'pill-blue':'pill-gray')} style="cursor:pointer;border:none"><${Icon} name="newspaper" size=12/> Daily briefs</button>
      <button onClick=${()=>setMode('monitor')} class=${'pill '+(mode==='monitor'?'pill-blue':'pill-gray')} style="cursor:pointer;border:none"><${Icon} name="binoculars" size=12/> Competitive monitor</button>
    </div>

    ${mode==='monitor' ? html`<${MonitorPanel} />` : html`<div>

    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
      <${Picker} icon="newspaper" label="Group" caption=${(g&&g.name)||'Pick a group'} active=${!!gid} minW=220 title="Keyword group">
        ${close=>html`<div>${groups.map(x=>{ const on=x.id===gid;
          return html`<button type="button" class="pk-item" role="menuitemradio" aria-checked=${on}
            onClick=${()=>{ setGid(x.id); close(); }}>${x.name}
            ${on?html`<span class="pk-ck"><${Icon} name="check" size=14/></span>`:''}</button>`; })}
          ${groups.length===0?html`<div class="pk-lbl">No groups loaded</div>`:''}</div>`}
      </${Picker}>
      <span style="flex:1"></span>
      <button onClick=${runNow} disabled=${busy} class="pk-btn">
        <${Icon} name=${busy?'loader':'refresh'} size=15 cls=${busy?'spin':''} /> ${busy?'Running...':'Run now'}</button>
    </div>

    ${err && html`<div class="glass-card" style="padding:16px;margin-bottom:16px;color:var(--ink-red-3)"><${Icon} name="alert" size=14/> ${err}</div>`}

    ${!rep ? html`
      <div class="glass-card" style="padding:32px;text-align:center;color:var(--ink-gray-5)">
        <${Icon} name="newspaper" size=26 /><div style="margin-top:8px">No brief for ${(g&&g.name)||'this group'} yet.</div>
        <div style="margin-top:4px;font-size:12px">It runs daily at 8am IST. Or hit Run now.</div>
      </div>`
    : html`
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">
        <span class="pill pill-gray">${(rep.totals.sources_hit||[]).join(', ')||'no sources'}</span>
        <span style="font-size:12px;color:var(--ink-gray-5)">generated ${agoFrom(rep.generated_at)}</span>
        ${rep.engine && rep.engine!=='none' && html`<span class=${'pill '+(rep.engine==='ai'?'pill-green':'pill-gray')}>engine: ${rep.engine}</span>`}
      </div>

      <div class="kpi-grid" style="margin-bottom:16px">
        <div class="glass-card kpi"><div class="kpi-label">Mentions</div><div class="kpi-value">${rep.totals.mentions}</div></div>
        <div class="glass-card kpi"><div class="kpi-label">Positive</div><div class="kpi-value" style="color:var(--ink-green-2)">${s.positive}</div></div>
        <div class="glass-card kpi"><div class="kpi-label">Negative</div><div class="kpi-value" style="color:var(--ink-red-3)">${s.negative}</div></div>
        <div class="glass-card kpi"><div class="kpi-label">Neutral</div><div class="kpi-value">${s.neutral}</div></div>
      </div>

      ${rep.synthesis && rep.synthesis.summary && html`
        <div class="glass-card" style="padding:16px;margin-bottom:16px">
          <div style="font-weight:600;margin-bottom:8px">What is moving</div>
          <div style="color:var(--ink-gray-7);line-height:1.55">${rep.synthesis.summary}</div>
        </div>`}

      ${(rep.share_of_voice||[]).length>0 && html`
        <div class="glass-card" style="padding:16px;margin-bottom:16px">
          <div style="font-weight:600;margin-bottom:8px">Share of voice</div>
          <table style="width:100%;border-collapse:separate;border-spacing:0;font-size:12px">
            <thead><tr style="text-align:left;color:var(--ink-gray-5)">
              <th style="padding:4px 8px">Brand</th><th>Mentions</th><th>Engagement</th><th>Reach</th></tr></thead>
            <tbody>${rep.share_of_voice.map(r=>html`<tr style="border-top:1px solid var(--outline-gray-2)">
              <td style="padding:8px">${r.brand}${r.you?html` <span class="pill pill-blue">you</span>`:''}</td>
              <td>${r.mentions}</td><td>${(r.engagement||0).toLocaleString()}</td><td>${r.reach_pct}%</td></tr>`)}</tbody>
          </table>
        </div>`}

      ${(()=>{ const posts=rep.top_posts||[]; const shown=posts.filter(p=>inDateRange(p.ts, topRange));
        return html`<div class="glass-card" style="padding:16px;margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="font-weight:600">Top mentions</span>
          <span style="font-size:12px;color:var(--ink-gray-5)">${drActive(topRange)?`${shown.length} of ${posts.length}`:posts.length}</span>
          <span style="flex:1"></span>
          ${posts.length>0 && html`<${DateRange} value=${topRange} onChange=${setTopRange}/>`}
        </div>
        ${posts.length===0 ? html`<div style="color:var(--ink-gray-5)">No mentions surfaced.</div>`
        : shown.length===0 ? html`<div style="color:var(--ink-gray-5)">No mentions in this date range. Widen it to see the rest.</div>`
        : shown.map(p=>html`
          <div style="padding:8px 0;border-top:1px solid var(--outline-gray-2)">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
              <span class="pill pill-gray"><${Icon} name=${platIcon(p.platform)} size=12 /> ${p.platform}</span>
              <span class=${'pill '+(SENT_PILL[p.sentiment]||'pill-gray')}>${p.sentiment}</span>
              ${p.company && p.company!=='Unknown' && html`<span class="pill pill-blue"><${Icon} name="building" size=11/> ${p.company}</span>`}
              ${p.profile_url ? html`<a href=${p.profile_url} target="_blank" rel="noopener" style="font-size:12px;color:var(--ink-violet-1);text-decoration:none">${p.author?('@'+p.author):'author'}</a>`
                : html`<span style="font-size:12px;color:var(--ink-gray-6)">${p.author||''}</span>`}
              ${p.ago && html`<span style="font-size:12px;color:var(--ink-gray-5)">· ${p.ago}</span>`}
            </div>
            <div style="font-size:14px;line-height:1.5;color:var(--ink-gray-8);overflow-wrap:anywhere">${(p.text||'').slice(0,280)}</div>
            ${p.url && html`<a href=${p.url} target="_blank" rel="noopener" style="font-size:12px;color:var(--ink-violet-1);text-decoration:none"><${Icon} name="externalLink" size=11 /> open</a>`}
          </div>`)}
      </div>`; })()}

      ${(rep.strategy_log||[]).length>0 && html`
        <div class="glass-card" style="padding:0;margin-bottom:16px">
          <div onClick=${()=>setShowLog(o=>!o)} style="display:flex;align-items:center;gap:8px;padding:16px 16px;cursor:pointer">
            <${Icon} name="knight" size=15 /> <span style="font-weight:600">Carlsen scan log</span>
            <span style="flex:1"></span><${Icon} name=${showLog?'minus':'plus'} size=13 />
          </div>
          ${showLog && html`<div style="padding:0 16px 16px">
            <div style="font-size:12px;color:var(--ink-gray-5);margin-bottom:8px">The move order: safe sources first, LinkedIn (the king) last and sequential, resigned on a challenge.</div>
            ${rep.strategy_log.map(m=>html`<div style="font-family:ui-monospace,monospace;font-size:12px;padding:4px 0;color:var(--ink-gray-7)">
              ${m.move==='clock' ? html`<span style="color:var(--ink-amber-2)">clock · ${m.note}</span>`
              : html`${m.is_king?html`<${Icon} name="knight" size=11/> `:''}${m.move}: ${m.note?m.note:`${m.found} found, ${m.fails} fail, ${m.keywords} kw, ${m.budget_s}s`}`}
            </div>`)}
          </div>`}
        </div>`}
    `}
    </div>`}
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'reports', icon:'newspaper', name:'Reports', desc:'Daily signal briefs + the competitive monitor', component: ReportsTool };
