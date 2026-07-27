"""cruise_ai.recommendations.mcp_discovery — detect opportunities for MCP servers.

Provides:
- API Pattern Detection: find swagger/OpenAPI files, REST client usage, curl/fetch calls
- MCP Server Recommendation: suggest creating MCP servers for detected APIs
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# File patterns indicating API usage
API_FILE_PATTERNS = [
    "swagger", "openapi", "api-spec", "api_spec",
    ".swagger.json", ".swagger.yaml", ".swagger.yml",
    "openapi.json", "openapi.yaml", "openapi.yml",
]

# Command patterns indicating REST client usage
API_COMMAND_PATTERNS = [
    "curl", "wget", "httpie", "http ",
    "fetch(", "axios", "requests.get", "requests.post",
    "got(", "node-fetch",
]


def _find_api_patterns_in_scan(scan_results: dict[str, Any]) -> list[str]:
    """Extract API-related patterns from scan_results."""
    detected_apis: list[str] = []

    # Check config_files for swagger/openapi specs
    config_files = scan_results.get("config_files", [])
    for f in config_files:
        f_lower = f.lower() if isinstance(f, str) else ""
        if any(pattern in f_lower for pattern in API_FILE_PATTERNS):
            detected_apis.append(f)

    return detected_apis


def _find_api_patterns_in_sessions(sessions: list[Any]) -> tuple[list[str], int]:
    """Detect API call patterns in session commands."""
    api_endpoints: list[str] = []
    api_call_count = 0

    for s in sessions:
        commands = getattr(s, "commands", None)
        if commands is None:
            if isinstance(s, dict):
                commands = s.get("commands", [])
            else:
                commands = []

        for cmd in commands:
            cmd_str = str(cmd).lower() if cmd else ""
            if any(pattern in cmd_str for pattern in API_COMMAND_PATTERNS):
                api_call_count += 1
                # Try to extract endpoint from curl/fetch patterns
                for part in cmd_str.split():
                    if part.startswith("http://") or part.startswith("https://"):
                        # Normalize to base endpoint
                        endpoint = part.split("?")[0].rstrip("/")
                        if endpoint not in api_endpoints:
                            api_endpoints.append(endpoint)

    return api_endpoints, api_call_count


def generate_mcp_skeleton(api_name: str, endpoints: list[str]) -> dict[str, str]:
    """Generate a minimal FastMCP-style server skeleton for detected APIs.

    Args:
        api_name: Name of the API to create a server for.
        endpoints: List of endpoint paths/names to create handlers for.

    Returns:
        Dict with 'filename', 'content' (Python MCP server template), 'description'.
    """
    try:
        safe_name = api_name.lower().replace(" ", "_").replace("-", "_")
        filename = f"mcp_server_{safe_name}.py"

        handlers = []
        for endpoint in endpoints:
            # Normalize endpoint to a valid function name
            func_name = (
                endpoint.strip("/")
                .replace("/", "_")
                .replace("-", "_")
                .replace("{", "")
                .replace("}", "")
                .replace(".", "_")
                .lower()
            )
            if not func_name:
                func_name = "default_handler"
            handlers.append(
                f'@mcp.tool()\n'
                f'async def {func_name}() -> dict:\n'
                f'    """Handler for {endpoint}."""\n'
                f'    # TODO: implement API call to {endpoint}\n'
                f'    return {{"status": "not_implemented", "endpoint": "{endpoint}"}}\n'
            )

        handler_block = "\n\n".join(handlers) if handlers else (
            '@mcp.tool()\n'
            'async def placeholder() -> dict:\n'
            '    """Placeholder handler."""\n'
            '    return {"status": "not_implemented"}\n'
        )

        content = (
            f'"""MCP server for {api_name}."""\n'
            f'\n'
            f'from mcp.server.fastmcp import FastMCP\n'
            f'\n'
            f'mcp = FastMCP("{safe_name}")\n'
            f'\n'
            f'\n'
            f'{handler_block}\n'
            f'\n'
            f'if __name__ == "__main__":\n'
            f'    mcp.run()\n'
        )

        return {
            "filename": filename,
            "content": content,
            "description": f"FastMCP server for {api_name} with {len(endpoints)} endpoint handler(s)",
        }
    except Exception:
        return {
            "filename": f"mcp_server_{api_name}.py",
            "content": "",
            "description": "Failed to generate MCP skeleton",
        }


def _detect_mcp_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive MCP recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    mcp_server_count = norm.get("mcpServerCount", 0)
    mcp_tool_calls = norm.get("mcpToolCalls", 0)
    terminal_command_count = norm.get("terminalCommandCount", 0)
    stack = scan_results.get("stack", [])

    # mcpServerCount == 0 AND mcpToolCalls > 0 -> already using MCP tools, recommend creating own
    if mcp_server_count == 0 and mcp_tool_calls > 0:
        recs.append(Recommendation(
            category="mcp_discovery",
            headline=f"{mcp_tool_calls} MCP tool calls detected but no servers configured — create your own",
            detail=(
                f"You've made {mcp_tool_calls} MCP tool calls (likely via built-in tools) "
                f"but have no custom MCP servers configured. Creating your own MCP server "
                f"for your specific APIs and workflows would extend AI capabilities further."
            ),
            action_type="create_mcp_server",
            trust_level="heuristic",
            confidence=65,
            evidence=f"{mcp_tool_calls} MCP tool calls, 0 custom servers (normalized)",
            priority="medium",
            teach_text=(
                "MCP servers let AI tools call your APIs directly. "
                "You're already benefiting from built-in MCP tools — creating a custom server "
                "for your project's APIs would give the AI deeper integration."
            ),
            auto_action="Generate MCP server scaffold for your most-used API patterns",
        ))

    # mcpServerCount == 0 AND terminalCommandCount > 1000 -> recommend MCP for CLI automation
    if mcp_server_count == 0 and terminal_command_count > 1000:
        recs.append(Recommendation(
            category="mcp_discovery",
            headline=f"{terminal_command_count} terminal commands — an MCP server could automate CLI workflows",
            detail=(
                f"You've run {terminal_command_count} terminal commands across sessions. "
                f"An MCP server wrapping your common CLI operations would let the AI "
                f"execute structured commands with validation instead of raw shell."
            ),
            action_type="create_mcp_server",
            trust_level="heuristic",
            confidence=60,
            evidence=f"{terminal_command_count} terminal commands, 0 MCP servers (normalized)",
            priority="low",
            teach_text=(
                "Instead of the AI running raw shell commands, an MCP server provides "
                "structured, typed tools with validation. Safer and more predictable."
            ),
            auto_action="Identify repetitive CLI patterns and suggest MCP server tools",
        ))

    # Stack contains API frameworks -> recommend API MCP
    if mcp_server_count == 0 and stack:
        api_frameworks = ["fastapi", "express", "flask", "django", "spring", "rails", "nest", "hapi", "koa"]
        stack_lower = " ".join(str(s).lower() for s in stack)
        detected_frameworks = [fw for fw in api_frameworks if fw in stack_lower]
        if detected_frameworks:
            recs.append(Recommendation(
                category="mcp_discovery",
                headline=f"API framework detected ({', '.join(detected_frameworks[:2])}) — create an MCP server for your endpoints",
                detail=(
                    f"Your tech stack includes {', '.join(detected_frameworks)} but no MCP servers "
                    f"are configured. An MCP server wrapping your API endpoints lets the AI "
                    f"call them directly with typed parameters."
                ),
                action_type="create_mcp_server",
                trust_level="heuristic",
                confidence=63,
                evidence=f"API frameworks: {', '.join(detected_frameworks)} in stack, 0 MCP servers (normalized)",
                priority="medium",
                teach_text=(
                    "MCP servers expose APIs as typed tools to AI assistants. "
                    "Instead of manually running curl and pasting results, the AI calls tools directly."
                ),
                auto_action="Generate MCP server from detected API framework patterns",
            ))

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Detect MCP server creation opportunities from API usage patterns.

    Checks scan_results for API specs and sessions for REST client usage.
    Recommends MCP server creation when APIs are detected but not wrapped.
    """
    recs: list[Recommendation] = []

    try:
        existing_mcps = scan_results.get("mcps", [])
        api_specs = _find_api_patterns_in_scan(scan_results)
        api_endpoints, api_call_count = _find_api_patterns_in_sessions(sessions)

        # Combine evidence
        has_api_specs = len(api_specs) > 0
        has_api_calls = api_call_count > 3
        has_many_endpoints = len(api_endpoints) > 3
        has_mcps = len(existing_mcps) > 0

        # If APIs detected but no MCPs configured
        if (has_api_specs or has_api_calls) and not has_mcps:
            evidence_parts: list[str] = []
            if api_specs:
                evidence_parts.append(f"API specs: {', '.join(api_specs[:3])}")
            if api_call_count > 0:
                evidence_parts.append(f"{api_call_count} API calls in sessions")
            if api_endpoints:
                evidence_parts.append(f"{len(api_endpoints)} unique endpoints")

            recs.append(Recommendation(
                category="mcp_discovery",
                headline="API usage detected but no MCP servers configured — wrap APIs for better AI integration",
                detail=(
                    f"Found API patterns in your project ({'; '.join(evidence_parts)}) "
                    f"but no MCP servers are configured. An MCP server wraps your APIs "
                    f"so the AI can call them directly instead of you writing curl/fetch commands."
                ),
                action_type="create_mcp_server",
                trust_level="heuristic",
                confidence=72 if has_api_specs else 65,
                evidence="; ".join(evidence_parts),
                priority="medium",
                teach_text=(
                    "MCP (Model Context Protocol) servers let AI tools call APIs directly. "
                    "Instead of you writing 'curl https://api.example.com/users', the AI "
                    "can call a typed tool like get_users(). Benefits:\n"
                    "- No more copy-pasting curl output back to the AI\n"
                    "- Type-safe parameters with validation\n"
                    "- AI can chain multiple API calls automatically\n"
                    "- Responses are structured, not raw text"
                ),
                auto_action="Generate an MCP server scaffold from detected API patterns",
                savings_estimate={"api_calls_automated": api_call_count},
            ))

        # If many unique endpoints, recommend MCP server specifically
        if has_many_endpoints and not has_mcps:
            endpoint_list = ", ".join(api_endpoints[:5])
            recs.append(Recommendation(
                category="mcp_discovery",
                headline=f"{len(api_endpoints)} API endpoints detected — an MCP server would centralize access",
                detail=(
                    f"Detected {len(api_endpoints)} unique API endpoints in your sessions: "
                    f"{endpoint_list}{'...' if len(api_endpoints) > 5 else ''}. "
                    f"With this many endpoints, a dedicated MCP server would provide "
                    f"structured, typed access instead of ad-hoc curl commands."
                ),
                action_type="create_mcp_server",
                trust_level="heuristic",
                confidence=75,
                evidence=f"{len(api_endpoints)} unique API endpoints, {api_call_count} total API calls",
                priority="high" if len(api_endpoints) > 6 else "medium",
                teach_text=(
                    "MCP (Model Context Protocol) servers expose APIs as typed tools to AI assistants. "
                    "Instead of manually running curl/fetch and pasting results, the AI calls "
                    "tools directly. This eliminates context-switching, reduces token usage "
                    "(no raw HTTP responses), and enables the AI to chain API calls intelligently."
                ),
                auto_action="Scaffold an MCP server with endpoints for detected APIs",
                savings_estimate={"endpoints_to_wrap": len(api_endpoints)},
            ))

        # If APIs detected and user has acted on create_mcp_server feedback
        feedback_history = scan_results.get("feedback_history", [])
        acted_on_mcp = any(
            fb.get("action_type") == "create_mcp_server" and fb.get("action") == "acted"
            for fb in feedback_history
            if isinstance(fb, dict)
        )
        if acted_on_mcp and (api_endpoints or api_specs):
            endpoints_for_skeleton = api_endpoints[:10] if api_endpoints else ["/api/v1/resource"]
            api_name = api_specs[0].split(".")[0] if api_specs else "detected_api"
            skeleton = generate_mcp_skeleton(api_name, endpoints_for_skeleton)
            recs.append(Recommendation(
                category="mcp_discovery",
                headline="Ready to generate MCP server skeleton from your API patterns",
                detail=(
                    f"You previously expressed interest in creating an MCP server. "
                    f"A skeleton with {len(endpoints_for_skeleton)} endpoint handler(s) "
                    f"is ready to generate at '{skeleton['filename']}'."
                ),
                action_type="generate_mcp_skeleton",
                trust_level="observed",
                confidence=80,
                evidence=f"User acted on create_mcp_server; {len(endpoints_for_skeleton)} endpoints available",
                priority="high",
                teach_text=(
                    "This will generate a Python file with a FastMCP server template. "
                    "Each detected endpoint gets a placeholder handler you can fill in. "
                    "Run the server with 'python mcp_server_*.py' to test locally."
                ),
                auto_action=skeleton.get("filename", ""),
                savings_estimate={"endpoints_scaffolded": len(endpoints_for_skeleton)},
            ))

    except Exception:
        pass

    # Additional detectors for API→MCP and DB MCP
    try:
        recs.extend(_detect_api_to_mcp(sessions, scan_results))
    except Exception:
        pass
    try:
        recs.extend(_detect_db_mcp(sessions, scan_results))
    except Exception:
        pass

    # Normalized-signal detection
    norm = scan_results.get("normalized", {}) if scan_results else {}
    if norm:
        recs.extend(_detect_mcp_from_normalized(norm, scan_results))

    return recs


