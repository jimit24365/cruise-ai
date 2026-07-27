"""cruise_ai.recommendations.calibration — threshold calibration from feedback data.

Analyzes historical feedback + longitudinal data to suggest optimal
confidence thresholds per detector. High 'useful' rates suggest we can
be more aggressive; high 'not_useful' rates suggest we should be more conservative.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    """Return path to calibration config file."""
    from cruise_ai.paths import data_dir
    return data_dir() / "calibration.json"


def _load_calibration_config() -> dict[str, Any]:
    """Load current calibration config."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_calibration_config(config: dict[str, Any]) -> None:
    """Persist calibration config."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))


def calibrate_thresholds(
    feedback_data: list[dict[str, Any]],
    longitudinal_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Compute optimal confidence thresholds based on feedback history.

    For each action_type with sufficient feedback (>10 entries):
    - If 'useful' rate > 80%: suggest lowering threshold (more aggressive)
    - If 'not_useful' rate > 50%: suggest raising threshold (more conservative)

    Args:
        feedback_data: List of feedback entries from feedback._load_feedback().
        longitudinal_data: Dict from longitudinal._load_data().

    Returns:
        Dict mapping action_type to:
        {
            "current_threshold": int,
            "suggested_threshold": int,
            "evidence": str,
        }
    """
    from cruise_ai.recommendations.types import CONFIDENCE_THRESHOLD

    if not feedback_data:
        return {}

    # Group feedback by action_type
    by_action: dict[str, list[dict[str, Any]]] = {}
    for entry in feedback_data:
        action_type = entry.get("action_type", "")
        if not action_type:
            continue
        if action_type not in by_action:
            by_action[action_type] = []
        by_action[action_type].append(entry)

    # Load existing calibration for current thresholds
    existing = _load_calibration_config()

    results: dict[str, dict[str, Any]] = {}

    for action_type, entries in by_action.items():
        # Require minimum sample size
        if len(entries) <= 10:
            continue

        total = len(entries)
        useful_count = sum(
            1 for e in entries if e.get("response") in ("acted", "useful")
        )
        not_useful_count = sum(
            1 for e in entries if e.get("response") == "not_useful"
        )

        useful_rate = useful_count / total
        not_useful_rate = not_useful_count / total

        # Current threshold: from config or default
        current = existing.get(action_type, {}).get(
            "threshold", CONFIDENCE_THRESHOLD
        )

        suggested = current
        evidence = ""

        if useful_rate > 0.80:
            # High usefulness — lower threshold to show more
            suggested = max(40, current - 10)
            evidence = (
                f"Useful rate {useful_rate:.0%} ({useful_count}/{total}) — "
                f"users find this detector valuable, lower threshold to surface more"
            )
        elif not_useful_rate > 0.50:
            # High noise — raise threshold to show fewer
            suggested = min(90, current + 10)
            evidence = (
                f"Not-useful rate {not_useful_rate:.0%} ({not_useful_count}/{total}) — "
                f"too noisy, raise threshold to reduce false positives"
            )
        else:
            # Stable — keep current
            evidence = (
                f"Useful rate {useful_rate:.0%}, not-useful rate {not_useful_rate:.0%} "
                f"({total} entries) — threshold appropriate"
            )

        # Factor in longitudinal improvement trends
        outcomes = longitudinal_data.get("outcomes", [])
        relevant_outcomes = [
            o for o in outcomes if o.get("action_type") == action_type
        ]
        if relevant_outcomes:
            improved = sum(1 for o in relevant_outcomes if o.get("improved", False))
            if improved > len(relevant_outcomes) * 0.7:
                # Strong improvement signal — slightly lower threshold
                suggested = max(40, suggested - 5)
                evidence += f" | Longitudinal: {improved}/{len(relevant_outcomes)} improved"

        results[action_type] = {
            "current_threshold": current,
            "suggested_threshold": suggested,
            "evidence": evidence,
        }

    return results


def apply_calibration(calibration_results: dict[str, dict[str, Any]]) -> None:
    """Persist adjusted thresholds to calibration config.

    Updates the local config with suggested thresholds from calibrate_thresholds().

    Args:
        calibration_results: Output of calibrate_thresholds().
    """
    if not calibration_results:
        return

    config = _load_calibration_config()

    for action_type, result in calibration_results.items():
        suggested = result.get("suggested_threshold")
        if suggested is None:
            continue
        if action_type not in config:
            config[action_type] = {}
        config[action_type]["threshold"] = suggested
        config[action_type]["evidence"] = result.get("evidence", "")

    _save_calibration_config(config)
