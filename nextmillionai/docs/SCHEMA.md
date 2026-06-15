# Schema Reference

Current schema version: **1.1**

Canonical source: [`nextmillionai/schema.py`](../schema.py)

---

## Artifacts

| Artifact | File | Sensitivity | Endpoints |
|----------|------|-------------|-----------|
| **ScanResult** | `~/.nextmillionai/data/scan_results.json` | LOCAL ONLY | none |
| **Profile** | `~/.nextmillionai/data/profile.json` | Full on disk; shareable via builder | `GET /api/profile` (full, localhost), `GET /api/profile/public` (stripped) |

Both carry `schema_version` at the root.

---

## ScanResult (local only)

```
schema_version  : str          — "1.1"
engine          : {schema, taxonomy, methodology, package}
                               — the engine that produced this scan; the 1h
                                 scan cache is INVALIDATED on any schema/
                                 methodology mismatch (engine change → full
                                 recompute, always)
scanned_at      : str          — ISO 8601 UTC timestamp
tools_detected  : [str]        — e.g. ["claude_code", "cursor_ide"]
summary         : Summary
claude_code?    : ClaudeCodeData | null   — LOCAL: contains filesystem paths
cursor?         : CursorData | null       — LOCAL: contains titles, messages
codex?          : CodexData | null        — LOCAL: contains filesystem path
git?            : GitData | null          — LOCAL: contains filesystem paths
normalized      : NormalizedMetrics       — aggregate counts only (safe)
activityByDay?  : [ActivityDay]          — per-day activity (derived)
projects?       : [ScannedProject]       — discovered projects (LOCAL: names from paths)
stack?          : StackSummary           — aggregated tech stack (derived)
models?         : ModelsSummary          — model usage counts (derived)
```

### Summary

```
total_sessions      : int
total_ai_blocks     : int
total_scored_commits: int
total_plans         : int
total_projects      : int
ai_usage_span_days  : int
models_used         : [str]
```

### ClaudeCodeData

```
sessions       : [ClaudeSession]
total_sessions : int
total_messages : int
models_used    : {model: count}
tool_calls     : int
earliest?      : str | null
latest?        : str | null
```

#### ClaudeSession

```
sessionId           : str
project             : str       — LOCAL: full filesystem path
messages            : int
userMessages        : int
userWordCount       : int
toolCalls           : int
fileToolCalls       : int
terminalToolCalls   : int
models              : [str]
gitBranch?          : str | null
version?            : str | null
earliest?           : str | null
latest?             : str | null
```

### CursorData

```
ai_code?        : CursorAiCode | null
scored_commits? : CursorScoredCommits | null
conversations?  : CursorConversations | null   — LOCAL: titles, tldrs
plans?          : CursorPlans | null            — LOCAL: plan titles
transcripts?    : CursorTranscripts | null      — LOCAL: project names
```

### CursorAiCode

```
totalHashes : int
bySource    : {source: count}
byModel     : {model: count}
earliest?   : str | null
latest?     : str | null
```

### CursorScoredCommits

```
totalCommits      : int
totalLinesAdded   : int
totalAiLines      : int
totalComposerLines: int
totalTabLines     : int
totalHumanLines   : int
avgAiPercentage?  : float | null
recentCommits     : [{hash, message, date?, aiPct?}]   — LOCAL: commit messages
```

### CursorConversations

```
totalConversations : int
models             : {model: count}
modes              : {mode: count}
recentTopics       : [{title?, tldr, model?, mode?}]   — LOCAL: titles, tldrs
```

### CursorPlans

```
totalPlans : int
plans      : [{file, title, lineCount, sizeBytes}]     — LOCAL: plan titles
```

### CursorTranscripts

```
totalSessions : int
totalSizeKB   : float
projects      : [{project, sessions, sizeKB}]          — LOCAL: project names
```

### CodexData

```
total_sessions : int
path           : str    — LOCAL: filesystem path
```

### GitData

```
projects : [{path, name, commits_6m, stack, languages, frameworks, tools}]
                        — LOCAL: filesystem paths
```

### NormalizedMetrics (all optional)

Aggregate counts and ratios fed to the scoring engine. No raw text.

