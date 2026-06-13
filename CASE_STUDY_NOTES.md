# One UI Research Notes

These notes translate two complex B2B product-design case studies into One UI rules for generated interfaces.

## ScaleXP: Automated Time-Series Reports

Source: https://suwardhan.com/scalexp

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
