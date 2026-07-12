/* Composite plays: runner + per-play result renderers */
import { API_BASE, Icon, Logo, PLAT_META, domainOf, h, html, useEffect, useRef, useState } from './core.js';
import { CTYPES, PersonaResult } from './persona.js';

export function SignalsEvidence(o){
  const ev = (o.evidence||[]).slice(0,6);
  return html`
    <div style="margin-top:4px">
      <div class="ev-chips">
        ${(o.platform_status||[]).map(p=>{ const m=PLAT_META[p.platform]||[null,p.platform];
          const ok=p.status==='ok'; return html`
          <span class=${'pill '+(ok?'pill-green':'pill-gray')} title=${p.note||''}>
            ${m[0]&&html`<${Icon} name=${m[0]} size=12 />`} ${m[1]}${ok?'':' · not connected'}</span>`; })}
      </div>
      <div class="ev-list">
        ${ev.map(p=>{ const m=PLAT_META[p.platform]||['globe',p.platform];
          const eng=(p.engagement||[]).map(e=>`${e.value} ${e.label}`).join(' · '); return html`
          <div class="ev-post">
            <span class="ev-ic"><${Icon} name=${m[0]} size=16 /></span>
            <div class="ev-body">
              <div class="ev-meta"><span>${m[1]} · ${p.kind}</span>${p.ago&&html`<span>${p.ago}</span>`}</div>
              <div class="ev-text">${p.text}</div>
              ${eng&&html`<div class="ev-eng">${eng}</div>`}
            </div>
          </div>`; })}
      </div>
    </div>`;
}

/* Renders the 'teardown' step: the repeatable patterns drawn from the posts. */
/* Shared reliability rendering for the content agents (13 teardown, 14 trends):
   a confidence pill, and grounded facets where every insight shows the posts it
   cites. An uncited insight is marked 'unverified' rather than passed off. */

