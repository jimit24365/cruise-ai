"""
nextmillionai.adapters.cursor -- Cursor IDE adapter.

Reads AI tracking data from ``~/.cursor/`` (SQLite DB, plans, transcripts)
and produces Session objects plus the legacy raw_data dict.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from nextmillionai.adapters._base import Session
from nextmillionai.scanner import (
    CURSOR_DB_PATH,
    CURSOR_DIR,
    CURSOR_PLANS_DIR,
    CURSOR_PROJECTS_DIR,
    safe_read_text,
    sqlite_query,
    ts_to_iso,
)


def _log(msg: str) -> None:
    if os.environ.get("NEXTMILLIONAI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


class CursorAdapter:
    """Adapter that scans Cursor IDE data sources."""

    def __init__(
        self,
        *,
        cursor_dir: Path | None = None,
        db_path: Path | None = None,
        plans_dir: Path | None = None,
        projects_dir: Path | None = None,
        app_user_dir: Path | None = None,
    ) -> None:
        self._cursor_dir = cursor_dir or CURSOR_DIR
        self._db_path = db_path or CURSOR_DB_PATH
        self._plans_dir = plans_dir or CURSOR_PLANS_DIR
        self._projects_dir = projects_dir or CURSOR_PROJECTS_DIR
        if app_user_dir is None:
            # Late binding so tests can monkeypatch scanner.CURSOR_APP_USER_DIR
            import nextmillionai.scanner as _scanner_mod

            app_user_dir = _scanner_mod.CURSOR_APP_USER_DIR
        self._app_user_dir = app_user_dir
        self._sessions: list[Session] = []
        self._raw: dict | None = None

    @property
    def name(self) -> str:
        return "cursor"

    def detect(self) -> bool:
        return self._cursor_dir.exists() or self._app_user_dir.is_dir()

    # ── Private sub-scanners (unchanged logic from scanner.py) ──

    def _scan_ai_code(self) -> dict | None:
        rows = sqlite_query(
            self._db_path,
            """SELECT source, model, COUNT(*) as cnt,
                      MIN(createdAt) as earliest, MAX(createdAt) as latest
               FROM ai_code_hashes
               GROUP BY source, model
               ORDER BY cnt DESC""",
        )
        if not rows:
            return None

        total_hashes = 0
        by_source: dict[str, int] = {}
        by_model: dict[str, int] = {}
        earliest = None
        latest = None

        for r in rows:
            cnt = r["cnt"]
            total_hashes += cnt
            src = r.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + cnt
            model = r.get("model")
            if model:
                by_model[model] = by_model.get(model, 0) + cnt
            e = r.get("earliest")
            l = r.get("latest")  # noqa: E741
            if e is not None and (earliest is None or e < earliest):
                earliest = e
            if l is not None and (latest is None or l > latest):
                latest = l

        return {
            "totalHashes": total_hashes,
            "bySource": by_source,
            "byModel": by_model,
            "earliest": ts_to_iso(earliest),
            "latest": ts_to_iso(latest),
        }

    def _scan_scored_commits(self) -> dict | None:
        rows = sqlite_query(
            self._db_path,
            """SELECT commitHash, branchName, commitMessage, commitDate,
                      linesAdded, linesDeleted,
                      composerLinesAdded, composerLinesDeleted,
                      humanLinesAdded, humanLinesDeleted,
                      tabLinesAdded, tabLinesDeleted,
                      v2AiPercentage
               FROM scored_commits
               ORDER BY commitDate DESC""",
        )
        if not rows:
            return None

        total_commits = len(rows)
        total_lines_added = 0
        total_ai_lines = 0
        total_human_lines = 0
        total_composer_lines = 0
        total_tab_lines = 0
        ai_percentages: list[float] = []

        for r in rows:
            total_lines_added += r.get("linesAdded") or 0
            composer = r.get("composerLinesAdded") or 0
            tab = r.get("tabLinesAdded") or 0
            total_ai_lines += composer + tab
            total_composer_lines += composer
            total_tab_lines += tab
            total_human_lines += r.get("humanLinesAdded") or 0
            pct = r.get("v2AiPercentage")
            if pct is not None:
                ai_percentages.append(float(pct))

        avg_ai_pct = round(sum(ai_percentages) / len(ai_percentages), 1) if ai_percentages else None

        recent = []
        for r in rows[:10]:
            h = r.get("commitHash", "")
            raw_pct = r.get("v2AiPercentage")
            try:
                pct_val = float(raw_pct) if raw_pct is not None else None
            except (TypeError, ValueError):
                pct_val = None
            recent.append(
                {
                    "hash": h[:8] if h else "",
                    "message": (r.get("commitMessage") or "")[:120],
                    "date": r.get("commitDate"),
                    "aiPct": pct_val,
                }
            )

        # Full per-commit (date, aiPct) series for the activity timeline —
        # dates and ratios only, no commit messages
        commit_days = []
        for r in rows:
            cdate = r.get("commitDate")
            if not cdate:
                continue
            raw_pct = r.get("v2AiPercentage")
            try:
                pct_val = float(raw_pct) if raw_pct is not None else None
            except (TypeError, ValueError):
                pct_val = None
            commit_days.append({"date": cdate, "aiPct": pct_val})

        return {
            "totalCommits": total_commits,
            "totalLinesAdded": total_lines_added,
            "totalAiLines": total_ai_lines,
            "totalComposerLines": total_composer_lines,
            "totalTabLines": total_tab_lines,
            "totalHumanLines": total_human_lines,
            "avgAiPercentage": avg_ai_pct,
            "recentCommits": recent,
            "commitDays": commit_days,
        }

    def _scan_conversations(self) -> dict | None:
        rows = sqlite_query(
            self._db_path,
            """SELECT conversationId, title, tldr, model, mode, updatedAt
               FROM conversation_summaries
               ORDER BY updatedAt DESC
               LIMIT 500""",
        )
        if not rows:
            return None

        models: dict[str, int] = {}
        modes: dict[str, int] = {}
        for r in rows:
            m = r.get("model")
            if m:
                models[m] = models.get(m, 0) + 1
            mode = r.get("mode")
            if mode:
                modes[mode] = modes.get(mode, 0) + 1

        recent_topics = []
        for r in rows[:15]:
            tldr = r.get("tldr") or ""
            recent_topics.append(
                {
                    "title": r.get("title"),
                    "tldr": tldr[:200],
                    "model": r.get("model"),
                    "mode": r.get("mode"),
                }
            )

        return {
            "totalConversations": len(rows),
            "models": models,
            "modes": modes,
            "recentTopics": recent_topics,
        }

    def _scan_plans(self) -> dict | None:
        if not self._plans_dir.exists():
            return None

        try:
            plan_files = sorted(self._plans_dir.glob("*.plan.md"))
        except Exception:
            return None

        if not plan_files:
            return None

        plans = []
        for pf in plan_files[:100]:
            content = safe_read_text(pf)
            if content is None:
                continue
            title = pf.stem.replace(".plan", "").replace("_", " ")
            title = re.sub(r"\s+[a-f0-9]{8}$", "", title)
            line_count = content.count("\n") + 1
            plans.append(
                {
                    "file": pf.name,
                    "title": title,
                    "lineCount": line_count,
                    "sizeBytes": len(content.encode("utf-8")),
                }
            )

        return {
            "totalPlans": len(plan_files),
            "plans": plans,
        }

    def _scan_transcripts(self) -> dict | None:
        if not self._projects_dir.exists():
            return None

        total_sessions = 0
        total_size_bytes = 0
        projects = []

        try:
            project_dirs = sorted(self._projects_dir.iterdir())
        except Exception:
            return None

        for proj_dir in project_dirs:
            if not proj_dir.is_dir():
                continue
            tx_dir = proj_dir / "agent-transcripts"
            if not tx_dir.exists():
                continue

            try:
                session_dirs = [d for d in tx_dir.iterdir() if d.is_dir()]
            except Exception:
                continue

            proj_size = 0
            for sd in session_dirs:
                try:
                    for f in sd.iterdir():
                        try:
                            proj_size += f.stat().st_size
                        except Exception:
                            pass
                except Exception:
                    pass

            session_count = len(session_dirs)
            total_sessions += session_count
            total_size_bytes += proj_size

            if session_count > 0:
                readable = proj_dir.name
                projects.append(
                    {
                        "project": readable,
                        "sessions": session_count,
                        "sizeKB": round(proj_size / 1024, 1),
                    }
                )

        if total_sessions == 0:
            return None

        return {
            "totalSessions": total_sessions,
            "totalSizeKB": round(total_size_bytes / 1024, 1),
            "projects": projects,
        }

    # ── Public interface ──

    # ── Composer sessions: the REAL Cursor history (state.vscdb) ──────
    # Three storage generations, oldest Cursor → current:
    #   1. workspace ItemTable 'workbench.panel.aichat.view.aichat.chatdata'
    #      (chat tabs, lastSendTime)
    #   2. workspace ItemTable 'composer.composerData' → allComposers[]
    #      (createdAt/lastUpdatedAt; later versions migrate these out)
    #   3. global cursorDiskKV 'composerData:<id>' (current; createdAt/
    #      lastUpdatedAt/isAgentic) + 'bubbleId:<id>:<n>' message rows
    # All reads are read-only sqlite; dedupe by composerId (global wins).

    def _scan_composer_sessions(self) -> tuple:
        import json as _json
        import sqlite3
        from datetime import datetime, timezone

        user_dir = self._app_user_dir
        if not user_dir or not user_dir.is_dir():
            return [], None

        found: dict = {}  # composerId -> session info (global wins)
        gen_counts = {"global": 0, "workspace": 0, "aichat": 0}

        def _to_dt(ms):
            try:
                return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)
            except (ValueError, TypeError, OSError, OverflowError):
                return None

        def _add(cid, created_ms, updated_ms, source, project=None, msgs=0, agentic=False):
            # First add wins; the global store is scanned first, so a
            # migrated composer never double-counts from a workspace db
            if not cid or cid in found:
                return
            started = _to_dt(created_ms)
            if started is None:
                return
            ended = started
            if updated_ms:
                # Cap the estimator at 8h like every duration in the
                # pipeline — a tab reopened days later is not one
                # multi-day session
                capped = min(float(updated_ms), float(created_ms) + 8 * 3600 * 1000)
                ended = _to_dt(capped) or started
            found[cid] = {
                "started": started,
                "ended": ended,
                "source": source,
                "project": project,
                "msgs": msgs,
                "agentic": agentic,
            }
            gen_counts[source] += 1

        # ── Generation 3 (current): global cursorDiskKV ──
        gdb = user_dir / "globalStorage" / "state.vscdb"
        if gdb.is_file():
            try:
                con = sqlite3.connect(f"file:{gdb}?mode=ro", uri=True, timeout=5)
                try:
                    bubble_counts: dict = {}
                    try:
                        for cid, n in con.execute(
                            "SELECT substr(key, 10, 36), COUNT(*) FROM cursorDiskKV "
                            "WHERE key LIKE 'bubbleId:%' GROUP BY substr(key, 10, 36)"
                        ):
                            bubble_counts[cid] = n
                    except sqlite3.Error:
                        pass
                    try:
                        rows = con.execute(
                            "SELECT substr(key, 14), "
                            "json_extract(value,'$.createdAt'), "
                            "json_extract(value,'$.lastUpdatedAt'), "
                            "json_extract(value,'$.isAgentic') "
                            "FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
                        ).fetchall()
                    except sqlite3.Error:
                        # Older sqlite without json1: load + parse (slower)
                        rows = []
                        for key, value in con.execute(
                            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
                        ):
                            try:
                                d = _json.loads(value)
                            except (_json.JSONDecodeError, TypeError):
                                continue
                            rows.append(
                                (
                                    key[len("composerData:") :],
                                    d.get("createdAt"),
                                    d.get("lastUpdatedAt"),
                                    d.get("isAgentic"),
                                )
                            )
                    for cid, created, updated, agentic in rows:
                        _add(
                            cid,
                            created,
                            updated,
                            "global",
                            msgs=bubble_counts.get(cid, 0),
                            agentic=bool(agentic),
                        )
                finally:
                    con.close()
            except sqlite3.Error:
                pass

        # ── Generations 1+2 (older Cursor): per-workspace state.vscdb ──
        ws_root = user_dir / "workspaceStorage"
        if ws_root.is_dir():
            try:
                ws_dirs = sorted(d for d in ws_root.iterdir() if d.is_dir())[:300]
            except OSError:
                ws_dirs = []
            for ws in ws_dirs:
                wdb = ws / "state.vscdb"
                if not wdb.is_file():
                    continue
                project = None
                meta = ws / "workspace.json"
                if meta.is_file():
                    try:
                        folder = (_json.loads(meta.read_text()) or {}).get("folder") or ""
                        if folder.startswith("file://"):
                            project = folder[len("file://") :]
                    except (_json.JSONDecodeError, OSError):
                        pass
                try:
                    con = sqlite3.connect(f"file:{wdb}?mode=ro", uri=True, timeout=2)
                except sqlite3.Error:
                    continue
                try:
                    # Gen 2: composer.composerData → allComposers[]
                    try:
                        row = con.execute(
                            "SELECT value FROM ItemTable WHERE key='composer.composerData'"
                        ).fetchone()
                    except sqlite3.Error:
                        row = None
                    if row and row[0]:
                        try:
                            data = _json.loads(row[0])
                            for comp in data.get("allComposers") or []:
                                _add(
                                    comp.get("composerId"),
                                    comp.get("createdAt"),
                                    comp.get("lastUpdatedAt"),
                                    "workspace",
                                    project=project,
                                )
                        except (_json.JSONDecodeError, TypeError):
                            pass
                    # Gen 1: aichat chat tabs
                    try:
                        row = con.execute(
                            "SELECT value FROM ItemTable WHERE "
                            "key='workbench.panel.aichat.view.aichat.chatdata'"
                        ).fetchone()
                    except sqlite3.Error:
                        row = None
                    if row and row[0]:
                        try:
                            data = _json.loads(row[0])
                            for tab in data.get("tabs") or []:
                                ts = tab.get("lastSendTime")
                                tab_id = tab.get("tabId")
                                if ts and tab_id:
                                    _add(
                                        f"aichat:{ws.name[:8]}:{tab_id}",
                                        ts,
                                        ts,
                                        "aichat",
                                        project=project,
                                        msgs=len(tab.get("bubbles") or []),
                                    )
                        except (_json.JSONDecodeError, TypeError):
                            pass
                finally:
                    con.close()

        if not found:
            return [], None

        sessions = []
        total_min = 0.0
        earliest = latest = None
        agentic_n = 0
        for cid, info in found.items():
            dur_min = (info["ended"] - info["started"]).total_seconds() / 60.0
            total_min += max(dur_min, 0)
            iso = info["started"].date().isoformat()
            if earliest is None or iso < earliest:
                earliest = iso
            if latest is None or iso > latest:
                latest = iso
            if info["agentic"]:
                agentic_n += 1
            sessions.append(
                Session(
                    tool="cursor",
                    session_id=f"composer:{cid}",
                    project_path=info["project"],
                    started_at=info["started"],
                    ended_at=info["ended"],
                    user_msgs=0,  # roles not parsed (kept cheap + honest)
                    assistant_msgs=0,
                    extras={
                        "messages": info["msgs"],
                        "agentic": info["agentic"],
                        "source": info["source"],
                    },
                )
            )

        summary = {
            "sessions": len(sessions),
            "estimatedHours": round(total_min / 60.0, 1),
            "agentic": agentic_n,
            "earliest": earliest,
            "latest": latest,
            "byGeneration": {k: v for k, v in gen_counts.items() if v},
            "note": (
                "Composer history from Cursor's own state.vscdb (read-only): "
                "real timestamps across storage generations; duration = "
                "created→lastUpdated capped at 8h per session."
            ),
        }
        return sessions, summary

    def scan(self, project_filter: str | None = None) -> list[Session]:
        if not self.detect():
            _log("Cursor IDE: ~/.cursor/ not found, skipping")
            self._sessions = []
            self._raw = None
            return []

        _log("Cursor IDE: scanning...")

        ai_code = self._scan_ai_code()
        scored_commits = self._scan_scored_commits()
        conversations = self._scan_conversations()
        plans = self._scan_plans()
        transcripts = self._scan_transcripts()
        composer_sessions, composer_summary = self._scan_composer_sessions()

        parts = []
        if composer_summary:
            parts.append(
                f"{composer_summary['sessions']} composer sessions "
                f"({composer_summary['estimatedHours']}h)"
            )
        if ai_code:
            parts.append(f"{ai_code['totalHashes']} code blocks")
        if scored_commits:
            parts.append(f"{scored_commits['totalCommits']} scored commits")
        if conversations:
            parts.append(f"{conversations['totalConversations']} conversations")
        if plans:
            parts.append(f"{plans['totalPlans']} plans")
        if transcripts:
            parts.append(f"{transcripts['totalSessions']} transcript sessions")

        if not parts:
            _log("Cursor IDE: no data found")
            self._sessions = []
            self._raw = None
            return []

        _log(f"Cursor IDE: {', '.join(parts)}")

        self._raw = {
            "ai_code": ai_code,
            "scored_commits": scored_commits,
            "conversations": conversations,
            "plans": plans,
            "transcripts": transcripts,
            "composerSessions": composer_summary,
        }

        # Composer sessions ARE the real dated history — they feed the
        # ledger, hours, span, and activity. The synthetic conversation
        # placeholders below describe the same chats without timestamps,
        # so they're skipped whenever composer data exists (no double
        # counting; the conversations raw dict still powers models/modes).
        sessions: list[Session] = list(composer_sessions)

        # Build Session objects from transcripts (each directory = one session).
        # Transcript dir names are lossy path ENCODINGS ("Users-apple-Docs-x"),
        # not real paths — never emit them as project_path (they would leak
        # into git scanning and the Work tab as phantom projects).
        if transcripts:
            for proj in transcripts.get("projects", []):
                proj_name = proj.get("project", "unknown")
                for i in range(proj.get("sessions", 0)):
                    sessions.append(
                        Session(
                            tool="cursor",
                            session_id=f"{proj_name}_tx_{i}",
                            project_path=None,
                        )
                    )

        # Also build sessions from conversations — only when no composer
        # history exists (they're the same chats, summarized)
        if conversations and not composer_sessions:
            for topic in conversations.get("recentTopics", []):
                models = []
                if topic.get("model"):
                    models = [topic["model"]]
                sessions.append(
                    Session(
                        tool="cursor",
                        session_id=f"convo_{id(topic)}",
                        models=models,
                        extras={"mode": topic.get("mode")},
                    )
                )

        self._sessions = sessions
        return sessions

    def raw_data(self) -> dict | None:
        return self._raw
