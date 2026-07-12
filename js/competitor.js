/* Competitor Intel module */
import { html } from './core.js';
import { COMPETITOR_CARD, PlayRunner } from './plays.js';


export function CompetitorTool(){
  return html`<${PlayRunner} card=${COMPETITOR_CARD} autoRun=${false} />`;
}

/* Module manifest: the standard interface every tool exposes to the shell. */
export const manifest = { id:'competitor', icon:'chartLine', name:'Competitor Intel', desc:'Share of voice vs your competitors', component: CompetitorTool };
