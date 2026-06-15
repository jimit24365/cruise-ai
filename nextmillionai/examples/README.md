# examples/

`profile.json` is **@generated — do not edit by hand.**

It is built by the real engine (no hand-authored numbers) via:

```bash
python3 scripts/make_example_profile.py
```

Regenerate it after any methodology/schema version bump —
`tests/test_docs_truth.py` fails if the bundled example was built by an
older engine. Hand-edits would make the example disagree with the
engine, which is exactly the kind of drift the docs-truth tests exist
to catch.
