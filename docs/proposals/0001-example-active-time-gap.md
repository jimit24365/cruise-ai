```json
{
  "id": "0001",
  "title": "Illustrative example — tighten the active-time idle gap",
  "status": "draft",
  "authors": ["cruise_ai"],
  "opened": "2026-06-18",
  "decided": null,
  "summary": "Worked example of the proposal format (not an active change): shorten the active-time idle gap from 30 to 20 minutes.",
  "target_versions": {
    "methodology": "0.4.4 -> 0.5.0",
    "schema": null,
    "taxonomy": null
  },
  "changes": [
    {
      "param": "active_time.idle_gap_minutes",
      "ref": "cruise_ai/scoring.py — per-event gap-based active-time estimator",
      "current": "30",
      "proposed": "20",
      "rationale": "Illustrative only: a tighter gap would count fewer between-event minutes as active. Shown to demonstrate a current → proposed delta, not because the value should change."
    }
  ],
  "blast_radius": [
    "tests/test_engine_consistency.py — formula fingerprint would change",
    "cruise_ai/docs/SCORING-METHODOLOGY.md header + DERIVATIONS.md regenerate",
    "version bump: METHODOLOGY_VERSION (scan cache invalidates, full recompute)"
  ],
  "references": [
    "docs/REFERENCES.md — Newport (2016) Deep Work; Csikszentmihalyi (1990) Flow"
  ]
}
```

> **This is an illustrative example, not an active proposal.** It exists so
> the format, the index, and `compare` have something real to render. The
> 30-minute gap is a deliberate reasoned-default and is not under review.

## Motivation

The active-time estimator counts the minutes between two events as working
time only when the gap is under a threshold, so a single idle stretch does
not inflate hours. The threshold (30 min) is a reasoned-default, openly
versioned and listed among the open questions — exactly the kind of
constant a proposal exists to move deliberately rather than by accident.

## Detailed design

Change the idle-gap threshold used by the per-event active-time estimator
from 30 minutes to 20 minutes. Every gap between consecutive events longer
than the threshold is excluded from active time; a shorter threshold counts
strictly less time as active. The constant lives in `scoring.py` and is the
single input to the estimator — no other formula changes.

## Evidence

Directional, not load-bearing. The flow / deep-work literature
(`docs/REFERENCES.md`) frames *uninterrupted* engaged stretches as the
meaningful unit of working time, which is why a gap threshold exists at all;
it does not pin the exact minute count. Choosing 20 vs 30 is a calibration
question that real distributions of inter-event gaps should settle, which is
why this stays a reasoned-default until that data exists.

## Alternatives considered

- **Keep 30 (status quo).** The current default; fine until gap-distribution
  data says otherwise.
- **Per-tool thresholds.** More faithful but adds tunables and provenance
  surface; not worth it without evidence each tool's idle pattern differs.

## Risks & blast radius

Any change here moves measured hours, so it is a methodology event: the
formula fingerprint goes red until `SCORING-METHODOLOGY.md` is revisited,
`DERIVATIONS.md` regenerates, `METHODOLOGY_VERSION` bumps, and the bump
invalidates every cached scan (full recompute on next `assess`). Measured
history never regresses — the ledger supersedes via `max()`.

## Discussion

Left open by design: this is a teaching example. Delete or supersede it once
a real first proposal lands.
