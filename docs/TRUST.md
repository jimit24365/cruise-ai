# Trust & anti-gaming

What makes a nextmillionai report worth reading, what would be required
to fake one, and — stated plainly — what a self-hosted profile can and
cannot prove. No overclaim: every mechanism listed here exists in the
shipped code, with the module named.

## The honest frame first

A self-hosted profile is **self-attested** — like a résumé, it is
evidence presented by its owner. We do not claim "ungameable." What we
claim: gaming it requires *manufacturing months of realistic,
cross-consistent tool history*, which is a different class of effort
from typing a bigger number — and every mechanism below raises that
bar. Strong, *enforceable* verification belongs to the network /
reverse-hiring layer (**coming soon** — see "The verification layer"
below), not to a local tool.

## Anti-gaming mechanisms in the shipped code

**1. Scores are generated, never authored.** Every score is arithmetic
over counted local signals against research-anchored bands
(`scoring.py`; formulas published at `/methodology` and in
[SCORING-METHODOLOGY.md](../nextmillionai/docs/SCORING-METHODOLOGY.md)).
There is no field where a user types a score. The optional narrative
(`enrich`) is written by the user's own agent and is ingested into
narrative fields only — it structurally cannot change a number
(`enrichment.py`).

**2. Provenance and confidence are stamped on every output.** Each
assessment carries which sources fed it, the date range, the session
count, a 4-factor confidence score (completeness, sources, volume,
window — `build_confidence` in `aggregator.py`), the schema/taxonomy
versions, and the methodology version of the engine that computed it
(`assessment.methodology_version`). Per-adapter **fidelity** (deep /
counts / presence) is declared in Provenance — what couldn't be read is
said, not faked.

**3. Confidence scales with data, and gaps are visible.** Thin data
yields low confidence on the face of the report; unmeasurable signals
render *insufficient*, never an estimate (the one estimate-class
reading, solo-equivalent time, is labeled, banded, Lab-only, and never
shareable). Every assess prints a coverage report of what was NOT
collected.

**4. The same fact has one value, everywhere — and it's reproducible.**
Every derived field declares its inputs and recompute rule in
`signal_registry.py` (CI-enforced); cross-surface invariants and a
determinism test (`tests/test_engine_consistency.py`) guarantee that
the same inputs and engine produce identical output and that no two
sections of a profile can disagree. A doctored JSON that edits one
number will disagree with its own evidence strings, its calendar, and
its counterpart fields.

**5. Faking the inputs means faking an ecosystem.** Signals are
cross-corroborated across independent stores: session transcripts with
per-event timestamps, subagent run files, git commit history, Cursor's
own per-commit AI/human line attribution, and a durable local ledger
(`history.py`). Hours are gap-measured active time; parallelism needs
overlapping transcript timestamps; AI-authorship needs attribution
rows. Forging a strong profile means fabricating months of mutually
consistent logs across multiple tools' native formats — at which point
the forger has done more verifiable work than most résumés contain.

**6. Shared artifacts are redacted by allowlist and verified.**
`export`/`publish` pass through `build_shareable_profile()` plus a
verifier that *refuses* on private keys or filesystem paths — so a
shared report can't quietly include manufactured "extras" outside the
contract (`schema.py`, `export.py`).

## What a reader should check

On any nextmillionai report: the **confidence** number and its why; the
**date range and session count**; **Provenance** (sources + fidelity);
and the **evidence appendix** — every claim with its measured pointer.
A report with high scores, low confidence, and a thin appendix is
telling you something; the design makes that visible rather than
hideable.

## The verification layer (coming soon)

Enforceable verification lives in the network / reverse-hiring layer,
not the local tool:

- **Re-run on request:** a hiring agent asks; the builder re-runs
  `assess` locally and republishes — freshness proven by the engine
  stamp and recomputation, raw data never leaving the machine.
- **Server-side recompute from a derived evidence bundle:** the
  registry recomputes scores from the same derived-only counted
  signals the builder publishes — verifying arithmetic without ever
  seeing code, prompts, or transcripts.
- Device/identity binding tiers (declared → corroborated → key-signed)
  are on the post-launch roadmap.

Until that layer ships, treat a self-hosted profile as a
well-instrumented résumé: far more checkable than prose, still
self-attested.

## What we will NOT do

- **No server-side scoring in the local tool.** The assessment path
  never talks to a network (CI-enforced: `network.py` is the only
  outbound module, importable only from explicit publish/sync
  commands). We will not "verify" your profile by uploading it.
- **No pretending a local signing key proves authenticity.** A key on
  the same machine that produced the data attests nothing a forger
  couldn't also do; we won't ship theater.
- **No hidden telemetry, ever** — not even "for verification."
- **No estimating missing data to make a profile look complete.**
  Insufficient stays insufficient; that's the product.
- **No percentiles, cohorts, or ranks** that would make gaming
  zero-sum and lucrative. A map, not a ladder, is also an anti-gaming
  choice.
