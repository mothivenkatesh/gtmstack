/* Tables module: Airtable-like grid */
import { API_BASE, Icon, h, html, useEffect, useMemo, useRef, useState } from './core.js';


/* ════════════════════════ TABLES (Airtable/Notion-like, JSON-first) ════════════════════════ */
export const TBL_KEY = 'gtmstack.tables.v1';

export const TBL_VIEW_KEY = 'gtmstack.tables.view';

export const TBL_COLORS = new Set(['blue','green','amber','red','gray']);

export const newId = () => 'r'+Date.now().toString(36)+Math.random().toString(36).slice(2,6);

export const pillFor = c => TBL_COLORS.has(c) ? 'pill-'+c : 'pill-gray';

export const optOf = (col,id) => (col.options||[]).find(o=>o.id===id) || null;

export function fmtDate(iso){
  if(!iso) return '';
  try{ return new Intl.DateTimeFormat('en',{month:'short',day:'numeric',year:'numeric'}).format(new Date(iso)); }
  catch(e){ return String(iso); }
}

export function dateBand(iso){
  if(!iso || Number.isNaN(Date.parse(iso))) return '';
  const d = new Date(iso), t = new Date(); t.setHours(0,0,0,0);
  if(d < t) return 'overdue';
  if((d - t) <= 7*864e5) return 'soon';
  return '';
}

/* Rendered text of a cell, so global search hits labels not ids. */
export function cellText(v, col){
  if(v==null) return '';
  if(col.type==='select') return optOf(col,v)?.label || String(v);
  if(col.type==='multi_select') return (Array.isArray(v)?v:[]).map(id=>optOf(col,id)?.label||id).join(' ');
  if(col.type==='date') return fmtDate(v);
  if(col.type==='checkbox') return v ? 'yes' : 'no';
  return String(v);
}

export function emptyValueFor(col){
  if(col.type==='multi_select') return [];
  if(col.type==='number') return null;
  if(col.type==='checkbox') return false;
  return '';
}

export const _isEmpty = v => v==null || v==='' || (Array.isArray(v) && v.length===0);
/* Per-type behaviour. render/editor live in Cell (dispatch on type); TYPE_META
   stays pure data: an icon, a matches(cell,filter,col) and a compare(a,b,col)
   that always sorts empties last (the sort wrapper re-pins on desc). */

export const TYPE_META = {
  text: {icon:'textAa',
    matches:(v,q)=>String(v??'').toLowerCase().includes(String(q).toLowerCase()),
    compare:(a,b)=>String(a??'').localeCompare(String(b??''))},
  longtext: {icon:'textAa',
    matches:(v,q)=>String(v??'').toLowerCase().includes(String(q).toLowerCase()),
    compare:(a,b)=>String(a??'').localeCompare(String(b??''))},
  url: {icon:'globe',
    matches:(v,q)=>String(v??'').toLowerCase().includes(String(q).toLowerCase()),
    compare:(a,b)=>String(a??'').localeCompare(String(b??''))},
  number: {icon:'hash',
    matches:(v,q)=>{
      const s=String(q).trim();
      let m;
      if((m=s.match(/^>\s*(-?\d+\.?\d*)$/))) return typeof v==='number' && v>parseFloat(m[1]);
      if((m=s.match(/^<\s*(-?\d+\.?\d*)$/))) return typeof v==='number' && v<parseFloat(m[1]);
      if((m=s.match(/^(-?\d+\.?\d*)\s*-\s*(-?\d+\.?\d*)$/))) return typeof v==='number' && v>=parseFloat(m[1]) && v<=parseFloat(m[2]);
      return String(v??'').includes(s);
    },
    compare:(a,b)=>(a==null?0:a)-(b==null?0:b)},
  select: {icon:'tag',
    matches:(v,q,col)=> Array.isArray(q) ? q.includes(v) : (optOf(col,v)?.label||String(v??'')).toLowerCase().includes(String(q).toLowerCase()),
    compare:(a,b,col)=>{
      const ix=id=>{ const i=(col.options||[]).findIndex(o=>o.id===id); return i<0?(col.options||[]).length:i; };
      return ix(a)-ix(b);
    }},
  multi_select: {icon:'list',
    matches:(v,q,col)=>{ const arr=Array.isArray(v)?v:[];
      return Array.isArray(q) ? arr.some(id=>q.includes(id))
        : arr.some(id=>(optOf(col,id)?.label||id).toLowerCase().includes(String(q).toLowerCase())); },
    compare:(a,b)=>((Array.isArray(a)?a.length:0)-(Array.isArray(b)?b.length:0))},
  date: {icon:'calendar',
    matches:(v,q)=>{
      if(q && typeof q==='object' && !Array.isArray(q)){   // {from,to} range filter
        if(_isEmpty(v)) return false;
        const t=Date.parse(v); if(Number.isNaN(t)) return false;
        const from=q.from?Date.parse(q.from):-Infinity;
        const to=q.to?Date.parse(q.to)+864e5:Infinity;      // inclusive end day
        return t>=from && t<=to;
      }
      return String(v??'').includes(String(q));
    },
    compare:(a,b)=>{ const pa=Date.parse(a), pb=Date.parse(b);
      if(Number.isNaN(pa)&&Number.isNaN(pb)) return 0;
      if(Number.isNaN(pa)) return 1; if(Number.isNaN(pb)) return -1; return pa-pb; }},
  checkbox: {icon:'check',
    matches:(v,q)=>{ const s=String(q).toLowerCase();
      if(['true','yes','1'].includes(s)) return v===true;
      if(['false','no','0'].includes(s)) return v===false; return true; },
    compare:(a,b)=>(a?1:0)-(b?1:0)},
};
/* A column filter is one of: an array (select ids), a {from,to} object (date
   range, date columns only), or a non-empty string. These read its state. */

export const filterActive = (f, col) =>
  Array.isArray(f) ? f.length>0
  : (f && typeof f==='object') ? (col && col.type==='date' ? !!(f.from||f.to) : false)
  : (f!==undefined && f!=='');

export const filterLabel = (f, col) =>
  Array.isArray(f) ? f.map(id=>optOf(col,id)?.label||id).join(', ')
  : (f && typeof f==='object') ? (f.from||'…')+' → '+(f.to||'…')
  : f;

export const SAMPLE = {
  name:'GTM Pipeline',
  cols:[
    {key:'merchant', label:'Merchant', type:'text', hidden:false, width:180},
    {key:'stage', label:'Stage', type:'select', hidden:false, width:150, options:[
      {id:'lead',label:'Lead',color:'gray'},{id:'demo',label:'Demo booked',color:'blue'},
      {id:'trial',label:'Trial',color:'amber'},{id:'live',label:'Live',color:'green'},
      {id:'churned',label:'Churned',color:'red'}]},
    {key:'channels', label:'Products', type:'multi_select', hidden:false, width:220, options:[
      {id:'pg',label:'Payment Gateway',color:'blue'},{id:'payouts',label:'Payouts',color:'green'},
      {id:'relay',label:'Relay',color:'amber'},{id:'secureid',label:'Secure ID',color:'gray'}]},
    {key:'partner', label:'Partner', type:'text', hidden:false, width:150},
    {key:'gmv', label:'Monthly GMV (L)', type:'number', hidden:false, width:130},
    {key:'nextStep', label:'Next step', type:'longtext', hidden:true, width:260},
    {key:'signed', label:'Signed', type:'checkbox', hidden:false, width:90},
    {key:'lastTouch', label:'Last touch', type:'date', hidden:false, width:140},
    {key:'url', label:'Deal doc', type:'url', hidden:false, width:160}
  ],
  rows:[
    {_id:'r1', merchant:'Zylker D2C', stage:'trial', channels:['pg','relay'], partner:'Growth360', gmv:42, nextStep:'Ship the recon agent template, then confirm outcome-based pricing above 30L GMV.', signed:false, lastTouch:'2026-06-28', url:'https://docs.example.com/zylker'},
    {_id:'r2', merchant:'RocketPay NBFC', stage:'live', channels:['payouts','relay'], partner:'Direct', gmv:180, nextStep:'Loan-recovery voice agent live. Track EMI-bounce branch conversion weekly.', signed:true, lastTouch:'2026-07-01', url:'https://docs.example.com/rocketpay'},
    {_id:'r3', merchant:'Meesho Ops', stage:'demo', channels:['pg','payouts'], partner:'Direct', gmv:0, nextStep:'Automate daily bank recon (refunds + payouts) via Relay into Oracle. Commercials deferred.', signed:false, lastTouch:'2026-06-20', url:''},
    {_id:'r4', merchant:'OSW Cart', stage:'lead', channels:['relay'], partner:'Zostel voice partner', gmv:9, nextStep:'Cart-voice recovery pilot. Qualify GMV before white-glove onboarding.', signed:false, lastTouch:'2026-06-05', url:''},
    {_id:'r5', merchant:'FlexyPe', stage:'churned', channels:['pg'], partner:'Direct', gmv:0, nextStep:'Blocked on status-callback recon dispute. Hold until Madras HC hearing outcome.', signed:false, lastTouch:'2026-05-30', url:''},
    {_id:'r6', merchant:'Byspeed', stage:'trial', channels:['pg','secureid'], partner:'IT agency', gmv:31, nextStep:'Onboarding series in progress. Push Secure ID 1-click KYC next.', signed:false, lastTouch:'2026-07-02', url:''},
    {_id:'r7', merchant:'Jaipur Handmade', stage:'demo', channels:['relay','pg'], partner:'Reddit inbound', gmv:14, nextStep:'From the Jaipur Reddit thread. COD to prepaid via OCC next.', signed:false, lastTouch:'2026-07-05', url:'https://example.com/jaipur'},
    {_id:'r8', merchant:'SMB Cohort A', stage:'lead', channels:['pg'], partner:'Event batch', gmv:6, nextStep:'Batch of 12 SMBs from the D2C event. Group onboarding.', signed:false, lastTouch:'2026-07-08', url:''}
  ]
};

export const TBL_TYPES = [
  {id:'text',label:'Text'},{id:'longtext',label:'Long text'},{id:'number',label:'Number'},
  {id:'select',label:'Select'},{id:'multi_select',label:'Multi-select'},{id:'date',label:'Date'},
  {id:'checkbox',label:'Checkbox'},{id:'url',label:'URL'}
];

export const TBL_PALETTE = ['blue','green','amber','red','gray'];

