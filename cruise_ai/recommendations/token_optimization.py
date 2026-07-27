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


def _detect_prompt_compression(sessions: list[Any]) -> list[Recommendation]:
    """Recommend summarization when avg prompt length exceeds 500 words."""
    recs: list[Recommendation] = []
    if not sessions:
        return recs

    all_word_counts: list[int] = []
    for s in sessions:
        wcs = getattr(s, "prompt_word_counts", [])
        all_word_counts.extend(wcs)

    if not all_word_counts:
        return recs

    avg_words = sum(all_word_counts) / len(all_word_counts)
    if avg_words <= 500:
        return recs

    total_excess = int((avg_words - 200) * len(all_word_counts) * 1.3)
    recs.append(Recommendation(
        category="token_optimization",
        headline=f"Avg prompt length is {avg_words:.0f} words — summarization could save {total_excess:,} tokens",
        detail=(
            f"Across {len(all_word_counts)} prompts, the average length is {avg_words:.0f} words. "
            f"Prompts above 500 words often contain context that could be pre-summarized "
            f"or moved to steering docs. Estimated savings: ~{total_excess:,} tokens."
        ),
        action_type="enable_prompt_compression",
        trust_level="observed",
        confidence=78,
        evidence=f"avg prompt length {avg_words:.0f} words across {len(all_word_counts)} prompts",
        priority="high" if avg_words > 800 else "medium",
        teach_text=(
            "Prompt compression means pre-processing your context before sending it to the AI. "
            "Techniques include: summarizing long documents, using bullet points instead of prose, "
            "extracting only relevant sections, and storing recurring context in steering docs "
            "that are loaded automatically."
        ),
        auto_action="Analyze top 10 longest prompts and suggest compression strategies",
        savings_estimate={"tokens": total_excess, "per_session": total_excess // max(len(sessions), 1)},
    ))

    return recs


def _detect_cached_context(sessions: list[Any]) -> list[Recommendation]:
    """Recommend pinning/memory when same context_files appear in >3 sessions."""
    recs: list[Recommendation] = []
    if len(sessions) < 4:
        return recs

    file_session_counts: Counter[str] = Counter()
    for s in sessions:
        context_files = getattr(s, "context_files", None)
        if context_files is None:
            # Try dict-style access for plain dict sessions
            if isinstance(s, dict):
                context_files = s.get("context_files", [])
            else:
                context_files = []
        seen_in_session: set[str] = set()
        for f in context_files:
            if f and f not in seen_in_session:
                file_session_counts[f] += 1
                seen_in_session.add(f)

    # Find files appearing in >3 sessions
    repeated_files = [(f, count) for f, count in file_session_counts.items() if count > 3]
    if not repeated_files:
        return recs

    repeated_files.sort(key=lambda x: -x[1])
    top_files = repeated_files[:5]
    file_list = ", ".join(f"{f} ({count}x)" for f, count in top_files)
    total_repeated = len(repeated_files)

    recs.append(Recommendation(
        category="token_optimization",
        headline=f"{total_repeated} context file(s) loaded in 4+ sessions — pin them to memory",
        detail=(
            f"These files appear across many sessions: {file_list}. "
            f"Repeatedly loading the same files wastes tokens. "
            f"Pin them to project memory or a steering doc so they're always available "
            f"without re-reading."
        ),
        action_type="pin_context_files",
        trust_level="observed",
        confidence=75,
        evidence=f"{total_repeated} files appear in >3 sessions",
        priority="medium",
        teach_text=(
            "When you find yourself loading the same files every session, it means that "
            "context should be persistent. Project memory (CLAUDE.md, .kiro/steering/) "
            "loads automatically, saving tokens and keystrokes. Pin frequently-accessed "
            "files there so the AI always has that context."
        ),
        auto_action="Add top repeated context files to project memory configuration",
        savings_estimate={"files_to_pin": total_repeated},
    ))

    return recs


def _compute_token_waste_score(
    sessions: list[Any], profile: dict[str, Any]
) -> list[Recommendation]:
    """Compute a 0-100 token waste score based on multiple factors."""
    recs: list[Recommendation] = []
    if len(sessions) < 5:
        return recs

    score_components: list[tuple[str, float]] = []

    # Factor 1: Duplicate contexts (0-35 points)
    file_session_counts: Counter[str] = Counter()
    for s in sessions:
        context_files = getattr(s, "context_files", None)
        if context_files is None:
            if isinstance(s, dict):
                context_files = s.get("context_files", [])
            else:
                context_files = []
        for f in set(context_files):
            if f:
                file_session_counts[f] += 1
    repeated_count = sum(1 for count in file_session_counts.values() if count > 3)
    total_files = max(len(file_session_counts), 1)
    dup_score = min(35, (repeated_count / total_files) * 70) if total_files > 0 else 0
    score_components.append(("duplicate_contexts", dup_score))

    # Factor 2: Oversized prompts (0-35 points)
    all_word_counts: list[int] = []
    for s in sessions:
        wcs = getattr(s, "prompt_word_counts", [])
        all_word_counts.extend(wcs)
    if all_word_counts:
        oversized_count = sum(1 for w in all_word_counts if w > 500)
        oversized_pct = oversized_count / len(all_word_counts)
        prompt_score = min(35, oversized_pct * 70)
    else:
        prompt_score = 0.0
    score_components.append(("oversized_prompts", prompt_score))

    # Factor 3: Wrong model choices (0-30 points)
    model_counts: Counter[str] = Counter()
    for s in sessions:
        for m in getattr(s, "models", []):
            model_counts[m] += 1
    total_model_uses = sum(model_counts.values())
    if total_model_uses > 10:
        expensive_count = sum(
            count for model_name, count in model_counts.items()
            if any(x in model_name.lower() for x in ["opus", "gpt-4o", "gpt-4", "o1", "o3"])
        )
        expensive_pct = expensive_count / total_model_uses
        model_score = min(30, expensive_pct * 37.5) if expensive_pct > 0.8 else 0.0
    else:
        model_score = 0.0
    score_components.append(("wrong_model_choices", model_score))

    # Total score
    total_score = int(sum(score for _, score in score_components))
    total_score = max(0, min(100, total_score))

    if total_score > 40:
        breakdown = ", ".join(f"{name}: {val:.0f}/{'35' if 'model' not in name else '30'}"
                             for name, val in score_components)
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"Token Waste Score: {total_score}/100 — {'significant' if total_score >= 60 else 'moderate'} optimization opportunity",
            detail=(
                f"Your token waste score is {total_score}/100 based on: {breakdown}. "
                f"A lower score means more efficient AI usage. "
                f"Focus on the highest-scoring component first for maximum savings."
            ),
            action_type="reduce_token_waste",
            trust_level="heuristic",
            confidence=70 if total_score >= 50 else 62,
            evidence=f"waste score {total_score}/100 from {len(sessions)} sessions",
            priority="high" if total_score >= 60 else "medium",
            teach_text=(
                "The Token Waste Score measures how efficiently you use AI tokens:\n"
                "- Duplicate contexts: same files loaded repeatedly (fix: pin to memory)\n"
                "- Oversized prompts: prompts >500 words (fix: compress or use steering docs)\n"
                "- Wrong model choices: premium models for simple tasks (fix: model routing)"
            ),
            auto_action="Generate a personalized token optimization plan based on waste breakdown",
            savings_estimate={"waste_score": total_score, "reduction_target": max(0, total_score - 20)},
        ))

    return recs


