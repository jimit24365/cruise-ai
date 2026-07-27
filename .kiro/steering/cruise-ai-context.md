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
├── recommendations/        # Coaching engine
│   ├── types.py            # Recommendation dataclass + CONFIDENCE_THRESHOLD
│   ├── engine.py           # Orchestrator: runs detectors, feedback adjust, gate, sort
│   ├── analytics.py        # Usage/Cost/Timeline dashboards
│   ├── token_optimization.py  # Duplicate context, long prompts, model routing
│   ├── skills.py           # Tool patterns, co-occurrence, skill generator
│   ├── project_memory.py   # Repeated context, cross-session patterns
│   ├── learning.py         # Teach Me / Why This? / tutorials
│   ├── feedback.py         # User feedback storage + confidence adjustment
│   ├── fingerprint.py      # Opt-in SHA-256 duplicate detection
│   ├── longitudinal.py     # Pre/post metric tracking
│   ├── personalization.py  # Persona-based tuning
│   ├── mcp_discovery.py    # MCP tool/server recommendations
│   ├── hooks.py            # Git/PR hook automation
│   ├── eval_harness.py     # Evaluation opportunity detection
│   ├── health_score.py     # AI Health Score composite metric
│   ├── architecture_memory.py  # Architecture doc generation
│   ├── eval_metrics.py     # Precision/recall measurement (analysis tool)
│   └── calibration.py      # Threshold calibration from feedback
├── adapters/               # Data collectors (Kiro, Claude Code, Cursor, Codex, git, etc.)
├── scoring.py              # Dimension scoring (fingerprint-pinned)
├── aggregator.py           # Signal computation
├── build_profile.py        # CLI entry point + all commands
├── config_cmd.py           # `cruise-ai config` subcommand
├── hub.py                  # HTTP server (/api/* + static pages at localhost:7749)
├── static/                 # Vanilla HTML/CSS/JS UI
│   ├── profile.html, report.html, howitworks.html
│   ├── recommend.html, dashboard.html
│   └── js/, css/
├── examples/               # Example outputs
├── docs/                   # Bundled documentation
└── paths.py                # All path constants
```

## CLI Commands

```bash
cruise-ai                        # Full scan + build profile
cruise-ai recommend [--category <cat>] [--json] [--min-confidence N]
cruise-ai dashboard [--json]
cruise-ai teach [topic]
cruise-ai feedback [acted|dismissed|useful|not_useful] --action-type <type>
cruise-ai config [--enable-fingerprinting] [--set key=value]
```

## Key Design Decisions

- **No LLMs** — all recommendations are predefined rules over counted signals
- **Privacy** — never reads prompt text, only counts/tool names/timestamps
- **trust_level** on every recommendation: validated, observed, heuristic, experimental
- **Feedback loop** — dismissed recs suppressed, confidence adjusted from user feedback
- **Confidence gate** — only show recommendations with confidence ≥ 60%
- **Never touch scoring.py** — formula fingerprint is pinned, scoring is the upstream's domain
- **Calibration** — threshold auto-tuning from historical feedback + longitudinal data

## Tests

```bash
python3 -m pytest -o "addopts=" -q   # Run all (currently 920+ pass)
python3 -m pytest tests/test_recommendations.py -o "addopts=" -q  # Recommendation tests
python3 -m pytest tests/test_eval_calibration.py -o "addopts=" -q  # Eval/calibration tests
```

## What's Done

- ✅ Full rebrand from nextmillionai → cruise_ai
- ✅ Recommendation engine (7 categories, 15+ detectors, 11 registered in engine.py)
- ✅ CLI commands: recommend, dashboard, teach, feedback, config
- ✅ Trust infrastructure: TRUST-MODEL.md, CALIBRATION.md, feedback, fingerprint, longitudinal
- ✅ Solution documentation (6 docs with mermaid diagrams)
- ✅ Feature roadmap (ROADMAP.md)
- ✅ Web UI: recommend.html, dashboard.html, API endpoints, feedback buttons
- ✅ Token optimization: prompt compression, cached context, simplification, waste score
- ✅ MCP discovery: recommendation + generator + API→MCP suggestion
- ✅ Hook automation: recommendation + git hook generator + PR hooks
- ✅ Eval harness: recommendation + generator
- ✅ Context window analysis, AI health score, skill merge/split
- ✅ Architecture memory: doc generation from sessions
- ✅ Personalization: persona-based recommendation tuning
- ✅ Precision/recall measurement (eval_metrics.py)
- ✅ Threshold calibration (calibration.py) with longitudinal integration
- ✅ PyPI publishing readiness (classifiers, keywords, MANIFEST.in)
- ✅ Community contribution guidelines (CONTRIBUTING.md rewritten)
- ✅ GitHub Actions CI (matrix 3.9–3.12, lint, typecheck, test)
- ✅ Real data validation script

## What's Next (Future / Community)

1. **Plugin marketplace** — community-contributed detectors installable via pip
2. **Team mode** — aggregate coaching across team members (opt-in, privacy-respecting)
3. **VS Code extension** — inline recommendations in editor sidebar
4. **Slack/Teams bot** — periodic coaching digest notifications
5. **Public benchmark** — anonymized precision/recall leaderboard for detectors
6. **Monthly trend reports** — long-form analysis emailed or served via UI

## Conventions

- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`)
- **Branch:** feature branches off main
- **Tests:** must pass before push. Run: `python3 -m pytest -o "addopts=" -q`
- **No framework in UI** — vanilla HTML/CSS/JS (match existing style)
- **Formula fingerprint:** if scoring.py changes, run `python3 scripts/formula_fingerprint.py --update`
