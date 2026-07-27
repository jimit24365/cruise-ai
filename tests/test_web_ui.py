"""Tests for Phase 2: Web UI Integration — API endpoints and HTML pages."""

import json
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from unittest.mock import patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────

def _find_free_port():
    """Find an available port for the test server."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("localhost", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """Start a test server and return its base URL."""
    import os
    port = _find_free_port()
    os.environ["PORT"] = str(port)

    from cruise_ai.hub import ThreadedHTTPServer, ProfileHandler

    srv = ThreadedHTTPServer(("localhost", port), ProfileHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    # Wait for server to be ready
    for _ in range(50):
        try:
            conn = HTTPConnection("localhost", port, timeout=1)
            conn.request("GET", "/")
            conn.getresponse()
            conn.close()
            break
        except Exception:
            time.sleep(0.1)
    yield f"http://localhost:{port}"
    srv.shutdown()


def get(server, path):
    """GET request helper."""
    req = urllib.request.Request(f"{server}{path}")
    req.add_header("Host", f"localhost:{server.split(':')[-1]}")
    return urllib.request.urlopen(req, timeout=10)


def post(server, path, data):
    """POST request helper with JSON body."""
    port = server.split(":")[-1]
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{server}{path}",
        data=body,
        method="POST",
    )
    req.add_header("Host", f"localhost:{port}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Origin", f"http://localhost:{port}")
    return urllib.request.urlopen(req, timeout=10)


# ── HTML page serving tests ──────────────────────────────────────────

class TestHTMLPages:
    """Test that HTML pages are served correctly."""

    def test_recommend_page_served(self, server):
        """GET /recommend returns HTML with correct content."""
        resp = get(server, "/recommend")
        assert resp.status == 200
        body = resp.read().decode()
        assert "Recommendations" in body
        assert "recommend.css" in body
        assert "recommend.js" in body

    def test_dashboard_page_served(self, server):
        """GET /dashboard returns HTML with correct content."""
        resp = get(server, "/dashboard")
        assert resp.status == 200
        body = resp.read().decode()
        assert "Dashboard" in body
        assert "dashboard.css" in body
        assert "dashboard.js" in body

    def test_recommend_css_served(self, server):
        """Static CSS file for recommendations is accessible."""
        resp = get(server, "/static/css/recommend.css")
        assert resp.status == 200
        assert "text/css" in resp.headers.get("Content-Type", "")

    def test_dashboard_css_served(self, server):
        """Static CSS file for dashboard is accessible."""
        resp = get(server, "/static/css/dashboard.css")
        assert resp.status == 200
        assert "text/css" in resp.headers.get("Content-Type", "")

    def test_recommend_js_served(self, server):
        """Static JS file for recommendations is accessible."""
        resp = get(server, "/static/js/recommend.js")
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")

    def test_dashboard_js_served(self, server):
        """Static JS file for dashboard is accessible."""
        resp = get(server, "/static/js/dashboard.js")
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")


# ── API endpoint tests ───────────────────────────────────────────────

class TestRecommendAPI:
    """Test GET /api/recommend endpoint."""

    def test_recommend_returns_json_array(self, server):
        """GET /api/recommend returns a JSON array."""
        resp = get(server, "/api/recommend")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert isinstance(data, list)

    def test_recommend_items_have_required_fields(self, server):
        """Each recommendation has the required schema fields."""
        resp = get(server, "/api/recommend")
        data = json.loads(resp.read())
        required_fields = {
            "category", "headline", "detail", "action_type",
            "confidence", "evidence", "priority", "trust_level",
        }
        for rec in data:
            assert required_fields.issubset(set(rec.keys())), (
                f"Missing fields: {required_fields - set(rec.keys())}"
            )

    def test_recommend_filter_by_category(self, server):
        """GET /api/recommend?category=X filters results."""
        # First get all recs
        resp = get(server, "/api/recommend")
        all_recs = json.loads(resp.read())
        if not all_recs:
            pytest.skip("No recommendations generated — need session data")

        cat = all_recs[0]["category"]
        resp2 = get(server, f"/api/recommend?category={cat}")
        filtered = json.loads(resp2.read())
        assert all(r["category"] == cat for r in filtered)

    def test_recommend_filter_nonexistent_category(self, server):
        """Filtering by non-existent category returns empty list."""
        resp = get(server, "/api/recommend?category=nonexistent_xyz")
        data = json.loads(resp.read())
        assert data == []

    def test_recommend_priority_values(self, server):
        """Priority field contains valid values."""
        resp = get(server, "/api/recommend")
        data = json.loads(resp.read())
        valid_priorities = {"low", "medium", "high"}
        for rec in data:
            assert rec["priority"] in valid_priorities

    def test_recommend_trust_level_values(self, server):
        """Trust level field contains valid values."""
        resp = get(server, "/api/recommend")
        data = json.loads(resp.read())
        valid_trust = {"validated", "observed", "heuristic", "experimental"}
        for rec in data:
            assert rec["trust_level"] in valid_trust


class TestDashboardAPI:
    """Test GET /api/dashboard endpoint."""

    def test_dashboard_returns_json(self, server):
        """GET /api/dashboard returns a JSON object."""
        resp = get(server, "/api/dashboard")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert isinstance(data, dict)

    def test_dashboard_has_expected_structure(self, server):
        """Dashboard data has usage, cost, models, projects, daily keys."""
        resp = get(server, "/api/dashboard")
        data = json.loads(resp.read())
        expected_keys = {"usage", "cost", "models", "projects", "daily"}
        assert expected_keys.issubset(set(data.keys())), (
            f"Missing keys: {expected_keys - set(data.keys())}"
        )

    def test_dashboard_usage_fields(self, server):
        """Usage section has the expected stat fields."""
        resp = get(server, "/api/dashboard")
        data = json.loads(resp.read())
        usage = data["usage"]
        assert "total_sessions" in usage
        assert "total_tokens_estimated" in usage
        assert "total_prompts" in usage

    def test_dashboard_cost_fields(self, server):
        """Cost section has total and optional model breakdown."""
        resp = get(server, "/api/dashboard")
        data = json.loads(resp.read())
        cost = data["cost"]
        assert "total_estimated_cost_usd" in cost


class TestFeedbackAPI:
    """Test POST /api/feedback and GET /api/feedback/summary endpoints."""

    def test_feedback_post_records_entry(self, server):
        """POST /api/feedback records a feedback entry."""
        payload = {
            "action_type": "test_action",
            "category": "analytics",
            "response": "useful",
            "headline": "Test recommendation",
            "notes": "Testing feedback API",
        }
        resp = post(server, "/api/feedback", payload)
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["status"] == "recorded"
        assert data["entry"]["action_type"] == "test_action"
        assert data["entry"]["response"] == "useful"

    def test_feedback_post_requires_fields(self, server):
        """POST /api/feedback returns 400 if required fields missing."""
        # Missing 'response' field
        payload = {"action_type": "test", "category": "analytics"}
        try:
            post(server, "/api/feedback", payload)
            pytest.fail("Expected 400 error")
        except urllib.error.HTTPError as e:
            assert e.code == 400

    def test_feedback_summary_returns_json(self, server):
        """GET /api/feedback/summary returns valid summary structure."""
        resp = get(server, "/api/feedback/summary")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert isinstance(data, dict)
        assert "total" in data
        assert "by_response" in data
        assert "by_category" in data


class TestLongitudinalAPI:
    """Test GET /api/longitudinal endpoint."""

    def test_longitudinal_returns_json(self, server):
        """GET /api/longitudinal returns a JSON object."""
        resp = get(server, "/api/longitudinal")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert isinstance(data, dict)

    def test_longitudinal_has_status(self, server):
        """Longitudinal data includes a status field."""
        resp = get(server, "/api/longitudinal")
        data = json.loads(resp.read())
        assert "status" in data
        # Either 'ok' or 'insufficient_data' is valid
        assert data["status"] in ("ok", "insufficient_data")


# ── Navigation tests ─────────────────────────────────────────────────

class TestNavigation:
    """Test navigation links exist."""

    def test_profile_has_recommend_link(self, server):
        """Profile page contains a link to /recommend."""
        resp = get(server, "/profile")
        body = resp.read().decode()
        assert "/recommend" in body

    def test_profile_has_dashboard_link(self, server):
        """Profile page contains a link to /dashboard."""
        resp = get(server, "/profile")
        body = resp.read().decode()
        assert "/dashboard" in body
