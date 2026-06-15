#!/usr/bin/env python3
"""Formula fingerprint: a stable hash of the scoring engine.

Hashes the SOURCE of every score_*/compute_* function and every
module-level UPPERCASE constant in scoring.py. The hash is recorded in
the header of SCORING-METHODOLOGY.md and pinned by a test: any change to
scoring code breaks CI until the methodology doc is deliberately
revisited — formulas can no longer drift away from their published
contract as a side effect of another task (docs/HARDLINES.md).

Implementation note: we hash each node's source segment
(`ast.get_source_segment`), NOT `ast.dump()`. `ast.dump`'s output is not
stable across Python versions (field set / f-string nodes differ between
3.9 and 3.12), which made the fingerprint compute differently in CI than
locally. Source segments are identical on every interpreter, and
formatting is canonical because `ruff format` is a gate — so the hash is
reproducible everywhere. The trade-off: a comment-only edit inside a
scoring function will trip it, which is acceptable (it just means
glancing at the methodology doc and re-running --update).

  python3 scripts/formula_fingerprint.py            # print current hash
  python3 scripts/formula_fingerprint.py --update   # rewrite the doc header line
"""

import ast
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORING = ROOT / "nextmillionai" / "scoring.py"
DOC = ROOT / "nextmillionai" / "docs" / "SCORING-METHODOLOGY.md"
LINE_RE = re.compile(r"Formula fingerprint: `([0-9a-f]{12})`")


def compute_fingerprint() -> str:
    source = SCORING.read_text()
    tree = ast.parse(source)
    parts = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name.startswith("score_") or node.name.startswith("compute_")
        ):
            seg = ast.get_source_segment(source, node) or ""
            parts.append((node.name, seg))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    seg = ast.get_source_segment(source, node) or ""
                    parts.append((t.id, seg))
    parts.sort()
    digest = hashlib.sha256("\n".join(d for _, d in parts).encode()).hexdigest()
    return digest[:12]


def main() -> None:
    fp = compute_fingerprint()
    if "--update" in sys.argv:
        text = DOC.read_text()
        if LINE_RE.search(text):
            text = LINE_RE.sub(f"Formula fingerprint: `{fp}`", text)
        else:
            raise SystemExit("no 'Formula fingerprint:' line in the doc header to update")
        DOC.write_text(text)
        print(f"updated: {fp}")
    else:
        print(fp)


if __name__ == "__main__":
    main()
