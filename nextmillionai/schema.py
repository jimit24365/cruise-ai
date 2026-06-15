"""
nextmillionai -- Data-contract schema module.

Single source of truth for all data shapes flowing through the pipeline:
  scanner -> scoring -> profile_data -> hub/MCP

Two root artifacts:
  - ScanResult  (scan_results.json) — LOCAL ONLY, may contain paths/titles
  - Profile     (profile.json)      — shareable via build_shareable_profile()

Every root artifact carries ``schema_version``.
"""

from __future__ import annotations

import sys
import warnings
from typing import TypedDict

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    try:
        from typing_extensions import NotRequired
    except ImportError:
        # Python 3.10 without typing_extensions installed.
        # Annotations are deferred strings (from __future__ import annotations),
        # so this stub is only needed to keep the name resolvable at runtime.
        from typing import Any as NotRequired  # type: ignore[assignment]

# ── Schema version ───────────────────────────────────────────────────────────

# 1.1 (methodology 0.4.0): positioning.buildDomain gains `distribution`
# (footprint across columns); profile gains private `multiDevice` and
# `toolsDetail`; modelsSummary gains `localRuntimes`. Additive only.
SCHEMA_VERSION = "1.1"
TAXONOMY_VERSION = "0.2.1"  # +AI Explorer baseline kind (13 kinds)
# Mirrors the header of docs/SCORING-METHODOLOGY.md (drift-tested).
# Bumped on every formula/estimator change — the scan cache and the
# staleness check key off it so an engine change always recomputes
# EVERYTHING from scratch.
METHODOLOGY_VERSION = "0.4.4"  # MCP count: all clients (Cursor+Desktop), reward-only + usage-aware

# ── Scan sub-types ───────────────────────────────────────────────────────────


class ClaudeSession(TypedDict):
    sessionId: str
    project: str
    messages: int
    userMessages: int
    userWordCount: int
    toolCalls: int
    fileToolCalls: int
    terminalToolCalls: int
    mcpToolCalls: NotRequired[int]
    readToolCalls: NotRequired[int]
    writeToolCalls: NotRequired[int]
    models: list[str]
    gitBranch: NotRequired[str | None]
    version: NotRequired[str | None]
    earliest: NotRequired[str | None]
    latest: NotRequired[str | None]


class ClaudeCodeData(TypedDict):
    sessions: list[ClaudeSession]
    total_sessions: int
    total_messages: int
    models_used: dict[str, int]
    tool_calls: int
    earliest: NotRequired[str | None]
    latest: NotRequired[str | None]


class CursorAiCode(TypedDict):
    totalHashes: int
    bySource: dict[str, int]
    byModel: dict[str, int]
    earliest: NotRequired[str | None]
    latest: NotRequired[str | None]


class CursorScoredCommit(TypedDict):
    hash: str
    message: str
    date: NotRequired[str | None]
    aiPct: NotRequired[float | None]


class CursorScoredCommits(TypedDict):
    totalCommits: int
    totalLinesAdded: int
    totalAiLines: int
    totalComposerLines: int
    totalTabLines: int
    totalHumanLines: int
    avgAiPercentage: NotRequired[float | None]
    recentCommits: list[CursorScoredCommit]


class CursorConversationTopic(TypedDict):
    title: NotRequired[str | None]
    tldr: str
    model: NotRequired[str | None]
    mode: NotRequired[str | None]


class CursorConversations(TypedDict):
    totalConversations: int
    models: dict[str, int]
    modes: dict[str, int]
    recentTopics: list[CursorConversationTopic]


class CursorPlan(TypedDict):
    file: str
    title: str
    lineCount: int
    sizeBytes: int


class CursorPlans(TypedDict):
    totalPlans: int
    plans: list[CursorPlan]


class CursorTranscriptProject(TypedDict):
    project: str
    sessions: int
    sizeKB: float


class CursorTranscripts(TypedDict):
    totalSessions: int
    totalSizeKB: float
    projects: list[CursorTranscriptProject]


class CursorData(TypedDict, total=False):
    ai_code: CursorAiCode | None
    scored_commits: CursorScoredCommits | None
    conversations: CursorConversations | None
    plans: CursorPlans | None
    transcripts: CursorTranscripts | None


class CodexData(TypedDict):
    total_sessions: int
    path: str


class GitProject(TypedDict):
    path: str
    name: str
    commits_6m: int
    stack: list[str]
    languages: list[str]
    frameworks: list[str]
    tools: list[str]
    feat_commits: NotRequired[int]
    fix_commits: NotRequired[int]


class GitData(TypedDict):
    projects: list[GitProject]


class Summary(TypedDict):
    total_sessions: int
    total_ai_blocks: int
    total_scored_commits: int
    total_plans: int
    total_projects: int
    ai_usage_span_days: int
    models_used: list[str]


