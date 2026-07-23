"""cruise_ai.recommendations.token_optimization — detect token waste patterns.

Provides:
- Duplicate Context Detection: same context repeatedly pasted
- Long Prompt Detection: excessively large prompts
- Model Recommendation: recommend cheaper/faster models for routine tasks
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from cruise_ai.recommendations.types import Recommendation

# Thresholds
LONG_PROMPT_WORDS = 300  # prompts above this are "long"
VERY_LONG_PROMPT_WORDS = 500  # prompts above this are "very long"
DUPLICATE_THRESHOLD = 0.7  # sessions with >70% similar first-prompt patterns


def _detect_long_prompts(sessions: list[Any]) -> list[Recommendation]:
    """Flag sessions with excessively large prompts."""
    recs: list[Recommendation] = []
    all_word_counts: list[int] = []
    long_count = 0
    very_long_count = 0

    for s in sessions:
        wcs = getattr(s, "prompt_word_counts", [])
        all_word_counts.extend(wcs)
        long_count += sum(1 for w in wcs if w > LONG_PROMPT_WORDS)
        very_long_count += sum(1 for w in wcs if w > VERY_LONG_PROMPT_WORDS)

    if not all_word_counts:
        return recs

    total_prompts = len(all_word_counts)
    long_pct = long_count / total_prompts * 100

    if long_pct > 20:
        avg_long = sum(w for w in all_word_counts if w > LONG_PROMPT_WORDS) / max(long_count, 1)
        wasted_tokens = int((avg_long - 150) * 1.3 * long_count)  # tokens above optimal

        recs.append(Recommendation(
            category="token_optimization",
            headline=f"{long_pct:.0f}% of prompts exceed {LONG_PROMPT_WORDS} words — likely wasting tokens",
            detail=(
                f"{long_count} of {total_prompts} prompts are over {LONG_PROMPT_WORDS} words "
                f"(avg {avg_long:.0f} words for the long ones). "
                f"Estimated ~{wasted_tokens:,} excess tokens. "
                f"Consider: steering docs for repeated context, or prompt compression."
            ),
            action_type="compress_prompts",
            trust_level="observed",
            confidence=80 if long_pct > 30 else 65,
            evidence=f"{long_count}/{total_prompts} prompts > {LONG_PROMPT_WORDS} words",
            priority="high" if long_pct > 40 else "medium",
            teach_text=(
                "Long prompts often repeat context the AI already knows. "
                "Steering docs (.kiro/steering/, CLAUDE.md, .cursorrules) provide "
                "context automatically — no need to paste it every time."
            ),
            auto_action="Analyze longest prompts and suggest which context to extract into steering docs",
            savings_estimate={"tokens": wasted_tokens, "per_session": wasted_tokens // max(len(sessions), 1)},
        ))

    if very_long_count > 5:
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"{very_long_count} prompts exceed {VERY_LONG_PROMPT_WORDS} words — consider splitting",
            detail=(
                f"Very long prompts often try to do too much at once. "
                f"Breaking them into focused, sequential prompts typically gets better results "
                f"AND uses fewer total tokens (the AI doesn't have to re-read context each time)."
            ),
            action_type="split_prompts",
            trust_level="heuristic",
            confidence=72,
            evidence=f"{very_long_count} prompts > {VERY_LONG_PROMPT_WORDS} words",
            priority="medium",
            teach_text="AI models perform better with focused, single-concern prompts. Multi-part requests often lead to partial completions that need correction cycles.",
            auto_action="Identify the longest prompts and suggest how to decompose them",
        ))

    return recs


def _detect_duplicate_context(sessions: list[Any]) -> list[Recommendation]:
    """Detect repeated context patterns across sessions.

    Uses prompt word count patterns as a proxy — sessions with very similar
    first-prompt lengths likely share pasted context.
    """
    recs: list[Recommendation] = []
    if len(sessions) < 5:
        return recs

    # Analyze first prompt of each session
    first_prompt_lengths: list[int] = []
    for s in sessions:
        wcs = getattr(s, "prompt_word_counts", [])
        if wcs:
            first_prompt_lengths.append(wcs[0])

    if len(first_prompt_lengths) < 5:
        return recs

    # Detect clustering of first-prompt lengths (proxy for same context pasted)
    # If many sessions start with a similar-length prompt (±20%), likely same context
    length_buckets: dict[int, int] = defaultdict(int)
    for length in first_prompt_lengths:
        # Bucket by 50-word ranges
        bucket = (length // 50) * 50
        length_buckets[bucket] += 1

    # Find dominant bucket
    if length_buckets:
        dominant_bucket, dominant_count = max(length_buckets.items(), key=lambda x: x[1])
        dominant_pct = dominant_count / len(first_prompt_lengths) * 100

        if dominant_pct > 50 and dominant_bucket >= 100:
            wasted_per_session = int(dominant_bucket * 0.7 * 1.3)  # 70% is likely repeated context
            total_wasted = wasted_per_session * dominant_count

            recs.append(Recommendation(
                category="token_optimization",
                headline=f"{dominant_pct:.0f}% of sessions start with ~{dominant_bucket}-{dominant_bucket+50} word prompts — likely duplicate context",
                detail=(
                    f"{dominant_count} of {len(first_prompt_lengths)} sessions begin with "
                    f"similar-length prompts (~{dominant_bucket} words), suggesting "
                    f"the same context is pasted repeatedly. A steering doc or project memory "
                    f"file would provide this automatically."
                ),
                action_type="create_steering_doc",
                trust_level="heuristic",
                confidence=70 if dominant_pct > 60 else 62,
                evidence=f"{dominant_count}/{len(first_prompt_lengths)} sessions cluster at {dominant_bucket}-{dominant_bucket+50} word first prompts",
                priority="high" if total_wasted > 50_000 else "medium",
                teach_text=(
                    "When you paste the same context into every session, you waste tokens and time. "
                    "Steering docs (.kiro/steering/*, CLAUDE.md, .cursorrules) are loaded automatically "
                    "by your AI tool — the context is always there without pasting."
                ),
                auto_action="Extract common first-prompt patterns into a steering doc template",
                savings_estimate={"tokens": total_wasted, "per_session": wasted_per_session},
            ))

    return recs


def _detect_model_opportunity(sessions: list[Any], profile: dict) -> list[Recommendation]:
    """Recommend cheaper models for routine tasks."""
    recs: list[Recommendation] = []

    # Check model diversity
    model_counts: Counter[str] = Counter()
    for s in sessions:
        for m in getattr(s, "models", []):
            model_counts[m] += 1

    # Also use profile's modelsSummary
    by_model = profile.get("modelsSummary", {}).get("byModel", {})
    for m, count in by_model.items():
        if m not in model_counts:
            model_counts[m] = count

    if not model_counts:
        return recs

    total = sum(model_counts.values())
    if total < 10:
        return recs

    # Check if using only expensive models
    expensive_count = 0
    for model_name, count in model_counts.items():
        name = model_name.lower()
        if any(x in name for x in ["opus", "gpt-4o", "gpt-4", "o1", "o3"]):
            expensive_count += count

    expensive_pct = expensive_count / total * 100

    if expensive_pct > 80 and total > 20:
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"{expensive_pct:.0f}% of usage is on premium models — try routing simple tasks to cheaper ones",
            detail=(
                f"You use premium models (opus/gpt-4) for {expensive_pct:.0f}% of {total} sessions. "
                f"Tasks like formatting, simple refactors, and boilerplate generation work equally "
                f"well on sonnet/haiku/flash-tier models at 80-95% lower cost."
            ),
            action_type="model_routing",
            trust_level="observed",
            confidence=75,
            evidence=f"{expensive_count}/{total} sessions use premium-tier models",
            priority="medium",
            teach_text=(
                "Model routing means using the right model for the right task:\n"
                "- Complex architecture/reasoning → opus/gpt-4\n"
                "- Standard coding tasks → sonnet/gpt-4o\n"
                "- Simple edits, formatting, tests → haiku/flash\n"
                "Most AI tools support model selection per-prompt or per-session."
            ),
            auto_action="Generate a model routing config based on your task patterns",
            savings_estimate={"cost_reduction_pct": 60},
        ))
    elif len(model_counts) == 1 and total > 20:
        model_name = list(model_counts.keys())[0]
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"Single-model usage ({model_name}) — multi-model routing could optimize cost/speed",
            detail=(
                f"All {total} sessions use {model_name}. Different tasks have different "
                f"complexity — routing simpler tasks to faster/cheaper models improves both "
                f"response time and cost without sacrificing quality."
            ),
            action_type="model_routing",
            trust_level="observed",
            confidence=65,
            evidence=f"100% of {total} sessions use a single model",
            priority="low",
            teach_text="Multi-model routing lets you keep quality for hard tasks while saving on easy ones.",
            auto_action="Suggest a model routing strategy based on prompt complexity",
        ))

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all token optimization detectors."""
    recs: list[Recommendation] = []
    recs.extend(_detect_long_prompts(sessions))
    recs.extend(_detect_duplicate_context(sessions))
    recs.extend(_detect_model_opportunity(sessions, profile))
    return recs
