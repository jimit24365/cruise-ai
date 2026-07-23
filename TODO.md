# cruise-ai — Task Backlog

## 🔴 Next Up: Web UI Integration

### API Endpoints (in `hub.py`)
- [ ] `GET /api/recommend` — returns recommendation JSON array
- [ ] `GET /api/recommend?category=token_optimization` — filtered
- [ ] `GET /api/dashboard` — returns dashboard data (usage, cost, models, projects)
- [ ] `POST /api/feedback` — record feedback `{action_type, response}`
- [ ] `GET /api/feedback/summary` — return feedback stats
- [ ] `GET /api/longitudinal` — return trend data

### UI Pages (in `cruise_ai/static/`)
- [ ] `recommend.html` — recommendation cards with priority icons, teach_text expandable, feedback buttons
- [ ] `dashboard.html` — usage stats, cost breakdown, model/project pie charts, daily timeline
- [ ] Navigation: add "Recommend" and "Dashboard" tabs to existing nav bar
- [ ] Feedback: "Acted" / "Dismissed" / "Useful" buttons on each recommendation card
- [ ] Trust level indicator on each card (validated ✓✓, observed ✓, heuristic ~, experimental ?)

### Tests
- [ ] API endpoint tests (mock sessions, verify JSON schema)
- [ ] Test that pages render without JS errors

---

## 🟡 P1 Features

### Token Optimization
- [ ] Prompt Compression — suggest summarization for long prompts
- [ ] Cached Context Recommendation — suggest memory/pinning instead of paste
- [ ] Prompt Simplification — detect verbose patterns, suggest rewrites
- [ ] Token Waste Score — single number summarizing waste

### Skill Engine
- [ ] Skill Revision — detect outdated/unused skills, suggest updates
- [ ] Skill Marketplace — suggest community skills that match patterns
- [ ] Skill Health Check — find unused/outdated skill files

### MCP Discovery
- [ ] MCP Recommendation — detect APIs/docs suited for MCP
- [ ] MCP Generator — build MCP skeleton from detected patterns
- [ ] API → MCP Suggestion — Swagger/OpenAPI → MCP server

### Hook Automation
- [ ] Hook Recommendation — detect repetitive git/build commands
- [ ] Git Hook Generator — pre/post commit hooks
- [ ] PR Hook Generator — PR automation hooks

### Eval Harness
- [ ] Harness Recommendation — detect evaluation opportunities
- [ ] Harness Generator — create evaluation harness files

---

## 🟢 P2 Features

- [ ] Context Window Analysis — analyze conversation token growth over session
- [ ] Monthly Report — long-term trend report
- [ ] AI Health Score — single composite optimization score
- [ ] Skill Merge/Split — detect similar or oversized skills
- [ ] DB MCP Suggestion — database → MCP
- [ ] Architecture Memory — generate architecture docs from sessions
- [ ] Team Guidelines — generate coding rules from patterns
- [ ] AGENTS.md / CLAUDE.md / GEMINI.md generators
- [ ] Interactive Tutorials — guided creation with inline examples
- [ ] AI Learning Path — progressive roadmap based on current skill level

---

## 🔵 Infrastructure / Quality

- [ ] Real data validation — run recommendations against actual ~/.kiro sessions
- [ ] Precision/recall measurement per detector (needs feedback data)
- [ ] Threshold calibration from longitudinal data
- [ ] `cruise-ai config --enable-fingerprinting` CLI for opt-in
- [ ] PyPI publishing (`pip install cruise-ai`)
- [ ] GitHub Actions CI for the repo
- [ ] Community contribution guidelines (separate from nextmillionai's)

---

## ✅ Done

- [x] Repo setup (from nextmillionai main, independent repo)
- [x] Full rebrand: nextmillionai → cruise_ai (746 tests pass)
- [x] README, LICENSE (MIT), ROADMAP.md
- [x] Recommendation engine (5 categories, 12 detectors)
- [x] CLI: recommend, dashboard, teach, feedback
- [x] Trust: TRUST-MODEL.md, CALIBRATION.md
- [x] Feedback: local storage, dismissed suppression, confidence adjustment
- [x] Fingerprint: opt-in SHA-256 duplicate detection
- [x] Longitudinal: pre/post metric snapshots
- [x] Solution docs (6 files with mermaid diagrams)
- [x] Steering file for next session
