#!/usr/bin/env python3
"""
nextmillionai Scanner — Multi-tool AI coding profile builder.

Reads AI coding data from Claude Code, Cursor IDE, and Codex CLI,
then produces a normalized scan result compatible with the Intent
scoring engine (intent-cursor-extension/lib/scoring/).

Usage:
    python scanner.py                    # Scan all tools, write data/scan_results.json
    python scanner.py --project ~/myapp  # Scan single project
    python scanner.py --tools            # List detected AI tools and session counts
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────────

HOME = Path(os.path.expanduser("~"))
CLAUDE_PROJECTS_DIR = HOME / ".claude" / "projects"
CURSOR_DIR = HOME / ".cursor"
CURSOR_DB_PATH = CURSOR_DIR / "ai-tracking" / "ai-code-tracking.db"
CURSOR_PLANS_DIR = CURSOR_DIR / "plans"
CURSOR_PROJECTS_DIR = CURSOR_DIR / "projects"

# Cursor's app storage (state.vscdb) — where the REAL session history
# lives, with timestamps, across Cursor versions. First existing wins.
_CURSOR_APP_CANDIDATES = [
    HOME / "Library" / "Application Support" / "Cursor" / "User",  # macOS
    HOME / ".config" / "Cursor" / "User",  # Linux
    HOME / "AppData" / "Roaming" / "Cursor" / "User",  # Windows
]
CURSOR_APP_USER_DIR = next(
    (p for p in _CURSOR_APP_CANDIDATES if p.is_dir()), _CURSOR_APP_CANDIDATES[0]
)
CODEX_SESSIONS_DIR = HOME / ".codex" / "sessions"
KIRO_SESSIONS_DIR = HOME / ".kiro" / "sessions" / "cli"

# Kiro IDE app storage (VS Code-family pattern) — platform-dependent.
if sys.platform == "darwin":
    KIRO_IDE_DIRS = [
        HOME
        / "Library"
        / "Application Support"
        / "Kiro"
        / "User"
        / "globalStorage"
        / "kiro.kiroagent"
    ]
elif sys.platform == "win32":
    KIRO_IDE_DIRS = (
        [Path(os.environ["APPDATA"]) / "Kiro" / "User" / "globalStorage" / "kiro.kiroagent"]
        if os.environ.get("APPDATA")
        else []
    )
else:  # Linux
    KIRO_IDE_DIRS = [HOME / ".config" / "Kiro" / "User" / "globalStorage" / "kiro.kiroagent"]

# Framework detection maps (mirrored from history-scanner.js)
JS_FRAMEWORK_MAP = {
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "nuxt": "Nuxt",
    "angular": "Angular",
    "svelte": "Svelte",
    "express": "Express",
    "fastify": "Fastify",
    "koa": "Koa",
    "hono": "Hono",
    "nest": "NestJS",
    "electron": "Electron",
    "tailwindcss": "Tailwind CSS",
    "three": "Three.js",
    "socket.io": "Socket.IO",
    "prisma": "Prisma",
    "drizzle-orm": "Drizzle",
    "typeorm": "TypeORM",
    "sequelize": "Sequelize",
    "mongoose": "Mongoose",
    "redis": "Redis",
    "ioredis": "Redis",
    "openai": "OpenAI SDK",
    "@anthropic-ai/sdk": "Anthropic SDK",
    "ai": "Vercel AI SDK",
    "langchain": "LangChain",
    "@langchain/core": "LangChain",
    "vscode": "VS Code Extension API",
    "zod": "Zod",
    "jest": "Jest",
    "vitest": "Vitest",
    "playwright": "Playwright",
    "cypress": "Cypress",
    "webpack": "Webpack",
    "vite": "Vite",
    "esbuild": "esbuild",
    "typescript": "TypeScript",
    "graphql": "GraphQL",
    "@modelcontextprotocol/sdk": "MCP SDK",
}

PY_FRAMEWORK_MAP = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "streamlit": "Streamlit",
    "gradio": "Gradio",
    "langchain": "LangChain",
    "openai": "OpenAI SDK",
    "anthropic": "Anthropic SDK",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "transformers": "HuggingFace Transformers",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scikit-learn": "scikit-learn",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "celery": "Celery",
    "redis": "Redis",
    "pytest": "pytest",
    "uvicorn": "Uvicorn",
    "aiohttp": "aiohttp",
    "httpx": "HTTPX",
    "boto3": "AWS SDK",
}

GO_FRAMEWORK_MAP = {
    "gin-gonic/gin": "Gin",
    "gorilla/mux": "Gorilla Mux",
    "go-chi/chi": "Chi",
    "gofiber/fiber": "Fiber",
    "gorm.io/gorm": "GORM",
    "ent/ent": "Ent",
}

RUST_FRAMEWORK_MAP = {
    "actix-web": "Actix Web",
    "axum": "Axum",
    "tokio": "Tokio",
    "serde": "Serde",
    "diesel": "Diesel",
    "sqlx": "SQLx",
    "wasm-bindgen": "WASM",
}

# Tool name categories for counting real file vs terminal operations in Claude Code
_FILE_TOOL_NAMES = frozenset({"Edit", "Write", "Read", "Grep", "Glob", "NotebookEdit"})
_TERMINAL_TOOL_NAMES = frozenset({"Bash"})
_READ_TOOL_NAMES = frozenset({"Read", "Grep", "Glob"})
_WRITE_TOOL_NAMES = frozenset({"Edit", "Write", "NotebookEdit"})


# ── Helpers ──────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    """Print scan detail to stderr — only in verbose mode.

    Good-citizen CLI: quiet by default (commands print their own honest
    summaries); `-v/--verbose` or NEXTMILLIONAI_VERBOSE=1 restores the
    per-repo detail.
    """
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_read_text(path: Path) -> str | None:
    """Read text file, return None on any error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_read_json(path: Path) -> dict | None:
    """Read JSON file, return None on any error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def git_run(args: list[str], cwd: str | Path | None = None, timeout: int = 15) -> str | None:
    """Run a git command, return stdout or None on error.

    Hardened so an automated scan can never block on interactive git:
    the pager is disabled, credential/terminal prompts are turned off,
    optional index locks are skipped, and stdin is closed. Any failure
    (including a timeout) returns None — never raises, never hangs.
    """
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # never prompt for credentials
        "GIT_OPTIONAL_LOCKS": "0",  # don't wait on index.lock
        "GCM_INTERACTIVE": "never",  # git-credential-manager: no popup
        "GIT_PAGER": "cat",
        "PAGER": "cat",
    }
    try:
        result = subprocess.run(
            ["git", "--no-pager"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def sqlite_query(db_path: Path, query: str) -> list[dict] | None:
    """Run a SQLite query and return rows as dicts, or None on error."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return None


