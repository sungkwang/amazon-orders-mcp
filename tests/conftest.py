"""Shared test setup: never touch the real Amazon browser profile."""

import pytest

from amazon_orders_mcp import browser_profile


@pytest.fixture(autouse=True)
def private_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_profile, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(browser_profile, "LOCK_PATH", tmp_path / "profile.lock")


class Persistent:
    """Make a fake browser look like the persistent context the code now opens."""

    def __init__(self, browser):
        self._browser = browser
        self._context = browser.new_context()

    def __getattr__(self, name):
        return getattr(self._context, name)

    def close(self):
        self._browser.close()


def persistent(browser_getter):
    return lambda *a, **k: Persistent(browser_getter())
