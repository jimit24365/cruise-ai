#!/usr/bin/env python3
"""
nextmillionai scoring engine
Ports the JavaScript scoring engine from intent-cursor-extension/lib/scoring/

Modules ported:
  - dimensions.js  -> score_* functions, score_dimensions()
  - archetypes.js  -> compute_archetypes()
  - categories.js  -> derive_titles(), detect_anti_patterns(), assess_trajectory()
  - engine.js      -> score_profile()
"""

import json
import sys
import time

from nextmillionai.schema import SCHEMA_VERSION, TAXONOMY_VERSION

# ── Helper functions ──────────────────────────────────────────────────────────


def clamp(v, lo=0, hi=100):
    """Clamp and round a value to [lo, hi]."""
    return max(lo, min(hi, round(v)))


def linear(val, floor, ceiling):
    """Map val from [floor, ceiling] to [0, 100]. Values outside are clamped."""
    if val <= floor:
        return 0
    if val >= ceiling:
        return 100
    return ((val - floor) / (ceiling - floor)) * 100


def inverse(val, best, worst):
    """Inverse scale: best -> 100, worst -> 0."""
    if val <= best:
        return 100
    if val >= worst:
        return 0
    return ((worst - val) / (worst - best)) * 100


def _avg(subs):
    """Average a list of sub-scores, or return None if empty."""
    if not subs:
        return None
    return clamp(sum(subs) / len(subs))


def _get(inp, key):
    """Safely get a value from the input dict, returning None if missing."""
    return inp.get(key)


# ── 6 DIMENSIONS ─────────────────────────────────────────────────────────────
# Each returns {"score": 0-100|None, "evidence": [...], "name": str,
#               "weight": float, "description": str}


def score_signal_clarity(inp):
    """
    DIMENSION 1: Signal Clarity (weight 0.18)
    Can they communicate with AI effectively?
    """
    subs = []

    if _get(inp, "firstShotAcceptRate") is not None:
        subs.append(linear(inp["firstShotAcceptRate"], 0.2, 0.85))

    if _get(inp, "avgTurnsPerTask") is not None:
        subs.append(inverse(inp["avgTurnsPerTask"], 1.5, 10))

    if _get(inp, "referenceUsageRate") is not None:
        subs.append(linear(inp["referenceUsageRate"], 0.05, 0.6))

    if _get(inp, "correctionConvergenceRate") is not None:
        subs.append(linear(inp["correctionConvergenceRate"], 0.3, 0.9))

    if _get(inp, "avgPromptWords") is not None:
        w = inp["avgPromptWords"]
        if w < 15:
            specificity = linear(w, 5, 15) * 0.6
        elif w <= 150:
            specificity = 60 + linear(w, 15, 80) * 0.4
        else:
            specificity = inverse(w, 150, 300) * 0.8 + 20
        subs.append(clamp(specificity))

    if _get(inp, "modelCount") is not None and inp["modelCount"] > 1:
        subs.append(linear(inp["modelCount"], 1, 5))

    score = _avg(subs)

    # Evidence
    ev = []
    if _get(inp, "firstShotAcceptRate") is not None:
        ev.append(f"{inp['firstShotAcceptRate'] * 100:.0f}% first-shot acceptance rate")
    if _get(inp, "avgTurnsPerTask") is not None:
        ev.append(f"{inp['avgTurnsPerTask']:.1f} avg turns per task")
    if _get(inp, "referenceUsageRate") is not None:
        ev.append(f"{inp['referenceUsageRate'] * 100:.0f}% of prompts include file/code references")
    if _get(inp, "modelCount") is not None:
        ev.append(f"{inp['modelCount']} distinct AI models used")

    return {
        "score": score,
        "evidence": ev,
        "name": "Signal Clarity",
        "weight": 0.18,
        "description": "How effectively they communicate intent to AI — prompt specificity, "
        "first-shot accuracy, and context utilization.",
    }


def score_build_stability(inp):
    """
    DIMENSION 2: Build Stability (weight 0.22)
    Does their AI-assisted output survive production?
    """
    subs = []

    if _get(inp, "aiLineSurvivalRate") is not None:
        subs.append(linear(inp["aiLineSurvivalRate"], 0.5, 0.95))

    if _get(inp, "errorFixRate") is not None:
        subs.append(linear(inp["errorFixRate"], 0.3, 0.95))

    if _get(inp, "testAfterAiRate") is not None:
        subs.append(linear(inp["testAfterAiRate"], 0.1, 0.7))

    if _get(inp, "errorsPerAiBlock") is not None:
        subs.append(inverse(inp["errorsPerAiBlock"], 0.01, 0.2))

    if _get(inp, "buildSuccessRate") is not None:
        subs.append(linear(inp["buildSuccessRate"], 0.3, 0.85))

    # Post-AI edit rate: 0% = blind trust (bad), 5-25% = healthy review, >50% = poor prompting
    if _get(inp, "postAiEditRate") is not None:
        r = inp["postAiEditRate"]
        if r < 0.02:
            quality = 30
        elif r <= 0.30:
            quality = 60 + linear(r, 0.05, 0.15) * 0.4
        else:
            quality = inverse(r, 0.30, 0.70) * 0.6 + 20
        subs.append(clamp(quality))

    # Qualified leverage: high AI output that ALSO survives = real stability
    if _get(inp, "leverageRatio") is not None and _get(inp, "aiLineSurvivalRate") is not None:
        qualified = inp["leverageRatio"] * inp["aiLineSurvivalRate"]
        subs.append(linear(qualified, 1.5, 40))

    score = _avg(subs)

    # Evidence
    ev = []
    if _get(inp, "aiLineSurvivalRate") is not None:
        ev.append(f"{inp['aiLineSurvivalRate'] * 100:.0f}% AI-generated lines survive in commits")
    if _get(inp, "errorFixRate") is not None:
        ev.append(f"{inp['errorFixRate'] * 100:.0f}% of introduced errors resolved")
    if _get(inp, "testAfterAiRate") is not None:
        ev.append(f"{inp['testAfterAiRate'] * 100:.0f}% of AI code followed by build/test")
    if _get(inp, "postAiEditRate") is not None:
        ev.append(f"{inp['postAiEditRate'] * 100:.0f}% human review/edit rate on AI output")
    if _get(inp, "totalScoredCommits") is not None:
        ev.append(f"{inp['totalScoredCommits']} commits with AI attribution scored")

    return {
        "score": score,
        "evidence": ev,
        "name": "Build Stability",
        "weight": 0.22,
        "description": "Whether AI-assisted code survives production — revert rates, error "
        "introduction, test discipline, and code survival.",
    }


def score_decision_weight(inp):
    """
    DIMENSION 3: Decision Weight (weight 0.18)
    Do they make good technical choices with AI?
    """
    subs = []

    if _get(inp, "planCount") is not None:
        subs.append(linear(inp["planCount"], 0, 40))

    if _get(inp, "avgPlanComplexity") is not None:
        subs.append(linear(inp["avgPlanComplexity"], 20, 200))

    if _get(inp, "referenceUsageRate") is not None:
        subs.append(linear(inp["referenceUsageRate"], 0.05, 0.6))

    # Plan-to-code ratio
    if (
        _get(inp, "planCount") is not None
        and _get(inp, "totalSessions") is not None
        and inp["totalSessions"] > 0
    ):
        plan_ratio = inp["planCount"] / inp["totalSessions"]
        subs.append(linear(plan_ratio, 0.05, 0.5))

    # Specs-first indication
    if _get(inp, "composerRatio") is not None:
        subs.append(linear(inp["composerRatio"], 0.3, 0.8))

    # Override rate (rejecting AI suggestions) signals independent judgment
    if _get(inp, "postAiEditRate") is not None:
        r = inp["postAiEditRate"]
        if r >= 0.05 and r <= 0.30:
            judgment = 70 + linear(r, 0.05, 0.20) * 30
        elif r < 0.05:
            judgment = 30
        else:
            judgment = 50
        subs.append(clamp(judgment))

    score = _avg(subs)

    # Evidence
    ev = []
    if _get(inp, "planCount") is not None:
        ev.append(f"{inp['planCount']} architecture plans created")
    if _get(inp, "avgPlanComplexity") is not None:
        ev.append(f"{round(inp['avgPlanComplexity'])} avg lines per architecture plan")
    if _get(inp, "referenceUsageRate") is not None:
        ev.append(f"{inp['referenceUsageRate'] * 100:.0f}% reference-rich prompts")
    if _get(inp, "composerRatio") is not None:
        ev.append(f"{inp['composerRatio'] * 100:.0f}% agent/composer mode usage")

    return {
        "score": score,
        "evidence": ev,
        "name": "Decision Weight",
        "weight": 0.18,
        "description": "Quality of architectural and technical "
        "decisions — planning before building, "
        "alternatives considered, and decisions that stick.",
    }


def score_recovery_velocity(inp):
    """
    DIMENSION 4: Recovery Velocity (weight 0.15)
    When AI fails, how fast do they recover?
    """
    subs = []

    if _get(inp, "errorFixRate") is not None:
        subs.append(linear(inp["errorFixRate"], 0.3, 0.95))

    if _get(inp, "correctionConvergenceRate") is not None:
        subs.append(linear(inp["correctionConvergenceRate"], 0.3, 0.9))

    if _get(inp, "errorsPerAiBlock") is not None:
        subs.append(inverse(inp["errorsPerAiBlock"], 0.01, 0.2))

    # Debug-to-generate ratio
    if (
        _get(inp, "terminalCommandCount") is not None
        and _get(inp, "totalAiCodeBlocks") is not None
        and inp["totalAiCodeBlocks"] > 0
    ):
        debug_ratio = inp["terminalCommandCount"] / (inp["totalAiCodeBlocks"] / 100)
        subs.append(linear(debug_ratio, 0.5, 5))

    # Error resolution speed proxy
    if _get(inp, "errorFixRate") is not None and _get(inp, "errorsPerAiBlock") is not None:
        recovery_quality = inp["errorFixRate"] * (1 - min(1, inp["errorsPerAiBlock"] * 5))
        subs.append(linear(recovery_quality, 0.2, 0.9))

    score = _avg(subs)

    # Evidence
    ev = []
    if _get(inp, "errorFixRate") is not None:
        ev.append(f"{inp['errorFixRate'] * 100:.0f}% error resolution rate")
    if _get(inp, "errorsPerAiBlock") is not None:
        ev.append(f"{inp['errorsPerAiBlock']:.2f} errors per AI block")
    if _get(inp, "correctionConvergenceRate") is not None:
        ev.append(f"{inp['correctionConvergenceRate'] * 100:.0f}% correction convergence")
    if _get(inp, "terminalCommandCount") is not None:
        ev.append(f"{inp['terminalCommandCount']} terminal commands (debugging signal)")

    return {
        "score": score,
        "evidence": ev,
        "name": "Recovery Velocity",
        "weight": 0.15,
        "description": "How quickly they detect and recover from AI errors — systematic debugging, "
        "pre-commit catches, and post-recovery stability.",
    }


