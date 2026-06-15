"""Tests for the nextmillionai scanner module.

Fixture-based tests using a tiny sample Claude Code JSONL and a small SQLite
database in tests/fixtures/. Asserts sessions, project paths (from cwd),
prompt word counts, and tool-call categories parse correctly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import nextmillionai.scanner as scanner_mod
from nextmillionai.scanner import (
    _FILE_TOOL_NAMES,
    _TERMINAL_TOOL_NAMES,
    build_summary,
    compute_normalized,
    days_between,
    detect_tech_stack,
    iso_now,
    scan_claude_code,
    scan_cursor_ai_code,
    scan_cursor_conversations,
    scan_cursor_plans,
    scan_cursor_scored_commits,
    ts_to_iso,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def claude_projects(tmp_path, monkeypatch):
    """Set up a fake ~/.claude/projects/ with fixture JSONL files.

    Returns the tmp_path so tests can inspect the layout.
    """
    projects_dir = tmp_path / ".claude" / "projects"
    proj_dir = projects_dir / "-Users-dev-my-project"
    proj_dir.mkdir(parents=True)

    # Copy fixture JSONL files into the fake project dir
    shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "session_abc.jsonl")
    shutil.copy(FIXTURES / "second_session.jsonl", proj_dir / "session_def.jsonl")

    # Monkey-patch the scanner's CLAUDE_PROJECTS_DIR constant
    import nextmillionai.scanner as scanner_mod

    monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", projects_dir)

    return tmp_path


@pytest.fixture()
def cursor_db(tmp_path, monkeypatch):
    """Copy the fixture SQLite database to a temp path and patch CURSOR_DB_PATH."""
    src = FIXTURES / "cursor_tracking.db"
    dst = tmp_path / "ai-code-tracking.db"
    shutil.copy(src, dst)
    monkeypatch.setattr(scanner_mod, "CURSOR_DB_PATH", dst)
    return dst


# ── Tool name constants ──────────────────────────────────────────────────────


class TestToolConstants:
    def test_file_tools(self):
        assert _FILE_TOOL_NAMES == frozenset(
            {
                "Edit",
                "Write",
                "Read",
                "Grep",
                "Glob",
                "NotebookEdit",
            }
        )

    def test_terminal_tools(self):
        assert _TERMINAL_TOOL_NAMES == frozenset({"Bash"})


# ── Claude Code scanner ─────────────────────────────────────────────────────


class TestScanClaudeCode:
    def test_returns_dict(self, claude_projects):
        result = scan_claude_code()
        assert result is not None
        assert isinstance(result, dict)

    def test_session_count(self, claude_projects):
        result = scan_claude_code()
        # Two JSONL files -> two sessions
        assert result["total_sessions"] == 2

    def test_session_ids(self, claude_projects):
        result = scan_claude_code()
        ids = {s["sessionId"] for s in result["sessions"]}
        assert ids == {"session_abc", "session_def"}

    def test_message_count(self, claude_projects):
        """sample_session.jsonl has 6 messages (3 user + 3 assistant),
        second_session.jsonl has 4 messages (2 user + 2 assistant)."""
        result = scan_claude_code()
        assert result["total_messages"] == 10

    def test_project_path_from_cwd(self, claude_projects):
        """Sessions should use the real cwd from the JSONL, not the dir name."""
        result = scan_claude_code()
        projects = {s["project"] for s in result["sessions"]}
        assert "/Users/dev/my-project" in projects

    def test_user_word_count(self, claude_projects):
        """sample_session.jsonl user messages:
          1. "Fix the login bug in auth.py" -> 6 words
          2. [{"type":"text","text":"Now add unit tests for the auth module please"}] -> 9 words
          3. "Looks good, ship it" -> 4 words
        Total: 19 words for session_abc.
        """
        result = scan_claude_code()
        abc = next(s for s in result["sessions"] if s["sessionId"] == "session_abc")
        assert abc["userWordCount"] == 19

    def test_user_word_count_second_session(self, claude_projects):
        """second_session.jsonl user messages:
          1. "Refactor the database layer" -> 4 words
          2. "Also check the migration files" -> 5 words
        Total: 9 words.
        """
        result = scan_claude_code()
        defn = next(s for s in result["sessions"] if s["sessionId"] == "session_def")
        assert defn["userWordCount"] == 9

    def test_tool_call_categories(self, claude_projects):
        """sample_session.jsonl assistant tool calls:
          msg2: Read (file), Edit (file) -> 2 file, 0 terminal
          msg4: Write (file), Bash (terminal) -> 1 file, 1 terminal
          msg6: Bash (terminal) -> 0 file, 1 terminal
        Totals: 3 file, 2 terminal, 5 total.
        """
        result = scan_claude_code()
        abc = next(s for s in result["sessions"] if s["sessionId"] == "session_abc")
        assert abc["fileToolCalls"] == 3
        assert abc["terminalToolCalls"] == 2
        assert abc["toolCalls"] == 5

    def test_tool_call_categories_second_session(self, claude_projects):
        """second_session.jsonl assistant tool calls:
          msg2: Grep (file), Glob (file) -> 2 file
          msg4: Read (file), NotebookEdit (file) -> 2 file
        Totals: 4 file, 0 terminal.
        """
        result = scan_claude_code()
        defn = next(s for s in result["sessions"] if s["sessionId"] == "session_def")
        assert defn["fileToolCalls"] == 4
        assert defn["terminalToolCalls"] == 0
        assert defn["toolCalls"] == 4

    def test_models_detected(self, claude_projects):
        """Both sessions use claude-sonnet-4-20250514; sample_session also uses
        claude-opus-4-20250514. So models_used should have 2 distinct models."""
        result = scan_claude_code()
        assert "claude-sonnet-4-20250514" in result["models_used"]
        assert "claude-opus-4-20250514" in result["models_used"]

    def test_per_session_models(self, claude_projects):
        result = scan_claude_code()
        abc = next(s for s in result["sessions"] if s["sessionId"] == "session_abc")
        assert sorted(abc["models"]) == ["claude-opus-4-20250514", "claude-sonnet-4-20250514"]

    def test_git_branch(self, claude_projects):
        result = scan_claude_code()
        abc = next(s for s in result["sessions"] if s["sessionId"] == "session_abc")
        assert abc["gitBranch"] == "main"

    def test_version(self, claude_projects):
        result = scan_claude_code()
        abc = next(s for s in result["sessions"] if s["sessionId"] == "session_abc")
        assert abc["version"] == "1.2.0"

    def test_timestamps(self, claude_projects):
        result = scan_claude_code()
        assert result["earliest"] is not None
        assert result["latest"] is not None
        # earliest should be before latest
        assert result["earliest"] <= result["latest"]

    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        """Returns None when the projects dir doesn't exist."""
        import nextmillionai.scanner as scanner_mod

        monkeypatch.setattr(scanner_mod, "CLAUDE_PROJECTS_DIR", tmp_path / "nonexistent")
        assert scan_claude_code() is None

    def test_project_filter(self, claude_projects):
        """When project_filter matches, only that project is scanned."""
        result = scan_claude_code(project_filter="/Users/dev/my-project")
        assert result is not None
        assert result["total_sessions"] == 2  # both files are in the matching dir


