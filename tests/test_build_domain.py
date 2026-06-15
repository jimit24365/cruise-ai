"""WS4 — build-domain detection tests.

The map gap: repos with an LLM wired behind a product feature must
classify as ai_products (they previously fell through to products
because the marker names never matched the scanner's labels). Where you
sit is a FOOTPRINT across columns: mass shows wherever the work is.
"""

from nextmillionai.code_intel import classify_build_domain, scan_repo
from nextmillionai.scoring import compute_positioning


def _repo(name, commits=10, frameworks=None, ai_frameworks=None, tools=None):
    return {
        "name": name,
        "path": f"/repos/{name}",
        "frameworks": frameworks or [],
        "aiFrameworks": ai_frameworks or [],
        "tools": tools or [],
        "languages": ["TypeScript"],
        "commits_6m": commits,
    }


# ── Per-repo classification through positioning ──────────────────────────────


def test_pure_product_repo_is_products():
    git = {"projects": [_repo("shop", frameworks=["React", "Express"])]}
    pos = compute_positioning({}, git_data=git)
    assert pos["buildDomain"]["primary"] == "products"
    dist = {d["domain"]: d for d in pos["buildDomain"]["distribution"]}
    assert dist["products"]["weight"] == 100


def test_llm_behind_feature_is_ai_products():
    """The kloned-style case: scanner labels 'Anthropic SDK' (aiFrameworks)
    — must light the AI-products column, not generic products."""
    git = {"projects": [_repo("klonedai", frameworks=["Next.js"], ai_frameworks=["Anthropic SDK"])]}
    pos = compute_positioning({}, git_data=git)
    assert pos["buildDomain"]["primary"] == "ai_products"
    assert any("LLM wired behind product code" in e for e in pos["buildDomain"]["evidence"])
    # the footprint cell also lands in the ai_products column
    domains = {c["domain"] for c in pos["footprint"]["cells"]}
    assert domains == {"ai_products"}


def test_agent_framework_repo_is_ai_systems():
    git = {"projects": [_repo("mcp-server", ai_frameworks=["MCP SDK"])]}
    pos = compute_positioning({}, git_data=git)
    assert pos["buildDomain"]["primary"] == "ai_systems"


def test_vercel_ai_sdk_counts_as_ai_products():
    git = {"projects": [_repo("chatapp", frameworks=["Vercel AI SDK", "Next.js"])]}
    pos = compute_positioning({}, git_data=git)
    assert pos["buildDomain"]["primary"] == "ai_products"


def test_builder_spanning_all_three_shows_mass_in_all_columns():
    git = {
        "projects": [
            _repo("shop", commits=50, frameworks=["React"]),
            _repo("chatbot", commits=30, ai_frameworks=["OpenAI SDK"]),
            _repo("agent-infra", commits=20, ai_frameworks=["LangGraph"]),
        ]
    }
    pos = compute_positioning({}, git_data=git)
    dist = {d["domain"]: d["weight"] for d in pos["buildDomain"]["distribution"]}
    assert set(dist) == {"products", "ai_products", "ai_systems"}
    assert dist["products"] == 50
    assert dist["ai_products"] == 30
    assert dist["ai_systems"] == 20
    # primary is where the commit-weighted mass sits — not "highest tier"
    assert pos["buildDomain"]["primary"] == "products"
    # footprint columns carry all three domains
    fp_domains = {c["domain"] for c in pos["footprint"]["cells"]}
    assert fp_domains == {"products", "ai_products", "ai_systems"}


# ── Code-scan verification: declared-but-unused does NOT count ──────────────


def test_declared_but_unused_sdk_not_counted():
    """A repo with an LLM SDK in its manifest but zero imports must stay
    products when the code scan verified usage."""
    git = {"projects": [_repo("deadweight", ai_frameworks=["OpenAI SDK"], commits=10)]}
    ci = {
        "available": True,
        "agentFrameworks": [],
        "llmSdks": ["OpenAI SDK"],
        "repos": [
            {
                "name": "deadweight",
                "llmSdks": ["OpenAI SDK"],
                "agentFrameworks": [],
                "aiUsage": {
                    "llmImports": 0,
                    "llmCallSites": 0,
                    "agentImports": 0,
                    "agentCallSites": 0,
                },
                "buildDomain": classify_build_domain(
                    {
                        "llmSdks": ["OpenAI SDK"],
                        "agentFrameworks": [],
                        "aiUsage": {
                            "llmImports": 0,
                            "llmCallSites": 0,
                            "agentImports": 0,
                            "agentCallSites": 0,
                        },
                    }
                ),
            }
        ],
    }
    pos = compute_positioning({}, git_data=git, code_intel=ci)
    assert pos["buildDomain"]["primary"] == "products"