def score_context_command(inp):
    """
    DIMENSION 5: Context Command (weight 0.12)
    Do they maintain continuity across tools and time?
    """
    subs = []

    if _get(inp, "referenceUsageRate") is not None:
        subs.append(linear(inp["referenceUsageRate"], 0.1, 0.65))

    # NOTE: planCount/avgPlanComplexity deliberately removed (v0.2.0).
    # Planning signals feed Decision Weight ONLY — they are not counted here
    # as universal virtues (SCORING-METHODOLOGY §7).

    # Checkpoint frequency
    if (
        _get(inp, "totalScoredCommits") is not None
        and _get(inp, "totalSessions") is not None
        and inp["totalSessions"] > 0
    ):
        checkpoint_freq = inp["totalScoredCommits"] / inp["totalSessions"]
        subs.append(linear(checkpoint_freq, 0.2, 2.0))

    # Cross-project breadth
    if _get(inp, "projectCount") is not None:
        subs.append(linear(inp["projectCount"], 1, 12))

    # First-shot x reference synergy
    if _get(inp, "firstShotAcceptRate") is not None and _get(inp, "referenceUsageRate") is not None:
        synergy = (inp["firstShotAcceptRate"] * inp["referenceUsageRate"]) * 200
        subs.append(clamp(synergy))

    # AI usage span
    if _get(inp, "aiUsageSpanDays") is not None:
        subs.append(linear(inp["aiUsageSpanDays"], 7, 180))

    # MCP / context bridging (RAG folded in as sub-signal). Reward-only:
    # counted only when MCP is actually configured, so a genuine zero never
    # drags the dimension. Servers are counted across every consented client
    # (Claude Code + Cursor + Claude Desktop), deduped — see count_mcp_servers.
    if (_get(inp, "mcpServerCount") or 0) > 0:
        subs.append(linear(inp["mcpServerCount"], 0, 5))

    # MCP usage: actual mcp__* tool calls are context bridging in action —
    # stronger evidence than mere config presence. Reward-only.
    if (_get(inp, "mcpToolCalls") or 0) > 0:
        subs.append(linear(inp["mcpToolCalls"], 0, 50))

    # Session continuity via deep sessions
    if _get(inp, "deepSessionCount") is not None and _get(inp, "totalSessions") is not None:
        if inp["totalSessions"] > 0:
            deep_ratio = inp["deepSessionCount"] / inp["totalSessions"]
            subs.append(linear(deep_ratio, 0.1, 0.6))

    # v0.4.0: cross-surface context — carrying work across MULTIPLE AI
    # surfaces with real parsed sessions. USAGE, never detection: a tool
    # that is merely installed contributes nothing here. Counted only
    # when breadth exists (>1), so single-surface profiles are unchanged.
    if (_get(inp, "activeSurfaceCount") or 0) > 1:
        subs.append(linear(inp["activeSurfaceCount"], 1, 5))

    score = _avg(subs)

    # Evidence
    ev = []
    if _get(inp, "referenceUsageRate") is not None:
        ev.append(f"{inp['referenceUsageRate'] * 100:.0f}% reference-rich prompts")
    if _get(inp, "projectCount") is not None:
        ev.append(f"{inp['projectCount']} projects with maintained context")
    if _get(inp, "aiUsageSpanDays") is not None:
        ev.append(f"{inp['aiUsageSpanDays']} days of continuous AI usage history")
    if _get(inp, "mcpServerCount") is not None and inp["mcpServerCount"] > 0:
        ev.append(f"{inp['mcpServerCount']} MCP servers bridging context")
    if (_get(inp, "mcpToolCalls") or 0) > 0:
        ev.append(f"{inp['mcpToolCalls']} MCP tool calls bridging context")
    if _get(inp, "deepSessionCount") is not None and inp["deepSessionCount"] > 0:
        ev.append(f"{inp['deepSessionCount']} deep sessions (>30 min)")
    if (_get(inp, "activeSurfaceCount") or 0) > 1:
        ev.append(
            f"{inp['activeSurfaceCount']} AI surfaces with real sessions (usage, not installs)"
        )

    return {
        "score": score,
        "evidence": ev,
        "name": "Context Command",
        "weight": 0.12,
        "description": "How effectively they maintain context across "
        "sessions and tools — reference usage, "
        "MCP bridging, session continuity, and retrieval patterns.",
    }


def score_orchestration_range(inp):
    """
    DIMENSION 6: Orchestration Range (weight 0.15)
    Can they operate across the multi-agent ecosystem?
    """
    subs = []

    if _get(inp, "uniqueToolCount") is not None:
        subs.append(linear(inp["uniqueToolCount"], 1, 10))

    if _get(inp, "composerRatio") is not None:
        subs.append(linear(inp["composerRatio"], 0.1, 0.8))

    if _get(inp, "agentModeRatio") is not None:
        subs.append(linear(inp["agentModeRatio"], 0.1, 0.7))

    # Reward-only: a genuine zero never drags orchestration (matches Context
    # Command). Count spans all consented clients, deduped (count_mcp_servers).
    if (_get(inp, "mcpServerCount") or 0) > 0:
        subs.append(linear(inp["mcpServerCount"], 0, 5))

    if _get(inp, "cliAiToolCount") is not None:
        subs.append(linear(inp["cliAiToolCount"], 0, 4))

    if _get(inp, "cliAiCommandCount") is not None:
        subs.append(linear(inp["cliAiCommandCount"], 0, 80))

    if _get(inp, "maxParallelAgents") is not None:
        subs.append(linear(inp["maxParallelAgents"], 1, 5))

    # v0.4.0: subagent dispatches — directing a fleet from one seat is
    # orchestration evidence (ledger-backed Task dispatches). Counted
    # only when present: absence is already captured by
    # maxParallelAgents/agentModeRatio, so zero never dilutes.
    if (_get(inp, "subagentDispatches") or 0) > 0:
        subs.append(linear(inp["subagentDispatches"], 0, 60))
    if (_get(inp, "sessionsWithSubagents") or 0) > 0:
        subs.append(linear(inp["sessionsWithSubagents"], 0, 15))

    if _get(inp, "mcpToolCalls") is not None and inp["mcpToolCalls"] > 0:
        subs.append(linear(inp["mcpToolCalls"], 0, 50))

    if _get(inp, "modelCount") is not None:
        subs.append(linear(inp["modelCount"], 1, 5))

    if _get(inp, "totalSessions") is not None:
        subs.append(linear(inp["totalSessions"], 5, 200))

    # Multi-surface bonus: IDE + terminal + CLI AI + MCP = 4 surfaces
    surfaces = 0
    if (inp.get("totalAiCodeBlocks") or 0) > 0:
        surfaces += 1
    if (inp.get("terminalCommandCount") or 0) > 0:
        surfaces += 1
    if (inp.get("cliAiToolCount") or 0) > 0:
        surfaces += 1
    if (inp.get("mcpServerCount") or 0) > 0:
        surfaces += 1
    if surfaces > 1:
        subs.append(linear(surfaces, 1, 4))

    score = _avg(subs)

    # Evidence
    ev = []
    if _get(inp, "uniqueToolCount") is not None:
        ev.append(f"{inp['uniqueToolCount']} distinct AI tool types used")
    if _get(inp, "mcpServerCount") is not None:
        ev.append(f"{inp['mcpServerCount']} MCP servers configured")
    if _get(inp, "cliAiToolCount") is not None and inp["cliAiToolCount"] > 0:
        tools_str = ""
        if inp.get("cliAiTools"):
            tools_str = f" ({', '.join(inp['cliAiTools'])})"
        ev.append(f"{inp['cliAiToolCount']} CLI AI tools{tools_str}")
    if _get(inp, "agentModeRatio") is not None:
        ev.append(f"{inp['agentModeRatio'] * 100:.0f}% agent mode usage")
    if (_get(inp, "subagentDispatches") or 0) > 0:
        ev.append(
            f"{inp['subagentDispatches']} subagent dispatches across "
            f"{inp.get('sessionsWithSubagents', 0)} sessions"
        )
    if _get(inp, "totalSessions") is not None:
        proj = inp.get("projectCount", "?")
        ev.append(f"{inp['totalSessions']} AI sessions across {proj} projects")

    return {
        "score": score,
        "evidence": ev,
        "name": "Orchestration Range",
        "weight": 0.15,
        "description": "Multi-tool, multi-model, multi-agent fluency — MCP servers, CLI tools, "
        "strategic model selection, and cross-tool workflows.",
    }


def score_dimensions(inp):
    """
    Score all 6 dimensions.
    Returns dict of {dim_id: {score, evidence, name, weight, description}}.
    """
    scorers = [
        ("signal_clarity", score_signal_clarity),
        ("build_stability", score_build_stability),
        ("decision_weight", score_decision_weight),
        ("recovery_velocity", score_recovery_velocity),
        ("context_command", score_context_command),
        ("orchestration_range", score_orchestration_range),
    ]
    results = {}
    for dim_id, scorer in scorers:
        results[dim_id] = scorer(inp)
    return results


# ── 8 ARCHETYPES ─────────────────────────────────────────────────────────────


def _get_level(score):
    """Assign level based on score thresholds."""
    if score is None:
        return {"id": "undetected", "label": "No Signal", "color": "#3f3f46"}
    if score >= 85:
        return {"id": "elite", "label": "Elite", "color": "#6ee7b7"}
    if score >= 70:
        return {"id": "advanced", "label": "Advanced", "color": "#67e8f9"}
    if score >= 55:
        return {"id": "proficient", "label": "Proficient", "color": "#fbbf24"}
    if score >= 35:
        return {"id": "developing", "label": "Developing", "color": "#a1a1aa"}
    return {"id": "emerging", "label": "Emerging", "color": "#52525b"}


