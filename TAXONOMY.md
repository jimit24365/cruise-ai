# cruise_ai — Builder Taxonomy

> **The living source of truth for how cruise_ai measures AI builders.**
> The scanner and scoring engine implement this document. When the taxonomy
> changes, this file changes first, then the code, then `schema.py`'s
> `taxonomy_version` is bumped.

**Taxonomy version:** `0.2.0` · **Last updated:** 2026-06 · **Status:** living
· aligns with methodology `0.3.0`

Status tags used throughout:
- `promoted` — measured from real signals, fully scored.
- `provisional` — published but low-weight / flagged "emerging"; needs validation.
- `candidate` — observed in the buffer, not yet scored.

---

## The model: three layers

A profile is not one number. It is three layers, in increasing order of "feels alive":

1. **Dimensions** — the scored rigor. *How strong are you, measurably?*
2. **Archetypes & work mode** — identity. *What kind of builder are you, and how do you build?*
3. **Signature & story** — the legible layer. *Wrapped stats, named decision patterns, and an evidence-grounded narrative.* This is the layer people screenshot.

A profile shows only what the available data supports. Missing inputs lower
`dataCompleteness`; they are never fabricated.

---

## Layer 1 — Dimensions (the six)

Stable core. Scored against research-anchored bands, not a curve. RAG is **not**
a dimension — it is a sub-signal of Context Engineering.

| # | Dimension | Measures | Key signals (today) | Status |
|---|-----------|----------|---------------------|--------|
| 1 | **Signal Clarity** | How precisely you direct AI | prompt specificity, iterations-to-accept, avg prompt words | promoted |
| 2 | **Build Stability** | Whether AI code survives | git churn / revert rate, post-edit stability | promoted |
| 3 | **Decision Weight** | Weight & durability of technical decisions | decision count/impact, plan-to-code ratio, decision reverts | promoted |
| 4 | **Recovery Velocity** | Speed & method of recovering from AI error | debug-vs-generate ratio, error→fix convergence | promoted |
| 5 | **Context Command** | Carrying context across tools, sessions, time | reference/rules usage, MCP/context bridging, long-session continuity, *RAG/retrieval patterns* | promoted |
| 6 | **Orchestration Range** | How many tools/models/agents you coordinate | tool count, **MCP servers**, **parallel-agent count**, model routing | promoted |

**Modernization note:** Context Command absorbs RAG/retrieval; Orchestration
Range foregrounds **MCP** and **parallel agents** over generic "tool count."

Candidate dimensions in the pipeline (see Layer 4 promotion):
- **Agent Harness Design** `candidate` — building the loop: tool definitions, control flow, verification, retries, autonomous-run gating.
- **Eval Engineering** `candidate` — eval/test-harness construction, verification-first behavior.
- **Steering Discipline** `candidate` — may split out of Signal Clarity: constraint-setting, scoping, production-risk framing.

Retired / demoted: *RAG Engineering Proficiency* (→ sub-signal of Context
Command), *MLOps / Model Management* (→ foundation-tier specialist archetype,
not a frontier dimension), *Cost-Conscious* (→ sub-signal of Orchestration).

---

## Layer 2 — Archetypes & work mode

### Archetypes (current — tiered)

**Frontier tier** (the crafts that define AI-native building now):
- **Agent Harness Builder** — builds and supervises the agent loop / fleets; parallel-agent management, output gating. `provisional`
- **Integration / MCP Engineer** — wires MCP servers, connectors, cross-service orchestration. `promoted`
- **Multi-Agent Orchestrator** — runs and coordinates multiple agents in parallel (worktrees, subagents). `promoted`
- **Context Engineer** — engineers context, rules, memory, retrieval, long-session state. `promoted`
- **Eval-Driven Builder** — verification-first; builds evals/harnesses around AI output. `provisional`
- **Production Guardian** — safety rails, production-risk instinct, review-heavy, manual-for-critical. `promoted`
- **AI Product Engineer** — ships AI-native products end to end (demo→production). `promoted`

**Application tier:**
- **System Thinker / Architect** — architecture-first, plan-then-build, decision quality.
- **Rapid Prototyper** — concept→working app, high leverage, features-heavy.
- **Code Weaver** — clean, surviving AI code, high test coverage.

**Foundation / specialist tier** (real but not the frontier):
- **Model Trainer** (fine-tune/eval/deploy), **Data / Pipeline Engineer**, **Model Router** (cost/quality routing).

Dropped: *Protocol Engineer* (out of scope for the standalone product).

### Work modes — "how you build" (surface in plain voice)

Observable from signals; one is dominant, others secondary.

| Mode | Plain-voice line | Key pattern |
|------|------------------|-------------|
| Architect-First | "You plan before you build." | high plan-to-code ratio, specs-first |
| Prompt-Iterate | "You riff in fast cycles." | high prompt count, iterative refine |
| One-Shot-Verify | "You ship in one run, then verify." | agent-mode dominant, verify-after |
| Read-Understand-Modify | "You read deeply before you touch." | high file-read-to-edit ratio |
| Test-Driven-AI | "You make the tests pass." | test-before-code signals |
| Multi-Agent-Orchestrated | "You run a fleet." | multiple simultaneous agent sessions |
| Hybrid-Manual | "You hand-write what matters." | high manual-for-critical rate |
| Exploration-Research | "You build to understand." | high question-ratio, low generation |

---

## Positioning — the map (build domain × leverage × tech domain)

Positioning **locates** a builder without ranking. No entity ranks above another;
no stage, domain, or tech stack is "better." These are **axis positions**, not tiers.

### `leverageMode` — how much you leverage AI to build

