"""Tests for the avatar persistence API (GET/POST /api/avatar)."""

import http.client
import json
import threading

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTMILLIONAI_HOME", str(tmp_path))


def _start_hub(monkeypatch):
    from nextmillionai import hub

    server = hub.ThreadedHTTPServer(("localhost", 0), hub.ProfileHandler)
    port = server.server_address[1]
    monkeypatch.setenv("PORT", str(port))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


def test_get_avatar_returns_null_when_no_file(monkeypatch):
    server, port = _start_hub(monkeypatch)
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/api/avatar")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["avatar"] is None
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_post_avatar_saves_and_get_returns_it(monkeypatch, tmp_path):
    server, port = _start_hub(monkeypatch)
    try:
        avatar_data = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
            "CAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        body = json.dumps({"avatar": avatar_data}).encode()

        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request(
            "POST",
            "/api/avatar",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
            },
        )
        resp = conn.getresponse()
        assert resp.status == 200
        result = json.loads(resp.read())
        assert result["status"] == "saved"

        # Verify the file was written
        avatar_file = tmp_path / "data" / "avatar"
        assert avatar_file.is_file()
        assert avatar_file.read_text().strip() == avatar_data

        # GET should return it
        conn2 = http.client.HTTPConnection("localhost", port, timeout=5)
        conn2.request("GET", "/api/avatar")
        resp2 = conn2.getresponse()
        assert resp2.status == 200
        data = json.loads(resp2.read())
        assert data["avatar"] == avatar_data
        conn2.close()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_post_avatar_clear(monkeypatch, tmp_path):
    server, port = _start_hub(monkeypatch)
    try:
        # First save an avatar
        avatar_data = "data:image/png;base64,AAAA"
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request(
            "POST",
            "/api/avatar",
            body=json.dumps({"avatar": avatar_data}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
            },
        )
        resp = conn.getresponse()
        assert resp.status == 200
        resp.read()
        conn.close()

        # Clear it
        conn2 = http.client.HTTPConnection("localhost", port, timeout=5)
        conn2.request(
            "POST",
            "/api/avatar",
            body=json.dumps({"avatar": None}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
            },
        )
        resp2 = conn2.getresponse()
        assert resp2.status == 200
        result = json.loads(resp2.read())
        assert result["status"] == "cleared"
        conn2.close()

        # File should be gone
        avatar_file = tmp_path / "data" / "avatar"
        assert not avatar_file.exists()
    finally:
        server.shutdown()
        server.server_close()


def test_post_avatar_rejects_non_image(monkeypatch):
    server, port = _start_hub(monkeypatch)
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request(
            "POST",
            "/api/avatar",
            body=json.dumps({"avatar": "not-a-data-url"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://localhost:{port}",
            },
        )
        resp = conn.getresponse()
        assert resp.status == 400
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_post_avatar_rejects_missing_origin(monkeypatch):
    server, port = _start_hub(monkeypatch)
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request(
            "POST",
            "/api/avatar",
            body=json.dumps({"avatar": "data:image/png;base64,AAAA"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
