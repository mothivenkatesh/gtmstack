# LLM UI Generation Context

Use this file when an LLM, agent, or code generator needs to create new screens, components, modals, dashboards, onboarding flows, or personalized workspaces inside this product suite.

The goal is not visual novelty. The goal is context-aware product UI that feels like it belongs to the same system, supports dense repeated use, and scales from simple tools to complex AI workflows such as personalized portfolio builders, agent workbenches, and analytics dashboards.

## Product UI Principles

1. Start from the user's job, not from a decorative layout.
2. Use the shared design tokens before introducing any new color, radius, shadow, font, or spacing value.
3. Prefer dense, scannable product surfaces over landing-page composition.
4. Make the hierarchy obvious in this order: page purpose, primary action, current state, evidence, next step.
5. Keep app personality in the accent color and domain copy, not in new component geometry.
6. Every generated UI must have empty, loading, success, warning, and error states when the workflow can enter those states.
7. If the screen uses AI output, show provenance, confidence, recency, assumptions, and a human override path.
8. Prefer reusable definitions over one-off screen logic: metrics, dimensions, portfolios, rules, saved searches, and prompts should be visible, editable, and reusable.
9. Expose dependencies before risky changes. If an edit can affect downstream reports, generated artifacts, or collaborators, show the impact before publishing.
10. Do not generate structural inline CSS. Use named classes, reusable components, and `--ds-*` tokens.

## Context Inputs

Before generating UI, infer or request these fields:

| Context | Examples | UI impact |
| --- | --- | --- |
| User role | founder, GTM lead, analyst, investor, operator | Nav labels, default filters, visible metrics |
| Task stage | discover, compare, configure, generate, review, export | Layout template and primary action |
| Data density | sparse, medium, dense, streaming | Card/table/chart choice |
| Risk level | low, reversible, expensive, compliance-sensitive | Confirmation, audit trail, warning states |
| Personalization | saved pains, company rails, target accounts, portfolio companies | Defaults, pinned sections, recommendations |
| Evidence need | low, medium, high | Citations, source chips, timestamps, confidence |
| Collaboration | solo, shareable, approval workflow | Comments, share buttons, status labels |
| Definition scope | one-off, saved, shared, global | Naming, ownership, dependency warnings |
| Dependency graph | none, shallow, deep, unknown | Impact preview, dependency modal, publish guardrail |
| Reuse frequency | rare, weekly, daily, workflow-critical | Library/listing pattern, search, edit history |

If context is unknown, choose conservative defaults: dense product shell, clear filters, reversible actions, and visible provenance.

## Research-Backed Rules

These rules are derived from product-design case studies on complex reporting and marketing-analytics systems:

- From ScaleXP's reporting work: users needed flexible columns, actual-vs-target comparison, entity breakdowns, reusable metric definitions, and correct tree-based calculation order. One UI should treat analytics UI as a configurable system of definitions, not only as charts on a page. Source: https://suwardhan.com/scalexp
- From Clarisights' custom-dimensions work: users were hurt by redundant filters, hidden downstream effects, and important details hidden behind too many clicks. One UI should give single-click access to values, channels, filters/rules, and dependencies before publishing changes. Source: https://suwardhan.com/clarisights
- Use compact, scan-first listing views for reusable definitions. Put critical fields directly in the row or card rather than behind nested menus.
- Prefer a dependency modal or drawer when edits may affect other surfaces. Show affected reports, generated UI, owners, and last-used metadata.
- Use color to support rule/state comprehension, but tokenized status colors must carry the meaning; do not invent local palettes per screen.

## Complex Systems Model

For advanced products such as personalized portfolio builders, AI agent apps, analytics suites, and GTM research workbenches, generate UI from this model:

| Model piece | UI requirement |
| --- | --- |
| Entity | Name, owner, type, status, recency, primary action |
| Definition | Reusable metric, rule, segment, prompt, saved search, or portfolio |
| Rule | Inputs, filters, channels/sources, exceptions, preview results |
| Dependency | Downstream dashboards, reports, generated artifacts, workflows, users |
| Evidence | Source, timestamp, sample size, confidence, assumptions |
| Lifecycle | Draft, preview, review, published, archived, rollback |
| Permissions | Owner, editor, viewer, approval required |
| Personalization | Why shown, ranking basis, pin/hide/save/reset controls |

If a generated UI cannot identify these pieces, it should start with a conservative discovery or setup flow rather than pretending the system is already configured.

## Layout Patterns

| Pattern | Use when | Structure |
| --- | --- | --- |
| Dashboard overview | User needs current state and drilldowns | Page header, KPI row, 2-column analytic modules, table/list below |
| Builder workflow | User configures and generates an artifact | Step rail or progress bar, form panel, preview/output panel |
| Research browser | User scans many candidates | Sticky filters, search, sortable cards/table, saved state |
| Detail workspace | User evaluates one entity deeply | Summary hero, evidence tabs, side metadata, action footer |
| Compare view | User chooses between options | Segmented controls, normalized rows, difference highlights |
| AI review queue | User approves or edits generated items | Status tabs, confidence chips, source citations, batch actions |
| Personalized portfolio | User monitors many owned entities | Owner-specific filters, pinned entities, alerts, portfolio rollup, per-entity drilldown |

Do not use a marketing hero for app screens. Hero-scale type belongs only to public landing pages.

## Component Contracts