def ts_to_iso(ts) -> str | None:
    """Convert a timestamp (seconds or milliseconds) to ISO 8601 string."""
    if ts is None:
        return None
    try:
        ts = float(ts)
        # Detect millisecond timestamps
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        # Maybe it's already an ISO string
        if isinstance(ts, str):
            return ts
        return None


def days_between(iso_a: str | None, iso_b: str | None) -> int | None:
    """Return days between two ISO timestamps."""
    if not iso_a or not iso_b:
        return None
    try:
        a = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
        b = datetime.fromisoformat(iso_b.replace("Z", "+00:00"))
        return abs((b - a).days)
    except Exception:
        return None


# ── Claude Code Scanner (facade → adapters.claude_code) ──────────────────────


def scan_claude_code(project_filter: str | None = None) -> dict | None:
    """Scan ~/.claude/projects/ for session JSONL files.

    Delegates to :class:`~nextmillionai.adapters.claude_code.ClaudeCodeAdapter`.
    """
    from nextmillionai.adapters.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter(projects_dir=CLAUDE_PROJECTS_DIR)
    if not adapter.detect():
        log("Claude Code: ~/.claude/projects/ not found, skipping")
        return None
    adapter.scan(project_filter)
    return adapter.raw_data()


# ── Cursor IDE Scanner (facade → adapters.cursor) ───────────────────────────


def scan_cursor_ai_code() -> dict | None:
    """Scan Cursor ai-code-tracking.db: ai_code_hashes table."""
    from nextmillionai.adapters.cursor import CursorAdapter

    adapter = CursorAdapter(db_path=CURSOR_DB_PATH)
    return adapter._scan_ai_code()


def scan_cursor_scored_commits() -> dict | None:
    """Scan Cursor scored_commits table."""
    from nextmillionai.adapters.cursor import CursorAdapter

    adapter = CursorAdapter(db_path=CURSOR_DB_PATH)
    return adapter._scan_scored_commits()


def scan_cursor_conversations() -> dict | None:
    """Scan Cursor conversation_summaries table."""
    from nextmillionai.adapters.cursor import CursorAdapter

    adapter = CursorAdapter(db_path=CURSOR_DB_PATH)
    return adapter._scan_conversations()


def scan_cursor_plans() -> dict | None:
    """Scan ~/.cursor/plans/ for .plan.md files."""
    from nextmillionai.adapters.cursor import CursorAdapter

    adapter = CursorAdapter(plans_dir=CURSOR_PLANS_DIR)
    return adapter._scan_plans()


def scan_cursor_transcripts() -> dict | None:
    """Scan ~/.cursor/projects/*/agent-transcripts/ directories."""
    from nextmillionai.adapters.cursor import CursorAdapter

    adapter = CursorAdapter(projects_dir=CURSOR_PROJECTS_DIR)
    return adapter._scan_transcripts()


def scan_cursor(project_filter: str | None = None) -> dict | None:
    """Scan all Cursor IDE data sources.

    Delegates to :class:`~nextmillionai.adapters.cursor.CursorAdapter`.
    """
    from nextmillionai.adapters.cursor import CursorAdapter

    adapter = CursorAdapter(
        cursor_dir=CURSOR_DIR,
        db_path=CURSOR_DB_PATH,
        plans_dir=CURSOR_PLANS_DIR,
        projects_dir=CURSOR_PROJECTS_DIR,
    )
    if not adapter.detect():
        log("Cursor IDE: ~/.cursor/ not found, skipping")
        return None
    adapter.scan(project_filter)
    return adapter.raw_data()


# ── Codex CLI Scanner (facade → adapters.codex) ─────────────────────────────


def scan_codex() -> dict | None:
    """Scan ~/.codex/sessions/ if present.

    Delegates to :class:`~nextmillionai.adapters.codex.CodexAdapter`.
    Returns the legacy dict shape (total_sessions + path) for backward
    compatibility.
    """
    from nextmillionai.adapters.codex import CodexAdapter

    adapter = CodexAdapter(sessions_dir=CODEX_SESSIONS_DIR)
    if not adapter.detect():
        log("Codex CLI: ~/.codex/sessions/ not found, skipping")
        return None
    adapter.scan()
    raw = adapter.raw_data()
    if raw is None:
        return None
    # Backward-compatible shape: just total_sessions + path
    return {
        "total_sessions": raw.get("total_sessions", 0),
        "path": raw.get("path", str(CODEX_SESSIONS_DIR)),
    }


# ── Tech Stack Detection ────────────────────────────────────────────────────