Three stages. Orchestrating / multi-agent is a sub-flavor **inside**
"Designs the loop," not a separate rung.

| Stage | Observes | Status |
|-------|----------|--------|
| **prompting** | Direct the agent turn by turn | `promoted` |
| **harnessing** | Rules, MCPs, hooks, persistent context around the agent | `promoted` |
| **designs_the_loop** | State file + self-feeding / scheduled runs, up to orchestrating multiple agents | `promoted` |

Higher leverage is *fit, not better*. It pays off on decomposable, repeatable work,
costs more tokens, and staying at prompting is the correct choice for
tightly-coupled work. No stage subtracts from any other value.

### `buildDomain` — what you build

An axis position, not a tier. No domain ranks above another.

| Domain | Description | Status |
|--------|-------------|--------|
| **products** | General products; AI is how you build, not what ships | `promoted` |
| **ai_products** | Products where the model does real work behind features | `promoted` |
| **ai_systems** | Agents, harnesses, multi-agent infrastructure — the tools others ship with | `promoted` |

Since methodology `0.4.0` the domain is classified **per repo** (deps declared;
imports/call sites verified under the opt-in code scan — a declared-but-unused
SDK does not count) and the profile carries a **distribution across columns**
alongside the commit-weight-dominant `primary`. The footprint is the identity:
mass shows wherever the work is.

### `techDomain` — where you operate

A share-of-activity tag set derived from commit-weighted language counts.
Pure signal — no stack ranked above another.

Common entries: `ts_react`, `python`, `swift`, `java`, `go`, `ruby`,
`php_laravel`, `rust`, `infra_docker_ci`.

Entries derived from the **experimental local code scan** (`--code`) are tagged
`code-scan-derived`. All others are derived from git commit data.

### Nearest expansion (fit-gated)

A *suggestion*, not a goal, shown only when the user's work decomposes cleanly.
Always carries the "fit, not better / ~15× the tokens / decomposable-only" caveat.

---

## Layer 3 — Signature & story (the YC-style legible layer)

### Wrapped stats (`promoted` — heuristic, computed from transcripts)

Parallel agents (max concurrent) · longest single session · plan-mode % ·
prompts per session · avg prompt length · ship streak · deep-session count ·
features vs fixes · go-to prompt (most-frequent short prompt) · tools used ·
models used · total active hours.

### Named decision patterns / "signature moves" (`provisional` — needs enrichment)

Recurring directive moves detected in real exchanges, each cited with evidence.
Seed library (extend as patterns emerge):

- **Name the Code Smell** — calls out a specific anti-pattern and demands the fix.
- **Kill Dead Complexity** — challenges over-engineering, asks for the lighter path.
- **Enforce Safety Rails** — constrains scope around production risk (no-edit, exact schema).
- **Audit Completeness** — requires file/line evidence, refuses hand-wavy findings.
- **Bring the Agent In** — context-rich framing; treats the agent as a thinking partner.
- **Constrain Hard** — tight boundaries, explicit output contracts.
- **Close the Loop** — verifies after the agent reports back (a growth signal when *absent*).

> These require the optional enrichment step (below). Without it, the profile
> shows wrapped-stats + dimensions but not named patterns or narrative.

### Narrative (`provisional` — needs enrichment)

Three short, evidence-grounded sections: **What You Built** (domains, dominant
tools, honest behavioral nuance), **Strengths**, **Growth Edge** (specific next
moves from the user's own sessions).

---

## Layer 4 — How the taxonomy evolves

The "observatory" mechanism (keep this — it is the moat):

```
OBSERVED   → pattern seen in the unclassified signal buffer
CANDIDATE  → validated across many builders / correlated with outcomes
PROVISIONAL→ published, low weight, flagged "emerging"
PROMOTED   → predictive power validated, full weight, integrated
```

Nothing is promoted without data. Raw, unmapped signals are preserved in
`scan_results.json` (never discarded) so future patterns can be discovered.

**Current candidates (refreshed — RAG-era list retired):** Agent Harness Design,
MCP / Integration Depth, Multi-Agent Orchestration, Eval Engineering, Context
Engineering (supersedes RAG), Steering Discipline.

---

## Enrichment (optional, opt-in, local-first)

The named decision patterns and narrative require an LLM summarization pass over
transcript excerpts. cruise_ai keeps this **opt-in and local-first**:

- Off by default. Heuristic scoring works fully without it.
- Uses the user's own API key **or** a local model. Excerpts never leave the
  machine via cruise_ai; nothing is uploaded to us.
- Output is derived-only (patterns, narrative, growth edge) — never raw prompts
  or code.

---

## Changelog

- `0.2.0` (2026-06) — Added the **positioning layer** as first-class taxonomy
  entities: `leverageMode` (three stages: prompting → harnessing → designs_the_loop;
  orchestrating is a sub-flavor inside designs_the_loop, not a rung), `buildDomain`
  (products / ai_products / ai_systems — axis positions, not tiers), and `techDomain`
  (share-of-activity tag set). No entity ranks above another. Added nearest-expansion
  (fit-gated). Tagged code-scan-derived entries. Aligned with methodology `0.3.0`.
- `0.1.0` (2026-06) — Initial living taxonomy. Consolidated the dimensions,
  archetypes, work modes, and evolution mechanism into one de-branded doc.
  Demoted RAG to a Context-Command sub-signal; foregrounded MCP / agent-harness /
  multi-agent / context / eval. Added the Layer-3 signature/story layer (wrapped
  stats, named decision patterns, narrative) and the opt-in enrichment model.
  Dropped Protocol Engineer.
