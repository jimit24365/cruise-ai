"""Render an assessment as agent-readable Markdown.

The profile and the report are normally HTML. This module produces the
SAME content as Markdown so a user can hand `profile.md` / `report.md` to
an AI agent (the easiest format for an LLM to read), and so an agent can
fetch `/profile.md` / `/report.md` from the local server.

Two call sites, one renderer:
  - hub.py serves it from the FULL profile (the user's own agent reads it,
    full fidelity).
  - export.py renders it from `build_shareable_profile(...)` (redacted) for
    sharing/publishing.
The renderer is defensive — every section renders only when its field is
present — so the export path is automatically privacy-safe: private fields
(`leverage`, `antiPatterns`, `growthEdge`, stripped `growthAreas`) are
simply absent and their sections drop out. Adding a section here never
widens what the shareable JSON allows.

Derived-only, like everything else: it renders fields already in the
assessment JSON — never code, prompts, or transcripts.
"""

from __future__ import annotations

_BUILD_DOMAIN_LABELS = {
    "ai_systems": "AI-systems builder",
    "ai_products": "AI-powered product builder",
    "products": "Product builder",
}
_LEVERAGE_LABELS = {
    "prompting": "Prompting",
    "harnessing": "Harnessing",
    "designs_the_loop": "Designs the loop",
}
_DIM_ORDER = [
    "signal_clarity",
    "build_stability",
    "decision_weight",
    "recovery_velocity",
    "context_command",
    "orchestration_range",
]

# Glossary for "Your numbers" — what each measures + how. Mirrors the card
# copy in static/js/profile.js (buildWrappedCards); keep the two in sync.
# Keyed by a stable metric id we map from wrappedStats / signals / leverage.
_GLOSSARY: dict[str, tuple[str, str]] = {
    "longestStreakDays": (
        "Your longest run of consecutive days with at least one AI coding session.",
        "Counted from session timestamps over the window.",
    ),
    "aiCodeShipped": (
        "AI-authored LINES that made it into commits — per-commit authorship "
        "attribution, survival not raw volume.",
        "Sum of AI-attributed diff lines over tracked commits (Cursor scored commits).",
    ),
    "aiCodeTracked": (
        "AI-generated code blocks tracked by your tools. Blocks, not lines — "
        "line-level survival needs per-commit attribution, which this machine's "
        "data doesn't carry.",
        "Count of tracked AI code-block events.",
    ),
    "maxParallelAgents": (
        "The most agents truly running at once — measured first from overlapping "
        "subagent-run transcripts (hard evidence: their own timestamps), with "
        "within-tool session overlap as the softer floor. Cross-tool overlap never counts.",
        "Peak concurrent session overlap from real timestamps, live + ledger.",
    ),
    "subagentDispatches": (
        "Agents you sent off to do work inside your sessions — the clearest loop-design signal.",
        "Task tool calls counted per session, accumulated in your local history ledger.",
    ),
    "longestSessionMinutes": (
        "Your longest single AI coding session. Gap-measured active time — "
        "stretches over 30 minutes idle never count, so a long one is genuinely long.",
        "Gap-based active time (uncapped — idle already excluded) where transcripts "
        "carry per-event timestamps; first-to-last span capped 8h otherwise. Ledger-preserved.",
    ),
    "goToModel": (
        "The model you reached for most across the window.",
        "Most frequent model in session metadata.",
    ),
    "planModePercent": (
        "Share of sessions where you wrote a plan before coding. Basis: Claude "
        "Code sessions — other tools don't expose plan mode.",
        "Plan-before-code signal / Claude Code sessions. Shown neutrally — not graded.",
    ),
    "avgPromptWords": (
        "Average length of your prompts. Basis: tools whose transcripts we parse "
        "(Claude Code, Codex) — Cursor prompt bodies are never read.",
        "Mean word count across parsed prompts. A signal of direction style, not quality.",
    ),
    "totalActiveHours": (
        "Time YOU actively spent in AI coding sessions. Where transcripts carry "
        "per-event timestamps (Claude Code, Codex) this is true ACTIVE time — gaps "
        "over 30 minutes never count. Where a tool only exposes open/close times "
        "(Cursor) it is the open-session span, capped 8h. Ledger-preserved.",
        "Gap-based active time where measurable; first-to-last span (8h cap) otherwise. "
        "Per-tool estimator declared in the signal registry.",
    ),
    "agentRuntimeHours": (
        "Hours your dispatched subagents worked, measured from their own "
        "transcripts. Kept separate from your hands-on time — agents run in "
        "parallel. Basis: Claude Code subagent transcripts only.",
        "Per-run span from agent transcript timestamps (capped 8h each), ledger-preserved.",
    ),
    "marathonSessionCount": (
        "Sessions with 2+ hours of work — active time where transcripts allow "
        "measuring it (idle over 30 minutes never counts), open-session span otherwise.",
        "Effective duration >= 2h, recomputed from the local ledger each assess.",
    ),
    "aiShare": (
        "Share of your shipped lines that AI wrote and that SURVIVED in commits. "
        'A counted fact, not an estimate. The "how long without AI" reading lives '
        "in your Lab as a labeled estimate band.",
        "Per-commit authorship attribution over tracked commits.",
    ),
}


