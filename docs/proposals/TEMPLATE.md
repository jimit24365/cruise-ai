```json
{
  "id": "NNNN",
  "title": "<imperative one-line title>",
  "status": "draft",
  "authors": ["<your name>"],
  "opened": "YYYY-MM-DD",
  "decided": null,
  "summary": "<one-sentence summary of the change>",
  "target_versions": {
    "methodology": "<live> -> <next>",
    "schema": null,
    "taxonomy": null
  },
  "changes": [
    {
      "param": "<module.param>",
      "ref": "<file / section it lives in>",
      "current": "<live value>",
      "proposed": "<new value>",
      "rationale": "<why this value>"
    }
  ],
  "blast_radius": [
    "<tests touched, e.g. formula fingerprint>",
    "<docs to regenerate>",
    "version bump: <which constant>"
  ],
  "references": [
    "docs/REFERENCES.md — <study>"
  ]
}
```

> This is the proposal template — not a live proposal. Copy it with
> `python3 scripts/proposals.py new "<title>"`, which assigns the next id,
> stamps the date, and seeds the live version base for you.

## Motivation

What problem with the current value or formula prompts this, and why now.

## Detailed design

The exact change — formula, band, weight, or constant — before and after.
Reference the precise code site so a reviewer can find it in one hop.

## Evidence

The research or measured data behind the proposed value. Tie to
`docs/REFERENCES.md` where possible; mark directional vs load-bearing
honestly. Reasoned-default constants should say so.

## Alternatives considered

Other values or approaches, and why they lose.

## Risks & blast radius

What breaks or shifts: tests (especially the formula fingerprint in
`tests/test_engine_consistency.py`), docs to regenerate (DERIVATIONS.md,
SCORING-METHODOLOGY.md header), the version bump, and the scan-cache
invalidation that a methodology bump triggers.

## Discussion

Open questions and notes captured during review. The proposal stays
`under-review` until this resolves; landing it is a separate, deliberate,
signed-off commit per `docs/HARDLINES.md` §6.