```
totalSessions            : int
totalScoredCommits       : int
totalAiCodeBlocks        : int
projectCount             : int
aiUsageSpanDays          : int
modelCount               : int
planCount                : int
languageCount            : int
aiLineSurvivalRate       : float    — 0.0-1.0
leverageRatio            : float
composerRatio            : float    — 0.0-1.0
postAiEditRate           : float    — 0.0-1.0
agentModeRatio           : float    — 0.0-1.0
avgPlanComplexity        : float
avgTurnsPerTask          : float
filesPerSession          : float
terminalCommandCount     : int
avgPromptWords           : int
peakProductivityHour     : int      — 0-23
longestStreakDays         : int
avgPromptsPerSession     : float
totalEstimatedHours      : float    — user session hours (ledger-preserved: max of live scan and history ledger; never regresses when tools prune)
agentRuntimeHours        : float    — hours subagents worked (their own transcripts; separate from user hours)
subagentRunCount         : int      — subagent transcript runs observed
longestSessionMinutes    : int
primaryModel             : str
cliAiToolCount           : int
cliAiTools               : [str]
cliAiCommandCount        : int
uniqueToolCount          : int
mcpServerCount           : int
firstShotAcceptRate      : float    — 0.0-1.0
referenceUsageRate       : float    — 0.0-1.0
errorFixRate             : float    — 0.0-1.0
errorsPerAiBlock         : float
buildSuccessRate         : float    — 0.0-1.0
correctionConvergenceRate: float    — 0.0-1.0
testAfterAiRate          : float    — 0.0-1.0
recentSignalDensity      : float
historicalSignalDensity  : float
recentLanguageCount      : int
historicalLanguageCount  : int
recentModelCount         : int
historicalModelCount     : int
recentPlanRatio          : float
historicalPlanRatio      : float
```

### ActivityDay

Per-day activity record for the contribution graph.  `aiRatio` is non-null only
where Cursor scored-commit data covers that day; all other days resolve to `null`.

```
date            : str           — "2024-06-01"
sessions        : int
activeMinutes   : float | null  — sum of session durations (capped 8h each)
tools           : [str]         — tools used that day
topProject      : str | null    — project with most sessions
aiRatio         : float | null  — real Cursor ai-code ratio, or null
```

### ScannedProject

```
name            : str
languages       : [str]
lastActive      : str | null    — ISO date of most recent session
sessionCount    : int
```

### StackSummary

```
languages       : {lang: weight}  — weights sum to 1.0
frameworks      : [str]
```

### ModelsSummary

```
byModel         : {model: count}
primaryModel    : str | null
```

---

## Assessment JSON (the shared object)

Both views — the profile and report pages in `nextmillionai/static/` (the
report) — render from this **same** assessment object. One source of truth, no
parallel shapes. The object lives on disk at `~/.nextmillionai/data/profile.json`
and is served via `GET /api/profile` (full, localhost only).

### Visibility split

Every field falls into one of three categories:

| Visibility | Meaning | Where it appears |
|-----------|---------|-----------------|
| **shareable** | Included in `build_shareable_profile()` output, safe to export/share | Profile public view, shared link, JSON-LD |
| **report** | Shown in the full report and profile (localhost only), but NOT in the shareable export | Report view, profile Details tab |
| **private** | Never leaves the local machine, excluded from all exports | Growth areas, raw goToPrompt, experimental |

### Profile (assessment JSON)

