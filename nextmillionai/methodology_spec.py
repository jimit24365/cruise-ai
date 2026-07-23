"""Machine-readable methodology spec — the data behind the /methodology explorer.

Single-source-of-truth discipline (same as the render-parity guards): every
NUMBER here is derived live from scoring.py — dimension weights via
``score_dimensions``, mode-adapted weights via ``_adapt_weights``, level bands
via ``_get_level``. Nothing numeric is hand-typed. Only the COPY — what each
dimension measures, the signals it reads, and the research behind it — is
declared here, and that is editable product surface, never a formula.

``tests/test_methodology_spec.py`` asserts the derived numbers match the engine
and that every cited reference resolves, so the explorer can never misstate the
real scoring. Served as JSON at ``/api/methodology-spec`` (hub.py).
"""

from __future__ import annotations

from nextmillionai import scoring
from nextmillionai.schema import METHODOLOGY_VERSION, SCHEMA_VERSION, TAXONOMY_VERSION

# Display order — matches the dimensions UI and SCORING-METHODOLOGY.md §2.
DIM_ORDER = [
    "signal_clarity",
    "build_stability",
    "decision_weight",
    "recovery_velocity",
    "context_command",
    "orchestration_range",
]

# Work modes shown in the weight-toggle, in a deliberate reading order.
MODE_ORDER = [
    "Architect-First",
    "Prompt-Iterate",
    "One-Shot-Verify",
    "Test-Driven-AI",
    "Multi-Agent-Orchestrated",
    "Read-Understand-Modify",
    "Hybrid-Manual",
    "Exploration-Research",
]

# Complete data-source coverage, by fidelity tier (deep / counts / presence).
# Faithful to docs/ADAPTERS.md (the canonical contract). The engine reads far
# more than the first-class tools; a guard (tests/test_tool_coverage.py)
# asserts every adapter the registry instantiates is listed here AND that each
# declared tier matches the adapter's own fidelity — so the methodology can
# never under-state, or mis-tier, what the engine actually reads.
TOOL_COVERAGE: dict[str, list[dict]] = {
    "firstClass": [
        {
            "id": "claude_code",
            "label": "Claude Code",
            "tier": "deep",
            "reads": "JSONL sessions + subagent runs: timestamps, roles, tool calls, "
            "models, prompt word counts, plan mode, dispatches",
        },
        {
            "id": "cursor",
            "label": "Cursor",
            "tier": "deep",
            "reads": "composer history (all storage generations) + AI code-tracking DB: "
            "sessions, per-commit AI/human line attribution, models, plans",
        },
        {
            "id": "codex",
            "label": "Codex",
            "tier": "deep",
            "reads": "JSONL sessions: timestamps, models, tool calls, prompt word counts",
        },
        {
            "id": "kiro",
            "label": "Kiro",
            "tier": "deep",
            "reads": "CLI JSON metadata + JSONL transcripts + history files: "
            "sessions, timestamps, tool calls by type, prompt word counts, "
            "subagent orchestration (parent_session_id), agent names; "
            "IDE session JSON: sessions, timestamps, message counts, "
            "prompt word counts, models, autonomy mode",
        },
        {
            "id": "git",
            "label": "git",
            "tier": "deep",
            "reads": "commit log + dependency manifests: commits, feature/fix mix, "
            "languages, frameworks, build domain",
        },
    ],
    "widerField": [
        {
            "id": "aider",
            "label": "Aider",
            "tier": "deep",
            "reads": "chat history session markers + timestamps",
        },
        {
            "id": "cline",
            "label": "Cline",
            "tier": "deep",
            "reads": "VS Code task dirs: sessions, message counts, timestamps",
        },
        {
            "id": "continue",
            "label": "Continue.dev",
            "tier": "deep",
            "reads": "session index: sessions, messages, models, timestamps",
        },
        {
            "id": "copilot_chat",
            "label": "GitHub Copilot Chat",
            "tier": "deep",
            "reads": "VS Code chat sessions: sessions, request counts, timestamps",
        },
        {
            "id": "zed_ai",
            "label": "Zed AI",
            "tier": "deep",
            "reads": "conversations (parsed) + thread counts",
        },
        {
            "id": "opencode",
            "label": "OpenCode",
            "tier": "deep",
            "reads": "opencode.db (or legacy JSON store): sessions, per-role "
            "message counts, timestamps, project paths",
        },
        {
            "id": "windsurf",
            "label": "Windsurf",
            "tier": "counts",
            "reads": "Cascade store file counts + last activity (sessions insufficient)",
        },
        {
            "id": "cody",
            "label": "Cody",
            "tier": "counts",
            "reads": "storage file counts + last activity (sessions insufficient)",
        },
        {
            "id": "antigravity",
            "label": "Antigravity",
            "tier": "counts",
            "reads": "trajectory (.pb) + brain-task counts + last activity "
            "(Protobuf store; sessions insufficient)",
        },
        {
            "id": "jetbrains_ai",
            "label": "JetBrains AI",
            "tier": "presence",
            "reads": "IDE config markers (chat not locally parseable)",
        },
    ],
    "localRuntimes": [
        {
            "id": "ollama",
            "label": "Ollama",
            "tier": "counts",
            "reads": "installed model tags + prompt history line count",
        },
        {
            "id": "lmstudio",
            "label": "LM Studio",
            "tier": "counts",
            "reads": "models + conversation file counts",
        },
        {
            "id": "llamacpp",
            "label": "llama.cpp",
            "tier": "presence",
            "reads": "GGUF model cache presence (no usage log)",
        },
    ],
    "optIn": [
        {
            "id": "claude_desktop",
            "label": "Claude Desktop",
            "tier": "presence",
            "reads": "install + MCP config names only (opt-in, default off; when "
            "enabled, its configured MCP servers count toward the deduped MCP "
            "signal — names never leave the machine)",
        },
        {
            "id": "custom",
            "label": "Custom adapters",
            "tier": "counts",
            "reads": "user-registered tool logs: file-per-session timestamps or presence",
        },
    ],
}


