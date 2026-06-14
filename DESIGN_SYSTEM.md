# Unified Product Design System

One UI is the shared design system for the GTMstack / India Payments / Agentic Stack product suite. Product screens should share the same shell, type, card, control, spacing rules, and unified accent color.

## Core Tokens

| Token | Default | Use |
| --- | --- | --- |
| `--ds-font-sans` | Geist Variable / Geist / Inter / system UI | All product UI text |
| `--ds-font-mono` | Geist Mono / SF Mono / monospace | Code, IDs, small metadata |
| `--ds-bg-app` | `#F8F8F8` | App workspace background |
| `--ds-bg-card` | `#FFFFFF` | Cards, panels, modals |
| `--ds-text-strong` | `#171717` | Headings and high-emphasis text |
| `--ds-text-main` | `#383838` | Body text |
| `--ds-text-muted` | `#6B6B6B` | Secondary text |
| `--ds-text-faint` | `#707070` | Captions and disabled text |
| `--ds-border-subtle` | `#E2E2E2` | Card and control borders |
| `--ds-sidebar-bg` | `#0F0F0F` | Shared dark sidebar |
| `--ds-sidebar-panel` | `#1C1C1C` | Sidebar hover surface |
| `--ds-sidebar-border` | `#232323` | Sidebar divider |
| `--ds-sidebar-text-strong` | `#F8F8F8` | Sidebar brand and active text |
| `--ds-sidebar-text` | `#999999` | Sidebar normal text |
| `--ds-sidebar-text-muted` | `#707070` | Sidebar captions |
| `--ds-radius-control` | `8px` | Buttons, inputs, compact controls |
| `--ds-radius-card` | `12px` | Cards and product panels |
| `--ds-radius-pill` | `9999px` | Pills and status chips |
| `--ds-space-1..10` | `4px` to `40px` | Product spacing on a 4px grid |
| `--ds-grid-columns` | `12` | Desktop content-area grid |
| `--ds-grid-gutter` | `24px` | Space between grid columns |
| `--ds-grid-margin` | `24px` | Content-area edge margin |
| `--ds-content-narrow` | `760px` | Focused forms, docs, and review flows |
| `--ds-content-default` | `1280px` | Standard product workspace max width |
| `--ds-content-wide` | `1500px` | Builder, dashboard, and canvas-heavy views |
| `--ds-font-size-*` | `12px` to `20px` | Product type scale |
| `--ds-line-height-*` | `16px` to `28px` | Coupled line heights on the 4px scale |
| `--ds-icon-size-sm/md` | `20px` / `24px` | Compact controls and navigation/feature icons |
| `--ds-control-height-*` | `32px` / `36px` / `44px` | Small, default, and mobile-safe controls |
| `--ds-accent` | `#0070CC` | Primary actions and active states |
| `--ds-accent-soft` | `#F2F9FF` | Focus rings and selected surfaces |
| `--ds-status-*` | info / success / warning / danger | Semantic status text and soft backgrounds |
| `--ds-focus-ring` | `0 0 0 3px var(--ds-accent-soft)` | Focus and selected control outlines |
| `--ds-shadow-card` | subtle 1px shadow | Optional card separation |
| `--ds-shadow-overlay` | larger overlay shadow | Modals, drawers, popovers |

## Foundation Order

Build and extend One UI in this order so later decisions do not create structural debt:

1. Product principles and personality.
2. UI audit: every component, variation, layout, typeface, icon, and color currently in use.
3. Spacing scale.
4. Layout and column grid.
5. Type scale with line-height.
6. Color palette.
7. Icon library and usage rules.
8. Component library with states and edge cases.
9. Adoption model: changelog, QA, support, and review rituals.

When deadlines are tight, define the bare minimum for each foundation so it unblocks the next layer, then refine in versioned updates.

## Unified Accent

