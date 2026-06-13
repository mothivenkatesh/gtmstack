# One UI Research Notes

These notes translate five product-design case studies and their reachable visual assets into One UI rules for generated interfaces. The detailed image-by-image coverage summary lives in `VISUAL_RESEARCH_AUDIT.md`.

## ScaleXP: Automated Time-Series Reports

Source: https://suwardhan.com/scalexp

Visual assets inspected: report screenshots, column configuration, row computation editor, customer-research notes, iteration boards, process timeline, final designs, and 4px specs.

Relevant lessons:

- Finance and executive reporting UIs need flexible columns because companies compare actuals, targets, forecasts, countries, entities, and reporting standards differently.
- Metric definitions should be reusable library objects, not one-off chart calculations.
- Complex metrics need explicit order of operations. Treat them as trees or dependency graphs instead of flat rows.
- Dense edit modes can use horizontal, scan-first layouts when users compare many columns or periods.
- A 4px base grid is a good default for dense operational UI.

One UI implications:

- Give metrics, portfolios, rules, prompts, and saved searches first-class definition screens.
- Show calculation structure, dependencies, source, owner, and last updated metadata.
- Use tables and compact panels for repeat work; use cards only for bounded modules or repeated entities.
- Let generated UI show actual vs target/forecast and entity breakdowns without inventing new component geometry.

## Clarisights: Custom Dimensions

Source: https://suwardhan.com/clarisights

Visual assets inspected: custom-dimension tables, expanded rows, color-coded rules, final listing UI, old listing UI, dependency modal, specs, SVG rule/table fragments, and rollout feedback. Two source assets were broken on the page and are recorded in `VISUAL_RESEARCH_AUDIT.md`.

Relevant lessons:

- Analytics systems become hard to use when critical details are hidden behind too many clicks.
- Redundant filters and scattered rule structure create maintenance debt.
- Edits to shared definitions need dependency visibility before publishing.
- Listing pages should expose values, sources/channels, filters/rules, and dependencies with minimal navigation.
- Error copy, automatic level assignment, and color-coded rules reduce cognitive load.

One UI implications:

- Prefer `Definition -> Value -> Rule -> Filter/Source` information architecture for reusable segmentation systems.
- Use dependency modals or drawers before global edits, deletes, publishes, or regenerations.
- Surface dependent dashboards, reports, generated UI, owners, and last-used timestamps.
- Use tokenized semantic colors for rule status and validation, not local color palettes.

## Gold-Standard LLM Behavior

When generating UI for complex systems, an LLM should:

- Ask what reusable definition is being created or edited.
- Identify downstream dependencies before proposing a destructive or global action.
- Use classes and tokens instead of inline CSS.
- Include empty/loading/error/success/warning states.
- Show evidence, recency, confidence, source, and assumption metadata for AI or analytics output.
- Prefer dense, scan-first product layouts over decorative marketing layouts.

## Leap: Web3 Wallet Mobile App

Source: https://suwardhan.com/leap

Visual assets inspected: mobile concept screens, information architecture, trust/seed phrase import screen, connect-wallet bottom sheet, portfolio, send, asset detail, staking, proposal, and App Store feedback.

Relevant lessons:

- Mobile apps need their own information architecture, not a compressed extension or desktop view.
- High-risk actions need visible trust and security explanation before the user commits.
- Power users still need compact, repeatable paths for assets, transfers, staking, governance, and activity.
- A component library is essential because the same mobile patterns repeat across portfolio, send, connect, stake, proposal, and asset-detail screens.

One UI implications:

- Use sticky mobile context bars, dark bottom navigation, safe-area-aware actions, and 44px tap targets.
- Keep active entity/account/workspace context visible near the top of the flow.
- Put trust/security/saved-state explanation beside sensitive generation, connection, publishing, or deploy actions.
- Prefer compact cards and bottom sheets to full desktop panels on mobile.
- Repeat sensitive details on a review screen before commit: account, destination, amount/scope, fee/cost, generated output, or affected workflow.

## Smartbeings: Conversation Flow Builder

Source: https://suwardhan.com/smartbeings

Visual assets inspected: information architecture, domain assets, empty state, intent modal, 3-column interface, node configuration, response configuration, branching, sample flows, and testing/error states.

Relevant lessons:

- Complex flow builders work best when assets, flow canvas, and configuration/testing stay visible in one place.
- Domain assets such as nodes, intents, entities, and code blocks should be one click away while building.
- Node types need visual distinction; branch conditions and node errors must be visible at the point of work.
- If no node is selected, the configuration area can become a live testing panel.
- Clear empty states and guided help reduce onboarding friction.

One UI implications:

- Use a three-pane desktop builder: assets rail, central journey canvas, configuration/testing panel.
- Use a progressive mobile builder: flow first, then selected node details and testing.
- Show node-level errors on cards and flow-level errors near deploy/recommend/publish.
- Let users test or preview without leaving the builder context.
- Keep branch conditions attached to branch nodes, and keep assets one click away while editing.

## Recko: Building A Design System

Source: https://suwardhan.com/18531115

Visual assets inspected: principles, UI audit, spacing, layout, grid behavior, 12-column grid, margins/gutters, type scale, font alignment, icon guidelines, color palette, component boards, state matrices, documentation, adoption, and chronology.

Relevant lessons:

- A design system should start with product principles and a UI audit, not with isolated components.
- The UI audit should inventory every UI element, variation, page layout, typeface, icon, and color.
- Foundation order matters: spacing, layout/grid, type scale, color, then icon library.
- A 4px base scale keeps margins, paddings, and component sizes consistent.
- A 12-column content-area grid gives flexible 2/3/4-column layouts while fixed sidebars remain outside the content grid.
- Type scale must pair font size with line height; line-height grids are easier to implement than baseline grids.
- Components need explicit state matrices, including enabled, focus, hover, active, loading, and disabled.
- Adoption depends on trust: communication, inclusive decisions, quick support, design-system QA, and changelog visibility.

One UI implications:

- Keep a living audit and use it to prioritize components.
- Add layout/grid and type/line-height tokens, not only color/radius tokens.
- Document component anatomy, states, edge cases, and token mapping before calling a component complete.
- Treat deviations as backlog for the next One UI version instead of allowing silent one-off overrides.
- Run design-system QA before handoff or merge.

## Cross-Source Synthesis

Use this synthesis when deciding whether a generated UI is good enough:

- Web apps: choose dense, scannable layouts for repeated work. Tables, lists, row expansion, and quiet actions beat oversized cards.
- Mobile apps: use native-feeling one-task flows with sticky context, safe-area actions, bottom sheets, and trust states.
- Builders: preserve context. Assets, canvas, selected-node configuration, tester, node errors, and publish status should stay in the same workflow.
- Design systems: start with principles and an audit, then tokens, components, state matrices, documentation, and adoption rituals.
- AI UI: make the model's context visible. Show sources, assumptions, confidence, recency, dependency impact, and human override.