# ── Database patterns indicating DB usage ──
_DB_COMMAND_PATTERNS = [
    "select ", "insert ", "update ", "delete ", "create table",
    "alter table", "drop table", "psql", "mysql", "sqlite3",
    "pg_dump", "mysqldump", "sequelize", "prisma", "typeorm",
    "knex", "sqlalchemy", "django.db", "activerecord",
]

_DB_FILE_PATTERNS = [
    "database.yml", "database.json", "db.sqlite", ".sqlite3",
    "schema.prisma", "ormconfig", "knexfile", "alembic.ini",
    "migrations/", "db/migrate", "sequelize", "typeorm",
    "database.url", "db_config", "pgpass", ".pgpass",
]

_DB_TYPE_INDICATORS: dict[str, list[str]] = {
    "postgres": ["psql", "pg_dump", "postgresql", "postgres", "pgpass"],
    "mysql": ["mysql", "mysqldump", "mariadb"],
    "sqlite": ["sqlite", "sqlite3", ".sqlite"],
}


def _detect_api_to_mcp(
    sessions: list[Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Detect Swagger/OpenAPI files and recommend converting to MCP server.

    Specifically looks for .yaml/.json files with openapi/swagger keys
    in scan_results or session context.
    """
    recs: list[Recommendation] = []

    # Check scan_results config_files for swagger/openapi specs
    swagger_files: list[str] = []
    config_files = scan_results.get("config_files", [])
    for f in config_files:
        f_lower = str(f).lower() if f else ""
        if any(kw in f_lower for kw in ["swagger", "openapi"]):
            swagger_files.append(str(f))

    # Also check session context_files
    for s in sessions:
        if isinstance(s, dict):
            context_files = s.get("context_files", [])
        else:
            context_files = getattr(s, "context_files", []) or []
        for f in context_files:
            f_lower = str(f).lower() if f else ""
            if any(kw in f_lower for kw in ["swagger", "openapi"]):
                if str(f) not in swagger_files:
                    swagger_files.append(str(f))

    if not swagger_files:
        return recs

    # Check if already has MCP servers
    existing_mcps = scan_results.get("mcps", [])
    if existing_mcps:
        # Check if any MCP already wraps these APIs
        mcp_names = [str(m).lower() for m in existing_mcps if m]
        for sf in swagger_files[:]:
            api_name = sf.lower().replace("swagger", "").replace("openapi", "").replace(".yaml", "").replace(".json", "").replace(".yml", "").strip("_-/.")
            if any(api_name in mn for mn in mcp_names):
                swagger_files.remove(sf)

    if not swagger_files:
        return recs

    # Estimate endpoint count (heuristic: typical APIs have 5-20 endpoints)
    estimated_endpoints = len(swagger_files) * 10

    recs.append(Recommendation(
        category="mcp_discovery",
        headline=f"OpenAPI/Swagger spec{'s' if len(swagger_files) > 1 else ''} found — convert to MCP server for direct AI access",
        detail=(
            f"Found {len(swagger_files)} API spec file(s): {', '.join(swagger_files[:3])}. "
            f"These define ~{estimated_endpoints} endpoints that could be exposed as MCP tools. "
            f"Converting to an MCP server lets AI call these APIs directly with typed parameters."
        ),
        action_type="convert_api_to_mcp",
        trust_level="heuristic",
        confidence=70,
        evidence=f"Swagger/OpenAPI specs: {', '.join(swagger_files[:3])}",
        priority="medium",
        teach_text=(
            "OpenAPI/Swagger specs already define your API structure. An MCP server "
            "generated from them gives AI tools typed access to every endpoint — "
            "no more manually writing curl commands and pasting responses back. "
            "The AI gets parameter validation, proper error handling, and can chain calls."
        ),
        auto_action=f"Generate MCP server from {swagger_files[0]}",
        savings_estimate={"spec_files": len(swagger_files), "estimated_endpoints": estimated_endpoints},
    ))

    return recs


def _detect_db_mcp(
    sessions: list[Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Detect database patterns and recommend DB MCP server.

    Looks for SQL queries in commands, ORM usage, and database config files.
    """
    recs: list[Recommendation] = []

    db_signals = 0
    detected_db_type = "unknown"
    evidence_parts: list[str] = []

    # Check commands for SQL/DB patterns
    sql_count = 0
    for s in sessions:
        if isinstance(s, dict):
            commands = s.get("commands", [])
        else:
            commands = getattr(s, "commands", []) or []
        for cmd in commands:
            cmd_lower = str(cmd).lower() if cmd else ""
            if any(p in cmd_lower for p in _DB_COMMAND_PATTERNS):
                sql_count += 1
                # Detect specific DB type
                for db_type, indicators in _DB_TYPE_INDICATORS.items():
                    if any(ind in cmd_lower for ind in indicators):
                        detected_db_type = db_type

    if sql_count > 0:
        db_signals += 1
        evidence_parts.append(f"{sql_count} DB-related commands in sessions")

    # Check config_files for DB config
    config_files = scan_results.get("config_files", [])
    db_configs: list[str] = []
    for f in config_files:
        f_lower = str(f).lower() if f else ""
        if any(p in f_lower for p in _DB_FILE_PATTERNS):
            db_configs.append(str(f))
            # Detect type from config file name
            for db_type, indicators in _DB_TYPE_INDICATORS.items():
                if any(ind in f_lower for ind in indicators):
                    detected_db_type = db_type

    if db_configs:
        db_signals += 1
        evidence_parts.append(f"DB config files: {', '.join(db_configs[:3])}")

    # Check stack for ORM/DB frameworks
    stack = scan_results.get("stack", [])
    db_frameworks = [s for s in stack if isinstance(s, str) and any(
        p in s.lower() for p in ["prisma", "sequelize", "typeorm", "sqlalchemy", "django", "activerecord"]
    )]
    if db_frameworks:
        db_signals += 1
        evidence_parts.append(f"DB frameworks: {', '.join(db_frameworks[:3])}")

    if db_signals < 1 or sql_count < 2:
        return recs

    # Check if a DB MCP already exists
    existing_mcps = scan_results.get("mcps", [])
    mcp_names = [str(m).lower() for m in existing_mcps if m]
    if any(kw in " ".join(mcp_names) for kw in ["db", "database", "sql", "postgres", "mysql", "sqlite"]):
        return recs

    recs.append(Recommendation(
        category="mcp_discovery",
        headline=f"Database access detected without MCP — a DB MCP would let AI query directly",
        detail=(
            f"Detected database usage ({'; '.join(evidence_parts)}). "
            f"DB type: {detected_db_type}. "
            f"A database MCP server would let AI tools run queries, inspect schema, "
            f"and manage migrations without you copy-pasting SQL results."
        ),
        action_type="create_db_mcp",
        trust_level="heuristic",
        confidence=65,
        evidence="; ".join(evidence_parts),
        priority="medium",
        teach_text=(
            "A database MCP server gives AI tools direct, safe access to your database. "
            "Instead of you running queries and pasting results back, the AI can: "
            "inspect schema, run read queries, suggest migrations, and validate data. "
            "Most DB MCPs include safety rails (read-only mode, query timeouts, row limits)."
        ),
        auto_action=f"Generate {detected_db_type} MCP server template",
        savings_estimate={"db_type": detected_db_type, "sql_commands_detected": sql_count},
    ))

    return recs


def generate_api_mcp(api_spec_path: str, endpoints: list[str]) -> dict[str, str]:
    """Generate MCP server from an API spec (Swagger/OpenAPI).

    Args:
        api_spec_path: Path to the API spec file.
        endpoints: List of endpoint paths to create handlers for.

    Returns:
        Dict with 'filename', 'content', 'description'.
    """
    try:
        import os
        api_name = os.path.splitext(os.path.basename(api_spec_path))[0]
        safe_name = api_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
        filename = f"mcp_server_{safe_name}.py"

        handlers = []
        for endpoint in endpoints:
            func_name = (
                endpoint.strip("/")
                .replace("/", "_")
                .replace("-", "_")
                .replace("{", "")
                .replace("}", "")
                .replace(".", "_")
                .lower()
            )
            if not func_name:
                func_name = "default_handler"
            handlers.append(
                f'@mcp.tool()\n'
                f'async def {func_name}() -> dict:\n'
                f'    """Handler for {endpoint} (from {api_spec_path})."""\n'
                f'    # TODO: implement call to {endpoint}\n'
                f'    return {{"status": "not_implemented", "endpoint": "{endpoint}"}}\n'
            )

        handler_block = "\n\n".join(handlers) if handlers else (
            '@mcp.tool()\n'
            'async def placeholder() -> dict:\n'
            '    """Placeholder handler."""\n'
            '    return {"status": "not_implemented"}\n'
        )

        content = (
            f'"""MCP server generated from {api_spec_path}."""\n'
            f'\n'
            f'from mcp.server.fastmcp import FastMCP\n'
            f'\n'
            f'mcp = FastMCP("{safe_name}")\n'
            f'\n'
            f'\n'
            f'{handler_block}\n'
            f'\n'
            f'if __name__ == "__main__":\n'
            f'    mcp.run()\n'
        )

        return {
            "filename": filename,
            "content": content,
            "description": f"MCP server from {api_spec_path} with {len(endpoints)} endpoints",
        }
    except Exception:
        return {
            "filename": "mcp_server_api.py",
            "content": "",
            "description": "Failed to generate API MCP server",
        }


def generate_db_mcp(db_type: str) -> dict[str, str]:
    """Generate MCP server template for database access.

    Args:
        db_type: One of 'postgres', 'mysql', 'sqlite'.

    Returns:
        Dict with 'filename', 'content', 'description'.
    """
    try:
        safe_type = db_type.lower().replace(" ", "_")
        filename = f"mcp_server_{safe_type}_db.py"

        # Connection setup varies by DB type
        conn_templates = {
            "postgres": (
                'import os\n'
                '\n'
                'DB_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/mydb")\n'
            ),
            "mysql": (
                'import os\n'
                '\n'
                'DB_URL = os.environ.get("DATABASE_URL", "mysql://localhost:3306/mydb")\n'
            ),
            "sqlite": (
                'import os\n'
                '\n'
                'DB_PATH = os.environ.get("DB_PATH", "database.sqlite3")\n'
            ),
        }

        conn_setup = conn_templates.get(safe_type, conn_templates["sqlite"])

        content = (
            f'"""MCP server for {db_type} database access."""\n'
            f'\n'
            f'from mcp.server.fastmcp import FastMCP\n'
            f'{conn_setup}\n'
            f'mcp = FastMCP("{safe_type}_db")\n'
            f'\n'
            f'\n'
            f'@mcp.tool()\n'
            f'async def query(sql: str, params: list | None = None) -> dict:\n'
            f'    """Execute a read-only SQL query.\n'
            f'\n'
            f'    Args:\n'
            f'        sql: SQL query to execute (SELECT only).\n'
            f'        params: Optional query parameters.\n'
            f'    """\n'
            f'    # TODO: implement {db_type} connection and query execution\n'
            f'    # SAFETY: validate sql starts with SELECT\n'
            f'    if not sql.strip().upper().startswith("SELECT"):\n'
            f'        return {{"error": "Only SELECT queries allowed in read-only mode"}}\n'
            f'    return {{"status": "not_implemented", "sql": sql}}\n'
            f'\n'
            f'\n'
            f'@mcp.tool()\n'
            f'async def list_tables() -> dict:\n'
            f'    """List all tables in the database."""\n'
            f'    # TODO: implement table listing for {db_type}\n'
            f'    return {{"status": "not_implemented"}}\n'
            f'\n'
            f'\n'
            f'@mcp.tool()\n'
            f'async def describe_table(table_name: str) -> dict:\n'
            f'    """Describe columns and types for a table.\n'
            f'\n'
            f'    Args:\n'
            f'        table_name: Name of the table to describe.\n'
            f'    """\n'
            f'    # TODO: implement schema description for {db_type}\n'
            f'    return {{"status": "not_implemented", "table": table_name}}\n'
            f'\n'
            f'\n'
            f'if __name__ == "__main__":\n'
            f'    mcp.run()\n'
        )

        return {
            "filename": filename,
            "content": content,
            "description": f"MCP server template for {db_type} with query, list_tables, describe_table tools",
        }
    except Exception:
        return {
            "filename": f"mcp_server_{db_type}_db.py",
            "content": "",
            "description": f"Failed to generate {db_type} DB MCP template",
        }
