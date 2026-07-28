/* Harness module - your GTM team.

   Rebuilt as a coworker surface, not a control panel. The first cut of this was
   an admin console with five tabs full of engineer vocabulary (tool names, node
   types, predicates, risk tiers). A GTM lead does not think in any of that.

   The shape now follows OpenWorker's actual product idea, not just its
   permission model: you DELEGATE work in plain English, the teammate does it,
   and when it needs a decision it puts an item in your INBOX and waits. The
   inbox is the canonical human-attention queue, and it is the first thing you
   see when something is waiting.

   Vocabulary rules for this file, because they are the difference between a
   tool a RevOps lead adopts and one they bounce off:
     - "teammate", not agent id. "watching", not classify_relevance.
     - Ask permission in outcomes: "Send you an alert when something matters",
       never "send_message".
     - Never show ids, node types, or predicates in the main flow.
*/
import { API_BASE, Icon, html, useEffect, useState } from './core.js';

/* The harness endpoints are gated (they run agents and write to the graph), so
   the browser has to present the shared secret. It is read from localStorage,
   NOT baked into the bundle: this file is served as a public static asset, so a
   literal here would publish the secret to anyone who views source.

   Set it once in the console:  localStorage.gtmstackHarnessSecret = '...'
   Local dev needs nothing, because the gate only bites when HARNESS_SECRET is
   set or the code is running on Vercel. */
const secret = () => { try { return localStorage.getItem('gtmstackHarnessSecret') || ''; }
                       catch (e) { return ''; } };

const api = (path, body) => {
  const h = {};
  const s = secret();
  if (s) h['X-Harness-Secret'] = s;
  if (body) h['Content-Type'] = 'application/json';
  return fetch(`${API_BASE}/api/${path}`,
               body ? { method: 'POST', headers: h, body: JSON.stringify(body) }
                    : { headers: h })
    .then(async r => {
      const d = await r.json().catch(() => ({}));
      // Surface the gate as a readable message instead of a blank panel.
      if (r.status === 401) return { error: d.detail || 'unauthorized', unauthorized: true };
      return d;
    });
};

const TABS = [
  ['work',  'Work',      'zap'],
  ['inbox', 'Inbox',     'mail'],
  ['team',  'Your team', 'users'],
  ['lists', 'Lists',     'funnel'],
  ['knows', 'Memory',    'book'],
];

/* Things a GTM lead would actually type. Doubles as onboarding: the empty state
   teaches the product by example rather than by instruction. */
const EXAMPLES = [
  'Watch for people asking which payment gateway to use',
  'Tell me when someone compares us to a competitor',
  'How many duplicate contacts do we have',
  'Who is talking about us on Reddit this week',
];

