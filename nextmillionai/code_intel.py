"""
nextmillionai.code_intel -- Experimental local code scan (opt-in `assess --code`).

Reads repository files locally and reduces them to METRICS ONLY:
structure, dependency names, test/doc presence, complexity hotspots,
deploy configs. Source code content is never stored and never sent —
only counts, names, and line totals survive the scan.

Feeds: positioning.buildDomain (manifest-grade evidence, tagged
"code scan") and experimental.codeIntelligence[] (report Experimental
tab + profile Details only; never shareable).

See CODE-INTELLIGENCE.md for the module contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Bounds — keep the scan cheap and predictable
_MAX_FILES_PER_REPO = 4000
_MAX_FILE_BYTES = 1_000_000
_HOTSPOT_LINES = 500

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    "vendor",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "coverage",
    ".cache",
}

_SOURCE_EXTS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
}

_TEST_HINTS = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|^spec_|/tests?/)")

_DEPLOY_FILES = {
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    "vercel.json": "Vercel",
    "fly.toml": "Fly.io",
    "netlify.toml": "Netlify",
    "render.yaml": "Render",
    "Procfile": "Heroku/Procfile",
    "app.yaml": "App Engine",
}

# Dependency names → build-domain markers (lowercase substring match)
_AGENT_FRAMEWORK_DEPS = {
    "langgraph": "LangGraph",
    "crewai": "CrewAI",
    "autogen": "AutoGen",
    "semantic-kernel": "Semantic Kernel",
    "llama-index": "LlamaIndex",
    "llamaindex": "LlamaIndex",
    "haystack": "Haystack",
    "@modelcontextprotocol": "MCP SDK",
    "mcp": "MCP SDK",
    "openai-agents": "OpenAI Agents",
    "claude-agent-sdk": "Claude Agent SDK",
    "@anthropic-ai/claude-agent-sdk": "Claude Agent SDK",
}
_LLM_SDK_DEPS = {
    "anthropic": "Anthropic SDK",
    "@anthropic-ai/sdk": "Anthropic SDK",
    "openai": "OpenAI SDK",
    "google-generativeai": "Gemini SDK",
    "@google/generative-ai": "Gemini SDK",
    "cohere": "Cohere SDK",
    "mistralai": "Mistral SDK",
    "transformers": "Transformers",
    "litellm": "LiteLLM",
    "langchain": "LangChain",
}


def _iter_files(repo: Path):
    """Walk a repo, skipping vendored/dot dirs, bounded by _MAX_FILES_PER_REPO."""
    count = 0
    stack = [repo]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                    if entry != repo and (entry / ".git").exists():
                        # Nested repo (vendored clone / submodule) — its own
                        # scan unit. Its commits aren't in the parent's git
                        # log; crossing the boundary would let another
                        # repo's code shape this repo's metrics, and count
                        # it twice if a session ever lands there.
                        continue
                    stack.append(entry)
                elif entry.name == ".github":
                    stack.append(entry)  # CI workflows are a deploy signal
            elif entry.is_file():
                count += 1
                if count > _MAX_FILES_PER_REPO:
                    return
                yield entry


def _count_lines(path: Path) -> int:
    """Count lines without keeping content; skip oversized files."""
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return 0
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except (PermissionError, OSError):
        return 0


def _dep_names(repo: Path) -> list[str]:
    """Extract dependency NAMES (never versions/urls) from manifests."""
    names: set[str] = set()

    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="replace"))
            for key in ("dependencies", "devDependencies"):
                deps = data.get(key)
                if isinstance(deps, dict):
                    names.update(deps.keys())
        except (json.JSONDecodeError, OSError):
            pass

    for req in ("requirements.txt", "requirements-dev.txt"):
        req_file = repo / req
        if req_file.is_file():
            try:
                for line in req_file.read_text(errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "-")):
                        names.add(re.split(r"[<>=!~\[;]", line)[0].strip().lower())
            except OSError:
                pass

    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(errors="replace")
            in_deps = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("dependencies"):
                    in_deps = True
                    continue
                if in_deps:
                    if stripped.startswith("]"):
                        in_deps = False
                        continue
                    m = re.match(r'"([A-Za-z0-9._@/\-]+)', stripped)
                    if m:
                        names.add(m.group(1).lower())
        except OSError:
            pass

    go_mod = repo / "go.mod"
    if go_mod.is_file():
        try:
            for line in go_mod.read_text(errors="replace").splitlines():
                m = re.match(r"\s*([a-z0-9./\-]+)\s+v[\d.]", line)
                if m:
                    names.add(m.group(1).split("/")[-1].lower())
        except OSError:
            pass

    cargo = repo / "Cargo.toml"
    if cargo.is_file():
        try:
            in_deps = False
            for line in cargo.read_text(errors="replace").splitlines():
                stripped = line.strip()
                if stripped.startswith("["):
                    in_deps = stripped.startswith("[dependencies")
                    continue
                if in_deps:
                    m = re.match(r"([a-z0-9_\-]+)\s*=", stripped)
                    if m:
                        names.add(m.group(1).lower())
        except OSError:
            pass

    return sorted(names)


def _match_markers(dep_names: list[str], markers: dict[str, str]) -> list[str]:
    found: set[str] = set()
    for dep in dep_names:
        dep_l = dep.lower()
        for needle, label in markers.items():
            if dep_l == needle or dep_l.startswith(needle + "-") or dep_l.endswith("/" + needle):
                found.add(label)
    return sorted(found)


# Import-line and call-site patterns: usage VERIFICATION beyond manifest
# presence. A declared-but-never-imported SDK must not classify a repo.
# Matching is per line, reduced to counts only — content never survives.
_LLM_IMPORT_RE = re.compile(
    r"""(?xi)
    ^\s*(?:from|import)\s+(?:anthropic|openai|cohere|mistralai|litellm|groq|
        replicate|ollama|transformers|google\.generativeai|google\.genai)\b
    | require\(\s*['\"](?:@anthropic-ai/sdk|openai|@google/generative-ai|
        cohere-ai|@mistralai|groq-sdk|replicate|ollama|ai)['\"]
    | from\s+['\"](?:@anthropic-ai/sdk|openai|@google/generative-ai|
        cohere-ai|@mistralai|groq-sdk|replicate|ollama|ai|@ai-sdk/)
    """
)
_LLM_CALLSITE_RE = re.compile(
    r"\.messages\.create\(|\.chat\.completions|\.responses\.create\(|"
    r"generateText\(|streamText\(|generateContent\(|generateObject\(|"
    r"\.embeddings\.create\(|\.complete\(|\.generate\(\s*model|"
    # Raw HTTP integrations: products that call model APIs without an
    # SDK dep (endpoint URLs + wire paths are real call-site evidence)
    r"api\.anthropic\.com|api\.openai\.com|generativelanguage\.googleapis\.com|"
    r"api\.mistral\.ai|api\.groq\.com|openrouter\.ai/api|"
    r"/v1/messages['\"]|/v1/chat/completions"
)
_AGENT_IMPORT_RE = re.compile(
    r"""(?xi)
    ^\s*(?:from|import)\s+(?:langgraph|langchain|crewai|autogen|semantic_kernel|
        llama_index|haystack|fastmcp|mcp\b|claude_agent_sdk)
    | require\(\s*['\"](?:@modelcontextprotocol/|langchain|@langchain/|
        @anthropic-ai/claude-agent-sdk)
    | from\s+['\"](?:@modelcontextprotocol/|langchain|@langchain/|
        @anthropic-ai/claude-agent-sdk)
    """
)
_AGENT_CALLSITE_RE = re.compile(
    r"FastMCP\(|StateGraph\(|create_react_agent\(|Crew\(|new\s+Server\(|"
    r"McpServer\(|AgentExecutor\(|\.add_node\("
)

_AI_SCAN_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs"}


def _scan_ai_usage_line(line: str, usage: dict) -> None:
    if _LLM_IMPORT_RE.search(line):
        usage["llmImports"] += 1
    if _LLM_CALLSITE_RE.search(line):
        usage["llmCallSites"] += 1
    if _AGENT_IMPORT_RE.search(line):
        usage["agentImports"] += 1
    if _AGENT_CALLSITE_RE.search(line):
        usage["agentCallSites"] += 1


_MANIFEST_NAMES = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
)


def _find_package_roots(repo: Path, max_packages: int = 40) -> list:
    """Package roots inside a repo: the root itself plus every directory
    holding its own manifest (pnpm/yarn/npm workspaces, lerna, nx,
    turborepo, plain nested packages, Python sub-projects — all reduce
    to "a dir with a manifest", so recursive discovery covers every
    workspace flavor without parsing each tool's config). Bounded;
    skips vendored/dot dirs and nested repos (own .git = not a package
    of THIS repo — its verdict must not feed this repo's aggregation)."""
    roots = [repo]
    stack = [repo]
    while stack and len(roots) < max_packages:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            if (entry / ".git").exists():
                continue
            if any((entry / m).is_file() for m in _MANIFEST_NAMES):
                roots.append(entry)
            stack.append(entry)
    return roots


def aggregate_monorepo_domain(package_verdicts: list) -> dict:
    """Repo-level build domain from per-package verdicts.

    Rule (documented in ADAPTERS/TRUST): if ANY package wires an LLM
    behind product code, the repo ships an AI product — internal agent
    tooling (a vendored MCP/dev package) doesn't redefine the product.
    ai_products > ai_systems > products at the AGGREGATION level only;
    per-package precedence is unchanged (a single-package MCP server
    still classifies ai_systems).
    """
    domains = {v["pkg"]: v["verdict"] for v in package_verdicts}
    by_class: dict = {"ai_products": [], "ai_systems": [], "products": []}
    for pkg, verdict in domains.items():
        by_class[verdict["domain"]].append(pkg)

    if by_class["ai_products"]:
        winners = by_class["ai_products"]
        evidence = (
            f"monorepo: {len(domains)} packages scanned; LLM wired behind product "
            f"code in: {', '.join(sorted(winners)[:4])}"
        )
        if by_class["ai_systems"]:
            evidence += (
                f" (agent infra in {', '.join(sorted(by_class['ai_systems'])[:3])} "
                "stays internal tooling)"
            )
        return {"domain": "ai_products", "evidence": evidence, "verified": True}
    if by_class["ai_systems"]:
        return {
            "domain": "ai_systems",
            "evidence": (
                f"monorepo: {len(domains)} packages scanned; agent/MCP infrastructure "
                f"in: {', '.join(sorted(by_class['ai_systems'])[:4])}"
            ),
            "verified": True,
        }
    return {
        "domain": "products",
        "evidence": f"monorepo: {len(domains)} packages scanned; no verified AI usage",
        "verified": True,
    }


def classify_build_domain(repo_metrics: dict) -> dict:
    """Per-repo build-domain verdict from deps + verified usage.

    ai_systems  — agent framework / MCP server wired as infrastructure
                  (declared AND imported/called)
    ai_products — LLM SDK wired behind product code (declared AND
                  imported/called)
    products    — neither, or declared-but-unused (presence is NOT usage)
    """
    usage = repo_metrics.get("aiUsage") or {}
    agent_deps = repo_metrics.get("agentFrameworks") or []
    llm_deps = repo_metrics.get("llmSdks") or []
    agent_used = (usage.get("agentImports", 0) + usage.get("agentCallSites", 0)) > 0
    llm_used = (usage.get("llmImports", 0) + usage.get("llmCallSites", 0)) > 0

    if agent_used:
        return {
            "domain": "ai_systems",
            "evidence": (
                f"agent framework imports verified in source "
                f"({usage.get('agentImports', 0)} import lines, "
                f"{usage.get('agentCallSites', 0)} call sites)"
            ),
            "verified": True,
        }
    if llm_used:
        return {
            "domain": "ai_products",
            "evidence": (
                f"LLM SDK imports verified in source "
                f"({usage.get('llmImports', 0)} import lines, "
                f"{usage.get('llmCallSites', 0)} call sites)"
            ),
            "verified": True,
        }
    if agent_deps or llm_deps:
        declared = ", ".join(sorted(set(agent_deps + llm_deps)))
        return {
            "domain": "products",
            "evidence": f"{declared} declared in manifests but never imported — not counted",
            "verified": True,
        }
    return {"domain": "products", "evidence": "no AI dependencies", "verified": True}


def scan_repo(repo_path: str) -> dict | None:
    """Scan one repo to metrics. Returns None if the path isn't a directory."""
    repo = Path(repo_path).expanduser()
    if not repo.is_dir():
        return None

    files_by_lang: dict[str, int] = {}
    lines_by_lang: dict[str, int] = {}
    source_files = 0
    test_files = 0
    doc_files = 0
    has_readme = False
    workflows = 0
    deploy: set[str] = set()
    hotspots: list[tuple[str, int]] = []
    ai_usage = {"llmImports": 0, "llmCallSites": 0, "agentImports": 0, "agentCallSites": 0}

    # Monorepo support: classify per PACKAGE, not per repo — a vendored
    # MCP/dev sub-package must not redefine an AI product (and an AI
    # sub-package must not vanish into a plain-product root).
    package_roots = _find_package_roots(repo)
    pkg_strs = sorted((str(r) for r in package_roots), key=len, reverse=True)
    pkg_usage: dict = {
        s: {"llmImports": 0, "llmCallSites": 0, "agentImports": 0, "agentCallSites": 0}
        for s in pkg_strs
    }

    def _pkg_for(path_str: str) -> str:
        for s in pkg_strs:  # longest prefix = nearest package root
            if path_str.startswith(s):
                return s
        return str(repo)

    for f in _iter_files(repo):
        rel = str(f.relative_to(repo))
        name = f.name

        if name in _DEPLOY_FILES:
            deploy.add(_DEPLOY_FILES[name])
        if "/.github/workflows/" in f"/{rel}" and f.suffix in (".yml", ".yaml"):
            workflows += 1
        if name.lower().startswith("readme"):
            has_readme = True
        if f.suffix.lower() in (".md", ".rst") or "/docs/" in f"/{rel}/":
            doc_files += 1

        lang = _SOURCE_EXTS.get(f.suffix.lower())
        if not lang:
            continue
        source_files += 1
        files_by_lang[lang] = files_by_lang.get(lang, 0) + 1

        if f.suffix.lower() in _AI_SCAN_EXTS:
            # One decoded pass: line count + AI import/call-site counts.
            # Counts only — line content never survives this loop.
            n_lines = 0
            file_pkg = pkg_usage[_pkg_for(str(f))]
            try:
                if f.stat().st_size <= _MAX_FILE_BYTES:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            n_lines += 1
                            _scan_ai_usage_line(line, ai_usage)
                            _scan_ai_usage_line(line, file_pkg)
            except (PermissionError, OSError):
                n_lines = 0
        else:
            n_lines = _count_lines(f)
        lines_by_lang[lang] = lines_by_lang.get(lang, 0) + n_lines

        if _TEST_HINTS.search(f"/{rel}".lower()):
            test_files += 1
        elif n_lines >= _HOTSPOT_LINES:
            hotspots.append((rel, n_lines))

    hotspots.sort(key=lambda x: -x[1])
    deps = _dep_names(repo)

    metrics = {
        "name": repo.name,
        "path": str(repo),
        "sourceFiles": source_files,
        "filesByLang": files_by_lang,
        "linesByLang": lines_by_lang,
        "testFiles": test_files,
        "testRatio": round(test_files / source_files, 3) if source_files else 0.0,
        "docFiles": doc_files,
        "hasReadme": has_readme,
        "ciWorkflows": workflows,
        "deployConfigs": sorted(deploy),
        "depCount": len(deps),
        "agentFrameworks": _match_markers(deps, _AGENT_FRAMEWORK_DEPS),
        "llmSdks": _match_markers(deps, _LLM_SDK_DEPS),
        "aiUsage": ai_usage,
        "hotspots": [{"file": rel, "lines": n} for rel, n in hotspots[:3]],
    }
    if len(package_roots) > 1:
        # Per-package verdicts → aggregated repo domain (rule documented
        # in aggregate_monorepo_domain). Existing shape preserved.
        verdicts: list[dict] = []
        for root in package_roots:
            s = str(root)
            pkg_deps = _dep_names(root)
            pkg_metrics = {
                "llmSdks": _match_markers(pkg_deps, _LLM_SDK_DEPS),
                "agentFrameworks": _match_markers(pkg_deps, _AGENT_FRAMEWORK_DEPS),
                "aiUsage": pkg_usage[s],
            }
            label = str(root.relative_to(repo)) if root != repo else "."
            verdicts.append({"pkg": label, "verdict": classify_build_domain(pkg_metrics)})
        metrics["packages"] = [
            {"pkg": v["pkg"], "domain": v["verdict"]["domain"]} for v in verdicts
        ]
        metrics["buildDomain"] = aggregate_monorepo_domain(verdicts)
    else:
        metrics["buildDomain"] = classify_build_domain(metrics)
    return metrics


def build_code_intelligence(repos: list[dict]) -> list[dict]:
    """Reduce per-repo metrics to codeIntelligence cards.

    Card shape (matches the report Experimental tab):
    {label, title, find, sugg, basis, confidence, kind}.
    Only emits cards the data actually supports — no padding.
    """
    cards: list[dict] = []

    for repo in repos:
        name = repo["name"]
        for spot in repo.get("hotspots", []):
            cards.append(
                {
                    "label": "Refactor hotspot",
                    "title": f"{name}: {spot['file']}",
                    "find": f"{spot['lines']} lines in one file.",
                    "sugg": "A natural seam for an agent-assisted decomposition pass.",
                    "basis": f"Line count, measured locally in {name}.",
                    "confidence": 60,
                    "kind": "measured",
                }
            )

        if repo["sourceFiles"] >= 20 and repo["testRatio"] < 0.1:
            cards.append(
                {
                    "label": "Test gap",
                    "title": f"{name}: thin test coverage signal",
                    "find": (
                        f"{repo['testFiles']} test files for {repo['sourceFiles']} source files."
                    ),
                    "sugg": "Test scaffolding is highly decomposable agent work.",
                    "basis": f"File-name heuristic in {name} (not a coverage run).",
                    "confidence": 45,
                    "kind": "estimate",
                }
            )

        if repo["sourceFiles"] >= 10 and not repo["hasReadme"]:
            cards.append(
                {
                    "label": "Doc gap",
                    "title": f"{name}: no README",
                    "find": "No README found at the repo root.",
                    "sugg": "One agent pass over the code can draft an honest one.",
                    "basis": f"File presence check in {name}.",
                    "confidence": 80,
                    "kind": "measured",
                }
            )

        if repo.get("deployConfigs") and not repo.get("ciWorkflows"):
            cards.append(
                {
                    "label": "Harness suggestion",
                    "title": f"{name}: deploy config without CI",
                    "find": f"{', '.join(repo['deployConfigs'])} present, no CI workflows.",
                    "sugg": "A CI check before deploy is a one-session agent task.",
                    "basis": f"Config file presence in {name}.",
                    "confidence": 70,
                    "kind": "measured",
                }
            )

    return cards


def scan_repos(repo_paths: list[str]) -> dict:
    """Scan all repos; return metrics + cards + build-domain evidence.

    The returned dict is METRICS ONLY — safe to persist in scan results.
    It still lives under experimental visibility: never shareable.
    """
    repos: list[dict] = []
    for path in repo_paths:
        result = scan_repo(path)
        if result:
            repos.append(result)

    agent_frameworks: set[str] = set()
    llm_sdks: set[str] = set()
    for repo in repos:
        agent_frameworks.update(repo.get("agentFrameworks", []))
        llm_sdks.update(repo.get("llmSdks", []))

    return {
        "available": bool(repos),
        "reposScanned": len(repos),
        "repos": repos,
        "agentFrameworks": sorted(agent_frameworks),
        "llmSdks": sorted(llm_sdks),
        "codeIntelligence": build_code_intelligence(repos),
    }
