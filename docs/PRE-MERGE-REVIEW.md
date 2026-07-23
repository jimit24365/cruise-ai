# Pre-merge dual review — required before anything ships

Every change that ships — a merge into `main`, or any push to `main` or
a shared branch — goes through **two independent reviews first**: one
engineering lens, one product lens. Findings are fixed and **each fix is
pinned by a regression test** before anything leaves the machine.
Iteration pushes to your own fork branch are exempt while you work; the
review happens before the work ships. The four gates are necessary but
not sufficient; they prove the code runs, not that it is right.

**Who runs it:** the person shipping. For an external PR, the merging
maintainer runs both reviews on the integrated branch before merge
(contributors are welcome to run them pre-PR, but it isn't required of
them). The core owner's GitHub review may serve as one of the two
lenses. Reviewers can be humans or agents — what matters is that each
gets a fresh context, independent of the author.

**Why this exists (the receipts):** the Kiro integration
([PR #6](https://github.com/nextmillionai/nextmillionai/pull/6)) had all
four gates green, a full sandbox e2e pass, and a clean privacy grep —
and the dual review still found, pre-merge: a measured-metric
*regression* (`modelCount` could decrease when a source was added), a
**one-way door** into the durable ledger (subagent child sessions
inflating user hours, unrecoverable once shipped), integration tests
reading the developer's real `~/.claude`, and a served `/methodology`
page contradicting the shipped measurement. None of these fail a gate.
All of them would have shipped.

## The rule

1. **Self-verify first.** Four gates green + an end-to-end pass in a
   sandbox `$HOME` (never real data). Don't spend reviewers on code you
   haven't verified yourself.
2. **Run BOTH reviews, independently.** Fresh context each — a reviewer
   who watched the code being written inherits its assumptions.
3. **Verdicts are `SHIP` / `SHIP WITH NITS` / `BLOCK`.** Any blocker or
   major finding stops the push. Fix it, add a regression test that
   pins the fix, re-run the gates. Nits are judgment calls — fix or
   log them, but say which in the PR.
4. **Never self-certify.** "I checked it again myself" is not a review.
5. **Hardline findings go to the owner** (`docs/HARDLINES.md`) — a
   reviewer flagging a scoring/contract/privacy change needs the owner's
   explicit confirmation in-conversation, recorded in the commit message.
6. **The PR body names the review.** What the reviews found, what was
   fixed, what was consciously not fixed. Reviews that found nothing are
   suspicious — say what was probed.

**Exception (narrow and exhaustive):** a change is exempt only if it
touches nothing but Markdown prose fixing typos, links, or formatting,
or regenerates an `@generated` artifact with no source change. Everything
else — product source, tests, scripts, CI config, static assets, consent
copy, substantive doc rewrites, contract docs — gets the full treatment.
When in doubt, it isn't exempt.

## Prompt 1 — the engineering review

Fill the `{...}` slots and give the reviewer a clean context.

```text
You are a senior software engineer doing a pre-merge review in {repo path},
branch {branch}. This is an open-source, privacy-first, local-only product —
vigilance matters because this ships publicly.

CONTEXT: {2-4 sentences: what the branch does, why, and any history a
reviewer can't infer from the diff — e.g. "merges external PR #N and adds
integration commits on top; review OUR commits: {list}".}

Review scope: `git diff {base}..HEAD`. Read every touched file IN FULL where
the diff alone is ambiguous — a diff hides the invariants around it.

HARD CONSTRAINTS to verify held (do not trust the author's claims — check):
1. scoring.py untouched: `git diff {base}..HEAD -- nextmillionai/scoring.py`
   is empty AND `python3 scripts/formula_fingerprint.py` matches main's.
2. No outbound network in any new code (network.py is the only sanctioned
   outbound module; the privacy CI tests must pass).
3. schema.py / docs/SCHEMA.md / version constants untouched — unless the PR
   explicitly declares a signed-off contract change.
4. Tests never read the developer's real data stores (~/.claude, ~/.cursor,
   ~/.codex, ~/.kiro, real git repos). Verify by reading the tests, and if
   in doubt run them with NEXTMILLIONAI_VERBOSE=1 and watch what they scan.

TECHNICAL AREAS TO SCRUTINIZE: {list the risky mechanisms this specific
branch introduces — merge math, cache logic, migration paths, mutation of
shared state, ordering of pipeline stages. Name your fears explicitly; a
reviewer aimed at nothing finds nothing.}

Be adversarial: construct concrete failure scenarios (inputs/state → wrong
output) and try to reproduce them live with small scripts. Check one-way
doors especially hard: anything written to the durable ledger
(~/.nextmillionai/data/history/), published, or persisted in a form a later
release cannot correct.

RUN the four gates yourself (CONTRIBUTING.md § Local checks is the
canonical list; the fingerprint is CI-enforced inside pytest but run it
directly too — you want the value, not just a pass):
  python3 -m pytest tests/ -q -p no:cacheprovider --override-ini addopts=
  uv tool run ruff check nextmillionai/ tests/ && uv tool run ruff format --check nextmillionai/ tests/
  uv run --python 3.12 --with mypy --no-project -- python -m mypy nextmillionai --ignore-missing-imports
  python3 scripts/formula_fingerprint.py

Return: verdict (SHIP / SHIP WITH NITS / BLOCK) + numbered findings, each
with severity (blocker / major / minor / nit), file:line, a concrete
failure scenario, and a one-line fix. Also list what you attacked that
HELD — a review is evidence, not just a defect list. Your final message is
the review; make it self-contained.
```

## Prompt 2 — the product review

```text
You are a product manager reviewing branch {branch} in {repo path}
pre-merge. The product's non-negotiables (CLAUDE.md): (1) privacy — local
only, explicit consent per source, no silent reads; (2) no ranking language
anywhere; (3) scores are arithmetic over counted local signals —
unmeasurable is insufficient, never estimated, and unmeasured input never
moves a measured number; (4) one assessment JSON renders both views.

CONTEXT: {what the branch does, from the user's point of view.}

Review scope: `git diff {base}..HEAD`, plus every SERVED surface those
files feed (/profile, /report, /methodology, /how-it-works, /preview,
the MCP tool descriptions) — the diff shows what changed; the served
surfaces show what users are now told.

Review from the product side — read the actual files, don't assume:
1. CONSENT & DISCLOSURE: does every consent/disclosure string match what
   the code actually reads? Is the "Never:" line airtight? Any dark
   pattern in defaults or prompts? Is every notice actionable (tells the
   user exactly what to run)?
2. HONESTY OF CLAIMS: README / docs / CURRENT.md / DATA_COLLECTION.md /
   docs/ADAPTERS.md — does every claim match shipped behavior? Check the
   SERVED surfaces too: /methodology renders from methodology_spec.py
   (basis strings!) — internal registries being right does not make the
   user-facing page right.
3. MEASUREMENT SEMANTICS: will any user's numbers change on upgrade? Is
   that change deliberate, owner-approved, and stated in CHANGELOG.md?
   Do signal_registry inputs declare every real input?
4. NO-RANKING RULE: scan all new/changed text for percentiles, cohorts,
   leaderboards, "top X%", ladder copy.
5. MIGRATION: what does an EXISTING user experience on upgrade — prompts,
   notices, silent changes? Is a "no" sticky? Is anything asked twice?
6. NOISE: does the change surface UI/CLI output to users it's irrelevant
   for? (e.g. nagging about a tool they don't have.)
7. CONTRIBUTOR EXPERIENCE (if docs changed): follow the doc's own steps
   against the real code — do the file/function references exist? Would a
   newcomer following it succeed?

Return: verdict (SHIP / SHIP WITH NITS / BLOCK) + numbered findings with
severity, file, and concrete suggested wording for any copy issue. List
what you verified clean. Your final message is the review; make it
self-contained.
```

## After the reviews

| Outcome | Action |
|---|---|
| Both SHIP | Push/merge. Note in the PR body what was probed. |
| Any BLOCK / major | Fix → **regression test per finding** → gates → a focused re-review of the fixes if they were structural. Then push. |
| Finding touches a hardline | STOP; owner sign-off in-conversation, recorded in the commit message, before the fix lands. |
| Reviewers disagree | The stricter verdict wins. Escalate to the owner only with both reviews attached. |

The review commit message lists the findings and their dispositions —
future readers should see what almost shipped. See commit `c8675d1`
("fix: pre-merge dual-review findings") for the format.
