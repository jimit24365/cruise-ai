"""cruise_ai.recommendations.personalization — adaptive thresholds and pattern mining.

Instead of fixed thresholds, computes per-user baselines and triggers
recommendations only when metrics deviate significantly from the user's
own patterns. Also mines workflow sequences for friction points and
detects usage trends over time.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

from cruise_ai.recommendations.types import Recommendation


# ─── Relative Thresholds ─────────────────────────────────────────────────────


def calculate_baseline(sessions: list[Any]) -> dict[str, Any]:
    """Compute per-user baseline statistics from session history.

    Args:
        sessions: List of Session-like objects.

    Returns:
        Dict with avg/stdev for prompt_length, session_tokens, tools_per_session.
    """
    if not sessions:
        return {
            "avg_prompt_length": 0.0,
            "stdev_prompt_length": 0.0,
            "avg_session_tokens": 0.0,
            "stdev_session_tokens": 0.0,
            "avg_tools_per_session": 0.0,
            "stdev_tools_per_session": 0.0,
            "sample_size": 0,
        }

    prompt_lengths: list[float] = []
    session_tokens: list[float] = []
    tools_per_session: list[float] = []

    for s in sessions:
        # Prompt lengths (word counts)
        words = getattr(s, "prompt_word_counts", None) or []
        if words:
            avg_words = sum(words) / len(words)
            prompt_lengths.append(avg_words)

        # Tokens per session
        user_msgs = getattr(s, "user_msgs", 0) or 0
        assistant_msgs = getattr(s, "assistant_msgs", 0) or 0
        token_est = (user_msgs + assistant_msgs) * 500  # rough estimate
        session_tokens.append(float(token_est))

        # Tools per session
        tool_calls = getattr(s, "tool_calls_by_type", None) or {}
        tools_per_session.append(float(sum(tool_calls.values())) if tool_calls else 0.0)

    def _safe_stdev(data: list[float]) -> float:
        if len(data) < 2:
            return 0.0
        try:
            return statistics.stdev(data)
        except statistics.StatisticsError:
            return 0.0

    def _safe_mean(data: list[float]) -> float:
        if not data:
            return 0.0
        return statistics.mean(data)

    return {
        "avg_prompt_length": round(_safe_mean(prompt_lengths), 2),
        "stdev_prompt_length": round(_safe_stdev(prompt_lengths), 2),
        "avg_session_tokens": round(_safe_mean(session_tokens), 2),
        "stdev_session_tokens": round(_safe_stdev(session_tokens), 2),
        "avg_tools_per_session": round(_safe_mean(tools_per_session), 2),
        "stdev_tools_per_session": round(_safe_stdev(tools_per_session), 2),
        "sample_size": len(sessions),
    }


def _check_threshold_violations(sessions: list[Any], baseline: dict[str, Any]) -> list[Recommendation]:
    """Check if recent sessions exceed the user's own baseline by >1.5 stdev.

    Uses the most recent 20% of sessions (minimum 1) as 'recent' window.
    """
    recs: list[Recommendation] = []
    if baseline["sample_size"] < 5:
        return recs  # need enough history to compute meaningful baselines

    # Compare recent sessions against baseline
    recent_count = max(1, len(sessions) // 5)
    recent = sessions[-recent_count:]
    recent_baseline = calculate_baseline(recent)

    # Check prompt length deviation
    threshold_prompt = baseline["avg_prompt_length"] + 1.5 * baseline["stdev_prompt_length"]
    if (
        baseline["stdev_prompt_length"] > 0
        and recent_baseline["avg_prompt_length"] > threshold_prompt
    ):
        recs.append(Recommendation(
            category="personalization",
            headline="Your recent prompts are significantly longer than usual",
            detail=(
                f"Recent avg: {recent_baseline['avg_prompt_length']:.0f} words vs "
                f"your baseline: {baseline['avg_prompt_length']:.0f} words "
                f"(threshold: {threshold_prompt:.0f}). Consider using structured prompts "
                f"or templates to be more concise."
            ),
            action_type="optimize_prompts",
            confidence=70,
            evidence=(
                f"Baseline from {baseline['sample_size']} sessions; "
                f"recent {recent_count} sessions exceed 1.5σ"
            ),
            priority="medium",
            trust_level="observed",
            teach_text=(
                "Longer prompts don't always mean better results. "
                "Your own history shows you typically communicate effectively "
                "with shorter prompts."
            ),
        ))

    # Check token usage deviation
    threshold_tokens = baseline["avg_session_tokens"] + 1.5 * baseline["stdev_session_tokens"]
    if (
        baseline["stdev_session_tokens"] > 0
        and recent_baseline["avg_session_tokens"] > threshold_tokens
    ):
        recs.append(Recommendation(
            category="personalization",
            headline="Recent sessions are burning more tokens than your norm",
            detail=(
                f"Recent avg: {recent_baseline['avg_session_tokens']:,.0f} tokens/session vs "
                f"your baseline: {baseline['avg_session_tokens']:,.0f}. "
                f"Check if tasks have grown in complexity or if there's inefficiency."
            ),
            action_type="reduce_token_usage",
            confidence=68,
            evidence=(
                f"Baseline from {baseline['sample_size']} sessions; "
                f"recent {recent_count} sessions exceed 1.5σ"
            ),
            priority="medium",
            trust_level="observed",
        ))

    # Check tool usage deviation
    threshold_tools = baseline["avg_tools_per_session"] + 1.5 * baseline["stdev_tools_per_session"]
    if (
        baseline["stdev_tools_per_session"] > 0
        and recent_baseline["avg_tools_per_session"] > threshold_tools
    ):
        recs.append(Recommendation(
            category="personalization",
            headline="You're invoking more tool calls than usual",
            detail=(
                f"Recent avg: {recent_baseline['avg_tools_per_session']:.1f} tools/session vs "
                f"your baseline: {baseline['avg_tools_per_session']:.1f}. "
                f"This could indicate exploration (good) or thrashing (bad)."
            ),
            action_type="review_tool_usage",
            confidence=65,
            evidence=(
                f"Baseline from {baseline['sample_size']} sessions; "
                f"recent {recent_count} sessions exceed 1.5σ"
            ),
            priority="low",
            trust_level="observed",
        ))

    return recs


# ─── Pattern Mining ──────────────────────────────────────────────────────────


def mine_workflow_patterns(sessions: list[Any]) -> list[dict[str, Any]]:
    """Detect common tool/command sequences across sessions.

    A pattern is a sequence of 2-4 tools/commands that appears >5 times.

    Args:
        sessions: List of Session-like objects.

    Returns:
        List of pattern dicts with sequence, frequency, avg_duration, friction_score.
    """
    if not sessions:
        return []

    # Extract tool sequences from each session
    sequences: list[list[str]] = []
    durations: dict[tuple[str, ...], list[float]] = defaultdict(list)

    for s in sessions:
        tool_calls = getattr(s, "tool_calls_by_type", None) or {}
        extras = getattr(s, "extras", None) or {}

        # Build a sequence of actions from available data
        seq: list[str] = []
        commands = extras.get("commands", [])
        if commands:
            seq.extend(str(c) for c in commands[:20])  # cap at 20
        elif tool_calls:
            # Use tool call types as sequence
            for tool_name, count in tool_calls.items():
                seq.extend([tool_name] * min(count, 5))

        if seq:
            sequences.append(seq)

        # Estimate session duration
        started = getattr(s, "started_at", None)
        ended = getattr(s, "ended_at", None)
        duration = 0.0
        if started and ended:
            try:
                duration = (ended - started).total_seconds()
            except (TypeError, AttributeError):
                pass

        # Extract n-grams (2 to 4 items)
        for n in range(2, 5):
            for i in range(len(seq) - n + 1):
                ngram = tuple(seq[i:i + n])
                durations[ngram].append(duration / max(len(seq) - n + 1, 1))

    # Count n-gram frequencies
    ngram_counts: Counter[tuple[str, ...]] = Counter()
    for seq in sequences:
        seen_in_session: set[tuple[str, ...]] = set()
        for n in range(2, 5):
            for i in range(len(seq) - n + 1):
                ngram = tuple(seq[i:i + n])
                if ngram not in seen_in_session:
                    ngram_counts[ngram] += 1
                    seen_in_session.add(ngram)

    # Filter to patterns occurring >5 times
    patterns: list[dict[str, Any]] = []
    for ngram, freq in ngram_counts.most_common(20):
        if freq <= 5:
            break
        dur_list = durations.get(ngram, [])
        avg_dur = statistics.mean(dur_list) if dur_list else 0.0

        # Friction score: high stdev in duration suggests inconsistency/friction
        friction = 0.0
        if len(dur_list) >= 2:
            try:
                friction = statistics.stdev(dur_list) / max(avg_dur, 1.0)
            except statistics.StatisticsError:
                friction = 0.0

        patterns.append({
            "sequence": list(ngram),
            "frequency": freq,
            "avg_duration": round(avg_dur, 2),
            "friction_score": round(min(friction, 1.0), 3),
        })

    return patterns


def _pattern_friction_recommendations(patterns: list[dict[str, Any]]) -> list[Recommendation]:
    """Generate recommendations from high-friction workflow patterns."""
    recs: list[Recommendation] = []

    for pat in patterns:
        if pat["friction_score"] > 0.5 and pat["frequency"] > 5:
            seq_str = " → ".join(pat["sequence"])
            recs.append(Recommendation(
                category="personalization",
                headline=f"Workflow '{seq_str}' has high friction",
                detail=(
                    f"This {len(pat['sequence'])}-step pattern occurs {pat['frequency']} times "
                    f"with a friction score of {pat['friction_score']:.2f}. "
                    f"High variance in execution time suggests inconsistency — "
                    f"consider automating or creating a template."
                ),
                action_type="automate_workflow",
                confidence=72,
                evidence=(
                    f"Pattern frequency: {pat['frequency']}, "
                    f"friction score: {pat['friction_score']:.2f}"
                ),
                priority="medium",
                trust_level="observed",
                teach_text=(
                    "Repeated sequences with high time variance often have "
                    "manual steps that could be automated or templated."
                ),
            ))

    return recs


# ─── Usage Trend Detection ───────────────────────────────────────────────────


def detect_trends(longitudinal_data: dict[str, Any]) -> list[Recommendation]:
    """Detect usage trends from longitudinal weekly aggregates.

    Args:
        longitudinal_data: Dict with 'weekly_aggregates' list of
            {week, total_tokens, session_count, tools_used: dict}.

    Returns:
        List of Recommendation objects for detected trends.
    """
    recs: list[Recommendation] = []
    weeks = longitudinal_data.get("weekly_aggregates", [])

    if len(weeks) < 3:
        return recs  # need at least 3 weeks for trend detection

    # Check token usage trend (increasing week-over-week)
    token_values = [w.get("total_tokens", 0) for w in weeks]
    if _is_increasing_trend(token_values):
        growth_pct = _trend_growth_percent(token_values)
        recs.append(Recommendation(
            category="personalization",
            headline="Token usage is increasing week-over-week",
            detail=(
                f"Usage grew ~{growth_pct:.0f}% over the last {len(weeks)} weeks. "
                f"This may be intentional (more complex work) or indicate prompt drift. "
                f"Review if sessions are becoming less focused."
            ),
            action_type="optimize_token_growth",
            confidence=70,
            evidence=f"Weekly tokens: {token_values[-3:]}",
            priority="medium",
            trust_level="observed",
            savings_estimate={"tokens": int(token_values[-1] * 0.1)},
        ))

    # Check session count trend (decreasing = adoption friction)
    session_values = [w.get("session_count", 0) for w in weeks]
    if _is_decreasing_trend(session_values) and session_values[0] > 0:
        drop_pct = _trend_growth_percent(session_values)
        recs.append(Recommendation(
            category="personalization",
            headline="Your AI session frequency is declining",
            detail=(
                f"Sessions dropped ~{abs(drop_pct):.0f}% over {len(weeks)} weeks. "
                f"If this is unintentional, there may be friction in your workflow. "
                f"Check if recent changes made AI less accessible."
            ),
            action_type="address_adoption_friction",
            confidence=66,
            evidence=f"Weekly sessions: {session_values[-3:]}",
            priority="low",
            trust_level="observed",
        ))

    # Check for abandoned tools
    _check_abandoned_tools(weeks, recs)

    return recs


def _check_abandoned_tools(weeks: list[dict[str, Any]], recs: list[Recommendation]) -> None:
    """Detect tools that were used heavily then abandoned."""
    if len(weeks) < 4:
        return

    # Split into first half and second half
    mid = len(weeks) // 2
    first_half = weeks[:mid]
    second_half = weeks[mid:]

    first_tools: Counter[str] = Counter()
    for w in first_half:
        for tool, count in (w.get("tools_used", {}) or {}).items():
            first_tools[tool] += count

    second_tools: Counter[str] = Counter()
    for w in second_half:
        for tool, count in (w.get("tools_used", {}) or {}).items():
            second_tools[tool] += count

    # Find tools with >5 uses in first half but 0 in second half
    for tool, count in first_tools.items():
        if count > 5 and second_tools.get(tool, 0) == 0:
            recs.append(Recommendation(
                category="personalization",
                headline=f"You stopped using '{tool}' — was it intentional?",
                detail=(
                    f"'{tool}' was used {count} times in earlier weeks but "
                    f"hasn't appeared recently. If it was useful, consider "
                    f"reintroducing it. If not, this confirms a natural workflow evolution."
                ),
                action_type="review_abandoned_tool",
                confidence=65,
                evidence=f"Used {count}× in first half, 0× in second half",
                priority="low",
                trust_level="observed",
            ))


def _is_increasing_trend(values: list[int | float]) -> bool:
    """Check if values show an increasing trend (>60% of consecutive pairs increase)."""
    if len(values) < 3:
        return False
    increases = sum(1 for i in range(1, len(values)) if values[i] > values[i - 1])
    return increases / (len(values) - 1) > 0.6


def _is_decreasing_trend(values: list[int | float]) -> bool:
    """Check if values show a decreasing trend (>60% of consecutive pairs decrease)."""
    if len(values) < 3:
        return False
    decreases = sum(1 for i in range(1, len(values)) if values[i] < values[i - 1])
    return decreases / (len(values) - 1) > 0.6


def _trend_growth_percent(values: list[int | float]) -> float:
    """Calculate overall percent change from first to last value."""
    if not values or values[0] == 0:
        return 0.0
    return ((values[-1] - values[0]) / values[0]) * 100


# ─── Main Detector Interface ─────────────────────────────────────────────────


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Standard detector interface: combine personalization signals.

    Combines:
    - Relative threshold violations (per-user baselines)
    - Pattern friction analysis
    - Usage trend detection (if longitudinal data available)
    """
    recs: list[Recommendation] = []
    if not sessions:
        return recs

    try:
        # 1. Relative thresholds
        baseline = calculate_baseline(sessions)
        recs.extend(_check_threshold_violations(sessions, baseline))

        # 2. Pattern mining + friction
        patterns = mine_workflow_patterns(sessions)
        recs.extend(_pattern_friction_recommendations(patterns))

        # 3. Trend detection (requires longitudinal data)
        try:
            from cruise_ai.recommendations.longitudinal import get_trend_data
            trend_data = get_trend_data()
            recs.extend(detect_trends(trend_data))
        except Exception:
            pass  # longitudinal data may not be available

    except Exception:
        pass  # never crash

    return recs
