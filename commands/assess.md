---
description: Scan local AI coding sessions + git and build your profile (fully local)
---

Run the user's cruise_ai assessment.

1. Call the `cruise_calibrate` tool if no consent exists yet (it will say so), then `cruise_assess` (pass `code: true` if the user asked for the code scan, `rescan: true` if they want fresh data).
2. Show the returned summary: composite + confidence, the six dimensions, positioning (leverage / build domain / tech), top archetypes, and the coverage report.
3. Remind the user: everything ran locally, nothing was uploaded, and they can view the full views with `cruise_ai report`.

Honesty rules: no percentiles or rankings; positioning is a map, not a ladder. If data is thin, say which signals were insufficient rather than papering over them.

$ARGUMENTS
