#!/usr/bin/env python3
"""
nextmillionai — Local profile server.
Serves your AI coding profile at http://localhost:7749/profile

Routes:
  GET  /              → redirects to /profile
  GET  /profile       → profile page (HTML)
  GET  /report        → AI Coding Wrapped report page (HTML)
  GET  /static/*      → CSS/JS assets
  GET  /api/profile         → full profile JSON
  GET  /api/profile.json    → agent-crawlable JSON-LD
  GET  /api/profile/meta    → lightweight discovery metadata
  GET  /.well-known/ai-profile.json → redirect to /api/profile.json
  POST /api/profile/rebuild → trigger rescan + rescore
"""

import http.server
import json
import os
import subprocess
import sys
import threading

from nextmillionai.paths import DOCS_DIR, PACKAGE_DIR, STATIC_DIR
from nextmillionai.profile_data import (
    build_agent_profile,
    build_profile_meta,
    load_profile,
)
from nextmillionai.schema import build_shareable_profile
from nextmillionai.visibility import (
    load_visibility_config,
    save_visibility_config,
    validate_visibility_config,
)

DEFAULT_PORT = 7749

_BASE_DIR = str(PACKAGE_DIR)
_STATIC_DIR = str(STATIC_DIR)
_DOCS_DIR = str(DOCS_DIR)


def _get_port() -> int:
    """Return the active server port (respects env override)."""
    return int(os.environ.get("PORT", str(DEFAULT_PORT)))


def _allowed_hosts() -> frozenset[str]:
    """Build the set of acceptable Host header values for the current port."""
    port = _get_port()
    return frozenset(
        [
            f"localhost:{port}",
            f"127.0.0.1:{port}",
            "localhost",
            "127.0.0.1",
        ]
    )


class ProfileHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    # ---- security guards ------------------------------------------------

    def _check_host(self):
        """Reject requests whose Host header is not localhost."""
        host = (self.headers.get("Host") or "").strip()
        if host not in _allowed_hosts():
            self.send_response(403)
            self.end_headers()
            return False
        return True

    def _check_localhost_origin(self):
        """Require Origin or Referer from localhost for mutating requests."""
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        origin = origin.strip().rstrip("/")
        port = _get_port()
        allowed = (
            origin == f"http://localhost:{port}",
            origin == f"http://127.0.0.1:{port}",
            origin.startswith(f"http://localhost:{port}/"),
            origin.startswith(f"http://127.0.0.1:{port}/"),
        )
        if not any(allowed):
            self.send_response(403)
            self.end_headers()
            return False
        return True

    @staticmethod
    def _safe_resolve(base_dir, untrusted_rel):
        """Resolve *untrusted_rel* under *base_dir*; return None on escape."""
        resolved = os.path.realpath(os.path.join(base_dir, untrusted_rel))
        if not resolved.startswith(base_dir + os.sep) and resolved != base_dir:
            return None
        return resolved

    # ---- response helpers -----------------------------------------------

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _serve_file(self, rel_path, content_type="text/html"):
        safe = self._safe_resolve(_BASE_DIR, rel_path)
        if safe and os.path.isfile(safe):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(safe, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        if not self._check_host():
            return
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if not self._check_host():
            return

        path = self.path.split("?")[0]

        if path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/profile")
            self.end_headers()

        elif path == "/profile":
            self._serve_file("static/profile.html")

        elif path == "/report":
            self._serve_file("static/report.html")

        elif path in ("/profile.md", "/report.md"):
            # Agent-readable Markdown of your own profile/report — hand it
            # to an LLM, or let an agent fetch it. Full local data (own
            # machine); the redacted version ships with `export`.
            from nextmillionai.markdown_export import profile_to_markdown

            profile = load_profile()
            view = "report" if path == "/report.md" else "profile"
            md = profile_to_markdown(profile, view=view).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(md)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(md)

        elif path == "/preview":
            self._serve_file("static/preview.html")

        elif path == "/methodology":
            self._serve_file("static/methodology.html")

        elif path == "/how-it-works":
            self._serve_file("static/howitworks.html")

        elif path == "/api/methodology-spec":
            from nextmillionai.methodology_spec import build_spec

            self.send_json(build_spec())

        elif path == "/api/methodology":
            md_path = os.path.join(_DOCS_DIR, "SCORING-METHODOLOGY.md")
            if os.path.isfile(md_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with open(md_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        elif path.startswith("/static/"):
            rel = path[len("/static/") :]
            safe = self._safe_resolve(_STATIC_DIR, rel)
            if safe and os.path.isfile(safe):
                ext = os.path.splitext(safe)[1].lstrip(".")
                mime = {
                    "css": "text/css",
                    "js": "application/javascript",
                    "html": "text/html",
                    "json": "application/json",
                    "png": "image/png",
                    "svg": "image/svg+xml",
                }.get(ext, "text/plain")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with open(safe, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        elif path == "/api/profile":
            profile = load_profile()
            self.send_json(profile)

        elif path == "/api/profile.json":
            profile = load_profile()
            vis = load_visibility_config()
            self.send_json(build_agent_profile(profile, _get_port(), visibility=vis))

        elif path == "/api/profile/meta":
            profile = load_profile()
            vis = load_visibility_config()
            self.send_json(build_profile_meta(profile, _get_port(), visibility=vis))

        elif path == "/api/profile/public":
            profile = load_profile()
            vis = load_visibility_config()
            self.send_json(build_shareable_profile(profile, visibility=vis))

        elif path == "/api/profile/config":
            self.send_json(load_visibility_config())

        elif path == "/api/cli":
            from nextmillionai.paths import cli_invocation

            self.send_json({"cli": cli_invocation()})

        elif path == "/api/publish/state":
            # Local file read only — never imports the network client and
            # never returns the revoke token.
            from nextmillionai.paths import data_dir

            state_file = os.path.join(str(data_dir()), "publish_state.json")
            state = {"published": False}
            if os.path.isfile(state_file):
                try:
                    with open(state_file) as f:
                        raw = json.load(f)
                    state = {
                        "published": True,
                        "registry": raw.get("registry"),
                        "builderId": raw.get("builderId"),
                        "publishedAt": raw.get("publishedAt"),
                        "sections": raw.get("sections", []),
                    }
                except (json.JSONDecodeError, OSError):
                    pass
            self.send_json(state)

        elif path == "/api/scan-results":
            from nextmillionai.paths import scan_results_path

            sr = scan_results_path()
            if sr.is_file():
                with open(sr) as f:
                    data = json.load(f)
                self.send_json(data)
            else:
                self.send_json({"error": "No scan data. Run nextmillionai first."}, status=404)

        elif path == "/api/live/status":
            # Watcher state — local file mtimes only, no network involved.
            from nextmillionai.live import STATE

            self.send_json(STATE.snapshot())

        elif path == "/api/live/events":
            self._serve_live_events()

        elif path == "/api/avatar":
            from nextmillionai.paths import data_dir

            avatar_file = os.path.join(str(data_dir()), "avatar")
            avatar = None
            if os.path.isfile(avatar_file):
                try:
                    with open(avatar_file) as f:
                        avatar = f.read().strip()
                except OSError:
                    pass
            if not avatar:
                # Fall back to an avatar carried in the profile itself — the
                # bundled demo sets one so `report --demo` shows a face. Real
                # profiles have no avatar field and keep the monogram fallback.
                carried = load_profile().get("avatar")
                if isinstance(carried, str) and carried.startswith("data:image/"):
                    avatar = carried
            self.send_json({"avatar": avatar})

        elif path == "/.well-known/ai-profile.json":
            self.send_response(302)
            self.send_header("Location", "/api/profile.json")
            self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def _serve_live_events(self):
        """Localhost SSE stream: pushes watcher status whenever it changes.

        One daemon thread per open EventSource (ThreadedHTTPServer); the
        loop exits when the client disconnects. Periodic heartbeat
        comments surface dead connections promptly.
        """
        from nextmillionai.live import STATE

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        import time as _time

        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            last_sent = None
            last_write = _time.monotonic()
            while True:
                # Short waits double as a poll: a notify that fires while
                # this thread is writing is still picked up next loop.
                with STATE.cond:
                    STATE.cond.wait(timeout=2)
                    snap = STATE._snapshot_locked()
                payload = json.dumps(snap)
                if payload != last_sent:
                    last_sent = payload
                    self.wfile.write(("event: status\ndata: " + payload + "\n\n").encode())
                    self.wfile.flush()
                    last_write = _time.monotonic()
                elif _time.monotonic() - last_write > 14:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_write = _time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self):
        if not self._check_host():
            return

        path = self.path.split("?")[0]

        if path == "/api/profile/config":
            if not self._check_localhost_origin():
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                data = json.loads(body) if body else {}
            except (json.JSONDecodeError, ValueError):
                self.send_json({"error": "invalid JSON"}, status=400)
                return
            errors = validate_visibility_config(data)
            if errors:
                self.send_json({"error": "validation failed", "details": errors}, status=400)
                return
            try:
                save_visibility_config(data)
                self.send_json({"status": "saved", "config": load_visibility_config()})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)

        elif path == "/api/avatar":
            if not self._check_localhost_origin():
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                data = json.loads(body) if body else {}
            except (json.JSONDecodeError, ValueError):
                self.send_json({"error": "invalid JSON"}, status=400)
                return
            from nextmillionai.paths import data_dir

            avatar_file = os.path.join(str(data_dir()), "avatar")
            avatar_val = data.get("avatar")
            if avatar_val and isinstance(avatar_val, str) and avatar_val.startswith("data:image/"):
                with open(avatar_file, "w") as f:
                    f.write(avatar_val)
                self.send_json({"status": "saved"})
            elif avatar_val is None:
                if os.path.isfile(avatar_file):
                    os.remove(avatar_file)
                self.send_json({"status": "cleared"})
            else:
                self.send_json({"error": "invalid avatar data"}, status=400)

        elif path == "/api/profile/rebuild":
            if not self._check_localhost_origin():
                return
            try:
                subprocess.run(
                    [sys.executable, "-m", "nextmillionai"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                profile = load_profile()
                self.send_json({"status": "rebuilt", "intent_score": profile.get("intent_score")})
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, status=500)

        else:
            self.send_response(404)
            self.end_headers()


class ThreadedHTTPServer(http.server.HTTPServer):
    allow_reuse_address = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self._handle, args=(request, client_address))
        t.daemon = True
        t.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def pick_port(requested=None, attempts=20):
    """First available port at or above *requested* (default 7749).

    Local bind probe only — lets `report` start cleanly when another
    instance (or anything else) already holds the default port.
    """
    import socket

    start = requested or _get_port()
    for offset in range(attempts):
        candidate = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("localhost", candidate))
            return candidate
        except OSError:
            continue
    return start  # let the server raise the honest error


def run_server(port=None, live=False, open_browser=False):
    if port is None:
        port = _get_port()
    os.environ["PORT"] = str(port)
    server = ThreadedHTTPServer(("localhost", port), ProfileHandler)

    # Graceful SIGTERM: terminal "kill" buttons (Cursor/VS Code trash icon),
    # `kill <pid>`, and `lsof -ti:PORT | xargs kill` all send SIGTERM. Convert
    # it into the same KeyboardInterrupt path that Ctrl+C (SIGINT) already takes
    # so shutdown runs cleanly instead of terminating hard. Signal handlers can
    # only be installed on the main thread — guarded so run_server stays usable
    # when called from a worker thread (e.g. tests).
    try:
        import signal

        def _request_shutdown(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _request_shutdown)
    except (ValueError, OSError):
        pass

    if open_browser:
        import threading as _threading
        import webbrowser

        _threading.Timer(0.6, lambda: webbrowser.open(f"http://localhost:{port}/profile")).start()

    # ── Live watcher: DEFERRED POST-LAUNCH — disabled, do not re-enable ──────
    # Live mode (`--live`) is hidden for launch; the file-watcher is not shipped
    # yet. Kept inert here (the `live` arg is accepted but ignored) so the
    # server never imports/starts the watcher. Re-enable by restoring the block
    # below once live mode is ready.
    watcher = None
    live_line = ""
    # if live:
    #     from nextmillionai.live import start_watcher
    #
    #     watcher = start_watcher()
    #     live_line = "\n    Live:     watching local sources — views update in place\n"

    print(f"""
    nextmillionai -- Profile Server
{live_line}
    Profile:  http://localhost:{port}/profile
    Report:   http://localhost:{port}/report
    Preview:  http://localhost:{port}/preview

    API:
    GET  /api/profile        - full profile JSON (localhost)
    GET  /api/profile/public - shareable profile (derived-only)
    GET  /api/profile.json   - agent-crawlable JSON-LD
    GET  /api/profile/meta   - discovery metadata
    GET  /api/scan-results   - raw scan data JSON
    GET  /api/profile/config  - visibility config
    GET  /api/live/status     - live watcher state
    GET  /api/live/events     - SSE status stream (live mode)
    POST /api/profile/config  - update visibility config
    POST /api/profile/rebuild - rescan + rescore

    Press Ctrl+C to stop
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n    Server stopped.")
        if watcher is not None:
            watcher.stop()
        server.server_close()


if __name__ == "__main__":
    run_server()