export function citesRow(ev){
  return (ev&&ev.length) ? html`<div class="td-cites">
    ${ev.map(e=>html`<span class="td-cite" title=${e.snippet||''}>#${e.n} ${e.platform}</span>`)}
  </div>` : null;
}

export function confPill(conf){
  const band=(conf&&conf.band)||'';
  return band ? html`<span class=${'pill '+(band==='high'?'pill-green':'pill-gray')} title=${(conf&&conf.basis)||''}>
    <${Icon} name="sealCheck" size=12 /> ${band} confidence</span>` : null;
}

export function groundedFacet(label, icon, items){
  return (items&&items.length) ? html`
    <div class="td-facet">
      <div class="td-facet-h"><span class="fi"><${Icon} name=${icon} size=14 /></span>${label}</div>
      <ul class="td-list">${items.map(it=>{ const T=(typeof it==='string')?{text:it,grounded:false,evidence:[]}:it; return html`<li>
        <div class="td-li-body">
          <span class="td-it">${T.text}${T.grounded===false?html`<span class="td-unv" title="No source post cited">unverified</span>`:null}</span>
          ${citesRow(T.evidence)}
        </div>
      </li>`; })}</ul>
    </div>` : null;
}


export function TeardownResult(o){
  const conf = o.confidence||{};
  return html`
    <div style="margin-top:4px">
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="pill pill-gray"><${Icon} name=${o.engine==='ai'?'sparkles':'cpu'} size=12 /> ${o.engine==='ai'?'Live AI teardown':'Built-in model'}</span>
        ${confPill(conf)}
      </div>
      ${o.summary&&html`<p class="td-sum">${o.summary}</p>`}
      ${conf.thin&&html`<div class="td-thin"><${Icon} name="alert" size=13 /> Thin evidence (${conf.basis}). Treat these as directional, not verified.</div>`}
      ${groundedFacet('Hooks that recur','zap',o.hooks)}
      ${groundedFacet('Formats they lean on','list',o.formats)}
      ${groundedFacet('Themes they own','hash',o.themes)}
      ${o.cadence&&html`<div class="td-cadence"><${Icon} name="clock" size=14 /> ${o.cadence}</div>`}
      ${o.steal&&html`<div class="td-steal">
        <div class="td-steal-h"><${Icon} name="target" size=13 /> Steal this week</div>
        <div class="td-steal-t">${o.steal}</div>
      </div>`}
      ${o.audit&&html`<p class="td-audit"><${Icon} name="sealCheck" size=12 /> ${o.audit}</p>`}
      <p style="font-size:12px;color:var(--ink-gray-4);margin:8px 0 0">
        Every pattern cites the posts it was drawn from. Connect an AI key for the full live teardown.
      </p>
    </div>`;
}

/* Agent 14: trending posts ranked by a shown velocity metric, the voices to
   engage, and a grounded read of what's heating up. */

export function TrendResult(o){
  const conf = o.confidence||{};
  const posts = o.trending_posts||[];
  const voices = o.top_voices||[];
  const ic = (plat)=>(PLAT_META[plat]||['globe',plat])[0];
  const eng = (e)=>(e||[]).map(x=>`${x.value} ${x.label}`).join(' · ');
  return html`
    <div style="margin-top:4px">
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="pill pill-gray"><${Icon} name=${o.engine==='ai'?'sparkles':'cpu'} size=12 /> ${o.engine==='ai'?'Live AI read':'Built-in model'}</span>
        ${confPill(conf)}
      </div>
      ${o.summary&&html`<p class="td-sum">${o.summary}</p>`}
      ${conf.thin&&html`<div class="td-thin"><${Icon} name="alert" size=13 /> Thin feed (${conf.basis}). Treat as directional.</div>`}
      ${groundedFacet('Topics heating up','zap',o.topics_heating)}
      ${groundedFacet('Where to engage','target',o.suggested_engagements)}
      ${posts.length?html`<div class="td-facet">
        <div class="td-facet-h"><span class="fi"><${Icon} name="rss" size=14 /></span>Trending now · by velocity</div>
        <div class="ev-list">${posts.slice(0,6).map(p=>html`
          <div class="ev-post">
            <span class="ev-ic"><${Icon} name=${ic(p.platform)} size=16 /></span>
            <div class="ev-body">
              <div class="ev-meta">${p.platform}${p.author?(' · @'+p.author):''}${p.velocity!=null?html` · <span class="tr-vel">${p.velocity}/hr</span>`:''}${p.ago?(' · '+p.ago):''}</div>
              <div class="ev-text">${p.text}</div>
              ${eng(p.engagement)&&html`<div class="ev-eng">${eng(p.engagement)}</div>`}
            </div>
          </div>`)}</div>
      </div>`:null}
      ${voices.length?html`<div class="td-facet">
        <div class="td-facet-h"><span class="fi"><${Icon} name="users" size=14 /></span>Top voices to engage</div>
        <div class="tr-voices">${voices.map(v=>html`
          <div class="tr-voice">
            <span class="ev-ic"><${Icon} name=${ic(v.platform)} size=15 /></span>
            <span class="vn">@${v.author}</span><span class="vw">${v.why}</span>
          </div>`)}</div>
      </div>`:null}
      ${o.audit&&html`<p class="td-audit"><${Icon} name="sealCheck" size=12 /> ${o.audit}</p>`}
    </div>`;
}

/* Agent 12: what works in your OWN content. Format winners + themes (grounded),
   best-time windows (metric shown), and an honest cross-run engagement trend. */

export function ContentPerfResult(o){
  const conf = o.confidence||{};
  const times = o.best_post_times||[];
  const trend = o.trend||{};
  return html`
    <div style="margin-top:4px">
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="pill pill-gray"><${Icon} name=${o.engine==='ai'?'sparkles':'cpu'} size=12 /> ${o.engine==='ai'?'Live AI read':'Built-in model'}</span>
        ${confPill(conf)}
      </div>
      ${o.summary&&html`<p class="td-sum">${o.summary}</p>`}
      ${conf.thin&&html`<div class="td-thin"><${Icon} name="alert" size=13 /> Thin evidence (${conf.basis}). Treat as directional.</div>`}
      ${groundedFacet('Format winners','list',o.format_winners)}
      ${groundedFacet('Themes that land','hash',o.top_themes)}
      ${times.length?html`<div class="td-facet">
        <div class="td-facet-h"><span class="fi"><${Icon} name="clock" size=14 /></span>Best time to post</div>
        <div class="cp-times">${times.map(t=>html`<div class="cp-time">
          <span class="cw">${t.window}</span><span class="cm">${t.posts} post(s) · avg ${Number(t.avg_engagement).toLocaleString()} engagement</span>
        </div>`)}</div>
      </div>`:null}
      ${groundedFacet('Do more of this','target',o.next_actions)}
      <div class="cp-trend"><${Icon} name="chartLine" size=13 /> ${trend.mom_delta!=null
        ? html`<span class="tr-vel">${trend.mom_delta>0?'+':''}${trend.mom_delta}%</span> month-over-month engagement, across ${trend.snapshots} snapshots`
        : (trend.note||'Building history across runs.')}</div>
      ${o.audit&&html`<p class="td-audit"><${Icon} name="sealCheck" size=12 /> ${o.audit}</p>`}
    </div>`;
}

/* Competitor intelligence: share of voice, a 2x2 market-positioning plot, and
   the voices shared across competitors. Plain SVG, no chart library. */

export function CompeteResult(o){
  const sov=o.share_of_voice||[];
  const pos=o.positioning||[];
  const ic=(plat)=>(PLAT_META[plat]||['globe',plat])[0];
  const fmtDate=(iso)=>{ if(!iso) return '?'; try{ return new Date(iso).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}); }catch(e){ return '?'; } };
  const dr=o.date_range||{};
  const maxReach=Math.max(1,...sov.map(r=>r.reach_pct));
  const maxVol=Math.max(1,...pos.map(p=>p.x_volume));
  const maxEng=Math.max(1,...pos.map(p=>p.y_engagement));
  const W=400,H=280,pad=40;
  const px=(v)=>pad+(v/maxVol)*(W-2*pad);
  const py=(v)=>H-pad-(v/maxEng)*(H-2*pad);
  const liCell=(r)=>{ const l=r.linkedin||{};
    if(l.followers_h) return html`<span class="ci-li"><span class="lic"><${Icon} name="linkedin" size=13 /></span>${l.followers_h}</span>`;
    if(l.staff_h)     return html`<span class="ci-li muted"><span class="lic"><${Icon} name="linkedin" size=13 /></span>~${l.staff_h} staff</span>`;
    return html`<span class="ci-li muted">—</span>`;
  };
  const anyLi=sov.some(r=>r.linkedin&&(r.linkedin.followers_h||r.linkedin.staff_h));
  return html`
    <div class="ci-wrap">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="pill pill-gray"><${Icon} name="radar" size=12 /> ${(o.brands||[]).length} brands · live read</span>
      </div>
      ${(o.insights||[]).length?html`<div class="ci-card">
        <div class="ci-h"><span class="fi"><${Icon} name="sparkles" size=14 /></span>What this means</div>
        <div class="ci-ins">${o.insights.map(i=>html`
          <div class="ci-ins-row">
            <span class=${'ci-ins-dot '+(i.kind||'')}></span>
            <div style="min-width:0"><div class="ci-ins-h">${i.headline}</div><div class="ci-ins-d">${i.detail}</div></div>
          </div>`)}</div>
      </div>`:null}
      <div class="ci-card">
        <div class="ci-h"><span class="fi"><${Icon} name="chartLine" size=14 /></span>Share of voice</div>
        <div class="ci-thead">
          <span></span><span>Brand</span><span>Reach</span><span class="rt">Posts</span><span class="rt">LinkedIn</span>
        </div>
        ${sov.map(r=>html`
          <div class="ci-trow">
            <span class=${'ci-rank'+(r.rank===1?' r1':'')}>${r.rank}</span>
            <span class=${'ci-brand'+(r.you?' you':'')}>${Logo(domainOf(r.brand),16)}<span class="ci-bn">${r.brand}</span></span>
            <span class="ci-reach"><span class="ci-bar"><i style=${'width:'+Math.max(3,r.reach_pct/maxReach*100)+'%'}></i></span><span class="ci-pct">${r.reach_pct}%</span></span>
            <span class="ci-num">${r.posts}</span>
            ${liCell(r)}
          </div>`)}
        <p class="ci-foot">Reach is each brand's share of total engagement.${anyLi?'':' LinkedIn follower counts need a connected LinkedIn session.'}</p>
      </div>
      <div class="ci-grid2">
        <div class="ci-card ci-quad">
          <div class="ci-h"><span class="fi"><${Icon} name="target" size=14 /></span>Market positioning</div>
          <svg viewBox=${'0 0 '+W+' '+H} role="img" aria-label="positioning quadrant">
            <line x1=${W/2} y1=${pad-8} x2=${W/2} y2=${H-pad+8} stroke="var(--outline-gray-2)" stroke-width="1"/>
            <line x1=${pad-8} y1=${H/2} x2=${W-pad+8} y2=${H/2} stroke="var(--outline-gray-2)" stroke-width="1"/>
            <text x=${W-pad} y=${pad-14} text-anchor="end" font-size="10" fill="var(--ink-gray-4)">LEADER</text>
            <text x=${pad} y=${pad-14} text-anchor="start" font-size="10" fill="var(--ink-gray-4)">PUNCHING ABOVE</text>
            <text x=${W-pad} y=${H-pad+22} text-anchor="end" font-size="10" fill="var(--ink-gray-4)">AGGRESSIVE</text>
            <text x=${pad} y=${H-pad+22} text-anchor="start" font-size="10" fill="var(--ink-gray-4)">STARTER</text>
            <text x=${W/2} y=${H-4} text-anchor="middle" font-size="9" fill="var(--ink-gray-4)">post volume</text>
            <text x="10" y=${H/2} text-anchor="middle" font-size="9" fill="var(--ink-gray-4)" transform=${'rotate(-90 10 '+(H/2)+')'}>engagement / post</text>
            ${pos.map(p=>{ const x=px(p.x_volume), y=py(p.y_engagement);
              const anchor=x<pad+34?'start':x>W-pad-34?'end':'middle';
              const ly=y<pad+24?y+16:y-11; return html`<g>
              <circle cx=${x} cy=${y} r=${p.you?7:5} fill=${p.you?'var(--ink-violet-1)':'var(--ink-gray-5)'} opacity=${p.you?1:.72}/>
              <text x=${x} y=${ly} text-anchor=${anchor} font-size="10.5" font-weight=${p.you?700:500} fill=${p.you?'var(--ink-violet-1)':'var(--ink-gray-7)'}>${p.brand}</text>
            </g>`; })}
          </svg>
        </div>
        ${(o.overlap||[]).length?html`<div class="ci-card">
          <div class="ci-h"><span class="fi"><${Icon} name="users" size=14 /></span>Shared voices · engage these</div>
          <div class="ci-ov">${o.overlap.map(v=>html`
            <div class="ci-ov-row">
              <span class="ev-ic"><${Icon} name=${ic(v.platform)} size=15 /></span>
              <span class="vn">@${v.author}</span>
              <span class="vb">talks about ${v.brands.join(', ')} · ${v.shared_across} brands</span>
            </div>`)}</div>
        </div>`:null}
      </div>
      <div class="ci-card">
        <div class="ci-h"><span class="fi"><${Icon} name="sealCheck" size=14 /></span>What was scanned</div>
        <p class="ci-prov">${dr.total||0} posts, realtime, ${dr.earliest?html`<b>${fmtDate(dr.earliest)}</b> to <b>${fmtDate(dr.latest)}</b>`:'dates unavailable'}${dr.dated?(' ('+dr.dated+' dated)'):''}. The most-engaged of them:</p>
        <div class="ev-list">${(o.evidence||[]).slice(0,6).map(e=>html`
          <div class="ev-post">
            <span class="ev-ic"><${Icon} name=${ic(e.platform)} size=15 /></span>
            <div class="ev-body">
              <div class="ev-meta">${Logo(domainOf(e.brand),13)} ${e.brand} · ${e.platform}${e.author?(' · @'+e.author):''}${e.ago?(' · '+e.ago):''}</div>
              <div class="ev-text">${e.text}</div>
            </div>
          </div>`)}</div>
        <p class="ci-foot">Built from public posts and mentions across X, GitHub, YouTube, and Reddit, not scraped engager lists. LinkedIn shows audience size from each brand's public company page.</p>
      </div>
    </div>`;
}

export const PLAY_CARDS = [
  {id:'video_messaging', icon:'captions', cat:'Content research',
   title:'Video messaging check',
   desc:'How your five developer personas react to a pitch, launch, or demo video.',
   steps:'Transcript → persona reactions',
   inputs:[
     {key:'url', label:'Video URL', type:'text', required:true,
      placeholder:'A watch, youtu.be, shorts, or embed link (or a video ID)',
      default:'https://www.youtube.com/watch?v=T1Lowy1mnEg'},
     {key:'ctype', label:'Treat the messaging as', type:'seg',
      options:CTYPES, default:'landing'},
   ]},
  {id:'creator_teardown', icon:'userSearch', cat:'Content research',
   title:'Creator teardown',
   desc:'A creator’s recent posts, with the hooks, formats, and the one move to steal.',
   steps:'Recent posts → pattern teardown',
   inputs:[
     {key:'handle', label:'Creator handle or name', type:'text', required:true,
      placeholder:'An X / GitHub / Reddit handle, e.g. levelsio',
      default:'levelsio'},
   ]},
  {id:'trend_discovery', icon:'rss', cat:'Content research',
   title:'Trend & top-voice scan',
   desc:'Scans a niche, ranks what’s moving by velocity, and names who to engage.',
   steps:'Scan niche → rank + read the trend',
   inputs:[
     {key:'topic', label:'Topic or keyword', type:'text', required:true,
      placeholder:'A niche topic, e.g. mcp servers',
      default:'mcp servers'},
   ]},
  {id:'content_performance', icon:'chartLine', cat:'Content research',
   title:'Content performance read',
   desc:'What works in your own posts: top formats, themes, and best time to post.',
   steps:'Your posts → what works',
   inputs:[
     {key:'handle', label:'Your handle or name', type:'text', required:true,
      placeholder:'Your X / GitHub / YouTube handle',
      default:'levelsio'},
   ]},
];

/* Competitor Intelligence runs as its own sidebar tool (not a home play), but
   reuses the same PlayRunner + the competitor_intel backend play. */

export const COMPETITOR_CARD = {
  id:'competitor_intel',
  title:'See where you stand against your competitors',
  desc:'Your brand vs your competitors: share of voice, market positioning, and the voices you both share. Built from public posts across X, GitHub, YouTube, and Reddit, not scraped engager lists.',
  inputs:[
    {key:'your_brand', label:'Your brand', type:'text', required:true,
     placeholder:'e.g. Cashfree', default:'Cashfree'},
    {key:'competitors', label:'Competitor brands', type:'text', required:true,
     placeholder:'comma-separated, e.g. Razorpay, PayU, PhonePe',
     default:'Razorpay, PayU, PhonePe'},
  ],
};


export function PlayRunner({card, onBack, autoRun=true}){
  const seed = {};
  card.inputs.forEach(f=>{ seed[f.key] = f.default!=null ? f.default
    : (f.options ? (f.options[0][0]!=null?f.options[0][0]:f.options[0]) : ''); });
  const [vals, setVals]    = useState(seed);
  const [loading, setLoad] = useState(false);
  const [error, setErr]    = useState('');
  const [res, setRes]      = useState(null);
  const resRef             = useRef(null);
  const setVal = (k,v)=> setVals(p=>({...p,[k]:v}));

  async function run(input){
    const data = input || vals;
    const miss = card.inputs.find(f=> f.required && !String(data[f.key]||'').trim());
    if(miss){ setErr(`Enter ${miss.label.toLowerCase()} to run this play.`); return; }
    setLoad(true); setErr(''); setRes(null);
    try{
      const r = await fetch(`${API_BASE}/api/plays`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({play: card.id, input: data}),
      });
      const j = await r.json();
      if(!r.ok){ setErr(j.error || 'The play could not run.'); }
      else setRes(j);
    }catch(e){ setErr('Could not reach the engine. Is the local server running on :5000?'); }
    setLoad(false);
  }

  /* Auto-run on open with the sample so one card click shows a full result.
     Disabled for standalone tools (e.g. Competitor Intel) where a heavy scan
     should only start when the user clicks Run. */
  useEffect(()=>{ if(autoRun) run(seed); }, []);

  /* When a result lands and its tail is below the fold, scroll to it so the
     multi-step output is what the user sees, not the form they just submitted.
     Instant, not smooth: late-loading icons shift layout and cancel a smooth
     animation, leaving the page parked on the form. */
  useEffect(()=>{
    if(res && resRef.current && resRef.current.getBoundingClientRect().bottom > innerHeight)
      requestAnimationFrame(()=> resRef.current && resRef.current.scrollIntoView({block:'start'}));
  }, [res]);

  return html`
  <div class="view">
    ${onBack && html`<button class="play-back" onClick=${onBack}><${Icon} name="arrowLeft" size=14 /> All plays</button>`}
    <div class="view-head">
      <h1 class="view-h1">${card.title}</h1>
      <p class="view-sub">${card.desc}</p>
    </div>

    <div class="glass-card" style="padding:24px;margin-bottom:16px">
      ${card.inputs.map(f=> html`
        <div>
          <label class="field-label">${f.label}</label>
          ${f.type==='seg'
            ? html`<div class="seg" style="margin:0 0 16px">
                ${f.options.map(([id,label])=>html`
                  <button class=${vals[f.key]===id?'on':''} onClick=${()=>setVal(f.key,id)}>${label}</button>`)}
              </div>`
            : html`<input class="input" style="width:100%;margin-bottom:16px" placeholder=${f.placeholder||''}
                value=${vals[f.key]||''} onInput=${e=>setVal(f.key,e.target.value)}
                onKeyDown=${e=>e.key==='Enter'&&run()} />`}
        </div>`)}
      <button class="btn btn-primary btn-lg" disabled=${loading} onClick=${()=>run()}>
        ${loading ? html`<${Icon} name="loader" size=15 cls="spin" /> Running play` : html`<${Icon} name="play" size=15 /> Run play`}
      </button>
    </div>

    ${error && html`<div class="errbox" style="margin-bottom:16px">
      <${Icon} name="alert" size=18 />
      <div><div style="font-weight:600;margin-bottom:4px">Couldn’t run the play</div>
      <div style="font-size:14px;opacity:.85">${error}</div></div>
    </div>`}

    ${loading && !res && html`
      <div class="glass-card" style="padding:24px;display:flex;gap:16px;margin-bottom:16px">
        <div class="skel" style="height:26px;width:26px;border-radius:50%;flex-shrink:0"></div>
        <div style="flex:1;display:flex;flex-direction:column;gap:8px;justify-content:center">
          <div class="skel" style="height:14px;width:35%"></div><div class="skel" style="height:10px;width:60%"></div></div>
      </div>`}

    ${res && html`<div class="stack" ref=${resRef}>
      ${res.steps.map((s,i)=>{ const err=s.status==='error'; const last=i===res.steps.length-1; return html`
        <div class="step">
          <div class="step-rail">
            <div class=${'step-dot'+(err?' err':'')}>${err?html`<${Icon} name="alert" size=14 />`:i+1}</div>
            ${!last && html`<div class="step-line"></div>`}
          </div>
          <div class="step-body">
            <div class="step-label">${s.label}</div>
            <div class="step-sum">${s.summary}</div>
            ${s.tool==='extract'  && s.output && s.output.preview && html`<div class="tprev">${s.output.preview}</div>`}
            ${s.tool==='persona'  && s.status==='ok' && s.output && PersonaResult(s.output)}
            ${s.tool==='signals'  && s.output && SignalsEvidence(s.output)}
            ${s.tool==='teardown' && s.status==='ok' && s.output && TeardownResult(s.output)}
            ${s.tool==='trends'   && s.status==='ok' && s.output && TrendResult(s.output)}
            ${s.tool==='contentperf' && s.status==='ok' && s.output && ContentPerfResult(s.output)}
            ${s.tool==='compete'  && s.status==='ok' && s.output && CompeteResult(s.output)}
          </div>
        </div>`; })}
    </div>`}
  </div>`;
}
