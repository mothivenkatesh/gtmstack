/* Connectors module (phase-2 stubs) */
import { API_BASE, Logo, Icon, html, useEffect, useState } from './core.js';


/* LIVE connectors come first and render their real status. The rest stay
   honest placeholders. A connector nobody can find is the same as one that does
   not exist, so this tab is where discovery has to happen: it is where a user
   goes looking when they want their alerts somewhere. */
export const LIVE = [
  {id:'sheets',   name:'Google Sheets', cat:'Delivery', domain:'google.com',
   why:'Alerts land in a tab you already live in, and the Outcome column feeds back'},
  {id:'slack',    name:'Slack',         cat:'Delivery', domain:'slack.com',
   why:'Interrupt the team when something is urgent'},
  {id:'whatsapp', name:'WhatsApp',      cat:'Delivery', domain:'whatsapp.com',
   why:'The channel Indian GTM teams actually read'},
  {id:'email',    name:'Email',         cat:'Delivery', domain:'gmail.com',
   why:'A daily digest of what was found'},
  {id:'hubspot',  name:'HubSpot',       cat:'CRM',      domain:'hubspot.com',
   why:'Gives Analyst and Steward real records instead of public posts'},
  {id:'salesforce', name:'Salesforce',  cat:'CRM',      domain:'salesforce.com',
   why:'Same, through the same provider protocol'},
];

export const CONNECTORS = [
  {name:'Smartlead',            cat:'Sequencer',  domain:'smartlead.ai'},
  {name:'Smartlead',            cat:'Sequencer',  domain:'smartlead.ai'},
  {name:'Instantly',            cat:'Sequencer',  domain:'instantly.ai'},
  {name:'WhatsApp API',         cat:'Messaging',  domain:'whatsapp.com'},
  {name:'Slack',                cat:'Messaging',  domain:'slack.com'},
  {name:'Google Calendar',      cat:'Calendar',   domain:'google.com'},
  {name:'Enrichment waterfall', cat:'Enrichment', domain:'clearbit.com'},
];


export function ConnectorsTool(){
  const [st, setSt] = useState(null);
  useEffect(()=>{
    Promise.all([
      fetch(`${API_BASE}/api/watch`).then(r=>r.json()).catch(()=>({})),
      fetch(`${API_BASE}/api/crm`).then(r=>r.json()).catch(()=>({})),
    ]).then(([w, c])=>setSt({delivery:w.delivery||{}, sheet:w.sheet||{}, crm:c.configured||{},
                             providers:c.providers||[]}));
  },[]);
  const on = (id) => !st ? null
    : (id==='hubspot'||id==='salesforce') ? !!st.crm[id] : !!st.delivery[id];

  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Send your team's findings where you already work</h1>
      <p class="view-sub">Your agents find things around the clock. Connect a destination and they land where you will actually see them.</p>
    </div>

    <div class="conn-grid">
      ${LIVE.map(c=>html`
        <div class=${'glass-card conn-card'+(on(c.id)?' conn-on':'')}>
          <div class="conn-top">
            <span class="conn-ic">${Logo(c.domain, 26)}</span>
            <span class=${'pill '+(on(c.id)?'pill-green':'pill-gray')}>
              ${st ? (on(c.id) ? 'connected' : 'not connected') : '...'}</span>
          </div>
          <h3 class="conn-name">${c.name}</h3>
          <p class="conn-why">${c.why}</p>
        </div>`)}
    </div>

    ${st && st.sheet && !st.sheet.configured && html`
      <div class="glass-card conn-setup">
        <h3 class="conn-name">Connect a Google Sheet</h3>
        <p class="conn-why">${st.sheet.then}</p>
        <ol class="conn-steps">${(st.sheet.steps||[]).map(x=>html`<li>${x}</li>`)}</ol>
      </div>`}

    <h2 class="conn-h2">Coming later</h2>
    <div class="conn-grid">
      ${CONNECTORS.map(c=>html`
        <div class="glass-card conn-card">
          <div class="conn-top">
            <span class="conn-ic">${Logo(c.domain, 26)}</span>
            <span class="conn-cat">${c.cat}</span>
          </div>
          <h3 class="conn-name">${c.name}</h3>
          <button class="btn btn-ghost btn-sm conn-btn" disabled>Connect</button>
        </div>`)}
    </div>
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'connectors', icon:'plug', name:'Connectors', desc:'Wire your CRM, sequencer, and messaging', component: ConnectorsTool };