def detect_tech_stack(project_path: Path) -> dict:
    """Detect frameworks, tools, and languages from project config files."""
    # languages/frameworks/tools/... are lists; "harness" is a count dict
    stack: dict[str, Any] = {
        "languages": [],
        "frameworks": [],
        "tools": [],
        "aiFrameworks": [],
        "databases": [],
        "cloud": [],
    }

    def _add(category: str, label: str) -> None:
        if label not in stack[category]:
            stack[category].append(label)

    # ── package.json (Node/JS/TS) — root + one level of workspace
    # manifests (apps/*, packages/*, services/*, frontend/*, backend/*):
    # monorepos keep their real deps per app. ──
    pkg_files = [project_path / "package.json"]
    for ws in ("apps", "packages", "services", "frontend", "backend", "client", "server", "web"):
        ws_dir = project_path / ws
        if ws_dir.is_dir():
            # Direct manifest in the subdir
            if (ws_dir / "package.json").is_file():
                pkg_files.append(ws_dir / "package.json")
            try:
                pkg_files.extend(sorted(ws_dir.glob("*/package.json"))[:30])
            except OSError:
                pass

    all_deps: dict = {}
    for pkg_file in pkg_files:
        pkg = safe_read_json(pkg_file)
        if not pkg:
            continue
        _add("languages", "JavaScript")
        all_deps.update(pkg.get("dependencies") or {})
        all_deps.update(pkg.get("devDependencies") or {})
    if all_deps:
        for dep_name in all_deps:
            for key, label in JS_FRAMEWORK_MAP.items():
                if (
                    dep_name == key
                    or dep_name.startswith(f"@{key}/")
                    or dep_name.startswith(f"{key}-")
                ):
                    _add("frameworks", label)
        if "TypeScript" in [JS_FRAMEWORK_MAP.get(d) for d in all_deps]:
            _add("languages", "TypeScript")

    # ── tsconfig.json ──
    if (project_path / "tsconfig.json").exists():
        _add("languages", "TypeScript")

    # ── requirements.txt (Python) — root + common subdirs ──
    _py_subdirs = [project_path] + [
        project_path / d for d in ("backend", "server", "api", "src") if (project_path / d).is_dir()
    ]
    reqs = None
    for _pdir in _py_subdirs:
        reqs = safe_read_text(_pdir / "requirements.txt")
        if reqs:
            break
    if reqs:
        _add("languages", "Python")
        for line in reqs.splitlines():
            dep = (
                line.strip()
                .split(">=")[0]
                .split("==")[0]
                .split("<")[0]
                .split("[")[0]
                .split("!")[0]
                .lower()
                .strip()
            )
            if dep in PY_FRAMEWORK_MAP:
                _add("frameworks", PY_FRAMEWORK_MAP[dep])

    # ── pyproject.toml (Python) — root + common subdirs ──
    pyproject = None
    for _pdir in _py_subdirs:
        pyproject = safe_read_text(_pdir / "pyproject.toml")
        if pyproject:
            break
    if pyproject:
        _add("languages", "Python")
        for key, label in PY_FRAMEWORK_MAP.items():
            if f'"{key}' in pyproject or f"'{key}" in pyproject:
                _add("frameworks", label)

    # ── go.mod (Go) ──
    gomod = safe_read_text(project_path / "go.mod")
    if gomod:
        _add("languages", "Go")
        for key, label in GO_FRAMEWORK_MAP.items():
            if key in gomod:
                _add("frameworks", label)

    # ── Cargo.toml (Rust) ──
    cargo = safe_read_text(project_path / "Cargo.toml")
    if cargo:
        _add("languages", "Rust")
        for key, label in RUST_FRAMEWORK_MAP.items():
            if key in cargo:
                _add("frameworks", label)

    # ── Additional Python manifests (setup.py, Pipfile) ──
    if "Python" not in stack["languages"]:
        for py_manifest in ("setup.py", "setup.cfg", "Pipfile"):
            if (project_path / py_manifest).exists():
                _add("languages", "Python")
                break

    # ── Additional manifests for other ecosystems ──
    if (project_path / "Gemfile").exists():
        _add("languages", "Ruby")
    if (project_path / "composer.json").exists():
        _add("languages", "PHP")
    for java_manifest in ("pom.xml", "build.gradle", "build.gradle.kts"):
        if (project_path / java_manifest).exists():
            _add("languages", "Java")
            if java_manifest.endswith(".kts"):
                _add("languages", "Kotlin")
            break
    if (project_path / "Package.swift").exists():
        _add("languages", "Swift")
    if (project_path / "mix.exs").exists():
        _add("languages", "Elixir")
    if (project_path / "CMakeLists.txt").exists():
        _add("languages", "C/C++")
    if (project_path / "Makefile").exists() and not stack["languages"]:
        # Only count Makefile as C/C++ signal when no other language detected
        pass  # handled by extension fallback below

    # ── File-extension fallback ──
    # When manifest-based detection found nothing, scan the repo for
    # common source file extensions (top-level + one level deep).
    if not stack["languages"]:
        _EXT_LANG = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".jsx": "JavaScript",
            ".rb": "Ruby",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".kt": "Kotlin",
            ".swift": "Swift",
            ".php": "PHP",
            ".cs": "C#",
            ".c": "C/C++",
            ".cpp": "C/C++",
            ".h": "C/C++",
            ".ex": "Elixir",
            ".exs": "Elixir",
            ".liquid": "Liquid",
            ".html": "HTML",
            ".css": "CSS",
            ".sh": "Shell",
            ".lua": "Lua",
            ".dart": "Dart",
            ".r": "R",
            ".scala": "Scala",
            ".zig": "Zig",
        }
        _SKIP_DIRS = frozenset(
            (
                ".git",
                "node_modules",
                ".next",
                "__pycache__",
                "dist",
                "build",
                ".venv",
                "venv",
                "vendor",
                ".cache",
            )
        )
        ext_counts: dict[str, int] = {}
        try:
            for entry in project_path.iterdir():
                if entry.name.startswith(".") and entry.is_dir():
                    continue
                if entry.is_file():
                    ext = entry.suffix.lower()
                    if ext in _EXT_LANG:
                        ext_counts[ext] = ext_counts.get(ext, 0) + 1
                elif entry.is_dir() and entry.name not in _SKIP_DIRS:
                    try:
                        for child in entry.iterdir():
                            if child.is_file():
                                ext = child.suffix.lower()
                                if ext in _EXT_LANG:
                                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    except OSError:
                        pass
        except OSError:
            pass

        # Add languages with at least 2 source files
        for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
            lang = _EXT_LANG[ext]
            if count >= 2:
                _add("languages", lang)

    # ── Config files for tools ──
    tool_files = [
        ("Dockerfile", "Docker"),
        (".dockerignore", "Docker"),
        ("docker-compose.yml", "Docker Compose"),
        ("docker-compose.yaml", "Docker Compose"),
        (".github/workflows", "GitHub Actions"),
        (".gitlab-ci.yml", "GitLab CI"),
        ("Makefile", "Make"),
        ("Justfile", "Just"),
        ("vercel.json", "Vercel"),
        ("fly.toml", "Fly.io"),
        ("netlify.toml", "Netlify"),
        ("render.yaml", "Render"),
        (".pre-commit-config.yaml", "pre-commit"),
        ("CLAUDE.md", "CLAUDE.md"),
        (".cursorrules", "Cursor Rules"),
        (".clinerules", "Cline Rules"),
    ]
    for fname, label in tool_files:
        if (project_path / fname).exists():
            _add("tools", label)

    # MCP config at project level
    mcp_file = project_path / ".mcp.json"
    mcp_data = safe_read_json(mcp_file)
    if mcp_data and mcp_data.get("mcpServers"):
        _add("tools", "MCP")

    # ── AI frameworks / databases / cloud (dependency NAMES only) ──
    dep_text = " ".join(
        filter(
            None,
            [
                " ".join(all_deps.keys()),
                (reqs or "").lower(),
                (pyproject or "").lower(),
                (gomod or "").lower(),
                (cargo or "").lower(),
            ],
        )
    ).lower()
    for needle, label in AI_FRAMEWORK_MARKERS.items():
        if needle in dep_text:
            _add("aiFrameworks", label)
    for needle, label in DB_MARKERS.items():
        if needle in dep_text:
            _add("databases", label)
    for needle, label in CLOUD_MARKERS.items():
        if needle in dep_text:
            _add("cloud", label)

    # ── Agent harness inventory (the 2026 craft signals) ──
    harness: dict[str, int] = {}

    def _count_dir(rel: str) -> int:
        d = project_path / rel
        if not d.is_dir():
            return 0
        try:
            return sum(1 for e in d.iterdir() if not e.name.startswith("."))
        except OSError:
            return 0

    harness["skills"] = _count_dir(".claude/skills")
    harness["agents"] = _count_dir(".claude/agents")
    harness["commands"] = _count_dir(".claude/commands") + _count_dir("commands")
    harness["rules"] = _count_dir(".cursor/rules")

    claude_md = safe_read_text(project_path / "CLAUDE.md")
    harness["claudeMdLines"] = len(claude_md.splitlines()) if claude_md else 0

    hooks = 0
    for settings_rel in (".claude/settings.json", ".claude/settings.local.json"):
        settings = safe_read_json(project_path / settings_rel)
        if settings and isinstance(settings.get("hooks"), dict):
            hooks += sum(len(v) if isinstance(v, list) else 1 for v in settings["hooks"].values())
    harness["hooks"] = hooks
    if (project_path / ".claude-plugin").is_dir():
        harness["plugin"] = 1

    if harness["skills"]:
        _add("tools", "Skills")
    if harness["agents"]:
        _add("tools", "Agents")
    if harness["commands"]:
        _add("tools", "Commands")
    if harness["hooks"]:
        _add("tools", "Hooks")
    if harness["rules"]:
        _add("tools", "Cursor Rules")
    if any(harness.values()):
        stack["harness"] = harness

    return stack


