# CODE-INTELLIGENCE.md — Experimental local code scan

**Status: experimental · opt-in · v0.1.0**

The code-intelligence module (`cruise_ai/code_intel.py`) is the opt-in
local code scan behind `cruise_ai assess --code`. It reads repository
files **on the user's machine only** and reduces them to metrics. It exists
to (a) give `positioning.buildDomain` manifest-grade evidence and (b) feed
the `experimental.codeIntelligence[]` cards in the report's Experimental tab
and the profile's Details tab.

## Privacy contract

- **Opt-in only.** Never runs unless the user passes `--code`. Not part of
  calibrate defaults.
- **Metrics only.** File contents are read to count lines and parse
  dependency *names*; no source code, no file contents, and no dependency
  versions/URLs are ever stored or transmitted. What persists is counts,
  ratios, config-file presence, language totals, and the relative names of
  complexity hotspots.
- **Never shareable.** Everything this module produces lives under
  `experimental` visibility: excluded from the shareable profile, the
  static export, and any published payload.

## What it measures (v1 — reliable signals)

| Signal | How | Output |
|---|---|---|
| Structure | walk (bounded: 4,000 files/repo, vendored + dot dirs skipped) | `filesByLang`, `linesByLang`, `sourceFiles` |
| Dependencies | manifest names only (`package.json`, `requirements*.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`) | `depCount`, `agentFrameworks[]`, `llmSdks[]` |
| Tests | file-name heuristic (`test_*`, `*.spec.*`, `/tests/`) | `testFiles`, `testRatio` |
| Docs | README presence, `.md`/`.rst`/`docs/` count | `hasReadme`, `docFiles` |
| Complexity hotspots | files ≥ 500 lines (top 3 per repo) | `hotspots[{file, lines}]` |
| Deploy readiness | config presence (Dockerfile, vercel.json, fly.toml, netlify.toml, render.yaml, Procfile, CI workflows) | `deployConfigs[]`, `ciWorkflows` |

## How it feeds buildDomain

Per `BUILDER-MODEL.md`, dependency-manifest detection is the strongest
local evidence for what someone builds:

- agent frameworks (LangGraph, CrewAI, AutoGen, MCP SDK, …) → `ai_systems`
- LLM SDKs (Anthropic, OpenAI, LiteLLM, …) → `ai_products`
- neither → `products` (AI is how you build, not what ships)

Code-scan evidence can **raise** the domain (products → ai_products →
ai_systems) but never lower a domain already established from git
framework detection. Every evidence string contributed by this module is
tagged `(code scan)`.

## codeIntelligence cards

Each card: `{label, title, find, sugg, basis, confidence, kind}` where
`kind` is `measured` or `estimate` and `confidence` is 0–100. v1 cards:

- **Refactor hotspot** (measured, 60) — a file ≥ 500 lines; a natural seam
  for agent-assisted decomposition.
- **Test gap** (estimate, 45) — ≥ 20 source files with `testRatio` < 0.1.
  Explicitly labelled as a file-name heuristic, *not* a coverage run.
- **Doc gap** (measured, 80) — ≥ 10 source files and no README.
- **Harness suggestion** (measured, 70) — deploy config present, no CI.

Cards are only emitted when the data supports them. No padding, no
fabricated findings — an empty list is a valid result.

## Held for calibration (v2 — not emitted)

Automation-opportunity %, multi-agent-fit estimates, and AI↔human
authorship attribution from code structure are **not** produced: we cannot
yet measure them honestly from a static scan. They remain roadmap until a
calibration pass exists.

---

*Note: the build handoff lists this spec as pre-existing; it was missing
from the repo, so this document was authored alongside the implementation
to record the contract (per docs/archive/DAY1-PROMPTS.md Step E).*