| Token | Value | Use |
| --- | --- | --- |
| `--ds-accent` | `#0070CC` | Primary actions, active navigation, focused controls, selected states, and primary chart series |
| `--ds-accent-soft` | `#F2F9FF` | Focus rings, selected surfaces, AI presence backgrounds, and low-emphasis active states |

## Product Shell

- Use a dark left sidebar on all app screens.
- Sidebar width should stay in the `212px` to `224px` range unless a screen has a strong data-density reason.
- Keep the main workspace light and dense.
- Use the `--ds-space-*` scale for spacing. Default to a 4px base grid and avoid arbitrary one-off padding values.
- Desktop content areas use a 12-column grid with stable gutter and edge margins. When a sidebar is present, sidebar width is fixed and the remaining content area owns the 12 columns.
- Choose grid behavior by context: full-width content for dashboards and comparison views; centered/narrow content for forms, focused review, docs, and single-object editing.
- Use `14px` as the default product UI text size.
- Use `28px` for app page titles and `15px` to `16px` for card titles.
- Cards should be white with a 1px subtle border and 12px radius.
- Avoid heavy shadows; use shadows only to separate floating overlays or active hover states.

## Typography

- Type scale and line-height are coupled. Do not invent a font size without its matching line height.
- Product body text defaults to `14px / 20px`.
- Compact metadata can use `12px / 16px`.
- Card titles and dense section headings use `16px / 24px`.
- Compact display labels and modal titles can use `20px / 28px`.
- Base-size text can support more weight variation; larger headings should use fewer weights for consistency.

## Component State Contract

Every reusable component must document its variants, anatomy, states, and token mapping before it is treated as One UI-compliant.

Required states:

- Enabled
- Hover
- Focused
- Active or selected
- Loading
- Disabled
- Error or destructive
- Empty when the component owns data display

Required component documentation:

- Anatomy: slots, icon placement, counter/badge behavior, helper/error text.
- Tokens: surface, stroke, text, icon, focus ring, radius, spacing, height.
- Interaction: keyboard behavior, pointer behavior, selection behavior, escape/close behavior.
- Edge cases: long text, missing data, async loading, permissions, and validation errors.
- Accessibility: label source, ARIA role when needed, contrast, focus order, and minimum target size.

## Icon Rules

- Compact controls use `--ds-icon-size-sm`.
- Sidebar, bottom nav, feature icons, and high-signal empty states use `--ds-icon-size-md`.
- Use one documented icon family and style per app surface. Phosphor, Lucide, or local SVG icons are acceptable only when the app uses them consistently and maps them to the same One UI size tokens.
- Filled icons are acceptable for active navigation, brand marks, or emphasis states; regular/line icons are preferred for neutral controls and repeated table actions.
- Do not mix filled and outline styles inside the same control group unless state changes require it.
- Icons provide context in uncertainty, warnings, empty states, and navigation. They should not replace clear labels for unfamiliar actions.

## Source-Audited Patterns

The detailed evidence log lives in `VISUAL_RESEARCH_AUDIT.md`. Use these patterns as the starting library for generated UI:

| Pattern | Source evidence | One UI requirement |
| --- | --- | --- |
| Dense analytics definition UI | ScaleXP, Clarisights | Prefer tables, row expansion, rule chips, actual/target comparison, and reusable definitions over decorative cards |
| Dependency-aware editing | Clarisights, ScaleXP | Show impacted dashboards, reports, workflows, generated UI, owners, and publish risk before global edits |
| High-risk mobile task flow | Leap | Use sticky context, bottom sheets, safe-area action bars, 44px targets, trust copy, and explicit review/confirm states |
| Journey or conversation builder | Smartbeings | Keep assets, canvas, configuration/testing, node status, branches, and flow actions visible in one workflow |
| Design-system foundation work | Recko | Start with principles and UI audit, then spacing, grid, type, color, icon, components, and adoption rituals |

If a generated screen does not match one of these patterns, record the new pattern and add its tokens/components before treating it as One UI-compliant.

## Mobile App Shell

Mobile product screens should feel intentionally designed, not like compressed desktop screens.

