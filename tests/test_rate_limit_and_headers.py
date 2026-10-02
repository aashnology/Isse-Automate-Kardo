"""
Tests for the in-memory rate limiter and the CSP/security headers added to
web/server.py. The rate limiter is skipped whenever app.config["TESTING"]
is set (see client fixture in test_web_bridge.py) -- otherwise the rest of
the test suite's own request volume, all sharing this one process's
_request_times state, would start tripping it as the suite grows. These
tests explicitly turn TESTING off to exercise the real limiting path.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import server as web_server


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    """Like test_web_bridge.py's `client` fixture, but with TESTING off so
    the rate limiter actually runs, and with a clean _request_times so
    other tests' request volume can't bleed into this one."""
    import user_memory
    monkeypatch.setattr(user_memory, "_STORE_PATH", str(tmp_path / "user_memory.json"))
    monkeypatch.setitem(web_server.app.config, "TESTING", False)
    monkeypatch.setattr(web_server, "_request_times", web_server.defaultdict(web_server.deque))
    with web_server.app.test_client() as c:
        yield c


def test_requests_within_the_limit_all_succeed(live_client):
    for _ in range(web_server.RATE_LIMIT_MAX_REQUESTS):
        resp = live_client.get("/api/friction-points")
        assert resp.status_code == 200


def test_requests_past_the_limit_get_429(live_client):
    for _ in range(web_server.RATE_LIMIT_MAX_REQUESTS):
        live_client.get("/api/friction-points")
    resp = live_client.get("/api/friction-points")
    assert resp.status_code == 429
    assert "error" in resp.get_json()


def test_rate_limit_is_per_client_not_global(live_client, monkeypatch):
    for _ in range(web_server.RATE_LIMIT_MAX_REQUESTS):
        live_client.get("/api/friction-points", environ_overrides={"REMOTE_ADDR": "1.1.1.1"})
    # A different client's requests shouldn't be affected by 1.1.1.1 having
    # used up its own budget.
    resp = live_client.get("/api/friction-points", environ_overrides={"REMOTE_ADDR": "2.2.2.2"})
    assert resp.status_code == 200


def test_testing_mode_is_exempt_from_the_rate_limit(client_exempt=None):
    """Uses the real TESTING=True client (from test_web_bridge's fixture
    style) to confirm the exemption itself works -- this is what keeps the
    rest of the suite from tripping the limiter."""
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        for _ in range(web_server.RATE_LIMIT_MAX_REQUESTS + 20):
            resp = c.get("/api/friction-points")
            assert resp.status_code == 200


def test_csp_and_security_headers_present():
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        resp = c.get("/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "script-src 'self'" in csp
        assert "'unsafe-inline'" not in csp.split("style-src")[0]  # not in script-src
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
