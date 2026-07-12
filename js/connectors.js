/* Connectors module (phase-2 stubs) */
import { Logo, html } from './core.js';


export const CONNECTORS = [
  {name:'Salesforce',           cat:'CRM',        domain:'salesforce.com'},
  {name:'HubSpot',              cat:'CRM',        domain:'hubspot.com'},
  {name:'Smartlead',            cat:'Sequencer',  domain:'smartlead.ai'},
  {name:'Instantly',            cat:'Sequencer',  domain:'instantly.ai'},
  {name:'WhatsApp API',         cat:'Messaging',  domain:'whatsapp.com'},
  {name:'Slack',                cat:'Messaging',  domain:'slack.com'},
  {name:'Google Calendar',      cat:'Calendar',   domain:'google.com'},
  {name:'Enrichment waterfall', cat:'Enrichment', domain:'clearbit.com'},
];


export function ConnectorsTool(){
  return html`
  <div class="view">
    <div class="view-head">
      <h1 class="view-h1">Wire the tools your Runs write back to</h1>
      <p class="view-sub">Connectors are how a Run routes a scored, drafted action into your stack: your CRM, your sequencer, your inbox. Not wired yet.</p>
    </div>
    <div class="conn-grid">
      ${CONNECTORS.map(c=>html`
        <div class="glass-card conn-card">
          <div class="conn-top">
            <span class="conn-ic">${Logo(c.domain, 26)}</span>
            <span class="conn-cat">${c.cat}</span>
          </div>
          <h3 class="conn-name">${c.name}</h3>
          <button class="btn btn-ghost btn-sm conn-btn" disabled>
            Connect <span class="conn-soon">Soon</span>
          </button>
        </div>`)}
    </div>
  </div>`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'connectors', icon:'plug', name:'Connectors', desc:'Wire your CRM, sequencer, and messaging', component: ConnectorsTool };
