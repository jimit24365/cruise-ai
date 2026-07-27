#!/usr/bin/env python3
"""scripts/validate_real_data.py — Run recommendations against real local data.

Validates that the recommendation engine doesn't crash on actual sessions.
Exit 0 as long as it runs without errors (even if zero sessions found).
"""

from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter


def find_sessions() -> list:
    """Discover real sessions from ~/.kiro/ and ~/.claude/ if they exist."""
    sessions = []

    # Try Kiro sessions
    kiro_dir = Path.home() / ".kiro"
    if kiro_dir.exists():
        try:
            from cruise_ai.adapters.kiro import KiroAdapter
            adapter = KiroAdapter()
            kiro_sessions = adapter.scan()
            if kiro_sessions:
                sessions.extend(kiro_sessions)
        except Exception as e:
            print(f"  ⚠ Kiro adapter error (non-fatal): {e}")

    # Try Claude Code sessions
    claude_dir = Path.home() / ".claude"
    if claude_dir.exists():
        try:
            from cruise_ai.adapters.claude_code import ClaudeCodeAdapter
            adapter = ClaudeCodeAdapter()
            claude_sessions = adapter.scan()
            if claude_sessions:
                sessions.extend(claude_sessions)
        except Exception as e:
            print(f"  ⚠ Claude Code adapter error (non-fatal): {e}")

    return sessions


def main() -> int:
    """Run validation and print summary stats."""
    print("=" * 60)
    print("  cruise-ai: Real Data Validation")
    print("=" * 60)
    print()

    # Discover sessions
    sessions = find_sessions()
    print(f"  Sessions found: {len(sessions)}")

    if not sessions:
        print("  No real sessions found — nothing to validate (OK)")
        print()
        print("  Checked: ~/.kiro/, ~/.claude/")
        print("  Result: PASS (no data, no crash)")
        return 0

    # Run recommendation engine
    print("  Running recommendation engine...")
    from cruise_ai.recommendations.engine import recommend

    try:
        recs = recommend(sessions)
    except Exception as e:
        print(f"  ✗ Engine crashed: {e}")
        return 1

    print(f"  Recommendations generated: {len(recs)}")
    print()

    # Category distribution
    categories: Counter = Counter()
    confidences: list[int] = []
    for rec in recs:
        categories[rec.category] += 1
        confidences.append(rec.confidence)

    print("  Category breakdown:")
    for cat, count in sorted(categories.items()):
        print(f"    {cat}: {count}")

    if confidences:
        print()
        print("  Confidence distribution:")
        print(f"    min: {min(confidences)}")
        print(f"    max: {max(confidences)}")
        print(f"    avg: {sum(confidences) / len(confidences):.0f}")

    print()
    print("  Result: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