def _prettify(value: str) -> str:
    return value.replace("_", " ").strip().capitalize() if value else ""


def _unwrap(field, key: str) -> str:
    """positioning fields are either a plain id string or {primary|current: id}."""
    if isinstance(field, dict):
        return field.get(key) or ""
    return field or ""


def _score_cell(score) -> str:
    # Null score = insufficient (never 0, never an estimate) — same rule as the UI.
    return "insufficient" if score is None else f"{score}/100"


def _fmt_minutes(mins: int) -> str:
    h, m = divmod(int(mins), 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _header(profile: dict) -> list[str]:
    am = profile.get("assessment") or {}
    pos = profile.get("positioning") or {}
    bd = _unwrap(pos.get("buildDomain"), "primary")
    lv = _unwrap(pos.get("leverageMode"), "current")
    title = (profile.get("primaryTitle") or {}).get("name") or "Builder"
    composite = profile.get("composite")
    conf = am.get("confidence")
    sources = am.get("sources_used") or am.get("sourcesUsed") or []

    facts = [
        f"- **Builder kind:** {title}",
        "- **Composite:** "
        + (f"{composite}/100" if composite is not None else "insufficient")
        + (f" · **Confidence:** {conf}%" if conf is not None else ""),
    ]
    # Self-described identity (user-provided — intentionally shared).
    if profile.get("title"):
        facts.append(f"- **Role (self-described):** {profile['title']}")
    where = [v for v in (profile.get("location"), profile.get("work_style")) if v]
    if where:
        facts.append("- **Based:** " + " · ".join(where))
    exp = []
    if profile.get("experience_years"):
        exp.append(f"{profile['experience_years']} yrs building")
    if profile.get("ai_experience_years"):
        exp.append(f"{profile['ai_experience_years']} yrs with AI")
    if exp:
        facts.append("- **Experience:** " + " · ".join(exp))
    if profile.get("notice_period"):
        facts.append(f"- **Notice period:** {profile['notice_period']}")
    if bd or lv:
        facts.append(
            "- **Builds:** "
            + (_BUILD_DOMAIN_LABELS.get(bd, _prettify(bd)) or "—")
            + " · **Operates at:** "
            + (_LEVERAGE_LABELS.get(lv, _prettify(lv)) or "—")
        )
    enr = profile.get("enrichment") or {}
    persona = (enr.get("howYouUseAI") or {}) if isinstance(enr.get("howYouUseAI"), dict) else {}
    if persona.get("persona"):
        line = persona.get("line") or ""
        facts.append(f"- **How you use AI:** {persona['persona']}" + (f" — {line}" if line else ""))
    meta = []
    if sources:
        meta.append("sources: " + ", ".join(sources))
    if am.get("sessions"):
        meta.append(f"{am['sessions']} sessions")
    if am.get("dateRange"):
        meta.append(am["dateRange"])
    if meta:
        facts.append("- **Evidence:** " + " · ".join(meta))
    return facts


def _dimension_table(profile: dict, with_evidence: bool = False) -> list[str]:
    dims = profile.get("dimensions") or {}
    order = [d for d in _DIM_ORDER if d in dims] + [d for d in dims if d not in _DIM_ORDER]
    if not order:
        return []
    if with_evidence:
        rows = ["| Dimension | Score | Evidence |", "|---|---|---|"]
        for k in order:
            d = dims[k] or {}
            ev = "; ".join((d.get("evidence") or [])[:3]) or "—"
            rows.append(f"| {d.get('name', _prettify(k))} | {_score_cell(d.get('score'))} | {ev} |")
    else:
        rows = ["| Dimension | Score |", "|---|---|"]
        for k in order:
            d = dims[k] or {}
            rows.append(f"| {d.get('name', _prettify(k))} | {_score_cell(d.get('score'))} |")
    return rows


def _collect_numbers(profile: dict) -> list[dict]:
    """The "Your numbers" stats, mirroring buildWrappedCards order/conditions.

    Each entry: {id, label, value, desc}. The glossary (means/how) is looked
    up from _GLOSSARY[id] when the report view wants it.
    """
    ws = profile.get("wrappedStats") or {}
    sig = profile.get("signals") or {}
    lev = profile.get("leverage") or {}
    out: list[dict] = []

    def add(mid, label, value, desc=""):
        out.append({"id": mid, "label": label, "value": value, "desc": desc})

    if ws.get("longestStreakDays"):
        add(
            "longestStreakDays",
            "Longest streak",
            f"{ws['longestStreakDays']} days",
            "consecutive AI coding",
        )
    if sig.get("ai_lines_survived"):
        add(
            "aiCodeShipped",
            "AI code shipped",
            f"{sig['ai_lines_survived']:,}",
            "lines that survived",
        )
    elif sig.get("ai_code_blocks"):
        add("aiCodeTracked", "AI code tracked", f"{sig['ai_code_blocks']:,}", "code blocks")
    if ws.get("maxParallelAgents") and ws["maxParallelAgents"] > 1:
        add("maxParallelAgents", "Max parallel agents", str(ws["maxParallelAgents"]), "at once")
    if ws.get("subagentDispatches"):
        add(
            "subagentDispatches",
            "Subagents dispatched",
            f"{ws['subagentDispatches']:,}",
            "Task-tool runs",
        )
    if ws.get("longestSessionMinutes"):
        capped = ws["longestSessionMinutes"] == 480
        add(
            "longestSessionMinutes",
            "Longest session",
            _fmt_minutes(ws["longestSessionMinutes"]) + ("+" if capped else ""),
            "hit the 8h span cap" if capped else "measured active time",
        )
    if ws.get("models"):
        add("goToModel", "Go-to model", ws["models"][0], "most used")
    if ws.get("planModePercent") is not None:
        add("planModePercent", "Plan-first", f"{ws['planModePercent']}%", "of Claude Code sessions")
    if ws.get("avgPromptWords"):
        add("avgPromptWords", "Avg prompt", f"{ws['avgPromptWords']} words", "substantive")
    if ws.get("totalActiveHours"):
        add(
            "totalActiveHours",
            "Your session time",
            f"{ws['totalActiveHours']}h",
            "active, hands-on",
        )
    if ws.get("agentRuntimeHours"):
        add(
            "agentRuntimeHours",
            "Agent runtime",
            f"{ws['agentRuntimeHours']}h",
            f"{ws.get('subagentRunCount', 0)} subagent runs",
        )
    if ws.get("marathonSessionCount"):
        add(
            "marathonSessionCount",
            "Marathon sessions",
            str(ws["marathonSessionCount"]),
            "over 2h each",
        )
    if lev.get("aiShare") is not None:
        add(
            "aiShare",
            "AI-authored share",
            f"{lev['aiShare']}%",
            f"{lev.get('aiLines', 0):,} AI lines shipped",
        )
    return out


def _numbers_concise(profile: dict) -> list[str]:
    nums = _collect_numbers(profile)
    out = []
    for n in nums:
        desc = f" — {n['desc']}" if n["desc"] else ""
        out.append(f"- **{n['label']}:** {n['value']}{desc}")
    return out


def _numbers_glossary(profile: dict) -> list[str]:
    nums = _collect_numbers(profile)
    out: list[str] = []
    for n in nums:
        desc = f" ({n['desc']})" if n["desc"] else ""
        out.append("")
        out.append(f"### {n['label']} — {n['value']}{desc}")
        means, how = _GLOSSARY.get(n["id"], ("", ""))
        if means:
            out.append(f"- **What it means:** {means}")
        if how:
            out.append(f"- **How it's measured:** {how}")
    return out


def _positioning(profile: dict, deep: bool = False) -> list[str]:
    pos = profile.get("positioning") or {}
    out = []
    techs = pos.get("techDomains") or []
    if techs:
        names = ", ".join(t.get("name", "") for t in techs[:6] if t.get("name"))
        if names:
            out.append(f"- **Tech domains:** {names}")
    bd = pos.get("buildDomain")
    if isinstance(bd, dict):
        dist = bd.get("distribution") or []
        if dist:
            parts = [
                f"{_BUILD_DOMAIN_LABELS.get(d.get('domain'), _prettify(d.get('domain', '')))}"
                f" {d.get('weight')}%"
                for d in dist
                if d.get("weight")
            ]
            if parts:
                out.append("- **Build-domain mix:** " + " · ".join(parts))
        if bd.get("evidence"):
            ev = "; ".join(bd["evidence"][: 3 if deep else 2])
            out.append("- **Build-domain evidence:** " + ev)
    lv = pos.get("leverageMode")
    if isinstance(lv, dict):
        if lv.get("subFlavor"):
            out.append(f"- **Leverage sub-flavor:** {_prettify(lv['subFlavor'])}")
        if lv.get("evidence"):
            out.append("- **Leverage evidence:** " + "; ".join(lv["evidence"][: 3 if deep else 2]))
    return out


def _work_modes(profile: dict) -> list[str]:
    wm = profile.get("workMode") or {}
    dom = wm.get("dominant") or {}
    if not dom:
        return []
    out = []
    line = dom.get("line") or ""
    out.append(f"- **Dominant:** {dom.get('id', '')}" + (f" — {line}" if line else ""))
    for s in wm.get("secondary") or []:
        sline = s.get("line") or ""
        out.append(f"- **Also:** {s.get('id', '')}" + (f" — {sline}" if sline else ""))
    return out


def _archetypes(profile: dict) -> list[str]:
    arts = profile.get("archetypes") or []
    if not arts:
        return []
    ordered = sorted(
        arts, key=lambda a: (a.get("score") is not None, a.get("score") or 0), reverse=True
    )
    out: list[str] = []
    for a in ordered:
        level = (a.get("level") or {}).get("label") or ""
        head = f"### {a.get('name', '')} — {_score_cell(a.get('score'))}"
        if level:
            head += f" · {level}"
        out += ["", head]
        if a.get("description"):
            out.append(a["description"])
        if a.get("soughtBy"):
            out.append(f"_Sought by: {a['soughtBy']}_")
        for ev in (a.get("evidence") or [])[:3]:
            out.append(f"- {ev}")
    return out


def _kinds(profile: dict) -> list[str]:
    out: list[str] = []
    pt = profile.get("primaryTitle") or {}
    if pt.get("name"):
        tag = pt.get("tagline") or ""
        out.append(f"**Primary kind: {pt['name']}**" + (f" — {tag}" if tag else ""))
        if pt.get("idealFor"):
            out.append(f"_Ideal for: {pt['idealFor']}_")
    catalog = profile.get("titlesCatalog") or []
    earned = [t for t in catalog if t.get("earned")]
    if earned:
        out += ["", "Earned kinds:"]
        for t in earned:
            tag = t.get("tagline") or ""
            out.append(f"- **{t.get('name', '')}**" + (f" — {tag}" if tag else ""))
    # Catalog of what each kind is and what earns it — never a ladder ("X to go").
    if catalog:
        out += ["", "Kinds catalog (what each is for, and what earns it):", ""]
        out += ["| Kind | For | Earned by | Earned |", "|---|---|---|---|"]
        for t in catalog:
            mark = "yes" if t.get("earned") else "—"
            out.append(
                f"| {t.get('name', '')} | {t.get('idealFor', '')} | "
                f"{t.get('earnedBy', '')} | {mark} |"
            )
    return out


def _harness(profile: dict) -> list[str]:
    h = profile.get("harness") or {}
    if not h or not h.get("available", True):
        return []
    label = [
        ("totalRepos", "Repos scanned"),
        ("claudeMdRepos", "Repos with CLAUDE.md"),
        ("claudeMdLines", "CLAUDE.md lines"),
        ("mcpRepos", "Repos with MCP config"),
        ("scaffoldedRepos", "Scaffolded repos"),
        ("skills", "Skills"),
        ("agents", "Custom agents"),
        ("commands", "Slash commands"),
        ("hooks", "Hooks"),
        ("rules", "Rule files"),
        ("plugins", "Plugins"),
        ("subagentDispatches", "Subagent dispatches"),
        ("sessionsWithSubagents", "Sessions using subagents"),
    ]
    out = []
    for k, lab in label:
        v = h.get(k)
        if v:
            out.append(f"- **{lab}:** {v}")
    return out


def _leverage(profile: dict) -> list[str]:
    lev = profile.get("leverage") or {}
    if not lev or lev.get("aiShare") is None:
        return []
    out = [
        f"- **AI-authored share:** {lev['aiShare']}% of shipped lines "
        f"({lev.get('aiLines', 0):,} AI vs {lev.get('humanLines', 0):,} hand-written, "
        f"over {lev.get('trackedCommits', 0)} tracked commits)",
    ]
    if lev.get("outputMultiple"):
        cap = "+" if lev.get("outputMultipleCapped") else ""
        out.append(
            f"- **Output multiple:** {lev['outputMultiple']}{cap}× the hand-written share alone"
        )
    if lev.get("handsOnHours") is not None or lev.get("agentHours") is not None:
        out.append(
            f"- **Hands-on vs agent time:** {lev.get('handsOnHours', 0)}h yours · "
            f"{lev.get('agentHours', 0)}h agents (parallel, kept separate)"
        )
    se = lev.get("soloEquivalentHours") or {}
    if se.get("low") is not None and se.get("high") is not None:
        out.append(
            f"- **Solo-equivalent estimate:** {se['low']}–{se['high']}h "
            "(research-anchored band, an estimate — never a score)"
        )
    if lev.get("basis"):
        out.append(f"- **Basis:** {lev['basis']}")
    if lev.get("estimateNote"):
        out.append(f"- **Note:** {lev['estimateNote']}")
    return out


_TOOL_ACRONYMS = {"ide": "IDE", "ai": "AI", "mcp": "MCP", "cli": "CLI", "lm": "LM"}


def _label_tool(tool_id: str) -> str:
    return " ".join(
        _TOOL_ACRONYMS.get(w.lower(), w.capitalize()) for w in tool_id.replace("_", " ").split()
    )


def _stack_and_tools(profile: dict) -> list[str]:
    out = []
    ss = profile.get("stackSummary") or {}
    langs = ss.get("languages")
    if langs:
        names = ", ".join(langs.keys()) if isinstance(langs, dict) else ", ".join(langs)
        if names:
            out.append(f"- **Languages:** {names}")
    if ss.get("frameworks"):
        out.append("- **Frameworks:** " + ", ".join(ss["frameworks"]))
    if ss.get("aiFrameworks"):
        out.append("- **AI frameworks:** " + ", ".join(ss["aiFrameworks"]))
    if ss.get("databases"):
        out.append("- **Databases:** " + ", ".join(ss["databases"]))
    if ss.get("cloud"):
        out.append("- **Cloud:** " + ", ".join(ss["cloud"]))
    tools = profile.get("tools_detected") or []
    if tools:
        out.append("- **AI tools:** " + ", ".join(_label_tool(t) for t in tools))
    ms = profile.get("modelsSummary") or {}
    if ms.get("primaryModel"):
        by = ms.get("byModel") or {}
        if by:
            mix = ", ".join(f"{m} ({c})" for m, c in by.items())
            out.append(f"- **Models:** {ms['primaryModel']} primary — {mix}")
        else:
            out.append(f"- **Primary model:** {ms['primaryModel']}")
    return out


def _projects(profile: dict) -> list[str]:
    projs = profile.get("projects") or []
    out = []
    for p in projs:
        if not isinstance(p, dict):
            continue
        name = p.get("name", "")
        desc = p.get("desc", "")
        if name:
            out.append(f"- **{name}**" + (f" — {desc}" if desc else ""))
    return out


def _decision_patterns(enr: dict) -> list[str]:
    dp = enr.get("decisionPatterns") or {}
    if not dp:
        return []
    out = []
    if dp.get("style"):
        out.append(f"- **Style:** {dp['style']}")
    stats = dp.get("stats") or {}
    if stats.get("detected"):
        by = stats.get("byDomain") or {}
        dens = ", ".join(f"{k}: {v}" for k, v in by.items()) if by else ""
        out.append(
            f"- **Decisions observed:** {stats['detected']}"
            + (f" (high-value: {stats['highValue']})" if stats.get("highValue") else "")
            + (f" — by domain: {dens}" if dens else "")
        )
    for p in dp.get("named") or []:
        ev = p.get("evidence") or ""
        out.append(f"- **{p.get('name', '')}**" + (f" — {ev}" if ev else ""))
    return out


def _business_fit(profile: dict) -> list[str]:
    bf = profile.get("businessFit") or {}
    tops = bf.get("topFits") or []
    if not tops:
        return []
    out = []
    if bf.get("framing"):
        out.append(f"_{bf['framing']}_")
        out.append("")
    for z in tops:
        out.append(f"- **{z.get('name', '')}** — {z.get('affinity', '')}% fit-to-segment")
    return out


def _activity(profile: dict) -> list[str]:
    act = profile.get("activity") or {}
    if not act:
        return []
    out = []
    if act.get("totalSessions"):
        out.append(f"- **Sessions:** {act['totalSessions']}")
    if act.get("activeDays"):
        out.append(f"- **Active days:** {act['activeDays']}")
    streak = act.get("streak")
    if isinstance(streak, dict):
        cur, longest = streak.get("current"), streak.get("longest")
        if cur is not None or longest is not None:
            out.append(f"- **Streak:** {cur or 0} current · {longest or 0} longest (days)")
    elif streak:
        out.append(f"- **Streak:** {streak} days")
    if act.get("avgSessionHours"):
        out.append(f"- **Avg session:** {act['avgSessionHours']}h")
    return out


_FOOTER = (
    "_Generated by nextmillionai from local signals. Scores are arithmetic "
    "over counted signals against research-anchored bands; any narrative is "
    "written by the user's own agent and can never change a score. "
    "No code, prompts, or transcripts are included._"
)


def profile_to_markdown(profile: dict, view: str = "profile") -> str:
    """Render `profile` as Markdown. view='profile' (concise) | 'report' (deep)."""
    deep = view == "report"
    name = profile.get("name") or "Builder"
    summary = profile.get("summaryLine") or (profile.get("enrichment") or {}).get("positioningLine")
    enr = profile.get("enrichment") or {}
    lines: list[str] = []

    lines.append(f"# {name} — AI coding {'report' if deep else 'profile'}")
    if summary:
        lines += ["", f"> {summary}"]
    lines += [""] + _header(profile)

    if deep and enr.get("narrative"):
        lines += ["", "## Summary", "", enr["narrative"]]

    # How you use AI — persona + decision patterns (report only)
    if deep:
        dp_lines = _decision_patterns(enr)
        if dp_lines:
            lines += ["", "## How you use AI", ""] + dp_lines

    lines += ["", "## How well you build with AI", ""]
    lines += _dimension_table(profile, with_evidence=deep)

    if deep and enr.get("whatYouBuilt"):
        lines += ["", "## What you built", ""]
        lines += [f"- {item}" for item in enr["whatYouBuilt"]]

    if deep and enr.get("strengths"):
        lines += ["", "## Strengths", ""]
        for s in enr["strengths"]:
            if isinstance(s, dict):
                claim = s.get("claim", "")
                ev = s.get("evidence", "")
                lines.append(f"- **{claim}**" + (f" — {ev}" if ev else ""))
            else:
                lines.append(f"- {s}")

    # Archetypes (the craft scores behind the kind) — report only
    if deep:
        art_lines = _archetypes(profile)
        if art_lines:
            lines += ["", "## Archetypes (your crafts)"] + art_lines

    # Kinds catalog — report only
    if deep:
        kind_lines = _kinds(profile)
        if kind_lines:
            lines += ["", "## Kinds", ""] + kind_lines

    pos_lines = _positioning(profile, deep=deep)
    if pos_lines:
        lines += ["", "## Positioning", ""] + pos_lines
        if deep:
            wm_lines = _work_modes(profile)
            if wm_lines:
                lines += ["", "### Work modes", ""] + wm_lines

    # Stack & tooling — languages, frameworks, AI tools, models
    stack_lines = _stack_and_tools(profile)
    if stack_lines:
        lines += ["", "## Stack & tooling", ""] + stack_lines

    # Projects (user-curated identity list, name + description only)
    proj_lines = _projects(profile)
    if proj_lines:
        lines += ["", "## Projects", ""] + proj_lines

    # Orchestration & leverage — how the work gets multiplied
    harness_lines = _harness(profile)
    leverage_lines = _leverage(profile)
    if harness_lines or leverage_lines:
        lines += ["", "## Orchestration & leverage", ""]
        if leverage_lines:
            lines += leverage_lines
        if harness_lines:
            if leverage_lines:
                lines += ["", "### Harness inventory", ""]
            lines += harness_lines

    # Your numbers — concise list, or full glossary in the report
    if deep:
        glossary = _numbers_glossary(profile)
        if glossary:
            lines += ["", "## Your numbers"] + glossary
    else:
        num_lines = _numbers_concise(profile)
        if num_lines:
            lines += ["", "## Your numbers", ""] + num_lines

    # Business fit (report only) — fit-to-segment, never a ranking
    if deep:
        bf_lines = _business_fit(profile)
        if bf_lines:
            lines += ["", "## Business fit", ""] + bf_lines

    # Activity (report only)
    if deep:
        act_lines = _activity(profile)
        if act_lines:
            lines += ["", "## Activity", ""] + act_lines

    if deep and enr.get("growthAreas"):
        lines += ["", "## Growth areas", ""]
        for g in enr["growthAreas"]:
            if isinstance(g, dict):
                obs = g.get("observed", "")
                nxt = g.get("nextSignal", "")
                lines.append(f"- {obs}" + (f" → _{nxt}_" if nxt else ""))
            else:
                lines.append(f"- {g}")

    lines += ["", "---", "", _FOOTER, ""]
    return "\n".join(lines)
