# DEEP-FIDELITY.md — the plan to take more tools from `counts` to `deep`

Directional plan, not a contract. The fidelity tiers themselves are
defined in [`docs/ADAPTERS.md`](ADAPTERS.md) (the canonical coverage
contract); this doc is the roadmap for *raising* a tool's tier without
ever faking what the tool doesn't expose.

## What `deep` requires

A tool earns the `deep` tier only when three things are readable from its
**local** files (no network, no account):

1. **Session boundaries** — one identifiable unit per conversation/run.
2. **Real timestamps** — start (and ideally end) from the tool's own data,
   not just file mtime. (mtime is reserved for user-registered custom
   adapters, which declare `timestampFidelity: mtime`.)
3. **Per-role message counts** — user vs assistant turns.

Anything short of all three stays honest at its real tier:

- `counts` — countable artifacts (files, rows) but no parseable sessions;
  we count, we never invent. No `Session` objects are emitted.
- `presence` — only install/config is detectable.

The rule that never bends: **unmeasurable is `insufficient`, never
estimated.** A tier is a promise about evidence, not an aspiration.

## Current `counts` / `presence` tools — per-tool path

Ordered by feasibility (most achievable first).

### Antigravity (`counts` → `deep`) — most feasible

Trajectories are per-session Protobuf files at
`~/.gemini/antigravity/conversations/*.pb`, with plan/walkthrough "brain"
artifacts under `~/.gemini/antigravity/brain/` and a `state.vscdb` UI index.

- **Step 1 (low risk, no protobuf):** emit one `Session` per `.pb` file —
  boundaries + timestamps from the brain dir / file mtime, project from
  `workspaceStorage`. This already lifts the timeline above `counts`;
  message counts remain absent (documented).
- **Step 2 (full `deep`):** walk the protobuf at the wire level (stdlib
  only — varint + length-delimited tags; no `.proto` needed) to count
  user/assistant turns. Medium effort, brittle to schema changes —
  version-guard it and fall back to Step 1 on any parse miss.

### Cody (`counts` → `deep`) — moderate

Chat lives in `globalStorage/sourcegraph.cody-ai/`. Where a build keeps
readable JSON chat history, parse roles + timestamps; where it is
account-coupled / server-side, it stays `counts` honestly. Blocked on a
fixture from a real install to pin the on-disk format.

### JetBrains AI (`presence` → `counts`, maybe `deep`) — hard

Chat is not reliably on disk in a parseable form today. The near-term win
is `presence` → `counts` (count whatever local artifacts exist). True
`deep` likely needs a JetBrains-side export feature.

### Windsurf (`counts`) — leave as-is for now

The Cascade store is a deliberately opaque binary blob; reverse-engineering
it is brittle and would break per release. Same Codeium lineage as
Antigravity — revisit only if the Antigravity protobuf reader lands and
generalizes.

## Reusable infrastructure (do once, reuse everywhere)

Each of these lowers the cost and risk of every future deep adapter:

1. **Stdlib protobuf wire-reader** in `adapters/` — a varint +
   length-delimited tag walk that needs no `.proto`. Unlocks Antigravity
   and any future protobuf-backed tool.
2. **Shared SQLite-introspection helper** — promote the tolerant
   table/column finder written inline for the OpenCode adapter
   (`adapters/local_tools.py`, `OpenCodeAdapter._scan_sqlite`) into a
   reusable function: find a session-like table + message-like table,
   resolve timestamp/role/session-id columns across naming drift. Reused by
   any DB-backed tool (Cody and others).
3. **Fixtures-from-real-installs** convention under
   `tests/test_adapters/fixtures/` — every new format pinned by a committed
   sample (never live data; `tests/conftest.py` guards real stores). A new
   storage generation ships with its fixture or it doesn't ship.

## Definition of done for a tier upgrade

A PR raising a tool's tier must:

- parse real session boundaries + timestamps + message counts from local
  files (for `deep`);
- declare the new tier in the adapter's `raw_data()` (`fidelity` + `note`);
- update the tier in `methodology_spec.TOOL_COVERAGE` (the
  `tests/test_tool_coverage.py` guard asserts declared tier == adapter
  fidelity);
- add a fixture test exercising the format;
- update [`docs/ADAPTERS.md`](ADAPTERS.md), `DATA_COLLECTION.md`, the
  consent disclosure, and the UI tool-label maps in the same commit.
