# cruise-ai Trust Model

> Every recommendation cruise-ai makes has a documented reasoning chain.
> This file is the "show your work" for why each rule exists.

---

## Trust Levels

Every recommendation carries a `trust_level` field:

| Level | Meaning | Validation Status |
|-------|---------|-------------------|
| `validated` | Backed by external research, standards, or measured outcomes | Peer-reviewed or industry-standard |
| `observed` | Based on patterns observed in real session data (nextmillionai's dataset) | Single-project observation, not peer-reviewed |
| `heuristic` | Reasonable assumption without empirical validation | Author's judgment, needs calibration |
| `experimental` | Exploratory — may change significantly with data | Low confidence, flagged for review |

---

## Threshold Registry

### Token Optimization

| Rule | Threshold | Value | Reasoning | Trust Level |
|------|-----------|-------|-----------|-------------|
| Long prompt detection | Words per prompt | 300 | nextmillionai's `signal_clarity` scoring finds optimal range 15-150 words; >300 is penalized. Based on analysis that high first-shot acceptance correlates with concise prompts. | `observed` |
| Very long prompt | Words per prompt | 500 | 2× the long threshold. Prompts this length almost certainly contain pasted context rather than instructions. | `heuristic` |
| Long prompt percentage | % of total prompts | 20% | If 1-in-5 prompts is long, it's a pattern not an outlier. Below 20% could be legitimate one-off complex prompts. | `heuristic` |
| High token usage | Total estimated tokens | 500,000 | ~$3-15 depending on model mix. Roughly 2-3 months of active daily use. Chosen as the point where cost awareness becomes valuable. | `heuristic` |
| Expensive model threshold | Cost per 1K tokens | $0.020 | Above this = premium tier (opus, gpt-4, o1). Below = commodity (sonnet, haiku, flash). Based on published API pricing. | `validated` |
| Expensive model concentration | % of sessions | 80% | If 4/5 sessions use premium, there's clear routing opportunity. Below 80% suggests intentional mixing. | `heuristic` |
| Token/word ratio | Tokens per word | 1.3 | Well-established average from OpenAI's tokenizer documentation. Varies by language (code ≈ 1.5, English prose ≈ 1.3). | `validated` |

### Duplicate Context Detection

| Rule | Threshold | Value | Reasoning | Trust Level |
|------|-----------|-------|-----------|-------------|
| Bucket width | Word range for grouping | 50 | Prompts within ±25 words are "similar length." Narrower (20) over-triggers; wider (100) misses. | `heuristic` |
| Cluster dominance | % of sessions in one bucket | 50% | If half your sessions start identically-sized, it's systematic. Below 50% could be coincidence. | `heuristic` |
| Minimum bucket size | Words in dominant bucket | 100 | Below 100 words, a repeated first prompt might just be a greeting/simple instruction, not pasted context. | `heuristic` |
| Repeated content estimate | % of clustered words that are "repeated" | 60% | Conservative: we assume 60% of the prompt is repeated context, 40% is genuinely new per-session. | `heuristic` |

**Known limitation:** This uses word count as a proxy for content similarity. Same-length prompts are NOT guaranteed to have the same content. See [Fingerprinting](#opt-in-fingerprinting) for the opt-in upgrade.

### Model Recommendation

| Rule | Threshold | Value | Reasoning | Trust Level |
|------|-----------|-------|-----------|-------------|
| Single model detection | Unique models | 1 | If only one model across 20+ sessions, there's zero routing happening. | `validated` (definitional) |
| Minimum sessions for detection | Session count | 20 | Below 20 sessions, model choice patterns aren't stable enough to recommend changes. | `heuristic` |
| Cost savings estimate | % reducible | 70% | Assumes 70% of premium-model tasks could be handled by a cheaper model. Conservative vs. the actual ~85% from routing studies. | `heuristic` |

### Skill Engine

| Rule | Threshold | Value | Reasoning | Trust Level |
|------|-----------|-------|-----------|-------------|
| Frequent tool threshold | % of sessions | 60% | A tool in 3/5 sessions is "core to your workflow." Below 60% could be project-specific. | `heuristic` |
| Basic tools excluded | Tool names | read, write, shell, grep, glob | These are infrastructure — everyone uses them. Recommending a "Skill" for file reading is noise. | `observed` |
| Co-occurrence threshold | % together vs individual | 70% | If two tools appear together 7/10 times they're individually used, they're a workflow pair. | `heuristic` |
| Subagent suggestion | Conditions | 0 dispatches + avg >15 turns + >20 sessions | All three must be true. High turns without delegation over sustained use = clear opportunity. | `heuristic` |
| Underutilization (grep/glob) | Condition | grep > 20, glob = 0 | If you search content 20+ times but never discover files by pattern, you're missing a tool. | `observed` |

### Project Memory

| Rule | Threshold | Value | Reasoning | Trust Level |
|------|-----------|-------|-----------|-------------|
| Minimum sessions per project | Count | 8 | Below 8 sessions, you might still be exploring the project. At 8+, you have a sustained engagement. | `heuristic` |
| First prompt length signal | Avg words | 100 | Above 100 words as a session opener almost certainly contains project context, not just a task description. | `observed` |
| High confidence threshold | Sessions | 12 | 12+ sessions with same pattern upgrades confidence from 65% → 75%. | `heuristic` |
| Cross-session tool set | % with same set | 50% | If half your sessions share the exact same tool configuration, it's your "default workspace." | `heuristic` |
| Minimum tool set size | Unique tools | 4 | Fewer than 4 tools is too simple to warrant a template. | `heuristic` |

### Learning Engine

| Rule | Threshold | Value | Reasoning | Trust Level |
|------|-----------|-------|-----------|-------------|
| Plan mode opportunity | planModePercent | < 5% | Below 5% is "basically never uses it." Could benefit if sessions > 20. | `observed` (from nextmillionai's work mode classification) |
| Subagent opportunity | dispatches + turns | 0 dispatches AND avg > 10 turns AND > 30 sessions | Sustained high-turn sessions without any delegation = clear opportunity. Requires 30 sessions to be confident it's a pattern. | `heuristic` |
| Context engineering opportunity | avgPromptWords | > 80 | 80+ word average across all prompts suggests heavy inline context rather than letting tools load it. nextmillionai considers 15-50 optimal. | `observed` |
| Minimum sessions for any learning rec | Count | 10-30 (varies) | Insufficient data below these thresholds — patterns aren't stable. | `heuristic` |

---

## Confidence Score Reasoning

| Confidence | Meaning |
|-----------|---------|
| 90% | Multiple strong signals align, large sample size |
| 80% | Clear pattern with sufficient evidence |
| 75% | Solid signal, moderate sample size |
| 70% | Pattern detected, could have alternative explanations |
| 65% | Weak signal, still above threshold |
| 60% | Minimum — borderline, might be noise |
| < 60% | Suppressed — not shown to user |

Confidence is **not** a probability. It's a severity/certainty blend:
- How strong is the signal? (magnitude)
- How much data supports it? (sample size)
- How many alternative explanations exist? (ambiguity)

---

## Known Limitations

### What We Cannot Detect (Without Opt-In)

| Limitation | Why | Mitigation |
|-----------|-----|------------|
| Actual prompt content duplication | Privacy: we never read prompt text | Opt-in fingerprinting (hash-based) |
| Task complexity per session | We only see counts, not semantics | Use turn count + correction rate as proxy |
| Whether model routing would actually work | We can't test cheaper models on your tasks | Confidence capped at 75% |
| Whether a Skill would be used | Behavioral prediction is unreliable | Frame as suggestion, not requirement |
| Whether the user already has steering docs | We don't scan project files | Check for common filenames in future |

### False Positive Scenarios

| Detector | False Positive Case | Frequency |
|----------|-------------------|-----------|
| Duplicate context | Different 200-word prompts that happen to be same length | ~20% estimated |
| Long prompts | Legitimately complex tasks that need long descriptions | ~10% |
| Model routing | All tasks genuinely need premium models (research, architecture) | ~15% |
| Skill recommendation | Tools used together by coincidence, not workflow | ~15% |
| Project memory | Different context pasted each time, same length | ~20% |

---

## Opt-In Fingerprinting

**Status: Implemented (opt-in, disabled by default)**

When enabled via `cruise-ai config --enable-fingerprinting`:

1. First 50 words of each prompt are hashed (SHA-256, truncated)
2. Hashes are compared across sessions (never stored as text)
3. If >60% of sessions share same hash → high-confidence duplicate detection
4. Hashes stored locally in `~/.cruise-ai/data/fingerprints.json`
5. Never transmitted, never included in exports

This upgrades duplicate detection from `heuristic` (word-count proxy) to `observed` (actual content matching).

---

## Validation Roadmap

### Phase 1: Self-Validation (Current)
- [x] Threshold reasoning documented (this file)
- [x] Trust levels on every recommendation
- [x] Known limitations published

### Phase 2: Feedback Loop
- [x] `cruise-ai feedback` command for user reporting
- [ ] Track acted-on vs dismissed recommendations
- [ ] Adjust confidence based on feedback (local only)

### Phase 3: Longitudinal Measurement
- [x] Pre/post score tracking infrastructure
- [ ] "Did acting on X improve dimension Y?" measurement
- [ ] Publish anonymized aggregates (opt-in)

### Phase 4: Community Calibration
- [ ] Anonymized threshold validation from opt-in users
- [ ] Precision/recall metrics per detector
- [ ] Threshold adjustment proposals (open-source process)
- [ ] Research paper citations for each `observed` threshold