export function HarnessTool() {
  const [tab, setTab] = useState('work');
  const [waiting, setWaiting] = useState(0);

  const refreshInbox = () => api('inbox').then(d => setWaiting(d.count || 0)).catch(() => {});
  useEffect(() => { refreshInbox(); }, []);

  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Your GTM team</h1>
      <p class="view-sub">Tell them what you want done, in your own words. They do the work and
        come back to you when they need a decision.</p>
    </div>
    <div class="hn-tabs">
      ${TABS.map(([id, label, icon]) => html`
        <button class=${'hn-tab' + (tab === id ? ' is-on' : '')} onClick=${() => setTab(id)}>
          <${Icon} name=${icon} size=${15} /> ${label}
          ${id === 'inbox' && waiting > 0 && html`<span class="hn-dot">${waiting}</span>`}
        </button>`)}
    </div>
    <div class="hn-body">
      ${tab === 'work'  && html`<${WorkPanel} onNeedsYou=${refreshInbox} goInbox=${() => setTab('inbox')} />`}
      ${tab === 'inbox' && html`<${InboxPanel} onChange=${refreshInbox} />`}
      ${tab === 'team'  && html`<${TeamPanel} />`}
      ${tab === 'lists' && html`<${ListsPanel} />`}
      ${tab === 'knows' && html`<${MemoryPanel} />`}
    </div>
  </div>`;
}

/* ── Work: delegate in plain English, watch it happen ─────────────────────── */

function WorkPanel({ onNeedsYou, goInbox }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    api('agents?runs=1&limit=6').then(d => setHistory(d.runs || [])).catch(() => {});
  }, []);

  const send = async (q) => {
    const ask = (q ?? text).trim();
    if (!ask || busy) return;
    setBusy(true); setResult(null);
    const r = await api('agents', { ask });
    setResult(r);
    setBusy(false);
    setText('');
    onNeedsYou && onNeedsYou();
    api('agents?runs=1&limit=6').then(d => setHistory(d.runs || [])).catch(() => {});
  };

  return html`
  <div>
    <div class="glass-card hn-ask">
      <textarea class="hn-askbox" rows="2" value=${text}
        placeholder="What do you want your team to do?"
        onInput=${e => setText(e.target.value)}
        onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}></textarea>
      <div class="hn-askrow">
        <span class="hn-hint">Plain English. Press Enter to send.</span>
        <button class="btn btn-primary btn-sm" onClick=${() => send()} disabled=${busy || !text.trim()}>
          ${busy ? 'Working...' : 'Send to my team'}</button>
      </div>
    </div>

    ${!result && !busy && html`
      <div class="hn-examples">
        <div class="hn-exlbl">Try one of these</div>
        ${EXAMPLES.map(e => html`
          <button class="hn-ex" onClick=${() => send(e)}>${e}</button>`)}
      </div>`}

    ${result && html`<${ResultCard} r=${result} goInbox=${goInbox} />`}

    ${history.length > 0 && html`
      <div class="glass-card hn-card">
        <div class="hn-h">Recently done</div>
        ${history.map(h => html`
          <div class="hn-histrow">
            <span class="hn-histwho">${h.name}</span>
            <span class="hn-histwhat">${(h.input && (h.input.question || h.input.query)) || ''}</span>
            <span class="hn-histn">${h.emitted ? `${h.emitted} found` : 'no new items'}</span>
          </div>`)}
      </div>`}
  </div>`;
}

/* The run, told as a story rather than a step table. Each line is what the
   teammate DID, in words the person who asked would use. */
function ResultCard({ r, goInbox }) {
  const waiting = (r.queued || []).length;
  const done = (r.steps || []).filter(s => s.status === 'ok');
  const who = r.routed ? r.routed.name : r.name;

  // A teammate with no steps is not wired up yet. Say so plainly rather than
  // reporting "got to work" over an empty card, which reads as a silent failure.
  if ((r.steps || []).length === 0) return html`
    <div class="glass-card hn-card">
      <div class="hn-h">${who} cannot take this on yet
        <span class="hn-sub">${r.routed ? r.routed.why : ''}</span></div>
      <div class="hn-line">
        <${Icon} name="alert" size=${14} />
        <span>${who} needs a connection before it can work. Nothing was run, and
          nothing was changed.</span>
      </div>
    </div>`;

  return html`
  <div class="glass-card hn-card">
    <div class="hn-h">
      ${who} got to work
      <span class="hn-sub">${r.routed ? r.routed.why : ''}</span>
    </div>

    <div class="hn-story">
      ${done.map(s => html`
        <div class="hn-line">
          <${Icon} name="check" size=${14} />
          <span>${s.output || s.text}</span>
        </div>`)}
      ${(r.steps || []).filter(s => s.status === 'error').map(s => html`
        <div class="hn-line hn-line-err">
          <${Icon} name="alert" size=${14} /><span>${s.error}</span>
        </div>`)}
    </div>

    ${waiting > 0 && html`
      <div class="hn-needyou">
        <div>
          <b>${waiting === 1 ? 'One thing needs your OK' : `${waiting} things need your OK`}</b>
          <span>Your teammate paused rather than guess.</span>
        </div>
        <button class="btn btn-primary btn-sm" onClick=${goInbox}>Open inbox</button>
      </div>`}

    ${waiting === 0 && r.emitted > 0 && html`
      <div class="hn-done">Saved ${r.emitted} items. Check <b>Lists</b> to see them grouped.</div>`}
  </div>`;
}

/* ── Inbox: the human-attention queue ────────────────────────────────────── */

function InboxPanel({ onChange }) {
  const [d, setD] = useState(null);
  const load = () => api('inbox').then(setD);
  useEffect(() => { load(); }, []);

  const answer = async (id, outcome) => {
    await api('inbox', { id, outcome });
    load(); onChange && onChange();
  };

  if (!d) return html`<div class="hn-empty">Loading...</div>`;

  return html`
  <div>
    ${d.count === 0 && html`
      <div class="glass-card hn-card hn-zero">
        <${Icon} name="check" size=${20} />
        <div><b>Nothing needs you</b>
          <span>Your team is working within the permissions you have already given.
            ${d.settled > 0 ? ` ${d.settled} standing ${d.settled === 1 ? 'permission' : 'permissions'} in place.` : ''}</span>
        </div>
      </div>`}

    ${d.items.map(it => html`
      <div class="glass-card hn-card hn-item">
        <div class="hn-itemtop">
          <span class="hn-who">${it.agent}</span>
          <span class="hn-asks">asks</span>
          ${it.spends_money && html`<span class="pill pill-red">spends money</span>`}
        </div>
        <div class="hn-itemtitle">${it.title}</div>
        <div class="hn-itemdetail">${it.detail}</div>
        ${it.context && html`<div class="hn-itemctx">${it.context}</div>`}
        <div class="hn-btns">
          <button class="btn btn-primary btn-sm" onClick=${() => answer(it.id, 'always')}>
            Yes, always</button>
          <button class="btn btn-ghost btn-sm" onClick=${() => answer(it.id, 'once')}>
            Just this once</button>
          <button class="btn btn-ghost btn-sm" onClick=${() => answer(it.id, 'deny')}>
            No</button>
        </div>
        <div class="hn-fine">Choosing "always" means your team stops asking for this.
          You can change it any time.</div>
      </div>`)}
  </div>`;
}

/* ── Your team ───────────────────────────────────────────────────────────── */

function TeamPanel() {
  const [agents, setAgents] = useState([]);
  const [open, setOpen] = useState(null);
  const [aop, setAop] = useState(null);

  useEffect(() => { api('agents').then(d => setAgents(d.agents || [])); }, []);
  useEffect(() => { if (open) api(`agents?id=${open}`).then(setAop); else setAop(null); }, [open]);

  if (open && aop) return html`
    <div>
      <button class="btn btn-ghost btn-sm" onClick=${() => setOpen(null)}>
        <${Icon} name="arrowLeft" size=${14} /> Back to the team</button>
      <div class="glass-card hn-card">
        <div class="hn-h">${aop.name}<span class="hn-sub">${aop.role}</span></div>
        <div class="hn-lbl">When ${aop.name} steps in</div>
        <div class="hn-scope">${aop.scope}</div>
        ${(aop.steps || []).length > 0 && html`
          <div class="hn-lbl">How ${aop.name} works</div>
          <ol class="hn-steps">${aop.steps.map(s => html`<li>${s.text}</li>`)}</ol>
          <div class="hn-fine">These are instructions in plain English, not code.
            Change them and ${aop.name} changes how it works.</div>`}
        ${(aop.guardrails || []).length > 0 && html`
          <div class="hn-lbl">Lines it will never cross</div>
          <ul class="hn-guards">${aop.guardrails.map(g => html`<li>${g}</li>`)}</ul>`}
      </div>
    </div>`;

  return html`
  <div class="hn-grid">
    ${agents.map(a => html`
      <button class="glass-card hn-mate" onClick=${() => setOpen(a.id)}>
        <div class="hn-matetop">
          <span class="hn-matename">${a.name}</span>
          ${a.runnable
            ? html`<span class="pill pill-green">ready</span>`
            : html`<span class="pill pill-gray">needs a connection</span>`}
        </div>
        <div class="hn-materole">${a.role}</div>
        <div class="hn-mult">${a.tenx}</div>
      </button>`)}
  </div>`;
}

/* ── Lists (cohorts, in human words) ─────────────────────────────────────── */

function ListsPanel() {
  const [lists, setLists] = useState([]);
  const [open, setOpen] = useState(null);
  const [members, setMembers] = useState(null);

  useEffect(() => { api('cohorts').then(d => setLists(d.cohorts || [])); }, []);
  useEffect(() => {
    if (!open) { setMembers(null); return; }
    api(`cohorts?key=${open}`).then(setMembers);
  }, [open]);

  if (open && members) return html`
    <div>
      <button class="btn btn-ghost btn-sm" onClick=${() => setOpen(null)}>
        <${Icon} name="arrowLeft" size=${14} /> All lists</button>
      <div class="glass-card hn-card">
        <div class="hn-h">${members.name}<span class="hn-sub">${members.count} people</span></div>
        ${(members.members || []).slice(0, 20).map(m => html`
          <div class="hn-person">
            <div class="hn-persontext">${(m.data.text || m.data.handle || '').slice(0, 150)}</div>
            <div class="hn-personwhy">On this list because ${m.reason.replace(/_/g, ' ')}
              ${m.source && html` · <a href=${m.source} target="_blank" rel="noreferrer">see the post</a>`}</div>
          </div>`)}
        ${members.count === 0 && html`
          <div class="hn-empty">Nobody here yet. Ask your team to watch for something in <b>Work</b>.</div>`}
      </div>
    </div>`;

  return html`
  <div>
    <p class="hn-note">Lists build themselves. People join and leave as what they do changes,
      and every person shows why they are on the list.</p>
    <div class="hn-grid">
      ${lists.map(c => html`
        <button class="glass-card hn-mate" onClick=${() => setOpen(c.key)}>
          <div class="hn-matetop"><span class="hn-matename">${c.name}</span></div>
          <div class="hn-materole">${c.plain}</div>
          <div class="hn-count">${c.count} <span>${c.count === 1 ? 'person' : 'people'}</span></div>
        </button>`)}
    </div>
  </div>`;
}

/* ── Memory: what the team has learned ───────────────────────────────────── */

function MemoryPanel() {
  const [g, setG] = useState(null);
  const [defs, setDefs] = useState([]);
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    api('graph').then(setG);
    api('definitions').then(d => setDefs(d.definitions || []));
    api('graph?type=signal&limit=8').then(d => setRecent(d.nodes || []));
  }, []);

  const by = (g && g.counts && g.counts.by_type) || {};
  return html`
  <div>
    <p class="hn-note">Everything your team learns stays here and makes the next job better.
      This is the part that compounds.</p>
    <div class="kpi-grid">
      ${[['Things found', by.signal || 0], ['People known', by.person || 0],
         ['Lists', by.cohort || 0], ['Agreed definitions', by.definition || 0]]
        .map(([k, v]) => html`
        <div class="glass-card kpi"><div class="kpi-label">${k}</div>
          <div class="kpi-value">${v}</div></div>`)}
    </div>

    <div class="glass-card hn-card">
      <div class="hn-h">Agreed definitions<span class="hn-sub">so two reports can never disagree</span></div>
      ${defs.map(d => html`
        <div class="hn-def2">
          <span class="hn-defname">${d.name}</span>
          <span class="hn-defform">${d.formula}</span>
        </div>`)}
    </div>

    <div class="glass-card hn-card">
      <div class="hn-h">Latest finds<span class="hn-sub">every one keeps its link back to the source</span></div>
      ${recent.length === 0 && html`<div class="hn-empty">Nothing yet.</div>`}
      ${recent.map(n => html`
        <div class="hn-person">
          <div class="hn-persontext">${(n.data.text || '').slice(0, 140)}</div>
          <div class="hn-personwhy">
            ${n.data.where || n.data.platform || ''}
            ${n.data.ago ? ` · ${n.data.ago}` : ''}
            ${n.source && html` · <a href=${n.source} target="_blank" rel="noreferrer">see the post</a>`}
          </div>
        </div>`)}
    </div>
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id: 'harness', icon: 'users', name: 'Your team',
  desc: 'Delegate GTM work in plain English', component: HarnessTool };