```
schema_version    : str               — "1.1"

# ── Identity (user-provided) ──────────────────────── shareable
name              : str
title             : str
experience_years  : int | null
ai_experience_years: int | null
location          : str
work_style        : str
notice_period     : str
stack             : [str]
projects          : [{name, desc}]

# ── Scores ─────────────────────────────────────────── shareable
intent_score      : int               — weighted composite (0-100)
composite         : int | null        — same as intent_score
dimensions        : {dim_id: DimensionResult}
archetypes        : [ArchetypeResult]
titles            : [TitleResult]
primaryTitle      : TitleResult | null
dataCompleteness  : float             — 0.0-1.0
tools_detected    : [str]
signals           : Signals
verification      : Verification
scoredAt          : float             — Unix timestamp

# ── Assessment metadata ────────────────────────────── shareable
assessment : {
  confidence      : int               — 0-100, weighted: 60% data completeness + 40% volume
  sessions        : int               — total sessions in window
  dateRange       : str               — e.g. "last 180 days"
  sourcesUsed     : [str]             — e.g. ["Claude Code", "Cursor", "git"]
  privacyMode     : str               — "local_only"
  methodology_version : str           — engine that computed this assessment;
                                        assessment_staleness() flags mismatches
}

# ── Positioning ────────────────────────────────────── shareable (tags)
positioning : {
  leverageMode    : str               — "prompting" | "harnessing" | "designs_the_loop"
  buildDomain     : {                 — schema 1.1: object with footprint
    primary       : str               — "products" | "ai_products" | "ai_systems"
                                        (commit-weight-dominant column — a map
                                        reading, never a tier)
    evidence      : [str]
    distribution  : [{domain, weight, projects}]  — share per column; a builder
                                        shipping products AND AI-products shows
                                        mass in both
  }
  techDomains     : [{name, weight, evidence}]  — share-of-activity tags
  footprint       : {cells: [{domain, stage, weight, projects}], basis}
  nearestExpansion: str | null         — fit-gated suggestion
  placement       : str | null         — placement sentence
}
# Note: the leverage MAP visual (dot + arrow) is report-only;
#        the profile carries positioning as neutral tags.

# ── Activity ───────────────────────────────────────── shareable
activity : {
  streak          : int
  activeDays      : int
  avgSessionHours : float
  totalSessions   : int
  days            : [int] | null       — heatmap levels (0-4) per day
}

# ── Wrapped stats / cards ──────────────────────────── report
wrappedStats      : {...}              — signal card data
cards             : [{q, a, d}]        — report-only formatted cards
# Note: wrappedStats.goToPrompt (the raw prompt text) is PRIVATE —
#        stripped from shareable by build_shareable_profile().

# ── Enrichment ─────────────────────────────────────── report (growthAreas = private)
enrichment : {
  narrative       : str                — one-sentence summary
  positioningLine : str                — positioning description
  whatYouBuilt    : [str]              — paragraphs
  decisionPatterns: {
    style         : str
    stats         : {detected, byDomain, highValue}
    named         : [{name, evidence}]
  }
  strengths       : [{claim, evidence}] — prominent on report
  growthAreas     : [{observed, nextSignal}]  — PRIVATE: "Only visible to you"
  howYouUseAI     : {persona, line, evidencePoints}
}
# growthAreas is stripped from the shareable profile.
# Without enrichment, heuristic fallback fills these blocks from scored data.

# ── Experimental ───────────────────────────────────── PRIVATE (never shareable)
experimental : {
  available       : bool
  signals         : [{label, headline, detail, confidence, kind}]
  codeIntelligence: [{label, title, find, sugg, basis, confidence, kind}]
}
# Lives in the report's Experimental tab and the profile's Details tab.
# Never appears on the main profile or in any shared/exported artifact.

# ── Private fields ─────────────────────────────────── PRIVATE
antiPatterns      : [AntiPattern]      — risk signals, never shared
growthEdge        : {suggestion, context}  — mode-aware next step, never shared
trajectory        : Trajectory

# ── AI leverage ────────────────────────────────────── report + profile (not shareable)
leverage : {                           — null when <10 tracked commits or <1000 lines
  aiShare         : float              — % of tracked shipped lines AI-authored (counted)
  aiLines         : int                — AI-authored lines surviving in commits
  humanLines      : int
  trackedCommits  : int
  outputMultiple  : float | null       — shipped/hand-written ratio, display-capped 50× (null when humanLines=0)
  outputMultipleCapped : bool
  handsOnHours    : float
  agentHours      : float
  soloEquivalentHours : {low, high} | null — research-anchored ESTIMATE band; also a Lab estimate card
  basis           : str
  estimateNote    : str
}
# Measured facts render on main surfaces; the counterfactual band is an
# estimate and lives in Lab/experimental. Never a score input.

# ── Wider tool field ───────────────────────────────── PRIVATE
toolsDetail : [{id, label, fidelity, note, models?}]
# Per-adapter fidelity declarations (deep / counts / presence) for the
# wider tool field + local model runtimes — Provenance display only.

# ── Multi-device (sync) ────────────────────────────── PRIVATE
multiDevice : {                        — present only when ≥2 synced devices
  devices   : [{id, name, lastSync, sessions, activeDays, thisDevice}]
  merged    : {sessions, activeDays, repoCount, dateRange}
  mergeRule : str                      — the documented dedupe rule
}
# Built by sync_merge.apply_multi_device from the local snapshot mirror
# (see docs/SYNC.md). The activity calendar unions across devices
# (entries gain `synced: true` where another device contributed);
# dimension scores stay per-device — raw signals never sync.
# Excluded from shareable (allowlist).

# ── Front-end view data ───────────────────────────── shareable (except scannedProjects)
summaryLine       : str | null        — one-liner from dominantMode + top dims + stat
compositeLabel    : str | null        — "strength index — <mode>"
dominantMode      : str | null        — work-mode ID
activityByDay     : [ActivityDay]     — per-day activity
scannedProjects   : [ScannedProject]  — project list (PRIVATE, excluded from shareable)
stackSummary      : StackSummary      — aggregated languages + frameworks
modelsSummary     : ModelsSummary     — model usage counts
```