def coverage_ids() -> set[str]:
    return {t["id"] for grp in TOOL_COVERAGE.values() for t in grp}


# The research behind the scoring. Faithful to docs/REFERENCES.md — keep the
# finding text in sync with the bibliography (a guard checks every key resolves).
CITATIONS: dict[str, dict] = {
    "metr": {
        "label": "METR (2025)",
        "finding": "RCT, 16 developers, 246 tasks — 19% slower with AI despite "
        "predicting and perceiving a speedup. The operator, not the tool, drives outcomes.",
        "strength": "load-bearing",
    },
    "veracode": {
        "label": "Veracode (2025)",
        "finding": "100+ LLMs, 80+ tasks — ~45% of AI-generated code introduced "
        "OWASP-class vulnerabilities, with no improvement at larger model scale.",
        "strength": "load-bearing",
    },
    "pwc": {
        "label": "PwC (2025)",
        "finding": "~1B job ads — a 56% wage premium for AI skills (up from 25%); "
        "AI-skill roles grew as total postings shrank.",
        "strength": "load-bearing",
    },
    "space": {
        "label": "Forsgren et al. (2021) — SPACE",
        "finding": "Never reduce a developer to one number — measure across "
        "dimensions. Behind the six-dimension model and 'no single score predicts performance.'",
        "strength": "design anchor",
    },
    "dora": {
        "label": "Forsgren, Humble, Kim (2018) — Accelerate / DORA",
        "finding": "Outcome, stability, and recovery as first-class engineering signals.",
        "strength": "design anchor",
    },
    "nagappan": {
        "label": "Nagappan & Ball (2005)",
        "finding": "Code churn predicts defect density — behind the AI-line-survival framing.",
        "strength": "design anchor",
    },
    "stackoverflow": {
        "label": "Stack Overflow (2025)",
        "finding": "AI output is 'almost right, but not quite' — real time spent debugging it.",
        "strength": "directional",
    },
    "apiiro": {
        "label": "Apiiro (2025)",
        "finding": "AI-assisted developers produce several times more commits — more to review.",
        "strength": "directional",
    },
    "newport": {
        "label": "Newport (2016) — Deep Work",
        "finding": "Sustained, uninterrupted focus is the real unit of output — behind the "
        "deep/marathon session metrics and the gap-based active-time estimator.",
        "strength": "design anchor",
    },
    "flow": {
        "label": "Csikszentmihalyi (1990) — Flow",
        "finding": "Uninterrupted engaged stretches are the meaningful measure of working "
        "time — behind counting active time (idle >30 min excluded), not raw wall-clock.",
        "strength": "design anchor",
    },
}