ARCHETYPE_META = {
    # ── Frontier tier ──
    "agent_builder": {
        "name": "Agent Harness Builder",
        "tier": "frontier",
        "icon": "\u25ce",  # ◎
        "color": "#67e8f9",
        "soughtBy": "AI platform teams, agent infrastructure",
        "description": "Builds and supervises the agent loop — parallel-agent "
        "management, output gating, MCP bridges.",
    },
    "integration_architect": {
        "name": "Integration / MCP Engineer",
        "tier": "frontier",
        "icon": "\u2b21",  # ⬡
        "color": "#7eb8d4",
        "soughtBy": "Enterprise AI, API-first companies",
        "description": "Wires MCP servers, connectors, cross-service orchestration. Drives "
        "Orchestration Range and Context Command.",
    },
    "multi_agent_orchestrator": {
        "name": "Multi-Agent Orchestrator",
        "tier": "frontier",
        "icon": "\u2637",  # ☷
        "color": "#38bdf8",
        "soughtBy": "AI-native teams, fleet-scale engineering",
        "description": "Runs and coordinates multiple agents in parallel — "
        "worktrees, subagents, fleet management.",
    },
    "context_engineer": {
        "name": "Context Engineer",
        "tier": "frontier",
        "icon": "\u2386",  # ⎆
        "color": "#818cf8",
        "soughtBy": "AI product teams, developer experience, platform engineering",
        "description": "Engineers context, rules, memory, retrieval, long-session state. Core "
        "driver of Context Command and Signal Clarity.",
    },
    "automation_engineer": {
        "name": "Production Guardian",
        "tier": "frontier",
        "icon": "\u2699",  # ⚙
        "color": "#f97316",
        "soughtBy": "DevOps, CI/CD teams, infrastructure, SRE",
        "description": "Safety rails, production-risk instinct, review-heavy. High Recovery "
        "Velocity and Build Stability through test discipline.",
    },
    # ── Application tier ──
    "system_thinker": {
        "name": "System Thinker",
        "tier": "application",
        "icon": "\u2394",  # ⎔
        "color": "#fbbf24",
        "soughtBy": "Architecture teams, staff+ roles, technical leadership",
        "description": "Architecture-first, plan-then-build — high Decision Weight, "
        "systematic design with AI assistance.",
    },
    "rapid_prototyper": {
        "name": "Rapid Prototyper",
        "tier": "application",
        "icon": "\u2197",  # ↗
        "color": "#a78bfa",
        "soughtBy": "Startups, 0\u21921 product teams, hackathon culture",
        "description": "Concept to working app — high leverage, features-heavy. "
        "Agent leverage is a strength.",
    },
    "code_weaver": {
        "name": "Code Weaver",
        "tier": "application",
        "icon": "\u25c7",  # ◇
        "color": "#6ee7b7",
        "soughtBy": "Quality-focused teams, fintech, healthcare tech",
        "description": "Clean, surviving AI code — high test coverage, strong "
        "edit survival, thorough review.",
    },
    "cli_native": {
        "name": "CLI-Native Builder",
        "tier": "application",
        "icon": "\u25b8",  # ▸
        "color": "#e879f9",
        "soughtBy": "DevOps, infrastructure, CLI-heavy teams",
        "description": "Uses AI coding tools beyond the editor — expands "
        "Orchestration Range through CLI AI mastery.",
    },
}


def _score_agent_builder(inp):
    subs = []
    if _get(inp, "agentModeRatio") is not None:
        subs.append(linear(inp["agentModeRatio"], 0.3, 0.85))
    if _get(inp, "planCount") is not None:
        subs.append(linear(inp["planCount"], 5, 50))
    if _get(inp, "composerRatio") is not None:
        subs.append(linear(inp["composerRatio"], 0.5, 0.95))
    if _get(inp, "mcpServerCount") is not None:
        subs.append(linear(inp["mcpServerCount"], 1, 5))
    if _get(inp, "totalSessions") is not None:
        subs.append(linear(inp["totalSessions"], 20, 200))
    return _avg(subs)


def _evidence_agent_builder(inp):
    ev = []
    if _get(inp, "agentModeRatio") is not None:
        ev.append(f"{inp['agentModeRatio'] * 100:.0f}% agent mode usage")
    if _get(inp, "planCount") is not None:
        ev.append(f"{inp['planCount']} architecture plans generated")
    if _get(inp, "mcpServerCount") is not None:
        ev.append(f"{inp['mcpServerCount']} MCP integrations built")
    return ev


def _score_integration_architect(inp):
    subs = []
    if _get(inp, "uniqueToolCount") is not None:
        subs.append(linear(inp["uniqueToolCount"], 2, 10))
    if _get(inp, "mcpServerCount") is not None:
        subs.append(linear(inp["mcpServerCount"], 0, 5))
    if _get(inp, "projectCount") is not None:
        subs.append(linear(inp["projectCount"], 3, 15))
    if _get(inp, "languageCount") is not None:
        subs.append(linear(inp["languageCount"], 2, 8))
    if _get(inp, "composerRatio") is not None:
        subs.append(linear(inp["composerRatio"], 0.3, 0.8))
    return _avg(subs)


def _evidence_integration_architect(inp):
    ev = []
    if _get(inp, "uniqueToolCount") is not None:
        ev.append(f"{inp['uniqueToolCount']} tool types integrated")
    if _get(inp, "mcpServerCount") is not None:
        ev.append(f"{inp['mcpServerCount']} MCP servers configured")
    if _get(inp, "projectCount") is not None:
        ev.append(f"{inp['projectCount']} cross-project breadth")
    if _get(inp, "languageCount") is not None:
        ev.append(f"{inp['languageCount']} languages in AI-assisted work")
    return ev


def _score_code_weaver(inp):
    subs = []
    if _get(inp, "aiLineSurvivalRate") is not None:
        subs.append(linear(inp["aiLineSurvivalRate"], 0.6, 0.98))
    if _get(inp, "errorFixRate") is not None:
        subs.append(linear(inp["errorFixRate"], 0.5, 0.98))
    if _get(inp, "postAiEditRate") is not None:
        r = inp["postAiEditRate"]
        if r >= 0.05 and r <= 0.25:
            subs.append(clamp(80 + linear(r, 0.05, 0.15) * 20))
        elif r < 0.05:
            subs.append(clamp(40))
        else:
            subs.append(clamp(60 - linear(r, 0.25, 0.6) * 40))
    if _get(inp, "totalScoredCommits") is not None:
        subs.append(linear(inp["totalScoredCommits"], 10, 100))
    return _avg(subs)


def _evidence_code_weaver(inp):
    ev = []
    if _get(inp, "aiLineSurvivalRate") is not None:
        ev.append(f"{inp['aiLineSurvivalRate'] * 100:.0f}% AI code survives in commits")
    if _get(inp, "errorFixRate") is not None:
        ev.append(f"{inp['errorFixRate'] * 100:.0f}% error fix rate")
    if _get(inp, "postAiEditRate") is not None:
        ev.append(f"{inp['postAiEditRate'] * 100:.0f}% post-AI edit rate (healthy review)")
    return ev


def _score_rapid_prototyper(inp):
    subs = []
    if _get(inp, "leverageRatio") is not None:
        subs.append(linear(inp["leverageRatio"], 5, 50))
    if _get(inp, "filesPerSession") is not None:
        subs.append(linear(inp["filesPerSession"], 5, 25))
    if _get(inp, "totalAiCodeBlocks") is not None:
        subs.append(linear(inp["totalAiCodeBlocks"], 1000, 30000))
    if _get(inp, "projectCount") is not None:
        subs.append(linear(inp["projectCount"], 3, 15))
    # Agent leverage is a positive signal (§9): high agent-mode ratio
    # and parallel agents raise this score, never lower it
    if _get(inp, "agentModeRatio") is not None:
        subs.append(linear(inp["agentModeRatio"], 0.2, 0.8))
    if _get(inp, "maxParallelAgents") is not None:
        subs.append(linear(inp["maxParallelAgents"], 1, 4))
    return _avg(subs)


def _evidence_rapid_prototyper(inp):
    ev = []
    if _get(inp, "leverageRatio") is not None:
        ev.append(f"{inp['leverageRatio']:.0f}x AI leverage ratio")
    if _get(inp, "totalAiCodeBlocks") is not None:
        ev.append(f"{inp['totalAiCodeBlocks']:,} AI code blocks shipped")
    if _get(inp, "projectCount") is not None:
        ev.append(f"{inp['projectCount']} projects built")
    return ev


def _score_system_thinker(inp):
    # NOTE: planCount/avgPlanComplexity removed (v0.2.0 §7).
    # Planning feeds Decision Weight only — System Thinker is scored by
    # reference usage, deliberate iteration, and architectural breadth.
    subs = []
    if _get(inp, "referenceUsageRate") is not None:
        subs.append(linear(inp["referenceUsageRate"], 0.2, 0.7))
    if _get(inp, "avgTurnsPerTask") is not None:
        subs.append(linear(inp["avgTurnsPerTask"], 2, 6))
    if _get(inp, "composerRatio") is not None:
        subs.append(linear(inp["composerRatio"], 0.3, 0.8))
    if _get(inp, "projectCount") is not None:
        subs.append(linear(inp["projectCount"], 2, 10))
    return _avg(subs)


def _evidence_system_thinker(inp):
    ev = []
    if _get(inp, "referenceUsageRate") is not None:
        ev.append(f"{inp['referenceUsageRate'] * 100:.0f}% reference-rich prompts")
    if _get(inp, "avgTurnsPerTask") is not None:
        ev.append(f"{inp['avgTurnsPerTask']:.1f} avg turns per task (deliberate iteration)")
    if _get(inp, "composerRatio") is not None:
        ev.append(f"{inp['composerRatio'] * 100:.0f}% agent/composer mode")
    return ev


def _score_automation_engineer(inp):
    subs = []
    if _get(inp, "testAfterAiRate") is not None:
        subs.append(linear(inp["testAfterAiRate"], 0.2, 0.8))
    if _get(inp, "buildSuccessRate") is not None:
        subs.append(linear(inp["buildSuccessRate"], 0.4, 0.9))
    if _get(inp, "terminalCommandCount") is not None:
        subs.append(linear(inp["terminalCommandCount"], 20, 200))
    if _get(inp, "cliAiToolCount") is not None:
        subs.append(linear(inp["cliAiToolCount"], 0, 4))
    return _avg(subs)


def _evidence_automation_engineer(inp):
    ev = []
    if _get(inp, "testAfterAiRate") is not None:
        ev.append(f"{inp['testAfterAiRate'] * 100:.0f}% test-after-AI rate")
    if _get(inp, "buildSuccessRate") is not None:
        ev.append(f"{inp['buildSuccessRate'] * 100:.0f}% build success rate")
    if _get(inp, "terminalCommandCount") is not None:
        ev.append(f"{inp['terminalCommandCount']} terminal commands tracked")
    return ev


def _score_cli_native(inp):
    subs = []
    if _get(inp, "cliAiToolCount") is not None:
        subs.append(linear(inp["cliAiToolCount"], 1, 5))
    if _get(inp, "cliAiCommandCount") is not None:
        subs.append(linear(inp["cliAiCommandCount"], 5, 100))
    if _get(inp, "terminalCommandCount") is not None:
        subs.append(linear(inp["terminalCommandCount"], 30, 300))
    if _get(inp, "modelCount") is not None:
        subs.append(linear(inp["modelCount"], 2, 6))
    return _avg(subs)


