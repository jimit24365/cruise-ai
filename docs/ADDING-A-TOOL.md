# Adding a tool integration

The end-to-end workflow for wiring a new AI coding tool into
cruise_ai — adapter, consent, displays, measurement, truth
registries, docs, and the tests that hold it all together.

**Why this doc exists:** an adapter that passes its own unit tests can
still be dead in production. The consent gate in
`cruise_ai/adapters/_registry.py` skips any adapter whose consent
group isn't a real consent key — silently. This checklist is ordered so
each step is verified before the next, and the test gates fail loudly
between the steps where that silence used to live.

Read [`docs/ADAPTERS.md`](ADAPTERS.md) first for the adapter *contract*
(what an adapter may read, fidelity rules); this doc is the *wiring
workflow* around it.

## Step 0 — Decide the tier and consent group

| Question | Answer → path |
|---|---|
| Does the tool store real sessions (boundaries + timestamps) you can parse? | Yes → fidelity `deep`. No → `counts` (countable artifacts) or `presence` (install only). |
| Is it a major surface deserving its own consent question? | Yes → **first-class** (own consent key, like `claude_code`/`cursor`/`codex`/`kiro`). No → **wider-field** (shares the one `other_tools` consent question, like Aider/OpenCode/Zed). |

Rules that never bend (see `docs/ADAPTERS.md` "Standing rules"):
local files only, read-only, no subprocess to the tool, no network
(CI-enforced); fidelity is declared, never invented; counts/presence
sources never invent sessions and never move scores.

A first-class tool's raw payload still lives under `otherTools.<id>` in
`scan_results.json` — "first-class" means *own consent question + deep
fidelity*, not a new top-level schema key. Never change `schema.py` /
`docs/SCHEMA.md` as a side effect of adding a tool.

## The wiring workflow

Steps 1–2 are all a **wider-field** tool needs. **First-class** tools
continue through step 9.

### 1. The adapter

- **Wider-field:** add a class to `cruise_ai/adapters/local_tools.py`
  and register it in `get_local_tool_adapters()`. Done — consent
  (`other_tools`), coverage, and history all flow automatically. Update
  the `other_tools` description in `consent.py ALL_SOURCES` +
  `_DISCLOSURE_BLOCKS` to name the tool, add the
  `methodology_spec.TOOL_COVERAGE` widerField entry (step 7), docs
  (step 8), and a fixture test in
  `tests/test_adapters/test_local_tools.py`.
- **First-class:** new module `cruise_ai/adapters/<tool>.py`
  producing `Session` objects (`adapters/_base.py`). Conventions:
  - `Session.tool` is the adapter's `name` — every downstream rollup
    keys on it.
  - Never read prompt/response text content — counts, tool names, and
    timestamps only. Word counts are computed in-stream and the text
    dropped.
  - `extras` keys the aggregator understands:
    `is_subagent` + `parent_session_id` (orchestration via child
    sessions — parents get task-dispatch credit automatically),
    `mcpToolCalls` (declare MCP calls yourself if you know the tool's
    builtin names — keep a `<TOOL>_BUILTIN_TOOLS` frozenset in the
    adapter), `source: "ide"` (marks non-CLI generations).
  - `raw_data()` returns a dict with `"label"` and `"fidelity"` keys —
    without them, provenance downgrades the tool to `counts`.
  - Skip empty sessions (`user_msgs == 0 and assistant_msgs == 0`).

  **Verify:** fixture unit tests in `tests/test_adapters/test_<tool>.py`
  (copy `test_kiro.py` as the template — synthetic fixture dirs, never
  real ones).

### 2. Path constants in `cruise_ai/scanner.py`

Path constants live in `scanner.py` (repo convention — see
`CLAUDE_PROJECTS_DIR`, `CODEX_SESSIONS_DIR`, `KIRO_SESSIONS_DIR`), NOT
in the adapter module. The adapter late-binds them
(`import cruise_ai.scanner as scanner_mod` inside `__init__`) so
test monkeypatching reaches even a bare `<Tool>Adapter()`.

Also add a detection block to `scanner.list_tools()` so
`cruise_ai --tools` shows the tool.

**Verify:** `python3 -m cruise_ai --tools` lists it.

### 3. Register in `adapters/_registry.py`

- Instantiate in `get_session_adapters()` passing the scanner constants.
- Add `"<tool>": "<tool>"` to the module-level `_CONSENT_KEYS` map.

**Verify:** the consent-registry completeness gate
(`tests/test_adapters/test_registry.py::TestConsentRegistryCompleteness`)
now **fails** — by design. An adapter whose consent group isn't in
`consent.ALL_SOURCES` is silently never scanned; the gate stays red
until step 4 closes the loop.

### 4. Consent in `cruise_ai/consent.py`

- Add the key to `ALL_SOURCES` (path summary as the description).
- Add a `Read:/Derived:/Never:` paragraph to `_DISCLOSURE_BLOCKS`
  (same key). It must match what the adapter actually reads — this is
  the promise the user consents to.
- Add to `OPT_IN_ONLY_SOURCES` only if the source is experimental /
  low-fidelity (then it defaults OFF even under `--yes`).

