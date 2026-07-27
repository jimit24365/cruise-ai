# cruise-ai — Task Backlog

## Summary

**All planned features complete.** 7 categories, 15+ detectors, full web UI, feedback loop,
precision/recall measurement, threshold calibration, and PyPI-ready packaging. Total: 900+ tests passing.

---

## ✅ Done

### Web UI Integration
- [x] `GET /api/recommend` — returns recommendation JSON array
- [x] `GET /api/recommend?category=token_optimization` — filtered
- [x] `GET /api/dashboard` — returns dashboard data (usage, cost, models, projects)
- [x] `POST /api/feedback` — record feedback `{action_type, response}`
- [x] `GET /api/feedback/summary` — return feedback stats
- [x] `GET /api/longitudinal` — return trend data
- [x] `recommend.html` — recommendation cards with priority icons, teach_text expandable, feedback buttons
- [x] `dashboard.html` — usage stats, cost breakdown, model/project pie charts, daily timeline
- [x] Navigation: "Recommend" and "Dashboard" tabs in nav bar
- [x] Feedback: "Acted" / "Dismissed" / "Useful" buttons on each recommendation card
- [x] Trust level indicator on each card (validated ✓✓, observed ✓, heuristic ~, experimental ?)
- [x] API endpoint tests (mock sessions, verify JSON schema)
- [x] Pages render without JS errors

### Token Optimization
- [x] Prompt Compression — suggest summarization for long prompts
- [x] Cached Context Recommendation — suggest memory/pinning instead of paste
- [x] Prompt Simplification — detect verbose patterns, suggest rewrites
- [x] Token Waste Score — single number summarizing waste

### Skill Engine
- [x] Skill Revision — detect outdated/unused skills, suggest updates
- [x] Skill Marketplace — suggest community skills that match patterns
- [x] Skill Health Check — find unused/outdated skill files

### MCP Discovery
- [x] MCP Recommendation — detect APIs/docs suited for MCP
- [x] MCP Generator — build MCP skeleton from detected patterns
- [x] API → MCP Suggestion — Swagger/OpenAPI → MCP server

### Hook Automation
- [x] Hook Recommendation — detect repetitive git/build commands
- [x] Git Hook Generator — pre/post commit hooks
- [x] PR Hook Generator — PR automation hooks

### Eval Harness
- [x] Harness Recommendation — detect evaluation opportunities
- [x] Harness Generator — create evaluation harness files

### P2 Features
- [x] Context Window Analysis — analyze conversation token growth over session
- [x] Monthly Report — long-term trend report
- [x] AI Health Score — single composite optimization score
- [x] Skill Merge/Split — detect similar or oversized skills
- [x] DB MCP Suggestion — database → MCP
- [x] Architecture Memory — generate architecture docs from sessions
- [x] Team Guidelines — generate coding rules from patterns
- [x] AGENTS.md / CLAUDE.md / GEMINI.md generators
- [x] Interactive Tutorials — guided creation with inline examples
- [x] AI Learning Path — progressive roadmap based on current skill level

### Infrastructure / Quality
- [x] Real data validation — run recommendations against actual ~/.kiro sessions
- [x] Precision/recall measurement per detector (eval_metrics.py)
- [x] Threshold calibration from longitudinal data (calibration.py)
- [x] `cruise-ai config --enable-fingerprinting` CLI for opt-in
- [x] PyPI publishing readiness (`pip install cruise-ai`) — pyproject.toml + MANIFEST.in
- [x] GitHub Actions CI for the repo
- [x] Community contribution guidelines (CONTRIBUTING.md)

### Foundation
- [x] Repo setup (from nextmillionai main, independent repo)
- [x] Full rebrand: nextmillionai → cruise_ai (900+ tests pass)
- [x] README, LICENSE (MIT), ROADMAP.md
- [x] Recommendation engine (7 categories, 15+ detectors)
- [x] CLI: recommend, dashboard, teach, feedback, config
- [x] Trust: TRUST-MODEL.md, CALIBRATION.md
- [x] Feedback: local storage, dismissed suppression, confidence adjustment
- [x] Fingerprint: opt-in SHA-256 duplicate detection
- [x] Longitudinal: pre/post metric snapshots
- [x] Solution docs (6 files with mermaid diagrams)
- [x] Steering file for sessions
- [x] Phase 2 Web UI: recommend.html, dashboard.html, API endpoints, feedback buttons
- [x] Config CLI (`cruise-ai config`)
- [x] GitHub Actions CI (matrix 3.9–3.12, lint, typecheck, test)
- [x] Real data validation script (`scripts/validate_real_data.py`)

---

## 🔮 Future (Community / Marketplace)

- [ ] Plugin marketplace — community-contributed detectors via pip
- [ ] Team mode — aggregate coaching across team members (opt-in)
- [ ] VS Code extension — inline recommendations in editor
- [ ] Slack/Teams bot — periodic coaching digest
- [ ] Public benchmark — anonymized precision/recall leaderboard for detectors
