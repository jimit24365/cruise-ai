"""Shared test guards.

Tests must never read the developer's real data stores. Cursor's app
storage (state.vscdb, multi-GB on real machines) is redirected to a
nonexistent path for every test; tests that exercise the composer
scanner pass an explicit ``app_user_dir`` fixture instead.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_cursor_app_storage(tmp_path, monkeypatch):
    import nextmillionai.scanner as scanner_mod

    monkeypatch.setattr(
        scanner_mod, "CURSOR_APP_USER_DIR", tmp_path / "no-cursor-app", raising=True
    )