def _evidence_cli_native(inp):
    ev = []
    if _get(inp, "cliAiToolCount") is not None:
        ev.append(f"{inp['cliAiToolCount']} CLI AI tools used")
    if _get(inp, "cliAiCommandCount") is not None:
        ev.append(f"{inp['cliAiCommandCount']} AI CLI commands executed")
    if inp.get("cliAiTools"):
        ev.append(f"Tools: {', '.join(inp['cliAiTools'])}")
    return ev


def _score_multi_agent_orchestrator(inp):
    subs = []
    if _get(inp, "maxParallelAgents") is not None:
        subs.append(linear(inp["maxParallelAgents"], 1, 5))
    if _get(inp, "agentModeRatio") is not None:
        subs.append(linear(inp["agentModeRatio"], 0.3, 0.9))
    if _get(inp, "totalSessions") is not None:
        subs.append(linear(inp["totalSessions"], 20, 200))
    if _get(inp, "mcpToolCalls") is not None:
        subs.append(linear(inp["mcpToolCalls"], 0, 30))
    if _get(inp, "mcpServerCount") is not None:
        subs.append(linear(inp["mcpServerCount"], 0, 5))
    return _avg(subs)


def _evidence_multi_agent_orchestrator(inp):
    ev = []
    if _get(inp, "maxParallelAgents") is not None:
        ev.append(f"{inp['maxParallelAgents']} max parallel agents")
    if _get(inp, "agentModeRatio") is not None:
        ev.append(f"{inp['agentModeRatio'] * 100:.0f}% agent mode usage")
    if _get(inp, "mcpToolCalls") is not None and inp["mcpToolCalls"] > 0:
        ev.append(f"{inp['mcpToolCalls']} MCP tool calls in transcripts")
    return ev


def _score_context_engineer(inp):
    subs = []
    if _get(inp, "referenceUsageRate") is not None:
        subs.append(linear(inp["referenceUsageRate"], 0.1, 0.65))
    if _get(inp, "planCount") is not None:
        subs.append(linear(inp["planCount"], 5, 50))
    if _get(inp, "avgPlanComplexity") is not None:
        subs.append(linear(inp["avgPlanComplexity"], 30, 200))
    if _get(inp, "firstShotAcceptRate") is not None:
        subs.append(linear(inp["firstShotAcceptRate"], 0.3, 0.85))
    if _get(inp, "firstShotAcceptRate") is not None and _get(inp, "referenceUsageRate") is not None:
        synergy = (inp["firstShotAcceptRate"] * inp["referenceUsageRate"]) * 200
        subs.append(clamp(synergy))
    return _avg(subs)


def _evidence_context_engineer(inp):
    ev = []
    if _get(inp, "planCount") is not None:
        ev.append(f"{inp['planCount']} specs/plans written before coding")
    if _get(inp, "referenceUsageRate") is not None:
        ev.append(f"{inp['referenceUsageRate'] * 100:.0f}% reference-rich prompts")
    if _get(inp, "firstShotAcceptRate") is not None:
        ev.append(
            f"{inp['firstShotAcceptRate'] * 100:.0f}% first-shot acceptance (context quality)"
        )
    return ev


# Archetype scorer/evidence registry
_ARCHETYPE_SCORERS = {
    "agent_builder": (_score_agent_builder, _evidence_agent_builder),
    "integration_architect": (_score_integration_architect, _evidence_integration_architect),
    "multi_agent_orchestrator": (
        _score_multi_agent_orchestrator,
        _evidence_multi_agent_orchestrator,
    ),
    "context_engineer": (_score_context_engineer, _evidence_context_engineer),
    "automation_engineer": (_score_automation_engineer, _evidence_automation_engineer),
    "system_thinker": (_score_system_thinker, _evidence_system_thinker),
    "rapid_prototyper": (_score_rapid_prototyper, _evidence_rapid_prototyper),
    "code_weaver": (_score_code_weaver, _evidence_code_weaver),
    "cli_native": (_score_cli_native, _evidence_cli_native),
}

# Order: frontier tier first, then application tier (per TAXONOMY.md)
_ARCHETYPE_ORDER = [
    # Frontier
    "agent_builder",
    "integration_architect",
    "multi_agent_orchestrator",
    "context_engineer",
    "automation_engineer",
    # Application
    "system_thinker",
    "rapid_prototyper",
    "code_weaver",
    "cli_native",
]


def compute_archetypes(inp):
    """
    Compute all 9 archetypes. Returns list of archetype dicts sorted by score
    descending, filtered to those with a non-None score.
    """
    results = []
    for arch_id in _ARCHETYPE_ORDER:
        meta = ARCHETYPE_META[arch_id]
        scorer, evidencer = _ARCHETYPE_SCORERS[arch_id]
        score = scorer(inp)
        level = _get_level(score)
        evidence = evidencer(inp)
        if score is not None:
            results.append(
                {
                    "id": arch_id,
                    "name": meta["name"],
                    "icon": meta["icon"],
                    "color": meta["color"],
                    "description": meta["description"],
                    "soughtBy": meta["soughtBy"],
                    "score": score,
                    "level": level,
                    "evidence": evidence,
                }
            )
    results.sort(key=lambda a: a["score"], reverse=True)
    return results


# ── TITLES ────────────────────────────────────────────────────────────────────


def _get_archetype_score(archetypes, arch_id):
    """Get score for an archetype by id, returning 0 if not found."""
    for a in archetypes:
        if a["id"] == arch_id:
            return a.get("score") or 0
    return 0


# Each derived category: (id, name, trigger_fn, tagline, idealFor, emoji, rare, legendary)
def _build_derived_categories():
    """Build the DERIVED_CATEGORIES list matching JS categories.js."""
    return [
        # -- PRIMARY TITLES (from single dominant archetype) --
        {
            "id": "agentic_engineer",
            "name": "Agentic Engineer",
            "trigger": lambda archs: _get_archetype_score(archs, "agent_builder") >= 80,
            "tagline": "Commands AI agents as force multipliers",
            "idealFor": "AI-first startups, agent platform teams",
            "emoji": "\u25ce",  # ◎
            "rare": False,
            "legendary": False,
        },
        {
            "id": "systems_architect",
            "name": "AI Systems Architect",
            "trigger": lambda archs: _get_archetype_score(archs, "integration_architect") >= 80,
            "tagline": "Connects systems, APIs, and AI services at scale",
            "idealFor": "Enterprise AI, API-first companies, platform teams",
            "emoji": "\u2b21",  # ⬡
            "rare": False,
            "legendary": False,
        },
        {
            "id": "craft_engineer",
            "name": "AI Craft Engineer",
            "trigger": lambda archs: _get_archetype_score(archs, "code_weaver") >= 80,
            "tagline": "Produces clean, reviewed, production-surviving AI code",
            "idealFor": "Quality-focused teams, fintech, healthcare tech",
            "emoji": "\u25c7",  # ◇
            "rare": False,
            "legendary": False,
        },
        {
            "id": "velocity_engineer",
            "name": "AI Velocity Engineer",
            "trigger": lambda archs: _get_archetype_score(archs, "rapid_prototyper") >= 80,
            "tagline": "Ships at extreme speed with AI leverage",
            "idealFor": "Startups, 0\u21921 product teams, hackathon culture",
            "emoji": "\u2197",  # ↗
            "rare": False,
            "legendary": False,
        },
        {
            "id": "context_architect",
            "name": "Context Architect",
            "trigger": lambda archs: _get_archetype_score(archs, "context_engineer") >= 80,
            "tagline": "Engineers AI context for maximum first-shot accuracy",
            "idealFor": "AI product teams, developer experience, tooling",
            "emoji": "\u2386",  # ⎆
            "rare": False,
            "legendary": False,
        },
        {
            "id": "design_engineer",
            "name": "AI Design Engineer",
            "trigger": lambda archs: _get_archetype_score(archs, "system_thinker") >= 80,
            "tagline": "Plans architectures with AI before writing a line",
            "idealFor": "Architecture teams, staff+ roles, technical leadership",
            "emoji": "\u2394",  # ⎔
            "rare": False,
            "legendary": False,
        },
        {
            "id": "devops_ai",
            "name": "AI DevOps Engineer",
            "trigger": lambda archs: (
                _get_archetype_score(archs, "automation_engineer") >= 75
                or _get_archetype_score(archs, "cli_native") >= 75
            ),
            "tagline": "Automates pipelines, tests, and infra with AI",
            "idealFor": "DevOps, CI/CD teams, infrastructure, SRE",
            "emoji": "\u2699",  # ⚙
            "rare": False,
            "legendary": False,
        },
        # -- COMBINATION TITLES (from 2+ strong archetypes) --
        {
            "id": "full_stack_ai",
            "name": "Full-Stack AI Engineer",
            "trigger": lambda archs: (
                _get_archetype_score(archs, "agent_builder") >= 75
                and _get_archetype_score(archs, "code_weaver") >= 70
                and _get_archetype_score(archs, "rapid_prototyper") >= 70
            ),
            "tagline": "Builds, reviews, and ships AI-powered systems end-to-end",
            "idealFor": "Founding engineer roles, full-stack AI product teams",
            "emoji": "\u26a1",  # ⚡
            "rare": True,
            "legendary": False,
        },
        {
            "id": "ai_platform_lead",
            "name": "AI Platform Engineer",
            "trigger": lambda archs: (
                _get_archetype_score(archs, "agent_builder") >= 80
                and _get_archetype_score(archs, "integration_architect") >= 75
                and _get_archetype_score(archs, "system_thinker") >= 70
            ),
            "tagline": "Designs and builds multi-agent AI infrastructure",
            "idealFor": "AI platform teams, infrastructure leads, Series B+ startups",
            "emoji": "\U0001f537",  # 🔷
            "rare": True,
            "legendary": False,
        },
        {
            "id": "ai_craftmaster",
            "name": "AI Craft Master",
            "trigger": lambda archs: (
                _get_archetype_score(archs, "code_weaver") >= 80
                and _get_archetype_score(archs, "context_engineer") >= 75
                and _get_archetype_score(archs, "system_thinker") >= 70
            ),
            "tagline": "Meticulous quality through superior context and planning",
            "idealFor": "Security-critical, compliance, regulated industries",
            "emoji": "\U0001f48e",  # 💎
            "rare": True,
            "legendary": False,
        },
        {
            "id": "shipping_machine",
            "name": "AI Shipping Machine",
            "trigger": lambda archs: (
                _get_archetype_score(archs, "rapid_prototyper") >= 85
                and _get_archetype_score(archs, "agent_builder") >= 75
            ),
            "tagline": "Maximum velocity with agent orchestration",
            "idealFor": "YC startups, rapid growth teams, MVP builders",
            "emoji": "\U0001f680",  # 🚀
            "rare": True,
            "legendary": False,
        },
        # -- LEGENDARY TITLE --
        {
            "id": "ai_pioneer",
            "name": "AI Pioneer",
            "trigger": lambda archs: (
                len([a for a in archs if a.get("score") is not None]) >= 6
                and all(a["score"] >= 75 for a in archs if a.get("score") is not None)
                and any(a["score"] >= 90 for a in archs if a.get("score") is not None)
            ),
            "tagline": "Excellence across all dimensions of AI engineering",
            "idealFor": "Technical co-founder, CTO, principal engineer, AI research lead",
            "emoji": "\U0001f3c6",  # 🏆
            "rare": True,
            "legendary": True,
        },
        # -- BASELINE -- everyone who builds with AI holds this until a craft
        # specializes (score >= 80). A starting craft, not a lesser rung. Sorts
        # last, so a specialized kind always wins primaryTitle when earned.
        {
            "id": "ai_explorer",
            "name": "AI Explorer",
            "trigger": lambda archs: any((a.get("score") or 0) > 0 for a in archs),
            "tagline": "Building with AI — exploring toward a specialized craft",
            "idealFor": "Anyone building with AI; the starting craft, not a lesser one",
            "emoji": "◈",  # ◈
            "rare": False,
            "legendary": False,
            "baseline": True,
        },
    ]