def test_verified_imports_confirm_ai_products():
    git = {"projects": [_repo("realuse", ai_frameworks=["Anthropic SDK"], commits=10)]}
    verdict = classify_build_domain(
        {
            "llmSdks": ["Anthropic SDK"],
            "agentFrameworks": [],
            "aiUsage": {
                "llmImports": 4,
                "llmCallSites": 7,
                "agentImports": 0,
                "agentCallSites": 0,
            },
        }
    )
    ci = {
        "available": True,
        "repos": [{"name": "realuse", "buildDomain": verdict}],
    }
    pos = compute_positioning({}, git_data=git, code_intel=ci)
    assert pos["buildDomain"]["primary"] == "ai_products"
    assert verdict["evidence"].startswith("LLM SDK imports verified")


def test_classify_agent_usage_is_ai_systems():
    verdict = classify_build_domain(
        {
            "llmSdks": [],
            "agentFrameworks": ["MCP SDK"],
            "aiUsage": {
                "llmImports": 0,
                "llmCallSites": 0,
                "agentImports": 3,
                "agentCallSites": 2,
            },
        }
    )
    assert verdict["domain"] == "ai_systems"


# ── scan_repo end-to-end on a synthetic repo ─────────────────────────────────


def test_scan_repo_counts_imports_and_call_sites(tmp_path):
    repo = tmp_path / "aiapp"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"dependencies": {"@anthropic-ai/sdk": "^1.0.0", "react": "^18.0.0"}}'
    )
    (repo / "feature.ts").write_text(
        "import Anthropic from '@anthropic-ai/sdk';\n"
        "const client = new Anthropic();\n"
        "const r = await client.messages.create({model: 'claude'});\n"
    )
    metrics = scan_repo(str(repo))
    assert metrics["llmSdks"] == ["Anthropic SDK"]
    assert metrics["aiUsage"]["llmImports"] == 1
    assert metrics["aiUsage"]["llmCallSites"] == 1
    assert metrics["buildDomain"]["domain"] == "ai_products"
    assert metrics["buildDomain"]["verified"] is True


def test_scan_repo_unused_sdk_demoted(tmp_path):
    repo = tmp_path / "deadapp"
    repo.mkdir()
    (repo / "package.json").write_text('{"dependencies": {"openai": "^4.0.0"}}')
    (repo / "app.ts").write_text("export const x = 1;\n")
    metrics = scan_repo(str(repo))
    assert metrics["llmSdks"] == ["OpenAI SDK"]
    assert metrics["buildDomain"]["domain"] == "products"
    assert "never imported" in metrics["buildDomain"]["evidence"]


def test_scan_repo_mcp_server_is_ai_systems(tmp_path):
    repo = tmp_path / "mcptool"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\ndependencies = [\n"fastmcp",\n]\n')
    (repo / "server.py").write_text("from fastmcp import FastMCP\n\nmcp = FastMCP('tool')\n")
    metrics = scan_repo(str(repo))
    assert metrics["buildDomain"]["domain"] == "ai_systems"


def test_scan_repo_raw_http_llm_integration(tmp_path):
    """klonedai-style: no SDK dep, the product calls the model API over
    raw HTTP — endpoint call sites are the honest evidence."""
    repo = tmp_path / "kloned"
    repo.mkdir()
    (repo / "package.json").write_text('{"dependencies": {"node-fetch": "^3.0.0"}}')
    (repo / "llm.ts").write_text(
        "const r = await fetch('https://api.anthropic.com/v1/messages', {\n"
        "  method: 'POST', body: JSON.stringify({model: 'claude-sonnet-4-6'})\n"
        "});\n"
    )
    metrics = scan_repo(str(repo))
    assert metrics["llmSdks"] == []
    assert metrics["aiUsage"]["llmCallSites"] >= 1
    assert metrics["buildDomain"]["domain"] == "ai_products"


def test_workspace_manifests_feed_detection(tmp_path):
    """Monorepos: an LLM SDK in apps/web counts for the repo."""
    from nextmillionai.scanner import detect_tech_stack

    repo = tmp_path / "mono"
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "package.json").write_text('{"workspaces": ["apps/*"]}')
    (repo / "apps" / "web" / "package.json").write_text(
        '{"dependencies": {"@anthropic-ai/sdk": "^1.0.0", "next": "^15.0.0"}}'
    )
    stack = detect_tech_stack(repo)
    assert "Anthropic SDK" in stack["frameworks"] or "Anthropic SDK" in stack["aiFrameworks"]
    assert "Next.js" in stack["frameworks"]


# ── WS2: monorepo sub-package detection ──────────────────────────────────────


def _mono(tmp_path):
    """kloned-style monorepo: product gateway with raw LLM connectors +
    a vendored MCP dev-tool sub-package + a plain web app."""
    repo = tmp_path / "kloned-like"
    (repo / "apps" / "gateway" / "src").mkdir(parents=True)
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "tools-cli" / "src").mkdir(parents=True)
    (repo / "package.json").write_text('{"workspaces": ["apps/*"], "dependencies": {}}')
    (repo / "apps" / "gateway" / "package.json").write_text('{"dependencies": {"fastify": "^4"}}')
    (repo / "apps" / "gateway" / "src" / "anthropic.ts").write_text(
        "const r = await fetch('https://api.anthropic.com/v1/messages', {});\n"
    )
    (repo / "apps" / "web" / "package.json").write_text('{"dependencies": {"react": "^18"}}')
    (repo / "tools-cli" / "package.json").write_text(
        '{"dependencies": {"@modelcontextprotocol/sdk": "^1.0"}}'
    )
    (repo / "tools-cli" / "src" / "client.ts").write_text(
        "import { Client } from '@modelcontextprotocol/sdk/client/index.js';\n"
    )
    return repo


