"""Tests for nextmillionai.live — the local live-watch behind `report --live`.

Covers: fingerprinting, source discovery (none / sessions / repos),
debounce under rapid successive edits, startup refresh against a stale
assessment, honest error surfacing, and the hub's localhost status/SSE
endpoints.
"""

import http.client
import json
import threading
import time
from pathlib import Path

from nextmillionai.live import (
    LiveState,
    LiveWatcher,
    discover_watch_paths,
    tree_fingerprint,
)


def test_tree_fingerprint_changes_on_write(tmp_path):
    (tmp_path / "a.jsonl").write_text("one\n")
    fp1 = tree_fingerprint(tmp_path)
    (tmp_path / "a.jsonl").write_text("one\ntwo\n")
    fp2 = tree_fingerprint(tmp_path)
    assert fp1 != fp2
    (tmp_path / "b.jsonl").write_text("x")
    assert tree_fingerprint(tmp_path) != fp2


def test_tree_fingerprint_skips_heavy_dirs(tmp_path):
    (tmp_path / "objects").mkdir()
    (tmp_path / "objects" / "pack").write_text("blob")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x")
    assert tree_fingerprint(tmp_path)[0] == 0


def test_discover_watch_paths_no_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path / ".nma"))
    assert discover_watch_paths() == []


def test_discover_watch_paths_sessions_and_repos(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    nma = tmp_path / "nma"
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(nma))

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (nma / "data").mkdir(parents=True)
    (nma / "data" / "scan_results.json").write_text(
        json.dumps(
            {
                "git": {
                    "projects": [
                        {"path": str(repo), "name": "repo"},
                        # deleted repo: silently absent, never an error
                        {"path": str(tmp_path / "gone"), "name": "gone"},
                    ]
                }
            }
        )
    )

    paths = discover_watch_paths()
    ids = [sid for sid, _ in paths]
    assert ids == ["claude_code", "git:repo"]
    # repos are watched via .git only (commits, not working-tree churn)
    assert paths[1][1] == repo / ".git"


def test_state_snapshot_and_generation():
    st = LiveState()
    snap = st.snapshot()
    assert snap["live"] is False and snap["generation"] == 0

    st.set_watching([("claude_code", Path("/tmp/x"))])
    st.notify_updated(["claude_code"])
    snap = st.snapshot()
    assert snap["live"] is True
    assert snap["generation"] == 1
    assert snap["lastUpdated"]
    assert snap["lastChanged"] == ["claude_code"]
    json.dumps(snap)  # SSE payload must be serializable

    # a failed refresh never bumps generation — stale is shown, not faked
    st.notify_updated(["claude_code"], error="boom")
    snap2 = st.snapshot()
    assert snap2["generation"] == 1
    assert snap2["lastError"] == "boom"


def test_watcher_debounces_rapid_edits(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "s.jsonl").write_text("a")

    calls = []
    st = LiveState()

    def recompute():
        calls.append(time.monotonic())
        return True, None

    w = LiveWatcher(
        state=st,
        recompute=recompute,
        poll_interval=0.05,
        debounce=0.25,
        paths=[("claude_code", src)],
        initial_recompute=False,
    )
    w.start()
    time.sleep(0.1)
    for i in range(4):  # a burst of rapid successive edits
        (src / "s.jsonl").write_text("a" * (i + 2))
        time.sleep(0.05)
    time.sleep(1.2)
    w.stop()
    w.join(timeout=3)

    assert len(calls) == 1, f"debounce failed: {len(calls)} recomputes"
    snap = st.snapshot()
    assert snap["generation"] == 1
    assert snap["lastChanged"] == ["claude_code"]


def test_watcher_startup_refresh_and_no_sources():
    """A watcher started against a stale assessment refreshes once up
    front, and zero watchable sources is a working (idle) live mode."""
    calls = []
    st = LiveState()

    def recompute():
        calls.append(1)
        return True, None

    w = LiveWatcher(
        state=st,
        recompute=recompute,
        poll_interval=0.05,
        debounce=0.1,
        paths=[],
        initial_recompute=True,
    )
    w.start()
    time.sleep(0.3)
    w.stop()
    w.join(timeout=3)

    assert calls == [1]
    snap = st.snapshot()
    assert snap["live"] is True
    assert snap["sources"] == []
    assert snap["lastChanged"] == ["startup"]
    assert snap["generation"] == 1


def test_watcher_failure_surfaces_in_state():
    st = LiveState()
    w = LiveWatcher(
        state=st,
        recompute=lambda: (False, "scan exploded"),
        poll_interval=0.05,
        debounce=0.1,
        paths=[],
        initial_recompute=True,
    )
    w.start()
    time.sleep(0.3)
    w.stop()
    w.join(timeout=3)

    snap = st.snapshot()
    assert snap["lastError"] == "scan exploded"
    assert snap["generation"] == 0  # never pretend an update happened
    assert snap["updating"] is False


def _start_hub(monkeypatch):
    from nextmillionai import hub

    server = hub.ThreadedHTTPServer(("localhost", 0), hub.ProfileHandler)
    port = server.server_address[1]
    monkeypatch.setenv("PORT", str(port))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


def test_hub_live_status_endpoint(monkeypatch):
    server, port = _start_hub(monkeypatch)
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/api/live/status")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert "live" in data and "generation" in data and "lastUpdated" in data
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_hub_live_sse_pushes_on_generation_bump(monkeypatch):
    from nextmillionai.live import STATE

    server, port = _start_hub(monkeypatch)
    try:
        start_gen = STATE.snapshot()["generation"]
        conn = http.client.HTTPConnection("localhost", port, timeout=10)
        conn.request("GET", "/api/live/events")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/event-stream"
        line = resp.fp.readline()
        assert b"retry:" in line

        STATE.notify_updated(["claude_code"])
        deadline = time.time() + 10
        saw_bump = False
        while time.time() < deadline and not saw_bump:
            line = resp.fp.readline()
            if line.startswith(b"event: status"):
                payload = resp.fp.readline()
                assert payload.startswith(b"data: ")
                body = json.loads(payload[len(b"data: ") :])
                if body["generation"] > start_gen:
                    saw_bump = True
        assert saw_bump
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
