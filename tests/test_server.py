"""Unit tests for server.py's pure-logic helpers.

These tests avoid hitting the real amazon-orders library by patching
`build_session`, `ensure_authenticated`, and the lazily imported
`AmazonTransactions` symbol at its real module path.
"""

import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from amazon_orders_mcp import server
from amazon_orders_mcp.client import NonInteractiveAuthRequired
from amazon_orders_mcp.server import (
    _run_blocking,
)


class TestRunBlocking:
    def test_success_passthrough(self):
        def blocking():
            return "hello"

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="test"))
        assert result == "hello"

    def test_timeout_returns_error_payload(self):
        def blocking():
            import time

            time.sleep(2)
            return "never"

        result = asyncio.run(
            _run_blocking(blocking, timeout=0.05, tool_name="slow_tool")
        )
        payload = json.loads(result)
        assert "error" in payload
        assert "timed out" in payload["error"]
        assert payload["tool"] == "slow_tool"
        assert payload["timeout_seconds"] == 0.05

    def test_non_interactive_auth_required(self):
        def blocking():
            raise NonInteractiveAuthRequired("need captcha")

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="t"))
        payload = json.loads(result)
        assert payload["action_required"] == "refresh_session"
        assert "need captcha" in payload["error"]

    def test_generic_exception(self):
        def blocking():
            raise RuntimeError("boom")

        result = asyncio.run(_run_blocking(blocking, timeout=1.0, tool_name="t"))
        payload = json.loads(result)
        assert "boom" in payload["error"]
        assert payload["exception_type"] == "RuntimeError"
