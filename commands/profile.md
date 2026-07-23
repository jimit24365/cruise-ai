---
description: Show your AI coding profile (dimensions, positioning, archetypes)
---

Show the user their cruise_ai profile.

1. Call `cruise_get_profile`. If no profile exists, offer to run /cruise_ai:assess first.
2. Present it readably: composite + confidence first, then the six dimensions, positioning (leverage mode / build domain / tech domains), top archetypes, and highlights.
3. If the user asks for the deep report or narrative, call `cruise_get_report`.

Never add ranking language (no percentiles, no "top X%", no comparisons to other builders) — the scores are measurements against research-anchored bands.

$ARGUMENTS
