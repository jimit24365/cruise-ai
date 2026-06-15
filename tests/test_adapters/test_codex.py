"""Tests for the CodexAdapter with deepened JSONL parsing.

Uses codex_session.jsonl fixture to verify message, model, tool-call,
and timestamp extraction.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nextmillionai.adapters._base import Session
from nextmillionai.adapters.codex import CodexAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def codex_adapter(tmp_path):
    """Set up a CodexAdapter with fixture JSONL files."""
    sessions_dir = tmp_path / ".codex" / "sessions"
    sessions_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "codex_session.jsonl", sessions_dir / "sess_001.jsonl")
    return CodexAdapter(sessions_dir=sessions_dir)


class TestCodexAdapterDetect:
    def test_detect_true(self, codex_adapter):
        assert codex_adapter.detect() is True

    def test_detect_false(self, tmp_path):
        adapter = CodexAdapter(sessions_dir=tmp_path / "nonexistent")
        assert adapter.detect() is False


class TestCodexAdapterScan:
    def test_returns_sessions(self, codex_adapter):
        sessions = codex_adapter.scan()
        assert len(sessions) == 1
        assert all(isinstance(s, Session) for s in sessions)

    def test_session_tool_field(self, codex_adapter):
        sessions = codex_adapter.scan()
        assert sessions[0].tool == "codex"

    def test_user_msg_count(self, codex_adapter):
        """3 user messages in codex_session.jsonl."""
        sessions = codex_adapter.scan()
        assert sessions[0].user_msgs == 3

    def test_assistant_msg_count(self, codex_adapter):
        """3 assistant messages in codex_session.jsonl."""
        sessions = codex_adapter.scan()
        assert sessions[0].assistant_msgs == 3

    def test_models_extracted(self, codex_adapter):
        """Models o3 and o4-mini in the fixture."""
        sessions = codex_adapter.scan()
        assert "o3" in sessions[0].models
        assert "o4-mini" in sessions[0].models

    def test_tool_calls_extracted(self, codex_adapter):
        """3 tool calls: read_file, write_file, run_command."""
        sessions = codex_adapter.scan()
        tc = sessions[0].tool_calls_by_type
        assert tc.get("read_file", 0) == 1
        assert tc.get("write_file", 0) == 1
        assert tc.get("run_command", 0) == 1

    def test_prompt_word_counts(self, codex_adapter):
        """Word counts for user messages:
        1. "Refactor the auth module to use JWT tokens" -> 8
        2. "Also add refresh token support" -> 5
        3. "Ship it" -> 2
        """
        sessions = codex_adapter.scan()
        assert sessions[0].prompt_word_counts == [8, 5, 2]

    def test_timestamps(self, codex_adapter):
        sessions = codex_adapter.scan()
        s = sessions[0]
        assert s.started_at is not None
        assert s.ended_at is not None
        assert s.started_at < s.ended_at

    def test_project_path_from_cwd(self, codex_adapter):
        sessions = codex_adapter.scan()
        assert sessions[0].project_path == "/Users/dev/my-app"


class TestCodexAdapterRawData:
    def test_raw_data_shape(self, codex_adapter):
        codex_adapter.scan()
        raw = codex_adapter.raw_data()
        assert raw is not None
        assert "total_sessions" in raw
        assert "parsed_sessions" in raw
        assert "models_used" in raw
        assert "path" in raw

    def test_raw_data_counts(self, codex_adapter):
        codex_adapter.scan()
        raw = codex_adapter.raw_data()
        assert raw["total_sessions"] == 1
        assert raw["parsed_sessions"] == 1
        assert raw["total_user_msgs"] == 3
        assert raw["total_assistant_msgs"] == 3

    def test_raw_data_models(self, codex_adapter):
        codex_adapter.scan()
        raw = codex_adapter.raw_data()
        assert raw["models_used"]["o3"] == 2
        assert raw["models_used"]["o4-mini"] == 1

    def test_non_jsonl_files_counted(self, tmp_path):
        """Non-JSONL files still appear in total_sessions count."""
        sessions_dir = tmp_path / ".codex" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "old_session.dat").write_text("binary data")
        shutil.copy(FIXTURES / "codex_session.jsonl", sessions_dir / "sess.jsonl")
        adapter = CodexAdapter(sessions_dir=sessions_dir)
        adapter.scan()
        raw = adapter.raw_data()
        assert raw["total_sessions"] == 2  # both files counted
        assert raw["parsed_sessions"] == 1  # only JSONL parsed


# ── Date-nested layout (current Codex versions) ──────────────────────────────


def test_nested_session_layout(tmp_path):
    """Newer Codex writes sessions/YYYY/MM/DD/rollout-*.jsonl — flat-only
    scanning returns zero sessions on any up-to-date install."""
    import json as _json

    nested = tmp_path / "2026" / "06" / "12"
    nested.mkdir(parents=True)
    lines = [
        {"type": "message", "role": "user", "content": "build x", "timestamp": 1750000000},
        {
            "type": "message",
            "role": "assistant",
            "content": "done",
            "model": "gpt-5",
            "timestamp": 1750000300,
        },
    ]
    (nested / "rollout-2026-06-12-abc.jsonl").write_text("\n".join(_json.dumps(x) for x in lines))
    # plus an old-style flat file: both generations in one store
    (tmp_path / "old-session.jsonl").write_text("\n".join(_json.dumps(x) for x in lines))

    adapter = CodexAdapter(sessions_dir=tmp_path)
    sessions = adapter.scan()
    assert len(sessions) == 2
    assert all(s.started_at is not None for s in sessions)
    assert adapter.raw_data()["total_sessions"] == 2