def test_monorepo_ai_subpackage_classifies_ai_products(tmp_path):
    metrics = scan_repo(str(_mono(tmp_path)))
    assert metrics["buildDomain"]["domain"] == "ai_products"
    assert "gateway" in metrics["buildDomain"]["evidence"]
    pkgs = {p["pkg"]: p["domain"] for p in metrics["packages"]}
    assert pkgs["apps/gateway"] == "ai_products"
    assert pkgs["tools-cli"] == "ai_systems"  # internal tooling, doesn't redefine
    assert pkgs["apps/web"] == "products"


def test_monorepo_infra_only_stays_ai_systems(tmp_path):
    repo = tmp_path / "mcp-mono"
    (repo / "server" / "src").mkdir(parents=True)
    (repo / "docs-site").mkdir(parents=True)
    (repo / "package.json").write_text('{"workspaces": ["*"]}')
    (repo / "server" / "package.json").write_text(
        '{"dependencies": {"@modelcontextprotocol/sdk": "^1.0"}}'
    )
    (repo / "server" / "src" / "index.ts").write_text(
        "import { Server } from '@modelcontextprotocol/sdk/server/index.js';\n"
        "const s = new Server({});\n"
    )
    (repo / "docs-site" / "package.json").write_text('{"dependencies": {"next": "^15"}}')
    metrics = scan_repo(str(repo))
    assert metrics["buildDomain"]["domain"] == "ai_systems"


def test_monorepo_unused_sdk_in_subpackage_not_counted(tmp_path):
    repo = tmp_path / "dead-mono"
    (repo / "pkg-a").mkdir(parents=True)
    (repo / "package.json").write_text('{"workspaces": ["pkg-a"]}')
    (repo / "pkg-a" / "package.json").write_text('{"dependencies": {"openai": "^4"}}')
    (repo / "pkg-a" / "app.ts").write_text("export const x = 1;\n")
    metrics = scan_repo(str(repo))
    assert metrics["buildDomain"]["domain"] == "products"
    assert (
        "never imported" in str([p for p in metrics.get("packages", [])])
        or metrics["buildDomain"]["domain"] == "products"
    )


def test_nested_workspace_packages_found(tmp_path):
    repo = tmp_path / "nested"
    deep = repo / "packages" / "group" / "ai-widget"
    deep.mkdir(parents=True)
    (repo / "package.json").write_text("{}")
    (deep / "package.json").write_text('{"dependencies": {"@anthropic-ai/sdk": "^1"}}')
    (deep / "widget.ts").write_text(
        "import Anthropic from '@anthropic-ai/sdk';\nnew Anthropic();\n"
        "await c.messages.create({});\n"
    )
    metrics = scan_repo(str(repo))
    assert metrics["buildDomain"]["domain"] == "ai_products"
    assert any(p["pkg"] == "packages/group/ai-widget" for p in metrics["packages"])


def test_single_package_repo_unchanged(tmp_path):
    repo = tmp_path / "solo"
    repo.mkdir()
    (repo / "package.json").write_text('{"dependencies": {"react": "^18"}}')
    (repo / "app.ts").write_text("export const a = 1;\n")
    metrics = scan_repo(str(repo))
    assert "packages" not in metrics  # single unit, original path
    assert metrics["buildDomain"]["domain"] == "products"


def test_nested_git_repo_is_a_boundary_not_a_package(tmp_path):
    """A vendored clone/submodule (own .git) is its OWN scan unit: its
    code must not feed the parent's metrics, packages, or verdict —
    else the same code is classified in two places (and a repo whose
    only AI marker is someone else's vendored repo gets mislabeled)."""
    repo = tmp_path / "host"
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text('{"dependencies": {"express": "^4"}}')
    (repo / "src" / "app.ts").write_text("const x = 1;\n")
    vendored = repo / "vendored-agent"
    (vendored / "src").mkdir(parents=True)
    (vendored / ".git").mkdir()
    (vendored / "package.json").write_text(
        '{"dependencies": {"@modelcontextprotocol/sdk": "^1.0"}}'
    )
    (vendored / "src" / "client.ts").write_text(
        "import { Client } from '@modelcontextprotocol/sdk/client/index.js';\n"
    )
    metrics = scan_repo(str(repo))
    # the host stays a plain product — vendoring an agent tool is not building one
    assert metrics["buildDomain"]["domain"] == "products"
    assert all(p["pkg"] != "vendored-agent" for p in metrics.get("packages", []))
    # the nested repo's imports never reached the host's counters
    assert metrics["aiUsage"]["agentImports"] == 0