# ── Cursor scanner sub-modules ───────────────────────────────────────────────


class TestScanCursorAiCode:
    def test_parses_ai_code(self, cursor_db):
        result = scan_cursor_ai_code()
        assert result is not None
        assert result["totalHashes"] == 5

    def test_by_source(self, cursor_db):
        result = scan_cursor_ai_code()
        assert result["bySource"]["composer"] == 3
        assert result["bySource"]["tab"] == 2

    def test_by_model(self, cursor_db):
        result = scan_cursor_ai_code()
        assert result["byModel"]["claude-sonnet-4-20250514"] == 3
        assert result["byModel"]["gpt-4o"] == 2


class TestScanCursorScoredCommits:
    def test_parses_scored_commits(self, cursor_db):
        result = scan_cursor_scored_commits()
        assert result is not None
        assert result["totalCommits"] == 3

    def test_lines_breakdown(self, cursor_db):
        result = scan_cursor_scored_commits()
        # Commit 1: 60+10=70 AI, 30 human, 100 total
        # Commit 2: 30+5=35 AI, 15 human, 50 total
        # Commit 3: 120+30=150 AI, 50 human, 200 total
        assert result["totalComposerLines"] == 210  # 60+30+120
        assert result["totalTabLines"] == 45  # 10+5+30
        assert result["totalAiLines"] == 255  # 210+45
        assert result["totalHumanLines"] == 95  # 30+15+50
        assert result["totalLinesAdded"] == 350  # 100+50+200


