"""cruise_ai.config_cmd — Configuration management CLI.

Stores settings in ~/.cruise-ai/data/config.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _config_file() -> Path:
    """Return the config file path."""
    from cruise_ai.paths import data_dir

    return data_dir() / "config.json"


def load_config() -> dict[str, Any]:
    """Load configuration from disk. Returns empty dict if none exists."""
    f = _config_file()
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    """Persist configuration to disk."""
    f = _config_file()
    f.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_config(args) -> None:
    """Handle `cruise-ai config` subcommand."""
    cfg = load_config()

    if args.enable_fingerprinting:
        cfg["fingerprinting"] = True
        save_config(cfg)
        print("  ✓ Fingerprinting enabled (SHA-256 duplicate detection)")
        return

    if args.disable_fingerprinting:
        cfg["fingerprinting"] = False
        save_config(cfg)
        print("  ✓ Fingerprinting disabled")
        return

    if args.set:
        for item in args.set:
            if "=" not in item:
                print(f"  ✗ Invalid format: {item!r} (expected KEY=VALUE)")
                continue
            key, _, value = item.partition("=")
            key = key.strip()
            # Attempt type coercion for common patterns
            if value.lower() in ("true", "yes"):
                cfg[key] = True
            elif value.lower() in ("false", "no"):
                cfg[key] = False
            elif value.isdigit():
                cfg[key] = int(value)
            else:
                cfg[key] = value
            print(f"  ✓ {key} = {cfg[key]!r}")
        save_config(cfg)
        return

    # Default: --show (also when no flag given)
    if not cfg:
        print("  (no configuration set — using defaults)")
        print()
        print("  Set values with:")
        print("    cruise-ai config --set KEY=VALUE")
        print("    cruise-ai config --enable-fingerprinting")
        return

    print("  cruise-ai configuration:")
    print()
    max_key = max(len(k) for k in cfg) if cfg else 0
    for key in sorted(cfg):
        print(f"    {key:<{max_key}}  {cfg[key]!r}")
