"""Expired session: one sign-in window, then one retry. Sign-in and fetch are faked."""

import pytest

from amazon_orders_mcp import server
from amazon_orders_mcp.client import NonInteractiveAuthRequired


def _expired_then_ok():
    calls = {"n": 0}

    def fetch(order_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise NonInteractiveAuthRequired("expired")
        return f"ok {order_id}"

    return fetch, calls


def test_expired_session_signs_in_once_and_retries(monkeypatch):
    signins = []
    monkeypatch.setattr(server, "capture_session", lambda timeout_seconds: signins.append(timeout_seconds) or {"ok": True})
    fetch, calls = _expired_then_ok()
    wrapped = server._with_auto_refresh(fetch)

    assert wrapped("111") == "ok 111"
    assert len(signins) == 1
    assert calls["n"] == 2


def test_no_sign_in_when_session_is_fine(monkeypatch):
    signins = []
    monkeypatch.setattr(server, "capture_session", lambda timeout_seconds: signins.append(1) or {"ok": True})
    wrapped = server._with_auto_refresh(lambda order_id: "fine")

    assert wrapped("111") == "fine"
    assert signins == []


def test_failed_sign_in_reraises_and_does_not_retry(monkeypatch):
    monkeypatch.setattr(server, "capture_session", lambda timeout_seconds: {"ok": False})
    fetch, calls = _expired_then_ok()
    wrapped = server._with_auto_refresh(fetch)

    with pytest.raises(NonInteractiveAuthRequired):
        wrapped("111")
    assert calls["n"] == 1


def test_retry_failure_is_not_retried_again(monkeypatch):
    monkeypatch.setattr(server, "capture_session", lambda timeout_seconds: {"ok": True})

    def always_expired(order_id):
        raise NonInteractiveAuthRequired("still expired")

    wrapped = server._with_auto_refresh(always_expired)
    with pytest.raises(NonInteractiveAuthRequired):
        wrapped("111")