Everything else is automatic: the calibrate prompt loop iterates
`ALL_SOURCES`; `default_enabled_sources()` picks up the key; existing
users get a **mini-prompt for just the new source** on their next
interactive run (`_ensure_calibrated`) — never silently enabled, never
silently persisted off.

**Verify:** completeness gate green; `cruise_ai calibrate` asks the
new question; with a pre-existing consent file, `assess` asks only the
new source.

### 5. Display + coverage surfaces

| Surface | File / map | What to add |
|---|---|---|
| Coverage report + "widen" knob | `aggregator.py` `_SOURCE_LABELS` | `"<tool>": "<Label>"` — without it the tool never appears in coverage |
| Coverage rollup exclusion | `build_profile.run_scan` (`detected["other_tools"]` + `coverage_raw["other_tools"]`) | exclude the tool's id (own consent key ⇒ own row, not the other_tools rollup) |
| Assess summary / `--preview` | `build_profile.show_preview` | a per-source block reading `otherTools.<id>` |
| `sources` command detail | `build_profile.cmd_sources` | an `elif adapter.name == "<tool>":` detail block (the consent map is shared from `_registry._CONSENT_KEYS` — nothing to copy) |
| Display names | `build_profile` `surfaces` + `_tool_labels` | `"<id>": "<Label>"` |
| Live watcher | `live.py` candidates list | `("<id>", <sessions path>)` |

### 6. Measurement — usually nothing to do

`scoring.py` is tool-name-blind and **must never be touched** (the
formula fingerprint pins it; changing it is a methodology version bump,
not a tool integration). Deep session sources feed the measured metrics
automatically through two tool-agnostic folds in `aggregator.py`:

- `fold_session_metrics` — prompt/turn averages, terminal commands, MCP
  calls, models, tool counts, from every non-claude/cursor `Session`.
- `attribute_subagent_dispatches` — orchestration credit from
  `is_subagent`/`parent_session_id` child sessions.

Only extend the classification sets when names differ:
`_TERMINAL_TOOL_NAMES` (what counts as "ran a terminal command"),
`_CLI_AI_SURFACE_TOOLS` (is this a CLI AI surface?). If your tool's
session metrics are already derived from its raw dict in
`scanner.compute_normalized` (only claude/cursor today), add its tool
name to `_RAW_METRIC_TOOLS` instead — folding it too would double-count.

### 7. Truth registries

- `methodology_spec.py` `TOOL_COVERAGE`: add the entry (id, label,
  tier, reads). Gate: `tests/test_tool_coverage.py`.
- `signal_registry.py`: if the tool's sessions now feed a derived field,
  add `"<tool>.sessions"` to `SOURCES` and to that field's `inputs`.
  **This is a hardline** (`docs/HARDLINES.md` §2 — inputs are a field's
  definition): get the owner's explicit confirmation first and say so in
  the commit message.
- `methodology_spec.py`: if a metric's tool scope changed, update its
  `basis` (and `derivation`) strings in METRICS too — **that registry,
  not signal_registry, is what renders on the served `/methodology`
  page**. A stale "Claude Code only" basis there contradicts the shipped
  measurement two sections away from the tool-coverage table.
- Regenerate: `python3 scripts/render_methodology_registry.py` and
  commit `DERIVATIONS.md` if it changed. Gate:
  `tests/test_methodology_doc.py`.

### 8. Docs (same commit as the code they describe)

- `DATA_COLLECTION.md`: a per-source table — what is read / derived /
  never touched. Must match the adapter and the consent disclosure.
- `docs/ADAPTERS.md`: paths, generations, reads, derives, notes.
- `README.md` + `CURRENT.md` one-liners (tool lists).
- Any **new** doc file must be registered in the `CURRENT.md` doc index
  table — enforced by
  `tests/test_docs_truth.py::test_every_doc_is_in_the_current_md_index`.

### 9. Tests

- `tests/conftest.py`: an autouse guard redirecting the new scanner
  path constants to nonexistent tmp paths — tests must never read the
  developer's real stores (hardline §3).
- Per-adapter fixture suite (step 1).
- Extend `TestConsentDerivedScan` in
  `tests/test_adapters/test_registry.py`: consent-derived
  `run_adapters` yields the tool's sessions; toggling its key off
  suppresses them. Unit tests that call the adapter directly bypass the
  consent gate — this is the test that exercises it.

## The four verify gates (all must be green)

```bash
python3 -m pytest tests/ -q -p no:cacheprovider --override-ini addopts=
uv tool run ruff check cruise_ai/ tests/ && uv tool run ruff format --check cruise_ai/ tests/
uv run --python 3.12 --with mypy --no-project -- python -m mypy cruise_ai --ignore-missing-imports
python3 scripts/formula_fingerprint.py   # must be UNCHANGED
```

Plus an end-to-end pass with synthetic data in a sandbox `$HOME`:
`assess --yes` counts the tool's sessions, `--tools`/`sources`/coverage
show it once (no double-report), the served `/profile` and `/report`
render, and a grep of `~/.cruise_ai/data/` proves no prompt text,
titles, or secrets leaked into the artifacts.

## Worked example

Kiro (first-class, deep, CLI + IDE generations, subagent orchestration,
adapter-declared MCP calls) — see the `feat/kiro-integration` PR for a
commit-by-commit template of every step above, including the
consent-wiring failure mode this workflow exists to prevent.
