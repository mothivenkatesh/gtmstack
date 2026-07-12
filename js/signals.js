/* Signals module: person/company/keyword lookups */
import { API_BASE, DateRange, Icon, Picker, drActive, h, html, inDateRange, initialsOf, joinDots, useEffect, useState } from './core.js';


/* ════════════════════════ SIGNALS ════════════════════════ */
export const SIG_META = {
  github:   {label:'GitHub',   icon:'github',   color:'#1A1A1A'},
  reddit:   {label:'Reddit',   icon:'reddit',   color:'#FF4500'},
  linkedin: {label:'LinkedIn', icon:'linkedin', color:'#0A66C2'},
  x:        {label:'X',        icon:'twitter',  color:'#0F0F0F'},
  youtube:  {label:'YouTube',  icon:'youtube',  color:'#FF0000'},
  trustpilot:{label:'TrustPilot', icon:'trustpilot', color:'#00B67A'},
  quora:    {label:'Quora',    icon:'quora',    color:'#B92B27'},
  capterra: {label:'Capterra', icon:'capterra', color:'#FF9D28'},
  g2:       {label:'G2',       icon:'g2',       color:'#FF492C'},
};

export const SIG_ORDER = ['github', 'reddit', 'linkedin', 'x', 'youtube', 'trustpilot', 'quora', 'capterra', 'g2'];

export const ACT_ICON = {post:'pen', comment:'message', reply:'message', share:'refresh', repost:'refresh', like:'star',
  commit:'code', pr:'code', issue:'alert', star:'star', fork:'refresh', create:'plus', release:'zap', video:'film',
  review:'review', answer:'quora'};

/* Three lookup units. Each has its own source set + framing. Person resolves a
   single footprint; company adds the people who work there; keyword is a live
   mentions feed. The source order per unit matches the engine's adapters. */

export const UNIT_META = {
  person:  {icon:'userSearch', label:'Person',  sources:['github','reddit','linkedin','x','youtube'],
            ph:'A handle or profile URL (GitHub, Reddit, LinkedIn, X, or YouTube)',
            bulkPh:'One handle or profile URL per line', cta:'Find footprint',
            hint:'Who someone is and what they posted most recently across their channels.'},
  company: {icon:'building',   label:'Company', sources:['github','linkedin','x','reddit','youtube'],
            ph:'A company name or domain, e.g. stripe.com',
            bulkPh:'One company name or domain per line', cta:'Map the company',
            hint:'The company footprint per source, plus the people who work there.'},
  keyword: {icon:'hash',       label:'Keyword', sources:['github','x','reddit','youtube','trustpilot','quora'],
            ph:'A topic or phrase to track, e.g. model context protocol',
            bulkPh:'One topic or phrase per line', cta:'Track mentions',
            hint:'A live mentions feed: what is being said about this right now.'},
};