# Dependency-name markers (lowercase substring match on manifest text).
# Labels are categories of tooling — a signal of focus, never a ranking.
AI_FRAMEWORK_MARKERS = {
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "llama-index": "LlamaIndex",
    "llamaindex": "LlamaIndex",
    "crewai": "CrewAI",
    "autogen": "AutoGen",
    "semantic-kernel": "Semantic Kernel",
    "haystack-ai": "Haystack",
    "@modelcontextprotocol": "MCP SDK",
    "fastmcp": "MCP SDK",
    "claude-agent-sdk": "Claude Agent SDK",
    "anthropic": "Anthropic SDK",
    "openai": "OpenAI SDK",
    "transformers": "Transformers",
    "litellm": "LiteLLM",
    "google-generativeai": "Gemini SDK",
    "@google/generative-ai": "Gemini SDK",
    "@ai-sdk": "Vercel AI SDK",
    "groq": "Groq SDK",
    "mistralai": "Mistral SDK",
    "cohere": "Cohere SDK",
    "replicate": "Replicate",
}
DB_MARKERS = {
    "postgres": "PostgreSQL",
    "psycopg": "PostgreSQL",
    "mysql": "MySQL",
    "mongoose": "MongoDB",
    "pymongo": "MongoDB",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "sqlite": "SQLite",
    "prisma": "Prisma",
    "supabase": "Supabase",
    "drizzle": "Drizzle",
    "sqlalchemy": "SQLAlchemy",
}
CLOUD_MARKERS = {
    "boto3": "AWS",
    "aws-sdk": "AWS",
    "@aws-sdk": "AWS",
    "google-cloud": "GCP",
    "@google-cloud": "GCP",
    "azure": "Azure",
    "vercel": "Vercel",
    "firebase": "Firebase",
    "cloudflare": "Cloudflare",
    "wrangler": "Cloudflare",
}


# ── Git History Scanner ──────────────────────────────────────────────────────


def derive_project_paths_from_cursor() -> list[Path]:
    """Derive real filesystem paths from ~/.cursor/projects/ directory names.

    Cursor encodes paths as directory names but the encoding is lossy
    (hyphens and path separators are conflated), so we cannot reliably
    reconstruct the original path.  Returns an empty list — project
    discovery relies on sources that record the real path (e.g. Claude
    Code's cwd field).
    """
    # Cursor's directory-name encoding is ambiguous (e.g. "my-project"
    # vs "my/project") and platform-specific.  Returning [] avoids
    # phantom paths; Claude Code cwd provides reliable project paths.
    return []


def derive_project_paths_from_claude(claude_data: dict | None = None) -> list[Path]:
    """Extract real filesystem paths from Claude Code session data.

    Uses the cwd field recorded in each JSONL session line, which is
    the actual working directory — no lossy directory-name decoding.
    """
    paths: list[Path] = []
    seen: set[str] = set()

    # Fast path: extract from already-scanned session data
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            proj = s.get("project")
            if not proj or proj in seen:
                continue
            seen.add(proj)
            p = Path(proj)
            if p.is_dir() and (p / ".git").exists():
                paths.append(p)
        return paths

    # Fallback: read cwd from first JSONL line in each project dir
    if not CLAUDE_PROJECTS_DIR.exists():
        return paths
    try:
        for d in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            for jf in d.glob("*.jsonl"):
                text = safe_read_text(jf)
                if not text:
                    continue
                for raw_line in text.splitlines()[:20]:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    cwd = obj.get("cwd")
                    if cwd:
                        if cwd not in seen:
                            seen.add(cwd)
                            p = Path(cwd)
                            if p.is_dir() and (p / ".git").exists():
                                paths.append(p)
                        break  # found cwd, done with this file
                break  # only need one JSONL file per project dir
    except Exception:
        pass
    return paths


def discover_project_paths(
    project_filter: str | None = None,
    claude_data: dict | None = None,
) -> list[Path]:
    """Get unique project paths from all sources.

    *claude_data*, if supplied, lets us extract real cwd paths from
    already-parsed session data instead of re-reading JSONL files.
    """
    seen: set[str] = set()
    result: list[Path] = []

    if project_filter:
        p = Path(os.path.expanduser(project_filter)).resolve()
        if p.exists():
            return [p]
        return []

    for p in derive_project_paths_from_cursor() + derive_project_paths_from_claude(claude_data):
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            result.append(p)

    return result


