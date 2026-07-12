/* Auth: magic-link sign-in, runs, welcome */
import { Icon, h, html, useEffect, useState } from './core.js';


/* ════════════════════════ APP SHELL ════════════════════════ */
/* ════════════════════════ ACCOUNTS — sign-in modal + run history ════════════════════════ */
export function Auth({open, onClose, initialErr}){
  const [email, setEmail] = useState('');
  const [stage, setStage] = useState('entry');   // entry | sent | dev
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState('');
  const [link, setLink]   = useState('');
  useEffect(()=>{ if(open){ setStage('entry'); setErr(initialErr||''); setBusy(false); } }, [open]);
  if(!open) return null;
  const submit = async () => {
    if(busy || !email) return;
    setBusy(true); setErr('');
    try{
      const r = await fetch('/api/auth', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({action:'request', email})});
      const d = await r.json();
      if(d.mode==='dev' && d.link){ setLink(d.link); setStage('dev'); }
      else if(d.ok){ setStage('sent'); }
      else setErr(d.error || 'Could not send the link. Try again.');
    }catch(e){ setErr('Network error. Try again.'); }
    setBusy(false);
  };
  return html`
    <div class="auth-backdrop" onClick=${e=>{ if(e.target.classList.contains('auth-backdrop')) onClose(); }}>
      <div class="auth-card">
        <button class="auth-x" onClick=${onClose} aria-label="Close">×</button>
        ${stage==='entry' && html`
          <div class="auth-mark"><span class="m"><${Icon} name="target" size=16 /></span>GTMstack</div>
          <h2 class="auth-h">Sign in to GTMstack</h2>
          <p class="auth-sub">No password. We email you a one-time sign-in link.</p>
          <label class="auth-label">Email</label>
          <input class="auth-input" type="email" placeholder="you@company.com" value=${email}
            onInput=${e=>setEmail(e.target.value)} onKeyDown=${e=>{ if(e.key==='Enter') submit(); }} autofocus />
          ${err && html`<div class="auth-err">${err}</div>`}
          <button class="auth-btn" disabled=${busy||!email} onClick=${submit}>${busy?'Sending…':'Continue with email'}</button>
          <p class="auth-note">Your runs save to your history once you sign in.</p>
          <p class="auth-legal">By continuing you agree to the Terms and Privacy Policy.</p>`}
        ${stage==='sent' && html`
          <div class="auth-ico"><${Icon} name="mail" size=22 /></div>
          <h2 class="auth-h">Check your inbox</h2>
          <p class="auth-sub">We sent a sign-in link to <b>${email}</b>. It expires in 15 minutes.</p>
          <button class="auth-link" onClick=${()=>setStage('entry')}>Use a different email</button>`}
        ${stage==='dev' && html`
          <div class="auth-ico"><${Icon} name="sealCheck" size=22 /></div>
          <h2 class="auth-h">Your sign-in link</h2>
          <p class="auth-sub">Email is not configured in dev, so here is your link directly. It expires in 15 minutes.</p>
          <a class="auth-btn" href=${link}>Open sign-in link</a>
          <button class="auth-link" onClick=${()=>setStage('entry')}>Use a different email</button>`}
      </div>
    </div>`;
}


export function RunsModal({open, onClose}){
  const [data, setData] = useState(null);
  useEffect(()=>{ if(open){ setData(null);
    fetch('/api/auth?action=runs').then(r=>r.json()).then(setData).catch(()=>setData({runs:[]})); } }, [open]);
  if(!open) return null;
  const runs = (data&&data.runs)||[];
  const fmt = (iso)=>{ try{ return new Date(iso).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}); }catch(e){ return ''; } };
  return html`
    <div class="auth-backdrop" onClick=${e=>{ if(e.target.classList.contains('auth-backdrop')) onClose(); }}>
      <div class="auth-card" style="max-width:440px">
        <button class="auth-x" onClick=${onClose}>×</button>
        <div class="auth-mark"><span class="m"><${Icon} name="clock" size=16 /></span>Your runs</div>
        ${!data ? html`<div class="auth-empty">Loading…</div>`
          : runs.length ? html`<div>${runs.map(r=>html`
              <div class="auth-runrow"><span class="rt">${r.tool}</span><span class="rs">${r.summary||''}</span><span class="ra">${fmt(r.at)}</span></div>`)}</div>`
          : data.no_db ? html`<div class="auth-empty">You are signed in. Run history starts saving once a database is connected to GTMstack.</div>`
          : html`<div class="auth-empty">No runs yet. Use any tool and it shows up here.</div>`}
      </div>
    </div>`;
}


export function WelcomeModal({open, onClose}){
  if(!open) return null;
  return html`
    <div class="auth-backdrop" onClick=${onClose}>
      <div class="auth-card" style="text-align:center" onClick=${e=>e.stopPropagation()}>
        <div class="auth-ico" style="margin:0 auto 16px"><${Icon} name="sparkles" size=22 /></div>
        <h2 class="auth-h">Welcome to GTMstack</h2>
        <p class="auth-sub">You are signed in. Every tool you run now saves to your history.</p>
        <button class="auth-btn" onClick=${onClose}>Start exploring</button>
      </div>
    </div>`;
}
