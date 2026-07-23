# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Kiro (CLI + IDE) as a first-class source** — its own consent question,
  deep fidelity: sessions, tool usage, prompt word counts, models (IDE),
  and subagent orchestration via parent/child session links. Contributed
  by @jimit24365 (adapter) with full pipeline integration.
- **New-source consent flow.** Sources added after you calibrated are
  asked once, individually, on your next interactive run — never enabled
  silently, and a newly-granted source is scanned immediately (the stale
  scan cache is dropped).
- **`docs/ADDING-A-TOOL.md`** — the end-to-end contributor workflow for
  tool integrations, plus test gates that fail loudly when an adapter's
  consent wiring is incomplete.

### Changed

- **Measured inputs widened (no formula changes; fingerprint unchanged).**
  Deep session sources beyond Claude Code/Cursor — Codex, Kiro, and deep
  wider-field tools — now feed the session-derived metrics they were
  already declared under in the signal registry (avg prompt words,
  prompts/turns per session, terminal commands, MCP calls, model and tool
  counts). Numbers can shift on upgrade for profiles with such sessions;
  Claude Code/Cursor-only profiles are bit-identical.
- Codex disclosure corrected: the adapter has parsed session JSONL
  (roles, models, tool names, word counts) since it was deepened — the
  docs previously understated this as "file count only".

## [1.0.0] - 2026-06-24

First public release. cruise_ai is a local-first AI coding profile
builder — the open alternative to Paxel.

### Added

- **Local-first assessment.** Scans the AI coding sessions already on your
  machine (Claude Code, Cursor, Codex) plus git, and scores how you build
  with AI — entirely on your machine. No account, no upload.
- **Six measured dimensions**, scored as arithmetic over counted local
  signals against research-anchored bands: Signal Clarity, Build Stability,
  Decision Weight, Recovery Velocity, Context Command, Orchestration Range.
  Anything that can't be measured is marked *insufficient*, never estimated.
- **Archetypes, crafts, and positioning.** Nine archetypes, twelve crafts
  plus the AI Explorer baseline, and a build-domain × leverage positioning
  map — a map, never a ladder (no percentiles, cohorts, or rankings).
- **One assessment JSON renders two views** — a shareable profile and a deep
  report (builder card, 2D positioning map, competency radar, Business Fit
  Map, heatmap, and a right-click "explain this number").
- **Wide tool coverage.** Claude Code, Cursor (all storage generations),
  Codex, git, and Claude Desktop (opt-in); a wider field of editors and CLIs
  (Aider, Cline, Continue, Copilot, Windsurf, Cody, JetBrains AI, Zed) and
  local model runtimes (Ollama, LM Studio, llama.cpp), with per-adapter
  fidelity shown in Provenance.
- **Opt-in enrichment** (`enrich`): narrative written by your own agent from
  real signals and bounded, secret-stripped excerpts; strictly validated and
  revocable — it never changes a score.
- **Opt-in code scan** (`assess --code`): repo files reduced to metrics only,
  on a raise-only basis, to sharpen build-domain classification.
- **Open, transparent methodology.** Every formula and band is documented and
  served at `/methodology`, with provenance and citations; a machine-readable
  registry drives the docs and a fingerprint test pins the formulas.
- **Privacy by construction.** No network in the assessment path; a single
  outbound module handles the explicit, derived-only, revocable `publish`.
  Your shareable profile carries derived numbers only — never your source
  code, prompts, or transcripts.
- **Surfaces.** A CLI, a self-hostable web profile + report + JSON, static
  export, an opt-in reference registry, and a Claude Code plugin.
- **Runs straight from the clone.** Python 3.9+, zero runtime dependencies.