def scan_git(project_filter: str | None = None, claude_data: dict | None = None) -> dict | None:
    """Scan git history for all discovered projects."""
    project_paths = discover_project_paths(project_filter, claude_data=claude_data)

    if not project_paths:
        log("Git: no project paths discovered")
        return None

    log(f"Git: scanning {len(project_paths)} projects...")

    projects = []
    for proj_path in project_paths:
        name = proj_path.name

        # Commit count in last 6 months
        output = git_run(
            ["log", "--oneline", "--since=6 months ago"],
            cwd=proj_path,
        )
        feat_count = 0
        fix_count = 0
        if output:
            for cline in output.splitlines():
                parts = cline.strip().split(" ", 1)
                if len(parts) > 1:
                    cmsg = parts[1].lower()
                    if cmsg.startswith(("feat:", "feat(", "feature:", "add:")):
                        feat_count += 1
                    elif cmsg.startswith(("fix:", "fix(", "bugfix:", "hotfix:")):
                        fix_count += 1
        commits_6m = len(output.splitlines()) if output else 0

        # Detect tech stack
        stack = detect_tech_stack(proj_path)
        stack_labels = stack["languages"] + stack["frameworks"]

        projects.append(
            {
                "path": str(proj_path),
                "name": name,
                "commits_6m": commits_6m,
                "stack": stack_labels,
                "languages": stack["languages"],
                "frameworks": stack["frameworks"],
                "tools": stack["tools"],
                "feat_commits": feat_count,
                "fix_commits": fix_count,
            }
        )

        log(f"  {name}: {commits_6m} commits (6m), stack={stack_labels}")

    if not projects:
        return None

    return {"projects": projects}


# ── Normalized Metrics Computation ───────────────────────────────────────────


def count_mcp_servers(
    home: Path,
    projects: list | None,
    cursor_enabled: bool = False,
    desktop_servers: list | None = None,
) -> tuple[int, list[str]]:
    """Count MCP servers across every consented client config, deduped by name.

    Context bridging is configured per-client; counting only Claude Code's
    config silently undercounts users who run MCP through Cursor or Claude
    Desktop. We union the server NAMES (deduped) from:
      - ``~/.claude.json`` + project ``.mcp.json`` (Claude Code)        [always]
      - ``~/.cursor/mcp.json`` + project ``.cursor/mcp.json`` (Cursor)  [if Cursor consented]
      - Claude Desktop config names (already parsed by the opt-in adapter,
        so passing them in keeps this consent-gated)

    All reads are LOCAL config files — no network, no session content.
    """
    names: set[str] = set()

    def _add(cfg_path: Path) -> None:
        data = safe_read_json(cfg_path)
        servers = (data or {}).get("mcpServers")
        if isinstance(servers, dict):
            names.update(str(k) for k in servers.keys())

    # Claude Code: global + per-project (unchanged sources)
    _add(home / ".claude.json")
    # Cursor: global + per-project — only when the Cursor source is consented
    if cursor_enabled:
        _add(home / ".cursor" / "mcp.json")
    for proj in projects or []:
        ppath = proj.get("path") if isinstance(proj, dict) else None
        if not ppath:
            continue
        base = Path(ppath)
        _add(base / ".mcp.json")
        if cursor_enabled:
            _add(base / ".cursor" / "mcp.json")
    # Claude Desktop: names already parsed by the opt-in adapter (consent-gated
    # by the caller passing them only when the Desktop source was scanned)
    for name in desktop_servers or []:
        if name:
            names.add(str(name))

    return len(names), sorted(names)


