"""
nextmillionai.network_server -- Reference registry for the nextmillionai
network (`nextmillionai network serve`).

A minimal, self-hostable, file-backed registry. This is the SAME code a
hosted nextmillionai.org registry would run — hosting it is roadmap; the
protocol works today against any deployment of this server.

Consent guarantees enforced server-side (defense in depth — the client
already redacts):
  - Published payloads are validated: only allowlisted derived fields
    are accepted; raw-code patterns, private blocks, and filesystem
    paths are rejected with 400.
  - Every record is revocable: DELETE with the revoke token removes it.
  - Discovery returns only what each builder published — nothing more.

Endpoints:
  POST   /v1/builders            {profile} -> 201 {builderId, revokeToken}
  PUT    /v1/builders/{id}       {profile} + Bearer token -> 200
  DELETE /v1/builders/{id}       Bearer token -> 204
  GET    /v1/builders            ?leverage=&domain=&tech= -> {builders: [...]}
  GET    /v1/builders/{id}       -> the published profile
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nextmillionai.export import verify_artifact_json
from nextmillionai.paths import user_home
from nextmillionai.schema import SHAREABLE_PROFILE_FIELDS

_MAX_BODY_BYTES = 2_000_000
_ALLOWED_TOP_KEYS = set(SHAREABLE_PROFILE_FIELDS) | {"schema_version"}


def default_store_dir() -> Path:
    d = user_home() / "registry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_published_profile(profile: dict) -> list[str]:
    """Server-side validation: derived-only or rejected."""
    if not isinstance(profile, dict):
        return ["profile must be an object"]
    violations = [f"field not allowed: {k}" for k in profile.keys() if k not in _ALLOWED_TOP_KEYS]
    violations.extend(verify_artifact_json(profile))
    return violations


class RegistryStore:
    """File-backed store: one JSON file per published builder."""

    def __init__(self, store_dir: Path | None = None):
        self.dir = store_dir or default_store_dir()
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, builder_id: str) -> Path:
        # ids are uuid4 hex — reject anything else (no path traversal)
        if not re.fullmatch(r"[0-9a-f]{32}", builder_id):
            raise KeyError(builder_id)
        return self.dir / f"{builder_id}.json"

    def create(self, profile: dict) -> tuple[str, str]:
        builder_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        record = {
            "builderId": builder_id,
            "tokenHash": _hash_token(token),
            "publishedAt": _now_iso(),
            "updatedAt": _now_iso(),
            "profile": profile,
        }
        self._path(builder_id).write_text(json.dumps(record, indent=2))
        return builder_id, token

    def get(self, builder_id: str) -> dict | None:
        try:
            p = self._path(builder_id)
        except KeyError:
            return None
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def update(self, builder_id: str, token: str, profile: dict) -> bool:
        record = self.get(builder_id)
        if not record or record["tokenHash"] != _hash_token(token):
            return False
        record["profile"] = profile
        record["updatedAt"] = _now_iso()
        self._path(builder_id).write_text(json.dumps(record, indent=2))
        return True

    def delete(self, builder_id: str, token: str) -> bool:
        record = self.get(builder_id)
        if not record or record["tokenHash"] != _hash_token(token):
            return False
        self._path(builder_id).unlink(missing_ok=True)
        return True

    def list_all(self) -> list[dict]:
        records = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                records.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return records


def _matches(profile: dict, leverage: str | None, domain: str | None, tech: str | None) -> bool:
    pos = profile.get("positioning") or {}
    if leverage:
        current = (pos.get("leverageMode") or {}).get("current", "")
        if current.lower() != leverage.lower():
            return False
    if domain:
        primary = (pos.get("buildDomain") or {}).get("primary", "")
        if primary.lower() != domain.lower():
            return False
    if tech:
        names = [t.get("name", "").lower() for t in pos.get("techDomains") or []]
        if tech.lower() not in names:
            return False
    return True


def _summary(record: dict) -> dict:
    """Discovery projection — a subset of what the builder published."""
    profile = record["profile"]
    pos = profile.get("positioning") or {}
    return {
        "builderId": record["builderId"],
        "name": profile.get("name", ""),
        "title": profile.get("title", ""),
        "primaryTitle": (profile.get("primaryTitle") or {}).get("name"),
        "leverageMode": (pos.get("leverageMode") or {}).get("current"),
        "buildDomain": (pos.get("buildDomain") or {}).get("primary"),
        "techDomains": [t.get("name") for t in (pos.get("techDomains") or [])[:8]],
        "publishedAt": record.get("publishedAt"),
        "updatedAt": record.get("updatedAt"),
    }


def make_handler(store: RegistryStore):
    class RegistryHandler(BaseHTTPRequestHandler):
        server_version = "nextmillionai-registry/0.1"

        def _send(self, status: int, body: dict):
            data = json.dumps(body, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _bearer_token(self) -> str | None:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                return auth[len("Bearer ") :].strip()
            return None

        def _read_body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return None
            if length <= 0 or length > _MAX_BODY_BYTES:
                return None
            try:
                data = json.loads(self.rfile.read(length).decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
            return data if isinstance(data, dict) else None

        def log_message(self, fmt, *args):  # quiet by default, no IP logs
            pass

        def do_POST(self):
            if urlparse(self.path).path != "/v1/builders":
                return self._send(404, {"error": "not found"})
            body = self._read_body()
            if body is None or "profile" not in body:
                return self._send(400, {"error": "body must be {profile}"})
            violations = validate_published_profile(body["profile"])
            if violations:
                return self._send(
                    400,
                    {
                        "error": "profile rejected: derived-only fields allowed",
                        "violations": violations[:10],
                    },
                )
            builder_id, token = store.create(body["profile"])
            self._send(
                201,
                {
                    "builderId": builder_id,
                    "revokeToken": token,
                    "publishedAt": _now_iso(),
                    "note": "Store the revokeToken — it is the only way to unpublish.",
                },
            )

        def do_PUT(self):
            m = re.fullmatch(r"/v1/builders/([0-9a-f]{32})", urlparse(self.path).path)
            if not m:
                return self._send(404, {"error": "not found"})
            token = self._bearer_token()
            if not token:
                return self._send(401, {"error": "missing revoke token"})
            body = self._read_body()
            if body is None or "profile" not in body:
                return self._send(400, {"error": "body must be {profile}"})
            violations = validate_published_profile(body["profile"])
            if violations:
                return self._send(
                    400,
                    {
                        "error": "profile rejected: derived-only fields allowed",
                        "violations": violations[:10],
                    },
                )
            if not store.get(m.group(1)):
                return self._send(404, {"error": "no such builder"})
            if not store.update(m.group(1), token, body["profile"]):
                return self._send(403, {"error": "invalid revoke token"})
            self._send(200, {"builderId": m.group(1), "updatedAt": _now_iso()})

        def do_DELETE(self):
            m = re.fullmatch(r"/v1/builders/([0-9a-f]{32})", urlparse(self.path).path)
            if not m:
                return self._send(404, {"error": "not found"})
            token = self._bearer_token()
            if not token:
                return self._send(401, {"error": "missing revoke token"})
            if not store.get(m.group(1)):
                return self._send(404, {"error": "no such builder"})
            if not store.delete(m.group(1), token):
                return self._send(403, {"error": "invalid revoke token"})
            self._send(204, {})

        def do_GET(self):
            parsed = urlparse(self.path)
            m = re.fullmatch(r"/v1/builders/([0-9a-f]{32})", parsed.path)
            if m:
                record = store.get(m.group(1))
                if not record:
                    return self._send(404, {"error": "not found"})
                # Only what the builder published — never the token hash
                return self._send(
                    200,
                    {
                        "builderId": record["builderId"],
                        "publishedAt": record.get("publishedAt"),
                        "updatedAt": record.get("updatedAt"),
                        "profile": record["profile"],
                    },
                )
            if parsed.path == "/v1/builders":
                q = parse_qs(parsed.query)
                leverage = (q.get("leverage") or [None])[0]
                domain = (q.get("domain") or [None])[0]
                tech = (q.get("tech") or [None])[0]
                builders = [
                    _summary(r)
                    for r in store.list_all()
                    if _matches(r["profile"], leverage, domain, tech)
                ]
                return self._send(200, {"builders": builders, "count": len(builders)})
            if parsed.path == "/v1/health":
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})

    return RegistryHandler


def run_registry(port: int = 7750, host: str = "127.0.0.1", store_dir: Path | None = None):
    store = RegistryStore(store_dir)
    server = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"  nextmillionai registry on http://{host}:{port}")
    print(f"  store: {store.dir}")
    print("  Builders appear here only after an explicit `nextmillionai publish`.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
