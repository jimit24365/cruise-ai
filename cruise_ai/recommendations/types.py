"""cruise_ai.recommendations.types — shared types for the recommendation system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Recommendation:
    """A single actionable coaching recommendation."""

    category: str  # analytics, token_optimization, skills, project_memory, learning
    headline: str  # one-line summary
    detail: str  # explanation with evidence
    action_type: str  # e.g. "create_steering_doc", "adopt_tool", "split_sessions"
    confidence: int  # 0-100, only emitted when >= 60
    evidence: str  # what data supports this
    priority: str = "medium"  # low / medium / high
    teach_text: str = ""  # explanation for teach mode
    auto_action: str = ""  # what auto mode would do
    savings_estimate: dict[str, Any] = field(default_factory=dict)  # tokens, time, cost


# Minimum confidence to emit a recommendation
CONFIDENCE_THRESHOLD = 60
