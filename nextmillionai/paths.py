"""
nextmillionai.paths — Central path resolution.

Package assets (static/, docs/) live inside the installed package.
Runtime data (profile.json, scan_results.json) lives at
``~/.nextmillionai/`` (override with ``$NEXTMILLIONAI_HOME``).
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Package-relative paths ────────────────────────────────────────────────────

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
DOCS_DIR = PACKAGE_DIR / "docs"

# ── User-home data directory ──────────────────────────────────────────────────


def user_home() -> Path:
    """Return (and lazily create) the user data root.

    Uses ``$NEXTMILLIONAI_HOME`` if set, otherwise ``~/.nextmillionai/``.
    """
    env = os.environ.get("NEXTMILLIONAI_HOME")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".nextmillionai"
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    """``~/.nextmillionai/data/`` — runtime data directory."""
    d = user_home() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scan_results_path() -> Path:
    """``~/.nextmillionai/data/scan_results.json``."""
    return data_dir() / "scan_results.json"


def profile_path() -> Path:
    """``~/.nextmillionai/data/profile.json``."""
    return data_dir() / "profile.json"


def consent_path() -> Path:
    """``~/.nextmillionai/data/consent.json``."""
    return data_dir() / "consent.json"


def visibility_config_path() -> Path:
    """``~/.nextmillionai/data/visibility.json`` — user visibility preferences."""
    return data_dir() / "visibility.json"


def collection_config_path() -> Path:
    """``~/.nextmillionai/data/collection_config.json`` — collection scope settings."""
    return data_dir() / "collection_config.json"


def config_path() -> Path | None:
    """Locate ``nextmillionai.config.json`` (identity + custom adapters).

    Lookup order — the data home wins, so identity and custom-adapter
    config persist across repo clones, the same as consent / collection /
    profile / history (all the durable state lives under the home dir):

    1. ``~/.nextmillionai/nextmillionai.config.json`` (durable, authoritative)
    2. ``./nextmillionai.config.json`` (cwd — project-local fallback)

    Returns the first that exists, or ``None``.
    """
    home_cfg = user_home() / "nextmillionai.config.json"
    if home_cfg.is_file():
        return home_cfg
    cwd_cfg = Path.cwd() / "nextmillionai.config.json"
    if cwd_cfg.is_file():
        return cwd_cfg
    return None


def cli_invocation() -> str:
    """How to invoke the CLI on THIS machine, for printed hints.

    A clone without pip-install has no `nextmillionai` on PATH — every
    hint must then say `python3 -m nextmillionai` or it teaches users a
    broken command.
    """
    import shutil

    return "nextmillionai" if shutil.which("nextmillionai") else "python3 -m nextmillionai"
