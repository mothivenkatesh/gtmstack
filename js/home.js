/* Home: template gallery */
import { Icon, h, html, useState } from './core.js';
import { SAMPLE_COPY } from './persona.js';
import { CLEAN_SAMPLE } from './clean.js';
import { PLAY_CARDS, PlayRunner } from './plays.js';

// Brand-ish colors for the engine-icon row on each card (the apps a use case
// touches), so a card reads at a glance like the Workspace template grid.
export const APP_COLOR = {
  github:'#1f2328', twitter:'#1f2328', youtube:'#ff0033', linkedin:'#0a66c2',
  reddit:'#ff4500', sparkles:'var(--ink-blue-2)', users:'var(--ink-violet-1)',
  mail:'var(--ink-gray-6)', sealCheck:'var(--ink-green-2)', captions:'var(--ink-gray-6)',
};


export const HOME_TEMPLATES = [
  {cat:'Prospecting', tool:'signals', icon:'userSearch',
   title:'Walk in knowing what they shipped this week',
   desc:'What a prospect actually shipped this week, across GitHub, X, LinkedIn, and YouTube.',
   engines:['github','twitter','linkedin','youtube'], eg:'rauchg',
   payload:{unit:'person', query:'rauchg', sources:['github','linkedin','x','youtube']}},
  {cat:'Account mapping', tool:'signals', icon:'building',
   title:'See the whole buying room, not one name',
   desc:'A company’s footprint plus the people inside it, ready to route a play to.',
   engines:['github','twitter','linkedin','youtube'], eg:'vercel.com',
   payload:{unit:'company', query:'vercel.com', sources:['github','linkedin','x','youtube']}},
  {cat:'Buying signals', tool:'signals', icon:'hash',
   title:'Catch the topic the minute it moves',
   desc:'A live, newest-first feed for any phrase. The trigger an AI SDR fires on.',
   engines:['github','twitter','reddit','youtube'], eg:'model context protocol',
   payload:{unit:'keyword', query:'model context protocol', sources:['github','x','reddit','youtube']}},
  {cat:'List hygiene', tool:'clean', icon:'broom',
   title:'Hand your agent a list it can actually send to',
   desc:'Syntax, live MX, disposable, role, and typos checked, then de-duped.',
   engines:['mail','sealCheck'], eg:'7 messy contacts',
   payload:{text: CLEAN_SAMPLE}},
  {cat:'Messaging', tool:'persona', icon:'users',
   title:'Let five developers gut your headline before launch',
   desc:'Five synthetic developers score your copy and name the fix worth the most.',
   engines:['users','sparkles'], eg:'a sample landing line',
   payload:{copy: SAMPLE_COPY, ctype:'landing'}},
  {cat:'Research', tool:'extract', icon:'captions',
   title:'Steal the exact words your market already uses',
   desc:'Any founder or competitor talk, transcribed clean and timestamped to mine.',
   engines:['youtube','captions'], eg:'a sample talk',
   payload:{url:'https://www.youtube.com/watch?v=T1Lowy1mnEg'}},
];

/* Composite "plays" chain several engines into ONE agent-callable run that
   returns every step's result inline. Today only the content axis composes
   cleanly (transcript -> persona); contact-axis plays wait for the connector
   phase. See api/_plays.py. Adding a play = one entry here + one in PLAYS. */


export function HomeTool({onLaunch, tools}){
  const [play, setPlay] = useState(null);
  if(play) return html`<${PlayRunner} card=${play} onBack=${()=>setPlay(null)} />`;
  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Your GTM research in one click, not one afternoon</h1>
      <p class="view-sub">Each card opens the right tool with a real example already run, so you see exactly what an AI agent gets back.</p>
    </div>
    <div class="home-grid">
      ${HOME_TEMPLATES.map(t=>{ const dest=tools[t.tool]; return html`
        <div class="glass-card home-card" onClick=${()=>onLaunch(t.tool, t.payload)} title=${'Open '+dest.name+' and run this live'}>
          <div class="hc-top">
            <span class="hc-ic"><${Icon} name=${t.icon} size=19 /></span>
            <span class="hc-cat">${t.cat}</span>
          </div>
          <h3 class="hc-title">${t.title}</h3>
          <p class="hc-desc">${t.desc}</p>
          ${t.engines&&html`<div class="hc-apps">${t.engines.map(e=>html`
            <span class="hc-app" style=${'color:'+(APP_COLOR[e]||'var(--ink-gray-5)')}><${Icon} name=${e} size=18 /></span>`)}</div>`}
          <div class="hc-foot">
            <span class="hc-eg">Opens ${dest.name} · loads <b>${t.eg}</b></span>
            <span class="hc-go">Run it <${Icon} name="arrowRight" size=13 /></span>
          </div>
        </div>`; })}
    </div>

    <div class="home-sec">
      <div class="home-sec-h"><span class="hs-ic"><${Icon} name="play" size=15 /></span> Multi-step plays</div>
      <p class="home-sec-sub">Plays chain several tools into one run an agent can call and branch on. Each returns every
        step’s result inline, so there is nothing to poll.</p>
      <div class="home-grid">
        ${PLAY_CARDS.map(p=>html`
          <div class="glass-card home-card play-card" onClick=${()=>setPlay(p)} title=${'Run the '+p.title+' play'}>
            <div class="hc-top">
              <span class="hc-ic"><${Icon} name=${p.icon} size=19 /></span>
              <span class="hc-cat">${p.cat}</span>
            </div>
            <h3 class="hc-title">${p.title}</h3>
            <p class="hc-desc">${p.desc}</p>
            <div class="hc-foot">
              <span class="hc-eg">${p.steps}</span>
              <span class="hc-go">Run play <${Icon} name="arrowRight" size=13 /></span>
            </div>
          </div>`)}
      </div>
    </div>

    <p style="font-size:12px;color:var(--ink-gray-4);text-align:center;margin:24px 0 0">
      Every tool here is also an API an agent can call, not just a screen to click.
    </p>
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'home', icon:'house', name:'Home', desc:'GTM use-case templates, prefilled and ready to run', component: HomeTool };
