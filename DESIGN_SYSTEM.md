# Unified Product Design System

One UI is the shared design system for the GTMstack / India Payments / Agentic Stack product suite. Product screens should share the same shell, type, card, control, and spacing rules while keeping their own accent color.

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
| `--ds-accent` | app-specific | Primary actions and active states |
| `--ds-accent-soft` | app-specific tint | Focus rings and selected surfaces |
| `--ds-status-*` | info / success / warning / danger | Semantic status text and soft backgrounds |
| `--ds-focus-ring` | `0 0 0 3px var(--ds-accent-soft)` | Focus and selected control outlines |
| `--ds-shadow-card` | subtle 1px shadow | Optional card separation |
| `--ds-shadow-overlay` | larger overlay shadow | Modals, drawers, popovers |

## App Accents

| App | Accent | Soft accent |
| --- | --- | --- |
| GTMstack | `#6846E3` | `#F0EBFF` |
| India Payments | `#0070CC` | `#F2F9FF` |
| Agentic Stack | `#00AA45` | `#ECFDF3` |

## Product Shell

- Use a dark left sidebar on all app screens.
- Sidebar width should stay in the `212px` to `224px` range unless a screen has a strong data-density reason.
- Keep the main workspace light and dense.
- Use the `--ds-space-*` scale for spacing. Default to a 4px base grid and avoid arbitrary one-off padding values.
- Use `14px` as the default product UI text size.
- Use `28px` for app page titles and `15px` to `16px` for card titles.
- Cards should be white with a 1px subtle border and 12px radius.
- Avoid heavy shadows; use shadows only to separate floating overlays or active hover states.

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

## Drift Guard

When adding new UI, map it to the local `--ds-*` tokens first, then to any framework-specific tokens. If a component needs a new token, add it here before using one-off colors or radii.

For LLM-generated screens, components, layouts, modals, drawers, AI output blocks, and personalized workspaces, follow `UI_GENERATION_CONTEXT.md`. That file is the suite-level contract for context-aware UI generation and gold-standard consistency checks.

Run `npm run audit` from the One UI repo to check app token drift and inline CSS debt across the suite. Run `npm run audit:strict` once legacy inline styles are removed and future UI should fail closed.
