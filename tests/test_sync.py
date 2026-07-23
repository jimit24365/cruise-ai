"""Tests for multi-device sync: snapshot building, the deterministic
merge rule (dedupe by stable IDs, never blind sums), assess integration,
and the git transport against a local bare repo standing in for the
user's private GitHub repo (no network anywhere)."""

import json
import subprocess

import pytest

from cruise_ai.sync_merge import (
    apply_multi_device,
    build_device_snapshot,
    device_identity,
    devices_dir,
    merge_snapshots,
)


def _seed_local_data(home, sessions=None, activity=None, repos=None):
    """Write a minimal ledger + scan_results under CRUISE_AI_HOME."""
    hist = home / "data" / "history"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / "sessions.json").write_text(json.dumps(sessions or {}))
    (hist / "activity.json").write_text(json.dumps(activity or {}))
    (home / "data" / "scan_results.json").write_text(json.dumps({"git": {"projects": repos or []}}))


def _snap(device_id, name, sessions_by_day=None, repos=None, days=None):
    return {
        "syncFormat": 1,
        "deviceId": device_id,
        "deviceName": name,
        "updatedAt": "2026-06-12T00:00:00Z",
        "sessionsByDay": sessions_by_day or {},
        "activityByDay": days or [],
        "repos": repos or [],
        "summary": {"sessions": 0, "activeDays": 0, "dateRange": "no data"},
    }


# ── Snapshot build ───────────────────────────────────────────────────────────


def test_snapshot_is_derived_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    _seed_local_data(
        tmp_path,
        sessions={
            "claude_code:abc": {
                "tool": "claude_code",
                "project": "/Users/me/secret-path/proj",
                "start": "2026-06-01T10:00:00",
                "end": "2026-06-01T11:00:00",
                "task": 2,
                "userMsgs": 10,
            }
        },
        activity={"2026-06-01": {"date": "2026-06-01", "sessions": 1, "commits": 3}},
        repos=[
            {
                "path": "/Users/me/secret-path/proj",
                "name": "proj",
                "commits_6m": 3,
                "commit_dates": ["2026-06-01", "2026-06-01", "2026-05-30"],
            }
        ],
    )

    snap = build_device_snapshot()
    raw = json.dumps(snap)
    assert "secret-path" not in raw, "local file paths must never sync"
    assert "userMsgs" not in raw
    assert snap["sessionsByDay"] == {"2026-06-01": ["claude_code:abc"]}
    assert snap["repos"][0]["commitsByDay"] == {"2026-06-01": 2, "2026-05-30": 1}
    assert snap["summary"]["sessions"] == 1


def test_device_identity_is_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    a = device_identity()
    b = device_identity()
    assert a["deviceId"] == b["deviceId"]


# ── The merge rule ───────────────────────────────────────────────────────────


def test_merge_dedupes_sessions_by_ledger_key():
    a = _snap("a", "laptop", {"2026-06-01": ["claude_code:s1", "claude_code:s2"]})
    b = _snap("b", "desktop", {"2026-06-01": ["claude_code:s2", "codex_cli:s3"]})
    merged = merge_snapshots([a, b])
    assert merged["sessions"] == 3  # s2 counted once
    day = merged["mergedDays"][0]
    assert day["sessions"] == 3


def test_merge_overlapping_repos_never_double_count():
    """Same repo cloned on both machines: commits take the per-day max."""
    repo_a = {"name": "shared", "commits6m": 10, "commitsByDay": {"2026-06-01": 4}}
    repo_b = {"name": "shared", "commits6m": 10, "commitsByDay": {"2026-06-01": 4}}
    merged = merge_snapshots([_snap("a", "x", repos=[repo_a]), _snap("b", "y", repos=[repo_b])])
    assert merged["repoCount"] == 1
    assert merged["mergedDays"][0]["commits"] == 4  # max, not 8


def test_merge_disjoint_repos_clean_union():
    repo_a = {"name": "only-a", "commits6m": 2, "commitsByDay": {"2026-06-01": 2}}
    repo_b = {"name": "only-b", "commits6m": 3, "commitsByDay": {"2026-06-01": 3}}
    merged = merge_snapshots([_snap("a", "x", repos=[repo_a]), _snap("b", "y", repos=[repo_b])])
    assert merged["repoCount"] == 2
    assert merged["mergedDays"][0]["commits"] == 5  # distinct repos sum


def test_merge_is_order_independent():
    a = _snap("a", "x", {"2026-06-01": ["t:1"]}, repos=[{"name": "r", "commitsByDay": {}}])
    b = _snap("b", "y", {"2026-06-02": ["t:2"]})
    assert merge_snapshots([a, b]) == merge_snapshots([b, a])


# ── Assess integration ───────────────────────────────────────────────────────


def test_single_device_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    _seed_local_data(tmp_path)
    own = devices_dir() / "me.json"
    own.write_text(json.dumps(_snap(device_identity()["deviceId"], "laptop")))

    profile = {"activityByDay": [], "dimensions": {"signal_clarity": {"score": 70}}}
    apply_multi_device(profile)
    assert "multiDevice" not in profile