class TestScanCursorConversations:
    def test_parses_conversations(self, cursor_db):
        result = scan_cursor_conversations()
        assert result is not None
        assert result["totalConversations"] == 3

    def test_model_counts(self, cursor_db):
        result = scan_cursor_conversations()
        assert result["models"]["claude-sonnet-4-20250514"] == 2
        assert result["models"]["gpt-4o"] == 1

    def test_mode_counts(self, cursor_db):
        result = scan_cursor_conversations()
        assert result["modes"]["agent"] == 1
        assert result["modes"]["composer"] == 1
        assert result["modes"]["agentic"] == 1


# ── Cursor plans scanner ────────────────────────────────────────────────────


class TestScanCursorPlans:
    def test_parses_plans(self, tmp_path, monkeypatch):
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        (plans_dir / "auth-migration.plan.md").write_text("# Auth\n\nStep 1\nStep 2\nStep 3\n")
        (plans_dir / "db-refactor.plan.md").write_text("# DB\n\nRefactor all queries\n")
        monkeypatch.setattr(scanner_mod, "CURSOR_PLANS_DIR", plans_dir)
        result = scan_cursor_plans()
        assert result is not None
        assert result["totalPlans"] == 2

    def test_plan_line_counts(self, tmp_path, monkeypatch):
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
        (plans_dir / "five-lines.plan.md").write_text(content)
        monkeypatch.setattr(scanner_mod, "CURSOR_PLANS_DIR", plans_dir)
        result = scan_cursor_plans()
        plan = result["plans"][0]
        assert plan["lineCount"] == 6  # 5 lines + trailing newline

    def test_returns_none_when_no_plans(self, tmp_path, monkeypatch):
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        monkeypatch.setattr(scanner_mod, "CURSOR_PLANS_DIR", plans_dir)
        assert scan_cursor_plans() is None


# ── Helpers ──────────────────────────────────────────────────────────────────


class TestHelperFunctions:
    def test_ts_to_iso_seconds(self):
        result = ts_to_iso(1717200000)
        assert result is not None
        assert "2024-06-01" in result

    def test_ts_to_iso_milliseconds(self):
        result = ts_to_iso(1717200000000)
        assert result is not None
        assert "2024-06-01" in result

    def test_ts_to_iso_string_passthrough(self):
        result = ts_to_iso("2024-06-01T12:00:00+00:00")
        assert result == "2024-06-01T12:00:00+00:00"

    def test_ts_to_iso_none(self):
        assert ts_to_iso(None) is None

    def test_days_between(self):
        d = days_between("2024-06-01T00:00:00+00:00", "2024-06-10T00:00:00+00:00")
        assert d == 9

    def test_days_between_none(self):
        assert days_between(None, "2024-06-01T00:00:00+00:00") is None

    def test_iso_now_format(self):
        result = iso_now()
        assert "T" in result  # ISO 8601 format


# ── Tech stack detection ─────────────────────────────────────────────────────


