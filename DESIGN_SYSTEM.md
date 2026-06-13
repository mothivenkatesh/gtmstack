# Unified Product Design System

This app is part of the GTMstack / India Payments / Agentic Stack product suite. Product screens should share the same shell, type, card, control, and spacing rules while keeping their own accent color.

## Core Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--ds-font-sans` | Geist / Inter / system UI | All product UI text |
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
| `--ds-radius-control` | `8px` | Buttons, inputs, compact controls |
| `--ds-radius-card` | `12px` | Cards and product panels |
| `--ds-radius-pill` | `9999px` | Pills and status chips |

## App Accents

| App | Accent |
| --- | --- |
| GTMstack | `#6846E3` |
| India Payments | `#0070CC` |
| Agentic Stack | `#00AA45` |

Accent colors are for active nav states, primary actions, focused controls, charts, and product-specific badges. Do not use accent colors as the dominant page background.

## Product Shell

- Use a dark left sidebar on all app screens.
- Sidebar width should stay in the `212px` to `224px` range unless a screen has a strong data-density reason.
- Keep the main workspace light and dense.
- Use `14px` as the default product UI text size.
- Use `28px` for app page titles and `15px` to `16px` for card titles.
- Cards should be white with a 1px subtle border and 12px radius.
- Avoid heavy shadows; use shadows only to separate floating overlays or active hover states.

## Drift Guard

When adding new UI, map it to the local `--ds-*` tokens first, then to any framework-specific tokens. If a component needs a new token, add it here before using one-off colors or radii.