/* a filesystem-safe unique column key from a label */
export function uniqueKey(base, cols){
  let k = String(base||'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'') || 'field';
  const used = new Set(cols.map(c=>c.key)); let n=k, i=2;
  while(used.has(n)){ n=k+'_'+i; i++; }
  return n;
}

/* migrate a cell value when its column type changes, so no data is silently lost */
export function coerceValue(v, toType){
  if(toType==='number'){ const n=parseFloat(v); return Number.isFinite(n)?n:null; }
  if(toType==='checkbox') return !!v && v!=='false' && v!=='0';
  if(toType==='multi_select') return Array.isArray(v) ? v : (_isEmpty(v)?[]:[String(v)]);
  if(toType==='select') return Array.isArray(v) ? (v[0]??'') : (_isEmpty(v)?'':String(v));
  if(toType==='date'){ const s=String(v??''); return Number.isNaN(Date.parse(s))?'':s.slice(0,10); }
  if(Array.isArray(v)) return v.join(', ');
  if(v==null) return ''; if(typeof v==='boolean') return v?'true':'';
  return String(v);
}


export function validateDb(obj){
  try{
    if(!obj || typeof obj!=='object' || Array.isArray(obj)) return {ok:false, err:'The JSON must be an object with cols and rows.'};
    if(!Array.isArray(obj.cols) || !Array.isArray(obj.rows)) return {ok:false, err:'Both cols and rows must be arrays.'};
    const seen=new Set();
    for(const c of obj.cols){
      if(!c || typeof c.key!=='string' || !c.key) return {ok:false, err:'Every column needs a non-empty key.'};
      if(seen.has(c.key)) return {ok:false, err:'Duplicate column key: '+c.key}; seen.add(c.key);
      if(!TYPE_META[c.type]) return {ok:false, err:'Unknown column type: '+String(c.type)};
      if(typeof c.label!=='string' || !c.label) c.label=c.key;
      c.hidden=!!c.hidden; c.width=Number(c.width)||160;
      if(c.type==='select'||c.type==='multi_select'){
        if(!Array.isArray(c.options)) c.options=[];
        c.options=c.options.map(o=>({id:String(o.id), label:String(o.label??o.id), color:TBL_COLORS.has(o.color)?o.color:'gray'}));
      }
    }
    const rows=obj.rows.map(r=>({...r, _id:(r&&r._id)||newId()}));
    return {ok:true, db:{name:String(obj.name||'Table'), cols:obj.cols, rows}};
  }catch(e){ return {ok:false, err:'Could not read that JSON.'}; }
}


/* ── column create/edit modal (name, type, and select options) ── */
export function FieldEditor({col, onSave, onClose}){
  const [draft,setDraft]=useState(()=> col
    ? {label:col.label, type:col.type, format:col.format||'', options:(col.options||[]).map(o=>({...o}))}
    : {label:'', type:'text', format:'', options:[]});
  const setD=(k,v)=> setDraft(o=>({...o,[k]:v}));
  const needsOpts = draft.type==='select' || draft.type==='multi_select';
  const addOpt=()=> setDraft(o=>({...o, options:[...(o.options||[]), {id:newId(), label:'Option', color:TBL_PALETTE[(o.options?.length||0)%TBL_PALETTE.length]}]}));
  const setOpt=(i,k,v)=> setDraft(o=>({...o, options:o.options.map((op,j)=>j===i?{...op,[k]:v}:op)}));
  const delOpt=i=> setDraft(o=>({...o, options:o.options.filter((_,j)=>j!==i)}));
  function save(){
    const def={label:(draft.label||'').trim()||'Untitled', type:draft.type};
    if(needsOpts) def.options=(draft.options||[]).map(o=>({id:o.id||newId(), label:(o.label||'').trim()||'Option', color:TBL_COLORS.has(o.color)?o.color:'gray'}));
    if(draft.type==='number' && draft.format) def.format=draft.format;
    onSave(def);
  }
  return html`<div class="tbl-overlay" onMouseDown=${onClose}>
    <div class="tbl-modal" role="dialog" aria-modal="true" aria-label=${col?'Edit field':'New field'}
      onMouseDown=${e=>e.stopPropagation()} onKeyDown=${e=>{if(e.key==='Escape')onClose();}}>
      <div style="font-weight:600;margin-bottom:16px">${col?'Edit field':'New field'}</div>
      <label class="fld">Name<input class="input" value=${draft.label} autofocus onInput=${e=>setD('label',e.target.value)}/></label>
      <label class="fld">Type<select class="input" value=${draft.type} onChange=${e=>setD('type',e.target.value)}>
        ${TBL_TYPES.map(t=>html`<option value=${t.id} selected=${t.id===draft.type}>${t.label}</option>`)}</select></label>
      ${draft.type==='number' && html`<label class="fld">Format<select class="input" value=${draft.format} onChange=${e=>setD('format',e.target.value)}>
        <option value="" selected=${!draft.format}>Plain number</option><option value="currency" selected=${draft.format==='currency'}>Currency (₹)</option></select></label>`}
      ${col && col.type!==draft.type && html`<div style="font-size:12px;color:var(--ink-amber-2);margin:4px 0 8px"><${Icon} name="alert" size=12/> Changing type converts existing values.</div>`}
      ${needsOpts && html`<div style="margin-top:8px">
        <div style="font-size:12px;color:var(--ink-gray-6);margin-bottom:8px">Options</div>
        ${(draft.options||[]).map((o,i)=>html`<div key=${o.id} style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <span class=${'pill '+pillFor(o.color)} style="min-width:54px;text-align:center">${o.label||'…'}</span>
          <input class="input" style="flex:1" value=${o.label} onInput=${e=>setOpt(i,'label',e.target.value)}/>
          <select class="input" style="width:92px" value=${o.color} onChange=${e=>setOpt(i,'color',e.target.value)}>
            ${TBL_PALETTE.map(c=>html`<option value=${c} selected=${c===o.color}>${c}</option>`)}</select>
          <span style="cursor:pointer;color:var(--ink-gray-5)" onClick=${()=>delOpt(i)}><${Icon} name="trash" size=13/></span></div>`)}
        <button class="pill pill-gray" style="cursor:pointer;border:1px solid var(--outline-gray-2)" onClick=${addOpt}><${Icon} name="plus" size=11/> Add option</button></div>`}
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
        <button class="pill pill-gray" style="cursor:pointer;border:1px solid var(--outline-gray-2)" onClick=${onClose}>Cancel</button>
        <button class="pill pill-blue" style="cursor:pointer;border:none" onClick=${save}><${Icon} name="check" size=12/> Save</button></div>
    </div></div>`;
}


/* ── per-column header dropdown ── */
export function ColumnMenu({col, filterVal, setFilter, onSortDir, onEdit, onHide, onDelete, onClose}){
  const item=(icon,label,fn,danger)=>html`<button type="button" class="tbl-mi" role="menuitem"
    style=${danger?'color:var(--ink-red-3)':''} onClick=${()=>{fn();onClose();}}><${Icon} name=${icon} size=12/> ${label}</button>`;
  const isSel = col.type==='select' || col.type==='multi_select';
  const arr = Array.isArray(filterVal) ? filterVal : [];
  return html`<div class="tbl-menu" role="menu" aria-label=${col.label+' options'} style="left:0;right:auto;min-width:210px" onMouseDown=${e=>e.stopPropagation()} onClick=${e=>e.stopPropagation()}>
    <div class="tbl-mi-label"><${Icon} name="funnel" size=12/> Filter</div>
    ${isSel
      ? html`<div style="display:flex;flex-wrap:wrap;gap:4px;padding:4px 8px 8px">
          ${(col.options||[]).map(o=>{ const on=arr.includes(o.id);
            return html`<button type="button" class=${'pill '+(on?pillFor(o.color):'pill-gray')} style="cursor:pointer;border:none;opacity:${on?1:.55}"
              onClick=${()=>setFilter(on?arr.filter(x=>x!==o.id):[...arr,o.id])}>${o.label}</button>`; })}
          ${(col.options||[]).length===0?html`<span style="font-size:12px;color:var(--ink-gray-5)">No options yet.</span>`:''}</div>`
      : col.type==='date'
      ? (()=>{ const fv=(filterVal&&typeof filterVal==='object')?filterVal:{};
          const upd=(from,to)=>setFilter((from||to)?{from,to}:'');
          return html`<div style="padding:4px 8px 8px;display:flex;flex-direction:column;gap:8px">
            <label style="font-size:11px;color:var(--ink-gray-5)">From<input type="date" class="pk-date" aria-label=${col.label+' from'}
              value=${fv.from||''} onInput=${e=>upd(e.target.value, fv.to)}/></label>
            <label style="font-size:11px;color:var(--ink-gray-5)">To<input type="date" class="pk-date" aria-label=${col.label+' to'}
              value=${fv.to||''} onInput=${e=>upd(fv.from, e.target.value)}/></label>
            ${(fv.from||fv.to)?html`<button type="button" class="tbl-mi" style="justify-content:center;color:var(--ink-red-3);padding:4px" onClick=${()=>setFilter('')}><${Icon} name="close" size=12/> Clear</button>`:''}</div>`; })()
      : html`<div style="padding:4px 8px 8px"><input class="search-mini" autofocus value=${filterVal||''}
          placeholder=${col.type==='number'?'e.g. >50 or 10-99':'Contains…'} onInput=${e=>setFilter(e.target.value)}/></div>`}
    <div class="tbl-mi-sep"></div>
    ${item('caretUp','Sort ascending',()=>onSortDir('asc'))}
    ${item('caretDown','Sort descending',()=>onSortDir('desc'))}
    ${item('pen','Edit field',onEdit)}
    ${item('eye','Hide field',onHide)}
    ${item('trash','Delete field',onDelete,true)}
  </div>`;
}

/* ── shared value renderer (used by the table Cell, list rows, and board cards
   so every view shows chips / dates / numbers / links identically) ── */

export function cellDisplay(v, col){
  if(col.type==='select'){
    const o=optOf(col,v);
    return _isEmpty(v) ? '' : html`<span class=${'pill '+pillFor(o?.color)}>${o?.label||v}</span>`;
  }
  if(col.type==='multi_select'){
    const arr=Array.isArray(v)?v:[];
    return html`<div style="display:flex;gap:4px;flex-wrap:wrap;min-width:0">
      ${arr.map(id=>{ const o=optOf(col,id); return html`<span class=${'pill '+pillFor(o?.color)}>${o?.label||id}</span>`; })}</div>`;
  }
  if(col.type==='date'){
    if(_isEmpty(v)) return '';
    const band=dateBand(v);
    return html`<span style="display:inline-flex;align-items:center;gap:8px;min-width:0;max-width:100%">
      <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${fmtDate(v)}</span>
      ${band==='overdue'?html`<span class="pill pill-red" style="flex-shrink:0">overdue</span>`
        :band==='soon'?html`<span class="pill pill-amber" style="flex-shrink:0">soon</span>`:''}</span>`;
  }
  if(col.type==='number')
    return html`<span class="mono">${_isEmpty(v)||!Number.isFinite(Number(v))?'':(col.format==='currency'?'₹':'')+Number(v).toLocaleString()}</span>`;
  if(col.type==='url')
    return v ? html`<a href=${v} target="_blank" rel="noopener" style="color:var(--ink-violet-1);text-decoration:none">
      <${Icon} name="externalLink" size=11/> ${(()=>{ try{return new URL(v).hostname;}catch(e){return v;} })()}</a>` : '';
  if(col.type==='checkbox')
    return v ? html`<${Icon} name="check" size=14/>` : html`<span style="color:var(--ink-gray-4)">—</span>`;
  if(col.type==='longtext')
    return html`<div class="cell-clamp" title=${v||''}>${v||''}</div>`;
  return html`<span>${v||''}</span>`;
}


/* ── one editable cell (renders + edits by column type) ── */
export function Cell({row, col, editing, setEditing, setCellValue, sticky}){
  const v = row[col.key];
  const tdCls = 'tbl-td'+(sticky?' tbl-sticky1':'');
  const isEd = editing && editing.rowId===row._id && editing.key===col.key;
  const commit = val => { setCellValue(row._id, col.key, val); setEditing(null); };
  const start = () => { if(col.type!=='checkbox') setEditing({rowId:row._id, key:col.key}); };
  const onKey = e => { if(e.key==='Enter'){ e.preventDefault(); commit(e.target.value); } if(e.key==='Escape') setEditing(null); };

  if(col.type==='checkbox')
    return html`<td class=${tdCls} style="width:${col.width}px">
      <input type="checkbox" aria-label=${col.label} checked=${!!v} onChange=${e=>setCellValue(row._id,col.key,e.target.checked)} style="cursor:pointer"/></td>`;

  if(isEd){
    let ed;
    if(col.type==='longtext')
      ed = html`<textarea class="cell-edit" autofocus rows=3 onBlur=${e=>commit(e.target.value)} onKeyDown=${e=>{if(e.key==='Escape')setEditing(null);}}>${v||''}</textarea>`;
    else if(col.type==='number')
      ed = html`<input class="cell-edit" type="number" autofocus value=${v==null?'':v} onBlur=${e=>commit(e.target.value===''?null:Number(e.target.value))} onKeyDown=${e=>{if(e.key==='Enter'){e.preventDefault();commit(e.target.value===''?null:Number(e.target.value));}if(e.key==='Escape')setEditing(null);}}/>`;
    else if(col.type==='date')
      ed = html`<input class="cell-edit" type="date" autofocus aria-label=${col.label} value=${v||''} onChange=${e=>commit(e.target.value)} onBlur=${e=>commit(e.target.value)} onKeyDown=${e=>{if(e.key==='Escape')setEditing(null);}}/>`;
    else if(col.type==='select')
      ed = html`<select class="cell-edit" autofocus onChange=${e=>commit(e.target.value)}>
        <option value="">(none)</option>
        ${(col.options||[]).map(o=>html`<option value=${o.id} selected=${o.id===v}>${o.label}</option>`)}</select>`;
    else if(col.type==='multi_select')
      ed = html`<div style="display:flex;gap:4px;flex-wrap:wrap;padding:4px 0">
        ${(col.options||[]).map(o=>{ const on=(Array.isArray(v)?v:[]).includes(o.id);
          return html`<span class=${'pill '+(on?pillFor(o.color):'pill-gray')} style="cursor:pointer;opacity:${on?1:.5}"
            onClick=${()=>{ const cur=Array.isArray(v)?v:[]; setCellValue(row._id,col.key, on?cur.filter(x=>x!==o.id):[...cur,o.id]); }}>${o.label}</span>`; })}
        <span class="pill pill-gray" style="cursor:pointer" onClick=${()=>setEditing(null)}>done</span></div>`;
    else
      ed = html`<input class="cell-edit" autofocus value=${v||''} onBlur=${e=>commit(e.target.value)} onKeyDown=${onKey}/>`;
    return html`<td class=${tdCls} style="width:${col.width}px">${ed}</td>`;
  }

  return html`<td class=${tdCls} style="width:${col.width}px;cursor:text" onClick=${start}>${cellDisplay(v, col)}</td>`;
}


/* ── header (sortable) + per-column filter rows ── */
export function TableHead({gid, visibleCols, sortBy, sortDir, onSort, colFilters, setColFilter, menuKey, setMenuKey,
                   colMenu, setColMenu, onSortDir, onEditCol, onHideCol, onDeleteCol, onAddColumn,
                   onMoveCol, dropCol, setDropCol, dragRef, resizeRef, onResizeCol, allSel, toggleAllSel}){
  /* colMenu + dropCol are scoped by {key, gid}: the header row is repeated once
     per group, so keying by col.key alone opened the menu (or lit the drop target)
     in every group at once. gid makes only the acted-on group react. */
  const menuOpen = c => colMenu && colMenu.key===c && colMenu.gid===gid;
  const dropHere = c => dropCol && dropCol.key===c && dropCol.gid===gid;
  return html`<thead>
    <tr>
      <th class="tbl-th tbl-actcol" scope="col">
        <input type="checkbox" class="tbl-rowck" aria-label="Select all rows" checked=${allSel}
          onMouseDown=${e=>e.stopPropagation()} onChange=${toggleAllSel}/></th>
      ${visibleCols.map((col,ci)=>{
        const asort = sortBy===col.key ? (sortDir==='asc'?'ascending':'descending') : 'none';
        const startResize = e => { e.stopPropagation(); e.preventDefault(); resizeRef.current=true;
          const startX=e.clientX, startW=col.width||160; let raf=null, last=startW;
          const mm=ev=>{ last=Math.max(80, startW+(ev.clientX-startX)); if(!raf) raf=requestAnimationFrame(()=>{ onResizeCol(col.key,last); raf=null; }); };
          const mu=()=>{ document.removeEventListener('mousemove',mm); document.removeEventListener('mouseup',mu);
            onResizeCol(col.key,last); setTimeout(()=>{resizeRef.current=false;},0); };
          document.addEventListener('mousemove',mm); document.addEventListener('mouseup',mu); };
        return html`<th key=${col.key} class=${'tbl-th tbl-thcol'+(dropHere(col.key)?' tbl-drop-col':'')}
          scope="col" aria-sort=${asort} style="width:${col.width}px;padding:0;position:relative"
          draggable=true
          onDragStart=${e=>{ if(resizeRef.current){ e.preventDefault(); return; } dragRef.current.col=col.key; e.dataTransfer.effectAllowed='move'; try{e.dataTransfer.setData('text/plain',col.key);}catch(_){} }}
          onDragEnd=${()=>{ dragRef.current.col=null; setDropCol(null); }}
          onDragOver=${e=>{ if(dragRef.current.col!=null && dragRef.current.col!==col.key){ e.preventDefault(); if(!dropHere(col.key)) setDropCol({key:col.key, gid}); } }}
          onDrop=${e=>{ e.preventDefault(); const src=dragRef.current.col; if(src){ onMoveCol(src, col.key); } dragRef.current.col=null; setDropCol(null); }}>
        <div style="display:flex;align-items:center;gap:4px;padding:8px;cursor:grab;user-select:none">
          <span role="button" tabindex="0" aria-label=${'Sort by '+col.label}
            style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;flex:1;min-width:0"
            onClick=${()=>onSort(col.key)} onKeyDown=${e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSort(col.key);}}}>
            <${Icon} name=${TYPE_META[col.type].icon} size=11/> <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${col.label}</span>
            ${sortBy===col.key ? html`<${Icon} name=${sortDir==='asc'?'caretUp':'caretDown'} size=10/>` : ''}</span>
          <button type="button" class="iconbtn" aria-label=${col.label+' field options'} aria-haspopup="menu"
            style="position:relative" draggable=false onMouseDown=${e=>e.stopPropagation()} onClick=${()=>setColMenu(menuOpen(col.key)?null:{key:col.key, gid})}>
            <${Icon} name="dots" size=13/>
            ${menuOpen(col.key) && html`<${ColumnMenu} col=${col}
              filterVal=${colFilters[col.key]} setFilter=${v=>setColFilter(col.key, v)}
              onSortDir=${d=>onSortDir(col.key,d)} onEdit=${()=>onEditCol(col.key)}
              onHide=${()=>onHideCol(col.key)} onDelete=${()=>onDeleteCol(col.key)} onClose=${()=>setColMenu(null)}/>`}
          </button>
        </div>
        <div class="col-resize" title="Drag to resize" draggable=false onMouseDown=${startResize} onClick=${e=>e.stopPropagation()}></div></th>`;
      })}
      <th class="tbl-th" scope="col" style="width:40px;text-align:center">
        <button type="button" class="iconbtn" aria-label="Add column"
          onMouseDown=${e=>e.stopPropagation()} onClick=${onAddColumn}><${Icon} name="plus" size=14/></button></th>
      <th class="tbl-th" scope="col" aria-hidden="true"></th>
    </tr>
  </thead>`;
}


