"""
cruise_ai.adapters.local_models — Offline / local model runtimes.

Detects Ollama, LM Studio, and llama.cpp-style local model usage from
their own local files (model stores, prompt history, chat files). These
are MODEL-USAGE evidence — they feed the models summary and provenance,
not the session timeline (no per-session boundaries exist locally).

Honesty: everything here is counted from files the runtime itself
writes; absent runtimes simply don't appear. Consent group:
``local_models``.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _log(msg: str) -> None:
    if os.environ.get("CRUISE_AI_VERBOSE"):
        print(f"[scanner] {msg}", file=sys.stderr)


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return None


def _detect_ollama(home: Path) -> dict | None:
    root = home / ".ollama"
    if not root.is_dir():
        return None
    models = []
    manifests = root / "models" / "manifests"
    if manifests.is_dir():
        # .../manifests/<registry>/<namespace>/<model>/<tag>
        try:
            for tag_file in manifests.rglob("*"):
                if tag_file.is_file():
                    parts = tag_file.relative_to(manifests).parts
                    if len(parts) >= 2:
                        models.append(f"{parts[-2]}:{parts[-1]}")
        except OSError:
            pass
    prompt_lines = 0
    history = root / "history"
    if history.is_file():
        try:
            prompt_lines = sum(
                1 for line in history.read_text(errors="replace").splitlines() if line.strip()
            )
        except OSError:
            prompt_lines = 0
    return {
        "runtime": "ollama",
        "label": "Ollama",
        "models": sorted(set(models)),
        "promptHistoryLines": prompt_lines,
        "lastActivity": _mtime_iso(history) if history.is_file() else _mtime_iso(root),
        "note": "Installed models from manifests; CLI prompt count from ~/.ollama/history.",
    }


def _detect_lmstudio(home: Path) -> dict | None:
    roots = [d for d in (home / ".lmstudio", home / ".cache" / "lm-studio") if d.is_dir()]
    if not roots:
        return None
    models = []
    conversations = 0
    last = None
    for root in roots:
        models_dir = root / "models"
        if models_dir.is_dir():
            try:
                for pub in models_dir.iterdir():
                    if pub.is_dir():
                        for m in pub.iterdir():
                            if m.is_dir():
                                models.append(m.name)
            except OSError:
                pass
        conv_dir = root / "conversations"
        if conv_dir.is_dir():
            try:
                for f in conv_dir.glob("*.json"):
                    conversations += 1
                    ts = _mtime_iso(f)
                    if ts and (last is None or ts > last):
                        last = ts
            except OSError:
                pass
    return {
        "runtime": "lmstudio",
        "label": "LM Studio",
        "models": sorted(set(models)),
        "conversations": conversations,
        "lastActivity": last,
        "note": "Downloaded models + local conversation files counted.",
    }


def _detect_llamacpp(home: Path) -> dict | None:
    """llama.cpp has no standard home; the honest detectable trace is a
    GGUF model cache in the common spots. Anything else would be a guess."""
    candidates = [
        home / ".cache" / "llama.cpp",
        home / "models",
    ]
    ggufs: list = []
    for root in candidates:
        if not root.is_dir():
            continue
        try:
            ggufs.extend(f.name for f in root.glob("*.gguf"))
            ggufs.extend(f.name for f in root.glob("*/*.gguf"))
        except OSError:
            continue
    if not ggufs:
        return None
    return {
        "runtime": "llamacpp",
        "label": "llama.cpp (GGUF cache)",
        "models": sorted(set(ggufs))[:20],
        "note": (
            "GGUF model files found; llama.cpp keeps no usage log, so "
            "run counts are insufficient — only the model cache is real."
        ),
    }


def detect_local_models(home: Path | None = None) -> dict | None:
    """All detected local model runtimes, or None when none exist."""
    home = home or Path.home()
    runtimes = [
        r
        for r in (
            _detect_ollama(home),
            _detect_lmstudio(home),
            _detect_llamacpp(home),
        )
        if r
    ]
    if not runtimes:
        return None
    _log(f"Local models: {', '.join(r['runtime'] for r in runtimes)}")
    return {
        "runtimes": runtimes,
        "fidelity": "counts",
        "note": "Local/offline model evidence — model stores + usage files, counted only.",
    }