### App Shell
- Dark left sidebar on all app screens.
- Light workspace with constrained inner content.
- Sidebar items use icon plus label, grouped by task stage.
- Active state uses the app accent but remains readable on `--ds-sidebar-bg`.

### Page Header
- Kicker: optional, mono or small uppercase, app accent.
- Title: one sentence naming the user's current job.
- Supporting text: one line explaining what changed, what is selected, or what the user can do.
- Actions: primary action first, then secondary actions.

### Cards And Panels
- Use `--ds-bg-card`, `--ds-border-subtle`, and `--ds-radius-card`.
- Cards represent one repeated object or one bounded analytic module.
- Panels hold a tool, chart, form, or long-form result.
- Do not nest cards inside cards. Use section dividers or full-width bands instead.

### Tables
- Use tables for comparison, rankings, ledger-like data, and dense evidence.
- Always include meaningful empty states and sortable/default order when relevant.
- Numeric columns should align right and use tabular numbers.
- Keep row actions visible but quiet.

### Charts
- Use charts only when the visual answer is faster than a table.
- Every chart needs a title, metric unit, time window or sample scope, and a table fallback or underlying data access.
- Use app accent for the primary series; use muted neutrals for context series.
- Avoid rainbow palettes unless categories are central to the analysis.

### Forms
- Group fields by decision, not database schema.
- Put helper text below fields when the field affects output quality.
- Validate inline and preserve user input on errors.
- For AI generation forms, show what context will be sent and what will be saved.

### Modals
- Use modals for focused decisions, confirmations, settings, and small creation flows.
- Do not use modals for complex multi-step workspaces; use a page or drawer.
- Modal anatomy: title, short explanation, body, footer actions.
- Destructive or external-side-effect actions require explicit copy and a secondary cancel action.
- Use dependency modals before publishing edits to shared definitions. Show affected surfaces, severity, owner, last used date, and a preview of the changed output.

### Drawers
- Use drawers for inspecting or editing one item without losing list context.
- Drawers should include summary, evidence, editable fields or actions, and close affordance.
- Avoid using drawers for unrelated navigation.

### AI Output Blocks
- Show generation state, model/action label when useful, and result confidence.
- Include source chips or citations for claims.
- Separate generated recommendation from raw evidence.
- Provide regenerate, edit, copy/export, and save actions when appropriate.
- Never make AI output look more certain than the available evidence supports.

## Personalization Rules

Personalized UI should make the user's context visible and editable:

- Show the active entity: company, portfolio, account list, persona, market, or saved segment.
- Provide "why this is shown" for recommendations.
- Let users pin, hide, save, dismiss, or reset personalized modules.
- Separate user-owned data from public/reference data.
- If personalization affects ranking, show the ranking basis.

For a personalized portfolio builder:

- Start with portfolio-level summary: total entities, alerts, opportunities, risks.
- Provide filters for stage, sector, geography, owner, status, and recency.
- Use cards for entity snapshots and tables for comparisons.
- Use drawers for entity deep dives.
- Use AI recommendations only with evidence, confidence, and next action.

## Gold Standard Consistency Rubric

A generated screen is gold-standard only if all checks pass:

| Check | Pass criteria |
| --- | --- |
| Token use | No one-off font, color, radius, or shadow unless added to `DESIGN_SYSTEM.md` |
| Inline CSS | No structural inline CSS; exceptions are isolated, data-driven, and documented |
| Shell consistency | Dark sidebar, light workspace, app accent only for active/primary states |
| Type scale | Product pages use 14px body, 28px page title, 15-16px card titles |
| Component fit | Cards, tables, charts, forms, modals, and drawers are used for the right job |
| State coverage | Loading, empty, error, success, warning, disabled states exist where applicable |
| Evidence | AI or analytical claims include source, timestamp, confidence, or assumption context |
| Dependencies | Shared definitions expose impacted reports, workflows, generated UI, and owners |
| Responsiveness | Layout works at desktop and mobile widths without overlapping or clipped text |
| Accessibility | Text contrast is AA for small text; controls have labels and visible focus states |
| Density | Operational screens are scannable and not padded like marketing pages |
| Drift | New UI visually matches at least two existing suite screens before introducing variation |

## LLM Prompt Contract

When asking an LLM to generate UI, include this context:

```text
You are generating product UI for the GTMstack / India Payments / Agentic Stack suite.
Use the shared design tokens from DESIGN_SYSTEM.md and the component/layout rules from UI_GENERATION_CONTEXT.md.
Keep the dark sidebar + light workspace shell.
Use the app accent only for primary actions, active states, focused controls, and key chart series.
Do not use structural inline CSS. Use classes, components, and --ds-* tokens.
Choose layout by user task: dashboard, builder, research browser, detail workspace, compare view, AI review queue, or personalized portfolio.
Include loading, empty, error, warning, and success states when relevant.
For AI output, include confidence, evidence, provenance, recency, and human override actions.
For shared definitions, show dependencies and publish impact before destructive or global edits.
Do not create a marketing hero or decorative card layout for an app screen.
```

## Review Workflow

Before accepting generated UI:

1. Compare computed styles against the `--ds-*` tokens.
2. Check at least one desktop and one mobile viewport.
3. Verify no text overlaps, clips, or becomes unreadable.
4. Confirm the component choices match the user's task stage.
5. Confirm AI/analytics surfaces show evidence and uncertainty.
6. Run `npm run audit` in One UI and inspect token drift plus inline CSS debt.
7. Run the app's existing build or UI consistency checks.
