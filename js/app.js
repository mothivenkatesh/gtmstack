/* App shell: registry, sidebar, mounting */
import { Icon, h, html, render, useEffect, useState } from './core.js';
import { HomeTool,       manifest as mHome }       from './home.js';
import { PersonaTool,    manifest as mPersona }    from './persona.js';
import { ExtractTool,    manifest as mExtract }    from './extract.js';
import { SignalsTool,    manifest as mSignals }    from './signals.js';
import { CleanTool,      manifest as mClean }      from './clean.js';
import { CompetitorTool, manifest as mCompetitor } from './competitor.js';
import { TablesTool,     manifest as mTables }     from './tables.js';
import { RoutinesTool,   manifest as mReports }    from './reports.js';
import { ConnectorsTool, manifest as mConnectors } from './connectors.js';
import { HarnessTool,    manifest as mHarness }    from './harness.js';
import { Auth, RunsModal, WelcomeModal } from './auth.js';


/* ── tool registry: built from each module's manifest (the shared interface) ── */
export const MODULES = [mHome, mHarness, mPersona, mExtract, mSignals, mClean, mCompetitor, mTables, mReports, mConnectors];
export const TOOLS = Object.fromEntries(MODULES.map(m=>[m.id, m]));
export const NAV = MODULES.map(m=>m.id);


export function App(){
  /* the active tab is persisted in the URL hash (#tables), so a reload keeps you
     where you were and back/forward + shareable links work. Falls back to 'home'
     for an empty or unknown hash. */
  const hashTool = () => { const h = (location.hash||'').replace(/^#/,''); return TOOLS[h] ? h : 'home'; };
  const [tool, setTool] = useState(hashTool);
  const [seed, setSeed] = useState(null);
  const meta = TOOLS[tool];

  useEffect(()=>{ if(hashTool() !== tool) location.hash = tool; }, [tool]);
  useEffect(()=>{ const onHash = () => setTool(hashTool());
    addEventListener('hashchange', onHash); return () => removeEventListener('hashchange', onHash); }, []);

  /* Pre-fill + run live: stamp a seed (n makes each launch a fresh object so the
     target tool's effect re-fires even on a repeat of the same card), then show it. */
  function launch(toolId, payload){ setSeed({tool:toolId, payload, n:Date.now()}); setTool(toolId); }

  /* accounts: passwordless sign-in, soft-gated (the app stays usable anonymously) */
  const [me, setMe]           = useState(null);   // null=loading; {anon:true} | {anon:false,email}
  const [authOpen, setAuth]   = useState(false);
  const [authErr, setAuthErr] = useState('');
  const [menu, setMenu]       = useState(false);
  const [runsOpen, setRuns]   = useState(false);
  const [welcome, setWelcome] = useState(false);
  const refreshMe = () => fetch('/api/auth?action=me').then(r=>r.json()).then(setMe).catch(()=>setMe({anon:true}));
  useEffect(()=>{
    refreshMe();
    const p = new URLSearchParams(location.search);
    if(p.get('welcome')==='1') setWelcome(true);
    if(p.get('auth')==='expired'){ setAuthErr('That sign-in link expired or was already used. Request a new one.'); setAuth(true); }
    if(p.get('welcome')||p.get('auth')) history.replaceState({}, '', location.pathname);
  }, []);
  const logout = async () => { try{ await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'logout'})}); }catch(e){} setMenu(false); refreshMe(); };

  return html`
  <div class="app">
    <aside class="sidebar">
      <div class="side-brand">
        <span class="side-mark"><${Icon} name="target" size=19 /></span>
        <span class="side-name">GTMstack</span>
      </div>
      <nav class="side-nav">
        ${NAV.map(id=>{ const t=TOOLS[id]; return html`
          <div class=${'side-item'+(tool===id?' on':'')} onClick=${()=>setTool(id)} title=${t.desc}>
            <span class="si-ic"><${Icon} name=${t.icon} size=17 /></span>
            <span class="si-name">${t.name}</span>
          </div>`; })}
      </nav>
      <div class="side-foot" style="position:relative">
        ${me && !me.anon ? html`
          ${menu && html`<div class="user-menu">
            <button onClick=${()=>{ setRuns(true); setMenu(false); }}><${Icon} name="clock" size=15 /> Your runs</button>
            <button onClick=${logout}><${Icon} name="signout" size=15 /> Sign out</button>
          </div>`}
          <button class="user-chip" onClick=${()=>setMenu(o=>!o)}>
            <span class="user-mono">${(me.email||'?').slice(0,1)}</span>
            <span class="user-meta"><div class="user-email">${me.email}</div><div class="user-act">Account and runs</div></span>
          </button>`
        : html`
          <button class="signin-btn" onClick=${()=>{ setAuthErr(''); setAuth(true); }}><${Icon} name="user" size=15 /> Sign in</button>`}
      </div>
    </aside>

    <main class="main">
      <div class="topbar">
        <span class="tb-ic"><${Icon} name=${meta.icon} size=24 /></span>
        <span class="tb-name">${meta.name}</span>
        <span class="tb-desc" style="margin-left:4px">· ${meta.desc}</span>
      </div>

      <div style=${tool==='home'    ? '' : 'display:none'}><${HomeTool} onLaunch=${launch} tools=${TOOLS} /></div>
      <div style=${tool==='persona' ? '' : 'display:none'}><${PersonaTool} seed=${seed} /></div>
      <div style=${tool==='extract' ? '' : 'display:none'}><${ExtractTool} seed=${seed} /></div>
      <div style=${tool==='signals' ? '' : 'display:none'}><${SignalsTool} seed=${seed} /></div>
      <div style=${tool==='clean'   ? '' : 'display:none'}><${CleanTool} seed=${seed} /></div>
      ${tool==='harness' && html`<div><${HarnessTool} /></div>`}
      ${tool==='competitor' && html`<div><${CompetitorTool} /></div>`}
      ${tool==='reports' && html`<div><${RoutinesTool} /></div>`}
      <div style=${tool==='tables' ? '' : 'display:none'}><${TablesTool} /></div>
      <div style=${tool==='connectors' ? '' : 'display:none'}><${ConnectorsTool} /></div>
    </main>
    <${Auth} open=${authOpen} initialErr=${authErr} onClose=${()=>setAuth(false)} />
    <${RunsModal} open=${runsOpen} onClose=${()=>setRuns(false)} />
    <${WelcomeModal} open=${welcome} onClose=${()=>setWelcome(false)} />
  </div>`;
}

render(html`<${App} />`, document.getElementById('root'));
