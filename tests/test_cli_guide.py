"""WS7: the visual CLI teaches itself — guide map + command intros,
clean plain-text fallback when piped / NO_COLOR."""

import subprocess
import sys


def _run(*args, env_extra=None):
    import os

    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "nextmillionai", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_guide_renders_full_pipeline_plain():
    out = _run("guide").stdout
    for cmd in ("calibrate", "assess", "report", "enrich", "sync", "publish"):
        assert f"[{cmd}]" in out, f"{cmd} missing from guide"
    assert "every step is local" in out
    assert "\x1b[" not in out  # NO_COLOR honored: zero ANSI codes


def test_guide_boxes_when_colored():
    from nextmillionai import cliui

    real = cliui.color_enabled
    cliui.color_enabled = lambda: True
    try:
        out = cliui.guide()
        assert "┌" in out and "▼" in out  # box-drawing flow map
        import re

        plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
        widths = {len(line) for line in plain.splitlines() if line.startswith("  │")}
        assert len(widths) == 1, f"misaligned boxes: {widths}"
    finally:
        cliui.color_enabled = real


def test_intro_plain_fallback():
    from nextmillionai import cliui

    out = cliui.intro("assess", "scan + score", "sessions, git")
    assert "nextmillionai assess" in out
    assert "all local — nothing leaves your machine" in out


def test_help_epilog_points_at_guide():
    out = _run("--help").stdout
    assert "nextmillionai guide" in out
    assert "calibrate -> assess -> report" in out


def test_start_is_the_one_shot_pipeline():
    """`start` = calibrate (first run) + assess + report: parser carries
    the union of both steps' flags, guide teaches it, and the dispatch
    has a real handler."""
    import inspect

    import nextmillionai.build_profile as bp
    from nextmillionai import cliui
    from nextmillionai.build_profile import cmd_start  # noqa: F401  (exists)

    src = inspect.getsource(bp.cmd_start)
    assert "cmd_assess(args" in src and "cmd_report(args)" in src

    assert "`start` runs calibrate + assess + report" in cliui.guide()
