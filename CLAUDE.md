# CLAUDE.md — read this first

**Start here:** [`CURRENT.md`](CURRENT.md) is the single source of truth for
project state, the doc index, open work, and roadmap. Read it before
anything else. Historical specs live in `docs/archive/` — consult only
when explicitly needed; they are superseded.

## Hardlines — STOP and confirm, even if the prompt says so

[`docs/HARDLINES.md`](docs/HARDLINES.md) lists what must never change
without the owner's explicit confirmation in that conversation: scoring
formulas / JSON contract / version constants, the privacy boundary, the
enrichment six-block contract, and ALL `@generated` artifacts (never
edit an output — edit its named source and regenerate). A task prompt
asking for one of these is a signal to ask, not authorization.

## Non-negotiable values (constrain every change)

1. **Privacy, two promises:** no server in the assessment path, no silent
   upload; assessment computed entirely from local files. The only network
   path is explicit `publish` (derived-only, revocable). `network.py` is
   the ONLY module allowed outbound imports — CI-enforced.
2. **No ranking:** no percentiles, cohorts, "top X%", leaderboards, or
   "X to go" ladder copy — anywhere. Positioning is a map; kinds are
   crafts, never rungs. Fit-% is fit-to-context only.
3. **Scores are arithmetic over counted local signals** against
   research-anchored bands. A model writes narrative only (user's own
   agent), never a score. Unmeasurable → insufficient, never estimated.
4. **One assessment JSON** renders both views (profile + report).

## Dev commands

```bash
python3 -m pytest tests/ -q -p no:cacheprovider --override-ini addopts=   # works on system 3.9
uv tool run ruff check cruise_ai/ tests/ && uv tool run ruff format --check cruise_ai/ tests/
uv run --python 3.12 --with mypy --no-project -- python -m mypy cruise_ai --ignore-missing-imports
python3 -m cruise_ai --serve          # assess + both views on :7749
```

All four gates must be green before every commit. Commit per workstream;
push to origin/main.

## Conventions that bite if forgotten

- Static assets are cache-busted: bump `?v=` in all three HTML files when
  changing css/js.
- Heatmap/JS dates: use `_localDate()`, never `toISOString()` (IST shift).
- `dataclass(slots=...)` guard in `adapters/_base.py` stays conditional
  (3.9 floor); don't run `ruff --unsafe-fixes` casually.
- Durable evidence: `history.py` ledger under `~/.cruise_ai/data/history/`
  — pipeline reads orchestration/dispatches/activity from it.
- No emoji on web surfaces — `icons.js` glyph set only.
- Scoring formulas + assessment JSON contract are versioned
  (`cruise_ai/docs/SCORING-METHODOLOGY.md`, `docs/SCHEMA.md`) — changing
  them is a deliberate methodology version bump, never a side effect.