class NormalizedMetrics(TypedDict, total=False):
    """All ~40 normalized metrics fed to the scoring engine.

    Most fields are optional because scanners only populate what they detect.
    """

    totalSessions: int
    totalScoredCommits: int
    totalAiCodeBlocks: int
    projectCount: int
    aiUsageSpanDays: int
    modelCount: int
    planCount: int
    languageCount: int
    aiLineSurvivalRate: float
    leverageRatio: float
    composerRatio: float
    postAiEditRate: float
    agentModeRatio: float
    avgPlanComplexity: float
    avgTurnsPerTask: float
    filesPerSession: float
    terminalCommandCount: int
    avgPromptWords: int
    peakProductivityHour: int
    longestStreakDays: int
    avgPromptsPerSession: float
    totalEstimatedHours: float
    longestSessionMinutes: int
    primaryModel: str
    cliAiToolCount: int
    cliAiTools: list[str]
    cliAiCommandCount: int
    uniqueToolCount: int
    mcpServerCount: int
    firstShotAcceptRate: float
    referenceUsageRate: float
    errorFixRate: float
    errorsPerAiBlock: float
    buildSuccessRate: float
    correctionConvergenceRate: float
    testAfterAiRate: float
    recentSignalDensity: float
    historicalSignalDensity: float
    recentLanguageCount: int
    historicalLanguageCount: int
    recentModelCount: int
    historicalModelCount: int
    recentPlanRatio: float
    historicalPlanRatio: float
    # v0.2.0 taxonomy signals
    maxParallelAgents: int
    mcpToolCalls: int
    deepSessionCount: int
    fileReadToEditRatio: float
    featureToFixRatio: float
    planModePercent: float


# ── Signal matrix types ──────────────────────────────────────────────────────


class AgentSignal(TypedDict, total=False):
    session_count: int
    total_user_msgs: int
    total_tool_calls: int
    models: list[str]
    earliest: str | None
    latest: str | None


class ProjectSignal(TypedDict):
    project_path: str
    project_name: str
    agents: dict[str, AgentSignal]


class SignalMatrix(TypedDict):
    projects: list[ProjectSignal]


# ── Front-end view types ────────────────────────────────────────────────────


class ActivityDay(TypedDict, total=False):
    """Per-day activity record for the GitHub-style contribution graph."""

    date: str  # "2024-06-01"
    sessions: int
    activeMinutes: float | None
    tools: list[str]
    topProject: str | None
    aiRatio: float | None  # Real cursor ai-code ratio, or None


class ScannedProject(TypedDict, total=False):
    """Project discovered via git/adapter scan."""

    name: str
    languages: list[str]
    lastActive: str | None  # ISO date
    sessionCount: int


class StackSummary(TypedDict, total=False):
    """Aggregated tech stack from real repo signals."""

    languages: dict[str, float]  # {lang: weight 0.0-1.0}
    frameworks: list[str]


class ModelsSummary(TypedDict, total=False):
    """Model usage from observed model strings."""

    byModel: dict[str, int]
    primaryModel: str | None


# ── Root scan result ─────────────────────────────────────────────────────────


class ScanResult(TypedDict):
    """Root type for scan_results.json.  LOCAL ONLY — may contain paths and titles."""

    schema_version: str
    scanned_at: str
    tools_detected: list[str]
    summary: Summary
    claude_code: NotRequired[ClaudeCodeData | None]
    cursor: NotRequired[CursorData | None]
    codex: NotRequired[CodexData | None]
    git: NotRequired[GitData | None]
    normalized: NormalizedMetrics
    signal_matrix: NotRequired[SignalMatrix]
    # Front-end view data (derived, no raw text)
    activityByDay: NotRequired[list[ActivityDay]]
    projects: NotRequired[list[ScannedProject]]
    stack: NotRequired[StackSummary]
    models: NotRequired[ModelsSummary]


# ── Profile sub-types ────────────────────────────────────────────────────────


class DimensionResult(TypedDict):
    score: int | None
    evidence: list[str]
    name: str
    weight: float
    description: str


class Level(TypedDict):
    id: str
    label: str
    color: str


class ArchetypeResult(TypedDict):
    id: str
    name: str
    icon: str
    color: str
    description: str
    soughtBy: str
    score: int
    level: Level
    evidence: list[str]


class TitleResult(TypedDict):
    id: str
    name: str
    tagline: str
    idealFor: str
    emoji: str
    rare: bool
    legendary: bool


class AntiPattern(TypedDict):
    id: str
    name: str
    icon: str
    risk: str


class Trajectory(TypedDict):
    id: str
    label: str
    description: str


class WorkModeDominant(TypedDict):
    id: str
    line: str


class WorkMode(TypedDict):
    dominant: WorkModeDominant
    secondary: list[WorkModeDominant]