DERIVED_CATEGORIES = _build_derived_categories()


def derive_titles(archetypes):
    """
    Derive titles from archetypes. Returns list of title dicts sorted:
    legendary first, then rare, then alphabetical.
    """
    titles = []
    for cat in DERIVED_CATEGORIES:
        if cat["trigger"](archetypes):
            titles.append(
                {
                    "id": cat["id"],
                    "name": cat["name"],
                    "tagline": cat["tagline"],
                    "idealFor": cat["idealFor"],
                    "emoji": cat["emoji"],
                    "rare": cat.get("rare", False),
                    "legendary": cat.get("legendary", False),
                    "baseline": cat.get("baseline", False),
                }
            )

    # Sort: legendary desc, rare desc, baseline LAST, then name alphabetically.
    # The baseline (AI Explorer) only becomes primaryTitle when no specialized
    # craft is earned — a specialized kind always wins.
    titles.sort(
        key=lambda a: (
            -int(a["legendary"]),
            -int(a["rare"]),
            int(a["baseline"]),
            a["name"],
        )
    )
    return titles


# ── ANTI-PATTERNS ─────────────────────────────────────────────────────────────


def detect_anti_patterns(dimensions, inp, work_mode=None):
    """
    Detect anti-patterns from dimension results and raw input.
    Archetype-aware (§10): a low test/plan rate is NOT flagged for
    prototyping/one-shot modes.
    Returns list of {id, name, icon, risk}.
    """
    results = []
    mode_id = ""
    if work_mode:
        mode_id = work_mode.get("dominant", {}).get("id", "")

    # Prototyping/one-shot modes get a pass on stability
    is_prototyping_mode = mode_id in ("One-Shot-Verify", "Prompt-Iterate")

    # 1. High Velocity, Low Stability
    # Skip for prototyping modes (low stability is expected and valid)
    sc = dimensions.get("signal_clarity", {})
    bs = dimensions.get("build_stability", {})
    if (
        not is_prototyping_mode
        and sc.get("score") is not None
        and sc["score"] >= 70
        and bs.get("score") is not None
        and bs["score"] < 30
    ):
        results.append(
            {
                "id": "high_velocity_low_stability",
                "name": "High Velocity, Low Stability",
                "icon": "\u26a0",  # ⚠
                "risk": "Ships technical debt at scale — fast output that breaks in production",
            }
        )

    # 2. AI Dependent
    rv = dimensions.get("recovery_velocity", {})
    if rv.get("score") is not None and rv["score"] < 25:
        results.append(
            {
                "id": "ai_dependent",
                "name": "AI Dependent",
                "icon": "\U0001f534",  # 🔴
                "risk": "Cannot function when AI is wrong — critical risk for any production role",
            }
        )

    # 3. Context Amnesiac
    cc = dimensions.get("context_command", {})
    if cc.get("score") is not None and cc["score"] < 30 and (inp.get("totalSessions") or 0) > 20:
        results.append(
            {
                "id": "context_amnesiac",
                "name": "Context Amnesiac",
                "icon": "\u26a0",  # ⚠
                "risk": "Productive per-session but zero continuity — wastes org "
                "time re-establishing context",
            }
        )

    # 4. Single-Tool Lock
    orch = dimensions.get("orchestration_range", {})
    if (
        orch.get("score") is not None
        and orch["score"] < 25
        and (inp.get("uniqueToolCount") or 1) <= 1
    ):
        results.append(
            {
                "id": "single_tool_lock",
                "name": "Single-Tool Lock",
                "icon": "\u26a0",  # ⚠
                "risk": "Cannot adapt to multi-agent future — obsolescence risk",
            }
        )

    # 5. Confident but Wrong
    sc2 = dimensions.get("signal_clarity", {})
    if (
        sc2.get("score") is not None
        and sc2["score"] < 35
        and (inp.get("totalAiCodeBlocks") or 0) > 5000
    ):
        results.append(
            {
                "id": "confident_but_wrong",
                "name": "Confident but Wrong",
                "icon": "\u26a0",  # ⚠
                "risk": "High AI usage volume with low effectiveness — the METR finding",
            }
        )

    return results


# ── TRAJECTORY ────────────────────────────────────────────────────────────────

TRAJECTORY = {
    "ACCELERATING": {
        "id": "accelerating",
        "label": "Accelerating",
        "description": "Signal density and sophistication increasing — actively leveling up.",
    },
    "STABLE": {
        "id": "stable",
        "label": "Stable",
        "description": "Consistent AI usage patterns — established working style.",
    },
    "PIVOTING": {
        "id": "pivoting",
        "label": "Pivoting",
        "description": "New tools or languages adopted, different work "
        "patterns — career transition.",
    },
    "DECLINING": {
        "id": "declining",
        "label": "Declining",
        "description": "Reduced AI engagement recently — may be between projects.",
    },
    "INSUFFICIENT": {
        "id": "insufficient",
        "label": "Insufficient Data",
        "description": "Not enough history to determine trajectory.",
    },
}


def assess_trajectory(inp):
    """
    Assess trajectory from input signals.
    Returns {id, label, description}.
    """
    if inp.get("aiUsageSpanDays") is None or inp["aiUsageSpanDays"] < 14:
        return TRAJECTORY["INSUFFICIENT"]

    # Signal density comparison: recent vs historical
    if (
        inp.get("recentSignalDensity") is not None
        and inp.get("historicalSignalDensity") is not None
    ):
        ratio = inp["recentSignalDensity"] / max(inp["historicalSignalDensity"], 0.01)
        if ratio > 1.3:
            return TRAJECTORY["ACCELERATING"]
        if ratio < 0.6:
            return TRAJECTORY["DECLINING"]

    # Model adoption recency
    if inp.get("recentModelCount") is not None and inp.get("historicalModelCount") is not None:
        if inp["recentModelCount"] > inp["historicalModelCount"]:
            return TRAJECTORY["ACCELERATING"]

    # Plan-first ratio increasing
    if inp.get("recentPlanRatio") is not None and inp.get("historicalPlanRatio") is not None:
        if inp["recentPlanRatio"] > inp["historicalPlanRatio"] * 1.3:
            return TRAJECTORY["ACCELERATING"]

    # Pivoting detection: new languages or tools in recent window
    if (
        inp.get("recentLanguageCount") is not None
        and inp.get("historicalLanguageCount") is not None
    ):
        if inp["recentLanguageCount"] > inp["historicalLanguageCount"] + 2:
            return TRAJECTORY["PIVOTING"]

    # Default to stable for established users
    return TRAJECTORY["STABLE"]


# ── WORK-MODE CLASSIFIER ─────────────────────────────────────────────────────

_WORK_MODES = {
    "Architect-First": {
        "line": "You plan before you build.",
        "key": "high plan-to-code ratio, specs-first",
    },
    "Prompt-Iterate": {
        "line": "You riff in fast cycles.",
        "key": "high prompt count, iterative refine",
    },
    "One-Shot-Verify": {
        "line": "You ship in one run, then verify.",
        "key": "agent-mode dominant, verify-after",
    },
    "Read-Understand-Modify": {
        "line": "You read deeply before you touch.",
        "key": "high file-read-to-edit ratio",
    },
    "Test-Driven-AI": {
        "line": "You make the tests pass.",
        "key": "test-before-code signals",
    },
    "Multi-Agent-Orchestrated": {
        "line": "You run a fleet.",
        "key": "multiple simultaneous agent sessions",
    },
    "Hybrid-Manual": {
        "line": "You hand-write what matters.",
        "key": "high manual-for-critical rate",
    },
    "Exploration-Research": {
        "line": "You build to understand.",
        "key": "high question-ratio, low generation",
    },
}


