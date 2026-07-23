"""
cruise_ai.sync_merge — Multi-device snapshots + deterministic merge.

Pure local logic (no network): builds this device's derived-only sync
snapshot, and merges snapshots from all devices into one union view.
The git transport lives in network.py (the one outbound module); this
module only reads/writes local files, so the assessment path may use it.

THE MERGE RULE (documented in docs/SYNC.md, deterministic by design):

  - Sessions  — deduped by stable ledger key (``tool:session_id``);
                per-day counts are the size of the per-day key union.
  - Commits   — deduped per repo per day: the same repo cloned on two
                machines holds the same commits, so each (repo, day)
                takes the MAX across devices, never the sum. Distinct
                repos sum cleanly.
  - Repos     — union by repo name; per-repo totals take the max.
  - Days      — the activity calendar is the union of all devices' days.
  - Scores    — NEVER merged. Dimension scores need raw local signals
                (prompt text stats, plan-mode, dispatches) that do not
                sync; each device's scores stay its own. The merged view
                is recomputed from the deduped union of countable
                evidence — numbers are never averaged across devices.

What syncs is derived-only: session IDs + day counts, per-repo commit-day
counts, repo names, day records. Never prompts, transcripts, code, file
paths, or scores-as-inputs.
"""

from __future__ import annotations

import json
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cruise_ai.paths import data_dir, scan_results_path

SYNC_FORMAT = 1


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Device identity ──────────────────────────────────────────────────────────


def device_identity_path() -> Path:
    return data_dir() / "sync_device.json"


def device_identity() -> dict:
    """Stable per-device identity, created once (uuid + hostname)."""
    p = device_identity_path()
    if p.is_file():
        try:
            ident = json.loads(p.read_text())
            if isinstance(ident, dict) and ident.get("deviceId"):
                return ident
        except (json.JSONDecodeError, OSError):
            pass
    ident = {
        "deviceId": uuid.uuid4().hex[:16],
        "deviceName": platform.node() or "unnamed-device",
        "createdAt": _iso_now(),
    }
    p.write_text(json.dumps(ident, indent=2))
    return ident


def devices_dir() -> Path:
    """Local mirror of every device's snapshot (this one + pulled ones)."""
    d = data_dir() / "sync" / "devices"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Snapshot build (derived-only) ────────────────────────────────────────────


