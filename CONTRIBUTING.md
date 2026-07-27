# Contributing to cruise-ai

Thank you for your interest in improving cruise-ai! This guide covers everything you need to get started.

## Getting Started

1. **Fork** the repo on GitHub
2. **Clone** your fork locally
3. **Set up** the development environment (see below)
4. **Create a branch** with the naming convention `<type>/<slug>`

Branch types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples: `feat/mcp-tool-support`, `fix/scoring-null-check`, `docs/calibration-guide`

## Development Setup

```bash
git clone https://github.com/<your-fork>/cruise-ai.git
cd cruise-ai
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Verify everything works:

```bash
ruff check .
ruff format --check .
mypy cruise_ai --ignore-missing-imports
python3 -m pytest -o "addopts=" -q
```

## Adding a Detector

The recommendation engine runs detectors from `cruise_ai/recommendations/`. Each category module exports a `detect()` function.

**Interface:**

```python
def detect(
    sessions: list[Any],
    profile: dict[str, Any],
    scan_results: dict[str, Any],
) -> list[Recommendation]:
    """Detect opportunities and return recommendations.

    Args:
        sessions: List of Session objects from adapters.
        profile: The profile.json dict (scored signals).
        scan_results: The scan_results.json dict (raw scan output).

    Returns:
        List of Recommendation objects with confidence >= 60.
    """
```

**Steps to add a detector:**

1. Create or extend a module in `cruise_ai/recommendations/`
2. Implement `detect(sessions, profile, scan_results) -> list[Recommendation]`
3. Register it in `cruise_ai/recommendations/engine.py` (add import + add to detector list)
4. Add a `trust_level` to each recommendation: `validated`, `observed`, `heuristic`, or `experimental`
5. Write tests in `tests/` — see `tests/test_recommendations.py` for patterns

**Guidelines:**

- Never read prompt text — only use counts, timestamps, and tool names
- Set `confidence` between 0–100 (only ≥60 are shown to users)
- Provide `evidence` explaining what data supports the recommendation
- Detectors must not crash — wrap risky logic in try/except

## Adding a Generator

Generators produce artifacts (skill files, hook scripts, config) based on detected patterns. They follow the `generate_*()` naming convention.

**Pattern:**

```python
def generate_hook_script(
    pattern: dict[str, Any],
    hook_type: str = "pre-commit",
) -> str:
    """Generate a git hook script from a detected pattern.

    Args:
        pattern: Dict with command, frequency, project info.
        hook_type: The git hook type (pre-commit, post-commit, etc.)

    Returns:
        The hook script content as a string.
    """
```

**Steps to add a generator:**

1. Add the `generate_*()` function in the relevant category module
2. Wire it to the CLI in `cruise_ai/build_profile.py` if it should be user-facing
3. Set `auto_action` on the related Recommendation to describe what the generator does
4. Write tests covering the generated output

## Adding a Tool Adapter

For adding support for a new AI coding tool, see the full walkthrough:
**[docs/ADDING-A-TOOL.md](docs/ADDING-A-TOOL.md)**

This covers the adapter contract, consent wiring, display integration, fidelity rules, and test requirements.

## Testing

```bash
# Run all tests
python3 -m pytest -o "addopts=" -q

# Run a specific test file
python3 -m pytest tests/test_recommendations.py -o "addopts=" -q

# Run with coverage
python3 -m pytest --cov=cruise_ai -o "addopts=" -q
```

**Test conventions:**

- Use `@dataclass` for fake objects (see `FakeSession` pattern in test files)
- Use `monkeypatch` for filesystem mocking — never touch real `~/.cruise-ai/`
- Test both happy path and edge cases (empty data, missing fields)
- New detectors need at least 3 test cases: triggers, doesn't trigger, edge case

## PR Process

1. **Branch** off `main` with a `<type>/<slug>` name
2. **Make the change** — keep it focused, one concern per PR
3. **Run the gates locally** (ruff check, ruff format, mypy, pytest)
4. **Commit** with a [Conventional Commits](https://www.conventionalcommits.org/) message
5. **Push** to your fork and **open the PR** against `cruise-ai:main`
6. **Fill in the PR template** — what/why/tests/schema impact
7. **Review** — CI runs the gates; a core owner reviews

**Merge policy:** squash merge. Your local commit history can stay messy.

**First-time contributors:** Look for `good first issue` and `adapters` labels — a new tool adapter is the most-wanted contribution.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add MCP tool support
fix: handle missing scan results gracefully
docs: update architecture diagram
chore: upgrade ruff to 0.5
```

## Data Contract

If your PR changes the shape of `profile.json` or `scan_results.json`, tag a core owner for review. See [ARCHITECTURE.md](ARCHITECTURE.md) for details.

## Proposing a Methodology Change

The scoring methodology is a versioned, fingerprint-pinned contract. Changes require evidence:

1. Open a thread in **Discussions → Methodology** with your proposed change and rationale
2. Bring evidence — a study, dataset, or reproducible observation
3. If it converges, PR against `SCORING-METHODOLOGY.md` + `scoring.py`

See [cruise_ai/docs/SCORING-METHODOLOGY.md](cruise_ai/docs/SCORING-METHODOLOGY.md) for details.

## Local Checks (CI Gates)

These four gates run in CI — pass them locally before pushing:

```bash
ruff check .
ruff format --check .
mypy cruise_ai --ignore-missing-imports
pytest
```
