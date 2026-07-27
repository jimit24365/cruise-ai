"""Tests for cruise_ai.config_cmd — configuration CLI."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect data_dir to tmp so tests never touch real config."""
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path / "home"))


def _config_file() -> Path:
    from cruise_ai.config_cmd import _config_file as cf

    return cf()


def _make_args(**kwargs) -> Namespace:
    defaults = {
        "show": False,
        "enable_fingerprinting": False,
        "disable_fingerprinting": False,
        "set": None,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


class TestLoadSave:
    def test_load_empty(self):
        from cruise_ai.config_cmd import load_config

        assert load_config() == {}

    def test_save_and_load_roundtrip(self):
        from cruise_ai.config_cmd import load_config, save_config

        save_config({"fingerprinting": True, "theme": "dark"})
        cfg = load_config()
        assert cfg == {"fingerprinting": True, "theme": "dark"}

    def test_load_corrupt_json(self):
        from cruise_ai.config_cmd import _config_file, load_config

        f = _config_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{invalid json", encoding="utf-8")
        assert load_config() == {}


class TestCmdConfig:
    def test_show_empty(self, capsys):
        from cruise_ai.config_cmd import cmd_config

        cmd_config(_make_args(show=True))
        out = capsys.readouterr().out
        assert "no configuration set" in out

    def test_enable_fingerprinting(self):
        from cruise_ai.config_cmd import cmd_config, load_config

        cmd_config(_make_args(enable_fingerprinting=True))
        assert load_config()["fingerprinting"] is True

    def test_disable_fingerprinting(self):
        from cruise_ai.config_cmd import cmd_config, load_config

        cmd_config(_make_args(enable_fingerprinting=True))
        cmd_config(_make_args(disable_fingerprinting=True))
        assert load_config()["fingerprinting"] is False

    def test_set_single_value(self):
        from cruise_ai.config_cmd import cmd_config, load_config

        cmd_config(_make_args(set=["theme=dark"]))
        assert load_config()["theme"] == "dark"

    def test_set_multiple_values(self):
        from cruise_ai.config_cmd import cmd_config, load_config

        cmd_config(_make_args(set=["a=1", "b=hello"]))
        cfg = load_config()
        assert cfg["a"] == 1
        assert cfg["b"] == "hello"

    def test_set_boolean_coercion(self):
        from cruise_ai.config_cmd import cmd_config, load_config

        cmd_config(_make_args(set=["flag=true"]))
        assert load_config()["flag"] is True
        cmd_config(_make_args(set=["flag=false"]))
        assert load_config()["flag"] is False

    def test_set_invalid_format(self, capsys):
        from cruise_ai.config_cmd import cmd_config

        cmd_config(_make_args(set=["noequalssign"]))
        out = capsys.readouterr().out
        assert "Invalid format" in out

    def test_show_after_set(self, capsys):
        from cruise_ai.config_cmd import cmd_config

        cmd_config(_make_args(set=["color=blue"]))
        cmd_config(_make_args(show=True))
        out = capsys.readouterr().out
        assert "color" in out
        assert "blue" in out

    def test_persistence_across_loads(self):
        from cruise_ai.config_cmd import cmd_config, load_config

        cmd_config(_make_args(enable_fingerprinting=True))
        cmd_config(_make_args(set=["editor=vim"]))
        cfg = load_config()
        assert cfg["fingerprinting"] is True
        assert cfg["editor"] == "vim"

    def test_config_file_is_valid_json(self):
        from cruise_ai.config_cmd import cmd_config

        cmd_config(_make_args(set=["x=42"]))
        raw = _config_file().read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["x"] == 42
