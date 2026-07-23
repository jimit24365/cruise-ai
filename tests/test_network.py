"""End-to-end tests for the opt-in network: publish -> discover ->
unpublish, with consent enforced at every step.

Runs the reference registry on an ephemeral localhost port and drives
the real client (urllib) against it.
"""

import json
import threading
from http.server import ThreadingHTTPServer

import pytest

import cruise_ai.paths as paths_mod
from cruise_ai.network import (
    build_publish_payload,
    load_publish_state,
    publish,
    unpublish,
)
from cruise_ai.network_server import (
    RegistryStore,
    make_handler,
    validate_published_profile,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUISE_AI_HOME", str(tmp_path / "home"))
    return tmp_path


@pytest.fixture
def registry(tmp_path):
    store = RegistryStore(tmp_path / "registry-store")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield url, store
    server.shutdown()


def write_profile(name="Net Builder"):
    profile = {
        "schema_version": "1.0",
        "name": name,
        "title": "Builder",
        "composite": 75,
        "intent_score": 75,
        "dimensions": {},
        "archetypes": [],
        "titles": [],
        "assessment": {
            "confidence": 80,
            "sessions": 40,
            "dateRange": "x",
            "sources_used": ["Claude Code"],
            "privacyMode": "local-only",
        },
        "positioning": {
            "leverageMode": {"current": "harnessing"},
            "buildDomain": {"primary": "ai_products"},
            "techDomains": [{"name": "python", "weight": 80}],
        },
        "activity": {"streak": 2, "activeDays": 12, "days": []},
        "wrappedStats": {"goToPrompt": "secret raw prompt", "tools": []},
        "experimental": {"available": True, "signals": [{"label": "x"}]},
        "antiPatterns": [{"name": "private"}],
        "scannedProjects": [{"name": "hidden-proj", "path": "/Users/x/hidden"}],
    }
    paths_mod.profile_path().write_text(json.dumps(profile))
    return profile


def fetch(url):
    import urllib.request

    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


class TestPublishLifecycle:
    def test_publish_discover_unpublish(self, fake_home, registry):
        url, _store = registry
        write_profile()

        result = publish(url)
        assert result["builderId"]
        assert load_publish_state() is not None

        # Discoverable by an agent, filtered by positioning
        found = fetch(f"{url}/v1/builders?leverage=harnessing&domain=ai_products&tech=python")
        assert found["count"] == 1
        assert found["builders"][0]["name"] == "Net Builder"

        # Wrong filter -> not returned
        miss = fetch(f"{url}/v1/builders?leverage=prompting")
        assert miss["count"] == 0

        # Full record contains ONLY shared fields
        record = fetch(f"{url}/v1/builders/{result['builderId']}")
        dumped = json.dumps(record)
        assert "secret raw prompt" not in dumped
        assert "hidden-proj" not in dumped
        assert "experimental" not in record["profile"]
        assert "antiPatterns" not in record["profile"]
        assert "tokenHash" not in dumped

        # Unpublish removes it
        msg = unpublish()
        assert "removed" in msg.lower() or "Unpublished" in msg
        assert load_publish_state() is None
        import urllib.error

        with pytest.raises(urllib.error.HTTPError):
            fetch(f"{url}/v1/builders/{result['builderId']}")

    def test_republish_updates_in_place(self, fake_home, registry):
        url, _store = registry
        write_profile("First Name")
        first = publish(url)

        write_profile("Second Name")
        second = publish(url)
        assert second["updated"] is True
        assert second["builderId"] == first["builderId"]

        found = fetch(f"{url}/v1/builders")
        assert found["count"] == 1
        assert found["builders"][0]["name"] == "Second Name"

    def test_unpublish_without_publish(self, fake_home):
        assert "nothing to unpublish" in unpublish().lower()


class TestServerSideConsent:
    def test_server_rejects_private_fields(self, registry):
        url, _store = registry
        import urllib.request

        bad = {"profile": {"name": "X", "experimental": {"signals": []}}}
        req = urllib.request.Request(
            f"{url}/v1/builders",
            data=json.dumps(bad).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        import urllib.error

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
        assert exc.value.code == 400

    def test_delete_requires_valid_token(self, registry, fake_home):
        url, store = registry
        write_profile()
        result = publish(url)
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{url}/v1/builders/{result['builderId']}",
            method="DELETE",
            headers={"Authorization": "Bearer wrong-token"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
        assert exc.value.code == 403
        # Still discoverable — wrong token must not remove it
        assert fetch(f"{url}/v1/builders")["count"] == 1

    def test_validate_rejects_filesystem_paths(self):
        violations = validate_published_profile(
            {"name": "X", "stackSummary": {"p": "/Users/me/code"}}
        )
        assert violations

    def test_validate_accepts_clean_payload(self, fake_home):
        write_profile()
        payload = build_publish_payload()
        assert validate_published_profile(payload) == []


class TestPayloadIsRedacted:
    def test_payload_never_contains_private_data(self, fake_home):
        write_profile()
        payload = build_publish_payload()
        dumped = json.dumps(payload)
        assert "secret raw prompt" not in dumped
        assert "hidden-proj" not in dumped
        assert "experimental" not in payload
        assert "scannedProjects" not in payload
        assert "antiPatterns" not in payload
