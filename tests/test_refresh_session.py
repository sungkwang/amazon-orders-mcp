"""Tests for the refresh_session tool and the expiry messages that point to it.

No browser is started and nothing contacts Amazon.
"""

import asyncio
import json

import pytest

from amazon_orders_mcp import server
from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.server import _clamp_refresh_timeout, _run_blocking


def _raise_non_interactive():
    raise NonInteractiveAuthRequired("Amazon requires interactive input (captcha)")


def test_interactive_challenge_points_to_refresh_tool():
    out = json.loads(
        asyncio.run(
            _run_blocking(_raise_non_interactive, timeout=5, tool_name="get_order")
        )
    )
    assert out["action_required"] == "refresh_session"
    assert "refresh_session" in out["error"]
    assert "cookie_capture" not in out["error"]


def test_refresh_session_is_registered_as_a_tool():
    names = [tool.name for tool in asyncio.run(server.mcp.list_tools())]
    assert "refresh_session" in names


@pytest.mark.parametrize(
    "requested, expected",
    [(10, 60), (60, 60), (180, 180), (300, 300), (9999, 300), (-5, 60)],
)
def test_refresh_timeout_is_clamped(requested, expected):
    assert _clamp_refresh_timeout(requested) == expected


def test_refresh_session_passes_clamped_timeout_and_returns_result(monkeypatch):
    seen = {}

    def fake_capture(timeout_seconds):
        seen["timeout_seconds"] = timeout_seconds
        return {"ok": True, "message": "Saved 18 Amazon cookies.", "cookie_count": 18}

    monkeypatch.setattr(server, "capture_session", fake_capture)
    out = json.loads(asyncio.run(server.refresh_session(timeout_seconds=9999)))

    assert seen["timeout_seconds"] == 300
    assert out["ok"] is True
    assert out["cookie_count"] == 18