/* ── one collapsible group block (or the single implicit group) ── */
export const TBL_GUTTER = 80, TBL_ADDCOL = 40;   // gutter: checkbox/number + hover actions

export function GroupBlock({group, groupByCol, visibleCols, collapsed, toggleCollapse, headProps, ghostRows=0}){
  const open = groupByCol ? !collapsed.has(group.id) : true;
  const {onDeleteRow, onDuplicateRow, onAddRow} = headProps;
  /* fixed table layout + explicit width: the colgroup is the single source of
     truth for column widths, so header and body align exactly and resizing a
     column just changes its col width. */
  const totalW = TBL_GUTTER + visibleCols.reduce((s,c)=>s+(c.width||160),0) + TBL_ADDCOL;
  /* a new row in a group pre-fills the grouped column with the group's value */
  const groupPreset = () => {
    if(!groupByCol || group.isEmpty) return {};
    /* group.key is a string bucket key; coerce it back to the column's type so a
       number-grouped new row stores 42, not "42" (which fails number filters).
       multi_select keeps its array wrap (coerceValue would double-wrap). */
    return {[groupByCol.key]: groupByCol.type==='multi_select' ? [group.key] : coerceValue(group.key, groupByCol.type)};
  };
  const colspan = visibleCols.length + 3;   // gutter + cols + add-col + filler
  return html`<div>
    ${groupByCol && html`<div class="tbl-grouphead" role="button" tabindex="0" aria-expanded=${open}
      onClick=${()=>toggleCollapse(group.id)} onKeyDown=${e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggleCollapse(group.id);}}}>
      <${Icon} name=${open?'caretDown':'caretRight'} size=12/>
      ${(groupByCol.type==='select'||groupByCol.type==='multi_select') && !group.isEmpty
        ? html`<span class=${'pill '+pillFor(optOf(groupByCol,group.key)?.color)}>${group.label}</span>`
        : html`<span style="font-weight:600">${group.label}</span>`}
      <span class="pill pill-gray">· ${group.count}</span>
      ${groupByCol.type==='number' && !group.isEmpty && html`<span style="font-size:12px;color:var(--ink-gray-5)">sum ${(group.sum||0).toLocaleString()} · avg ${Math.round(group.avg||0).toLocaleString()}</span>`}
    </div>`}
    ${open && html`<table style=${'table-layout:fixed;width:100%;min-width:'+totalW+'px;border-collapse:separate;border-spacing:0;font-size:12px'}>
      <colgroup>
        <col style="width:${TBL_GUTTER}px"/>
        ${visibleCols.map(c=>html`<col key=${c.key} style=${'width:'+(c.width||160)+'px'}/>`)}
        <col style="width:${TBL_ADDCOL}px"/>
        <col/>
      </colgroup>
      <${TableHead} gid=${group.id} ...${headProps} />
      <tbody>
        ${group.rows.map((row,i)=>html`<tr key=${row._id} class=${(headProps.dropRow===row._id?'tbl-droprow ':'')+(headProps.selRows.has(row._id)?'rowsel':'')}
          onDragOver=${e=>{ if(headProps.dragRef.current.row!=null && headProps.dragRef.current.row!==row._id){ e.preventDefault(); if(headProps.dropRow!==row._id) headProps.setDropRow(row._id); } }}
          onDrop=${e=>{ e.preventDefault(); const src=headProps.dragRef.current.row; if(src){ headProps.onDropRow(src, row); } headProps.dragRef.current.row=null; headProps.setDropRow(null); }}>
          <td class=${'tbl-td tbl-actcol'+(headProps.canDragRows?' tbl-rowdrag':'')} draggable=${headProps.canDragRows}
            title=${headProps.canDragRows?'Drag to reorder':'Clear the sort to reorder rows'}
            onDragStart=${e=>{ headProps.dragRef.current.row=row._id; e.dataTransfer.effectAllowed='move'; try{e.dataTransfer.setData('text/plain',row._id);}catch(_){} }}
            onDragEnd=${()=>{ headProps.dragRef.current.row=null; headProps.setDropRow(null); }}>
            <div class="gutter-stack">
              <span class="gs-left">
                <span class="tbl-rownum">${i+1}</span>
                <input type="checkbox" class="tbl-rowck" aria-label="Select row" checked=${headProps.selRows.has(row._id)}
                  onMouseDown=${e=>e.stopPropagation()} onClick=${e=>e.stopPropagation()} onChange=${()=>headProps.toggleSel(row._id)}/>
              </span>
              <span class="tbl-row-acts">
                <button type="button" class="iconbtn" aria-label="Duplicate row" onClick=${()=>onDuplicateRow(row._id)}><${Icon} name="copyRow" size=13/></button>
                <button type="button" class="iconbtn acts-del" aria-label="Delete row" onClick=${()=>onDeleteRow(row._id)}><${Icon} name="trash" size=13/></button>
              </span>
            </div></td>
          ${visibleCols.map((col,ci)=>html`<${Cell} key=${col.key} row=${row} col=${col} sticky=${false} editing=${headProps.editing} setEditing=${headProps.setEditing} setCellValue=${headProps.setCellValue}/>`)}
          <td class="tbl-td" style="width:40px"></td>
          <td class="tbl-td"></td>
        </tr>`)}
        <tr><td colspan=${colspan} style="padding:0">
          <button type="button" class="tbl-newrow" onClick=${()=>onAddRow(groupPreset())}><${Icon} name="plus" size=12/> New</button></td></tr>
        ${Array.from({length:ghostRows}).map((_,i)=>html`<tr class="tbl-ghostrow" key=${'g'+i} title="Click to add a row" onClick=${()=>onAddRow({})}>
          <td class="tbl-td tbl-actcol"></td>
          ${visibleCols.map(c=>html`<td key=${c.key} class="tbl-td"></td>`)}
          <td class="tbl-td"></td><td class="tbl-td"></td>
        </tr>`)}
      </tbody>
    </table>`}
  </div>`;
}


