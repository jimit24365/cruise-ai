#!/usr/bin/env python3
"""Regenerate cruise_ai/examples/profile.json.

The bundled example is produced by the REAL engine over a synthetic
home — sessions, subagent runs, and git repos are generated, then
`assess` computes the profile exactly as it would for any user. No
number in the example is hand-authored.

Run from the repo root:  python3 scripts/make_example_profile.py
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "cruise_ai" / "examples" / "profile.json"

MODELS = ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


PROMPTS = [
    "Wire the checkout flow end to end: `src/cart/checkout.ts` should call the new "
    "pricing service, handle the declined-card branch from `payments/errors.ts`, and "
    "add an integration test that covers the retry path before we ship this.",
    "The reconciliation job in `jobs/reconcile.ts` double-counts refunds issued on the "
    "same day as the charge. Trace the aggregation in `lib/ledger.ts`, fix the window "
    "logic, and verify against the fixtures in `tests/fixtures/ledger`.",
    "Plan first, then build: split `server/router.ts` into per-domain modules, keep "
    "the public API stable, and run the full suite after each extraction step so we "
    "can bisect any regression to a single move.",
    "Take the failing `pricing.spec.ts` cases, reproduce them locally, and converge "
    "on a fix — the rounding error only appears for three-decimal currencies, see "
    "`lib/money.ts` and the table in `docs/currencies.md`.",
]


def write_session(path, start, turns, model, cwd, tasks=0):
    lines = []
    t = start
    for i in range(turns):
        lines.append(
            {
                "type": "user",
                "timestamp": _iso(t),
                "message": {"content": PROMPTS[i % len(PROMPTS)]},
                "cwd": cwd,
            }
        )
        t += timedelta(minutes=3 + (i % 4))
        content = [{"type": "text", "text": "done, verified"}]
        if tasks and i < tasks:
            content.append({"type": "tool_use", "name": "Task", "input": {}})
        content.append({"type": "tool_use", "name": "Edit", "input": {}})
        content.append({"type": "tool_use", "name": "Bash", "input": {}})
        lines.append(
            {
                "type": "assistant",
                "timestamp": _iso(t),
                "message": {"model": model, "content": content},
                "cwd": cwd,
            }
        )
        t += timedelta(minutes=4 + (i % 5))
    path.write_text("\n".join(json.dumps(x) for x in lines))
    return t


def write_subagent_runs(session_dir, start, n):
    sub = session_dir / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    for r in range(n):
        a = start + timedelta(minutes=2 * r)
        b = a + timedelta(minutes=25 + 5 * r)
        lines = [
            {"type": "user", "timestamp": _iso(a), "message": {"content": "subtask"}},
            {
                "type": "assistant",
                "timestamp": _iso(b),
                "message": {"content": [{"type": "text", "text": "done"}]},
            },
        ]
        (sub / f"agent-{r:02d}.jsonl").write_text("\n".join(json.dumps(x) for x in lines))


def make_repo(root, name, deps, day_offsets, ai_product=False, harness=False):
    repo = root / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "package.json").write_text(json.dumps({"dependencies": deps}, indent=2))
    (repo / "index.ts").write_text(
        "import Anthropic from '@anthropic-ai/sdk';\n"
        "const c = new Anthropic();\n"
        "await c.messages.create({model: 'claude-sonnet-4-6'});\n"
        if ai_product
        else "export const app = () => 'hello';\n"
    )
    if harness:
        (repo / "CLAUDE.md").write_text("# Project rules\n\nKeep tests green.\n")
        (repo / ".claude" / "skills").mkdir(parents=True)
        (repo / ".claude" / "skills" / "review.md").write_text("review skill")
    now = datetime.now(timezone.utc)
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Demo",
            "GIT_AUTHOR_EMAIL": "demo@example.com",
            "GIT_COMMITTER_NAME": "Demo",
            "GIT_COMMITTER_EMAIL": "demo@example.com",
        }
    )
    for i, off in enumerate(day_offsets):
        d = now - timedelta(days=off)
        stamp = d.strftime("%Y-%m-%dT12:%M:00")
        (repo / "work.txt").write_text(f"change {i}\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
        env2 = dict(env, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        msg = ("feat: ship feature " if i % 3 else "fix: tighten edge ") + str(i)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", msg], check=True, env=env2)
    return repo


# Agent-written enrichment for the bundled demo persona ("Maya Chen"). Narrated
# from the demo's own assessed signals; submitted through `enrich --submit` so it
# satisfies the six-block contract (no off-schema keys, no ranking language).
EXAMPLE_ENRICHMENT = {
    "narrative": (
        "Builds production software with AI as a collaborator, not a vending "
        "machine: precise, reference-rich direction up front, fast iterative "
        "loops, and nothing shipped until it is verified. The signature is "
        "strongest in Recovery Velocity and Build Stability, with 91% of "
        "AI-authored code surviving in commits."
    ),
    "positioningLine": (
        "A JavaScript ai_products builder operating mostly at the designs_the_loop level."
    ),
    "whatYouBuilt": [
        "Shipped lighthouse-app, an AI-native product (Next.js with the "
        "Anthropic SDK wired into the runtime) — the largest body of work, "
        "committed steadily across roughly four months.",
        "Built harbor-mcp, a Model Context Protocol server with zod-validated "
        "tools that exposes capabilities to coding agents.",
        "Kept tidewater-shop, a React and Express storefront, on a steady "
        "release cadence alongside the bigger builds.",
    ],
    "decisionPatterns": {
        "style": "Plans the risky work, then builds in small verifiable steps.",
        "stats": {
            "detected": 4,
            "byDomain": {"refactoring": 2, "debugging": 1, "delivery": 1},
            "highValue": 2,
        },
        "named": [
            {
                "name": "Plan-before-build on structural changes",
                "evidence": (
                    "Nine written plans precede coding; the router split ran as reversible "
                    "extraction steps with the suite checked after each move."
                ),
            },
            {
                "name": "Reproduce, then fix",
                "evidence": (
                    "Failing pricing cases reproduced locally before any change; "
                    "96% of flagged errors resolved."
                ),
            },
            {
                "name": "Test the risky path before merge",
                "evidence": (
                    "An integration test covered the checkout retry and declined-card "
                    "branch before it shipped."
                ),
            },
            {
                "name": "Reference-rich direction",
                "evidence": (
                    "Every prompt cites specific files or fixtures; 21.5 turns of "
                    "deliberate iteration per task on average."
                ),
            },
        ],
    },
    "strengths": [
        {
            "claim": "Durable AI-assisted code (Code Weaver)",
            "evidence": "91% of AI-authored lines survive in commits; 96% error-fix rate.",
        },
        {
            "claim": "Deliberate, spec-led iteration (System Thinker)",
            "evidence": "100% reference-rich prompts; 21.5 average turns per task.",
        },
        {
            "claim": "Carries context across tools (Context Engineer)",
            "evidence": (
                "Nine specs and plans written before coding; consistent context "
                "across Claude Code and Cursor."
            ),
        },
    ],
    "growthAreas": [
        {
            "observed": "Parallelism tops out around four agents at once.",
            "nextSignal": (
                "Fan a well-scoped task across more subagents — orchestration grows "
                "with breadth, not just depth."
            ),
        },
        {
            "observed": "Work concentrates in JavaScript product code.",
            "nextSignal": (
                "A second language or a non-product repo would broaden the build-domain footprint."
            ),
        },
    ],
    "howYouUseAI": {
        "persona": "Dances with Robots",
        "line": "Riffs in fast, verified cycles — directs, checks, then ships.",
    },
}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cruise-ai-example-"))
    home = tmp / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    cruise_home = tmp / "cruise-ai"

    repos = {
        "lighthouse-app": make_repo(
            tmp / "code",
            "lighthouse-app",
            {"react": "^18", "next": "^15", "@anthropic-ai/sdk": "^1.0"},
            day_offsets=list(range(2, 120, 4)),
            ai_product=True,
            harness=True,
        ),
        "harbor-mcp": make_repo(
            tmp / "code",
            "harbor-mcp",
            {"@modelcontextprotocol/sdk": "^1.0", "zod": "^3"},
            day_offsets=list(range(5, 90, 9)),
        ),
        "tidewater-shop": make_repo(
            tmp / "code",
            "tidewater-shop",
            {"react": "^18", "express": "^4"},
            day_offsets=list(range(1, 140, 6)),
        ),
    }

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    proj_dir = home / ".claude" / "projects" / "-code"
    proj_dir.mkdir(parents=True)
    names = list(repos)
    for i in range(70):  # ~5 months of sessions, varied length
        day = 1 + i * 2
        start = now - timedelta(days=day, hours=(9 + i % 9))
        repo = repos[names[i % 3]]
        turns = 8 + (i % 10) * 3
        tasks = 4 if i % 4 == 0 else 0
        sid = f"demo-{i:03d}"
        write_session(proj_dir / f"{sid}.jsonl", start, turns, MODELS[i % 3], str(repo), tasks)
        if tasks:
            write_subagent_runs(proj_dir / sid, start + timedelta(minutes=10), tasks)

    # Cursor tracking db (real schema) — unlocks survival/stability,
    # AI-vs-human line attribution, the leverage card, plans
    import sqlite3

    track = home / ".cursor" / "ai-tracking"
    track.mkdir(parents=True)
    con = sqlite3.connect(track / "ai-code-tracking.db")
    con.execute("CREATE TABLE ai_code_hashes (source TEXT, model TEXT, createdAt INTEGER)")
    con.execute(
        "CREATE TABLE scored_commits (commitHash TEXT, branchName TEXT, "
        "commitMessage TEXT, commitDate INTEGER, linesAdded INTEGER, "
        "linesDeleted INTEGER, composerLinesAdded INTEGER, "
        "composerLinesDeleted INTEGER, humanLinesAdded INTEGER, "
        "humanLinesDeleted INTEGER, tabLinesAdded INTEGER, "
        "tabLinesDeleted INTEGER, v2AiPercentage REAL)"
    )
    con.execute(
        "CREATE TABLE conversation_summaries (conversationId TEXT, title TEXT, "
        "tldr TEXT, model TEXT, mode TEXT, updatedAt INTEGER)"
    )
    for i in range(60):
        d = now - timedelta(days=2 + i * 2)
        ms = int(d.timestamp() * 1000)
        for _ in range(8 + i % 5):
            con.execute(
                "INSERT INTO ai_code_hashes VALUES (?,?,?)",
                ("composer", MODELS[i % 3], ms),
            )
        ai = 140 + (i % 7) * 30
        human = 12 + (i % 5) * 4
        con.execute(
            "INSERT INTO scored_commits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"c{i:04d}",
                "main",
                ("feat: ship slice " if i % 3 else "fix: converge on ") + str(i),
                ms,
                ai + human,
                30,
                ai - 40,
                10,
                human,
                4,
                40,
                2,
                round(ai / (ai + human) * 100, 1),
            ),
        )
        con.execute(
            "INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?)",
            (f"conv{i}", f"Slice {i}", "shipped the slice", MODELS[i % 3], "agent", ms),
        )
    con.commit()
    con.close()

    plans = home / ".cursor" / "plans"
    plans.mkdir(parents=True)
    for i in range(9):
        (plans / f"plan-{i}.plan.md").write_text(
            "# Plan\n\n" + "\n".join(f"- step {s}: build, verify, ship" for s in range(14))
        )

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CRUISE_AI_HOME"] = str(cruise_home)
    env.pop("CRUISE_AI_PROFILE_PATH", None)
    subprocess.run(
        [sys.executable, "-m", "cruise_ai", "assess", "--rescan", "--yes"],
        check=True,
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    # Submit an agent-written enrichment so the bundled demo shows the real
    # "reads like a reference letter" experience (not the heuristic fallback +
    # "run enrich" nudge). This goes through the real `enrich --submit`
    # validator, so it stays inside the six-block contract; numbers below are
    # the demo's own assessed signals, narrated — the agent never sets a score.
    result_file = tmp / "enrich-result.json"
    result_file.write_text(json.dumps(EXAMPLE_ENRICHMENT))
    subprocess.run(
        [sys.executable, "-m", "cruise_ai", "enrich", "--submit", str(result_file), "--yes"],
        check=True,
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    profile = json.loads((cruise_home / "data" / "profile.json").read_text())
    profile.update(
        {
            "name": "Maya Chen",
            "title": "AI Engineer",
            "location": "Lisbon",
            "work_style": "remote",
        }
    )
    # A bundled sample avatar so the demo shows a face, not the monogram
    # fallback. hub.py serves profile["avatar"] from /api/avatar only for the
    # demo; real users have no avatar field and keep the monogram.
    avatar_svg = (OUT.parent / "demo-avatar.svg").read_bytes()
    profile["avatar"] = "data:image/svg+xml;base64," + base64.b64encode(avatar_svg).decode()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(profile, indent=1))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(
        "composite:",
        profile.get("composite"),
        "| sessions:",
        profile["assessment"]["sessions"],
        "| range:",
        profile["assessment"]["dateRange"],
    )


if __name__ == "__main__":
    main()
