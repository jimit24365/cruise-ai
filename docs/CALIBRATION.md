# cruise-ai Calibration Framework

> How thresholds get validated, adjusted, and eventually promoted from `heuristic` → `observed` → `validated`.

---

## Philosophy

cruise-ai ships with **heuristic thresholds** — reasonable guesses informed by observed patterns but not empirically validated at scale. The calibration framework provides a path from "we think this is right" to "we measured this is right."

---

## Calibration Levels

| Level | What It Means | How To Get There |
|-------|---------------|------------------|
| `heuristic` | Author's judgment based on reasoning | Default for new rules |
| `observed` | Pattern confirmed in real user data (N ≥ 50 sessions) | Longitudinal tracking shows correlation |
| `validated` | External evidence: research paper, industry standard, or A/B test | Community calibration or formal study |

---

## How Calibration Works

### 1. Local Self-Calibration (Automatic)

Every time `cruise-ai recommend` runs:
- A **snapshot** of current metrics is stored locally
- When the user provides **feedback** (acted/dismissed/useful/not_useful), it's recorded
- Over time, cruise-ai can compare: "did metrics improve after acting on X?"

```
Session 1: recommend "create steering doc" → user acts on it
Session 5: avgPromptWords dropped from 120 → 45
            → outcome recorded: steering doc recommendation WORKED
```

### 2. Precision/Recall Measurement

For each detector, we can compute:

| Metric | Formula | Target |
|--------|---------|--------|
| **Precision** | acted / (acted + dismissed) | > 0.6 |
| **Usefulness** | useful / (useful + not_useful) | > 0.7 |
| **Action rate** | acted / total_shown | > 0.3 |

If a detector falls below targets, its confidence should be lowered or its threshold adjusted.

### 3. Community Calibration (Opt-In, Future)

Users who opt in can share **anonymized threshold validation data**:

```json
{
  "detector": "long_prompt_detection",
  "threshold": 300,
  "sessions_analyzed": 150,
  "true_positives": 45,    // user confirmed it was wasted
  "false_positives": 12,   // user said it was fine
  "precision": 0.79,
  "user_id_hash": "a3f7..."  // never reversible
}
```

This data helps adjust thresholds globally via open PRs.

---

## Threshold Adjustment Process

### When to Adjust

A threshold should be reviewed when:
- Precision < 0.5 (more false positives than true positives)
- Action rate < 0.1 (nobody acts on it — probably noise)
- Multiple users report the same false positive pattern
- New research contradicts the current value

### How to Propose

1. Open an issue with: current threshold, proposed new value, evidence
2. Show data: feedback counts, longitudinal trends, or external citations
3. If accepted, update the threshold + TRUST-MODEL.md + upgrade trust_level

### Gradualism

Never change a threshold by more than 30% in one release. Large jumps cause:
- Previously-suppressed recommendations suddenly appearing
- Previously-shown recommendations suddenly disappearing
- User confusion about why behavior changed

---

## Metrics We Track Per Detector

| Metric | Storage | Purpose |
|--------|---------|---------|
| Times shown | feedback.json counts | Exposure |
| Times acted on | feedback response="acted" | User found value |
| Times dismissed | feedback response="dismissed" | User rejected |
| Metric improvement after action | longitudinal.json outcomes | Actual efficacy |
| Confidence adjustment | Per-action_type running total | Auto-calibrate |

---

## Open Questions for Calibration

These are thresholds where we're least confident and most want data:

| Question | Current Guess | What Would Help |
|----------|---------------|-----------------|
| Is 300 words the right "long prompt" threshold? | Yes (from nextmillionai) | A/B: does reducing to <150 improve first-shot rate? |
| Is 50-word bucketing the right granularity for duplicate detection? | Maybe | Opt-in fingerprinting data showing actual duplication |
| Is 60% the right "frequent tool" threshold for Skills? | Unknown | Measure: do users who create Skills at 60% actually use them? |
| Is 8 sessions enough to suggest project memory? | Unknown | Measure: at what session count do users agree they need it? |
| Is the 70% co-occurrence threshold too aggressive? | Maybe | False positive rate from user feedback |

---

## Contributing Calibration Data

If you want to help calibrate cruise-ai thresholds:

```bash
# Enable feedback tracking
cruise-ai recommend
# → interact with recommendations, provide feedback

# View your local calibration data
cruise-ai feedback --summary

# (Future) Opt in to anonymized threshold sharing
# cruise-ai config --share-calibration
```

All shared data is:
- Aggregated (never individual sessions)
- Anonymized (user_id is a one-way hash)
- Threshold-scoped (only precision/recall for specific detectors)
- Revocable (opt out at any time, data removed from next aggregation)
