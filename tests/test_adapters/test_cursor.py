"""Tests for the CursorAdapter.

Uses the same SQLite fixture as test_scanner.py to verify that the
adapter produces correct sub-scanner results and raw_data dict.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nextmillionai.adapters.cursor import CursorAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def cursor_adapter(tmp_path):
    """Set up a CursorAdapter with fixture SQLite DB."""
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    ai_dir = cursor_dir / "ai-tracking"
    ai_dir.mkdir()
    src = FIXTURES / "cursor_tracking.db"
    dst = ai_dir / "ai-code-tracking.db"
    shutil.copy(src, dst)
    return CursorAdapter(
        cursor_dir=cursor_dir,
        db_path=dst,
        plans_dir=cursor_dir / "plans",  # nonexistent
        projects_dir=cursor_dir / "projects",  # nonexistent
    )


class TestCursorAdapterDetect:
    def test_detect_true(self, cursor_adapter):
        assert cursor_adapter.detect() is True

    def test_detect_false(self, tmp_path):
        adapter = CursorAdapter(cursor_dir=tmp_path / "nonexistent")
        assert adapter.detect() is False


class TestCursorAdapterSubScanners:
    def test_ai_code(self, cursor_adapter):
        result = cursor_adapter._scan_ai_code()
        assert result is not None
        assert result["totalHashes"] == 5
        assert result["bySource"]["composer"] == 3
        assert result["bySource"]["tab"] == 2

    def test_scored_commits(self, cursor_adapter):
        result = cursor_adapter._scan_scored_commits()
        assert result is not None
        assert result["totalCommits"] == 3
        assert result["totalComposerLines"] == 210
        assert result["totalTabLines"] == 45

    def test_conversations(self, cursor_adapter):
        result = cursor_adapter._scan_conversations()
        assert result is not None
        assert result["totalConversations"] == 3

    def test_plans_none_when_missing(self, cursor_adapter):
        result = cursor_adapter._scan_plans()
        assert result is None

    def test_plans_with_data(self, tmp_path):
        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        (plans_dir / "auth.plan.md").write_text("# Auth Plan\nStep 1\n")
        adapter = CursorAdapter(
            cursor_dir=tmp_path,
            plans_dir=plans_dir,
        )
        result = adapter._scan_plans()
        assert result is not None
        assert result["totalPlans"] == 1


class TestCursorAdapterRawData:
    def test_scan_produces_raw_data(self, cursor_adapter):
        cursor_adapter.scan()
        raw = cursor_adapter.raw_data()
        assert raw is not None
        assert "ai_code" in raw
        assert "scored_commits" in raw
        assert "conversations" in raw

    def test_raw_data_ai_code_shape(self, cursor_adapter):
        cursor_adapter.scan()
        raw = cursor_adapter.raw_data()
        ai_code = raw["ai_code"]
        assert ai_code is not None
        assert "totalHashes" in ai_code
        assert "bySource" in ai_code
        assert "byModel" in ai_code


# ── Composer sessions: the real Cursor history (state.vscdb) ────────────────


def _make_global_db(user_dir, composers, bubbles=None):
    """composers: [(composerId, createdAt_ms, lastUpdatedAt_ms, isAgentic)]"""
    import json as _json
    import sqlite3

    gs = user_dir / "globalStorage"
    gs.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(gs / "state.vscdb")
    con.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
    con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    for cid, created, updated, agentic in composers:
        con.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            (
                f"composerData:{cid}",
                _json.dumps(
                    {
                        "composerId": cid,
                        "createdAt": created,
                        "lastUpdatedAt": updated,
                        "isAgentic": agentic,
                        "conversation": [],
                    }
                ),
            ),
        )
    for cid, n in (bubbles or {}).items():
        for i in range(n):
            con.execute(
                "INSERT INTO cursorDiskKV VALUES (?, ?)",
                (f"bubbleId:{cid}:b{i}", "{}"),
            )
    con.commit()
    con.close()


def _make_workspace_db(user_dir, ws_name, folder=None, all_composers=None, chat_tabs=None):
    import json as _json
    import sqlite3

    ws = user_dir / "workspaceStorage" / ws_name
    ws.mkdir(parents=True, exist_ok=True)
    if folder:
        (ws / "workspace.json").write_text(_json.dumps({"folder": f"file://{folder}"}))
    con = sqlite3.connect(ws / "state.vscdb")
    con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    if all_composers is not None:
        con.execute(
            "INSERT INTO ItemTable VALUES ('composer.composerData', ?)",
            (_json.dumps({"allComposers": all_composers}),),
        )
    if chat_tabs is not None:
        con.execute(
            "INSERT INTO ItemTable VALUES ('workbench.panel.aichat.view.aichat.chatdata', ?)",
            (_json.dumps({"tabs": chat_tabs}),),
        )
    con.commit()
    con.close()


CID_A = "aaaaaaaa-1111-2222-3333-444444444444"
CID_B = "bbbbbbbb-1111-2222-3333-444444444444"


def test_composer_sessions_current_generation(tmp_path):
    user_dir = tmp_path / "User"
    # two sessions: 1h and 30min, one agentic
    _make_global_db(
        user_dir,
        [
            (CID_A, 1733925809000, 1733929409000, True),  # 1h
            (CID_B, 1750000000000, 1750001800000, False),  # 30m
        ],
        bubbles={CID_A: 5},
    )
    a = CursorAdapter(
        cursor_dir=tmp_path / "nope",
        db_path=tmp_path / "nope.db",
        plans_dir=tmp_path / "nope",
        projects_dir=tmp_path / "nope",
        app_user_dir=user_dir,
    )
    assert a.detect() is True  # app storage alone is enough
    sessions = a.scan()
    composer = [s for s in sessions if s.session_id.startswith("composer:")]
    assert len(composer) == 2
    by_id = {s.session_id: s for s in composer}
    sa = by_id[f"composer:{CID_A}"]
    assert sa.started_at is not None and sa.ended_at is not None
    assert round((sa.ended_at - sa.started_at).total_seconds() / 3600, 1) == 1.0
    assert sa.extras["agentic"] is True
    assert sa.extras["messages"] == 5

    raw = a.raw_data()["composerSessions"]
    assert raw["sessions"] == 2
    assert raw["estimatedHours"] == 1.5
    assert raw["agentic"] == 1
    assert raw["byGeneration"] == {"global": 2}


def test_composer_sessions_older_generations_and_dedupe(tmp_path):
    user_dir = tmp_path / "User"
    # global already holds CID_A (migrated); workspace still lists it too
    _make_global_db(user_dir, [(CID_A, 1733925809000, 1733929409000, False)])
    _make_workspace_db(
        user_dir,
        "ws1",
        folder="/Users/dev/oldproj",
        all_composers=[
            {"composerId": CID_A, "createdAt": 1733925809000, "lastUpdatedAt": 1733929409000},
            {"composerId": CID_B, "createdAt": 1700000000000, "lastUpdatedAt": 1700003600000},
        ],
    )
    _make_workspace_db(
        user_dir,
        "ws2",
        folder="/Users/dev/ancient",
        chat_tabs=[{"tabId": "t1", "lastSendTime": 1690000000000, "bubbles": [{}, {}]}],
    )
    a = CursorAdapter(
        cursor_dir=tmp_path / "nope",
        db_path=tmp_path / "nope.db",
        plans_dir=tmp_path / "nope",
        projects_dir=tmp_path / "nope",
        app_user_dir=user_dir,
    )
    sessions = [s for s in a.scan() if s.session_id.startswith("composer:")]
    assert len(sessions) == 3  # CID_A deduped (global wins), CID_B + aichat tab
    raw = a.raw_data()["composerSessions"]
    assert raw["byGeneration"] == {"global": 1, "workspace": 1, "aichat": 1}
    by_id = {s.session_id: s for s in sessions}
    assert by_id[f"composer:{CID_B}"].project_path == "/Users/dev/oldproj"
    assert by_id["composer:aichat:ws2:t1"].extras["messages"] == 2


def test_composer_duration_capped_at_8h(tmp_path):
    user_dir = tmp_path / "User"
    week_ms = 7 * 24 * 3600 * 1000
    _make_global_db(user_dir, [(CID_A, 1733925809000, 1733925809000 + week_ms, False)])
    a = CursorAdapter(
        cursor_dir=tmp_path / "nope",
        db_path=tmp_path / "nope.db",
        plans_dir=tmp_path / "nope",
        projects_dir=tmp_path / "nope",
        app_user_dir=user_dir,
    )
    s = [x for x in a.scan() if x.session_id.startswith("composer:")][0]
    assert (s.ended_at - s.started_at).total_seconds() == 8 * 3600


def test_no_app_storage_is_clean(tmp_path):
    a = CursorAdapter(
        cursor_dir=tmp_path / "nope",
        db_path=tmp_path / "nope.db",
        plans_dir=tmp_path / "nope",
        projects_dir=tmp_path / "nope",
        app_user_dir=tmp_path / "absent",
    )
    assert a.detect() is False
    assert a.scan() == []