def _detect_context_window_growth(sessions: list[Any]) -> list[Recommendation]:
    """Detect sessions where token usage grows >50% from start to end.

    Tracks token usage across messages within sessions (via the prompts list).
    If tokens grow significantly, recommends splitting into smaller sessions.
    """
    recs: list[Recommendation] = []
    if not sessions:
        return recs

    growing_sessions = 0
    total_checked = 0

    for s in sessions:
        # Get prompts list — supports both object and dict access
        prompts: list[Any] = []
        if isinstance(s, dict):
            prompts = s.get("prompts", [])
        else:
            prompts = getattr(s, "prompts", [])

        if not prompts or len(prompts) < 3:
            continue

        # Extract token counts from prompts
        token_counts: list[int] = []
        for p in prompts:
            if isinstance(p, dict):
                tokens = p.get("tokens_used", 0) or p.get("tokens", 0)
            else:
                tokens = getattr(p, "tokens_used", 0) or getattr(p, "tokens", 0)
            if tokens and tokens > 0:
                token_counts.append(tokens)

        if len(token_counts) < 3:
            continue

        total_checked += 1

        # Compare early tokens to late tokens
        early_avg = sum(token_counts[:max(1, len(token_counts) // 3)]) / max(1, len(token_counts) // 3)
        late_avg = sum(token_counts[-(max(1, len(token_counts) // 3)):]) / max(1, len(token_counts) // 3)

        if early_avg > 0 and late_avg > early_avg * 1.5:
            growing_sessions += 1

    if total_checked < 3:
        return recs

    growth_pct = growing_sessions / total_checked * 100

    if growth_pct > 30:
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"{growth_pct:.0f}% of sessions show >50% token growth — consider splitting long sessions",
            detail=(
                f"{growing_sessions} of {total_checked} sessions show token usage growing "
                f"more than 50% from start to end. This indicates context window bloat — "
                f"each message gets more expensive as the conversation grows. "
                f"Splitting into focused, shorter sessions resets this growth."
            ),
            action_type="split_long_sessions",
            trust_level="observed",
            confidence=68,
            evidence=f"{growing_sessions}/{total_checked} sessions with >50% token growth",
            priority="medium",
            teach_text=(
                "As conversations grow longer, each message costs more tokens because "
                "the AI re-reads the entire history. After 15-20 turns, start a fresh session "
                "for new topics. Use steering docs to carry context between sessions cheaply."
            ),
            auto_action="Identify sessions that should have been split and suggest breakpoints",
            savings_estimate={
                "sessions_affected": growing_sessions,
                "potential_savings_pct": 25,
            },
        ))

    return recs


# ── Filler patterns for prompt simplification ──
_FILLER_PATTERNS = [
    "please", "kindly", "i would like you to", "could you please",
    "would you mind", "if you don't mind", "i'd appreciate it if",
    "thank you in advance", "thanks in advance", "it would be great if",
    "i was wondering if you could", "would it be possible",
    "i need you to", "can you help me with", "i'm looking for help with",
]


def _detect_prompt_simplification(sessions: list[Any]) -> list[Recommendation]:
    """Detect verbose prompt patterns with excessive politeness or filler.

    Flags when >20% of prompts contain filler patterns that waste tokens
    without improving results.
    """
    recs: list[Recommendation] = []
    if not sessions:
        return recs

    total_prompts = 0
    filler_prompts = 0

    for s in sessions:
        prompts = None
        if isinstance(s, dict):
            prompts = s.get("prompts", [])
        else:
            prompts = getattr(s, "prompts", [])
        if not prompts:
            continue

        for prompt in prompts:
            if not isinstance(prompt, str):
                continue
            total_prompts += 1
            prompt_lower = prompt.lower()
            if any(pattern in prompt_lower for pattern in _FILLER_PATTERNS):
                filler_prompts += 1

    if total_prompts < 5:
        return recs

    filler_rate = filler_prompts / total_prompts
    if filler_rate > 0.20:
        estimated_wasted_tokens = int(filler_prompts * 15)  # ~15 tokens per filler phrase
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"{filler_rate * 100:.0f}% of prompts contain filler phrases — simplify for better results",
            detail=(
                f"{filler_prompts} of {total_prompts} prompts contain polite filler "
                f"('please', 'kindly', 'I would like you to', etc.). "
                f"AI models respond equally well to direct instructions. "
                f"Estimated ~{estimated_wasted_tokens:,} wasted tokens on filler."
            ),
            action_type="simplify_prompts",
            trust_level="heuristic",
            confidence=65,
            evidence=f"{filler_prompts}/{total_prompts} prompts with filler patterns ({filler_rate * 100:.0f}%)",
            priority="medium",
            teach_text=(
                "Concise prompts save tokens AND get better results. AI models don't need "
                "politeness markers — they respond to clear, direct instructions. Instead of "
                "'Could you please help me refactor the auth module?', just say "
                "'Refactor the auth module'. Same result, fewer tokens, often better output "
                "because the signal-to-noise ratio is higher."
            ),
            auto_action="Rewrite verbose prompts into concise equivalents",
            savings_estimate={"tokens": estimated_wasted_tokens, "prompts_affected": filler_prompts},
        ))

    return recs


def _detect_from_normalized(norm: dict[str, Any], scan_results: dict[str, Any]) -> list[Recommendation]:
    """Derive token optimization recommendations from normalized scan signals."""
    recs: list[Recommendation] = []
    if not norm:
        return recs

    avg_prompt_words = norm.get("avgPromptWords", 0)
    total_sessions = norm.get("totalSessions", 0)
    model_count = norm.get("modelCount", 0)
    marathon_count = norm.get("marathonSessionCount", 0)

    # avgPromptWords > 500 -> prompt_compression
    if avg_prompt_words > 500:
        estimated_excess = int((avg_prompt_words - 200) * total_sessions * 4.5 * 1.3)
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"Avg prompt length is {avg_prompt_words:.0f} words — summarization could save ~{estimated_excess:,} tokens",
            detail=(
                f"Across {total_sessions} sessions, the average prompt length is {avg_prompt_words:.0f} words. "
                f"Prompts above 500 words often contain context that could be pre-summarized "
                f"or moved to steering docs."
            ),
            action_type="enable_prompt_compression",
            trust_level="heuristic",
            confidence=73 if avg_prompt_words > 800 else 63,
            evidence=f"avg prompt length {avg_prompt_words:.0f} words (from scan normalized data)",
            priority="high" if avg_prompt_words > 800 else "medium",
            teach_text=(
                "Prompt compression means pre-processing your context before sending it to the AI. "
                "Techniques include: summarizing long documents, using bullet points instead of prose, "
                "extracting only relevant sections, and storing recurring context in steering docs."
            ),
            auto_action="Analyze prompt patterns and suggest compression strategies",
            savings_estimate={"tokens": estimated_excess},
        ))

    # avgPromptWords > 300 AND totalSessions > 20 -> prompt_simplification
    if avg_prompt_words > 300 and total_sessions > 20:
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"Avg {avg_prompt_words:.0f}-word prompts across {total_sessions} sessions — simplify for efficiency",
            detail=(
                f"With {total_sessions} sessions averaging {avg_prompt_words:.0f} words per prompt, "
                f"there's likely repeated context or verbose phrasing. Structured prompts and "
                f"steering docs could cut this significantly."
            ),
            action_type="simplify_prompts",
            trust_level="heuristic",
            confidence=60,
            evidence=f"avg {avg_prompt_words:.0f} words/prompt over {total_sessions} sessions (normalized)",
            priority="medium",
            teach_text=(
                "Concise prompts save tokens AND get better results. Use steering docs "
                "for repeated context, and keep prompts focused on the specific task."
            ),
            auto_action="Suggest prompt optimization patterns based on usage data",
        ))

    # modelCount == 1 AND totalSessions > 10 -> model_routing
    if model_count == 1 and total_sessions > 10:
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"Single-model usage across {total_sessions} sessions — multi-model routing could optimize cost/speed",
            detail=(
                f"All {total_sessions} sessions use a single model. Different tasks have different "
                f"complexity — routing simpler tasks to faster/cheaper models improves both "
                f"response time and cost without sacrificing quality."
            ),
            action_type="model_routing",
            trust_level="heuristic",
            confidence=60,
            evidence=f"1 model used across {total_sessions} sessions (normalized scan data)",
            priority="low",
            teach_text="Multi-model routing lets you keep quality for hard tasks while saving on easy ones.",
            auto_action="Suggest a model routing strategy based on prompt complexity",
        ))

    # marathonSessionCount > 5 -> split_long_sessions
    if marathon_count > 5:
        recs.append(Recommendation(
            category="token_optimization",
            headline=f"{marathon_count} marathon sessions detected — consider splitting long sessions",
            detail=(
                f"You have {marathon_count} marathon sessions (very long conversations). "
                f"Long sessions accumulate context window bloat — each message gets more expensive. "
                f"Splitting into focused, shorter sessions resets this growth."
            ),
            action_type="split_long_sessions",
            trust_level="heuristic",
            confidence=63,
            evidence=f"{marathon_count} marathon sessions (from scan normalized data)",
            priority="medium",
            teach_text=(
                "As conversations grow longer, each message costs more tokens because "
                "the AI re-reads the entire history. After 15-20 turns, start a fresh session "
                "for new topics. Use steering docs to carry context between sessions cheaply."
            ),
            auto_action="Identify session patterns and suggest optimal session length",
            savings_estimate={"sessions_affected": marathon_count, "potential_savings_pct": 25},
        ))

    return recs


def detect(
    sessions: list[Any], profile: dict[str, Any], scan_results: dict[str, Any]
) -> list[Recommendation]:
    """Run all token optimization detectors."""
    recs: list[Recommendation] = []

    # Session-based detection (when sessions available)
    if sessions:
        recs.extend(_detect_long_prompts(sessions))
        recs.extend(_detect_duplicate_context(sessions))
        recs.extend(_detect_model_opportunity(sessions, profile))
        recs.extend(_detect_prompt_compression(sessions))
        recs.extend(_detect_cached_context(sessions))
        recs.extend(_compute_token_waste_score(sessions, profile))
        recs.extend(_detect_context_window_growth(sessions))
        recs.extend(_detect_prompt_simplification(sessions))

    # Normalized-signal detection (always available from scan)
    norm = scan_results.get("normalized", {}) if scan_results else {}
    if norm:
        recs.extend(_detect_from_normalized(norm, scan_results))

    return recs
