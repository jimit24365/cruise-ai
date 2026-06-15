"""
nextmillionai.enrichment -- Enrichment module.

Produces bounded, secret-stripped excerpts from local sessions,
embeds the ENRICHMENT-PROMPT template, validates and ingests
enrichment results. Off by default, opt-in.

Run paths:
  - copy/paste (default): `nextmillionai enrich` prints prompt+excerpts
    to stdout and saves to a file. User runs in their own agent, then
    `nextmillionai enrich --submit result.json` ingests the result.
  - BYO-key (optional): `--key` runs via user's own API key locally.

Output: six blocks — narrative, whatYouBuilt, decisionPatterns,
strengths, growthAreas, howYouUseAI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Max excerpt characters to keep the prompt bounded
_MAX_EXCERPT_CHARS = 8000
_MAX_EXCERPTS = 10

# Patterns that suggest secrets — strip these from excerpts
_SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),  # API keys
    re.compile(r"(ghp_[a-zA-Z0-9]{36})"),  # GitHub PATs
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})"),  # Bearer tokens
    re.compile(r'("password"\s*:\s*"[^"]+")'),  # JSON passwords
    re.compile(r"(AKIA[A-Z0-9]{16})"),  # AWS keys
    re.compile(r"(-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----)"),  # PEM keys
]


def _strip_secrets(text: str) -> str:
    """Replace potential secrets with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def select_excerpts(
    sessions: list,
    max_excerpts: int = _MAX_EXCERPTS,
    max_chars: int = _MAX_EXCERPT_CHARS,
) -> list[dict]:
    """Select representative, bounded, secret-stripped session excerpts.

    Returns list of dicts with: tool, project, turns (list of {role, content}).
    """
    excerpts: list[dict] = []
    total_chars = 0

    # DIVERSE selection — longest alone over-samples one work style.
    # Pool: the longest, the most recent, the dispatch-heaviest, and
    # first-seen-per-project (breadth), deduped in that priority order.
    def _len_key(s):
        return getattr(s, "user_msgs", 0) or 0

    def _date_key(s):
        return getattr(s, "started_at", None) or 0

    def _task_key(s):
        return (getattr(s, "tool_calls_by_type", {}) or {}).get("task", 0)

    pool: list = []
    seen_ids: set = set()

    def _take(seq, n):
        for s in seq:
            sid = f"{getattr(s, 'tool', '')}:{getattr(s, 'session_id', id(s))}"
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            pool.append(s)
            n -= 1
            if n <= 0:
                break

    by_len = sorted(sessions, key=_len_key, reverse=True)
    dated = [s for s in sessions if getattr(s, "started_at", None)]
    by_recent = sorted(dated, key=_date_key, reverse=True)
    by_tasks = sorted(sessions, key=_task_key, reverse=True)
    _take(by_len, max(max_excerpts // 2, 2))
    _take(by_recent, 3)
    _take([s for s in by_tasks if _task_key(s) > 0], 2)
    seen_projects: set = set()
    for s in by_len:
        proj = getattr(s, "project_path", None)
        if proj and proj not in seen_projects:
            seen_projects.add(proj)
            _take([s], 1)
        if len(pool) >= max_excerpts * 2:
            break

    for session in pool[: max_excerpts * 2]:  # oversample then trim
        if len(excerpts) >= max_excerpts:
            break
        if total_chars >= max_chars:
            break

        tool = getattr(session, "tool", "unknown")
        project = getattr(session, "project_path", "")
        if project:
            # Strip to project name only (no full path)
            project = project.rstrip("/").split("/")[-1]

        # Take up to 6 turns from each session (user msgs only for brevity)
        prompt_words = getattr(session, "prompt_word_counts", [])
        user_msg_count = getattr(session, "user_msgs", 0)
        models = list(getattr(session, "models", []))

        # Build a summary excerpt (no raw prompts — only metadata).
        # The DATE makes the session itself a citable pointer.
        started = getattr(session, "started_at", None)
        date_str = started.date().isoformat() if started else "undated"
        excerpt_text = (
            f"Session {date_str} in {project or 'unknown project'} using {tool}. "
            f"{user_msg_count} user messages, "
            f"{sum(getattr(session, 'tool_calls_by_type', {}).values())} tool calls. "
            f"Models: {', '.join(models) if models else 'unknown'}."
        )

        # Add tool call breakdown
        tool_calls = getattr(session, "tool_calls_by_type", {})
        if tool_calls:
            parts = [f"{k}: {v}" for k, v in sorted(tool_calls.items()) if v > 0]
            if parts:
                excerpt_text += f" Tool types: {', '.join(parts)}."

        # Add avg prompt length
        if prompt_words:
            avg_words = sum(prompt_words) / len(prompt_words)
            excerpt_text += f" Avg prompt: {avg_words:.0f} words."

        excerpt_text = _strip_secrets(excerpt_text)

        if total_chars + len(excerpt_text) > max_chars:
            break

        started = getattr(session, "started_at", None)
        excerpts.append(
            {
                "tool": tool,
                "project": project,
                "date": started.date().isoformat() if started else None,
                "summary": excerpt_text,
                "userMsgs": user_msg_count,
                "models": models,
                "toolCalls": dict(tool_calls) if tool_calls else {},
                "subagentRuns": (getattr(session, "extras", {}) or {}).get("subagentRuns", 0),
            }
        )
        total_chars += len(excerpt_text)

    return excerpts


GENERATED_BANNER = """\
════════════════════════════════════════════════════════════════════════
@generated — DO NOT EDIT THIS FILE.
Written by `enrich`; regenerated (and overwritten) on every run.
Source of truth: ENRICHMENT-PROMPT.md (template) and
nextmillionai/enrichment.py (excerpt selection + evidence bank).
Edit those, then re-run `enrich`. Hand-edits here are lost and never
feed back into the product.
════════════════════════════════════════════════════════════════════════

"""


def prompt_file_text(prompt: str) -> str:
    """The on-disk form of the generated prompt: @generated banner first,
    so neither a human nor an agent mistakes the artifact for a source."""
    return GENERATED_BANNER + prompt


def build_evidence_bank(scan_results: dict, profile: dict) -> dict:
    """The POINTER BANK: derived evidence the agent may cite from.

    The prompt requires every claim to carry a pointer; this bank is
    where pointers come from — repo names with verified build-domain
    verdicts (incl. monorepo package evidence), recent commit subjects,
    and the engine's own dimension evidence strings. All derived-only:
    names, subjects, counts — never code, never full paths.
    """
    bank: dict = {"repos": [], "recentCommits": [], "dimensionEvidence": {}}

    ci_by_name = {}
    for r in ((scan_results.get("code_intel") or {}).get("repos")) or []:
        if r.get("name"):
            ci_by_name[r["name"]] = r

    for proj in ((scan_results.get("git") or {}).get("projects")) or []:
        name = proj.get("name")
        if not name:
            continue
        entry: dict = {
            "repo": name,
            "languages": (proj.get("languages") or [])[:3],
            "commits6m": proj.get("commits_6m", 0),
            "aiDeps": (proj.get("aiFrameworks") or [])[:4],
        }
        ci = ci_by_name.get(name)
        if ci and ci.get("buildDomain"):
            entry["buildDomain"] = ci["buildDomain"].get("domain")
            entry["domainEvidence"] = (ci["buildDomain"].get("evidence") or "")[:160]
            if ci.get("packages"):
                entry["packages"] = ci["packages"][:6]
        if entry["aiDeps"] or entry.get("buildDomain") or entry["commits6m"] >= 5:
            bank["repos"].append(entry)
    bank["repos"] = sorted(bank["repos"], key=lambda r: r.get("commits6m", 0), reverse=True)[:12]

    sc = (scan_results.get("cursor") or {}).get("scored_commits") or {}
    for c in (sc.get("recentCommits") or [])[:8]:
        if c.get("message"):
            bank["recentCommits"].append(
                {
                    "hash": c.get("hash", ""),
                    "subject": c["message"][:90],
                    "aiPct": c.get("aiPct"),
                }
            )

    for dim_id, d in (profile.get("dimensions") or {}).items():
        if isinstance(d, dict) and d.get("evidence"):
            bank["dimensionEvidence"][dim_id] = d["evidence"][:2]

    return bank


def build_enrichment_prompt(
    signals: dict,
    dominant_mode: str,
    primary_archetype: str,
    excerpts: list[dict],
    evidence_bank: dict | None = None,
) -> str:
    """Build the enrichment prompt from the template + real data.

    Reads ENRICHMENT-PROMPT.md from the package docs directory and fills
    the template variables.
    """
    # Load the template
    template_path = Path(__file__).parent.parent / "ENRICHMENT-PROMPT.md"
    if not template_path.exists():
        # Fallback: inline minimal template
        template_path = Path(__file__).parent / "docs" / "ENRICHMENT-PROMPT.md"

    if template_path.exists():
        template = template_path.read_text()
    else:
        # Minimal fallback template
        template = _FALLBACK_TEMPLATE

    # Extract the prompt section between markers. Match markers on their
    # own line — the doc's prose also mentions them inline.
    block = re.search(
        r"^--- PROMPT START ---$(.*?)^--- PROMPT END ---$",
        template,
        re.DOTALL | re.MULTILINE,
    )
    prompt_text = block.group(1).strip() if block else template

    # Fill template variables
    signals_json = json.dumps(signals, indent=2, default=str)
    excerpts_json = json.dumps(excerpts, indent=2, default=str)

    prompt_text = prompt_text.replace("{{SIGNALS}}", signals_json)
    prompt_text = prompt_text.replace("{{DOMINANT_MODE}}", dominant_mode)
    prompt_text = prompt_text.replace("{{ARCHETYPE}}", primary_archetype)
    prompt_text = prompt_text.replace("{{EXCERPTS}}", excerpts_json)
    bank_json = json.dumps(evidence_bank or {}, indent=2, default=str)
    prompt_text = prompt_text.replace("{{EVIDENCE_BANK}}", bank_json)

    return prompt_text


def build_heuristic_enrichment(profile: dict) -> dict:
    """Build a heuristic fallback enrichment from scored profile data.

    Used when the user hasn't run enrichment (opt-in, off by default).
    Returns the same six-block structure with factual-only content.
    """
    dims = profile.get("dimensions", {})
    work_mode = profile.get("workMode", {})
    mode_id = work_mode.get("dominant", {}).get("id", "Unknown")
    mode_line = work_mode.get("dominant", {}).get("line", "")
    archetypes = profile.get("archetypes", [])
    profile.get("primaryTitle", {})
    normalized = profile.get("wrappedStats", {})
    positioning = profile.get("positioning", {})

    # Top 2 dimensions
    scored_dims = sorted(
        [(k, v) for k, v in dims.items() if isinstance(v, dict) and v.get("score") is not None],
        key=lambda x: x[1]["score"],
        reverse=True,
    )
    top_dims = scored_dims[:2] if len(scored_dims) >= 2 else scored_dims

    # Narrative
    if top_dims:
        dim_names = " and ".join(d[1].get("name", d[0]) for d in top_dims)
        narrative = f"Strongest in {dim_names}."
    else:
        narrative = "Profile built from available data."

    # positioningLine
    leverage = positioning.get("leverageMode", {})
    build_domain = positioning.get("buildDomain", {})
    tech_domains = positioning.get("techDomains", [])
    tech_label = tech_domains[0]["name"] if tech_domains else "general"
    positioning_line = (
        f"A {tech_label} {build_domain.get('primary', 'product')} builder "
        f"operating mostly at the {leverage.get('current', 'prompting')} level."
    )

    # whatYouBuilt
    what_you_built = []
    tools = normalized.get("tools", [])
    if tools:
        what_you_built.append(
            f"Primarily worked with {', '.join(tools)}. Work mode: {mode_line or mode_id}."
        )

    # Strengths from top archetypes
    strengths = []
    for arch in archetypes[:3]:
        if isinstance(arch, dict) and arch.get("score") is not None and arch["score"] >= 55:
            ev = arch.get("evidence", [])
            strengths.append(
                {
                    "claim": f"Strong {arch.get('name', '')} pattern",
                    "evidence": "; ".join(ev[:2]) if ev else "Based on scoring signals",
                }
            )
    if not strengths and top_dims:
        for d in top_dims:
            ev = d[1].get("evidence", [])
            strengths.append(
                {
                    "claim": f"High {d[1].get('name', '')}",
                    "evidence": "; ".join(ev[:2]) if ev else "Based on scoring signals",
                }
            )

    # Growth areas from growth edge
    growth = profile.get("growthEdge", {})
    growth_areas = []
    if growth.get("suggestion"):
        growth_areas.append(
            {
                "observed": f"Growth opportunity in {growth.get('context', 'current workflow')}.",
                "nextSignal": growth["suggestion"],
            }
        )

    # howYouUseAI
    how_you_use = {
        "persona": _infer_persona(mode_id),
        "line": mode_line or f"Works in {mode_id} mode.",
        "evidencePoints": 0,
    }

    return {
        "narrative": narrative,
        "positioningLine": positioning_line,
        "whatYouBuilt": what_you_built,
        "decisionPatterns": {
            "style": f"Works in {mode_id} mode.",
            "stats": {"detected": 0, "byDomain": {}, "highValue": 0},
            "named": [],
        },
        "strengths": strengths,
        "growthAreas": growth_areas,
        "howYouUseAI": how_you_use,
        "generatedAt": _utc_now_iso(),
        "source": "heuristic",
    }


def _infer_persona(mode_id: str) -> str:
    """Map work mode to an AI-use persona (heuristic)."""
    _personas = {
        "One-Shot-Verify": "Surgeon",
        "Prompt-Iterate": "Dances with Robots",
        "Architect-First": "Architect",
        "Multi-Agent-Orchestrated": "Fleet Commander",
        "Test-Driven-AI": "Verifier",
        "Read-Understand-Modify": "Explorer",
        "Hybrid-Manual": "Gatekeeper",
        "Exploration-Research": "Explorer",
    }
    return _personas.get(mode_id, "Builder")


# ── Validation ────────────────────────────────────────────────────────────────

# The exact output contract from ENRICHMENT-PROMPT.md. Anything else is
# off-schema and rejected — the agent only narrates, it never adds fields.
_REQUIRED_BLOCKS = {
    "narrative",
    "positioningLine",
    "whatYouBuilt",
    "decisionPatterns",
    "strengths",
    "growthAreas",
    "howYouUseAI",
}
# Metadata stamped by us at ingest time, tolerated on re-submission.
_INGEST_METADATA_KEYS = {"generatedAt", "source"}

# Patterns that indicate raw code leaked into the result
_CODE_PATTERNS = [
    re.compile(r"(def\s+\w+\s*\(|class\s+\w+\s*[:(]|import\s+\w+|from\s+\w+\s+import)"),
    re.compile(r"(\{\s*\n\s*(if|for|while|return)\s)"),
    re.compile(r"(function\s+\w+\s*\(|const\s+\w+\s*=|let\s+\w+\s*=)"),
    re.compile(r"```"),  # markdown code fences inside values
]

# Ranking/cohort language the agent is forbidden from producing
_RANKING_PATTERNS = [
    re.compile(r"\btop\s+\d+\s*%", re.IGNORECASE),
    re.compile(r"\bpercentile\b", re.IGNORECASE),
    re.compile(r"\bbetter than (most|other)", re.IGNORECASE),
    re.compile(r"\boutperform(s|ing)?\b", re.IGNORECASE),
    re.compile(r"\bcohort\b", re.IGNORECASE),
    re.compile(r"\bleaderboard\b", re.IGNORECASE),
]


def parse_submission(raw_text: str) -> tuple[dict | None, str]:
    """Parse a submitted enrichment file into a dict.

    Tolerates a single outer markdown fence wrapper (agents often add one),
    but the content inside must be pure JSON. Returns (result, error).
    """
    text = raw_text.strip()
    fence = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if not isinstance(result, dict):
        return None, "result must be a JSON object"
    return result, ""


def _check_pointer_list(items, key_a: str, key_b: str, label: str) -> str:
    """Validate a list of {key_a, key_b} string pairs. Returns error or ''."""
    if not isinstance(items, list):
        return f"{label} must be a list"
    for item in items:
        if not isinstance(item, dict):
            return f"{label} items must be objects"
        if not isinstance(item.get(key_a), str) or not isinstance(item.get(key_b), str):
            return f"{label} items need string '{key_a}' and '{key_b}'"
    return ""


def validate_enrichment(result: dict) -> tuple[bool, str]:
    """Validate an enrichment result against the six-block contract.

    Rejects off-schema keys, raw/fenced code in values, and ranking
    language. Returns (valid, error_message).
    """
    missing = _REQUIRED_BLOCKS - set(result.keys())
    if missing:
        return False, f"Missing required blocks: {', '.join(sorted(missing))}"

    extra = set(result.keys()) - _REQUIRED_BLOCKS - _INGEST_METADATA_KEYS
    if extra:
        return False, f"Off-schema keys not allowed: {', '.join(sorted(extra))}"

    if not isinstance(result.get("narrative"), str) or not result["narrative"].strip():
        return False, "narrative must be a non-empty string"

    if not isinstance(result.get("positioningLine"), str):
        return False, "positioningLine must be a string"

    wyb = result.get("whatYouBuilt")
    if not isinstance(wyb, list) or not all(isinstance(p, str) for p in wyb):
        return False, "whatYouBuilt must be a list of strings"

    dp = result.get("decisionPatterns")
    if not isinstance(dp, dict) or not isinstance(dp.get("style"), str):
        return False, "decisionPatterns must be an object with string 'style'"
    stats = dp.get("stats")
    if (
        not isinstance(stats, dict)
        or not isinstance(stats.get("detected"), int)
        or not isinstance(stats.get("byDomain"), dict)
        or not isinstance(stats.get("highValue"), int)
    ):
        return False, "decisionPatterns.stats needs int detected/highValue and object byDomain"
    err = _check_pointer_list(dp.get("named"), "name", "evidence", "decisionPatterns.named")
    if err:
        return False, err

    err = _check_pointer_list(result.get("strengths"), "claim", "evidence", "strengths")
    if err:
        return False, err

    err = _check_pointer_list(result.get("growthAreas"), "observed", "nextSignal", "growthAreas")
    if err:
        return False, err

    how = result.get("howYouUseAI")
    if (
        not isinstance(how, dict)
        or not isinstance(how.get("persona"), str)
        or not isinstance(how.get("line"), str)
    ):
        return False, "howYouUseAI must have string persona and line"

    full_text = json.dumps(result)
    for pattern in _CODE_PATTERNS:
        if pattern.search(full_text):
            return False, f"Result contains raw code (matched: {pattern.pattern[:40]})"

    for pattern in _RANKING_PATTERNS:
        match = pattern.search(full_text)
        if match:
            return False, (
                f"Result contains ranking language ('{match.group(0)}') — "
                "no percentiles, cohorts, or better-than comparisons"
            )

    return True, ""


def ingest_enrichment(result: dict, profile_path: Path, source: str = "agent") -> tuple[bool, str]:
    """Validate and merge an enrichment result into the profile.

    Idempotent: re-submitting replaces the previous block. Stamps
    generatedAt + source so rescans can tell agent narrative from
    heuristic fallback. Only the enrichment block changes — scores never.
    Returns (success, message).
    """
    valid, error = validate_enrichment(result)
    if not valid:
        return False, f"Enrichment rejected: {error}"

    if not profile_path.exists():
        return False, f"Profile not found at {profile_path}"

    with open(profile_path) as f:
        profile = json.load(f)

    stamped = dict(result)
    stamped["generatedAt"] = _utc_now_iso()
    stamped["source"] = source
    # Strip secrets defensively from every string value before storing
    profile["enrichment"] = _strip_secrets_deep(stamped)

    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2, default=str)

    return True, "Enrichment merged into profile."


def revoke_enrichment(profile_path: Path) -> tuple[bool, str]:
    """Remove any ingested enrichment; the next assess rebuilds heuristic text."""
    if not profile_path.exists():
        return False, f"Profile not found at {profile_path}"

    with open(profile_path) as f:
        profile = json.load(f)

    if "enrichment" not in profile:
        return True, "No enrichment present — nothing to revoke."

    profile["enrichment"] = build_heuristic_enrichment(profile)

    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2, default=str)

    return True, "Enrichment revoked; heuristic text restored."


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_secrets_deep(value):
    """Apply secret stripping to every string in a nested structure."""
    if isinstance(value, str):
        return _strip_secrets(value)
    if isinstance(value, list):
        return [_strip_secrets_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_secrets_deep(v) for k, v in value.items()}
    return value


# ── Minimal fallback template ────────────────────────────────────────────────

_FALLBACK_TEMPLATE = """
--- PROMPT START ---
You are analyzing a developer's AI coding sessions. Return a JSON object with
these six blocks: narrative (one sentence), whatYouBuilt (list of paragraphs),
decisionPatterns ({style, stats, named}), strengths ([{claim, evidence}]),
growthAreas ([{observed, nextSignal}]), howYouUseAI ({persona, line, evidencePoints}).

SIGNALS: {{SIGNALS}}
DOMINANT MODE: {{DOMINANT_MODE}}
PRIMARY ARCHETYPE: {{ARCHETYPE}}
EXCERPTS: {{EXCERPTS}}

Return ONLY the JSON object, no markdown fences.
--- PROMPT END ---
"""
