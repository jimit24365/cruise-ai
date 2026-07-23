"""Shared test guards.

Tests must never read the developer's real data stores. Cursor's app
storage (state.vscdb, multi-GB on real machines) is redirected to a
nonexistent path for every test; tests that exercise the composer
scanner pass an explicit ``app_user_dir`` fixture instead. Kiro's
session stores get the same treatment (its adapter is consent-enabled
by default, so any test driving run_adapters/run_scan with defaults
would otherwise read a real ~/.kiro); kiro tests pass explicit dirs.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_cursor_app_storage(tmp_path, monkeypatch):
    import nextmillionai.scanner as scanner_mod

    monkeypatch.setattr(
        scanner_mod, "CURSOR_APP_USER_DIR", tmp_path / "no-cursor-app", raising=True
    )


@pytest.fixture(autouse=True)
def _no_real_kiro_stores(tmp_path, monkeypatch):
    import nextmillionai.scanner as scanner_mod

    monkeypatch.setattr(scanner_mod, "KIRO_SESSIONS_DIR", tmp_path / "no-kiro", raising=True)
    monkeypatch.setattr(scanner_mod, "KIRO_IDE_DIRS", [], raising=True)
