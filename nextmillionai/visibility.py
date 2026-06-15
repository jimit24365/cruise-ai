"""
nextmillionai.visibility -- User-controlled visibility config.

Persistent config at ``~/.nextmillionai/data/visibility.json`` lets users
choose which profile sections appear on the page and/or in the shareable
profile, hide specific projects, and hide specific dimensions.

This module never changes scoring -- it only controls what is *shown*.
"""

from __future__ import annotations

import json
from pathlib import Path

from nextmillionai.paths import visibility_config_path

# ── Whitelists ───────────────────────────────────────────────────────────────

VALID_SECTION_IDS: frozenset[str] = frozenset(
    {
        "dimensions",
        "archetypes",
        "titles",
        "workMode",
        "antiPatterns",
        "trajectory",
        "map",
        "growthEdge",
        "wrappedStats",
        "activityByDay",
        "stackSummary",
        "modelsSummary",
        "signals",
        # Growth areas: the one section that defaults to PRIVATE — the
        # user opts in per the report toggle before it enters any share
        "growthAreas",
    }
)

# Sections whose includeInShareable defaults to False (explicit opt-in)
PRIVATE_BY_DEFAULT_SECTIONS: frozenset[str] = frozenset({"growthAreas"})

VALID_DIMENSION_IDS: frozenset[str] = frozenset(
    {
        "signal_clarity",
        "build_stability",
        "decision_weight",
        "recovery_velocity",
        "context_command",
        "orchestration_range",
    }
)

# Keys allowed at the top level of the config JSON.
_VALID_TOP_KEYS: frozenset[str] = frozenset(
    {
        "sections",
        "hiddenProjects",
        "hiddenDimensions",
    }
)

# ── Defaults ─────────────────────────────────────────────────────────────────


def default_visibility_config() -> dict:
    """Return a config where everything is visible."""
    return {
        "sections": {
            sid: {
                "showOnPage": True,
                "includeInShareable": sid not in PRIVATE_BY_DEFAULT_SECTIONS,
            }
            for sid in sorted(VALID_SECTION_IDS)
        },
        "hiddenProjects": [],
        "hiddenDimensions": [],
    }


# ── Persistence ──────────────────────────────────────────────────────────────


def load_visibility_config() -> dict:
    """Load config from disk, returning defaults if the file is absent or invalid."""
    p = visibility_config_path()
    if p.is_file():
        try:
            with open(p) as f:
                raw = json.load(f)
            # Merge with defaults so new section IDs get sane values
            return _merge_with_defaults(raw)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return default_visibility_config()


def save_visibility_config(config: dict) -> Path:
    """Validate and persist *config* to disk.  Returns the file path."""
    errors = validate_visibility_config(config)
    if errors:
        raise ValueError("; ".join(errors))
    merged = _merge_with_defaults(config)
    p = visibility_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(merged, f, indent=2)
    return p


# ── Validation ───────────────────────────────────────────────────────────────


def validate_visibility_config(config: dict) -> list[str]:
    """Return a list of human-readable error strings.  Empty list = valid."""
    errors: list[str] = []

    if not isinstance(config, dict):
        return ["config must be a JSON object"]

    # Reject unknown top-level keys
    unknown = set(config.keys()) - _VALID_TOP_KEYS
    if unknown:
        errors.append(f"unknown keys: {sorted(unknown)}")

    # sections
    sections = config.get("sections")
    if sections is not None:
        if not isinstance(sections, dict):
            errors.append("sections must be an object")
        else:
            bad_ids = set(sections.keys()) - VALID_SECTION_IDS
            if bad_ids:
                errors.append(f"invalid section IDs: {sorted(bad_ids)}")
            for sid, flags in sections.items():
                if sid in VALID_SECTION_IDS:
                    if not isinstance(flags, dict):
                        errors.append(f"sections.{sid} must be an object")
                    else:
                        for fk, fv in flags.items():
                            if fk not in ("showOnPage", "includeInShareable"):
                                errors.append(f"sections.{sid}: unknown flag '{fk}'")
                            elif not isinstance(fv, bool):
                                errors.append(f"sections.{sid}.{fk} must be boolean")

    # hiddenProjects
    hp = config.get("hiddenProjects")
    if hp is not None:
        if not isinstance(hp, list):
            errors.append("hiddenProjects must be an array")
        elif not all(isinstance(p, str) for p in hp):
            errors.append("hiddenProjects entries must be strings")

    # hiddenDimensions
    hd = config.get("hiddenDimensions")
    if hd is not None:
        if not isinstance(hd, list):
            errors.append("hiddenDimensions must be an array")
        else:
            bad_dims = set(hd) - VALID_DIMENSION_IDS
            if bad_dims:
                errors.append(f"invalid dimension IDs: {sorted(bad_dims)}")

    return errors


# ── Internal helpers ─────────────────────────────────────────────────────────


def _merge_with_defaults(raw: dict) -> dict:
    """Merge a (possibly partial) config with defaults."""
    defaults = default_visibility_config()
    merged: dict = {}

    # sections: start from defaults, overlay provided values
    merged_sections = dict(defaults["sections"])
    for sid, flags in (raw.get("sections") or {}).items():
        if sid in VALID_SECTION_IDS and isinstance(flags, dict):
            merged_flags = dict(merged_sections[sid])
            if "showOnPage" in flags and isinstance(flags["showOnPage"], bool):
                merged_flags["showOnPage"] = flags["showOnPage"]
            if "includeInShareable" in flags and isinstance(flags["includeInShareable"], bool):
                merged_flags["includeInShareable"] = flags["includeInShareable"]
            merged_sections[sid] = merged_flags
    merged["sections"] = merged_sections

    # hiddenProjects
    hp = raw.get("hiddenProjects")
    if isinstance(hp, list) and all(isinstance(p, str) for p in hp):
        merged["hiddenProjects"] = hp
    else:
        merged["hiddenProjects"] = defaults["hiddenProjects"]

    # hiddenDimensions
    hd = raw.get("hiddenDimensions")
    if isinstance(hd, list) and all(isinstance(d, str) and d in VALID_DIMENSION_IDS for d in hd):
        merged["hiddenDimensions"] = hd
    else:
        merged["hiddenDimensions"] = defaults["hiddenDimensions"]

    return merged