def compute_normalized(
    claude_data: dict | None,
    cursor_data: dict | None,
    codex_data: dict | None,
    git_data: dict | None,
    desktop_data: dict | None = None,
    *,
    cursor_consented: bool = False,
) -> dict:
    """
    Compute normalized metrics from raw scan data.

    These metrics are the input to the Intent scoring engine
    (signal_clarity, build_stability, decision_weight, etc.).
    Where exact Cursor-specific metrics aren't available from Claude Code
    sessions, we use reasonable heuristics.
    """
    n: dict[str, Any] = {}

    # ── Aggregate counts ──

    total_sessions = 0
    total_scored_commits = 0
    total_ai_code_blocks = 0
    total_plans = 0
    total_conversations = 0
    all_models: set[str] = set()
    earliest_global: str | None = None
    latest_global: str | None = None

    # From Claude Code
    if claude_data:
        total_sessions += claude_data.get("total_sessions", 0)
        for model in claude_data.get("models_used", {}):
            all_models.add(model)
        e = claude_data.get("earliest")
        lt = claude_data.get("latest")
        if e and (earliest_global is None or e < earliest_global):
            earliest_global = e
        if lt and (latest_global is None or lt > latest_global):
            latest_global = lt

    # From Cursor
    cursor_ai = None
    cursor_commits = None
    cursor_convos = None
    cursor_plans_data = None
    cursor_tx = None

    if cursor_data:
        cursor_ai = cursor_data.get("ai_code")
        cursor_commits = cursor_data.get("scored_commits")
        cursor_convos = cursor_data.get("conversations")
        cursor_plans_data = cursor_data.get("plans")
        cursor_tx = cursor_data.get("transcripts")

        if cursor_ai:
            total_ai_code_blocks += cursor_ai.get("totalHashes", 0)
            for model in cursor_ai.get("byModel", {}):
                all_models.add(model)
            e = cursor_ai.get("earliest")
            lt = cursor_ai.get("latest")
            if e and (earliest_global is None or e < earliest_global):
                earliest_global = e
            if lt and (latest_global is None or lt > latest_global):
                latest_global = lt

        if cursor_commits:
            total_scored_commits += cursor_commits.get("totalCommits", 0)

        if cursor_convos:
            total_conversations += cursor_convos.get("totalConversations", 0)
            for model in cursor_convos.get("models", {}):
                all_models.add(model)

        if cursor_plans_data:
            total_plans += cursor_plans_data.get("totalPlans", 0)

        if cursor_tx:
            total_sessions += cursor_tx.get("totalSessions", 0)

    # From Codex
    if codex_data:
        total_sessions += codex_data.get("total_sessions", 0)

    # Project count from git
    project_count = 0
    all_languages: set[str] = set()
    if git_data and git_data.get("projects"):
        project_count = len(git_data["projects"])
        for p in git_data["projects"]:
            for lang in p.get("languages", []):
                all_languages.add(lang)

    # AI usage span
    ai_usage_span_days = days_between(earliest_global, latest_global) or 0

    # ── Populate normalized metrics ──

    n["totalSessions"] = total_sessions
    n["totalScoredCommits"] = total_scored_commits
    n["totalAiCodeBlocks"] = total_ai_code_blocks
    n["projectCount"] = project_count
    n["aiUsageSpanDays"] = ai_usage_span_days
    n["modelCount"] = len(all_models)
    n["planCount"] = total_plans
    n["languageCount"] = len(all_languages)

    # ── Cursor-derived metrics (exact from DB) ──

    if cursor_commits and cursor_commits.get("totalCommits", 0) > 0:
        total_ai = cursor_commits.get("totalAiLines", 0)
        total_human = cursor_commits.get("totalHumanLines", 0)
        total_added = cursor_commits.get("totalLinesAdded", 0)
        total_composer = cursor_commits.get("totalComposerLines", 0)
        cursor_commits.get("totalTabLines", 0)

        # aiLineSurvivalRate: fraction of AI lines that survived into commits
        # High AI percentage in committed code indicates survival
        avg_pct = cursor_commits.get("avgAiPercentage")
        if avg_pct is not None:
            n["aiLineSurvivalRate"] = round(min(avg_pct / 100.0, 1.0), 3)

        # leverageRatio: AI lines per human line
        if total_human > 0:
            n["leverageRatio"] = round(total_ai / total_human, 1)
        elif total_ai > 0:
            n["leverageRatio"] = float(total_ai)

        # composerRatio: composer lines / total AI lines
        if total_ai > 0:
            n["composerRatio"] = round(total_composer / total_ai, 3)

        # postAiEditRate: human edits after AI generation
        # Heuristic: human lines / total lines added = review/edit fraction
        if total_added > 0:
            n["postAiEditRate"] = round(total_human / total_added, 3)

    # ── Conversation/mode metrics from Cursor ──

    if cursor_convos:
        modes = cursor_convos.get("modes", {})
        total_mode_count = sum(modes.values()) if modes else 0
        if total_mode_count > 0:
            agent_count = modes.get("agent", 0) + modes.get("agentic", 0)
            n["agentModeRatio"] = round(agent_count / total_mode_count, 3)

    # ── Plan complexity ──

    if cursor_plans_data and cursor_plans_data.get("plans"):
        plan_lines = [p["lineCount"] for p in cursor_plans_data["plans"] if "lineCount" in p]
        if plan_lines:
            n["avgPlanComplexity"] = round(sum(plan_lines) / len(plan_lines), 1)

    # ── Claude Code derived heuristics ──

    if claude_data and claude_data.get("sessions"):
        sessions_list = claude_data["sessions"]

        # avgTurnsPerTask: real user-message count per session
        total_user = sum(s.get("userMessages", 0) for s in sessions_list)
        if len(sessions_list) > 0 and total_user > 0:
            n["avgTurnsPerTask"] = round(total_user / len(sessions_list), 1)

        # filesPerSession: real count of file-operation tool calls
        total_file_tools = sum(s.get("fileToolCalls", 0) for s in sessions_list)
        if len(sessions_list) > 0:
            n["filesPerSession"] = round(total_file_tools / len(sessions_list), 1)

        # terminalCommandCount: real count of Bash tool-use blocks
        n["terminalCommandCount"] = sum(s.get("terminalToolCalls", 0) for s in sessions_list)

        # avgPromptWords: real word count from user message text
        total_words = sum(s.get("userWordCount", 0) for s in sessions_list)
        if total_user > 0:
            n["avgPromptWords"] = round(total_words / total_user)

    # ── Wrapped signal fields ──

    # peakProductivityHour: bucket session timestamps by hour, find mode
    hour_counts: dict[int, int] = {}
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            ts = s.get("earliest")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    h = dt.hour
                    hour_counts[h] = hour_counts.get(h, 0) + 1
                except Exception:
                    pass
    if hour_counts:
        n["peakProductivityHour"] = max(hour_counts, key=lambda h: hour_counts[h])
    else:
        n["peakProductivityHour"] = 14  # default: afternoons

    # longestStreakDays: gap analysis on session dates, find max consecutive
    session_dates: set[str] = set()
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            for ts_key in ("earliest", "latest"):
                ts = s.get(ts_key)
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        session_dates.add(dt.strftime("%Y-%m-%d"))
                    except Exception:
                        pass
    if session_dates:
        sorted_dates = sorted(session_dates)
        max_streak = 1
        current_streak = 1
        for i in range(1, len(sorted_dates)):
            try:
                prev = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
                curr = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
                if (curr - prev).days == 1:
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 1
            except Exception:
                current_streak = 1
        n["longestStreakDays"] = max_streak
    else:
        n["longestStreakDays"] = 0

    # avgPromptsPerSession: real user-role message count per session
    if claude_data and claude_data.get("sessions"):
        user_msg_counts = [s.get("userMessages", 0) for s in claude_data["sessions"]]
        if user_msg_counts:
            n["avgPromptsPerSession"] = round(sum(user_msg_counts) / len(user_msg_counts), 1)

    # totalEstimatedHours: gap-based active minutes where measured
    # (idle >30min never counts); first-to-last span capped 8h otherwise
    total_minutes = 0.0
    longest_session_min = 0.0
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            am = s.get("activeMinutes")
            if am:
                total_minutes += am
                longest_session_min = max(longest_session_min, am)
                continue
            e = s.get("earliest")
            lt = s.get("latest")
            if e and lt:
                try:
                    dt_e = datetime.fromisoformat(e.replace("Z", "+00:00"))
                    dt_l = datetime.fromisoformat(lt.replace("Z", "+00:00"))
                    dur_min = max(0, (dt_l - dt_e).total_seconds() / 60.0)
                    # Cap single session at 8 hours to avoid outliers
                    dur_min = min(dur_min, 480)
                    total_minutes += dur_min
                    longest_session_min = max(longest_session_min, dur_min)
                except Exception:
                    pass
    n["totalEstimatedHours"] = round(total_minutes / 60.0, 1) if total_minutes > 0 else 0

    # longestSessionMinutes
    n["longestSessionMinutes"] = round(longest_session_min) if longest_session_min > 0 else 0

    # primaryModel: most-used model across all tools
    all_model_counts: dict[str, int] = {}
    if claude_data and claude_data.get("models_used"):
        for model, cnt in claude_data["models_used"].items():
            all_model_counts[model] = all_model_counts.get(model, 0) + cnt
    if cursor_data:
        ai_code = cursor_data.get("ai_code")
        if ai_code and ai_code.get("byModel"):
            for model, cnt in ai_code["byModel"].items():
                all_model_counts[model] = all_model_counts.get(model, 0) + cnt
        convos = cursor_data.get("conversations")
        if convos and convos.get("models"):
            for model, cnt in convos["models"].items():
                all_model_counts[model] = all_model_counts.get(model, 0) + cnt
    if all_model_counts:
        n["primaryModel"] = max(all_model_counts, key=lambda m: all_model_counts[m])

    # ── Tool detection metrics ──

    tools_detected: list[str] = []
    if claude_data:
        tools_detected.append("claude_code")
    if cursor_data:
        tools_detected.append("cursor_ide")
    if codex_data:
        tools_detected.append("codex_cli")

    n["cliAiToolCount"] = len([t for t in tools_detected if t in ("claude_code", "codex_cli")])
    n["uniqueToolCount"] = len(tools_detected) + (
        1 if total_plans > 0 else 0
    )  # +1 for plans as a tool

    # ── MCP server detection (all consented clients, deduped by name) ──
    # Store the COUNT only — normalized is a counts-only block (no names, which
    # can be sensitive like project names; see schema.py privacy note).
    mcp_count, _ = count_mcp_servers(
        HOME,
        (git_data or {}).get("projects", []),
        cursor_enabled=cursor_consented or cursor_data is not None,
        desktop_servers=(desktop_data or {}).get("mcpServers"),
    )
    n["mcpServerCount"] = mcp_count

    # ── Heuristic metrics (derived from available data) ──

    # firstShotAcceptRate: heuristic from AI line survival and low edit rate
    if "aiLineSurvivalRate" in n and "postAiEditRate" in n:
        survival = n["aiLineSurvivalRate"]
        edit_rate = n["postAiEditRate"]
        # High survival + low edit = high first-shot acceptance
        n["firstShotAcceptRate"] = round(min(survival * (1.0 - edit_rate * 0.5), 1.0), 3)
    elif cursor_commits and cursor_commits.get("avgAiPercentage"):
        # Fallback: high AI% in commits suggests good first-shot
        n["firstShotAcceptRate"] = round(min(cursor_commits["avgAiPercentage"] / 100.0, 0.95), 3)

    # referenceUsageRate: heuristic — tool-call density proxies file references
    # ×0.8 weight on tool ratio; plan_boost caps at 0.3 (50 plans = max boost)
    if claude_data and total_plans > 0:
        tool_ratio = claude_data.get("tool_calls", 0) / max(claude_data.get("total_messages", 1), 1)
        plan_boost = min(total_plans / 50.0, 0.3)
        n["referenceUsageRate"] = round(min(tool_ratio * 0.8 + plan_boost, 1.0), 3)
    elif total_plans > 10:
        n["referenceUsageRate"] = round(min(total_plans / 100.0 + 0.3, 0.8), 3)

    # errorFixRate: derived from AI line survival rate
    # +0.05 offset — surviving code implies most errors were already fixed
    if "aiLineSurvivalRate" in n:
        n["errorFixRate"] = round(min(n["aiLineSurvivalRate"] + 0.05, 1.0), 3)

    # errorsPerAiBlock: derived from human edit rate on AI output
    # ×0.15 factor — only a fraction of human edits are actual error corrections
    if "postAiEditRate" in n and total_ai_code_blocks > 0:
        n["errorsPerAiBlock"] = round(n["postAiEditRate"] * 0.15, 3)
    elif total_ai_code_blocks > 0:
        # 0.02 conservative fallback when no edit-rate data is available
        n["errorsPerAiBlock"] = 0.02

    # buildSuccessRate: cannot be measured from available session data
    # (would require CI/build-system logs).  Left as None so the scoring
    # engine skips it and dataCompleteness reflects the gap.

    # correctionConvergenceRate: derived from errorFixRate
    # ×0.9 dampening — convergence is slightly slower than raw fix rate
    if "errorFixRate" in n:
        n["correctionConvergenceRate"] = round(n["errorFixRate"] * 0.9, 3)

    # testAfterAiRate: cannot be measured from available session data
    # (would require test-runner invocation tracking from CI).

    # Signal density (recent vs historical)
    if ai_usage_span_days > 30:
        # Recent = last 30 days signal density, historical = overall
        # Heuristic: if we have recent sessions, recent density is higher
        recent_session_count = 0
        if claude_data and claude_data.get("sessions"):
            now = datetime.now(timezone.utc)
            for s in claude_data["sessions"]:
                try:
                    latest = s.get("latest")
                    if latest:
                        dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                        if (now - dt).days <= 30:
                            recent_session_count += 1
                except Exception:
                    pass

        total_sess = total_sessions if total_sessions > 0 else 1
        n["recentSignalDensity"] = round(
            min(recent_session_count / max(total_sess * 0.3, 1), 1.0), 2
        )
        n["historicalSignalDensity"] = round(
            min(total_sessions / max(ai_usage_span_days / 7, 1), 1.0), 2
        )
    else:
        n["recentSignalDensity"] = 0.5
        n["historicalSignalDensity"] = 0.5

    # Language counts (recent vs historical)
    n["recentLanguageCount"] = len(all_languages)
    n["historicalLanguageCount"] = len(all_languages)

    # ── New taxonomy v0.2.0 signals ──

    # maxParallelAgents: max overlapping sessions by timestamp
    intervals: list[tuple[str, str]] = []
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            e = s.get("earliest")
            lt = s.get("latest")
            if e and lt:
                intervals.append((e, lt))
    if intervals:
        events: list[tuple[str, int]] = []
        for start, end in intervals:
            events.append((start, 1))
            events.append((end, -1))
        events.sort()
        current_par = 0
        max_par = 0
        for _, delta in events:
            current_par += delta
            max_par = max(max_par, current_par)
        n["maxParallelAgents"] = max_par
    else:
        n["maxParallelAgents"] = 1 if total_sessions > 0 else 0

    # mcpToolCalls: count of mcp__* tool calls across sessions
    total_mcp_calls = 0
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            total_mcp_calls += s.get("mcpToolCalls", 0)
    n["mcpToolCalls"] = total_mcp_calls

    # deepSessionCount: sessions longer than 30 minutes
    deep_count = 0
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            e = s.get("earliest")
            lt = s.get("latest")
            if e and lt:
                try:
                    dt_e = datetime.fromisoformat(e.replace("Z", "+00:00"))
                    dt_l = datetime.fromisoformat(lt.replace("Z", "+00:00"))
                    if (dt_l - dt_e).total_seconds() >= 1800:
                        deep_count += 1
                except Exception:
                    pass
    n["deepSessionCount"] = deep_count

    # fileReadToEditRatio: read tools / write tools
    total_read_tools = 0
    total_write_tools = 0
    if claude_data and claude_data.get("sessions"):
        for s in claude_data["sessions"]:
            total_read_tools += s.get("readToolCalls", 0)
            total_write_tools += s.get("writeToolCalls", 0)
    if total_write_tools > 0:
        n["fileReadToEditRatio"] = round(total_read_tools / total_write_tools, 2)
    elif total_read_tools > 0:
        n["fileReadToEditRatio"] = float(total_read_tools)

    # featureToFixRatio: from git commit message classification
    total_feat = 0
    total_fix = 0
    if git_data and git_data.get("projects"):
        for p in git_data["projects"]:
            total_feat += p.get("feat_commits", 0)
            total_fix += p.get("fix_commits", 0)
    if total_fix > 0:
        n["featureToFixRatio"] = round(total_feat / total_fix, 2)
    elif total_feat > 0:
        n["featureToFixRatio"] = float(total_feat)

    # planModePercent: plan sessions / total sessions
    if total_sessions > 0 and total_plans > 0:
        n["planModePercent"] = round(total_plans / total_sessions * 100, 1)
    else:
        n["planModePercent"] = 0.0

    # questionRatio: heuristic — short prompts with "?" are questions
    # (cannot detect precisely without reading raw text; set None)

    return n


