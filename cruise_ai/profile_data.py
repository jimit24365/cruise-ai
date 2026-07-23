"""
cruise_ai -- Profile data module.
Loads/saves developer profile from data/profile.json.
Identity fields (name, title, location, etc.) come from cruise_ai.config.json.
"""

import json
import os
import subprocess
import time

from cruise_ai.paths import config_path, profile_path
from cruise_ai.schema import (
    SCHEMA_VERSION,
    TAXONOMY_VERSION,
    build_shareable_profile,
    validate_schema_version,
)

# ── Identity from config file ────────────────────────────────────────────────


def _detect_git_name():
    """Best-effort name from local git config when identity config is blank."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        name = (result.stdout or "").strip()
        return name if result.returncode == 0 and name else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _load_identity():
    """Load identity fields from cruise_ai.config.json if present."""
    cfg_path = config_path()
    if cfg_path and os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            name = (cfg.get("name") or "").strip() or _detect_git_name()
            return {
                "name": name,
                "title": cfg.get("title", ""),
                "experience_years": cfg.get("experience_years"),
                "ai_experience_years": cfg.get("ai_experience_years"),
                "location": cfg.get("location", ""),
                "work_style": cfg.get("work_style", ""),
                "notice_period": cfg.get("notice_period", ""),
                "stack": cfg.get("stack", []),
                "projects": cfg.get("projects", []),
            }
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "name": _detect_git_name(),
        "title": "",
        "experience_years": None,
        "ai_experience_years": None,
        "location": "",
        "work_style": "",
        "notice_period": "",
        "stack": [],
        "projects": [],
    }


# ── Default profile (blank identity, placeholder scores) ─────────────────────


def _build_default_profile():
    identity = _load_identity()
    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        **identity,
        "intent_score": 0,
        "composite": None,
        "dimensions": {
            "signal_clarity": {
                "score": None,
                "evidence": [],
                "name": "Signal Clarity",
                "weight": 0.18,
                "description": "",
            },
            "build_stability": {
                "score": None,
                "evidence": [],
                "name": "Build Stability",
                "weight": 0.22,
                "description": "",
            },
            "decision_weight": {
                "score": None,
                "evidence": [],
                "name": "Decision Weight",
                "weight": 0.18,
                "description": "",
            },
            "recovery_velocity": {
                "score": None,
                "evidence": [],
                "name": "Recovery Velocity",
                "weight": 0.15,
                "description": "",
            },
            "context_command": {
                "score": None,
                "evidence": [],
                "name": "Context Command",
                "weight": 0.12,
                "description": "",
            },
            "orchestration_range": {
                "score": None,
                "evidence": [],
                "name": "Orchestration Range",
                "weight": 0.15,
                "description": "",
            },
        },
        "archetypes": [],
        "titles": [],
        "primaryTitle": None,
        "workMode": {"dominant": {"id": "Hybrid-Manual", "line": ""}, "secondary": []},
        "antiPatterns": [],
        "trajectory": {
            "id": "insufficient",
            "label": "Insufficient Data",
            "description": "Not enough data to determine trajectory.",
        },
        "map": {
            "x": 50.0,
            "y": 50.0,
            "xLabel": ["Explorer", "Architect"],
            "yLabel": ["Solo", "Orchestrator"],
        },
        "growthEdge": {"suggestion": "Connect more AI tools to build your profile.", "context": ""},
        "wrappedStats": {},
        "dataCompleteness": 0.0,
        "tools_detected": [],
        "signals": {},
        "verification": {"source": "unknown", "verified": False},
    }


def load_profile():
    """Load profile from ~/.cruise_ai/data/profile.json if exists, else return default.

    ``CRUISE_AI_PROFILE_PATH`` overrides the location — used by
    `report --demo` to serve the bundled example without touching the
    user's real data."""
    import os as _os

    override = _os.environ.get("CRUISE_AI_PROFILE_PATH")
    if override:
        try:
            with open(override) as f:
                demo = json.load(f)
            validate_schema_version(demo, "profile.json (override)")
            return demo  # bundled example: never overlay local identity
        except (json.JSONDecodeError, OSError):
            pass
    pp = profile_path()
    if pp.is_file():
        try:
            with open(pp) as f:
                profile = json.load(f)
            validate_schema_version(profile, "profile.json")
            # Overlay identity from config (so name/title stay up to date)
            identity = _load_identity()
            for key in (
                "name",
                "title",
                "location",
                "work_style",
                "notice_period",
                "experience_years",
                "ai_experience_years",
                "stack",
                "projects",
            ):
                val = identity.get(key)
                if val:
                    profile[key] = val
            return profile
        except (OSError, json.JSONDecodeError):
            pass
    return _build_default_profile()


def save_profile(profile):
    """Persist profile to disk."""
    profile.setdefault("schema_version", SCHEMA_VERSION)
    pp = profile_path()
    pp.parent.mkdir(parents=True, exist_ok=True)
    with open(pp, "w") as f:
        json.dump(profile, f, indent=2)


