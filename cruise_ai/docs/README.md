# `cruise_ai/docs/` — engine contract docs

The versioned contracts the scoring engine is built against. These are the
source of truth for the assessment JSON and the methodology; changing them is a
deliberate version bump, never a side effect (see
[`../../docs/HARDLINES.md`](../../docs/HARDLINES.md)).

| File | What it is |
|---|---|
| [`SCORING-METHODOLOGY.md`](./SCORING-METHODOLOGY.md) | Every scoring formula and band, with provenance — served at `/methodology`. |
| [`SCHEMA.md`](./SCHEMA.md) | The one assessment JSON contract + the shareable/private field map. |
| [`methodology/DERIVATIONS.md`](./methodology/DERIVATIONS.md) | `@generated` per-metric reference (logic + reasoning + provenance + citations) from the methodology registry. Never edit by hand — edit `cruise_ai/methodology_spec.py` and regenerate. |

For the product overview and quickstart, see the top-level
[`README.md`](../../README.md). For the full docs map (what every doc is for),
see [`../../docs/README.md`](../../docs/README.md).