# ── Summary Builder ──────────────────────────────────────────────────────────


def build_summary(
    claude_data: dict | None,
    cursor_data: dict | None,
    codex_data: dict | None,
    git_data: dict | None,
    normalized: dict,
) -> dict:
    """Build the top-level summary object."""
    tools_detected: list[str] = []
    if claude_data:
        tools_detected.append("claude_code")
    if cursor_data:
        tools_detected.append("cursor_ide")
    if codex_data:
        tools_detected.append("codex_cli")

    _junk = {"<synthetic>", "synthetic", ""}
    all_models: list[str] = []
    if claude_data:
        all_models.extend(
            m
            for m in claude_data.get("models_used", {}).keys()
            if m.strip() and m.strip().lower() not in _junk
        )
    if cursor_data:
        ai_code = cursor_data.get("ai_code")
        if ai_code:
            all_models.extend(
                m
                for m in ai_code.get("byModel", {}).keys()
                if m.strip() and m.strip().lower() not in _junk
            )
        convos = cursor_data.get("conversations")
        if convos:
            all_models.extend(
                m
                for m in convos.get("models", {}).keys()
                if m.strip() and m.strip().lower() not in _junk
            )
    # Deduplicate
    all_models = sorted(set(all_models))

    return {
        "total_sessions": normalized.get("totalSessions", 0),
        "total_ai_blocks": normalized.get("totalAiCodeBlocks", 0),
        "total_scored_commits": normalized.get("totalScoredCommits", 0),
        "total_plans": normalized.get("planCount", 0),
        "total_projects": normalized.get("projectCount", 0),
        "ai_usage_span_days": normalized.get("aiUsageSpanDays", 0),
        "models_used": all_models,
    }