class MapPosition(TypedDict):
    x: float
    y: float
    xLabel: list[str]
    yLabel: list[str]


class GrowthEdge(TypedDict):
    suggestion: str
    context: str


class WrappedStats(TypedDict, total=False):
    maxParallelAgents: int | None
    longestSessionMinutes: int | None
    planModePercent: float | None
    avgPromptsPerSession: float | None
    avgPromptWords: int | None
    longestStreakDays: int | None
    deepSessionCount: int | None
    featureToFixRatio: float | None
    goToPrompt: str | None
    tools: list[str]
    models: list[str]
    totalActiveHours: float | None
    peakProductivityHour: int | None
    workMode: str | None


class Signals(TypedDict, total=False):
    ai_code_blocks: int
    scored_commits: int
    architecture_plans: int
    models_used: list[str]


class Verification(TypedDict):
    source: str
    verified: bool


class IdentityProject(TypedDict):
    name: str
    desc: str


class AssessmentMeta(TypedDict, total=False):
    """Metadata about how the assessment was produced."""

    schema_version: str
    taxonomy_version: str
    generated_at: str  # ISO timestamp
    sources_used: list[str]  # e.g. ["Claude Code", "git"]
    sessions: int
    dateRange: str  # e.g. "last 180 days" or "2025-12-01 to 2026-06-08"
    privacyMode: str  # "local-only"
    confidence: int  # 0-100, from dataCompleteness + data volume


class ExperimentalSignal(TypedDict, total=False):
    """One experimental signal (tagged, never shareable)."""

    label: str
    headline: str
    detail: str
    confidence: int
    kind: str  # "measured" | "inferred" | "estimate"


class ExperimentalBlock(TypedDict, total=False):
    """Experimental signals — excluded from shareable/export."""

    available: bool
    signals: list[ExperimentalSignal]
    codeIntelligence: list[dict]  # Step E populates this


class ActivitySummary(TypedDict, total=False):
    """Structured activity summary for front-end rendering."""

    streak: int
    activeDays: int
    avgSessionHours: float
    totalSessions: int
    days: list[dict]  # list of ActivityDay dicts


class Profile(TypedDict, total=False):
    """Root type for profile.json."""

    schema_version: str
    taxonomy_version: str
    # Assessment metadata
    assessment: AssessmentMeta
    # Identity (user-provided)
    name: str
    title: str
    experience_years: int | None
    ai_experience_years: int | None
    location: str
    work_style: str
    notice_period: str
    stack: list[str]
    projects: list[IdentityProject]
    # Scores (derived)
    intent_score: int
    composite: int | None
    dimensions: dict[str, DimensionResult]
    archetypes: list[ArchetypeResult]
    titles: list[TitleResult]
    primaryTitle: TitleResult | None
    workMode: WorkMode
    antiPatterns: list[AntiPattern]
    trajectory: Trajectory
    map: MapPosition
    growthEdge: GrowthEdge
    wrappedStats: WrappedStats
    dataCompleteness: float
    tools_detected: list[str]
    signals: Signals
    verification: Verification
    scoredAt: float
    # Enrichment (null until Step 5 populates it)
    enrichment: dict | None
    # Experimental (never shareable)
    experimental: ExperimentalBlock
    # Structured activity summary
    activity: ActivitySummary
    # Front-end view data (derived from scan, no raw text)
    summaryLine: str | None
    compositeLabel: str | None
    dominantMode: str | None
    activityByDay: list[ActivityDay]
    scannedProjects: list[ScannedProject]
    stackSummary: StackSummary
    modelsSummary: ModelsSummary


# ── Sensitivity classification ───────────────────────────────────────────────

# Top-level ScanResult fields containing raw/sensitive data (paths, titles, text).
# The "summary" and "normalized" sections contain only aggregate counts.
LOCAL_ONLY_SCAN_FIELDS: frozenset[str] = frozenset(
    {
        "claude_code",  # filesystem paths in session.project
        "cursor",  # conversation titles, commit messages, plan titles
        "codex",  # filesystem path
        "git",  # filesystem paths
    }
)