def classify_work_mode(inp):
    """Classify the builder's work mode from observable metrics.

    Returns {"dominant": {"id": str, "line": str}, "secondary": [...]}.
    No mode is "better" — each describes a valid way to build.
    """
    scores = {}

    plan_count = inp.get("planCount", 0) or 0
    total_sessions = inp.get("totalSessions", 0) or 0
    plan_ratio = plan_count / total_sessions if total_sessions > 0 else 0
    agent_ratio = inp.get("agentModeRatio", 0) or 0
    read_to_edit = inp.get("fileReadToEditRatio", 0) or 0
    test_rate = inp.get("testAfterAiRate", 0) or 0
    max_parallel = inp.get("maxParallelAgents", 0) or 0
    prompts_per_session = inp.get("avgPromptsPerSession", 0) or 0
    composer_ratio = inp.get("composerRatio", 0) or 0
    post_edit = inp.get("postAiEditRate", 0) or 0
    leverage = inp.get("leverageRatio", 0) or 0

    # Architect-First: plan-heavy, reference-rich
    scores["Architect-First"] = (
        linear(plan_ratio, 0.1, 0.5) * 0.5
        + linear(inp.get("referenceUsageRate", 0) or 0, 0.1, 0.5) * 0.3
        + linear(composer_ratio, 0.3, 0.8) * 0.2
    )

    # Prompt-Iterate: many prompts per session, short iteration cycles
    scores["Prompt-Iterate"] = (
        linear(prompts_per_session, 5, 20) * 0.5
        + linear(inp.get("avgTurnsPerTask", 0) or 0, 3, 10) * 0.3
        + inverse(plan_ratio, 0, 0.3) * 0.2
    )

    # One-Shot-Verify: agent-mode dominant, low turns, fast
    scores["One-Shot-Verify"] = (
        linear(agent_ratio, 0.3, 0.9) * 0.4
        + inverse(inp.get("avgTurnsPerTask", 5) or 5, 1.5, 8) * 0.3
        + linear(leverage, 5, 50) * 0.3
    )

    # Read-Understand-Modify: high read-to-edit ratio
    scores["Read-Understand-Modify"] = (
        linear(read_to_edit, 2, 8) * 0.6
        + linear(inp.get("referenceUsageRate", 0) or 0, 0.1, 0.5) * 0.4
    )

    # Test-Driven-AI: test signals
    scores["Test-Driven-AI"] = (
        linear(test_rate, 0.2, 0.7) * 0.5
        + linear(inp.get("buildSuccessRate", 0) or 0, 0.5, 0.9) * 0.3
        + linear(inp.get("terminalCommandCount", 0) or 0, 20, 200) * 0.2
    )

    # Multi-Agent-Orchestrated: parallel agents
    scores["Multi-Agent-Orchestrated"] = (
        linear(max_parallel, 2, 5) * 0.5
        + linear(agent_ratio, 0.3, 0.9) * 0.3
        + linear(inp.get("mcpToolCalls", 0) or 0, 0, 30) * 0.2
    )

    # Hybrid-Manual: high post-edit rate, low agent ratio
    scores["Hybrid-Manual"] = (
        linear(post_edit, 0.15, 0.5) * 0.4
        + inverse(agent_ratio, 0, 0.5) * 0.3
        + inverse(leverage, 1, 30) * 0.3
    )

    # Exploration-Research: high read, low generation
    scores["Exploration-Research"] = (
        linear(read_to_edit, 3, 10) * 0.4
        + inverse(leverage, 1, 20) * 0.3
        + linear(inp.get("projectCount", 0) or 0, 3, 15) * 0.3
    )

    # Sort by score, pick dominant + secondary
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    dominant_id = ranked[0][0]
    secondary = [{"id": m, "line": _WORK_MODES[m]["line"]} for m, s in ranked[1:4] if s > 20]

    return {
        "dominant": {
            "id": dominant_id,
            "line": _WORK_MODES[dominant_id]["line"],
        },
        "secondary": secondary,
    }


# ── ARCHETYPE-RELATIVE COMPOSITE WEIGHTS ─────────────────────────────────────

# Weight multipliers per work mode (SCORING-METHODOLOGY §3).
# Keys not listed default to 1.0.  After multiplication, weights renormalize.
_MODE_WEIGHT_MULTIPLIERS = {
    "One-Shot-Verify": {
        "signal_clarity": 1.4,
        "orchestration_range": 1.4,
        "recovery_velocity": 1.3,
        "decision_weight": 0.6,
        "build_stability": 0.6,
    },
    "Prompt-Iterate": {
        "signal_clarity": 1.4,
        "orchestration_range": 1.3,
        "recovery_velocity": 1.3,
        "decision_weight": 0.6,
        "build_stability": 0.7,
    },
    "Architect-First": {
        "decision_weight": 1.4,
        "context_command": 1.3,
        "orchestration_range": 0.7,
    },
    "Test-Driven-AI": {
        "build_stability": 1.4,
        "recovery_velocity": 1.3,
        "orchestration_range": 0.7,
    },
    "Multi-Agent-Orchestrated": {
        "orchestration_range": 1.4,
        "context_command": 1.3,
        "decision_weight": 0.6,
    },
    # Read-Understand-Modify, Hybrid-Manual, Exploration-Research: balanced
    # All multipliers bounded to [0.6, 1.4] so no dimension is erased.
}


def _adapt_weights(dims, mode_id):
    """Return dimension weights adapted to the dominant work mode."""
    multipliers = _MODE_WEIGHT_MULTIPLIERS.get(mode_id, {})
    adapted = {}
    for dim_id, dim_data in dims.items():
        base = dim_data["weight"]
        mult = multipliers.get(dim_id, 1.0)
        adapted[dim_id] = base * mult
    # Renormalize so weights sum to 1.0
    total = sum(adapted.values())
    if total > 0:
        adapted = {k: v / total for k, v in adapted.items()}
    return adapted


# ── PERCEPTUAL MAP ───────────────────────────────────────────────────────────


def compute_map(archetypes, inp):
    """Compute perceptual map position.

    X: Explorer (0) ↔ Architect (100)
    Y: Solo (0) ↔ Orchestrator (100)

    NO archetype subtracts from any axis.  Position is identity, not score.
    Agent leverage drives orchestrator-axis UP (SCORING-METHODOLOGY §8).
    """
    {a["id"]: a.get("score", 0) for a in archetypes}

    # X axis: exploration/iteration vs up-front structure
    architect_signals = []
    if inp.get("referenceUsageRate") is not None:
        architect_signals.append(linear(inp["referenceUsageRate"], 0, 0.6))
    if inp.get("planCount") is not None:
        architect_signals.append(linear(inp["planCount"], 0, 40))
    if inp.get("composerRatio") is not None:
        architect_signals.append(linear(inp["composerRatio"], 0.2, 0.8))

    explorer_signals = []
    if inp.get("agentModeRatio") is not None:
        explorer_signals.append(linear(inp["agentModeRatio"], 0, 0.8))
    if inp.get("leverageRatio") is not None:
        explorer_signals.append(linear(inp["leverageRatio"], 1, 50))
    if inp.get("filesPerSession") is not None:
        explorer_signals.append(linear(inp["filesPerSession"], 3, 25))

    arch_avg = sum(architect_signals) / len(architect_signals) if architect_signals else 50
    expl_avg = sum(explorer_signals) / len(explorer_signals) if explorer_signals else 50

    total_x = arch_avg + expl_avg
    x = (arch_avg / total_x * 100) if total_x > 0 else 50

    # Y axis: single-thread vs multi-tool/multi-agent coordination
    orchestrator_signals = []
    if inp.get("maxParallelAgents") is not None:
        orchestrator_signals.append(linear(inp["maxParallelAgents"], 1, 5))
    if inp.get("mcpServerCount") is not None:
        orchestrator_signals.append(linear(inp["mcpServerCount"], 0, 5))
    if inp.get("mcpToolCalls") is not None:
        orchestrator_signals.append(linear(inp["mcpToolCalls"], 0, 30))
    if inp.get("uniqueToolCount") is not None:
        orchestrator_signals.append(linear(inp["uniqueToolCount"], 1, 8))
    # Agent leverage drives Y UP (§9)
    if inp.get("agentModeRatio") is not None:
        orchestrator_signals.append(linear(inp["agentModeRatio"], 0.1, 0.8))

    solo_signals = []
    if inp.get("maxParallelAgents") is not None:
        solo_signals.append(inverse(inp["maxParallelAgents"], 1, 5))
    if inp.get("uniqueToolCount") is not None:
        solo_signals.append(inverse(inp["uniqueToolCount"], 1, 8))

    orch_avg = sum(orchestrator_signals) / len(orchestrator_signals) if orchestrator_signals else 50
    solo_avg = sum(solo_signals) / len(solo_signals) if solo_signals else 50

    total_y = orch_avg + solo_avg
    y = (orch_avg / total_y * 100) if total_y > 0 else 50

    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "xLabel": ["Explorer", "Architect"],
        "yLabel": ["Solo", "Orchestrator"],
    }


# ── GROWTH EDGE ──────────────────────────────────────────────────────────────


def compute_growth_edge(work_mode, dims, archetypes, inp):
    """Archetype-aware growth suggestion.

    Growth edges match the dominant mode (SCORING-METHODOLOGY §9).
    Never tells a prototyper to "plan more" or an explorer to "write more tests."
    """
    mode_id = work_mode.get("dominant", {}).get("id", "")

    # Find weakest scored dimension
    scored_dims = [(k, v) for k, v in dims.items() if v.get("score") is not None]
    if not scored_dims:
        return {"suggestion": "Connect more AI tools to build your profile.", "context": mode_id}

    scored_dims.sort(key=lambda x: x[1]["score"])
    weakest_id = scored_dims[0][0]
    scored_dims[0][1]

    # Mode-specific growth (never cross-mode prescriptions)
    suggestions = {
        "One-Shot-Verify": {
            "build_stability": "Tighten verification after the agent reports back.",
            "recovery_velocity": "Add a quick smoke-test step after each agent run.",
            "context_command": "Pin key context files in your agent prompts.",
            "_default": "Try running a second agent in parallel on a sub-task.",
        },
        "Prompt-Iterate": {
            "signal_clarity": "Front-load constraints in your first prompt to cut iterations.",
            "build_stability": "Add a test after your fastest iteration cycles.",
            "_default": "Reference specific files when you riff — context sharpens each cycle.",
        },
        "Architect-First": {
            "orchestration_range": "Scope one planned task for agent execution.",
            "recovery_velocity": "Let the agent draft, then review — trust the plan.",
            "_default": "Try shipping one small feature in one prompt cycle.",
        },
        "Multi-Agent-Orchestrated": {
            "signal_clarity": "Give each agent a focused scope to reduce cross-talk.",
            "build_stability": "Gate agent output with a verification agent.",
            "_default": "Route different subtasks to specialized models.",
        },
        "Test-Driven-AI": {
            "orchestration_range": "Wire a second AI tool into your test workflow.",
            "signal_clarity": "Specify expected test output in the prompt.",
            "_default": "Try agent mode for the test-write-verify loop.",
        },
        "Read-Understand-Modify": {
            "orchestration_range": "Use Grep+Read before Edit — you already do; add an MCP server.",
            "signal_clarity": "Reference the file you just read in your next prompt.",
            "_default": "Summarize what you found before asking for the edit.",
        },
        "Hybrid-Manual": {
            "orchestration_range": "Let the agent handle boilerplate while you "
            "handle the critical path.",
            "_default": "Increase agent leverage on the rote tasks you hand-write today.",
        },
        "Exploration-Research": {
            "signal_clarity": "Scope one open-ended task the way you scope your reviews.",
            "_default": "Build to ship one small artifact from your latest exploration.",
        },
    }

    mode_map = suggestions.get(mode_id, {})
    suggestion = mode_map.get(weakest_id, mode_map.get("_default", "Keep building."))

    return {"suggestion": suggestion, "context": mode_id}


# ── POSITIONING (BUILDER-MODEL.md) ───────────────────────────────────────────