class TestDetectTechStack:
    def test_python_project(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask>=2.0\nrequests\npytest\n")
        stack = detect_tech_stack(tmp_path)
        assert "Python" in stack["languages"]
        assert "Flask" in stack["frameworks"]

    def test_node_project(self, tmp_path):
        import json

        pkg = {"dependencies": {"express": "^4.0", "react": "^18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        stack = detect_tech_stack(tmp_path)
        assert "JavaScript" in stack["languages"]
        assert "Express" in stack["frameworks"]
        assert "React" in stack["frameworks"]

    def test_typescript_detection(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text("{}")
        stack = detect_tech_stack(tmp_path)
        assert "TypeScript" in stack["languages"]

    def test_go_project(self, tmp_path):
        (tmp_path / "go.mod").write_text(
            "module example.com/foo\nrequire github.com/gin-gonic/gin v1.9\n"
        )
        stack = detect_tech_stack(tmp_path)
        assert "Go" in stack["languages"]
        assert "Gin" in stack["frameworks"]

    def test_rust_project(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[dependencies]\nactix-web = "4"\n')
        stack = detect_tech_stack(tmp_path)
        assert "Rust" in stack["languages"]
        assert "Actix Web" in stack["frameworks"]

    def test_docker_detection(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
        stack = detect_tech_stack(tmp_path)
        assert "Docker" in stack["tools"]

    def test_github_actions_detection(self, tmp_path):
        gha = tmp_path / ".github" / "workflows"
        gha.mkdir(parents=True)
        (gha / "ci.yml").write_text("name: CI\n")
        stack = detect_tech_stack(tmp_path)
        assert "GitHub Actions" in stack["tools"]

    def test_empty_project(self, tmp_path):
        stack = detect_tech_stack(tmp_path)
        assert stack["languages"] == []
        assert stack["frameworks"] == []
        assert stack["tools"] == []


# ── compute_normalized ───────────────────────────────────────────────────────


class TestComputeNormalized:
    def test_returns_dict(self):
        n = compute_normalized(None, None, None, None)
        assert isinstance(n, dict)

    def test_total_sessions_from_claude(self, claude_projects):
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert n["totalSessions"] == 2

    def test_avg_turns_per_task(self, claude_projects):
        """session_abc: 3 user msgs, session_def: 2 user msgs.
        avgTurnsPerTask = totalUserMsgs / sessionCount = 5 / 2 = 2.5"""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert n["avgTurnsPerTask"] == 2.5

    def test_avg_prompt_words(self, claude_projects):
        """session_abc: 19 words / 3 user msgs, session_def: 9 words / 2 user msgs.
        Total: 28 words / 5 user msgs = 5.6"""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert n["avgPromptWords"] == 6  # rounded

    def test_terminal_command_count(self, claude_projects):
        """session_abc: 2 Bash calls, session_def: 0 Bash calls = 2 total."""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert n["terminalCommandCount"] == 2

    def test_files_per_session(self, claude_projects):
        """session_abc: 3 file tools, session_def: 4 file tools.
        Total: 7 / 2 sessions = 3.5"""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert n["filesPerSession"] == 3.5


# ── build_summary ────────────────────────────────────────────────────────────


class TestBuildSummary:
    def test_summary_structure(self, claude_projects):
        claude_data = scan_claude_code()
        normalized = compute_normalized(claude_data, None, None, None)
        summary = build_summary(claude_data, None, None, None, normalized)
        assert "total_sessions" in summary
        assert "total_ai_blocks" in summary
        assert "total_scored_commits" in summary
        assert "total_plans" in summary
        assert "total_projects" in summary
        assert "models_used" in summary

    def test_models_deduplicated(self, claude_projects):
        claude_data = scan_claude_code()
        normalized = compute_normalized(claude_data, None, None, None)
        summary = build_summary(claude_data, None, None, None, normalized)
        assert len(summary["models_used"]) == len(set(summary["models_used"]))


# ── v0.2.0 taxonomy signals ────────────────────────────────────────────────


class TestNewTaxonomySignals:
    """Tests for maxParallelAgents, mcpToolCalls, deepSessionCount,
    fileReadToEditRatio, and new session-level fields."""

    def test_mcp_tool_calls_counted(self, claude_projects):
        """MCP tool calls (mcp__*) are counted per session."""
        claude_data = scan_claude_code()
        # sample_session.jsonl has no mcp__ calls, second_session.jsonl has none
        for s in claude_data["sessions"]:
            assert "mcpToolCalls" in s
        n = compute_normalized(claude_data, None, None, None)
        assert "mcpToolCalls" in n
        assert n["mcpToolCalls"] == 0  # no mcp__ calls in fixtures

    def test_read_write_tool_calls_counted(self, claude_projects):
        """Read/write tools counted separately per session."""
        claude_data = scan_claude_code()
        for s in claude_data["sessions"]:
            assert "readToolCalls" in s
            assert "writeToolCalls" in s

    def test_file_read_to_edit_ratio(self, claude_projects):
        """fileReadToEditRatio = read tools / write tools."""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        # session_abc: Read(1) + Edit(1) + Write(1) + Bash(2) → read=1, write=2
        # session_def: Grep(1) + Glob(1) + Read(1) + NotebookEdit(1) → read=3, write=1
        # Total: read=4, write=3 → ratio=4/3≈1.33
        assert "fileReadToEditRatio" in n
        assert n["fileReadToEditRatio"] > 0

    def test_max_parallel_agents(self, claude_projects):
        """maxParallelAgents computed from session timestamp overlaps."""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert "maxParallelAgents" in n
        assert n["maxParallelAgents"] >= 1

    def test_deep_session_count(self, claude_projects):
        """deepSessionCount = sessions longer than 30 minutes."""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert "deepSessionCount" in n
        assert isinstance(n["deepSessionCount"], int)

    def test_plan_mode_percent(self, claude_projects):
        """planModePercent emitted."""
        claude_data = scan_claude_code()
        n = compute_normalized(claude_data, None, None, None)
        assert "planModePercent" in n