# Provenance — the honest confidence class of every number. Documenting this per
# metric is the point: it lets us be complete without overclaiming, and it
# surfaces exactly which constants are reasoned (not validated) choices.
PROVENANCE = {
    "measured": "A direct count or ratio — true by definition of what was observed.",
    "research-anchored": "The construct or its anchor traces to a cited study.",
    "reasoned-default": "A sensible chosen constant — not externally validated, openly "
    "versioned, recalibrated as data accrues. An honest default, not a hidden assumption.",
    "estimate": "An explicitly labeled band — never sold as an exact measurement.",
}

# Per-dimension copy + research grounding. Numbers (weight, bands) come from
# scoring.py; this is the editable narrative layer.
DIMENSION_META: dict[str, dict] = {
    "signal_clarity": {
        "measures": "The precision of your direction — how clearly you steer the AI.",
        "signals": [
            "first-shot acceptance rate",
            "iterations to acceptance",
            "reference-rich prompts",
            "prompt specificity",
        ],
        "citations": ["metr", "pwc", "space"],
        "evidenceNote": "Strongly anchored — the operator effect is the load-bearing finding.",
    },
    "build_stability": {
        "measures": "Whether the AI code holds up in your context — does it survive?",
        "signals": [
            "AI-line survival in commits",
            "post-edit stability",
            "error-fix rate",
        ],
        "citations": ["veracode", "nagappan", "dora", "apiiro"],
        "evidenceNote": "Strongly anchored — AI code safety + churn-as-defect-signal.",
    },
    "decision_weight": {
        "measures": "The weight and durability of the decisions you make with AI.",
        "signals": [
            "decision impact",
            "decisions that stick",
            "plan-before-code signals",
        ],
        "citations": ["space"],
        "evidenceNote": "Less externally quantified — anchored in craft logic and the "
        "SPACE framework more than a single study. An open question.",
    },
    "recovery_velocity": {
        "measures": "How fast you recover when the AI gets it wrong.",
        "signals": [
            "debug-vs-generate ratio",
            "error→fix convergence",
        ],
        "citations": ["metr", "dora", "stackoverflow"],
        "evidenceNote": "Anchored — rework and 'almost right' debugging are well documented.",
    },
    "context_command": {
        "measures": "Carrying context across tools and sessions without losing the thread.",
        "signals": [
            "reference & rules usage",
            "MCP / context bridging (servers configured across Claude Code, "
            "Cursor & Claude Desktop, deduped — plus actual MCP tool-call usage)",
            "session continuity",
            "cross-surface breadth",
        ],
        "citations": ["space"],
        "evidenceNote": "Less externally quantified — emerging context-engineering practice. "
        "An open question.",
    },
    "orchestration_range": {
        "measures": "The tools, models, and agents you coordinate to get work done.",
        "signals": [
            "tool count",
            "MCP servers",
            "max parallel agents",
            "subagent dispatches",
            "model routing",
        ],
        "citations": [],
        "evidenceNote": "Directional — rests on rising agentic/MCP adoption, not an RCT. "
        "The least externally quantified dimension, and a prime open question.",
    },
}

# Calibration scope — applicability, never a ranking (see SCORING-METHODOLOGY.md).
SCOPE = {
    "title": "Who this is calibrated for",
    "body": "These scores are calibrated for people who build software with AI — "
    "software developers and AI engineers. Every signal is read from your AI coding "
    "tools — Claude Code, Cursor, Codex, and Kiro first-class, plus a wider field of editors, "
    "CLIs, and local model runtimes — and your git history, and every band is anchored "
    "to research on software developers.",
    "notYet": "If you build with AI in other ways — no-code tools, design, product, "
    "research — this assessment is not yet calibrated for your work, and the numbers "
    "won't mean what they're meant to. That's a 'not yet', not a verdict: widening the "
    "calibration is on the roadmap.",
    "principle": "As always, no builder type is ranked above another. This is about "
    "what the measurement is valid for — not a hierarchy.",
}

