"""
nextmillionai.cliui — minimal ANSI styling for CLI output.

Color only when stdout is a real terminal; honors NO_COLOR and
TERM=dumb. Piped/captured output stays byte-identical plain text, so
scripts and tests see exactly what they always saw.
"""

from __future__ import annotations

import os
import sys
from typing import Callable

# Palette tuned to the brand: warm accent, banded score colors.
_ACCENT = "38;5;166"
_GOOD = "38;5;71"
_MID = "38;5;172"
_LOW = "38;5;167"


def color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _wrap(s: str, code: str) -> str:
    if not color_enabled():
        return str(s)
    return f"\033[{code}m{s}\033[0m"


def bold(s: str) -> str:
    return _wrap(s, "1")


def dim(s: str) -> str:
    return _wrap(s, "2")


def accent(s: str) -> str:
    return _wrap(s, _ACCENT)


def good(s: str) -> str:
    return _wrap(s, _GOOD)


def mid(s: str) -> str:
    return _wrap(s, _MID)


def low(s: str) -> str:
    return _wrap(s, _LOW)


def band(score: float) -> Callable[[str], str]:
    """The score→color band used across all surfaces."""
    return good if score >= 75 else mid if score >= 50 else low


def score_text(score: int) -> str:
    return band(score)(str(score))


def bar(score: int, width: int = 20) -> str:
    """A score bar: block glyphs + band color on a TTY, the classic
    ``####----`` everywhere else (same width, same math)."""
    filled = int(score) // (100 // width)
    filled = max(0, min(width, filled))
    if color_enabled():
        return band(score)("█" * filled) + dim("░" * (width - filled))
    return "#" * filled + "-" * (width - filled)


def header(title: str) -> str:
    """Section header: bold title over a dim rule."""
    rule = "─" * 42 if color_enabled() else "=" * 42
    return f"  {bold(title)}\n  {dim(rule)}"


def step(n: int, total: int, text: str) -> str:
    return f"  {accent(f'[{n}/{total}]')} {text}"


# ── Visual command intros + the pipeline guide (stdlib-only) ─────────────────
# Unicode box-drawing on a TTY; clean plain text when piped / NO_COLOR /
# TERM=dumb. Width-aware down to ~60 columns.


def _width(default: int = 72) -> int:
    try:
        import shutil

        return max(56, min(shutil.get_terminal_size().columns - 2, 78))
    except Exception:
        return default


def intro(name: str, what: str, reads: str | None = None) -> str:
    """The structured command header: name, one-line purpose, what it
    reads, and the privacy line — every command teaches itself."""
    w = _width()
    if color_enabled():
        top = "╭" + "─" * (w - 2) + "╮"
        bot = "╰" + "─" * (w - 2) + "╯"

        def row(s: str, style=None) -> str:
            pad = w - 4 - len(s)
            styled = style(s) if style else s
            return "│ " + styled + " " * max(pad, 0) + " │"

        lines = [top, row(f"nextmillionai {name}", bold), row(what, dim)]
        if reads:
            lines.append(row(f"reads: {reads}", dim))
        lines.append(row("all local — nothing leaves your machine", good))
        lines.append(bot)
        return "\n".join(lines)
    out = [f"  nextmillionai {name} — {what}"]
    if reads:
        out.append(f"  reads: {reads}")
    out.append("  all local — nothing leaves your machine")
    return "\n".join(out)


_PIPELINE = [
    ("calibrate", "consent + scope", "you say which sources to read", "consent.json"),
    ("assess", "scan + score", "sessions, git, ledger -> arithmetic", "profile.json"),
    ("report", "serve both views", "profile.json only", "localhost pages"),
    ("enrich", "the story (opt-in)", "derived excerpts -> YOUR agent", "narrative blocks"),
    ("sync", "more machines (opt-in)", "derived snapshots", "your private repo"),
    ("publish", "the network (opt-in)", "curated shareable JSON", "a registry YOU choose"),
]


def guide() -> str:
    """The pipeline as a flow map — each step's purpose, input, output."""
    w = _width()
    on = color_enabled()
    out = []
    title = "How nextmillionai works — the pipeline"
    out.append(("  " + bold(title)) if on else ("  " + title))
    out.append(
        dim("  every step is local; the three opt-in steps say exactly what leaves")
        if on
        else "  every step is local; the three opt-in steps say exactly what leaves"
    )
    out.append("")
    inner = w - 8  # content width inside the box
    for i, (cmd, what, inp, outp) in enumerate(_PIPELINE):
        if on:
            head = f"{cmd:<10}"
            l1 = (head + what)[:inner].ljust(inner)
            io = f"in: {inp}   out: {outp}"
            l2 = (io[: inner - 1] + "…") if len(io) > inner else io.ljust(inner)
            # pad on PLAIN text, colorize after (ANSI codes have no width)
            l1c = bold(l1[: len(head)]) + l1[len(head) :]
            out += [
                "  ┌" + "─" * (inner + 2) + "┐",
                "  │ " + l1c + " │",
                "  │ " + dim(l2.ljust(inner)) + " │",
                "  └" + "─" * (inner + 2) + "┘",
            ]
            if i < len(_PIPELINE) - 1:
                out.append(accent("      │"))
                out.append(accent("      ▼"))
        else:
            out.append(f"  [{cmd}] {what}")
            out.append(f"      in: {inp}")
            out.append(f"      out: {outp}")
            if i < len(_PIPELINE) - 1:
                out.append("      |")
                out.append("      v")
    out.append("")
    tail = (
        "one-shot: `start` runs calibrate + assess + report together\n"
        "  full methodology: the /methodology page · flow diagram: /how-it-works"
    )
    out.append(("  " + dim(tail)) if on else ("  " + tail))
    return "\n".join(out)


def step_progress(n: int, total: int, label: str) -> str:
    """Live step line used while a command works."""
    if color_enabled():
        return f"  {accent(f'[{n}/{total}]')} {label}"
    return f"  [{n}/{total}] {label}"