def build_device_snapshot() -> dict:
    """This device's sync snapshot — dedupe keys + day counts, nothing raw.

    Reads the durable history ledger + the last scan. Local file paths are
    deliberately reduced to repo NAMES; session entries to their ledger
    keys and dates.
    """
    ident = device_identity()

    # Sessions: ledger keys per day (the dedupe keys)
    sessions_by_day: dict = {}
    ledger_file = data_dir() / "history" / "sessions.json"
    if ledger_file.is_file():
        try:
            ledger = json.loads(ledger_file.read_text())
        except (json.JSONDecodeError, OSError):
            ledger = {}
        for key, entry in ledger.items():
            start = entry.get("start") or ""
            date = start[:10]
            if date:
                sessions_by_day.setdefault(date, []).append(key)

    # Activity days (already derived day records)
    activity_by_day = []
    activity_file = data_dir() / "history" / "activity.json"
    if activity_file.is_file():
        try:
            store = json.loads(activity_file.read_text())
            for date in sorted(store.keys()):
                day = store[date]
                activity_by_day.append(
                    {
                        "date": date,
                        "sessions": day.get("sessions") or 0,
                        "commits": day.get("commits") or 0,
                        "tools": day.get("tools") or [],
                        "aiRatio": day.get("aiRatio"),
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass

    # Repos: names + per-day commit counts (the commit dedupe unit)
    repos = []
    sr = scan_results_path()
    if sr.is_file():
        try:
            scan = json.loads(sr.read_text())
            for proj in (scan.get("git") or {}).get("projects") or []:
                name = proj.get("name")
                if not name:
                    continue
                commits_by_day: dict = {}
                for d in proj.get("commit_dates") or []:
                    date = str(d)[:10]
                    commits_by_day[date] = commits_by_day.get(date, 0) + 1
                repos.append(
                    {
                        "name": name,
                        "commits6m": proj.get("commits_6m", 0),
                        "commitsByDay": commits_by_day,
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass

    all_keys = set()
    for keys in sessions_by_day.values():
        all_keys.update(keys)
    dates = sorted(set(sessions_by_day.keys()) | {d["date"] for d in activity_by_day})

    return {
        "syncFormat": SYNC_FORMAT,
        "deviceId": ident["deviceId"],
        "deviceName": ident["deviceName"],
        "updatedAt": _iso_now(),
        "sessionsByDay": {k: sorted(v) for k, v in sorted(sessions_by_day.items())},
        "activityByDay": activity_by_day,
        "repos": repos,
        "summary": {
            "sessions": len(all_keys),
            "activeDays": len(dates),
            "dateRange": f"{dates[0]} to {dates[-1]}" if dates else "no data",
        },
    }


def write_own_snapshot() -> Path:
    """Write this device's snapshot into the local mirror; returns path."""
    snap = build_device_snapshot()
    out = devices_dir() / f"{snap['deviceId']}.json"
    out.write_text(json.dumps(snap, indent=1))
    return out


def load_device_snapshots() -> list:
    """All device snapshots in the local mirror (incl. this device)."""
    snaps = []
    for f in sorted(devices_dir().glob("*.json")):
        try:
            snap = json.loads(f.read_text())
            if isinstance(snap, dict) and snap.get("deviceId"):
                snaps.append(snap)
        except (json.JSONDecodeError, OSError):
            continue
    return snaps


# ── Deterministic merge ──────────────────────────────────────────────────────


def merge_snapshots(snapshots: list) -> dict:
    """Union across devices, deduped by stable IDs — see THE MERGE RULE.

    Deterministic: same snapshots in, same merge out, regardless of
    order. Counts are computed over the deduped union, never by adding
    per-device totals.
    """
    # Sessions: per-day union of ledger keys
    session_keys_by_day: dict = {}
    for snap in snapshots:
        for date, keys in (snap.get("sessionsByDay") or {}).items():
            session_keys_by_day.setdefault(date, set()).update(keys)

    # Commits: per repo per day, max across devices (same clone = same
    # commits); distinct repos sum.
    repo_day_commits: dict = {}
    repo_totals: dict = {}
    for snap in snapshots:
        for repo in snap.get("repos") or []:
            name = repo.get("name")
            if not name:
                continue
            repo_totals[name] = max(repo_totals.get(name, 0), repo.get("commits6m", 0) or 0)
            for date, n in (repo.get("commitsByDay") or {}).items():
                cur = repo_day_commits.setdefault(name, {})
                cur[date] = max(cur.get(date, 0), n or 0)

    commits_by_day: dict = {}
    for _name, by_day in repo_day_commits.items():
        for date, n in by_day.items():
            commits_by_day[date] = commits_by_day.get(date, 0) + n

    # Day records: tools union; aiRatio from the device with most
    # sessions that day (a ratio cannot be deduped, only chosen)
    tools_by_day: dict = {}
    ai_ratio_by_day: dict = {}
    for snap in snapshots:
        for day in snap.get("activityByDay") or []:
            date = day.get("date")
            if not date:
                continue
            tools_by_day.setdefault(date, set()).update(day.get("tools") or [])
            if day.get("aiRatio") is not None:
                best = ai_ratio_by_day.get(date)
                weight = day.get("sessions") or 0
                if best is None or weight > best[0]:
                    ai_ratio_by_day[date] = (weight, day["aiRatio"])

    all_dates = sorted(set(session_keys_by_day) | set(commits_by_day) | set(tools_by_day))
    merged_days = []
    for date in all_dates:
        merged_days.append(
            {
                "date": date,
                "sessions": len(session_keys_by_day.get(date, ())),
                "commits": commits_by_day.get(date, 0),
                "tools": sorted(tools_by_day.get(date, ())),
                "aiRatio": ai_ratio_by_day.get(date, (0, None))[1],
            }
        )

    all_session_keys = set()
    for keys in session_keys_by_day.values():
        all_session_keys.update(keys)

    devices = sorted(
        (
            {
                "id": s.get("deviceId"),
                "name": s.get("deviceName"),
                "lastSync": s.get("updatedAt"),
                "sessions": (s.get("summary") or {}).get("sessions", 0),
                "activeDays": (s.get("summary") or {}).get("activeDays", 0),
            }
            for s in snapshots
        ),
        key=lambda d: d["id"] or "",
    )

    return {
        "devices": devices,
        "mergedDays": merged_days,
        "sessions": len(all_session_keys),
        "activeDays": len([d for d in merged_days if d["sessions"] or d["commits"]]),
        "repoCount": len(repo_totals),
        "dateRange": f"{all_dates[0]} to {all_dates[-1]}" if all_dates else "no data",
    }


def apply_multi_device(profile: dict) -> dict:
    """Attach the multi-device union to an assessment (in place).

    Only acts when ≥2 device snapshots exist locally. Extends the
    activity calendar with the cross-device union and records device
    provenance. Dimension scores are deliberately untouched — raw
    signals never sync (see THE MERGE RULE).
    """
    snapshots = load_device_snapshots()
    ident_id = device_identity()["deviceId"]
    if len(snapshots) < 2:
        profile.pop("multiDevice", None)
        return profile

    merged = merge_snapshots(snapshots)
    for dev in merged["devices"]:
        dev["thisDevice"] = dev["id"] == ident_id

    # Union calendar: keep richer local day records where they exist;
    # add union days (other devices) the local calendar doesn't have,
    # and lift counts where the deduped union counted more.
    local_days = {d.get("date"): dict(d) for d in profile.get("activityByDay") or []}
    for day in merged["mergedDays"]:
        date = day["date"]
        cur = local_days.get(date)
        if cur is None:
            entry = dict(day)
            entry["synced"] = True
            local_days[date] = entry
        else:
            if (day["sessions"] or 0) > (cur.get("sessions") or 0):
                cur["sessions"] = day["sessions"]
                cur["synced"] = True
            if (day["commits"] or 0) > (cur.get("commits") or 0):
                cur["commits"] = day["commits"]
                cur["synced"] = True
            cur["tools"] = sorted(set(cur.get("tools") or []) | set(day.get("tools") or []))
    union_days = [local_days[k] for k in sorted(local_days.keys())]
    profile["activityByDay"] = union_days

    activity = profile.get("activity")
    if isinstance(activity, dict):
        activity["days"] = union_days
        activity["activeDays"] = len(
            [d for d in union_days if (d.get("sessions") or 0) + (d.get("commits") or 0) > 0]
        )

    profile["multiDevice"] = {
        "devices": merged["devices"],
        "merged": {
            "sessions": merged["sessions"],
            "activeDays": merged["activeDays"],
            "repoCount": merged["repoCount"],
            "dateRange": merged["dateRange"],
        },
        "mergeRule": (
            "Union across devices, deduped by stable IDs: sessions by ledger key, "
            "commits per repo per day (max across devices, summed over distinct repos). "
            "Scores stay per-device — raw signals never sync."
        ),
    }
    return profile
