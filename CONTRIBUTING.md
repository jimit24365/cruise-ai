# Contributing

## Prerequisites

- Python 3.9+
- Node 18+ (optional, for MCP server)
- pip

## Setup

```bash
git clone https://github.com/nextmillionai/nextmillionai.git
cd nextmillionai
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Branch naming

Use `<type>/<slug>` where type is one of:

- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation only
- `refactor` — code restructuring
- `test` — adding or updating tests
- `chore` — tooling, CI, dependencies

Examples: `feat/mcp-tool-support`, `fix/scoring-null-check`

## Parallel sessions — one git worktree per chat

Running more than one Claude Code (or any) session against this repo at
once? Give each its **own git worktree** so they never edit the same
checkout and conflict:

```bash
claude --worktree my-task      # CLI: starts the session in a fresh worktree + branch
```

The CLI has no foreground-default for this, so to make *every* bare
`claude` isolate itself, add a shell function to `~/.zshrc`:

```bash
claude() {
  if [ "$#" -eq 0 ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    command claude --worktree
  else
    command claude "$@"
  fi
}
```

The repo ships worktree settings (`.claude/settings.json` → `worktree`):
`baseRef: fresh` (branch from `origin/HEAD`), `symlinkDirectories` shares
`nextmillionai-mcp/node_modules` so worktrees don't re-install it, and
background sessions/subagents are worktree-isolated. Caveat: with
`symlinkDirectories` set, auto-cleanup can't remove a worktree — prune
manually with `git worktree remove --force <path>` (or `git worktree
list` / `prune`).

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add MCP tool support
fix: handle missing scan results gracefully
docs: update architecture diagram
```

## How to raise a pull request

1. **Fork** the repo and clone your fork (set up as above).
2. **Branch** off `main` with a `<type>/<slug>` name (see above):
   `git switch -c feat/zed-adapter`.
3. **Make the change.** Keep it focused — one concern per PR. If you
   touch a tool adapter, add a fixture test; if you touch a doc that's
   indexed in [CURRENT.md](CURRENT.md), update the index in the same
   commit (CI enforces it).
4. **Run the gates locally** (see below) until all four are green.
5. **Commit** with a [Conventional Commits](https://www.conventionalcommits.org/)
   message, then **push** to your fork.
6. **Open the PR** against `nextmillionai/nextmillionai:main`. Fill in the
   PR template (what / why / schema impact / tests). Link any issue
   with `Closes #123`.
7. **Review**: CI runs the four gates; a core owner reviews. Address
   feedback by pushing more commits to the same branch. Merges are
   **squash** — your local commit history can stay messy.

First time? The `good first issue` and `adapters` labels are the
easiest entry points, and a new tool adapter is the most-wanted
contribution.

## Pull requests

- No direct pushes to `main`.
- Every PR requires green CI and at least 1 review.
- Use squash merge.
- **Before any push or merge, run the dual pre-merge review** —
  [docs/PRE-MERGE-REVIEW.md](docs/PRE-MERGE-REVIEW.md): one engineering
  review + one product review, independent of the author, with every
  blocker/major finding fixed and pinned by a regression test first. The
  four gates prove the code runs; the reviews are what catch metric
  regressions, one-way doors, and docs that contradict shipped behavior.

## Local checks

Run these before opening a PR — the same four gates CI runs:

```bash
ruff check .
ruff format --check .
mypy nextmillionai --ignore-missing-imports
pytest
```

## Data contract

If your PR changes the shape of `profile.json` or `scan_results.json`, tag a
core owner (`@anshulixyz`) for review. See [ARCHITECTURE.md](ARCHITECTURE.md)
for details.

## Proposing a methodology change

The scoring methodology is a versioned contract
([SCORING-METHODOLOGY.md](nextmillionai/docs/SCORING-METHODOLOGY.md)) — we take
changes to it seriously, and we want them. Measuring *how* people build with AI
is a young field; it should evolve with evidence.

1. Open a thread in **Discussions → Methodology** describing the signal, band, or
   weight you'd change and *why*. Start from the
   [open questions](nextmillionai/docs/SCORING-METHODOLOGY.md#open-questions) if you
   aren't sure where to begin.
2. **Bring evidence** — a study, a dataset, a reproducible observation, or a good
   worked example. "It feels off" is a fine Discussion, not yet a PR.
3. If it converges, open a PR against `SCORING-METHODOLOGY.md` and `scoring.py`.
   Accepted changes are a **methodology-version bump** (the engine flags
   assessments computed on an older version), so the history of *why scores
   changed* is always public. The formula-fingerprint test keeps the doc and the
   code honest with each other.

Keep proposals **archetype-aware** and **non-ranking** — no model ever assigns a
score, and we never penalize a builder type for being a different builder type.
The scoring is calibrated for developers and AI engineers
([scope](nextmillionai/docs/SCORING-METHODOLOGY.md#who-this-is-calibrated-for));
proposals to widen that calibration are especially welcome, with the data to back
them.

## Adding a tool adapter

The most-wanted contribution. **Start with
[docs/ADDING-A-TOOL.md](docs/ADDING-A-TOOL.md)** — the end-to-end wiring
checklist (adapter → consent → displays → measurement → registries →
tests). An adapter that skips the consent wiring passes its own unit
tests but is silently never scanned in production; the checklist's test
gates make that failure loud.

The adapter *contract* — fidelity rules (deep / counts / presence —
declared honestly, never invented) and a no-code custom-adapter config —
is documented in [docs/ADAPTERS.md](docs/ADAPTERS.md). Fixture-based
tests live in `tests/test_adapters/` — copy `test_kiro.py` (first-class)
or one from `test_local_tools.py` (wider-field) as a template.