### DimensionResult

```
score       : int | null    — 0-100
evidence    : [str]         — human-readable evidence strings
name        : str           — display name
weight      : float         — 0.0-1.0
description : str
```

Six dimensions: `signal_clarity`, `build_stability`, `decision_weight`,
`recovery_velocity`, `context_command`, `orchestration_range`.

### ArchetypeResult

```
id          : str
name        : str
icon        : str           — single Unicode character
color       : str           — hex color
description : str
soughtBy    : str
score       : int           — 0-100
level       : {id, label, color}
evidence    : [str]
```

Eight archetypes: `agent_builder`, `integration_architect`, `code_weaver`,
`rapid_prototyper`, `system_thinker`, `automation_engineer`, `cli_native`,
`context_engineer`.

### TitleResult

```
id        : str
name      : str
tagline   : str
idealFor  : str
emoji     : str
rare      : bool
legendary : bool
```

### AntiPattern

```
id   : str
name : str
icon : str
risk : str
```

### Trajectory

```
id          : str    — accelerating | stable | pivoting | declining | insufficient
label       : str
description : str
```

### Signals

```
ai_code_blocks      : int
scored_commits       : int
architecture_plans   : int
models_used          : [str]
```

### Verification

```
source   : str     — e.g. "claude_code"
verified : bool
```

---

## Sensitivity classification

| ScanResult section | Contains raw/sensitive data? | Details |
|--------------------|------------------------------|---------|
| `summary` | No | Aggregate counts only |
| `normalized` | No | Ratios and counts only |
| `claude_code` | **Yes** | Filesystem paths in `session.project` |
| `cursor` | **Yes** | Conversation titles, commit messages, plan titles |
| `codex` | **Yes** | Filesystem path |
| `git` | **Yes** | Filesystem paths, project paths |

| Profile field | Visibility | Notes |
|---------------|-----------|-------|
| Identity fields | shareable | User-provided, intentionally shared |
| Scores (dimensions, archetypes, titles, composite) | shareable | Derived from aggregate metrics |
| `assessment` (confidence, sources, dateRange) | shareable | Assessment metadata |
| `positioning` (leverageMode, buildDomain, techDomains) | shareable | Tags; map visual is report-only |
| `activity` (streak, activeDays, days) | shareable | Activity summary |
| `enrichment` (narrative, strengths, howYouUseAI, etc.) | report | Shown in report; `growthAreas` is **private** |
| `wrappedStats` / `cards` | report | Signal cards; `goToPrompt` raw text is **private** |
| `experimental` (signals, codeIntelligence) | **private** | Never shareable, report Experimental tab only |
| `antiPatterns`, `growthEdge` | **private** | Risk signals + growth, never shared |
| `scannedProjects` | **private** | Project list with paths, never shared |
| Any field not in `SHAREABLE_PROFILE_FIELDS` | **private** | Stripped by `build_shareable_profile()` |

---

## API endpoints

| Endpoint | Artifact | Sensitivity |
|----------|----------|-------------|
| `GET /api/profile` | Full Profile | Localhost only |
| `GET /api/profile/public` | Shareable Profile | Stripped via `build_shareable_profile()` |
| `GET /api/profile.json` | JSON-LD (from shareable) | Stripped via `build_agent_profile()` |
| `GET /api/profile/meta` | Metadata (from shareable) | Stripped via `build_profile_meta()` |

---

## Schema version policy

- `schema_version` is required on both `ScanResult` and `Profile`.
- Pre-1.0 files without `schema_version` trigger a warning, not a crash.
- Fields may only be **added**, never renamed or removed.
- Any schema change requires a core-owner review and a CHANGELOG entry.
