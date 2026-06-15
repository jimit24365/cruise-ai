---
description: Write the narrative for your profile (runs on YOUR agent, never changes scores)
---

Run the nextmillionai enrichment pass — you are the user's own agent, which is exactly who this is designed for.

1. Call `nma_enrichment_request` to get the enrichment prompt filled with the user's real signals and bounded, secret-stripped excerpts.
2. Follow its instructions EXACTLY and produce only the six-block JSON (narrative, positioningLine, whatYouBuilt, decisionPatterns, strengths, growthAreas, howYouUseAI). Hard rules: no raw code, no fences, no extra keys, no ranking/percentile language, every claim traceable to the provided SIGNALS or EXCERPTS, positioning narrated as ground truth — never reassigned.
3. Call `nma_enrichment_submit` with the JSON. If it is rejected, fix the stated reason and resubmit once; if rejected again, tell the user the heuristic narrative remains in place.
4. Tell the user the narrative is revocable anytime with `nextmillionai enrich --revoke`, and that it never changed any score.

$ARGUMENTS
