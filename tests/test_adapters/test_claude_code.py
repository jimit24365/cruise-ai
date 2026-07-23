"""Tests for the ClaudeCodeAdapter.

Uses the same JSONL fixtures as test_scanner.py to verify that the
adapter produces correct Session objects and raw_data dict.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cruise_ai.adapters._base import Session
from cruise_ai.adapters.claude_code import ClaudeCodeAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def claude_adapter(tmp_path):
    """Set up a ClaudeCodeAdapter with fixture JSONL files."""
    projects_dir = tmp_path / ".claude" / "projects"
    proj_dir = projects_dir / "-Users-dev-my-project"
    proj_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "sample_session.jsonl", proj_dir / "session_abc.jsonl")
    shutil.copy(FIXTURES / "second_session.jsonl", proj_dir / "session_def.jsonl")
    return ClaudeCodeAdapter(projects_dir=projects_dir)


class TestClaudeCodeAdapterDetect:
    def test_detect_true(self, claude_adapter):
        assert claude_adapter.detect() is True

    def test_detect_false(self, tmp_path):
        adapter = ClaudeCodeAdapter(projects_dir=tmp_path / "nonexistent")
        assert adapter.detect() is False


class TestClaudeCodeAdapterScan:
    def test_returns_sessions(self, claude_adapter):
        sessions = claude_adapter.scan()
        assert len(sessions) == 2
        assert all(isinstance(s, Session) for s in sessions)

    def test_session_tool_field(self, claude_adapter):
        sessions = claude_adapter.scan()
        assert all(s.tool == "claude_code" for s in sessions)

    def test_session_ids(self, claude_adapter):
        sessions = claude_adapter.scan()
        ids = {s.session_id for s in sessions}
        assert ids == {"session_abc", "session_def"}

    def test_project_path_from_cwd(self, claude_adapter):
        sessions = claude_adapter.scan()
        paths = {s.project_path for s in sessions}
        assert "/Users/dev/my-project" in paths

    def test_user_msg_count(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        assert abc.user_msgs == 3

    def test_assistant_msg_count(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        assert abc.assistant_msgs == 3

    def test_prompt_word_counts(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        # "Fix the login bug in auth.py" -> 6
        # "Now add unit tests for the auth module please" -> 9
        # "Looks good, ship it" -> 4
        assert abc.prompt_word_counts == [6, 9, 4]

    def test_tool_calls_by_type(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        assert abc.tool_calls_by_type["file"] == 3
        assert abc.tool_calls_by_type["terminal"] == 2

    def test_models(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        assert "claude-sonnet-4-20250514" in abc.models
        assert "claude-opus-4-20250514" in abc.models

    def test_timestamps(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        assert abc.started_at is not None
        assert abc.ended_at is not None
        assert abc.started_at <= abc.ended_at

    def test_extras(self, claude_adapter):
        sessions = claude_adapter.scan()
        abc = next(s for s in sessions if s.session_id == "session_abc")
        assert abc.extras.get("git_branch") == "main"
        assert abc.extras.get("version") == "1.2.0"


class TestClaudeCodeAdapterRawData:
    def test_raw_data_shape(self, claude_adapter):
        claude_adapter.scan()
        raw = claude_adapter.raw_data()
        assert raw is not None
        assert "sessions" in raw
        assert "total_sessions" in raw
        assert "total_messages" in raw
        assert "models_used" in raw
        assert "tool_calls" in raw

    def test_raw_data_matches_scanner(self, claude_adapter):
        """raw_data() should produce the same shape as the old scan_claude_code()."""
        claude_adapter.scan()
        raw = claude_adapter.raw_data()
        assert raw["total_sessions"] == 2
        assert raw["total_messages"] == 10
        assert "claude-sonnet-4-20250514" in raw["models_used"]

    def test_raw_data_none_when_not_scanned(self):
        adapter = ClaudeCodeAdapter(projects_dir=Path("/nonexistent"))
        assert adapter.raw_data() is None

    def test_project_filter(self, claude_adapter):
        sessions = claude_adapter.scan(project_filter="/Users/dev/my-project")
        assert len(sessions) == 2  # both files in matching dir


# ── Subagent transcripts (<session-id>/subagents/agent-*.jsonl) ─────────────


def test_subagent_runs_counted(tmp_path):
    """Newer Claude Code stores each subagent run beside the parent
    session — runs and runtime must be measured, never skipped."""
    import json as _json

    from cruise_ai.adapters.claude_code import ClaudeCodeAdapter

    proj = tmp_path / "-Users-dev-myproj"
    proj.mkdir(parents=True)
    main = [
        {
            "type": "user",
            "timestamp": "2026-06-01T10:00:00Z",
            "message": {"content": "build it"},
            "cwd": "/Users/dev/myproj",
        },
        {
            "type": "assistant",
            "timestamp": "2026-06-01T10:30:00Z",
            "message": {"content": [{"type": "text", "text": "done"}]},
        },
    ]
    (proj / "sess1.jsonl").write_text("\n".join(_json.dumps(x) for x in main))

    subs = proj / "sess1" / "subagents"
    subs.mkdir(parents=True)
    for i, (start, end) in enumerate(
        [
            ("2026-06-01T10:05:00Z", "2026-06-01T11:05:00Z"),
            ("2026-06-01T10:06:00Z", "2026-06-01T10:36:00Z"),
        ]
    ):
        lines = [
            {"type": "user", "timestamp": start, "message": {"content": "go"}},
            {
                "type": "assistant",
                "timestamp": end,
                "message": {"content": [{"type": "text", "text": "ok"}]},
            },
        ]
        (subs / f"agent-{i}.jsonl").write_text("\n".join(_json.dumps(x) for x in lines))

    a = ClaudeCodeAdapter(projects_dir=tmp_path)
    sessions = a.scan()
    assert len(sessions) == 1
    s = sessions[0]
    # two run files = two dispatches, even without Task tool_use lines
    assert s.tool_calls_by_type.get("task") == 2
    assert s.extras["subagentRuns"] == 2
    assert s.extras["agentMinutes"] == 90.0  # 60 + 30

    raw = a.raw_data()
    assert raw["subagent_runs"] == 2
    assert raw["agent_hours"] == 1.5


def test_no_subagents_dir_is_clean(tmp_path):
    import json as _json

    from cruise_ai.adapters.claude_code import ClaudeCodeAdapter

    proj = tmp_path / "-Users-dev-plain"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(
        _json.dumps(
            {"type": "user", "timestamp": "2026-06-01T10:00:00Z", "message": {"content": "hi"}}
        )
    )
    a = ClaudeCodeAdapter(projects_dir=tmp_path)
    sessions = a.scan()
    assert sessions[0].extras["subagentRuns"] == 0
    assert a.raw_data()["agent_hours"] == 0


def test_active_time_excludes_idle_gaps(tmp_path):
    """Human session durations are gap-based ACTIVE time: a 2h idle gap
    inside a session never counts as work."""
    import json as _json

    from cruise_ai.adapters.claude_code import ClaudeCodeAdapter

    proj = tmp_path / "-Users-dev-gaps"
    proj.mkdir(parents=True)
    lines = [
        {"type": "user", "timestamp": "2026-06-01T10:00:00Z", "message": {"content": "go"}},
        {
            "type": "assistant",
            "timestamp": "2026-06-01T10:10:00Z",
            "message": {"content": [{"type": "text", "text": "ok"}]},
        },
        # 1h50m idle (lunch) — must not count
        {"type": "user", "timestamp": "2026-06-01T12:00:00Z", "message": {"content": "more"}},
        {
            "type": "assistant",
            "timestamp": "2026-06-01T12:05:00Z",
            "message": {"content": [{"type": "text", "text": "done"}]},
        },
    ]
    (proj / "s.jsonl").write_text("\n".join(_json.dumps(x) for x in lines))

    a = ClaudeCodeAdapter(projects_dir=tmp_path)
    s = a.scan()[0]
    assert s.extras["activeMinutes"] == 15.0  # 10 + 5, never 125
    # span (started→ended) still reflects first-to-last for the record
    assert round((s.ended_at - s.started_at).total_seconds() / 60) == 125