# Build-domain marker sets — aligned with the labels the scanner actually
# emits (detect_tech_stack frameworks + aiFrameworks categories). The
# pre-fix sets used bare names ("Anthropic") that never matched the
# scanner's labels ("Anthropic SDK"), so LLM-integrated repos silently
# classified as plain products. Legacy bare names kept for old scan data.
AI_SYSTEMS_MARKERS = frozenset(
    {
        "LangChain",
        "LangGraph",
        "LlamaIndex",
        "CrewAI",
        "AutoGen",
        "Semantic Kernel",
        "Haystack",
        "Dify",
        "MCP SDK",
        "Claude Agent SDK",
        "OpenAI Agents",
    }
)
AI_PRODUCTS_MARKERS = frozenset(
    {
        "OpenAI SDK",
        "Anthropic SDK",
        "Gemini SDK",
        "Cohere SDK",
        "Mistral SDK",
        "Groq SDK",
        "LiteLLM",
        "Transformers",
        "HuggingFace Transformers",
        "Vercel AI SDK",
        "Replicate",
        "Ollama SDK",
        # legacy bare names (older scan data)
        "OpenAI",
        "Anthropic",
        "HuggingFace",
        "TensorFlow",
        "PyTorch",
    }
)


def compute_positioning(inp, git_data=None, code_intel=None, project_orchestration=None):
    """Compute positioning: leverageMode, buildDomain, techDomains.

    Positioning is a MAP, not a LADDER — no domain/stage ranks above another.
    See BUILDER-MODEL.md and SCORING-METHODOLOGY §8.

    Parameters
    ----------
    inp : dict
        NormalizedMetrics.
    git_data : dict or None
        Git scan data with projects/stack info.
    code_intel : dict or None
        Opt-in `assess --code` results. Provides manifest-grade
        buildDomain evidence, tagged "code scan" per BUILDER-MODEL.
    """
    # ── Leverage mode ──
    # Three stages (v1): prompting → harnessing → designs_the_loop
    # orchestrating/multi-agent is a sub-flavor inside designs_the_loop
    leverage_evidence = []
    leverage_mode = "prompting"  # default

    # Check for harnessing signals: CLAUDE.md, rules, MCP, hooks
    has_context_scaffolding = False
    has_mcp = (inp.get("mcpServerCount") or 0) > 0
    has_plans = (inp.get("planCount") or 0) > 5

    if git_data and git_data.get("projects"):
        for proj in git_data["projects"]:
            tools = proj.get("tools", [])
            if any(t in tools for t in ("CLAUDE.md", "Cursor Rules", "Cline Rules")):
                has_context_scaffolding = True
            if "MCP" in tools:
                has_mcp = True
            if "pre-commit" in tools:
                leverage_evidence.append("pre-commit hooks detected")

    if has_mcp:
        leverage_evidence.append(f"{inp.get('mcpServerCount', 0)} MCP servers configured")
    if has_context_scaffolding:
        leverage_evidence.append("Agent context files (CLAUDE.md/rules) detected")
    if has_plans:
        leverage_evidence.append(f"{inp.get('planCount', 0)} architecture plans")

    # designs_the_loop: multi-agent, high agent automation, or sustained
    # subagent dispatching (Task tool) — directing a fleet from one seat
    # IS designing the loop, even when the store no longer holds the old
    # parallel sessions.
    max_par = inp.get("maxParallelAgents") or 0
    agent_ratio = inp.get("agentModeRatio") or 0
    dispatches = inp.get("subagentDispatches") or 0
    dispatch_sessions = inp.get("sessionsWithSubagents") or 0
    sub_flavor = None

    dispatches_qualify = dispatches >= 10 and dispatch_sessions >= 3
    if max_par >= 3 or (agent_ratio > 0.5 and max_par >= 2) or dispatches_qualify:
        leverage_mode = "designs_the_loop"
        sub_flavor = "orchestrating"
        if dispatches_qualify:
            # The strongest evidence leads the list
            leverage_evidence.insert(
                0, f"{dispatches} subagent dispatches across {dispatch_sessions} sessions"
            )
        if max_par >= 2:
            leverage_evidence.append(
                f"{max_par} max parallel agents, {agent_ratio * 100:.0f}% agent mode"
            )
    elif has_context_scaffolding or has_mcp or has_plans:
        leverage_mode = "harnessing"
    else:
        leverage_evidence.append("Direct prompting workflow observed")

    # Nearest expansion (fit-gated: only if work decomposes)
    nearest_expansion = None
    if leverage_mode == "prompting" and has_plans:
        nearest_expansion = (
            "Your planning artifacts could feed a CLAUDE.md or rules file — try harnessing."
        )
    elif leverage_mode == "harnessing" and (inp.get("deepSessionCount") or 0) > 3:
        nearest_expansion = (
            "Your audit/review work decomposes cleanly — a state file could drive those runs."
        )

    positioning_leverage = {
        "current": leverage_mode,
        "evidence": leverage_evidence,
    }
    if sub_flavor:
        positioning_leverage["subFlavor"] = sub_flavor
    if nearest_expansion:
        positioning_leverage["adjacent"] = nearest_expansion

    # ── Build domain ──
    # ai_systems | ai_products | products — a FOOTPRINT across columns,
    # not a single bucket. Each repo is classified (deps declared, or
    # import/call-site verified when the opt-in code scan ran); primary
    # is the commit-weight-dominant column; distribution carries the rest.
    build_domain = "products"
    domain_evidence = []

    # Per-repo verified verdicts from the opt-in code scan, keyed by name
    ci_by_name: dict = {}
    if code_intel and code_intel.get("available"):
        for r in code_intel.get("repos") or []:
            if r.get("name") and r.get("buildDomain"):
                ci_by_name[r["name"]] = r

    def _classify_repo(proj: dict) -> tuple:
        """(domain, basis) for one repo. Code-scan verdicts (import/
        call-site verified) supersede declared-deps markers — a declared
        but never-imported SDK does NOT count."""
        ci_repo = ci_by_name.get(proj.get("name"))
        if ci_repo:
            verdict = ci_repo["buildDomain"]
            return verdict["domain"], "verified"
        markers = set(proj.get("frameworks") or []) | set(proj.get("aiFrameworks") or [])
        if markers & AI_SYSTEMS_MARKERS:
            return "ai_systems", "declared"
        if markers & AI_PRODUCTS_MARKERS:
            return "ai_products", "declared"
        return "products", "declared"

    domain_weights: dict = {}
    domain_projects: dict = {}
    domain_markers: dict = {}
    if git_data and git_data.get("projects"):
        for proj in git_data["projects"]:
            p_domain, basis = _classify_repo(proj)
            w = max(proj.get("commits_6m", 0), 1)
            domain_weights[p_domain] = domain_weights.get(p_domain, 0) + w
            domain_projects[p_domain] = domain_projects.get(p_domain, 0) + 1
            markers = set(proj.get("frameworks") or []) | set(proj.get("aiFrameworks") or [])
            if p_domain == "ai_systems":
                domain_markers.setdefault(p_domain, set()).update(markers & AI_SYSTEMS_MARKERS)
            elif p_domain == "ai_products":
                domain_markers.setdefault(p_domain, set()).update(markers & AI_PRODUCTS_MARKERS)

        total_w = sum(domain_weights.values()) or 1
        # Primary = where the commit-weighted mass actually sits (a map
        # reading, not a "highest tier" — domains are not ranked)
        _order = {"products": 0, "ai_products": 1, "ai_systems": 2}
        build_domain = max(domain_weights, key=lambda d: (domain_weights[d], _order[d]))

        for dom in ("ai_systems", "ai_products"):
            if domain_projects.get(dom):
                what = (
                    "agent/harness/MCP infrastructure"
                    if dom == "ai_systems"
                    else "an LLM wired behind product code"
                )
                marks = sorted(domain_markers.get(dom, set()))
                domain_evidence.append(
                    f"{domain_projects[dom]} repo{'s' if domain_projects[dom] != 1 else ''} "
                    f"ship {what}" + (f" ({', '.join(marks[:5])})" if marks else "")
                )
        if domain_projects.get("products") and build_domain == "products":
            domain_evidence.append("AI is the build tool, not the product, in most repos")

    # Legacy global code-scan raise — only when the scan provided no
    # per-repo verdicts (old scan shape). Can raise, never lower.
    if code_intel and code_intel.get("available") and not ci_by_name:
        scan_agent_fw = code_intel.get("agentFrameworks") or []
        scan_llm_sdks = code_intel.get("llmSdks") or []
        raised = None
        if scan_agent_fw:
            build_domain = "ai_systems"
            raised = (
                f"Agent frameworks in dependency manifests: {', '.join(scan_agent_fw)} (code scan)"
            )
        elif scan_llm_sdks and build_domain == "products":
            build_domain = "ai_products"
            raised = f"LLM SDKs in dependency manifests: {', '.join(scan_llm_sdks)} (code scan)"
        if raised:
            domain_evidence = [
                e for e in domain_evidence if not e.startswith("AI is the build tool")
            ]
            domain_evidence.append(raised)

    if not domain_evidence:
        domain_evidence.append("AI is the build tool, not the product")

    # ── Tech domains ──
    tech_domains = []
    if git_data and git_data.get("projects"):
        lang_counts: dict[str, int] = {}
        for proj in git_data["projects"]:
            commits = proj.get("commits_6m", 0)
            for lang in proj.get("languages", []):
                lang_counts[lang] = lang_counts.get(lang, 0) + max(commits, 1)

        total_weight = sum(lang_counts.values()) if lang_counts else 1
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
            pct = round(count / total_weight * 100)
            if pct >= 1:
                tech_domains.append(
                    {
                        "name": lang,
                        "weight": pct,
                        "evidence": [f"{count} commits"],
                    }
                )

    # ── Footprint: work is a DISTRIBUTION across domain x stage cells, ──
    # not a single verdict. Per-project: domain from framework markers,
    # stage from harness scaffolding presence; weighted by commit volume.
    # The orchestrating sub-flavor lifts the dominant domain's share into
    # designs_the_loop, because parallel-agent evidence is session-global.
    footprint: dict = {}
    if git_data and git_data.get("projects"):
        cells: dict[tuple, dict] = {}
        total_w = 0.0
        for proj in git_data["projects"]:
            tools = set(proj.get("tools", []))
            p_domain, _basis = _classify_repo(proj)
            scaffolded = bool(
                tools
                & {
                    "CLAUDE.md",
                    "Cursor Rules",
                    "Cline Rules",
                    "MCP",
                    "Skills",
                    "Agents",
                    "Commands",
                    "Hooks",
                }
            )
            # Per-repo loop evidence: this repo's sessions dispatched
            # subagents or ran parallel agents -> designs_the_loop here
            orch = (project_orchestration or {}).get(proj.get("path"), {})
            if orch.get("dispatches", 0) >= 3 or orch.get("maxParallel", 1) >= 2:
                p_stage = "designs_the_loop"
            elif scaffolded:
                p_stage = "harnessing"
            else:
                p_stage = "prompting"
            w = max(proj.get("commits_6m", 0), 1)
            cell = cells.setdefault((p_domain, p_stage), {"weight": 0.0, "projects": 0})
            cell["weight"] += w
            cell["projects"] += 1
            total_w += w

        if total_w > 0:
            footprint = {
                "cells": [
                    {
                        "domain": d,
                        "stage": s,
                        "weight": round(c["weight"] / total_w * 100),
                        "projects": c["projects"],
                    }
                    for (d, s), c in sorted(cells.items(), key=lambda kv: -kv[1]["weight"])
                    if round(c["weight"] / total_w * 100) >= 1
                ],
                "basis": "per-repo framework + scaffolding signals, weighted by commits",
            }

    result = {
        "leverageMode": positioning_leverage,
        "buildDomain": {
            "primary": build_domain,
            "evidence": domain_evidence,
        },
        "techDomains": tech_domains,
    }
    # The footprint across COLUMNS: share of commit-weighted work per
    # build domain — a builder shipping products AND AI-products shows
    # mass in both. Distribution, never a single verdict.
    if domain_weights:
        dist_total = sum(domain_weights.values()) or 1
        result["buildDomain"]["distribution"] = [
            {
                "domain": dom,
                "weight": round(domain_weights[dom] / dist_total * 100),
                "projects": domain_projects.get(dom, 0),
            }
            for dom in sorted(domain_weights, key=lambda d: -domain_weights[d])
            if round(domain_weights[dom] / dist_total * 100) >= 1
        ]
    if footprint:
        result["footprint"] = footprint
    return result