# Fields allowed in the shareable profile (allowlist).
# Everything else is stripped by build_shareable_profile().
#
# EXCLUDED by design:
#   - scannedProjects: project names are user-controlled visibility
#   - growthEdge: private (improvement suggestions)
#   - antiPatterns: private (risk signals)
#   - experimental: always private (tagged signals, code intelligence)
#   - enrichment: handled separately (growthAreas stripped)
SHAREABLE_PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "taxonomy_version",
        # Assessment metadata
        "assessment",
        # Identity (user-provided — intentionally shared)
        "name",
        "title",
        "experience_years",
        "ai_experience_years",
        "location",
        "work_style",
        "notice_period",
        "stack",
        "projects",
        # Scores (all derived, no raw text)
        "intent_score",
        "composite",
        "dimensions",
        "archetypes",
        "titles",
        # Full kinds taxonomy + earned flags (static taxonomy, no raw data)
        "titlesCatalog",
        "primaryTitle",
        "workMode",
        "map",
        "positioning",
        # Business Fit Map: shareable-class (derived, fit-to-context like
        # role-compare), rendered on the report surface only
        "businessFit",
        # Harness inventory: derived counts of agent tooling (flex signal)
        "harness",
        "wrappedStats",
        "dataCompleteness",
        "tools_detected",
        "signals",
        "verification",
        "scoredAt",
        # Note: trajectory excluded — SCHEMA.md marks it PRIVATE
        # Activity summary
        "activity",
        # Enrichment (growthAreas stripped in build_shareable_profile)
        "enrichment",
        # Front-end view data (derived, no raw text / no filesystem paths)
        "summaryLine",
        "compositeLabel",
        "dominantMode",
        "activityByDay",
        "stackSummary",
        "modelsSummary",
        # Note: scannedProjects excluded — project names are user-controlled visibility
        # Note: growthEdge, antiPatterns excluded — private improvement data
        # Note: experimental EXCLUDED — never shareable
    }
)


# ── Builders & validators ────────────────────────────────────────────────────


def build_shareable_profile(profile: dict, visibility: dict | None = None) -> dict:
    """Return a copy of *profile* containing only derived/shareable fields.

    Guarantees: no filesystem paths, no raw prompt text, no conversation
    titles, no commit messages.  Projects are scrubbed to name + desc only.

    When *visibility* is provided (from ``load_visibility_config()``), sections
    with ``includeInShareable=False`` are omitted, and ``hiddenProjects`` /
    ``hiddenDimensions`` entries are filtered out.  This is an *additional*
    filter on top of the SHAREABLE_PROFILE_FIELDS allowlist, not a replacement.
    """
    shareable = {k: v for k, v in profile.items() if k in SHAREABLE_PROFILE_FIELDS}
    shareable["schema_version"] = SCHEMA_VERSION

    # Scrub projects to name + description only (drop any stray path keys)
    if "projects" in shareable and shareable["projects"]:
        shareable["projects"] = [
            {"name": p.get("name", ""), "desc": p.get("desc", "")} for p in shareable["projects"]
        ]

    # Scrub wrappedStats.goToPrompt — raw prompt text must never leak
    if "wrappedStats" in shareable and isinstance(shareable["wrappedStats"], dict):
        ws = dict(shareable["wrappedStats"])
        ws.pop("goToPrompt", None)
        shareable["wrappedStats"] = ws

    # Hard-exclude experimental block (belt + suspenders: also not in allowlist)
    shareable.pop("experimental", None)

    # growthAreas: private by default; included ONLY when the user
    # explicitly enabled the growthAreas section in their visibility config
    growth_opted_in = bool(
        visibility
        and (visibility.get("sections") or {})
        .get("growthAreas", {})
        .get("includeInShareable", False)
    )
    if "enrichment" in shareable and isinstance(shareable["enrichment"], dict):
        enr = dict(shareable["enrichment"])
        if not growth_opted_in:
            enr.pop("growthAreas", None)
        shareable["enrichment"] = enr

    # Apply user visibility preferences (additional filter, not replacement)
    if visibility:
        sections = visibility.get("sections") or {}
        for section_id, flags in sections.items():
            if not flags.get("includeInShareable", True):
                shareable.pop(section_id, None)
                # Paired fields: hiding "titles" also hides "primaryTitle"
                if section_id == "titles":
                    shareable.pop("primaryTitle", None)
                # Hiding "workMode" also hides compositeLabel/dominantMode
                if section_id == "workMode":
                    shareable.pop("compositeLabel", None)
                    shareable.pop("dominantMode", None)

        # Filter hidden projects from identity projects list
        hidden_projects = set(visibility.get("hiddenProjects") or [])
        if hidden_projects and "projects" in shareable:
            shareable["projects"] = [
                p for p in shareable["projects"] if p.get("name") not in hidden_projects
            ]

        # Filter hidden dimensions from dimensions dict
        hidden_dims = set(visibility.get("hiddenDimensions") or [])
        if hidden_dims and "dimensions" in shareable:
            shareable["dimensions"] = {
                k: v for k, v in shareable["dimensions"].items() if k not in hidden_dims
            }

    return shareable


def validate_schema_version(data: dict, label: str = "data") -> None:
    """Warn (not crash) if *schema_version* is missing or unexpected."""
    v = data.get("schema_version")
    if v is None:
        warnings.warn(
            f"{label} has no schema_version (pre-1.0 data)",
            stacklevel=2,
        )
    elif v != SCHEMA_VERSION:
        warnings.warn(
            f"{label} schema_version={v}, expected {SCHEMA_VERSION}",
            stacklevel=2,
        )
