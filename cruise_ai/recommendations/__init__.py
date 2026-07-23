"""cruise_ai.recommendations — actionable coaching engine.

Analyzes scan results and profiles to produce evidence-based
recommendations across categories: analytics, token optimization,
skill discovery, project memory, and learning.
"""

from cruise_ai.recommendations.types import Recommendation
from cruise_ai.recommendations.engine import recommend

__all__ = ["recommend", "Recommendation"]