# Human-readable earn criteria + declarative requirement mirrors of the
# DERIVED_CATEGORIES triggers (for honest gap math in the kinds gallery).
_TITLE_REQS = {
    "agentic_engineer": ("all", [("agent_builder", 80)]),
    "systems_architect": ("all", [("integration_architect", 80)]),
    "craft_engineer": ("all", [("code_weaver", 80)]),
    "velocity_engineer": ("all", [("rapid_prototyper", 80)]),
    "context_architect": ("all", [("context_engineer", 80)]),
    "design_engineer": ("all", [("system_thinker", 80)]),
    "devops_ai": ("any", [("automation_engineer", 75), ("cli_native", 75)]),
    "full_stack_ai": (
        "all",
        [("agent_builder", 75), ("code_weaver", 70), ("rapid_prototyper", 70)],
    ),
    "ai_platform_lead": (
        "all",
        [("agent_builder", 80), ("integration_architect", 75), ("system_thinker", 70)],
    ),
    "ai_craftmaster": (
        "all",
        [("code_weaver", 80), ("context_engineer", 75), ("system_thinker", 70)],
    ),
    "shipping_machine": ("all", [("rapid_prototyper", 85), ("agent_builder", 75)]),
}

_ARCH_LABELS = {
    "agent_builder": "Agent Builder",
    "multi_agent_orchestrator": "Multi-Agent Orchestrator",
    "integration_architect": "Integration Architect",
    "code_weaver": "Code Weaver",
    "rapid_prototyper": "Rapid Prototyper",
    "system_thinker": "System Thinker",
    "automation_engineer": "Automation Engineer",
    "cli_native": "CLI-Native Builder",
    "context_engineer": "Context Engineer",
}


def build_titles_catalog(archetypes):
    """Every kind we measure, earned or not — kinds are different crafts,
    never rungs. Unearned kinds carry their honest criteria and the
    builder's current gap so 'where could I go next' is real, not vibes."""
    earned_ids = {t["id"] for t in derive_titles(archetypes)}
    scores = {a.get("id"): a.get("score") or 0 for a in archetypes}
    catalog = []
    for cat in DERIVED_CATEGORIES:
        entry = {
            "id": cat["id"],
            "name": cat["name"],
            "emoji": cat["emoji"],
            "tagline": cat["tagline"],
            "idealFor": cat["idealFor"],
            "rare": cat.get("rare", False),
            "legendary": cat.get("legendary", False),
            "baseline": cat.get("baseline", False),
            "earned": cat["id"] in earned_ids,
        }
        req = _TITLE_REQS.get(cat["id"])
        if req:
            mode, pairs = req
            joiner = " or " if mode == "any" else " + "
            entry["earnedBy"] = joiner.join(f"{_ARCH_LABELS[a]} \u2265 {m}" for a, m in pairs)
            if not entry["earned"]:
                gaps = [(a, m, max(0, m - scores.get(a, 0))) for a, m in pairs]
                if mode == "any":
                    a, m, g = min(gaps, key=lambda x: x[2])
                    entry["nearestGap"] = {"archetype": _ARCH_LABELS[a], "toGo": round(g)}
                else:
                    a, m, g = max(gaps, key=lambda x: x[2])
                    entry["nearestGap"] = {"archetype": _ARCH_LABELS[a], "toGo": round(g)}
        elif cat["id"] == "ai_pioneer":
            entry["earnedBy"] = "6+ archetypes scored \u2265 75, at least one \u2265 90"
        elif cat["id"] == "ai_explorer":
            entry["earnedBy"] = "Any AI coding activity \u2014 the baseline craft"
        catalog.append(entry)
    return catalog


# ── WRAPPED STATS ────────────────────────────────────────────────────────────


def build_wrapped_stats(inp, work_mode):
    """Assemble the wrapped stats (signal cards) from normalized metrics."""
    stats = {}
    stats["maxParallelAgents"] = inp.get("maxParallelAgents")
    stats["subagentDispatches"] = inp.get("subagentDispatches")
    stats["longestSessionMinutes"] = inp.get("longestSessionMinutes")
    stats["planModePercent"] = inp.get("planModePercent")
    stats["avgPromptsPerSession"] = inp.get("avgPromptsPerSession")
    stats["avgPromptWords"] = inp.get("avgPromptWords")
    stats["longestStreakDays"] = inp.get("longestStreakDays")
    stats["deepSessionCount"] = inp.get("deepSessionCount")
    stats["marathonSessionCount"] = inp.get("marathonSessionCount")
    stats["featureToFixRatio"] = inp.get("featureToFixRatio")
    stats["goToPrompt"] = None  # requires enrichment pass (raw text not read)
    stats["tools"] = inp.get("cliAiTools", [])
    stats["models"] = [inp["primaryModel"]] if inp.get("primaryModel") else []
    stats["totalActiveHours"] = inp.get("totalEstimatedHours")
    # Agent runtime: hours subagents worked under dispatches — measured
    # from their own transcripts, never mixed into the user's hours
    stats["agentRuntimeHours"] = inp.get("agentRuntimeHours")
    stats["subagentRunCount"] = inp.get("subagentRunCount")
    stats["peakProductivityHour"] = inp.get("peakProductivityHour")
    stats["workMode"] = work_mode.get("dominant", {}).get("line")
    return stats


# ── MAIN SCORING FUNCTION ────────────────────────────────────────────────────


def score_profile(scan_results):
    """
    Takes raw scan_results dict (from scanner.py's normalized output),
    returns scored profile dict.

    v0.2.0: archetype-relative composite, work-mode classifier, perceptual map,
    growth edge, wrapped stats.  No builder type is ranked above another.
    """
    inp = scan_results.get("normalized", scan_results)

    dims = score_dimensions(inp)

    # Classify work mode BEFORE composite (weights depend on it)
    work_mode = classify_work_mode(inp)
    mode_id = work_mode["dominant"]["id"]

    # Archetype-relative composite (§6): adapt weights to dominant mode
    adapted_weights = _adapt_weights(dims, mode_id)
    weighted_sum = 0
    total_weight = 0
    scored_count = 0
    for dim_id, d in dims.items():
        if d["score"] is not None:
            w = adapted_weights.get(dim_id, d["weight"])
            weighted_sum += d["score"] * w
            total_weight += w
            scored_count += 1

    composite = round(weighted_sum / total_weight) if total_weight > 0 else None

    # Build composite label — "strength index — <mode>" (§3)
    composite_label = None
    if composite is not None:
        composite_label = f"strength index \u2014 {mode_id}"

    archetypes = compute_archetypes(inp)
    titles = derive_titles(archetypes)
    titles_catalog = build_titles_catalog(archetypes)
    primary_title = titles[0] if titles else None
    anti_patterns = detect_anti_patterns(dims, inp, work_mode=work_mode)
    trajectory = assess_trajectory(inp)
    perceptual_map = compute_map(archetypes, inp)
    growth_edge = compute_growth_edge(work_mode, dims, archetypes, inp)
    wrapped_stats = build_wrapped_stats(inp, work_mode)

    # Positioning (BUILDER-MODEL.md): map, not ladder
    git_data = scan_results.get("git")
    positioning = compute_positioning(
        inp,
        git_data,
        scan_results.get("code_intel"),
        project_orchestration=scan_results.get("projectOrchestration"),
    )

    # Honest labels: the axes ARE Explorer/Architect x Solo/Orchestrator
    # (that is what compute_map computes). Build domain x leverage is the
    # positioning footprint, a separate structure — never a relabel of
    # different math.
    perceptual_map["xLabel"] = ["Explorer", "Architect"]
    perceptual_map["yLabel"] = ["Solo", "Orchestrator"]

    # Business Fit Map (report-only rendering; fit-to-context, not ranking)
    from nextmillionai.business_fit import build_business_fit

    business_fit = build_business_fit(archetypes)

    data_completeness = scored_count / 6
    data_completeness = round(data_completeness, 2)

    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "composite": composite,
        "compositeLabel": composite_label,
        "dominantMode": mode_id,
        "dimensions": dims,
        "archetypes": archetypes,
        "titles": titles,
        "titlesCatalog": titles_catalog,
        "primaryTitle": primary_title,
        "workMode": work_mode,
        "antiPatterns": anti_patterns,
        "trajectory": trajectory,
        "map": perceptual_map,
        "positioning": positioning,
        "businessFit": business_fit,
        "growthEdge": growth_edge,
        "wrappedStats": wrapped_stats,
        "dataCompleteness": data_completeness,
        "scoredAt": time.time(),
    }


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    from nextmillionai.paths import scan_results_path

    scan_path = sys.argv[1] if len(sys.argv) > 1 else str(scan_results_path())
    with open(scan_path) as f:
        scan = json.load(f)
    profile = score_profile(scan)
    print(json.dumps(profile, indent=2, ensure_ascii=False))