# ── Tool Listing ─────────────────────────────────────────────────────────────


def list_tools() -> None:
    """Print detected AI tools and session counts to stdout."""
    print("nextmillionai Scanner — Detected AI Tools")
    print("=" * 50)

    # Claude Code
    if CLAUDE_PROJECTS_DIR.exists():
        project_dirs = [
            d for d in CLAUDE_PROJECTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
        ]
        total_jsonl = sum(1 for d in project_dirs for _ in d.glob("*.jsonl"))
        print("\n  Claude Code")
        print(f"    Path:     {CLAUDE_PROJECTS_DIR}")
        print(f"    Projects: {len(project_dirs)}")
        print(f"    Sessions: {total_jsonl}")
    else:
        print(f"\n  Claude Code: not found ({CLAUDE_PROJECTS_DIR})")

    # Cursor IDE
    if CURSOR_DIR.exists():
        print("\n  Cursor IDE")
        print(f"    Path:     {CURSOR_DIR}")
        if CURSOR_DB_PATH.exists():
            row = sqlite_query(CURSOR_DB_PATH, "SELECT COUNT(*) as cnt FROM ai_code_hashes")
            cnt = row[0]["cnt"] if row else 0
            print(f"    AI Code Blocks: {cnt}")
            row2 = sqlite_query(CURSOR_DB_PATH, "SELECT COUNT(*) as cnt FROM scored_commits")
            cnt2 = row2[0]["cnt"] if row2 else 0
            print(f"    Scored Commits: {cnt2}")
            row3 = sqlite_query(
                CURSOR_DB_PATH, "SELECT COUNT(*) as cnt FROM conversation_summaries"
            )
            cnt3 = row3[0]["cnt"] if row3 else 0
            print(f"    Conversations:  {cnt3}")
        else:
            print(f"    DB: not found ({CURSOR_DB_PATH})")
        if CURSOR_PLANS_DIR.exists():
            plans = list(CURSOR_PLANS_DIR.glob("*.plan.md"))
            print(f"    Plans:    {len(plans)}")
        if CURSOR_PROJECTS_DIR.exists():
            tx_count = 0
            for d in CURSOR_PROJECTS_DIR.iterdir():
                tx_dir = d / "agent-transcripts"
                if tx_dir.exists():
                    tx_count += sum(1 for s in tx_dir.iterdir() if s.is_dir())
            print(f"    Transcript Sessions: {tx_count}")
    else:
        print(f"\n  Cursor IDE: not found ({CURSOR_DIR})")

    # Codex CLI
    if CODEX_SESSIONS_DIR.exists():
        sessions = [f for f in CODEX_SESSIONS_DIR.iterdir() if f.is_file()]
        print("\n  Codex CLI")
        print(f"    Path:     {CODEX_SESSIONS_DIR}")
        print(f"    Sessions: {len(sessions)}")
    else:
        print(f"\n  Codex CLI: not found ({CODEX_SESSIONS_DIR})")

    # Kiro (CLI + IDE)
    kiro_ide_found = [d for d in KIRO_IDE_DIRS if d.exists()]
    if KIRO_SESSIONS_DIR.exists() or kiro_ide_found:
        print("\n  Kiro")
        if KIRO_SESSIONS_DIR.exists():
            kiro_sessions = [
                f
                for f in KIRO_SESSIONS_DIR.iterdir()
                if f.suffix == ".json" and not f.name.endswith(".lock")
            ]
            print(f"    CLI Path:     {KIRO_SESSIONS_DIR}")
            print(f"    CLI Sessions: {len(kiro_sessions)}")
        for d in kiro_ide_found:
            print(f"    IDE Storage:  {d}")
    else:
        print(f"\n  Kiro: not found ({KIRO_SESSIONS_DIR})")

    # Git projects
    projects = discover_project_paths()
    print(f"\n  Git Projects: {len(projects)}")
    for p in projects:
        print(f"    - {p}")

    print()


if __name__ == "__main__":
    from nextmillionai.build_profile import main as _cli_main

    _cli_main()