- Use a sticky compact top bar for app identity, current context, and overflow/navigation access.
- Use a dark bottom navigation bar for the primary app sections when the desktop app uses a dark sidebar.
- Respect `env(safe-area-inset-bottom)` and keep primary actions above the OS home indicator.
- Use 44px minimum tap targets for bottom nav, icon buttons, segmented controls, and primary actions.
- Prefer a single-column task flow with progressive disclosure over shrinking a 3-column desktop layout.
- Keep the current entity, saved context, and trust/security status visible near the top of mobile flows.
- Use sticky mobile action bars for expensive actions such as generate, deploy, recommend, publish, vote, connect, or review.
- Use bottom sheets for focused mobile decisions that should preserve the current page: connect, choose account, select asset, configure rule, review generated output, or confirm publish.
- Every high-risk mobile flow needs a review state before commit and a visible cancel/escape path.

## Builder Layouts

For journey builders, conversation builders, flow editors, prompt chains, and agent-workflow designers:

- Desktop builder layout: assets/library rail, central flow canvas, configuration/testing panel.
- Mobile builder layout: flow first, then configuration/testing, with assets exposed through tabs, drawers, or compact chips.
- Every node needs type, status, label, short description, and next action.
- Use semantic status tokens for node errors, warnings, ready states, and testing results.
- Show flow-level status near the deploy/recommend/publish action.
- Let users test or preview the journey without losing their place in the builder.
- Keep branch conditions visually attached to the branch node.
- When no node is selected, the right panel should become a tester, preview, or flow-level issue panel instead of going blank.

## No Structural Inline CSS

Generated UI must not use inline CSS for structure, layout, color, typography, radius, shadows, spacing, or state styling. Put styling in named classes, components, or token-backed CSS variables.

Allowed exceptions are narrow and reviewable:

- Data-driven chart geometry such as bar widths, SVG coordinates, or canvas dimensions.
- Runtime measured overlay positions when a popover, tour, or tooltip is anchored to live DOM.
- CSS variable handoff at a component boundary, for example `style={{ '--series-color': color }}` with the actual styling in CSS.
- Third-party library interop where the library only accepts inline style objects.
- Accessibility bridge styles, such as a visually hidden honeypot, until a shared utility exists.

If an exception repeats, promote it to a reusable utility or component.

## Contextual Complexity

For complex systems, the design system must model definitions and relationships before screens:

- Reusable definitions: metrics, custom dimensions, portfolios, account lists, prompts, rules, segments.
- Dependencies: what will change if a definition is edited, deleted, published, or reused.
- Provenance: who created it, source data, last refresh, confidence, and assumptions.
- Impact previews: affected reports, dashboards, generated artifacts, workflows, and collaborators.
- Safe publishing: draft, preview, compare, confirm, publish, rollback.
- Rule structures: values, channels/sources, filters, exceptions, and preview results.
- Mobile risk context: active account/entity, destination, amount/scope, fee/cost, trust reason, and recovery path.

## Adoption And Governance

One UI should be easy to trust and hard to accidentally bypass:

- Keep a changelog for token, component, and generation-context changes.
- Run design-system QA before handoff or merge, not only after implementation.
- Include design and engineering in foundation decisions, especially spacing, grids, type, icon, and component APIs.
- Maintain a support channel or owner path for unclear component usage.
- When a screen requires a deviation, document the gap and convert repeated deviations into the next One UI version.

## Drift Guard

When adding new UI, map it to the local `--ds-*` tokens first, then to any framework-specific tokens. If a component needs a new token, add it here before using one-off colors or radii.

For LLM-generated screens, components, layouts, modals, drawers, AI output blocks, and personalized workspaces, follow `UI_GENERATION_CONTEXT.md`. That file is the suite-level contract for context-aware UI generation and gold-standard consistency checks.

Run `npm run audit` from the One UI repo to check app token drift and inline CSS debt across the suite. Run `npm run audit:strict` once legacy inline styles are removed and future UI should fail closed.
