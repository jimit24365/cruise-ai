# cruise-ai Project Context

## What This Is

cruise-ai is a self-driven AI developer coaching tool. It observes how you use AI coding tools (Kiro, Claude Code, Cursor, Codex) and recommends improvements — without using LLMs, purely through rule-based analysis of counted signals.

**Repo:** https://github.com/jimit24365/cruise-ai  
**Origin:** Built on top of [nextmillionai](https://github.com/nextmillionai/nextmillionai) by @anshulixyz (credited in README + LICENSE)  
**Package:** `cruise_ai` (import) / `cruise-ai` (pip/CLI)  
**Home dir:** `~/.cruise-ai/`  
**Config:** `cruise-ai.config.json`  
**Env vars:** `CRUISE_AI_HOME`, `CRUISE_AI_VERBOSE`, `CRUISE_AI_PROFILE_PATH`, `CRUISE_AI_NO_BROWSER`

## Architecture

```
cruise_ai/
├── recommendations/        # OUR ADDITION — the coaching engine
│   ├── types.py            # Recommendation dataclass + CONFIDENCE_THRESHOLD
│   ├── engine.py           # Orchestrator: runs detectors, feedback adjust, gate, sort
│   ├── analytics.py        # Usage/Cost/Timeline dashboards
│   ├── token_optimization.py  # Duplicate context, long prompts, model routing
│   ├── skills.py           # Tool patterns, co-occurrence, skill generator
│   ├── project_memory.py   # Repeated context, cross-session patterns
│   ├── learning.py         # Teach Me / Why This? / tutorials
│   ├── feedback.py         # User feedback storage + confidence adjustment
│   ├── fingerprint.py      # Opt-in SHA-256 duplicate detection
│   └── longitudinal.py     # Pre/post metric tracking
├── adapters/               # Data collectors (Kiro, Claude Code, Cursor, Codex, git, etc.)
├── scoring.py              # Dimension scoring (untouched — fingerprint-pinned)
├── aggregator.py           # Signal computation
├── build_profile.py        # CLI entry point + all commands
├── static/                 # Vanilla HTML/CSS/JS UI (served at localhost:7749)
│   ├── profile.html
│   ├── report.html
│   ├── howitworks.html
│   └── js/, css/
├── hub.py                  # HTTP server (serves /api/* + static pages)
└── paths.py                # All path constants
```

## CLI Commands (Our Additions)

```bash
cruise-ai recommend [--category <cat>] [--json] [--min-confidence N]
cruise-ai dashboard [--json]
cruise-ai teach [topic]
cruise-ai feedback [acted|dismissed|useful|not_useful] --action-type <type>
```

## Key Design Decisions

- **No LLMs** — all recommendations are predefined rules over counted signals
- **Privacy** — never reads prompt text, only counts/tool names/timestamps
- **trust_level** on every recommendation: validated, observed, heuristic, experimental
- **Feedback loop** — dismissed recs suppressed, confidence adjusted from user feedback
- **Confidence gate** — only show recommendations with confidence ≥ 60%
- **Never touch scoring.py** — formula fingerprint is pinned, scoring is the upstream's domain

## Tests

```bash
python3 -m pytest -o "addopts=" -q   # Run all (currently 746 pass)
python3 -m pytest tests/test_recommendations.py  # Just our recommendation tests (30)
```

## What's Done

- ✅ Full rebrand from nextmillionai → cruise_ai
- ✅ P0 recommendation engine (5 categories, 30 tests)
- ✅ CLI commands: recommend, dashboard, teach, feedback
- ✅ Trust infrastructure: TRUST-MODEL.md, CALIBRATION.md, feedback, fingerprint, longitudinal
- ✅ Solution documentation (6 docs with mermaid diagrams)
- ✅ Feature roadmap (ROADMAP.md)

## What's Next (Priority Order)

1. **Web UI Integration** — API endpoints + HTML pages for recommend/dashboard/feedback
2. **P1 features** — Prompt Compression, Cached Context, Skill Revision, MCP Recommendation
3. **Real data validation** — Run against actual ~/.kiro sessions and validate recommendations
4. **Hook Automation** — Detect repetitive commands → generate git/PR hooks
5. **Eval Harness** — Detect evaluation opportunities

## UI Integration Plan (Next Session)

The existing UI is vanilla HTML/JS served from `cruise_ai/static/`. Backend serves JSON at `/api/*`.

Steps:
1. Add API routes in `hub.py`:
   - `GET /api/recommend` → JSON array of recommendations
   - `GET /api/dashboard` → dashboard data
   - `POST /api/feedback` → record feedback
2. Add `static/recommend.html` — cards UI matching existing design
3. Add `static/dashboard.html` — usage/cost/model charts
4. Add navigation tab for the new pages
5. Wire feedback buttons on recommendation cards

## Conventions

- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`)
- **Branch:** work on `main` (this is our own repo, not a fork contributing upstream)
- **Tests:** must pass before push. Run: `python3 -m pytest -o "addopts=" -q`
- **No framework in UI** — vanilla HTML/CSS/JS (match existing style)
- **Doc index:** all new .md files must be registered in CURRENT.md (CI enforces)
- **Formula fingerprint:** if scoring.py changes, run `python3 scripts/formula_fingerprint.py --update`
