/* GTMstack core: preact/htm runtime, API base, icons, shared UI primitives (Picker, DateRange) */
import { h, render } from 'https://esm.sh/preact@10.23.1';
import { useState, useMemo, useRef, useEffect } from 'https://esm.sh/preact@10.23.1/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
export { h, render, useState, useMemo, useRef, useEffect };

export const html = htm.bind(h);


export const API_BASE = location.protocol === 'file:' ? 'http://localhost:5000' : '';

/* ── solid icon set: Phosphor via Iconify. Fill weight for areal glyphs,
      Bold weight for inherently linear ones (check, plus, arrows, hash, code).
      One name→id map drives the whole app. Never reintroduce outline/stroke icons. ── */
/* Material Symbols Rounded ligature names (line style, wght 300 / GRAD 200 / opsz 24).
   Brand logos + the chess knight have no Material equivalent, so they stay on
   Phosphor via Iconify, switched to the LINE (regular) weight to match. An id
   containing ':' renders through iconify-icon; anything else is a Material ligature. */

export const ICONS = {
  captions:'closed_caption', youtube:'ph:youtube-logo', search:'search',
  copy:'content_copy', download:'download', clock:'schedule', type:'title',
  list:'format_list_bulleted', zap:'bolt', alert:'error', check:'check',
  globe:'language', hash:'tag', film:'movie', loader:'progress_activity',
  plus:'add', languages:'translate', book:'menu_book', pen:'edit',
  code:'code', target:'target', users:'group', sparkles:'auto_awesome',
  message:'chat_bubble', house:'home',
  arrowLeft:'arrow_back', play:'play_arrow',
  wrench:'build', cpu:'memory', github:'ph:github-logo', star:'star',
  arrowRight:'arrow_forward', radar:'radar', linkedin:'ph:linkedin-logo',
  twitter:'ph:x-logo', refresh:'refresh', mapPin:'location_on',
  externalLink:'open_in_new', plug:'power', userSearch:'frame_person',
  reddit:'ph:reddit-logo', building:'apartment', webhook:'webhook',
  rss:'rss_feed', sealCheck:'verified', upload:'upload',
  mail:'mail', broom:'mop', chartLine:'monitoring',
  minus:'remove', user:'person', signout:'logout',
  newspaper:'newspaper', knight:'ph:horse', calendar:'calendar_month',
  binoculars:'travel_explore', quora:'format_quote', trustpilot:'star',
  capterra:'storefront', g2:'military_tech', review:'star',
  sheet:'table', comment:'comment', archive:'archive',
  textAa:'text_fields', tag:'label', funnel:'filter_alt', eye:'visibility', eyeSlash:'visibility_off',
  caretDown:'keyboard_arrow_down', caretRight:'keyboard_arrow_right', caretUp:'keyboard_arrow_up',
  trash:'delete', dots:'more_horiz', copyRow:'file_copy',
  close:'close', columns:'view_column', kanban:'view_kanban', rows:'table_rows',
};
/* Icon size scale (user decision): 24px page-level, 20px nav/toolbar, 16px dense
   inline (grid headers, menus, chips). The legacy size prop snaps to the nearest
   tier, so call sites keep their relative hierarchy without pixel-exact sizes.
   htm passes attribute values as strings, hence the coercion. */

export const Icon = ({name, size, cls=''}) => {
  const id = ICONS[name] || name;
  const n = parseInt(size, 10) || 16;
  const px = n >= 22 ? 24 : n >= 15 ? 20 : 16;
  return id.includes(':')
    ? html`<iconify-icon class=${cls} icon=${id} width=${px} height=${px}></iconify-icon>`
    : html`<span class=${'msi'+(cls?' '+cls:'')} style=${'font-size:'+px+'px'} aria-hidden="true">${id}</span>`;
};


/* Platform -> [icon name, label]. Used by play steps that render a footprint. */
export const PLAT_META = {
  github:['github','GitHub'], x:['twitter','X'], linkedin:['linkedin','LinkedIn'],
  reddit:['reddit','Reddit'], youtube:['youtube','YouTube'],
};

/* Official logos, no key, no build: Clearbit by domain, falling back to a Google
   favicon, then hiding if both miss. Brand names map to a best-guess .com. */

export const domainOf = (brand) => (brand||'').trim().toLowerCase().replace(/[^a-z0-9]/g,'') + '.com';

export function Logo(domain, size){
  size = size || 18;
  return html`<img class="brand-logo" width=${size} height=${size} alt=""
    src=${'https://logo.clearbit.com/' + domain}
    onError=${e=>{ const t=e.target;
      if(!t.dataset.fb){ t.dataset.fb='1'; t.src='https://www.google.com/s2/favicons?domain='+domain+'&sz=64'; }
      else { t.style.visibility='hidden'; } }} />`;
}

/* Renders the 'signals' step of a play: which platforms answered, plus the
   posts the next step actually reasoned over (so the teardown is auditable). */

export const initialsOf = s => ((s||'?').trim().split(/\s+/).slice(0,2).map(w=>w[0]||'').join('') || '?').toUpperCase();

export const joinDots = nodes => nodes.filter(Boolean).flatMap((n,i)=> i ? [html`<span class="dotsep"></span>`, n] : [n]);

