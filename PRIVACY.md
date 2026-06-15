# Privacy

nextmillionai makes two promises. Both are literally true, enforced in
code, and tested in CI.

## The two promises

**1. Your code, sessions, prompts, scores, and narratives never reach
nextmillionai by default.** There is no server in the assessment path
and no silent upload. `calibrate`, `assess`, `report`, `enrich`, and
`export` run entirely on your machine. A CI test
(`test_no_outbound_network_calls`) fails the build if any module in the
assessment path gains an outbound network import.

**2. The assessment is computed entirely from local files on your
machine.** Your AI coding tool session metadata — Claude Code, Cursor, and
Codex first-class, plus a wider field of editors, CLIs, and local model
runtimes you opt into (the full list is in
[`DATA_COLLECTION.md`](DATA_COLLECTION.md)) — your local git history, and
(only if you opt in with `assess --code`) local repo metrics. Every score is arithmetic over counted local signals — no
model computes or changes a score.

## The one exception — and it is yours to take

The only way any data reaches a network is the explicit, opt-in
`nextmillionai publish`, and even then:

- **Derived and user-curated only.** What is sent is the same
  visibility-filtered shareable JSON used by `export`: the scores,
  tags, and narrative you chose to show. Never raw code, transcripts,
  or prompt text. Hidden projects, private growth areas, anti-patterns,
  trajectory, coverage, and experimental signals are stripped — and a
  verifier refuses to publish (rather than silently scrubbing) if
  private data is detected in the payload.
- **Confirmed, per field.** Your visibility config controls every
  section; the publish prompt lists exactly which sections will be
  sent and requires explicit confirmation. `publish --dry-run` shows
  the same without sending anything.
- **Revocable.** `nextmillionai unpublish` removes your record from
  the registry. The registry enforces this with a revoke token only
  you hold.
- **Validated on the receiving side too.** The registry re-checks every
  payload against the derived-only allowlist and rejects anything else.

There is no hosted nextmillionai registry today — the default registry
is one you (or anyone) self-hosts with `nextmillionai network serve`.
A hosted network is roadmap, and when it exists it will run this same
consent-gated protocol.

## Nuances we will not hide behind

- **Links are display-only.** If you add a GitHub/LinkedIn link to your
  identity config, it is shown, never fetched, and never scored.
- **Enrichment runs on *your* agent.** The optional narrative pass
  hands a prompt (real signals + bounded, secret-stripped session
  summaries — never raw prompt text) to the agent or API key *you*
  choose. If you use a cloud model, that content goes to *your*
  provider under *your* account — not to nextmillionai. The result is
  validated on ingest and never changes a score. Skip it entirely and
  a local heuristic writes the text instead.
- **The local server is localhost-only.** `report` binds to localhost,
  validates Host/Origin headers, and serves your own data back to you.
- **What the scanners read and skip** is itemized per source in
  [DATA_COLLECTION.md](DATA_COLLECTION.md). The experimental Claude
  Desktop source is off by default — even with `--yes` — because it is
  low-fidelity; it reads only install presence and MCP server names.
- **The code scan stores metrics, not code.** `assess --code` reads
  repo files locally and keeps only counts, names, and line totals.
  Its findings live under `experimental` and are never shareable.

## Where your data lives

Everything is in `~/.nextmillionai/` (override: `$NEXTMILLIONAI_HOME`).
Delete that directory and every trace of the assessment is gone.

This is the promise the closed alternatives broke. If you find any path
through this codebase that violates either promise, that is a security
bug: see [SECURITY.md](SECURITY.md).
