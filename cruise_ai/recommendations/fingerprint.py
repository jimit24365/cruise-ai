"""cruise_ai.recommendations.fingerprint — opt-in text fingerprinting.

When enabled, hashes the first N words of each session's first prompt
to detect actual content duplication (not just length similarity).

Privacy:
- Disabled by default — requires explicit opt-in
- Only first 50 words are hashed (never stored as text)
- SHA-256 truncated to 12 chars (collision-resistant but not reversible)
- Hashes stored locally at ~/.cruise-ai/data/fingerprints.json
- Never transmitted, never included in exports
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

# How many words of the first prompt to fingerprint
FINGERPRINT_WORDS = 50


def _fingerprint_path() -> Path:
    """Return path to fingerprint storage file."""
    from cruise_ai.paths import data_dir
    return data_dir() / "fingerprints.json"


def _config_path() -> Path:
    """Return path to recommendation config."""
    from cruise_ai.paths import data_dir
    return data_dir() / "recommend_config.json"


def is_fingerprinting_enabled() -> bool:
    """Check if the user has opted in to fingerprinting."""
    cfg = _config_path()
    if not cfg.exists():
        return False
    try:
        data = json.loads(cfg.read_text())
        return data.get("fingerprinting_enabled", False)
    except (json.JSONDecodeError, OSError):
        return False


def enable_fingerprinting() -> None:
    """Enable fingerprinting (user opt-in)."""
    cfg = _config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data["fingerprinting_enabled"] = True
    cfg.write_text(json.dumps(data, indent=2))


def disable_fingerprinting() -> None:
    """Disable fingerprinting and clear stored hashes."""
    cfg = _config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data["fingerprinting_enabled"] = False
    cfg.write_text(json.dumps(data, indent=2))

    # Clear stored fingerprints
    fp = _fingerprint_path()
    if fp.exists():
        fp.unlink()


def compute_fingerprint(words: list[str]) -> str:
    """Compute a truncated SHA-256 hash of the first N words.

    Args:
        words: List of words from the prompt.

    Returns:
        12-char hex hash string (not reversible to original text).
    """
    text = " ".join(words[:FINGERPRINT_WORDS]).lower().strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def store_fingerprints(session_fingerprints: list[dict[str, str]]) -> None:
    """Store computed fingerprints locally.

    Args:
        session_fingerprints: List of {"session_id": str, "fingerprint": str}
    """
    path = _fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Merge — dedupe by session_id
    existing_ids = {e["session_id"] for e in existing}
    for fp in session_fingerprints:
        if fp["session_id"] not in existing_ids:
            existing.append(fp)

    path.write_text(json.dumps(existing, indent=2))


def load_fingerprints() -> list[dict[str, str]]:
    """Load stored fingerprints."""
    path = _fingerprint_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def detect_duplicates(fingerprints: list[dict[str, str]]) -> dict[str, Any]:
    """Analyze fingerprints for duplicates.

    Returns:
        {
            "total_sessions": int,
            "unique_fingerprints": int,
            "duplicate_groups": [{fingerprint, count, session_ids}],
            "duplicate_rate": float (0-1),
        }
    """
    if not fingerprints:
        return {"total_sessions": 0, "unique_fingerprints": 0, "duplicate_groups": [], "duplicate_rate": 0.0}

    fp_counter: Counter[str] = Counter()
    fp_sessions: dict[str, list[str]] = {}

    for entry in fingerprints:
        fp = entry.get("fingerprint", "")
        sid = entry.get("session_id", "")
        if fp and sid:
            fp_counter[fp] += 1
            if fp not in fp_sessions:
                fp_sessions[fp] = []
            fp_sessions[fp].append(sid)

    total = len(fingerprints)
    unique = len(fp_counter)
    duplicate_groups = [
        {"fingerprint": fp, "count": count, "session_ids": fp_sessions[fp]}
        for fp, count in fp_counter.most_common()
        if count > 1
    ]
    duplicated_sessions = sum(g["count"] for g in duplicate_groups)
    duplicate_rate = duplicated_sessions / total if total > 0 else 0.0

    return {
        "total_sessions": total,
        "unique_fingerprints": unique,
        "duplicate_groups": duplicate_groups,
        "duplicate_rate": duplicate_rate,
    }
