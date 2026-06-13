# One UI Visual Research Audit

This audit records the source-backed visual pass used to improve One UI. It covers all five supplied Suwardhan case-study links, including raster screenshots and SVG/vector assets that were reachable from each page.

## Coverage

| Source | Link | Downloaded assets | Inaccessible assets | Primary UI domain |
| --- | --- | ---: | ---: | --- |
| ScaleXP | https://suwardhan.com/scalexp | 16 | 0 | Financial reporting, configurable tables, metric builders |
| Clarisights | https://suwardhan.com/clarisights | 11 | 2 | Marketing analytics, reusable dimensions, dependency-aware editing |
| Leap | https://suwardhan.com/leap | 7 | 0 | Mobile wallet, trust, high-risk actions |
| Smartbeings | https://suwardhan.com/smartbeings | 14 | 0 | Conversation and journey flow builder |
| Recko | https://suwardhan.com/18531115 | 27 | 0 | Design-system foundation, tokens, components, adoption |

Total inspected: 75 downloaded assets plus the page text for all five sources. Two Clarisights assets returned 404 from the source page (`cover.svg`, `dependencies.jpg`); the available Clarisights table, dependency modal, component, and rollout screenshots were inspected instead.

## Source Findings

### ScaleXP

Observed assets included report screenshots, flexible column configuration, row computation iterations, research notes, final column and row editors, 4px specifications, and product-section diagrams.

One UI rules extracted:

- Dense web apps should support horizontal scan patterns when users compare columns, periods, actuals, targets, forecasts, entities, or scenarios.
- Reporting UI should treat metrics and formulas as reusable definitions with owner, source, last edited, dependencies, and calculation order.
- Calculation builders need tree/order-of-operations views rather than flat row-only editors.
- The 4px base grid is appropriate for dense enterprise controls and should be preserved across generated UI.
- Specs should show the grid and control dimensions so implementation does not rely on visual guessing.

### Clarisights

Observed assets included custom dimension list/detail screens, expanded row structures, rule/filter chips, dependency modal, old and final UI comparisons, specs, rollout feedback, and SVG component fragments.

One UI rules extracted:

- Reusable definition lists should expose the critical fields directly: values, sources/channels, filters/rules, dependency count, and last-used or owner metadata.
- Information architecture should remove redundant rule entry. Prefer `Definition -> Value -> Rule -> Source/Filter` over repeated channel-specific authoring.
- Global edits need dependency previews before publish, delete, regenerate, or rename.
- Rule chips and filter clauses can use color, but only through semantic or app-accent tokens.
- Dense tables need row expansion, quiet actions, visible counts, and stable alignment before decorative cards.

### Leap

Observed assets included mobile wallet concepts, portfolio, connect-wallet bottom sheet, send flow, asset detail, staking, governance proposal, seed phrase trust screen, information architecture, and App Store feedback.

One UI rules extracted:

- Mobile product UI needs its own navigation model: sticky context, bottom nav, safe-area action placement, and one task per screen.
- High-risk flows such as connect, send, vote, generate, publish, deploy, or sync need trust copy, visible entity/account context, and explicit confirmation.
- Bottom sheets are the right surface for focused mobile decisions that should preserve page context.
- Mobile cards can be visually rich, but they must keep hierarchy tight: entity, value, status, action.
- A mobile component library must cover portfolio summaries, asset rows, amount entry, review actions, confirmation, bottom sheets, and secure recovery/import states.

### Smartbeings

Observed assets included information architecture diagrams, domain assets, empty states, intent modals, interface breakdowns, node configuration, response configuration, branching, error/testing views, and sample flows.

One UI rules extracted:

- Complex builder UI should keep domain assets, canvas, and configuration/testing visible together on desktop.
- Domain assets should be one click away and editable in context through modals/drawers that preserve canvas state.
- Node cards need type, label, status, branch relationship, and node-level error affordances.
- Branch conditions must stay attached to the branch node, not hidden in a separate settings page.
- Testing and error panels should be parallel to the builder, not a separate destination that loses context.

### Recko

Observed assets included design principles, UI audit, spacing scale, 12-column grid, grid behavior, margin/gutter diagrams, type-scale examples, font alignment comparisons, icon guidelines, color palette, component boards, stateful button/dropdown/slider components, documentation, adoption, and chronology.

One UI rules extracted:

- Start with product principles and a UI audit before expanding tokens or components.
- Foundation order is principles, audit, spacing, grid, type, color, icon, components, adoption.
- Use a 4px spacing scale, 12-column content grid, fixed sidebar outside the content grid, and context-driven grid behavior.
- Pair every type size with a line-height token.
- Components require state matrices and documentation before they are considered complete.
- Adoption requires changelog, support, QA before handoff, and inclusive design-engineering decisions.

## Gold-Standard Manual Rubric

Use this rubric before shipping any generated or hand-built One UI surface.

| Dimension | Pass standard |
| --- | --- |
| Source fit | Screen maps to a known pattern from this audit or records why a new pattern is needed |
| Token discipline | Color, type, spacing, radius, shadow, and focus states use `--ds-*` tokens |
| Layout choice | Dashboard, definition list, builder, mobile task, detail, compare, or review layout matches the job |
| Data density | Dense operational views stay scan-first with tables/lists before cards |
| Definition modeling | Metrics, dimensions, portfolios, prompts, rules, and journeys are reusable objects when they can recur |
| Dependency safety | Shared or global edits show impact preview before commit |
| Builder context | Assets, canvas, config/testing, node status, branch state, and flow-level actions remain visible |
| Mobile quality | Top context, bottom nav or sheet, 44px targets, safe-area actions, and trust states are present |
| Component completeness | Variants, anatomy, token mapping, states, long text, accessibility, and async behavior are documented |
| Evidence and AI | AI/analytics claims include sources, recency, assumptions, confidence, and human override |
| Accessibility | AA contrast, keyboard focus, labels, and non-overlapping text are verified |
| Governance | Deviation is documented and added to the One UI backlog when repeated |

## LLM Generation Implication

When an LLM generates UI for this suite, it should first classify the screen as one of these audited product patterns:

- Dense analytics/reporting definition UI
- Reusable rule or dimension management
- High-risk mobile task flow
- Journey/conversation/agent flow builder
- Design-system component or foundation work
- AI evidence review or personalized portfolio workspace

If the pattern is unclear, generate a discovery/setup screen with conservative defaults rather than inventing a new visual system.
