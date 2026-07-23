# Business Fit Map — Product & Methodology

**Status:** shipped (report-only) · v1
**Code:** `cruise_ai/business_fit.py` · rendered in the report's "AI engineering DNA" section
**Related:** `SCORING-METHODOLOGY.md` §10, `cruise_compare_to_role`

The Business Fit Map positions a builder in a 2D landscape of AI business
segments and shows **fit-to-segment** percentages.

## Placement: report-only

| Surface | Business Fit Map |
|---------|------------------|
| Report (`/report`) | **Yes** — inside "AI engineering DNA", toggled with the competency radar |
| Profile | No — the profile carries the positioning footprint (kinds × leverage), a different question |
| Shared/exported report | Yes — `businessFit` is shareable-class data (derived, fit-to-context) |

Segment fit is interpretive market context for a shareable artifact, not a
live identity widget. The profile answers *who you are*; the report's map
answers *where that profile tends to fit*.

## What "93% fit" means — two cautions

**1. Fit-to-context, never ranking.** Same output class as
`cruise_compare_to_role` (JD fit): your archetype profile compared to a
*segment definition*. Allowed: "your profile aligns 93% with this
segment's requirements," gap tables (required vs actual). Never allowed:
percentiles, leaderboards, "better than N% of builders," any
builder-vs-builder scalar.

**2. Every number traces to the signal chain.**

```
local sessions+git → normalized metrics → dimension scores
                   → archetype scores → map position + zone affinity
```

No hand-tuned per-user values. If a zone requirement or axis weight
cannot be explained from this chain, it does not ship.

## Formulas

**Map position** — archetype-weighted sums normalized to −1…+1.

X (AI-Augmented ↔ AI-Native):
`building = agent_builder×.25 + multi_agent_orchestrator×.10 + integration_architect×.25 + context_engineer×.20 + system_thinker×.20`
`using = rapid_prototyper×.30 + code_weaver×.25 + automation_engineer×.25 + cli_native×.20`
`x = (building − using) / 100`

Y (Velocity ↔ Precision):
`precision = code_weaver×.35 + automation_engineer×.30 + system_thinker×.20 + context_engineer×.15`
`velocity = rapid_prototyper×.40 + agent_builder×.30 + cli_native×.30`
`y = (precision − velocity) / 100`

**Zone affinity** — per segment requirement
`{archetypeId, minScore, weight}`:
`affinity% = round( Σ(min(actual/min, 1.0) × weight × 100) / Σ(weight) )`
Strong fit = every minimum met. Gaps list required vs actual.

**v1 amendment over the legacy spec:** `multi_agent_orchestrator`
post-dates the original formulas. It joins `building` (the most
AI-native signal; agent_builder rebalanced .35→.25) and the Autonomous
Agents zone requirements (weights rebalanced to sum 1.0). Each zone's
weights are asserted to sum to 1.0 in tests.

## Naming policy: categories, never companies

Zones carry **category examples** ("IDE copilots", "legal workflow AI") —
stable taxonomy labels. Specific company names are prohibited in zone
data, tooltips, and report copy: they age fast and read as implied
endorsement. Enforced by test (`test_no_company_names_anywhere`).

## Insufficiency

No scored archetypes → no map (`build_business_fit` returns `None`, the
section hides). A fabricated landscape is worse than an absent one.