/* ── LIST view: each row a compact card (title + property values) ── */
export function ListView({groups, groupByCol, visibleCols, collapsed, toggleCollapse, onDeleteRow, onDuplicateRow, onAddRow, onEditRow}){
  const primary = visibleCols[0];
  const rest = visibleCols.slice(1);
  const groupPreset = g => (!groupByCol||g.isEmpty) ? {} : {[groupByCol.key]: groupByCol.type==='multi_select'?[g.key]:coerceValue(g.key,groupByCol.type)};
  return html`<div>
    ${groups.map(g=>{
      const open = groupByCol ? !collapsed.has(g.id) : true;
      return html`<div key=${g.id} style="margin-bottom:${groupByCol?'14px':'0'}">
        ${groupByCol && html`<div class="tbl-grouphead" role="button" tabindex="0" aria-expanded=${open}
          onClick=${()=>toggleCollapse(g.id)} onKeyDown=${e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggleCollapse(g.id);}}}>
          <${Icon} name=${open?'caretDown':'caretRight'} size=12/>
          ${(groupByCol.type==='select'||groupByCol.type==='multi_select') && !g.isEmpty
            ? html`<span class=${'pill '+pillFor(optOf(groupByCol,g.key)?.color)}>${g.label}</span>`
            : html`<span style="font-weight:600">${g.label}</span>`}
          <span class="pill pill-gray">· ${g.count}</span></div>`}
        ${open && html`<div class="tbl-frame">
          ${g.rows.map(row=>html`<div key=${row._id} class="list-row">
            <button type="button" class="list-title" onClick=${()=>onEditRow(row._id, primary?.key)}>
              ${primary ? (cellText(row[primary.key],primary) || html`<span style="color:var(--ink-gray-5)">Untitled</span>`) : 'Row'}</button>
            <div class="list-props">
              ${rest.map(c=>{ const disp=cellDisplay(row[c.key],c);
                return _isEmpty(row[c.key]) ? '' : html`<span key=${c.key} class="list-prop"><span class="list-plabel">${c.label}</span>${disp}</span>`; })}
            </div>
            <span class="tbl-row-acts">
              <button type="button" class="iconbtn" aria-label="Duplicate row" onClick=${()=>onDuplicateRow(row._id)}><${Icon} name="copyRow" size=13/></button>
              <button type="button" class="iconbtn acts-del" aria-label="Delete row" onClick=${()=>onDeleteRow(row._id)}><${Icon} name="trash" size=13/></button>
            </span>
          </div>`)}
          <button type="button" class="tbl-newrow" onClick=${()=>onAddRow(groupPreset(g))}><${Icon} name="plus" size=12/> New</button>
        </div>`}
      </div>`;
    })}
  </div>`;
}


/* ── BOARD (kanban) view: lanes by a select field, drag a card to restack ── */
export function BoardView({boardCol, rows, visibleCols, setCellValue, onAddRow, onDeleteRow, onEditRow}){
  const [over,setOver]=useState(null);
  if(!boardCol) return html`<div class="glass-card" style="padding:24px;text-align:center;color:var(--ink-gray-5)">
    Board view needs a Select field to stack by. Add one (the + at the end of the header) or pick one from Group.</div>`;
  const inLane = (row, optId) => boardCol.type==='multi_select'
    ? (Array.isArray(row[boardCol.key]) && row[boardCol.key].includes(optId))
    : row[boardCol.key]===optId;
  const laneValue = optId => optId===null ? emptyValueFor(boardCol) : (boardCol.type==='multi_select'?[optId]:optId);
  const lanes = [
    ...(boardCol.options||[]).map(o=>({id:o.id, opt:o, rows:rows.filter(r=>inLane(r,o.id))})),
    {id:'__empty__', opt:null, rows:rows.filter(r=>_isEmpty(r[boardCol.key]))},
  ];
  const cardCols = visibleCols.filter(c=>c.key!==boardCol.key);
  /* drop = a true MOVE. For multi_select we remove the source tag and add the
     target tag (keeping every other tag) instead of replacing the whole array,
     which would silently drop a card's other values. */
  const drop = (e, optId) => { e.preventDefault(); setOver(null);
    const raw=e.dataTransfer.getData('text/plain'); if(!raw) return;
    let id, from=null; try{ const p=JSON.parse(raw); id=p.id; from=p.from; }catch(_){ id=raw; }
    if(!id) return;
    if(boardCol.type==='multi_select'){
      const row=rows.find(r=>r._id===id); const cur=Array.isArray(row&&row[boardCol.key])?row[boardCol.key]:[];
      let next = from ? cur.filter(x=>x!==from) : cur.slice();
      if(optId!==null && !next.includes(optId)) next.push(optId);
      setCellValue(id, boardCol.key, next);
    } else setCellValue(id, boardCol.key, laneValue(optId));
  };
  return html`<div class="board-wrap">
    ${lanes.map(lane=>html`<div key=${lane.id} class=${'board-lane'+(over===lane.id?' drop-over':'')}
      onDragOver=${e=>{e.preventDefault(); if(over!==lane.id) setOver(lane.id);}} onDragLeave=${()=>setOver(o=>o===lane.id?null:o)} onDrop=${e=>drop(e, lane.opt?lane.opt.id:null)}>
      <div class="board-lanehead">
        ${lane.opt ? html`<span class=${'pill '+pillFor(lane.opt.color)}>${lane.opt.label}</span>` : html`<span style="color:var(--ink-gray-5);font-weight:600">No ${boardCol.label}</span>`}
        <span class="pill pill-gray">${lane.rows.length}</span></div>
      <div class="board-cards">
        ${lane.rows.map(row=>html`<div key=${row._id} class="board-card" draggable=true
          onDragStart=${e=>{e.dataTransfer.setData('text/plain', JSON.stringify({id:row._id, from:(lane.opt?lane.opt.id:null)})); e.dataTransfer.effectAllowed='move';}}
          onDragEnd=${()=>setOver(null)}>
          <div style="display:flex;align-items:flex-start;gap:8px">
            <button type="button" class="board-card-title" onClick=${()=>onEditRow(row._id, cardCols[0]?.key)}>
              ${cardCols[0] ? (cellText(row[cardCols[0].key],cardCols[0])||'Untitled') : 'Row'}</button>
            <button type="button" class="iconbtn acts-del" aria-label="Delete row" onClick=${()=>onDeleteRow(row._id)} style="opacity:.35"><${Icon} name="trash" size=12/></button>
          </div>
          ${cardCols.slice(1).map(c=> _isEmpty(row[c.key]) ? '' : html`<div key=${c.key} class="board-field">${cellDisplay(row[c.key],c)}</div>`)}
        </div>`)}
        <button type="button" class="tbl-newrow" style="border-top:none;border-radius:var(--radius)" onClick=${()=>onAddRow(lane.opt?{[boardCol.key]:laneValue(lane.opt.id)}:{})}><${Icon} name="plus" size=12/> New</button>
      </div>
    </div>`)}
  </div>`;
}


/* ── row detail editor (opened from a list row or board card) ── */
export function RowEditor({row, cols, onSet, onDelete, onClose}){
  const field = c => {
    const v=row[c.key];
    if(c.type==='checkbox') return html`<input type="checkbox" checked=${!!v} onChange=${e=>onSet(c.key,e.target.checked)} style="margin-top:4px"/>`;
    if(c.type==='longtext') return html`<textarea class="input" rows=3 value=${v||''} onInput=${e=>onSet(c.key,e.target.value)}></textarea>`;
    if(c.type==='number') return html`<input class="input" type="number" value=${v==null?'':v} onInput=${e=>onSet(c.key, e.target.value===''?null:Number(e.target.value))}/>`;
    if(c.type==='date') return html`<input class="input" type="date" value=${v||''} onInput=${e=>onSet(c.key,e.target.value)}/>`;
    if(c.type==='select') return html`<select class="input" value=${v||''} onChange=${e=>onSet(c.key,e.target.value)}>
      <option value="">(none)</option>${(c.options||[]).map(o=>html`<option value=${o.id} selected=${o.id===v}>${o.label}</option>`)}</select>`;
    if(c.type==='multi_select'){ const arr=Array.isArray(v)?v:[];
      return html`<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">${(c.options||[]).map(o=>{ const on=arr.includes(o.id);
        return html`<button type="button" class=${'pill '+(on?pillFor(o.color):'pill-gray')} style="border:none;cursor:pointer;opacity:${on?1:.5}"
          onClick=${()=>onSet(c.key, on?arr.filter(x=>x!==o.id):[...arr,o.id])}>${o.label}</button>`; })}</div>`; }
    return html`<input class="input" value=${v||''} onInput=${e=>onSet(c.key,e.target.value)}/>`;
  };
  return html`<div class="tbl-overlay" onMouseDown=${onClose}>
    <div class="tbl-modal" role="dialog" aria-modal="true" aria-label="Edit row"
      onMouseDown=${e=>e.stopPropagation()} onKeyDown=${e=>{if(e.key==='Escape')onClose();}}>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
        <span style="font-weight:600">Edit row</span><span style="flex:1"></span>
        <button type="button" class="iconbtn acts-del" aria-label="Delete row" onClick=${()=>{onDelete();onClose();}}><${Icon} name="trash" size=14/></button>
        <button type="button" class="iconbtn" aria-label="Close" onClick=${onClose}><${Icon} name="close" size=15/></button></div>
      ${cols.map(c=>html`<label key=${c.key} class="fld">${c.label}${field(c)}</label>`)}
      <div style="display:flex;justify-content:flex-end;margin-top:16px">
        <button type="button" class="btn btn-primary btn-sm" onClick=${onClose}>Done</button></div>
    </div></div>`;
}