# Calibrations we are genuinely least sure of — where contributors start.
OPEN_QUESTIONS = [
    {
        "title": "Decision Weight & Context Command grounding",
        "detail": "These two dimensions are anchored more in craft logic and the SPACE "
        "framework than in external studies — they're the least externally quantified. "
        "What would rigorous measurement of decision durability and context-carry look like?",
    },
    {
        "title": "Orchestration Range evidence base",
        "detail": "Orchestration Range rests on directional adoption trends, not an RCT. "
        "What's the right evidence base for multi-agent / multi-tool skill?",
    },
    {
        "title": "Equal sub-signal weighting",
        "detail": "Within each dimension, sub-signals are averaged equally. Should some "
        "count more than others, and on what evidence?",
    },
    {
        "title": "Level band cutoffs",
        "detail": "The level cutoffs (Elite ≥85 … Emerging <35) are a research-derived "
        "calibration, not a validated threshold. They recalibrate as real usage data accrues.",
    },
    {
        "title": "Mode-adaptive weighting multipliers",
        "detail": "The composite re-weights dimensions by your dominant work mode "
        "(multipliers bounded 0.6–1.4 so no dimension is erased). Are those multipliers right?",
    },
]


# Sections, in reading order, for grouping the registry in the doc + UI.
SECTION_LABELS = {
    "composite": "Composite & weighting",
    "archetypes": "Archetypes & kinds",
    "work_modes": "Work modes",
    "positioning": "Positioning (the map)",
    "business_fit": "Business fit",
    "your_numbers": "Your numbers",
    "collaboration": "AI collaboration",
    "lab": "Lab (leverage & estimates)",
    "confidence": "Confidence & integrity",
}

