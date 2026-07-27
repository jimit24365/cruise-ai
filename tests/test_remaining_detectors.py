"""Tests for remaining detector/feature implementations.

Covers:
- Prompt simplification
- Token waste score recommendation emission
- Skill marketplace
- API-to-MCP detection
- DB MCP detection
- Monthly report generation
- Team guidelines detection and generation
- GEMINI.md generation
- Engine integration with all new detectors
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cruise_ai.recommendations.types import Recommendation, CONFIDENCE_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _make_session(**kwargs):
    """Create a minimal session dict for testing."""
    defaults = {
        "tool_name": "kiro",
        "tokens_used": 1000,
        "duration": 60,
        "model": "claude-sonnet",
        "prompts": [],
        "context_files": [],
        "commands": [],
        "timestamp": datetime.now().isoformat(),
    }
    defaults.update(kwargs)
    return defaults


def _make_verbose_session():
    """Create a session with verbose/polite prompts."""
    return _make_session(prompts=[
        "Could you please help me refactor the auth module?",
        "I would like you to write a test for the login function.",
        "Would you mind explaining how this code works?",
        "Please kindly update the documentation for the API.",
        "If you don't mind, could you review this code?",
    ])


def _make_concise_session():
    """Create a session with concise prompts."""
    return _make_session(prompts=[
        "Refactor the auth module.",
        "Write a test for login.",
        "Explain this code.",
        "Update the API docs.",
        "Review this code.",
    ])


# ═══════════════════════════════════════════════════════════════════════
# 1. Prompt Simplification Tests
# ═══════════════════════════════════════════════════════════════════════

class TestPromptSimplification:
    """Tests for _detect_prompt_simplification."""

    def test_detects_verbose_prompts(self):
        """Should flag sessions with >20% filler rate."""
        from cruise_ai.recommendations.token_optimization import _detect_prompt_simplification

        sessions = [_make_verbose_session() for _ in range(5)]
        recs = _detect_prompt_simplification(sessions)

        assert len(recs) >= 1
        rec = recs[0]
        assert rec.action_type == "simplify_prompts"
        assert rec.trust_level == "heuristic"
        assert rec.confidence == 65
        assert "filler" in rec.detail.lower() or "polite" in rec.detail.lower()

    def test_no_flag_for_concise_prompts(self):
        """Should not flag concise sessions."""
        from cruise_ai.recommendations.token_optimization import _detect_prompt_simplification

        sessions = [_make_concise_session() for _ in range(5)]
        recs = _detect_prompt_simplification(sessions)

        assert len(recs) == 0

    def test_threshold_at_20_percent(self):
        """Should only trigger above 20% filler rate."""
        from cruise_ai.recommendations.token_optimization import _detect_prompt_simplification

        # 1 verbose + 5 concise = ~16% filler (below threshold)
        sessions = [_make_verbose_session()] + [_make_concise_session() for _ in range(5)]
        recs = _detect_prompt_simplification(sessions)
        # Total prompts: 30, filler: 5 → 16.7% → should NOT trigger
        assert len(recs) == 0

    def test_empty_sessions_no_crash(self):
        """Should handle empty sessions gracefully."""
        from cruise_ai.recommendations.token_optimization import _detect_prompt_simplification

        assert _detect_prompt_simplification([]) == []
        assert _detect_prompt_simplification([_make_session()]) == []

    def test_teach_text_present(self):
        """Should include meaningful teach_text."""
        from cruise_ai.recommendations.token_optimization import _detect_prompt_simplification

        sessions = [_make_verbose_session() for _ in range(5)]
        recs = _detect_prompt_simplification(sessions)
        assert recs[0].teach_text
        assert "concise" in recs[0].teach_text.lower() or "direct" in recs[0].teach_text.lower()


# ═══════════════════════════════════════════════════════════════════════
# 2. Token Waste Score Tests
# ═══════════════════════════════════════════════════════════════════════

class TestTokenWasteScore:
    """Tests for token waste score recommendation emission."""

    def test_emits_recommendation_above_40(self):
        """Should emit reduce_token_waste when score > 40."""
        from cruise_ai.recommendations.token_optimization import _compute_token_waste_score

        # Create sessions with high waste (many duplicate files + oversized prompts)
        sessions = []
        for _ in range(10):
            s = _make_session()
            # Simulate session object with attrs for the function
            class FakeSession:
                context_files = ["same_file.py"] * 5
                prompt_word_counts = [600, 700, 800]  # all oversized
                models = ["claude-opus-4"]  # expensive model
            sessions.append(FakeSession())

        profile = {}
        recs = _compute_token_waste_score(sessions, profile)

        waste_recs = [r for r in recs if r.action_type == "reduce_token_waste"]
        assert len(waste_recs) >= 1
        assert waste_recs[0].confidence >= CONFIDENCE_THRESHOLD

    def test_no_emission_below_40(self):
        """Should NOT emit when waste score <= 40."""
        from cruise_ai.recommendations.token_optimization import _compute_token_waste_score

        # Create low-waste sessions
        sessions = []
        for _ in range(10):
            class LowWasteSession:
                context_files = [f"file_{i}.py" for i in range(3)]
                prompt_word_counts = [50, 60, 70]  # short prompts
                models = ["claude-haiku"]  # cheap model
            sessions.append(LowWasteSession())

        profile = {}
        recs = _compute_token_waste_score(sessions, profile)
        waste_recs = [r for r in recs if r.action_type == "reduce_token_waste"]
        assert len(waste_recs) == 0

    def test_waste_score_in_detail(self):
        """Should show the score in detail field."""
        from cruise_ai.recommendations.token_optimization import _compute_token_waste_score

        sessions = []
        for _ in range(10):
            class HighWaste:
                context_files = ["same.py"] * 10
                prompt_word_counts = [600, 700, 800, 900]
                models = ["claude-opus-4"] * 3
            sessions.append(HighWaste())

        recs = _compute_token_waste_score(sessions, {})
        waste_recs = [r for r in recs if r.action_type == "reduce_token_waste"]
        if waste_recs:
            assert "waste score" in waste_recs[0].detail.lower() or "/100" in waste_recs[0].detail


# ═══════════════════════════════════════════════════════════════════════
# 3. Skill Marketplace Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSkillMarketplace:
    """Tests for _detect_skill_marketplace."""

    def test_detects_testing_patterns(self):
        """Should recommend testing skill when test commands detected."""
        from cruise_ai.recommendations.skills import _detect_skill_marketplace

        sessions = [
            _make_session(commands=["pytest -q", "pytest --cov", "jest --watchAll"]),
            _make_session(commands=["pytest tests/", "coverage report"]),
            _make_session(commands=["npm test", "vitest run"]),
        ]
        profile = {}
        scan_results = {"skills": []}

        recs = _detect_skill_marketplace(sessions, profile, scan_results)
        assert any(r.action_type == "install_community_skill" for r in recs)
        testing_recs = [r for r in recs if "testing" in r.detail.lower() or "test" in r.headline.lower()]
        assert len(testing_recs) >= 1

    def test_detects_deployment_patterns(self):
        """Should recommend deployment skill when deploy commands detected."""
        from cruise_ai.recommendations.skills import _detect_skill_marketplace

        sessions = [
            _make_session(commands=["docker build -t app .", "docker push app"]),
            _make_session(commands=["terraform plan", "kubectl apply -f deploy.yaml"]),
            _make_session(commands=["helm upgrade my-app"]),
        ]
        recs = _detect_skill_marketplace(sessions, {}, {"skills": []})

        deploy_recs = [r for r in recs if "deploy" in r.detail.lower()]
        assert len(deploy_recs) >= 1
        assert deploy_recs[0].confidence == 63
        assert deploy_recs[0].trust_level == "heuristic"

    def test_no_recommend_existing_skill(self):
        """Should not recommend skills already installed."""
        from cruise_ai.recommendations.skills import _detect_skill_marketplace

        sessions = [
            _make_session(commands=["pytest -q", "pytest --cov"]),
            _make_session(commands=["pytest tests/"]),
            _make_session(commands=["jest --run"]),
        ]
        # Already have the testing skill
        scan_results = {"skills": ["tdd-workflow"]}

        recs = _detect_skill_marketplace(sessions, {}, scan_results)
        testing_recs = [r for r in recs if "tdd-workflow" in r.detail.lower()]
        assert len(testing_recs) == 0

    def test_empty_sessions(self):
        """Should handle empty/few sessions gracefully."""
        from cruise_ai.recommendations.skills import _detect_skill_marketplace

        assert _detect_skill_marketplace([], {}, {}) == []
        assert _detect_skill_marketplace([_make_session()], {}, {}) == []


# ═══════════════════════════════════════════════════════════════════════
# 4. API-to-MCP Detection Tests
# ═══════════════════════════════════════════════════════════════════════

class TestApiToMcp:
    """Tests for _detect_api_to_mcp and generate_api_mcp."""

    def test_detects_swagger_in_config_files(self):
        """Should detect swagger files in scan_results."""
        from cruise_ai.recommendations.mcp_discovery import _detect_api_to_mcp

        scan_results = {
            "config_files": ["swagger.yaml", "package.json", "tsconfig.json"],
            "mcps": [],
        }
        recs = _detect_api_to_mcp([], scan_results)

        assert len(recs) >= 1
        assert recs[0].action_type == "convert_api_to_mcp"
        assert recs[0].confidence == 70
        assert "swagger" in recs[0].evidence.lower()

    def test_detects_openapi_in_context_files(self):
        """Should detect openapi specs in session context."""
        from cruise_ai.recommendations.mcp_discovery import _detect_api_to_mcp

        sessions = [_make_session(context_files=["docs/openapi.json", "src/main.py"])]
        scan_results = {"config_files": [], "mcps": []}

        recs = _detect_api_to_mcp(sessions, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "convert_api_to_mcp"

    def test_no_detect_if_mcp_exists(self):
        """Should skip if MCP already covers the API."""
        from cruise_ai.recommendations.mcp_discovery import _detect_api_to_mcp

        scan_results = {
            "config_files": ["swagger.yaml"],
            "mcps": ["swagger_api_mcp"],
        }
        recs = _detect_api_to_mcp([], scan_results)
        assert len(recs) == 0

    def test_generate_api_mcp_produces_content(self):
        """Should generate a valid MCP server template."""
        from cruise_ai.recommendations.mcp_discovery import generate_api_mcp

        result = generate_api_mcp("api/openapi.yaml", ["/users", "/users/{id}", "/posts"])
        assert result["filename"] == "mcp_server_openapi.py"
        assert "FastMCP" in result["content"]
        assert "users" in result["content"]
        assert "posts" in result["content"]
        assert "3 endpoints" in result["description"]

    def test_generate_api_mcp_empty_endpoints(self):
        """Should handle empty endpoint list."""
        from cruise_ai.recommendations.mcp_discovery import generate_api_mcp

        result = generate_api_mcp("my-api.yaml", [])
        assert result["filename"]
        assert "placeholder" in result["content"]


# ═══════════════════════════════════════════════════════════════════════
# 5. DB MCP Detection Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDbMcp:
    """Tests for _detect_db_mcp and generate_db_mcp."""

    def test_detects_sql_in_commands(self):
        """Should detect SQL patterns in session commands."""
        from cruise_ai.recommendations.mcp_discovery import _detect_db_mcp

        sessions = [
            _make_session(commands=["psql -c 'SELECT * FROM users'", "pg_dump mydb"]),
            _make_session(commands=["psql mydb", "SELECT count(*) FROM orders"]),
        ]
        scan_results = {"config_files": [], "mcps": [], "stack": []}

        recs = _detect_db_mcp(sessions, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "create_db_mcp"
        assert recs[0].confidence == 65
        assert "postgres" in recs[0].detail.lower()

    def test_detects_db_config_files(self):
        """Should detect database config files."""
        from cruise_ai.recommendations.mcp_discovery import _detect_db_mcp

        sessions = [
            _make_session(commands=["select * from users", "insert into logs values (1)"]),
        ]
        scan_results = {
            "config_files": ["database.yml", "config/db.sqlite"],
            "mcps": [],
            "stack": [],
        }

        recs = _detect_db_mcp(sessions, scan_results)
        assert len(recs) >= 1

    def test_no_detect_if_db_mcp_exists(self):
        """Should skip if DB MCP already configured."""
        from cruise_ai.recommendations.mcp_discovery import _detect_db_mcp

        sessions = [
            _make_session(commands=["psql -c 'select 1'", "psql mydb"]),
        ]
        scan_results = {"config_files": [], "mcps": ["postgres_db_mcp"], "stack": []}

        recs = _detect_db_mcp(sessions, scan_results)
        assert len(recs) == 0

    def test_generate_db_mcp_postgres(self):
        """Should generate postgres MCP template."""
        from cruise_ai.recommendations.mcp_discovery import generate_db_mcp

        result = generate_db_mcp("postgres")
        assert result["filename"] == "mcp_server_postgres_db.py"
        assert "FastMCP" in result["content"]
        assert "postgresql" in result["content"]
        assert "SELECT" in result["content"]

    def test_generate_db_mcp_sqlite(self):
        """Should generate sqlite MCP template."""
        from cruise_ai.recommendations.mcp_discovery import generate_db_mcp

        result = generate_db_mcp("sqlite")
        assert result["filename"] == "mcp_server_sqlite_db.py"
        assert "sqlite" in result["content"].lower()


# ═══════════════════════════════════════════════════════════════════════
# 6. Monthly Report Tests
# ═══════════════════════════════════════════════════════════════════════

class TestMonthlyReport:
    """Tests for reports module."""

    def test_generate_monthly_report_structure(self):
        """Should return dict with required keys."""
        from cruise_ai.recommendations.reports import generate_monthly_report

        sessions = [_make_session(tokens_used=5000) for _ in range(10)]
        profile = {}

        result = generate_monthly_report(sessions, profile)
        assert "period" in result
        assert "total_sessions" in result
        assert "total_tokens" in result
        assert "cost_estimate" in result
        assert "top_recommendations" in result
        assert "trends" in result
        assert "health_score_change" in result

    def test_generates_report_with_longitudinal(self):
        """Should include trends from longitudinal data."""
        from cruise_ai.recommendations.reports import generate_monthly_report

        sessions = [_make_session(tokens_used=10000) for _ in range(20)]
        longitudinal = {
            "prev_month_tokens": 50000,
            "prev_month_sessions": 10,
            "current_health_score": 75,
            "prev_health_score": 60,
        }

        result = generate_monthly_report(sessions, {}, longitudinal)
        assert result["health_score_change"] == 15
        assert len(result["trends"]) > 0

    def test_detect_recommends_report_after_30_days(self):
        """Should recommend monthly report when >30 days of data."""
        from cruise_ai.recommendations.reports import detect

        sessions = []
        now = datetime.now()
        for i in range(35):
            ts = (now - timedelta(days=i)).isoformat()
            sessions.append(_make_session(timestamp=ts))

        recs = detect(sessions, {}, {})
        report_recs = [r for r in recs if r.action_type == "view_monthly_report"]
        assert len(report_recs) >= 1
        assert report_recs[0].confidence == 80
        assert report_recs[0].trust_level == "validated"

    def test_detect_no_report_insufficient_data(self):
        """Should not recommend report with <30 days."""
        from cruise_ai.recommendations.reports import detect

        now = datetime.now()
        sessions = [
            _make_session(timestamp=(now - timedelta(days=i)).isoformat())
            for i in range(10)
        ]

        recs = detect(sessions, {}, {})
        report_recs = [r for r in recs if r.action_type == "view_monthly_report"]
        assert len(report_recs) == 0


# ═══════════════════════════════════════════════════════════════════════
# 7. Team Guidelines Tests
# ═══════════════════════════════════════════════════════════════════════

class TestTeamGuidelines:
    """Tests for team_guidelines module."""

    def test_detects_consistent_patterns(self):
        """Should recommend guidelines when linter + test framework detected."""
        from cruise_ai.recommendations.team_guidelines import detect

        sessions = [
            _make_session(commands=["eslint src/", "jest --coverage"]),
            _make_session(commands=["eslint .", "jest tests/"]),
            _make_session(commands=["prettier --write .", "jest"]),
            _make_session(commands=["eslint src/", "jest"]),
            _make_session(commands=["eslint .", "jest --watch"]),
        ]
        scan_results = {"config_files": [".eslintrc.json", "jest.config.js"], "stack": []}

        recs = detect(sessions, {}, scan_results)
        guideline_recs = [r for r in recs if r.action_type == "generate_team_guidelines"]
        assert len(guideline_recs) >= 1
        assert guideline_recs[0].confidence == 65

    def test_no_recommend_if_contributing_exists(self):
        """Should not recommend if CONTRIBUTING.md already exists."""
        from cruise_ai.recommendations.team_guidelines import detect

        sessions = [
            _make_session(commands=["eslint src/", "jest"]),
        ] * 5
        scan_results = {
            "config_files": [".eslintrc.json", "CONTRIBUTING.md"],
            "stack": [],
        }

        recs = detect(sessions, {}, scan_results)
        guideline_recs = [r for r in recs if r.action_type == "generate_team_guidelines"]
        assert len(guideline_recs) == 0

    def test_generate_team_guidelines_content(self):
        """Should generate meaningful markdown guidelines."""
        from cruise_ai.recommendations.team_guidelines import generate_team_guidelines

        patterns = {
            "linters": ["eslint", "prettier"],
            "test_frameworks": ["jest"],
            "commit_styles": ["conventional"],
            "other": [],
        }

        result = generate_team_guidelines(patterns)
        assert result["filename"] == "TEAM-GUIDELINES.md"
        assert "eslint" in result["content"]
        assert "jest" in result["content"]
        assert "conventional" in result["content"]
        assert "## Linting" in result["content"]
        assert "## Testing" in result["content"]

    def test_empty_patterns_still_generates(self):
        """Should generate base guidelines even with empty patterns."""
        from cruise_ai.recommendations.team_guidelines import generate_team_guidelines

        result = generate_team_guidelines({"linters": [], "test_frameworks": [], "commit_styles": [], "other": []})
        assert result["filename"] == "TEAM-GUIDELINES.md"
        assert "## General Rules" in result["content"]


# ═══════════════════════════════════════════════════════════════════════
# 8. GEMINI.md Generation Tests
# ═══════════════════════════════════════════════════════════════════════

class TestGeminiMd:
    """Tests for GEMINI.md generation and detection."""

    def test_detects_gemini_model_usage(self):
        """Should recommend GEMINI.md when Gemini models detected."""
        from cruise_ai.recommendations.architecture_memory import _detect_gemini_md_need

        sessions = [_make_session(model="gemini-pro-1.5")]
        scan_results = {"config_files": [], "models": ["gemini-pro"], "tools_detected": []}

        recs = _detect_gemini_md_need(sessions, scan_results)
        assert len(recs) >= 1
        assert recs[0].action_type == "generate_gemini_md"
        assert recs[0].confidence == 68

    def test_no_detect_if_gemini_md_exists(self):
        """Should skip if GEMINI.md already exists."""
        from cruise_ai.recommendations.architecture_memory import _detect_gemini_md_need

        sessions = [_make_session(model="gemini-flash")]
        scan_results = {
            "config_files": ["GEMINI.md"],
            "models": ["gemini-flash"],
            "tools_detected": [],
        }

        recs = _detect_gemini_md_need(sessions, scan_results)
        assert len(recs) == 0

    def test_generate_gemini_md_content(self):
        """Should generate meaningful GEMINI.md content."""
        from cruise_ai.recommendations.architecture_memory import generate_gemini_md

        scan_results = {
            "summary": "A Python CLI for AI usage analytics",
            "stack": ["Python", "pytest", "Click"],
            "projects": [{"name": "cruise-ai", "path": "/app"}],
            "tools_detected": ["kiro", "claude-code"],
        }

        result = generate_gemini_md(scan_results)
        assert result["filename"] == "GEMINI.md"
        assert "Python" in result["content"]
        assert "cruise-ai" in result["content"]
        assert "Conventions" in result["content"]

    def test_generate_gemini_md_empty_scan(self):
        """Should handle empty scan results gracefully."""
        from cruise_ai.recommendations.architecture_memory import generate_gemini_md

        result = generate_gemini_md({})
        assert result["filename"] == "GEMINI.md"
        assert len(result["content"]) > 0


# ═══════════════════════════════════════════════════════════════════════
# 9. Engine Integration Tests
# ═══════════════════════════════════════════════════════════════════════

class TestEngineIntegration:
    """Tests for engine.py integration with all new detectors."""

    def test_engine_imports_all_modules(self):
        """Should successfully import all detector modules."""
        from cruise_ai.recommendations import engine
        assert hasattr(engine, '_reports')
        assert hasattr(engine, '_team_guidelines')

    def test_engine_runs_without_crash(self):
        """Should run recommend() without crashing even with empty input."""
        from cruise_ai.recommendations.engine import recommend

        recs = recommend([], {}, {})
        assert isinstance(recs, list)

    def test_engine_includes_new_detectors(self):
        """Should include results from new detectors when conditions met."""
        from cruise_ai.recommendations.engine import recommend

        # Create sessions that trigger multiple new detectors
        now = datetime.now()
        sessions = []
        for i in range(35):
            sessions.append(_make_session(
                timestamp=(now - timedelta(days=i)).isoformat(),
                commands=["eslint src/", "pytest -q", "psql -c 'select 1'", "psql mydb"],
                prompts=[
                    "Could you please help me with this?",
                    "I would like you to refactor the code.",
                ],
                context_files=["openapi.yaml"],
            ))

        scan_results = {
            "config_files": ["swagger.yaml", ".eslintrc.json"],
            "mcps": [],
            "stack": ["pytest"],
            "models": [],
            "tools_detected": [],
            "skills": [],
        }

        recs = recommend(sessions, {}, scan_results)
        action_types = {r.action_type for r in recs}

        # Should have at least some of our new detectors firing
        assert len(recs) > 0
        # All recs should pass confidence threshold
        assert all(r.confidence >= CONFIDENCE_THRESHOLD for r in recs)

    def test_engine_confidence_gate(self):
        """Should filter out recs below confidence threshold."""
        from cruise_ai.recommendations.engine import recommend

        recs = recommend([_make_session()], {}, {})
        for r in recs:
            assert r.confidence >= CONFIDENCE_THRESHOLD

    def test_engine_sort_order(self):
        """Should sort by priority then confidence descending."""
        from cruise_ai.recommendations.engine import recommend

        now = datetime.now()
        sessions = [
            _make_session(
                timestamp=(now - timedelta(days=i)).isoformat(),
                commands=["pytest", "eslint", "docker build"],
                prompts=["please help me"] * 5,
            )
            for i in range(40)
        ]

        recs = recommend(sessions, {}, {"config_files": [], "mcps": [], "stack": [], "models": [], "tools_detected": [], "skills": []})
        if len(recs) >= 2:
            priority_order = {"high": 0, "medium": 1, "low": 2}
            for i in range(len(recs) - 1):
                p1 = priority_order.get(recs[i].priority, 1)
                p2 = priority_order.get(recs[i + 1].priority, 1)
                if p1 == p2:
                    assert recs[i].confidence >= recs[i + 1].confidence
                else:
                    assert p1 <= p2