def load_scan_results():
    """Load scan_results.json with schema_version validation."""
    from cruise_ai.paths import scan_results_path

    sr = scan_results_path()
    if sr.is_file():
        try:
            with open(sr) as f:
                data = json.load(f)
            validate_schema_version(data, "scan_results.json")
            return data
        except (OSError, json.JSONDecodeError):
            pass
    return None


def build_agent_profile(profile, port=7749, visibility=None):
    """Build a JSON-LD agent-crawlable profile.

    Uses build_shareable_profile() to guarantee no raw/sensitive data leaks
    into the JSON-LD wrapper.  *visibility* is forwarded to
    ``build_shareable_profile()`` to honor user preferences.
    """
    safe = build_shareable_profile(profile, visibility=visibility)
    return {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": safe.get("name") or None,
        "jobTitle": safe.get("title") or None,
        "description": "AI coding profile" + (f" for {safe['name']}" if safe.get("name") else ""),
        "additionalType": "cruise_ai:AIEngineerProfile",
        "cruise_ai": {
            "version": SCHEMA_VERSION,
            "taxonomy_version": safe.get("taxonomy_version", TAXONOMY_VERSION),
            "intent_score": safe.get("intent_score"),
            "composite": safe.get("composite"),
            "dimensions": safe.get("dimensions"),
            "archetypes": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "score": a["score"],
                    "level": a.get("level", {}).get("label", ""),
                }
                for a in safe.get("archetypes", [])
            ],
            "titles": [
                {"id": t["id"], "name": t["name"], "rare": t.get("rare", False)}
                for t in safe.get("titles", [])
            ],
            "primaryTitle": (safe.get("primaryTitle") or {}).get("name"),
            "workMode": safe.get("workMode"),
            "wrappedStats": safe.get("wrappedStats"),
            "stack": safe.get("stack", []),
            "signals": safe.get("signals", {}),
            "projects": safe.get("projects", []),
            "verification": safe.get("verification", {"source": "unknown", "verified": False}),
            "tools_detected": safe.get("tools_detected", []),
            "profile_url": f"http://localhost:{port}/profile",
            "api_url": f"http://localhost:{port}/api/profile.json",
            "last_updated": time.time(),
        },
    }


def build_profile_meta(profile, port=7749, visibility=None):
    """Build lightweight discovery metadata.

    Derives from build_shareable_profile() to guarantee no raw data leaks.
    *visibility* is forwarded to ``build_shareable_profile()``.
    """
    safe = build_shareable_profile(profile, visibility=visibility)
    wm = safe.get("workMode") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": safe.get("taxonomy_version", TAXONOMY_VERSION),
        "name": safe.get("name"),
        "title": safe.get("title"),
        "intent_score": safe.get("intent_score"),
        "composite": safe.get("composite"),
        "primaryTitle": (safe.get("primaryTitle") or {}).get("name"),
        "workMode": (wm.get("dominant") or {}).get("id"),
        "top_archetypes": [a["name"] for a in safe.get("archetypes", [])[:3]],
        "stack": safe.get("stack", [])[:8],
        "tools_detected": safe.get("tools_detected", []),
        "profile_url": f"http://localhost:{port}/profile",
        "api_url": f"http://localhost:{port}/api/profile.json",
    }


def assessment_staleness() -> list:
    """Reasons the saved assessment lags its inputs (empty = fresh).

    Core honesty rule: when an INPUT to the assessment changes (consent
    scope, synced device data), the commands must tell the user their
    numbers predate it — never quietly serve a stale profile as current.
    """
    from cruise_ai.paths import data_dir, profile_path

    reasons = []
    pf = profile_path()
    if not pf.is_file():
        return ["no assessment yet"]
    pf_mtime = pf.stat().st_mtime

    consent = data_dir() / "consent.json"
    if consent.is_file() and consent.stat().st_mtime > pf_mtime:
        reasons.append("consent scope changed since this assessment")

    # Engine moved on since this profile was computed?
    try:
        import json as _json

        from cruise_ai.schema import METHODOLOGY_VERSION

        with open(pf) as f:
            saved = _json.load(f)
        saved_mv = (saved.get("assessment") or {}).get("methodology_version")
        if saved_mv and saved_mv != METHODOLOGY_VERSION:
            reasons.append(
                f"assessment computed by engine {saved_mv}; current is {METHODOLOGY_VERSION}"
            )
    except (OSError, ValueError):
        pass

    sync_dir = data_dir() / "sync" / "devices"
    if sync_dir.is_dir():
        try:
            newest = max((f.stat().st_mtime for f in sync_dir.glob("*.json")), default=0)
            if newest > pf_mtime:
                reasons.append("synced device data arrived since this assessment")
        except OSError:
            pass

    return reasons