/* ── Shared dropdown. Renders a labelled button + a popover that closes on an
   outside click or Escape. `children` is a render function given a `close`
   callback so items can dismiss the menu. Used by Signals, Reports, Monitor. ── */

export function Picker({label, caption, icon, active, children, align='left', minW=210, title}){
  const [open,setOpen]=useState(false);
  const ref=useRef(null);
  useEffect(()=>{ if(!open) return;
    const onDoc=e=>{ if(ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey=e=>{ if(e.key==='Escape') setOpen(false); };
    document.addEventListener('mousedown',onDoc); document.addEventListener('keydown',onKey);
    return ()=>{ document.removeEventListener('mousedown',onDoc); document.removeEventListener('keydown',onKey); };
  },[open]);
  return html`<div class="pk" ref=${ref}>
    <button type="button" class=${'pk-btn'+(active?' on':'')} aria-haspopup="menu" aria-expanded=${open}
      title=${title||''} onClick=${()=>setOpen(o=>!o)}>
      ${icon?html`<${Icon} name=${icon} size=15/>`:''} ${label}
      ${caption?html`<span class="pk-cap">${caption}</span>`:''}
      <${Icon} name="caretDown" size=14/>
    </button>
    ${open && html`<div class="pk-pop" role="menu" style=${align+':0;min-width:'+minW+'px'}
      onMouseDown=${e=>e.stopPropagation()}>${children(()=>setOpen(false))}</div>`}
  </div>`;
}

/* ── Date range control (a Picker with presets + a custom from/to). Value shape:
   {preset} for a preset, {preset:'custom', from, to} for a custom span. ── */

export const DR_PRESETS = [['all','Any time'],['1','Last 24 hours'],['7','Last 7 days'],
                    ['30','Last 30 days'],['90','Last 90 days']];

export const drActive = v => !!(v && v.preset && v.preset!=='all' && (v.preset!=='custom' || v.from || v.to));

export function drLabel(v){
  if(!drActive(v)) return 'Any time';
  if(v.preset==='custom') return (v.from||'…')+' → '+(v.to||'…');
  const p=DR_PRESETS.find(x=>x[0]===v.preset); return p?p[1]:'Any time';
}
/* True when `tsLike` (ISO string or epoch) falls inside the range. Undated items
   are dropped by an active range (they cannot be placed on the timeline). */

export function inDateRange(tsLike, v){
  if(!drActive(v)) return true;
  const t = typeof tsLike==='number' ? tsLike : (tsLike?Date.parse(tsLike):NaN);
  if(Number.isNaN(t)) return false;
  if(v.preset==='custom'){
    const from = v.from ? Date.parse(v.from) : -Infinity;
    const to   = v.to   ? Date.parse(v.to)+864e5 : Infinity;   // inclusive end day
    return t>=from && t<=to;
  }
  const days=Number(v.preset); return !days ? true : t >= Date.now()-days*864e5;
}

export function DateRange({value, onChange}){
  const v = value || {preset:'all'};
  return html`<${Picker} icon="calendar" label="When" caption=${drLabel(v)} active=${drActive(v)}
    minW=232 title="Filter by date">
    ${close=>html`<div>
      ${DR_PRESETS.map(([id,lbl])=>{ const on = (v.preset||'all')===id;
        return html`<button type="button" class="pk-item" role="menuitemradio" aria-checked=${on}
          onClick=${()=>{ onChange({preset:id}); close(); }}>${lbl}
          ${on?html`<span class="pk-ck"><${Icon} name="check" size=14/></span>`:''}</button>`; })}
      <div class="pk-sep"></div>
      <div class="pk-lbl">Custom range</div>
      <div style="display:flex;flex-direction:column;gap:8px;padding:0 8px 4px">
        <input type="date" class="pk-date" aria-label="From" value=${v.from||''}
          onInput=${e=>onChange({preset:'custom', from:e.target.value, to:v.to})}/>
        <input type="date" class="pk-date" aria-label="To" value=${v.to||''}
          onInput=${e=>onChange({preset:'custom', from:v.from, to:e.target.value})}/>
        ${drActive(v)?html`<button type="button" class="pk-item" style="justify-content:center;color:var(--ink-red-3)"
          onClick=${()=>{ onChange({preset:'all'}); close(); }}><${Icon} name="close" size=13/> Clear</button>`:''}
      </div>
    </div>`}
  </${Picker}>`;
}

/* Classify the search box. Signals keys off a handle or profile URL, never a
   display name (no source resolves "First Last"). A pasted profile link routes
   straight to its one source. Returns one of:
   {kind:'empty'} | {kind:'url', platform, handle} | {kind:'url-unknown'}
   | {kind:'email', value} | {kind:'handle', value} | {kind:'name', value} */


/* ── Daily Report: scheduled keyword-group signal briefs (api/_report.py) ── */
export function agoFrom(iso){
  if(!iso) return '';
  const t = Date.parse(iso); if(isNaN(t)) return '';
  const s = Math.max(0,(Date.now()-t)/1000);
  if(s<3600) return Math.round(s/60)+'m ago';
  if(s<86400) return Math.round(s/3600)+'h ago';
  return Math.round(s/86400)+'d ago';
}

export const SENT_PILL = {positive:'pill-green', negative:'pill-red', neutral:'pill-gray'};

export const platIcon = p => p==='x' ? 'twitter' : p;