# The per-metric registry: for EVERY derived number, the exact code logic, our
# reasoning for it, and an honest provenance label. This is the answer to "does
# our analysis have meaning?" — meaning comes from construct validity +
# transparency + honest provenance, not from validation we can't have without a
# cohort (which the no-ranking, local-first design forbids). Dimensions live in
# DIMENSION_META above; everything else is here.
METRICS: list[dict] = [
    {
        "id": "composite",
        "label": "Composite (strength index)",
        "section": "composite",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Σ(dimension_score × mode-adapted weight) / Σ(weights of scored "
        "dimensions). Base weights live in scoring.py; they adapt to your dominant work "
        "mode via _MODE_WEIGHT_MULTIPLIERS (bounded 0.6–1.4), renormalized to 1.0. Unscored "
        "dimensions are excluded, never zero-filled.",
        "reasoning": "A single number must reflect excellence in HOW you build, not a "
        "generic ideal — so weights tilt toward the dimensions your mode depends on. The "
        "base weights and multipliers are reasoned defaults (an open question), bounded so "
        "no dimension is erased.",
        "citations": ["space"],
    },
    {
        "id": "archetypes",
        "label": "Archetypes (crafts)",
        "section": "archetypes",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Each of the 9 archetypes is scored independently: its sub-signals are "
        "each mapped to 0–100 by a linear/inverse band, then averaged equally. Agent-leverage "
        "signals only raise scores, never lower them. Levels: Elite ≥85, Advanced ≥70, "
        "Proficient ≥55, Developing ≥35, Emerging <35.",
        "reasoning": "Crafts are multi-hold and independent — you can be strong at several at "
        "once, never ranked on a ladder. Equal sub-signal averaging is a neutral prior: with "
        "no evidence one signal matters more, we don't pretend it does (an open question).",
        "basis": "An archetype with no measurable signal is insufficient, not zero.",
    },
    {
        "id": "work_modes",
        "label": "Work modes",
        "section": "work_modes",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "8 modes, each scored from weighted behavioral signals (e.g. "
        "Architect-First = 0.5·plan-ratio + 0.3·reference-usage + 0.2·composer-ratio). "
        "Dominant = highest; secondary = the others scoring above 20.",
        "reasoning": "Your dominant mode sets the composite's weighting, so it's measured "
        "from observable behavior, never self-reported. The per-signal weights (0.5/0.3/0.2) "
        "are reasoned primary/secondary/tertiary splits — chosen, not validated.",
    },
    {
        "id": "titles",
        "label": "Kinds (titles)",
        "section": "archetypes",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Everyone with any measured AI activity holds the baseline kind "
        "(AI Explorer); specialized kinds are earned by crossing archetype thresholds: "
        "single-archetype kinds at ≥80 (Automation/CLI at ≥75); combination kinds need ≥70–80 "
        "across 2–3 archetypes; the legendary kind needs 6+ archetypes ≥75 with at least one "
        "≥90. A specialized kind always outranks the baseline for the primary title.",
        "reasoning": "Kinds are crafts you hold, never rungs — and the entry craft is a real "
        "craft, not a void: a builder who has started but not specialized is an AI Explorer, "
        "not 'no kind'. The cutoffs (80/75/70) are reasoned thresholds; hard boundaries create "
        "a cliff at 79 vs 80 — a known limitation we'd smooth later.",
    },
    {
        "id": "leverage_mode",
        "label": "Leverage mode (map Y)",
        "section": "positioning",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Three stages from agent-orchestration evidence: designs_the_loop when "
        "maxParallelAgents ≥ 3, OR agentModeRatio > 0.5 with maxParallel ≥ 2, OR ≥ 10 "
        "subagent dispatches across ≥ 3 sessions; harnessing when context scaffolding is "
        "present (CLAUDE.md / rules / MCP / hooks, or > 5 plans); prompting otherwise.",
        "reasoning": "Higher leverage is fit, not better — staying at prompting is correct "
        "for tightly-coupled work. The thresholds are reasoned defaults marking qualitative "
        "shifts in how much structure carries the agents.",
        "basis": "Subagent/parallel evidence from Claude Code (Task calls + run files) "
        "and Kiro (subagent child sessions).",
    },
    {
        "id": "build_domain",
        "label": "Build domain (map X)",
        "section": "positioning",
        "type": "indirect",
        "provenance": "measured",
        "derivation": "Per-repo classification by dependency markers, verified against "
        "import/call-sites when the --code scan runs (declared-but-unused SDKs don't count): "
        "ai_systems (agent frameworks: LangChain, CrewAI, MCP SDK…), ai_products (LLM SDKs: "
        "OpenAI, Anthropic…), else products. Primary = commit-weighted majority; the "
        "distribution carries the full footprint.",
        "reasoning": "What you build is a fact about your repos, not a judgment — read from "
        "real dependencies and (when scanned) actual usage, weighted by recent commits.",
    },
    {
        "id": "footprint",
        "label": "Footprint cells",
        "section": "positioning",
        "type": "indirect",
        "provenance": "measured",
        "derivation": "Each repo placed in a (build-domain × leverage-stage) cell, weighted "
        "by its 6-month commit share; cells render at ≥ 1%.",
        "reasoning": "Shows where your real work sits across repos, not a single label — "
        "commit-weighted so active work dominates.",
    },
    {
        "id": "business_fit",
        "label": "Business fit (affinity)",
        "section": "business_fit",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Per segment: round(Σ(min(your_archetype_score / required_min, 1.0) × "
        "weight × 100) / Σ weight). Strong fit = every minimum met. Top 3 surfaced. Report-only.",
        "reasoning": "Fit-to-segment, never builder-vs-builder. The per-segment archetype "
        "requirements and weights are reasoned editorial mappings of what each segment values "
        "— the softest part of the methodology, and the first we'd back with evidence.",
    },
    {
        "id": "confidence",
        "label": "Confidence",
        "section": "confidence",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "round(completeness×25 + sources×20 + depth×30 + volume×15 + window×10), "
        "capped 95 (98 with the opt-in code scan). completeness = measured metric slots / 46; "
        "sources = collected / 4 standard; depth = fraction of scored dimensions on a sufficient "
        "sample (≥10 events); volume = active hours / 40; window = AI-era active days / 90.",
        "reasoning": "Confidence rewards SUBSTANCE, not raw counts — many short sessions over a "
        "long, sparse span no longer buys it. Depth is the biggest factor: when scores rest on "
        "small samples, confidence is held down even if breadth is high. The weights and the "
        "sufficiency threshold are reasoned defaults; the caps reserve the top for the deepest "
        "evidence.",
    },
    {
        "id": "trajectory",
        "label": "Trajectory",
        "section": "confidence",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Compares recent vs historical signal density, model adoption, and "
        "language breadth → accelerating / pivoting / declining / stable; insufficient under "
        "14 days. Private by default.",
        "reasoning": "A you-vs-you trend, never against other people; the ratio thresholds "
        "(e.g. 1.3×) are reasoned defaults.",
    },
    {
        "id": "anti_patterns",
        "label": "Anti-patterns",
        "section": "confidence",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Risk flags from dimension combinations (e.g. high Signal Clarity with "
        "very low Build Stability), with prototyping modes excepted. Private by default.",
        "reasoning": "Surfaces genuine risk without penalizing a legitimate fast-prototype "
        "style; the trigger bands are reasoned defaults.",
    },
    # ── Your numbers (mostly direct counts) ──
    {
        "id": "ai_lines_survived",
        "label": "AI code shipped",
        "section": "your_numbers",
        "type": "direct",
        "provenance": "measured",
        "derivation": "Sum of AI-attributed diff lines that survive in tracked commits "
        "(per-commit authorship attribution).",
        "reasoning": "Survival in commits — not raw generation volume — is the honest output "
        "signal; code that was reverted didn't ship.",
        "basis": "Cursor scored commits only; ≥ 10 commits / ≥ 1000 lines, or shown insufficient.",
        "citations": ["nagappan"],
    },
    {
        "id": "maxParallelAgents",
        "label": "Max parallel agents",
        "section": "your_numbers",
        "type": "indirect",
        "provenance": "measured",
        "derivation": "Peak concurrent agents from overlapping subagent-run transcripts (hard "
        "evidence: their own timestamps), with within-tool session overlap as a softer floor. "
        "Cross-tool overlap never counts.",
        "reasoning": "Counts only genuine simultaneity from real timestamps — never assumed "
        "parallelism.",
        "basis": "Claude Code subagent transcripts.",
    },
    {
        "id": "subagentDispatches",
        "label": "Subagents dispatched",
        "section": "your_numbers",
        "type": "direct",
        "provenance": "measured",
        "derivation": "Count of Task-tool dispatches (or subagent child sessions linked by "
        "parent_session_id) per session, accumulated in the local ledger.",
        "reasoning": "A direct count of agents you sent off to work — the clearest "
        "loop-design signal.",
        "basis": "Claude Code (Task calls + run files) and Kiro (subagent child sessions).",
    },
    {
        "id": "totalActiveHours",
        "label": "Your session time",
        "section": "your_numbers",
        "type": "indirect",
        "provenance": "estimate",
        "derivation": "Gap-based active time where per-event timestamps exist (idle > 30 min "
        "excluded); first-to-last span capped at 8h otherwise. Ledger-preserved.",
        "reasoning": "Active, engaged time is the meaningful unit — not wall-clock — so idle "
        "gaps are removed where measurable. The 8h span cap and 30-min idle threshold are "
        "reasoned defaults grounded in deep-work / flow research.",
        "basis": "True active time for Claude Code/Codex; open-session span (8h cap) for "
        "Cursor and Kiro. Subagent child sessions are agent runtime, never session time.",
        "citations": ["newport", "flow"],
    },
    {
        "id": "agentRuntimeHours",
        "label": "Agent runtime",
        "section": "your_numbers",
        "type": "indirect",
        "provenance": "estimate",
        "derivation": "Sum of subagent run spans (8h cap each) from their own transcripts, "
        "kept separate from your hands-on hours.",
        "reasoning": "Agents run in parallel, so their time can't be added to yours — it is "
        "tracked separately, never folded into your active hours.",
        "basis": "Claude Code subagent transcripts only.",
    },
    {
        "id": "planModePercent",
        "label": "Plan-first",
        "section": "your_numbers",
        "type": "direct",
        "provenance": "measured",
        "derivation": "Plan-before-code sessions / Claude Code sessions.",
        "reasoning": "Shown neutrally, never graded — planning is a mode, not a universal virtue.",
        "basis": "Claude Code only (other tools don't expose plan mode).",
    },
    {
        "id": "avgPromptWords",
        "label": "Avg prompt",
        "section": "your_numbers",
        "type": "direct",
        "provenance": "measured",
        "derivation": "Mean word count over parsed prompts.",
        "reasoning": "A signal of direction style, not quality.",
        "basis": "Parsed-transcript tools — Claude Code, Codex, Kiro; Cursor prompt "
        "bodies are never read.",
    },
    # ── AI collaboration ──
    {
        "id": "surfaces_donut",
        "label": "Surfaces split",
        "section": "collaboration",
        "type": "indirect",
        "provenance": "measured",
        "derivation": "Per-tool share of your active days (days the tool appears / total "
        "active days). Git is the source, not a surface.",
        "reasoning": "Day-presence, not session count — so a heavily-logged tool doesn't "
        "dwarf one you use daily but lightly.",
    },
    {
        "id": "heatmap_day",
        "label": "Contribution heatmap",
        "section": "collaboration",
        "type": "indirect",
        "provenance": "reasoned-default",
        "derivation": "Each active day shaded by the AI-authored share of that day's commits: "
        "≥ 60% AI-heavy, ≥ 30% mixed, < 30% human-heavy; days without per-commit attribution "
        "show as activity-only (honest unknown).",
        "reasoning": "The 60/30 cutoffs are reasoned bands for mostly-AI vs mixed vs "
        "mostly-hand; we never guess a day's split when attribution is missing.",
        "basis": "aiRatio is Cursor per-commit attribution.",
    },
    # ── Lab ──
    {
        "id": "aiShare",
        "label": "AI-authored share",
        "section": "lab",
        "type": "direct",
        "provenance": "measured",
        "derivation": "AI-authored lines / (AI + human) lines over tracked commits.",
        "reasoning": "A counted authorship fact, not an estimate.",
        "basis": "Cursor scored commits.",
    },
    {
        "id": "solo_equivalent",
        "label": "Solo-equivalent time",
        "section": "lab",
        "type": "indirect",
        "provenance": "estimate",
        "derivation": "A research-anchored BAND (≈ 1.33–2× your measured hands-on hours, from "
        "literature reporting ~25–50% task-time savings with AI — evidence is mixed). "
        "Lab-only, labeled an estimate, never a score input.",
        "reasoning": "We can't measure your counterfactual, so we never pretend to — it's an "
        "explicit band with mixed-evidence caveats, to be recalibrated per-user over time.",
        "citations": ["metr"],
    },
]


def _bands() -> list[dict]:
    """Derive the level bands from scoring._get_level (the source of truth)."""
    seen: dict[str, dict] = {}
    for s in range(0, 101):
        lv = scoring._get_level(s)
        if lv["id"] not in seen:
            seen[lv["id"]] = {"id": lv["id"], "label": lv["label"], "color": lv["color"], "min": s}
    return sorted(seen.values(), key=lambda b: b["min"], reverse=True)


def _citations_for(keys: list[str]) -> list[dict]:
    return [{**CITATIONS[k], "key": k} for k in keys]


def build_spec() -> dict:
    """Assemble the full methodology spec — numbers live from the engine."""
    dims = scoring.score_dimensions({})  # weights present; scores None (no inputs)
    base = scoring._adapt_weights(dims, "")  # no mode → normalized base weights

    dimensions = []
    for dim_id in DIM_ORDER:
        d = dims[dim_id]
        meta = DIMENSION_META[dim_id]
        load_bearing = any(CITATIONS[k]["strength"] == "load-bearing" for k in meta["citations"])
        dimensions.append(
            {
                "id": dim_id,
                "name": d["name"],
                "weight": round(d["weight"], 3),
                "type": "indirect",
                # Construct grounded in load-bearing research → research-anchored;
                # otherwise the construct is sound but the scaling anchors are
                # reasoned defaults (the per-signal linear/inverse bands live in
                # scoring.py — an open question to hoist + validate).
                "provenance": "research-anchored" if load_bearing else "reasoned-default",
                "measures": meta["measures"],
                "signals": meta["signals"],
                "reasoning": meta["evidenceNote"],
                "evidenceNote": meta["evidenceNote"],
                "citations": _citations_for(meta["citations"]),
            }
        )

    modes = [
        {
            "id": "base",
            "label": "Base weighting",
            "line": "How the six dimensions weigh by default.",
            "weights": {k: round(v, 3) for k, v in base.items()},
        }
    ]
    for mode_id in MODE_ORDER:
        adapted = scoring._adapt_weights(dims, mode_id)
        modes.append(
            {
                "id": mode_id,
                "label": mode_id.replace("-", " "),
                "line": scoring._WORK_MODES.get(mode_id, {}).get("line", ""),
                "weights": {k: round(v, 3) for k, v in adapted.items()},
            }
        )

    return {
        "methodologyVersion": METHODOLOGY_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "taxonomyVersion": TAXONOMY_VERSION,
        "composite": {
            "formula": "composite = Σ(dimension_score × weight_for_your_mode) "
            "/ Σ(weights of scored dimensions)",
            "note": "Dimension weights adapt to your dominant work mode so the composite "
            "reflects excellence in how you actually build. Unmeasured dimensions are "
            "excluded, never zero-filled.",
        },
        "dimensions": dimensions,
        "modes": modes,
        "bands": _bands(),
        "dataSources": TOOL_COVERAGE,
        "provenanceLevels": PROVENANCE,
        "sectionLabels": SECTION_LABELS,
        "metrics": [{**m, "citations": _citations_for(m.get("citations", []))} for m in METRICS],
        "scope": SCOPE,
        "openQuestions": OPEN_QUESTIONS,
    }