export function parseQuery(raw){
  const q = (raw || '').trim();
  if(!q) return {kind:'empty'};
  if(/^https?:\/\//i.test(q) || /\b(?:github|linkedin|reddit|x|twitter|youtube)\.com\//i.test(q)){
    const host = (q.match(/(github|linkedin|reddit|x|twitter|youtube)\.com/i) || [])[1];
    if(host){
      const h = host.toLowerCase();
      const path = q.replace(/^https?:\/\//i,'').replace(/[?#].*$/,'').replace(/\/+$/,'');
      if(h === 'github'){ const m = path.match(/github\.com\/([^\/]+)/i);
             if(m && !/^(orgs|topics|search|marketplace|sponsors|features|about|pricing|collections|trending|notifications|settings|explore)$/i.test(m[1])) return {kind:'url', platform:'github', handle:m[1]}; }
      else if(h === 'linkedin'){ const m = path.match(/\/in\/([^\/]+)/i); if(m) return {kind:'url', platform:'linkedin', handle:decodeURIComponent(m[1])}; }
      else if(h === 'reddit'){ const m = path.match(/\/(?:user|u)\/([^\/]+)/i); if(m) return {kind:'url', platform:'reddit', handle:m[1]}; }
      else if(h === 'youtube'){ const m = path.match(/youtube\.com\/(?:@|c\/|user\/|channel\/)?([^\/]+)/i);
             if(m && !/^(watch|results|feed|playlist|shorts|hashtag|embed)$/i.test(m[1])) return {kind:'url', platform:'youtube', handle:m[1].replace(/^@/,'')}; }
      else { const seg = path.split('/').slice(1).find(Boolean);
             if(seg && !/^(i|home|search|hashtag|explore|messages|notifications)$/i.test(seg)) return {kind:'url', platform:'x', handle:seg.replace(/^@/,'')}; }
    }
    return {kind:'url-unknown'};
  }
  if(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(q)) return {kind:'email', value:q};
  if(!/\s/.test(q)) return {kind:'handle', value:q.replace(/^@/,'')};
  return {kind:'name', value:q};
}


export function SignalCard({s}){
  const m = SIG_META[s.platform] || {label:s.platform, icon:'globe', color:'#525252'};
  const ok = s.status === 'ok';
  const emptyMeta = {
    needs_connection: ['plug',       'Connect to read this source'],
    not_found:        ['userSearch', 'No match on ' + m.label],
    error:            ['alert',      'Could not read ' + m.label],
  }[s.status] || ['alert', 'No data'];

  return html`
  <div class=${'glass-card sig-card' + (ok ? '' : ' dim')}>
    <div class="sig-head">
      <span style=${`position:absolute;left:0;top:0;bottom:0;width:3px;background:${m.color}`}></span>
      <span class="sig-ava" style=${`background:${m.color}`}>
        ${initialsOf(s.display_name || s.handle)}
        ${s.avatar && html`<img src=${s.avatar} alt="" referrerpolicy="no-referrer" onError=${e=>e.target.remove()}
          style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover" />`}
      </span>
      <div class="sig-id">
        <span class="sig-plat" style=${`color:${m.color}`}><${Icon} name=${m.icon} size=12 /> ${m.label}</span>
        <div class="sig-name">${s.display_name || s.handle || '—'}</div>
        ${s.headline && html`<div class="sig-headline">${s.headline}</div>`}
        ${(s.handle || s.location) && html`<div class="sig-meta">
          ${s.handle && html`<span>@${String(s.handle).replace(/^@/, '')}</span>`}
          ${s.location && html`<span><${Icon} name="mapPin" size=11 /> ${s.location}</span>`}
        </div>`}
      </div>
      ${s.profile_url && html`<a href=${s.profile_url} target="_blank" rel="noopener noreferrer" title="Open profile"
        style="color:var(--ink-gray-4);flex-shrink:0;margin-top:4px"><${Icon} name="externalLink" size=15 /></a>`}
    </div>

    ${ok && (s.stats||[]).length > 0 && html`<div class="sig-stats">
      ${s.stats.map(st=>html`<div class="sig-stat"><b>${st.value}</b><span>${st.label}</span></div>`)}
    </div>`}

    ${ok
      ? ((s.activity||[]).length > 0
          ? html`<div class="sig-body">
              ${s.activity.map(a=>html`<div class="sig-act">
                <span class="sig-act-ic"><${Icon} name=${ACT_ICON[a.kind] || 'pen'} size=14 /></span>
                <div class="sig-act-main">
                  <div class="sig-act-text">${a.url
                    ? html`<a href=${a.url} target="_blank" rel="noopener noreferrer" style="color:inherit">${a.text}</a>`
                    : a.text}</div>
                  <div class="sig-act-meta">${joinDots([
                    a.kind && html`<span style="text-transform:capitalize">${a.kind}</span>`,
                    a.where && html`<span>${a.where}</span>`,
                    a.ago && html`<span>${a.ago}</span>`,
                    ...(a.engagement || []).map(e=>html`<span class="sig-act-eng">${e}</span>`),
                  ])}</div>
                </div>
              </div>`)}
            </div>`
          : html`<div class="sig-empty"><div class="se-title">Profile found, no recent public posts.</div></div>`)
      : html`<div class="sig-empty">
          <span class="se-ic"><${Icon} name=${emptyMeta[0]} size=17 /></span>
          <div class="se-title">${emptyMeta[1]}</div>
          ${s.note && html`<div class="se-note">${s.note}</div>`}
        </div>`}
  </div>`;
}

/* Company unit: the people who work there (GitHub org members today). Each row
   is clickable to pivot into a person lookup on that handle. */

export function PersonRoster({people, onPick}){
  if(!people || !people.length) return null;
  return html`
    <div class="sec-h"><span class="sec-ic"><${Icon} name="users" size=14 /></span> People who work here
      <span class="sec-n">${people.length} found</span></div>
    <div class="roster">
      ${people.map(p=>{ const m = SIG_META[p.platform] || {color:'#525252', icon:'globe'};
        return html`<div class="rost" onClick=${()=>onPick && onPick(p)} title="Look up this person"
          style="cursor:pointer">
          <span class="rost-ava" style=${`background:${m.color}`}>
            ${initialsOf(p.display_name || p.handle)}
            ${p.avatar && html`<img src=${p.avatar} alt="" referrerpolicy="no-referrer" onError=${e=>e.target.remove()}
              style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover" />`}
          </span>
          <div class="rost-id">
            <div class="rost-name">${p.display_name || p.handle}</div>
            <div class="rost-sub"><span style=${`color:${m.color};display:inline-flex`}><${Icon} name=${m.icon} size=11 /></span>
              @${String(p.handle).replace(/^@/,'')}</div>
          </div>
        </div>`; })}
    </div>`;
}


/* Keyword unit: one merged, newest-first mentions feed across the sources. */
export function FeedList({feed, sources}){
  const errs = (sources||[]).filter(s=>s.status!=='ok');
  const [range,setRange]=useState({preset:'all'});
  const all = feed||[];
  const shown = all.filter(a=>inDateRange(a.ts, range));
  return html`
    ${(sources||[]).length>0 && html`<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      ${(sources||[]).map(s=>{ const m = SIG_META[s.platform]||{label:s.platform,color:'#525252',icon:'globe'};
        const ok = s.status==='ok'; const n = (s.activity||[]).length;
        return html`<span class="pill ${ok?'pill-green':'pill-gray'}" title=${s.note||''}>
          <span style=${`color:${m.color};display:inline-flex`}><${Icon} name=${m.icon} size=12 /></span>
          ${m.label} ${ok?`· ${n}`:'· quiet'}</span>`; })}
    </div>`}
    ${all.length>0 && html`<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      <span style="font-size:12px;color:var(--ink-gray-5)">${drActive(range)?`${shown.length} of ${all.length}`:all.length} mention${shown.length===1?'':'s'}</span>
      <span style="flex:1"></span>
      <${DateRange} value=${range} onChange=${setRange}/>
    </div>`}
    ${shown && shown.length
      ? html`<div class="feed">
          ${shown.map(a=>{ const m = SIG_META[a.platform]||{label:a.platform,color:'#525252',icon:'globe'};
            return html`<div class="feed-row">
              <span class="feed-plat" style=${`background:${m.color}`}><${Icon} name=${m.icon} size=15 /></span>
              <div class="feed-main">
                <div class="feed-text">${a.url
                  ? html`<a href=${a.url} target="_blank" rel="noopener noreferrer" style="color:inherit">${a.text}</a>`
                  : a.text}</div>
                <div class="feed-meta">${joinDots([
                  a.author && html`<span class="feed-au">${a.where && /^r\//.test(a.where) ? a.where+' · ' : ''}${a.author.startsWith?'@'+String(a.author).replace(/^@/,''):a.author}</span>`,
                  !a.author && a.where && html`<span>${a.where}</span>`,
                  a.ago && html`<span>${a.ago}</span>`,
                  ...(a.engagement || []).map(e=>html`<span class="feed-eng">${e}</span>`),
                ])}</div>
              </div>
            </div>`; })}
        </div>`
      : html`<div class="sig-empty glass-card" style="border-radius:var(--radius-lg)">
          <span class="se-ic"><${Icon} name="rss" size=17 /></span>
          <div class="se-title">${all.length&&drActive(range)?'No mentions in this date range.':'No live mentions yet.'}</div>
          <div class="se-note">${all.length&&drActive(range)
            ? 'Widen the date range to see the rest of the feed.'
            : errs.length
            ? 'The sources that need a connection (X session, Reddit app) stayed quiet. GitHub leads the zero-config read.'
            : 'Nothing matched right now. Try a broader phrase or hit Refresh.'}</div>
        </div>`}`;
}


/* Render one lookup payload by its unit. */
export function UnitResult({payload, onPick}){
  if(payload.unit === 'keyword')
    return html`<${FeedList} feed=${payload.feed||[]} sources=${payload.sources||[]} />`;
  return html`
    <div class="sig-grid">${(payload.sources||[]).map(s=>html`<${SignalCard} s=${s} />`)}</div>
    ${payload.unit === 'company' && html`<${PersonRoster} people=${payload.people||[]} onPick=${onPick} />`}`;
}


/* One row of a bulk job result: a query with its payload, collapsed by default. */
export function BulkItem({item, onPick}){
  const [open, setOpen] = useState(false);
  const p = item.payload;
  const sum = item.error ? 'error'
    : p.unit==='keyword' ? `${(p.feed||[]).length} mentions`
    : p.unit==='company' ? `${p.summary.platforms_found}/${p.summary.platforms_searched} sources · ${(p.people||[]).length} people`
    : `${p.summary.platforms_found}/${p.summary.platforms_searched} sources matched`;
  return html`<div class="bulk-item">
    <div class="bulk-head" onClick=${()=>!item.error && setOpen(o=>!o)}>
      <${Icon} name=${item.error?'alert':(open?'minus':'plus')} size=14 />
      <span class="bulk-q">${item.query}</span>
      <span class="bulk-sum">${sum}</span>
    </div>
    ${open && !item.error && html`<div class="bulk-body"><${UnitResult} payload=${p} onPick=${onPick} /></div>`}
    ${item.error && html`<div class="bulk-body" style="font-size:12px;color:var(--ink-red-3)">${item.error}</div>`}
  </div>`;
}


export function SignalsTool({seed}){
  const [unit, setUnit]       = useState('person');
  const [query, setQuery]     = useState('');
  const [bulk, setBulk]       = useState(false);
  const [bulkText, setBulkT]  = useState('');
  const [sel, setSel]         = useState({});   // empty = all of the unit's sources on; a key set false turns one off
  const [adv, setAdv]         = useState(false);
  const [handles, setHandles] = useState({github:'', reddit:'', linkedin:'', x:''});
  const [webhook, setWebhook] = useState('');
  const [deliver, setDeliver] = useState(false);
  const [copied, setCopied]   = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData]       = useState(null);
  const [job, setJob]         = useState(null);
  const [error, setError]     = useState(null);
  const [conn, setConn]       = useState(null);

  useEffect(()=>{
    fetch(`${API_BASE}/api/signals`).then(r=>r.json()).then(j=>setConn(j.sources||null)).catch(()=>{});
  }, []);

  const um = UNIT_META[unit];
  const chosen = um.sources.filter(s=>sel[s] !== false);   // every unit source on unless explicitly toggled off
  const isBulk = data && data.items;

  function pickUnit(u){
    if(u === unit) return;
    setUnit(u); setData(null); setJob(null); setError(null); setBulk(false);
    setSel({});   // {} means every source for the new unit is on by default
    if(u !== 'person') setAdv(false);
  }

  function buildSingleBody(force){
    if(unit === 'person'){
      const advHandle = adv && Object.values(handles).some(v=>v && v.trim());
      const parsed = parseQuery(query);
      if(parsed.kind === 'empty' && !advHandle) return {error:'Enter a handle or a profile URL.'};
      if(parsed.kind === 'name' && !advHandle){ setAdv(true);
        return {error:"That looks like a topic or full name. People are looked up by handle or profile link. To see live mentions of it, search it as a keyword."}; }
      if(parsed.kind === 'email' && !advHandle)
        return {error:"Email lookup needs an enrichment source we have not wired yet. Paste a profile URL or type a handle for now."};
      if(parsed.kind === 'url-unknown' && !advHandle)
        return {error:"That link is not a supported source. Use a GitHub, Reddit, LinkedIn, X, or YouTube profile URL, or type a handle."};
      if(parsed.kind === 'url')
        return {body:{ unit, query: parsed.handle, sources:[parsed.platform], handles:{[parsed.platform]: parsed.handle}, force }};
      if(chosen.length === 0) return {error:'Pick at least one source to look in.'};
      const q = parsed.kind === 'handle' ? parsed.value : query.trim();
      return {body:{ unit, query:q, sources:chosen, handles: adv ? handles : undefined, force }};
    }
    if(!query.trim()) return {error: unit==='company' ? 'Enter a company name or domain.' : 'Enter a topic or phrase to track.'};
    if(chosen.length === 0) return {error:'Pick at least one source.'};
    return {body:{ unit, query: query.trim(), sources:chosen, force }};
  }

  async function pollJob(id){
    for(let i=0;i<45;i++){
      await new Promise(res=>setTimeout(res, 1100));
      try{ const r = await fetch(`${API_BASE}/api/jobs?id=${id}`); const j = await r.json();
        if(j.status === 'done' || j.status === 'error') return j; }catch(e){}
    }
    return null;
  }

  async function runJob(body){
    setLoading(true); setData(null);
    try{
      const r = await fetch(`${API_BASE}/api/jobs`, {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
      let j = await r.json(); setJob(j);
      if(j.status !== 'done' && j.status !== 'error') j = await pollJob(j.id);
      if(!j){ setError('Job timed out. Try a smaller batch or retry.'); setLoading(false); return; }
      setJob(j);
      if(j.status === 'error') setError(j.error || 'Job failed.');
      else setData(j.result);
    }catch(e){ setError('Could not reach the jobs API. Is the local server running on :5000?'); }
    setLoading(false);
  }

  async function run(force=false){
    setError(null); setJob(null);
    if(bulk){
      const queries = bulkText.split('\n').map(s=>s.trim()).filter(Boolean);
      if(!queries.length){ setError('Add at least one query, one per line.'); return; }
      if(chosen.length === 0){ setError('Pick at least one source.'); return; }
      return runJob({ kind:'bulk', unit, queries, sources:chosen, force,
                      webhook: webhook.trim() || undefined });
    }
    const b = buildSingleBody(force);
    if(b.error){ setError(b.error); return; }
    if(webhook.trim())
      return runJob({ kind:'lookup', ...b.body, webhook: webhook.trim() });
    setLoading(true); setData(null);
    try{
      const r = await fetch(`${API_BASE}/api/signals`, {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(b.body)});
      const j = await r.json();
      if(!r.ok) setError(j.error || 'Lookup failed.'); else setData(j);
    }catch(e){ setError('Could not reach Signals. Is the local server running on :5000?'); }
    setLoading(false);
  }

  /* bridge: run the current query as a Keyword lookup (offered when a person/company
     search of a topic phrase comes back empty or errors) */
  async function searchAsKeyword(){
    const q = query.trim(); if(!q) return;
    setUnit('keyword'); setBulk(false); setAdv(false); setSel({});
    setError(null); setJob(null); setLoading(true); setData(null);
    try{
      const r = await fetch(`${API_BASE}/api/signals`, {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({unit:'keyword', query:q, sources: UNIT_META.keyword.sources})});
      const j = await r.json();
      if(!r.ok) setError(j.error||'Lookup failed.'); else setData(j);
    }catch(e){ setError('Could not reach Signals. Is the local server running on :5000?'); }
    setLoading(false);
  }

  /* Build a sel map ({source: bool}) covering every source of the unit, so no
     source (e.g. youtube) is left undefined and silently defaulted on. */
  function selFor(u, on){
    const m = {};
    (UNIT_META[u].sources || []).forEach(s => { m[s] = on(s); });
    return m;
  }

  async function pickPerson(p){
    setUnit('person'); setBulk(false); setAdv(false); setWebhook('');
    setSel(selFor('person', s => s === p.platform));
    setQuery(p.handle); setError(null); setJob(null); setLoading(true); setData(null);
    try{
      const r = await fetch(`${API_BASE}/api/signals`, {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({unit:'person', query:p.handle, sources:[p.platform], handles:{[p.platform]:p.handle}})});
      const j = await r.json();
      if(!r.ok) setError(j.error||'Lookup failed.'); else setData(j);
    }catch(e){ setError('Could not reach Signals.'); }
    setLoading(false);
  }

  /* Pre-fill + run live from a Home template. Fetches with explicit params (like
     pickPerson) so it never waits on async state flushes. */
  async function seedLookup(p){
    const u = p.unit || 'person';
    const srcs = p.sources || UNIT_META[u].sources;
    setUnit(u); setBulk(false); setAdv(false); setWebhook(''); setJob(null); setError(null);
    setSel(selFor(u, s => srcs.includes(s)));
    setQuery(p.query); setLoading(true); setData(null);
    try{
      const r = await fetch(`${API_BASE}/api/signals`, {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({unit:u, query:p.query, sources:srcs})});
      const j = await r.json();
      if(!r.ok) setError(j.error||'Lookup failed.'); else setData(j);
    }catch(e){ setError('Could not reach Signals. Is the local server running on :5000?'); }
    setLoading(false);
  }

  useEffect(()=>{ if(seed && seed.tool==='signals' && seed.payload){ seedLookup(seed.payload); } }, [seed]);

  async function exportResult(fmt){
    let id = job && job.id;
    if(!id){
      const b = buildSingleBody(false);
      if(b.error){ setError(b.error); return; }
      try{
        const r = await fetch(`${API_BASE}/api/jobs`, {method:'POST',
          headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'lookup', ...b.body})});
        let j = await r.json();
        if(j.status !== 'done' && j.status !== 'error') j = await pollJob(j.id);
        if(!j || j.status === 'error'){ setError('Export failed.'); return; }
        id = j.id; setJob(j);
      }catch(e){ setError('Export failed.'); return; }
    }
    window.open(`${API_BASE}/api/jobs?id=${id}&format=${fmt}`, '_blank');
  }

  function apiSnippet(){
    const base = API_BASE || location.origin;
    if(bulk){
      const qs = bulkText.split('\n').map(s=>s.trim()).filter(Boolean);
      const body = {kind:'bulk', unit, queries: qs.length?qs:['query-1','query-2'], sources:chosen};
      if(webhook.trim()) body.webhook = webhook.trim();
      return `curl -X POST ${base}/api/jobs \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(body)}'`;
    }
    const wh = webhook.trim();
    const endpoint = wh ? '/api/jobs' : '/api/signals';
    const body = wh ? {kind:'lookup', unit, query: query.trim()||'query', sources:chosen, webhook:wh}
                    : {unit, query: query.trim()||'query', sources:chosen};
    return `curl -X POST ${base}${endpoint} \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(body)}'`;
  }
  function copySnippet(){ navigator.clipboard.writeText(apiSnippet()); setCopied(true); setTimeout(()=>setCopied(false),1400); }

  const summary = data && !isBulk && html`
    <div style="font-size:14px;color:var(--ink-gray-6)">
      ${unit==='keyword'
        ? html`<b style="color:var(--ink-gray-9)">${(data.feed||[]).length}</b> live mentions across ${data.summary.platforms_found} of ${data.summary.platforms_searched} sources`
        : html`<b style="color:var(--ink-gray-9)">${data.summary.platforms_found}</b> of ${data.summary.platforms_searched} sources matched${
            unit==='company' ? html` · <b style="color:var(--ink-gray-9)">${data.summary.people_found||0}</b> people` : ''}${
            data.summary.latest_activity_ago ? html` · last seen <b style="color:var(--ink-gray-9)">${data.summary.latest_activity_ago}</b>` : ''}`}
    </div>`;

  return html`
  <div class="view">
    <div class="view-head">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
        <span class="pill pill-blue"><${Icon} name="radar" size=12 /> Real-time</span>
        <span class="pill pill-gray"><${Icon} name="cpu" size=12 /> Agent-ready</span>
      </div>
      <h1 class="view-h1">Reach people the moment they do something worth mentioning</h1>
      <p class="view-sub">Look up a person, company, or keyword and get real-time activity across GitHub, Reddit, LinkedIn, X, and YouTube. The same fresh context a human reads or an AI agent calls.</p>
    </div>

    ${conn && html`
      <div class="conn-strip">
        <span class="cs-label">Sources</span>
        ${SIG_ORDER.map(s=>{ const c = conn[s] || {}; const m = SIG_META[s];
          return html`<span class=${'conn' + (c.ready ? ' ready' : '')} title=${c.note || ''}>
            <span class="cn-dot"></span>
            <span style=${`color:${m.color};display:inline-flex`}><${Icon} name=${m.icon} size=13 /></span>
            ${m.label}
            <span style="color:var(--ink-gray-4);font-weight:400">· ${c.ready ? 'connected' : 'public'}</span>
          </span>`; })}
      </div>`}

    <div class="glass-card" style="padding:24px;margin-bottom:16px">
      <div class="seg" style="margin-bottom:16px">
        ${Object.entries(UNIT_META).map(([u,m])=>html`<button class=${unit===u?'on':''} onClick=${()=>pickUnit(u)}>
          <${Icon} name=${m.icon} size=14 /> ${m.label}</button>`)}
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:8px">
        <label class="field-label" style="margin:0">${bulk
          ? (unit==='person'?'Handles or profile URLs':unit==='company'?'Companies':'Topics') + ', one per line'
          : (unit==='person'?'Who are you looking up?':unit==='company'?'Which company?':'What do you want to track?')}</label>
        <button class="btn btn-ghost btn-sm" onClick=${()=>{ setBulk(b=>!b); setData(null); setJob(null); setError(null); }}>
          <${Icon} name=${bulk?'userSearch':'list'} size=13 /> ${bulk?'Single lookup':'Bulk list'}
        </button>
      </div>

      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
        ${bulk
          ? html`<textarea class="copy-area" style="flex:1;min-width:240px;min-height:96px"
              placeholder=${um.bulkPh} value=${bulkText} onInput=${e=>setBulkT(e.target.value)}></textarea>`
          : html`<input class="input" style="flex:1;min-width:240px" placeholder=${um.ph}
              value=${query} onInput=${e=>setQuery(e.target.value)} onKeyDown=${e=>e.key==='Enter'&&run(false)} />`}
        <button class="btn btn-primary btn-lg" disabled=${loading} onClick=${()=>run(false)}>
          ${loading
            ? html`<${Icon} name="loader" size=15 cls="spin" /> Working`
            : html`<${Icon} name=${um.icon} size=15 /> ${bulk ? 'Run batch' : um.cta}`}
        </button>
      </div>
      <div class="sig-hint">${um.hint}${bulk ? ' Bulk runs as an async job you can poll, webhook, or export.' : ''}</div>

      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:16px">
        <span class="field-label" style="margin:0">Look in</span>
        ${(()=>{ const onSrcs=um.sources.filter(s=>sel[s]!==false); const total=um.sources.length; const allOn=onSrcs.length===total;
          return html`<${Picker} icon="radar" label="Sources" caption=${allOn?'All':onSrcs.length+' of '+total}
            active=${!allOn} minW=220 title="Choose which sources to search">
            ${()=>html`<div>
              <button type="button" class="pk-item" onClick=${()=>setSel({})}>All sources
                ${allOn?html`<span class="pk-ck"><${Icon} name="check" size=14/></span>`:''}</button>
              <div class="pk-sep"></div>
              ${um.sources.map(s=>{ const m=SIG_META[s]; const on=sel[s]!==false;
                return html`<button type="button" class="pk-item" role="menuitemcheckbox" aria-checked=${on}
                  onClick=${()=>setSel(p=>({...p,[s]:p[s]===false}))}>
                  <span style=${`color:${m.color};display:inline-flex`}><${Icon} name=${m.icon} size=15/></span> ${m.label}
                  ${on?html`<span class="pk-ck"><${Icon} name="check" size=14/></span>`:''}</button>`; })}
            </div>`}
          </${Picker}>`; })()}
        ${unit==='person' && !bulk && html`<span style="flex:1"></span>
          <button class="btn btn-ghost btn-sm" onClick=${()=>setAdv(a=>!a)}>
            <${Icon} name=${adv?'minus':'plus'} size=13 /> ${adv ? 'Using exact handles' : 'Know their exact handles?'}
          </button>`}
      </div>

      ${unit==='person' && !bulk && adv && html`
        <div class="sig-adv" style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:16px">
          ${um.sources.map(s=>{ const m = SIG_META[s];
            return html`<div>
              <label class="field-label" style="display:flex;align-items:center;gap:8px">
                <span style=${`color:${m.color};display:inline-flex`}><${Icon} name=${m.icon} size=13 /></span> ${m.label}
              </label>
              <input class="input" placeholder=${m.label + ' handle'} value=${handles[s]}
                onInput=${e=>setHandles(p=>({...p, [s]:e.target.value}))} onKeyDown=${e=>e.key==='Enter'&&run(false)} />
            </div>`; })}
        </div>`}
    </div>

    <div class="deliver">
      <div class="deliver-h" onClick=${()=>setDeliver(d=>!d)}>
        <${Icon} name="webhook" size=15 /> Delivery: API, webhook, bulk export
        <span style="margin-left:auto;color:var(--ink-gray-4)"><${Icon} name=${deliver?'minus':'plus'} size=14 /></span>
      </div>
      ${deliver && html`<div class="deliver-b">
        <div class="dlv-block">
          <div class="dlv-lab"><${Icon} name="code" size=13 /> Call it from an agent</div>
          <div class="code-blk">
            <button class="copy-mini" onClick=${copySnippet}><${Icon} name=${copied?'check':'copy'} size=12 /> ${copied?'Copied':'Copy'}</button>
            <pre>${apiSnippet()}</pre>
          </div>
        </div>
        <div class="dlv-block">
          <div class="dlv-lab"><${Icon} name="webhook" size=13 /> Webhook (optional)</div>
          <input class="input" placeholder="https://your-app.com/hooks/signals" value=${webhook}
            onInput=${e=>setWebhook(e.target.value)} />
          <div class="sig-hint">Set a URL and the lookup runs as an async job that POSTs the finished result to it. Leave blank for an inline read.</div>
        </div>
        <div class="dlv-block">
          <div class="dlv-lab"><${Icon} name="download" size=13 /> Bulk export</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-ghost btn-sm" disabled=${!data} onClick=${()=>exportResult('csv')}><${Icon} name="download" size=13 /> Export CSV</button>
            <button class="btn btn-ghost btn-sm" disabled=${!data} onClick=${()=>exportResult('json')}><${Icon} name="download" size=13 /> Export JSON</button>
          </div>
          <div class="sig-hint">Exports the current result through the jobs API, so a CSV matches exactly what an agent would receive.</div>
        </div>
      </div>`}
    </div>

    ${error && html`<div class="errbox" style="margin:16px 0">
      <${Icon} name="alert" size=18 />
      <div style="flex:1;min-width:0"><div style="font-weight:600;margin-bottom:4px">Couldn't run that lookup</div>
      <div style="font-size:14px;opacity:.85">${error}</div>
      ${unit!=='keyword' && query.trim() && html`<button class="btn btn-primary btn-sm" style="margin-top:8px" onClick=${searchAsKeyword}>
        <${Icon} name="hash" size=13 /> Search "${query.trim()}" as a keyword</button>`}</div>
    </div>`}

    ${job && html`<div class="job-strip" style="margin-top:16px">
      <span class="pill ${job.status==='done'?'pill-green':job.status==='error'?'pill-amber':'pill-blue'}">
        <${Icon} name=${job.status==='done'?'check':job.status==='error'?'alert':'loader'} size=12 cls=${job.status==='running'||job.status==='queued'?'spin':''} />
        ${job.status}</span>
      <span style="font-size:12px;color:var(--ink-gray-7)">Async ${job.kind} job</span>
      <span class="js-id">${job.id ? job.id.slice(0,12) : ''}</span>
      ${job.webhook && html`<span style="font-size:12px;color:var(--ink-gray-5)"><${Icon} name="webhook" size=11 /> webhook set</span>`}
    </div>`}

    ${loading && !job && !data && html`<div class="sig-grid" style="margin-top:16px">
      ${(chosen.length?chosen:[0,1,2]).map(()=>html`<div class="glass-card sig-card">
        <div class="sig-head">
          <div class="skel" style="width:46px;height:46px;border-radius:var(--radius-lg)"></div>
          <div style="flex:1"><div class="skel" style="height:13px;width:55%;margin-bottom:8px"></div>
            <div class="skel" style="height:11px;width:85%"></div></div>
        </div>
        <div class="sig-body">${[0,1,2].map(()=>html`<div class="sig-act">
          <div class="skel" style="width:26px;height:26px;border-radius:var(--radius);flex-shrink:0"></div>
          <div style="flex:1"><div class="skel" style="height:11px;width:94%;margin-bottom:8px"></div>
            <div class="skel" style="height:9px;width:42%"></div></div></div>`)}</div>
      </div>`)}
    </div>`}

    ${isBulk && html`
      <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:16px 0 16px">
        <div style="font-size:14px;color:var(--ink-gray-6)">
          Batch of <b style="color:var(--ink-gray-9)">${data.count}</b> ${data.unit} lookups</div>
        <span style="flex:1"></span>
        <button class="btn btn-ghost btn-sm" onClick=${()=>exportResult('csv')}><${Icon} name="download" size=13 /> Export CSV</button>
      </div>
      ${data.items.map(it=>html`<${BulkItem} item=${it} onPick=${pickPerson} />`)}`}

    ${data && !isBulk && html`
      <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:16px 0 16px">
        ${summary}
        ${data.cached && html`<span class="pill pill-amber"><${Icon} name="clock" size=11 /> Cached</span>`}
        <span style="flex:1"></span>
        <button class="btn btn-ghost btn-sm" disabled=${loading} onClick=${()=>run(true)}>
          <${Icon} name="refresh" size=13 cls=${loading?'spin':''} /> Refresh
        </button>
      </div>
      <${UnitResult} payload=${data} onPick=${pickPerson} />`}

    ${!data && !loading && !job && !error && html`
      <div class="note note-blue" style="margin-top:16px"><${Icon} name="zap" size=16 />
        <div>Every source is read live at lookup time, so you see what was posted today, not a stale export. GitHub and YouTube
          read with zero config; LinkedIn and X read richest with a connected session. One source being quiet never blocks the rest.</div>
      </div>`}
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'signals', icon:'radar', name:'Signals', desc:'The data intelligence layer for AI agents', component: SignalsTool };