def test_two_devices_union_without_touching_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    _seed_local_data(tmp_path)
    my_id = device_identity()["deviceId"]
    (devices_dir() / f"{my_id}.json").write_text(
        json.dumps(_snap(my_id, "laptop", {"2026-06-01": ["claude_code:s1"]}))
    )
    (devices_dir() / "other.json").write_text(
        json.dumps(
            _snap(
                "other",
                "desktop",
                {"2026-06-02": ["claude_code:s9"]},
                days=[
                    {
                        "date": "2026-06-02",
                        "sessions": 1,
                        "commits": 0,
                        "tools": ["claude_code"],
                    }
                ],
            )
        )
    )

    dims_before = {"signal_clarity": {"score": 70}}
    profile = {
        "activityByDay": [{"date": "2026-06-01", "sessions": 1, "commits": 0}],
        "activity": {"days": [], "activeDays": 1},
        "dimensions": json.loads(json.dumps(dims_before)),
        "composite": 70,
    }
    apply_multi_device(profile)

    md = profile["multiDevice"]
    assert len(md["devices"]) == 2
    assert md["merged"]["sessions"] == 2
    assert [d for d in md["devices"] if d["thisDevice"]][0]["name"] == "laptop"
    # the other device's day joined the calendar, tagged synced
    days = {d["date"]: d for d in profile["activityByDay"]}
    assert days["2026-06-02"]["synced"] is True
    # scores untouched — raw signals never sync
    assert profile["dimensions"] == dims_before
    assert profile["composite"] == 70


# ── Transport (local bare repo = the user's private remote) ─────────────────


def _git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _git_available(), reason="git not installed")
def test_sync_round_trip_and_revoke(tmp_path, monkeypatch):
    from cruise_ai.network import load_sync_config, sync_revoke, sync_run

    home = tmp_path / "home"
    monkeypatch.setenv("CRUISE_AI_HOME", str(home))
    _seed_local_data(
        home,
        sessions={"claude_code:s1": {"tool": "claude_code", "start": "2026-06-01T10:00:00"}},
    )

    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        capture_output=True,
        check=True,
    )
    # bare repos need HEAD to point somewhere clonable even when empty
    url = str(remote)

    result = sync_run(url)
    assert result["pushed"] is True
    assert result["devices"] == 1
    assert load_sync_config()["repoUrl"] == url

    # simulate a second device pushing its snapshot
    other_clone = tmp_path / "other"
    subprocess.run(["git", "clone", url, str(other_clone)], capture_output=True, check=True)
    (other_clone / "devices").mkdir(exist_ok=True)
    (other_clone / "devices" / "otherdev.json").write_text(
        json.dumps(_snap("otherdev", "desktop", {"2026-06-02": ["claude_code:s2"]}))
    )
    for cmd in (
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "d2"],
        ["git", "push"],
    ):
        subprocess.run(cmd, cwd=str(other_clone), capture_output=True, check=True)

    # sync again on device A: pulls device B's snapshot into the mirror
    result = sync_run()
    assert result["devices"] == 2
    mirror = sorted(f.name for f in devices_dir().glob("*.json"))
    assert "otherdev.json" in mirror

    # revoke: removes OUR file from the remote, clears local state
    my_id = device_identity()["deviceId"]
    msg = sync_revoke()
    assert "removed" in msg.lower() or "cleared" in msg.lower()
    assert load_sync_config() is None
    assert list(devices_dir().glob("*.json")) == []
    ls = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=str(remote),
        capture_output=True,
        text=True,
    ).stdout
    assert f"{my_id}.json" not in ls
    assert "otherdev.json" in ls  # other devices keep theirs


@pytest.mark.skipif(not _git_available(), reason="git not installed")
def test_sync_unreachable_remote_is_graceful(tmp_path, monkeypatch):
    from cruise_ai.network import sync_run

    home = tmp_path / "home"
    monkeypatch.setenv("CRUISE_AI_HOME", str(home))
    _seed_local_data(home)

    with pytest.raises(RuntimeError) as exc:
        sync_run(str(tmp_path / "does-not-exist.git"))
    # friendly, actionable, and never crashes local use
    assert "git failed" in str(exc.value) or "reach" in str(exc.value).lower()


def test_sync_unconfigured_is_explicit(tmp_path, monkeypatch):
    from cruise_ai.network import sync_run

    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path))
    with pytest.raises(RuntimeError) as exc:
        sync_run()
    assert "No sync repo configured" in str(exc.value)


def test_multidevice_never_in_shareable(tmp_path, monkeypatch):
    """The sync union is private: build_shareable_profile must drop it."""
    from cruise_ai.schema import build_shareable_profile

    profile = {
        "schema_version": "1.0",
        "multiDevice": {"devices": [{"id": "x", "name": "laptop"}]},
        "composite": 50,
    }
    shareable = build_shareable_profile(profile, {})
    assert "multiDevice" not in shareable