/* ── JSON drawer: view / import / export / load-from-monitor ── */
export function JsonView({db, onApply, onLoadMonitor, busy, note}){
  const [draft,setDraft]=useState(JSON.stringify(db,null,2));
  const [err,setErr]=useState('');
  useEffect(()=>{ setDraft(JSON.stringify(db,null,2)); },[db]);
  let valid=true; try{ JSON.parse(draft); }catch(e){ valid=false; }
  function apply(){ let obj; try{ obj=JSON.parse(draft); }catch(e){ setErr('That is not valid JSON.'); return; }
    const r=validateDb(obj); if(!r.ok){ setErr(r.err); return; } setErr(''); onApply(r.db); }
  function download(){ const b=new Blob([JSON.stringify(db,null,2)],{type:'application/json'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download='tables.json'; a.click(); URL.revokeObjectURL(a.href); }
  function importFile(e){ const f=e.target.files[0]; if(!f) return; const rd=new FileReader();
    rd.onload=()=>{ setDraft(String(rd.result)); }; rd.readAsText(f); e.target.value=''; }
  return html`<div class="glass-card" style="padding:16px">
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
      <span style="width:9px;height:9px;border-radius:50%;background:${valid?'var(--ink-green-2)':'var(--ink-red-3)'}"></span>
      <span style="font-size:12px;color:var(--ink-gray-5)">${valid?'valid JSON':'invalid JSON'}</span>
      <span style="flex:1"></span>
      <button class="pill pill-gray" style="cursor:pointer;border:1px solid var(--outline-gray-2)" onClick=${()=>navigator.clipboard&&navigator.clipboard.writeText(JSON.stringify(db,null,2))}><${Icon} name="copy" size=12/> Copy</button>
      <button class="pill pill-gray" style="cursor:pointer;border:1px solid var(--outline-gray-2)" onClick=${download}><${Icon} name="download" size=12/> Download</button>
      <label class="pill pill-gray" style="cursor:pointer;border:1px solid var(--outline-gray-2)"><${Icon} name="upload" size=12/> Import<input type="file" accept=".json" onChange=${importFile} style="display:none"/></label>
      <button class="pill pill-gray" style="cursor:pointer;border:1px solid var(--outline-gray-2)" disabled=${busy} onClick=${onLoadMonitor}><${Icon} name=${busy?'loader':'binoculars'} size=12 cls=${busy?'spin':''}/> Load from monitor</button>
      <button class="pill pill-blue" style="cursor:pointer;border:none" onClick=${apply}><${Icon} name="check" size=12/> Apply</button>
    </div>
    ${err && html`<div class="errbox" style="margin-bottom:8px">${err}</div>`}
    ${note && html`<div style="font-size:12px;color:var(--ink-green-2);margin-bottom:8px"><${Icon} name="check" size=12/> ${note}</div>`}
    <textarea class="input" spellcheck="false" value=${draft} onInput=${e=>{setDraft(e.target.value);setErr('');}}
      style="width:100%;min-height:50vh;font-family:ui-monospace,'IBM Plex Mono',monospace;font-size:12px"></textarea>
  </div>`;
}


/* ── the Tables tab ── */
export function TablesTool(){
  /* boot flags: did stored data exist but fail to load (corrupt), and should the
     first persist be skipped so we do NOT overwrite that recoverable data */
  const bootRef = useRef({corrupt:false, skip:false});
  const [db,setDb]=useState(()=>{
    try{ const s=localStorage.getItem(TBL_KEY);
      if(s){ const r=validateDb(JSON.parse(s));
        if(r.ok && (r.db.cols||[]).length>0) return r.db;   // a 0-column table is unrenderable (looks blank)
        // Corrupt bytes: protect them (skip the first overwrite) so the JSON view can recover.
        // Valid-but-columnless: fall through to SAMPLE and let it persist over the dead table.
        if(!r.ok){ bootRef.current.corrupt=true; bootRef.current.skip=true; }
      }
    }catch(e){ try{ if(localStorage.getItem(TBL_KEY)){ bootRef.current.corrupt=true; bootRef.current.skip=true; } }catch(_){} }
    return SAMPLE;
  });
  const [view,setView]=useState(()=>{ try{ const v=localStorage.getItem(TBL_VIEW_KEY);
    return ['table','list','board','json'].includes(v)?v:'table'; }catch(e){ return 'table'; } });
  const [rowEd,setRowEd]=useState(null);            // row _id open in the detail editor
  const [groupBy,setGroupBy]=useState('');
  const [sortBy,setSortBy]=useState(''); const [sortDir,setSortDir]=useState('asc');
  const [globalQ,setGlobalQ]=useState('');
  const [colFilters,setColFilters]=useState({});
  const [collapsed,setCollapsed]=useState(new Set());
  const [editing,setEditing]=useState(null);
  const [showCols,setShowCols]=useState(false);
  const [menuKey,setMenuKey]=useState(null);
  const [colMenu,setColMenu]=useState(null);        // which header dropdown is open
  const [groupMenu,setGroupMenu]=useState(false);   // group-by dropdown
  const [viewMenu,setViewMenu]=useState(false);     // "Grid view" dropdown
  const [filterMenu,setFilterMenu]=useState(false); // toolbar Filter popover (active-filter summary)
  const [sortMenu,setSortMenu]=useState(false);     // toolbar Sort menu
  const [dropRow,setDropRow]=useState(null);        // row id under a row drag
  const [dropCol,setDropCol]=useState(null);        // col key under a column drag
  const dragRef=useRef({col:null, row:null});       // dragged id, stashed here not in dataTransfer (getData is read-protected)
  const resizeRef=useRef(false);                    // true while resizing a column (suppresses the header drag)
  const [fieldEd,setFieldEd]=useState(null);        // {mode:'new'} | {mode:'edit', key}
  const [editingName,setEditingName]=useState(false);
  const [busy,setBusy]=useState(false); const [note,setNote]=useState('');

  /* persist, but skip the first write when boot data was corrupt (so we leave the
     recoverable bytes on disk); surface a quota/save failure instead of dropping it silently */
  useEffect(()=>{ if(bootRef.current.skip){ bootRef.current.skip=false; return; }
    try{ localStorage.setItem(TBL_KEY, JSON.stringify(db)); }
    catch(e){ setNote('Could not save to browser storage (it may be full). Export your JSON so you do not lose changes.'); } },[db]);
  /* on mount, tell the user if their saved table could not be read */
  useEffect(()=>{ if(bootRef.current.corrupt)
    setNote('Your saved table could not be read, so the sample is shown. Your old data is still in storage; export or overwrite when you are ready.'); },[]);
  /* persist the chosen view so a reload keeps you on Table / List / Board / JSON */
  useEffect(()=>{ try{ localStorage.setItem(TBL_VIEW_KEY, view); }catch(e){} },[view]);
  /* Board stacks by a select field. On entering Board, if the current group is not
     a select, auto-pick the first select column so lanes make sense; on LEAVING
     board, restore whatever grouping Table/List had, so a board-only stack choice
     does not leak into the other views. */
  const preBoardGroup = useRef('');
  useEffect(()=>{ if(view!=='board') return;
    preBoardGroup.current = groupBy;
    const gc=db.cols.find(c=>c.key===groupBy);
    if(!gc || (gc.type!=='select' && gc.type!=='multi_select')){
      const first=db.cols.find(c=>c.type==='select'||c.type==='multi_select');
      setGroupBy(first?first.key:''); }
    return ()=>{ setGroupBy(preBoardGroup.current); };
  },[view]);
  /* one outside-click handler closes every open popover (filter, header menu, columns) */
  const [loadMenu,setLoadMenu]=useState(false);     // "Load data" dropdown
  const [actionMenu,setActionMenu]=useState(false); // "Action" dropdown (export / dedupe)
  const [actMode,setActMode]=useState('root');      // action menu pane: root | dedupe
  const [colQ,setColQ]=useState('');                // search box inside the columns/sort menus
  const [sortDraft,setSortDraft]=useState({key:'',dir:'asc'});          // sort builder
  const [fDraft,setFDraft]=useState({key:'',op:'contains',v:'',v2:''}); // filter builder
  useEffect(()=>{ const h=()=>{ setMenuKey(null); setColMenu(null); setShowCols(false); setGroupMenu(false); setViewMenu(false); setFilterMenu(false); setSortMenu(false); setLoadMenu(false); setActionMenu(false); };
    document.addEventListener('mousedown',h); return ()=>document.removeEventListener('mousedown',h); },[]);
  /* Toolbar dropdowns are mutually exclusive: opening one closes every other
     popover (and toggles the clicked one shut if it was already open). */
  const toggleBar=(key)=>{
    const cur={view:viewMenu, cols:showCols, filter:filterMenu, group:groupMenu, sort:sortMenu, load:loadMenu, action:actionMenu}[key];
    setMenuKey(null); setColMenu(null);
    setViewMenu(key==='view' && !cur); setShowCols(key==='cols' && !cur);
    setFilterMenu(key==='filter' && !cur); setGroupMenu(key==='group' && !cur);
    setSortMenu(key==='sort' && !cur); setLoadMenu(key==='load' && !cur);
    setActionMenu(key==='action' && !cur);
    if(key==='cols'||key==='sort') setColQ('');
    if(key==='sort' && !cur) setSortDraft({key:sortBy||'', dir:sortDir||'asc'});
    if(key==='action' && !cur) setActMode('root');
  };
  /* if a grouped/sorted column is deleted, drop the stale reference */
  useEffect(()=>{ const keys=new Set(db.cols.map(c=>c.key));
    if(groupBy && !keys.has(groupBy)) setGroupBy('');
    if(sortBy && !keys.has(sortBy)) setSortBy('');
  },[db.cols]);

  /* ── row selection (the column-A checkboxes) ── */
  const [selRows,setSelRows]=useState(new Set());
  const toggleSel=id=> setSelRows(s=>{ const n=new Set(s); n.has(id)?n.delete(id):n.add(id); return n; });
  /* prune selections whose row no longer exists (delete, JSON replace) */
  useEffect(()=>{ setSelRows(s=>{ const ids=new Set(db.rows.map(r=>r._id));
    const n=new Set([...s].filter(id=>ids.has(id))); return n.size===s.size?s:n; }); },[db.rows]);
  const deleteSelected=()=>{ setDb(d=>({...d, rows:d.rows.filter(r=>!selRows.has(r._id))})); setSelRows(new Set()); };

  const visibleCols = useMemo(()=> db.cols.filter(c=>!c.hidden), [db.cols]);

  const filteredRows = useMemo(()=>{
    const q=globalQ.trim().toLowerCase();
    return db.rows.filter(row=>{
      if(q && !visibleCols.some(c=>cellText(row[c.key],c).toLowerCase().includes(q))) return false;
      for(const c of visibleCols){ const f=colFilters[c.key];
        if(filterActive(f,c) && !TYPE_META[c.type].matches(row[c.key],f,c)) return false; }
      return true;
    });
  },[db.rows, db.cols, globalQ, colFilters, visibleCols]);

  const sortedRows = useMemo(()=>{
    if(!sortBy) return filteredRows;
    const col=db.cols.find(c=>c.key===sortBy); if(!col) return filteredRows;
    const cmp=TYPE_META[col.type].compare;
    const arr=filteredRows.map((r,i)=>[r,i]);
    arr.sort((A,B)=>{
      const a=A[0][sortBy], b=B[0][sortBy], ea=_isEmpty(a), eb=_isEmpty(b);
      if(ea&&eb) return A[1]-B[1];
      if(ea) return 1; if(eb) return -1;          // empties always last, both dirs
      let d=cmp(a,b,col); if(d===0) return A[1]-B[1];
      return sortDir==='desc'?-d:d;
    });
    return arr.map(x=>x[0]);
  },[filteredRows, db.cols, sortBy, sortDir]);

  const groups = useMemo(()=>{
    if(!groupBy) return [{id:'__all__', label:'', rows:sortedRows, count:sortedRows.length}];
    const col=db.cols.find(c=>c.key===groupBy); if(!col) return [{id:'__all__',label:'',rows:sortedRows,count:sortedRows.length}];
    const buckets=new Map();
    for(const row of sortedRows){ const v=row[groupBy]; let keys;
      if(col.type==='multi_select') keys=(Array.isArray(v)&&v.length)?v:['__empty__'];
      else keys=[_isEmpty(v)?'__empty__':String(v)];
      for(const k of keys){ if(!buckets.has(k)) buckets.set(k,[]); buckets.get(k).push(row); } }
    let arr=[...buckets.entries()].map(([k,rows])=>{ const isEmpty=k==='__empty__';
      const label=isEmpty?'(No value)':((col.type==='select'||col.type==='multi_select')?(optOf(col,k)?.label||k):k);
      const g={id:k, key:k, isEmpty, label, rows, count:rows.length};
      if(col.type==='number'&&!isEmpty){ const nums=rows.map(r=>r[groupBy]).filter(n=>typeof n==='number'); g.sum=nums.reduce((a,b)=>a+b,0); g.avg=nums.length?g.sum/nums.length:0; }
      return g; });
    // Group keys are single option ids (multi_select is fanned out one bucket per
    // tag above), so order multi_select groups with the select comparator, which
    // ranks by the column's option order; multi_select.compare ranks by array
    // length and would leave every group at 0 (insertion order).
    const gcmp = TYPE_META[col.type==='multi_select'?'select':col.type].compare;
    arr.sort((A,B)=> A.isEmpty?1:B.isEmpty?-1:gcmp(A.key,B.key,col));
    return arr;
  },[sortedRows, db.cols, groupBy]);

  const filteredCount = useMemo(()=> new Set(groups.flatMap(g=>g.rows.map(r=>r._id))).size, [groups]);
  const groupByCol = db.cols.find(c=>c.key===groupBy) || null;
  /* count only live, visible columns so an orphan/hidden filter never inflates "Clear N" */
  const activeFilters = visibleCols.reduce((n,c)=>n + (filterActive(colFilters[c.key],c)?1:0), 0) + (globalQ.trim()?1:0);

  function onSort(key){ if(sortBy!==key){ setSortBy(key); setSortDir('asc'); }
    else if(sortDir==='asc') setSortDir('desc'); else { setSortBy(''); setSortDir('asc'); } }
  const onSortDir=(key,dir)=>{ setSortBy(key); setSortDir(dir); };
  const setColFilter=(key,val)=> setColFilters(o=>({...o,[key]:val}));
  const toggleCollapse=id=> setCollapsed(s=>{ const n=new Set(s); n.has(id)?n.delete(id):n.add(id); return n; });

  /* ── row CRUD ── */
  const setCellValue=(rowId,key,val)=> setDb(o=>({...o, rows:o.rows.map(r=>r._id===rowId?{...r,[key]:val}:r)}));
  const addRow=(presets={})=> setDb(o=>{ const r={_id:newId()}; o.cols.forEach(c=>r[c.key]=emptyValueFor(c));
    Object.assign(r, presets); return {...o, rows:[...o.rows, r]}; });
  const deleteRow=id=> setDb(o=>({...o, rows:o.rows.filter(r=>r._id!==id)}));
  const duplicateRow=id=> setDb(o=>{ const i=o.rows.findIndex(r=>r._id===id); if(i<0) return o;
    const copy={...o.rows[i], _id:newId()}; const rows=[...o.rows]; rows.splice(i+1,0,copy); return {...o, rows}; });
  /* drag reorder: moving forward drops AFTER the target, backward drops BEFORE,
     so the row lands where the indicator shows */
  const moveRow=(srcId,dstId)=> setDb(o=>{ const rows=[...o.rows];
    const si=rows.findIndex(r=>r._id===srcId), di=rows.findIndex(r=>r._id===dstId);
    if(si<0||di<0||si===di) return o;
    const [r]=rows.splice(si,1); const ni=rows.findIndex(x=>x._id===dstId);
    rows.splice(si<di?ni+1:ni,0,r); return {...o, rows}; });
  /* a row dragged into another group adopts that group's value (select only;
     multi_select fan-out makes adoption ambiguous, so it just reorders) */
  const onDropRow=(srcId,target)=>{ if(!srcId || srcId===target._id) return;
    if(groupBy){ const gc=db.cols.find(c=>c.key===groupBy);
      if(gc && gc.type==='select'){ const src=db.rows.find(r=>r._id===srcId);
        if(src && src[groupBy]!==target[groupBy]) setCellValue(srcId, groupBy, target[groupBy]); } }
    moveRow(srcId, target._id); };

  /* ── column CRUD ── */
  const toggleHidden=key=> setDb(o=>({...o, cols:o.cols.map(c=>c.key===key?{...c,hidden:!c.hidden}:c)}));
  const addColumn=def=> setDb(o=>{ const col={hidden:false, width:160, ...def, key:uniqueKey(def.key||def.label, o.cols)};
    return {...o, cols:[...o.cols, col], rows:o.rows.map(r=>({...r,[col.key]:emptyValueFor(col)}))}; });
  const updateColumn=(key,def)=> setDb(o=>{ const old=o.cols.find(c=>c.key===key); if(!old) return o;
    const nc={...old, ...def}; const cols=o.cols.map(c=>c.key===key?nc:c);
    let rows=o.rows;
    if(def.type && def.type!==old.type) rows=o.rows.map(r=>({...r,[key]:coerceValue(r[key], def.type)}));
    return {...o, cols, rows}; });
  const deleteColumn=key=>{ setDb(o=>({...o, cols:o.cols.filter(c=>c.key!==key),
    rows:o.rows.map(r=>{ const nr={...r}; delete nr[key]; return nr; })}));
    setColFilters(o=>{ if(!(key in o)) return o; const n={...o}; delete n[key]; return n; }); };
  const moveColumn=(srcKey,dstKey)=> setDb(o=>{ const cols=[...o.cols];
    const si=cols.findIndex(c=>c.key===srcKey), di=cols.findIndex(c=>c.key===dstKey);
    if(si<0||di<0||si===di) return o;
    const [c]=cols.splice(si,1); const ni=cols.findIndex(x=>x.key===dstKey);
    cols.splice(si<di?ni+1:ni,0,c); return {...o, cols}; });
  const setColWidth=(key,w)=> setDb(o=>({...o, cols:o.cols.map(c=>c.key===key?{...c,width:Math.max(80,Math.round(w))}:c)}));
  const renameTable=name=> setDb(o=>({...o, name:name||'Table'}));
  /* Save a field edit AND keep colFilters honest: a type change makes the old
     filter shape meaningless (drop it); an options change can leave orphan ids in
     a chip filter (prune to surviving ids). Done here because colFilters is
     separate state the setDb reducer cannot reach. */
  function saveField(def){
    if(fieldEd?.mode==='edit'){
      const key=fieldEd.key, old=db.cols.find(c=>c.key===key);
      updateColumn(key, def);
      if(old){
        if(def.type && def.type!==old.type){
          setColFilters(o=>{ if(!(key in o)) return o; const n={...o}; delete n[key]; return n; });
        } else if(def.options){
          const ids=new Set(def.options.map(o=>o.id));
          setColFilters(o=>{ const f=o[key]; if(!Array.isArray(f)) return o;
            const pruned=f.filter(id=>ids.has(id)); return {...o, [key]:pruned}; });
        }
      }
    } else addColumn(def);
    setFieldEd(null);
  }

  const clearFilters=()=>{ setGlobalQ(''); setColFilters({}); };

  function resetSample(){
    setLoadMenu(false);
    if(!window.confirm('Replace the current table with the sample GTM pipeline? This overwrites your saved data.')) return;
    const r=validateDb(JSON.parse(JSON.stringify(SAMPLE)));
    if(r.ok){ setDb(r.db); setGroupBy(''); setSortBy(''); clearFilters(); setSelRows(new Set()); setNote('Sample pipeline loaded.'); }
  }
  async function loadMonitor(){
    setBusy(true); setNote('');
    try{
      const j=await fetch(`${API_BASE}/api/monitor`).then(r=>r.json());
      const groups=j.mentions||{}; const first=Object.keys(groups)[0];
      const ms=first?groups[first]:[];
      const platforms=[...new Set(ms.map(m=>m.platform).filter(Boolean))];
      const cols=[
        {key:'platform',label:'Platform',type:'select',hidden:false,width:120,options:platforms.map(p=>({id:p,label:p,color:'gray'}))},
        {key:'kind',label:'Kind',type:'text',hidden:false,width:90},
        {key:'sentiment',label:'Sentiment',type:'select',hidden:false,width:110,options:[
          {id:'positive',label:'positive',color:'green'},{id:'negative',label:'negative',color:'red'},{id:'neutral',label:'neutral',color:'gray'}]},
        {key:'brand',label:'Brand',type:'text',hidden:false,width:110},
        {key:'company',label:'Company',type:'text',hidden:false,width:130},
        {key:'body',label:'Text',type:'longtext',hidden:false,width:320},
        {key:'author',label:'Author',type:'text',hidden:false,width:120},
        {key:'post_ts',label:'Posted',type:'date',hidden:false,width:130},
        {key:'url',label:'Link',type:'url',hidden:false,width:120},
      ];
      const rows=ms.map(m=>({_id:newId(), platform:m.platform||'', kind:m.kind||'', sentiment:m.sentiment||'',
        brand:m.brand||'', company:m.company||'', body:(m.body||m.text||''), author:m.author||'',
        post_ts:(m.post_ts||m.ts||'').slice(0,10), url:m.url||''}));
      if(!rows.length){ setNote('No mentions in the store yet. Run the monitor first.'); }
      else { setDb({name:'Monitor mentions', cols, rows}); setGroupBy(''); setSortBy(''); clearFilters();
        setNote(`Loaded ${rows.length} mentions.`); }
    }catch(e){ setNote('Could not reach the monitor. Is the backend running?'); }
    setBusy(false);
  }

  /* select-all covers the FILTERED rows (what the user can see) */
  const allSel = filteredRows.length>0 && filteredRows.every(r=>selRows.has(r._id));
  const toggleAllSel = ()=> setSelRows(allSel ? new Set() : new Set(filteredRows.map(r=>r._id)));
  const headProps={visibleCols, sortBy, sortDir, onSort, onSortDir, colFilters, setColFilter,
    menuKey, setMenuKey, colMenu, setColMenu, editing, setEditing, setCellValue,
    onEditCol:key=>setFieldEd({mode:'edit', key}), onHideCol:toggleHidden, onDeleteCol:deleteColumn,
    onAddColumn:()=>setFieldEd({mode:'new'}), onDeleteRow:deleteRow, onDuplicateRow:duplicateRow, onAddRow:addRow,
    onMoveCol:moveColumn, dropCol, setDropCol, dropRow, setDropRow, onDropRow, canDragRows: !sortBy,
    dragRef, resizeRef, onResizeCol:setColWidth, selRows, toggleSel, allSel, toggleAllSel};
  const editingCol = fieldEd?.mode==='edit' ? db.cols.find(c=>c.key===fieldEd.key) : null;
  const onEditRow = id => setRowEd(id);
  const rowEdRow = rowEd ? db.rows.find(r=>r._id===rowEd) : null;
  /* the field the board stacks by: the current group when it is a select */
  const boardCol = (groupByCol && (groupByCol.type==='select'||groupByCol.type==='multi_select')) ? groupByCol : null;
  const groupChoices = view==='board' ? visibleCols.filter(c=>c.type==='select'||c.type==='multi_select') : visibleCols;

  const VIEWS = [['table','Table','sheet'],['list','List','rows'],['board','Board','kanban'],['json','JSON','code']];
  /* ── toolbar actions: filter builder apply, exports, dedupe ── */
  function applyDraftFilter(){
    const c=db.cols.find(x=>x.key===fDraft.key); if(!c) return;
    let val;
    if(c.type==='number') val = fDraft.op==='gt' ? '>'+fDraft.v : fDraft.op==='lt' ? '<'+fDraft.v
      : fDraft.op==='between' ? fDraft.v+'-'+fDraft.v2 : fDraft.v;
    else if(c.type==='select'||c.type==='multi_select') val = fDraft.v ? [fDraft.v] : [];
    else if(c.type==='date') val = {from:fDraft.v, to:fDraft.v2};
    else val = fDraft.v;
    setColFilter(fDraft.key, val);
    setFDraft(d=>({...d, v:'', v2:''}));   // menu stays open so filters can stack
  }
  function download(name, text, type){
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([text],{type})); a.download=name;
    document.body.appendChild(a); a.click(); a.remove();
  }
  function exportCSV(){
    const esc=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
    const head=visibleCols.map(c=>esc(c.label)).join(',');
    const body=sortedRows.map(r=>visibleCols.map(c=>esc(cellText(r[c.key],c))).join(',')).join('\n');
    download((db.name||'table')+'.csv', head+'\n'+body, 'text/csv');
    setActionMenu(false);
  }
  function exportJSON(){
    const rows=db.rows.map(({_id, ...rest})=>rest);
    download((db.name||'table')+'.json', JSON.stringify({name:db.name, cols:db.cols, rows}, null, 2), 'application/json');
    setActionMenu(false);
  }
  function dedupeBy(key){
    const col=db.cols.find(c=>c.key===key); if(!col) return;
    const seen=new Set(); let removed=0;
    const rows=db.rows.filter(r=>{ const k=cellText(r[key],col).trim().toLowerCase();
      if(k==='') return true;
      if(seen.has(k)){ removed++; return false; }
      seen.add(k); return true; });
    setDb(d=>({...d, rows}));
    setNote(removed ? `Removed ${removed} duplicate row${removed===1?'':'s'} by ${col.label}.` : `No duplicates found in ${col.label}.`);
    setActionMenu(false);
  }

  const countStr = (activeFilters>0 ? `${filteredCount} of ${db.rows.length} rows` : `${db.rows.length} ${db.rows.length===1?'row':'rows'}`)
    + ` · ${visibleCols.length} of ${db.cols.length} columns`;

  const curView = VIEWS.find(v=>v[0]===view) || VIEWS[0];
  return html`<div class="tbl-shell">
    <div class="tbl-mainpane">
    <div class="tbl-bar">
      <div style="position:relative">
        <button type="button" class="tbar-btn on" aria-haspopup="menu" aria-expanded=${viewMenu}
          onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('view')}>
          <${Icon} name=${curView[2]} size=14/> ${curView[1]} <${Icon} name="caretDown" size=12/></button>
        ${viewMenu && html`<div class="tbl-menu" role="menu" aria-label="Views" style="left:0;min-width:170px" onMouseDown=${e=>e.stopPropagation()}>
          ${VIEWS.map(([id,label,icon])=>html`<button key=${id} type="button" class="tbl-mi" role="menuitemradio" aria-checked=${view===id} onClick=${()=>{setView(id);setViewMenu(false);}}>
            <${Icon} name=${icon} size=14/> ${label} ${view===id?html`<span class="mi-end"><${Icon} name="check" size=13/></span>`:''}</button>`)}
        </div>`}
      </div>
      <div style="position:relative">
        <button type="button" class="tbar-btn" aria-haspopup="menu" aria-expanded=${loadMenu}
          onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('load')}>
          <${Icon} name="upload" size=15/> Load data <${Icon} name="caretDown" size=12/></button>
        ${loadMenu && html`<div class="tbl-menu" role="menu" aria-label="Load data" style="left:0;min-width:210px" onMouseDown=${e=>e.stopPropagation()}>
          <button type="button" class="tbl-mi" onClick=${()=>{setLoadMenu(false); loadMonitor();}}><${Icon} name="binoculars" size=13/> Monitor mentions</button>
          <button type="button" class="tbl-mi" onClick=${()=>{setLoadMenu(false); setView('json');}}><${Icon} name="code" size=13/> Paste JSON</button>
          <div class="tbl-mi-sep"></div>
          <button type="button" class="tbl-mi" onClick=${resetSample}><${Icon} name="refresh" size=13/> Reset to sample</button>
        </div>`}
      </div>
      ${view!=='json' && html`<span class="tbar-chip"><${Icon} name="rows" size=15/> ${db.rows.length} Rows</span>`}
      ${selRows.size>0 && html`
        <span class="pill pill-blue">${selRows.size} selected</span>
        <button type="button" class="tbar-btn" style="color:var(--ink-red-3)" onClick=${deleteSelected}><${Icon} name="trash" size=13/> Delete</button>
        <button type="button" class="tbar-btn" onClick=${()=>setSelRows(new Set())}>Clear</button>`}
      ${view!=='json' && html`
        <div style="position:relative">
          <button type="button" class=${'tbar-btn'+(visibleCols.length<db.cols.length?' on':'')} aria-expanded=${showCols}
            onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('cols')}><${Icon} name="eye" size=15/> ${visibleCols.length}/${db.cols.length} Columns</button>
          ${showCols && html`<div class="tbl-menu" role="group" aria-label="Show or hide columns" style="left:0;right:auto;min-width:250px" onMouseDown=${e=>e.stopPropagation()} onClick=${e=>e.stopPropagation()}>
            <input class="search-mini" placeholder="Search columns..." value=${colQ} onInput=${e=>setColQ(e.target.value)}/>
            <button type="button" class="tbl-mi" style="margin-top:4px" onClick=${()=>{setShowCols(false); setFieldEd({mode:'new'});}}>
              <${Icon} name="plus" size=13/> Create new column</button>
            <div class="tbl-mi-sep"></div>
            ${db.cols.filter(c=>!colQ.trim()||c.label.toLowerCase().includes(colQ.trim().toLowerCase())).map(c=>html`
              <div key=${c.key} style="display:flex;align-items:center;gap:8px;padding:4px 8px">
                <button type="button" class=${'tswitch'+(c.hidden?'':' on')} role="switch" aria-checked=${!c.hidden}
                  aria-label=${'Show '+c.label} onClick=${()=>toggleHidden(c.key)}></button>
                <${Icon} name=${TYPE_META[c.type].icon} size=13/> <span style="font-size:13px">${c.label}</span>
              </div>`)}
          </div>`}
        </div>
        <div style="position:relative">
          <button type="button" class=${'tbar-btn'+(activeFilters>0?' on':'')} aria-expanded=${filterMenu}
            onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('filter')}><${Icon} name="funnel" size=15/> Filter${activeFilters>0?' ('+activeFilters+')':''}</button>
          ${filterMenu && html`<div class="tbl-menu" role="group" aria-label="Filters" style="left:0;right:auto;min-width:320px;padding:8px" onMouseDown=${e=>e.stopPropagation()} onClick=${e=>e.stopPropagation()}>
            <div class="pk-lbl">When</div>
            <div style="display:flex;gap:8px;margin-bottom:8px">
              <select class="input" style="height:32px;padding:0 24px 0 8px;font-size:12px;flex:1" value=${fDraft.key}
                onChange=${e=>{ const c=db.cols.find(x=>x.key===e.target.value); const t=c?c.type:'text';
                  const op=t==='number'?'gt':(t==='select'||t==='multi_select'||t==='checkbox')?'is':t==='date'?'between':'contains';
                  setFDraft({key:e.target.value, op, v:'', v2:''}); }}>
                <option value="">Select a column</option>
                ${visibleCols.map(c=>html`<option key=${c.key} value=${c.key}>${c.label}</option>`)}
              </select>
              ${(()=>{ const c=db.cols.find(x=>x.key===fDraft.key); const t=c?c.type:null;
                const OPS = t==='number'?[['gt','Greater than'],['lt','Less than'],['eq','Equal to'],['between','Between']]
                  : (t==='select'||t==='multi_select'||t==='checkbox')?[['is','Is']]
                  : t==='date'?[['between','Between']] : [['contains','Contains']];
                return html`<select class="input" style="height:32px;padding:0 24px 0 8px;font-size:12px;width:130px" value=${fDraft.op}
                  disabled=${!t} onChange=${e=>setFDraft(d=>({...d,op:e.target.value}))}>
                  ${OPS.map(([id,label])=>html`<option key=${id} value=${id}>${label}</option>`)}
                </select>`; })()}
            </div>
            ${(()=>{ const c=db.cols.find(x=>x.key===fDraft.key); if(!c) return '';
              const set=(k)=>e=>setFDraft(d=>({...d,[k]:e.target.value}));
              if(c.type==='select'||c.type==='multi_select') return html`<select class="input" style="height:32px;padding:0 24px 0 8px;font-size:12px;width:100%;margin-bottom:8px" value=${fDraft.v} onChange=${set('v')}>
                <option value="">Pick an option</option>${(c.options||[]).map(o=>html`<option key=${o.id} value=${o.id}>${o.label}</option>`)}</select>`;
              if(c.type==='checkbox') return html`<select class="input" style="height:32px;padding:0 24px 0 8px;font-size:12px;width:100%;margin-bottom:8px" value=${fDraft.v} onChange=${set('v')}>
                <option value="">Pick a value</option><option value="true">Checked</option><option value="false">Unchecked</option></select>`;
              if(c.type==='date') return html`<div style="display:flex;gap:8px;margin-bottom:8px">
                <input type="date" class="pk-date" aria-label="From" value=${fDraft.v} onInput=${set('v')}/>
                <input type="date" class="pk-date" aria-label="To" value=${fDraft.v2} onInput=${set('v2')}/></div>`;
              if(c.type==='number') return html`<div style="display:flex;gap:8px;margin-bottom:8px">
                <input type="number" class="search-mini" placeholder=${fDraft.op==='between'?'From':'Value'} value=${fDraft.v} onInput=${set('v')}/>
                ${fDraft.op==='between'?html`<input type="number" class="search-mini" placeholder="To" value=${fDraft.v2} onInput=${set('v2')}/>`:''}</div>`;
              return html`<input class="search-mini" style="margin-bottom:8px" placeholder="Enter filter value" value=${fDraft.v} onInput=${set('v')}/>`; })()}
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px">
              <span style="flex:1"></span>
              ${activeFilters>0 && html`<button type="button" class="tbar-btn" style="color:var(--ink-red-3)" onClick=${()=>{clearFilters();}}><${Icon} name="trash" size=13/> Clear filters</button>`}
              <button type="button" class="btn btn-primary btn-sm" disabled=${!fDraft.key} onClick=${applyDraftFilter}>Apply filter</button>
            </div>
            ${activeFilters>0 && html`<div class="tbl-mi-sep"></div>
              ${visibleCols.filter(c=>filterActive(colFilters[c.key],c)).map(c=>{ const f=colFilters[c.key]; const val=filterLabel(f,c);
                return html`<div key=${c.key} class="tbl-mi" style="cursor:default">
                  <${Icon} name=${TYPE_META[c.type].icon} size=13/> <b>${c.label}</b> <span style="color:var(--ink-gray-6)">${val}</span>
                  <button type="button" class="iconbtn" style="margin-left:auto" aria-label="Clear" onClick=${()=>setColFilter(c.key, Array.isArray(f)?[]:'')}><${Icon} name="close" size=13/></button></div>`; })}`}
          </div>`}
        </div>
        <div style="position:relative">
          <button type="button" class=${'tbar-btn'+(groupBy?' on':'')} aria-expanded=${groupMenu}
            onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('group')}>
            <${Icon} name=${view==='board'?'kanban':'list'} size=15/> ${view==='board'?'Stack':'Group'}${groupBy?': '+(visibleCols.find(c=>c.key===groupBy)?.label||''):''}</button>
          ${groupMenu && html`<div class="tbl-menu" role="menu" aria-label="Group by" style="left:0;right:auto;min-width:170px" onMouseDown=${e=>e.stopPropagation()}>
            ${view!=='board' ? html`<button type="button" class="tbl-mi" role="menuitemradio" aria-checked=${!groupBy} onClick=${()=>{setGroupBy('');setGroupMenu(false);}}>None ${!groupBy?html`<span class="mi-end"><${Icon} name="check" size=13/></span>`:''}</button>` : ''}
            ${groupChoices.map(c=>html`<button type="button" key=${c.key} class="tbl-mi" role="menuitemradio" aria-checked=${groupBy===c.key} onClick=${()=>{setGroupBy(c.key);setGroupMenu(false);}}>
              <${Icon} name=${TYPE_META[c.type].icon} size=13/> ${c.label} ${groupBy===c.key?html`<span class="mi-end"><${Icon} name="check" size=13/></span>`:''}</button>`)}
            ${view==='board' && groupChoices.length===0 ? html`<div style="padding:8px 8px;font-size:12px;color:var(--ink-gray-5)">Add a Select field first.</div>` : ''}
          </div>`}
        </div>
        ${view!=='board' && html`<div style="position:relative">
          <button type="button" class=${'tbar-btn'+(sortBy?' on':'')} aria-expanded=${sortMenu}
            onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('sort')}>
            <${Icon} name="rows" size=15/> Sort${sortBy?': '+(visibleCols.find(c=>c.key===sortBy)?.label||''):''}</button>
          ${sortMenu && html`<div class="tbl-menu" role="group" aria-label="Sort by" style="left:0;right:auto;min-width:280px;padding:8px" onMouseDown=${e=>e.stopPropagation()} onClick=${e=>e.stopPropagation()}>
            <input class="search-mini" placeholder="Search columns..." value=${colQ} onInput=${e=>setColQ(e.target.value)}/>
            <div style="max-height:190px;overflow:auto;margin-top:4px">
              ${visibleCols.filter(c=>!colQ.trim()||c.label.toLowerCase().includes(colQ.trim().toLowerCase())).map(c=>html`
                <button type="button" key=${c.key} class="tbl-mi" role="menuitemradio" aria-checked=${sortDraft.key===c.key}
                  onClick=${()=>setSortDraft(d=>({...d,key:c.key}))}>
                  <${Icon} name=${TYPE_META[c.type].icon} size=13/> ${c.label}
                  ${sortDraft.key===c.key?html`<span class="mi-end"><${Icon} name="check" size=13/></span>`:''}</button>`)}
            </div>
            <div class="tbl-mi-sep"></div>
            <div style="display:flex;gap:8px;align-items:center">
              <div class="seg">
                <button type="button" class=${sortDraft.dir==='asc'?'on':''} onClick=${()=>setSortDraft(d=>({...d,dir:'asc'}))}>Ascending</button>
                <button type="button" class=${sortDraft.dir==='desc'?'on':''} onClick=${()=>setSortDraft(d=>({...d,dir:'desc'}))}>Descending</button>
              </div>
              <span style="flex:1"></span>
              ${sortBy && html`<button type="button" class="tbar-btn" onClick=${()=>{setSortBy('');setSortMenu(false);}}>Clear</button>`}
              <button type="button" class="btn btn-primary btn-sm" disabled=${!sortDraft.key}
                onClick=${()=>{onSortDir(sortDraft.key, sortDraft.dir); setSortMenu(false);}}>Apply</button>
            </div>
          </div>`}
        </div>`}
        <span style="flex:1"></span>
        <div style="position:relative">
          <button type="button" class="tbar-btn" aria-haspopup="menu" aria-expanded=${actionMenu}
            onMouseDown=${e=>e.stopPropagation()} onClick=${()=>toggleBar('action')}>
            <${Icon} name="zap" size=15/> Action <${Icon} name="caretDown" size=12/></button>
          ${actionMenu && html`<div class="tbl-menu" role="menu" aria-label="Actions" style="left:auto;right:0;min-width:230px" onMouseDown=${e=>e.stopPropagation()}>
            ${actMode==='root' ? html`
              <button type="button" class="tbl-mi" onClick=${exportCSV}><${Icon} name="download" size=13/> Export view as CSV</button>
              <button type="button" class="tbl-mi" onClick=${exportJSON}><${Icon} name="code" size=13/> Export table as JSON</button>
              <div class="tbl-mi-sep"></div>
              <button type="button" class="tbl-mi" onClick=${e=>{e.stopPropagation(); setActMode('dedupe');}}>
                <${Icon} name="copy" size=13/> Dedupe by column <span class="mi-end"><${Icon} name="caretRight" size=13/></span></button>`
            : html`
              <button type="button" class="tbl-mi" onClick=${e=>{e.stopPropagation(); setActMode('root');}}><${Icon} name="arrowLeft" size=13/> Back</button>
              <div class="pk-lbl">Keep the first row per value of</div>
              ${visibleCols.map(c=>html`<button type="button" key=${c.key} class="tbl-mi" onClick=${()=>dedupeBy(c.key)}>
                <${Icon} name=${TYPE_META[c.type].icon} size=13/> ${c.label}</button>`)}`}
          </div>`}
        </div>
        <div class="search" style="width:200px"><${Icon} name="search" size=15/>
          <input placeholder="Search" aria-label="Search all columns" value=${globalQ}
            onInput=${e=>setGlobalQ(e.target.value)}/></div>
        <button type="button" class="btn btn-primary" onClick=${()=>addRow()}><${Icon} name="plus" size=13/> New</button>`}
    </div>

    <div class="tbl-scroll">
      ${note && html`<div style="font-size:12px;color:var(--ink-gray-6);margin-bottom:8px">${note}</div>`}
      ${view==='json' ? html`<${JsonView} db=${db} onApply=${d=>{setDb(d);setView('table');}} onLoadMonitor=${loadMonitor} busy=${busy} note=${note}/>`
      : view==='board' ? html`<${BoardView} boardCol=${boardCol} rows=${sortedRows} visibleCols=${visibleCols}
          setCellValue=${setCellValue} onAddRow=${addRow} onDeleteRow=${deleteRow} onEditRow=${onEditRow}/>`
      : view==='list' ? (filteredCount===0
          ? html`<div class="tbl-frame" style="padding:24px;text-align:center;color:var(--ink-gray-5)">No rows yet. Click New to add one.</div>`
          : html`<${ListView} groups=${groups} groupByCol=${groupByCol} visibleCols=${visibleCols}
              collapsed=${collapsed} toggleCollapse=${toggleCollapse} onDeleteRow=${deleteRow}
              onDuplicateRow=${duplicateRow} onAddRow=${addRow} onEditRow=${onEditRow}/>`)
      : html`<div class="tbl-frame">
          ${filteredCount===0
            ? html`<div style="padding:24px;text-align:center;color:var(--ink-gray-5)">No rows yet. Click New to add one.</div>`
            : groups.map(g=>html`<${GroupBlock} key=${g.id} group=${g} groupByCol=${groupByCol} visibleCols=${visibleCols}
                collapsed=${collapsed} toggleCollapse=${toggleCollapse} headProps=${headProps}
                ghostRows=${groupByCol?0:8}/>`)}
        </div>`}
    </div>
    ${view!=='json' && html`<div class="tbl-foot">${countStr}</div>`}
    </div>

    ${fieldEd && html`<${FieldEditor} col=${editingCol} onSave=${saveField} onClose=${()=>setFieldEd(null)}/>`}
    ${rowEdRow && html`<${RowEditor} row=${rowEdRow} cols=${db.cols} onSet=${(k,val)=>setCellValue(rowEd,k,val)} onDelete=${()=>deleteRow(rowEd)} onClose=${()=>setRowEd(null)}/>`}
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'tables', icon:'sheet', name:'Tables', desc:'GTM Pipeline', component: TablesTool };
