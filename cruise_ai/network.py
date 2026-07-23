"""
cruise_ai.network -- Opt-in network publish/unpublish client.

THE ONLY MODULE IN THIS PACKAGE THAT MAKES OUTBOUND NETWORK CALLS.

It is never imported by the assessment path (calibrate/assess/report/
enrich/export run fully local). Publishing happens only when the user
runs `cruise_ai publish` and explicitly confirms. What is sent is
the same redacted, visibility-filtered shareable JSON used by export —
derived data only: never raw code, transcripts, prompts, hidden
projects, private growth, or experimental signals. Publishing is
revocable: `cruise_ai unpublish` deletes the record.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from cruise_ai.export import verify_artifact_json
from cruise_ai.paths import data_dir, profile_path
from cruise_ai.schema import build_shareable_profile
from cruise_ai.visibility import load_visibility_config

# No hosted cruise_ai registry exists yet (roadmap). Default points
# at a self-hosted reference registry (`cruise_ai network serve`).
DEFAULT_REGISTRY = "http://localhost:7750"
_TIMEOUT_S = 20


def publish_state_path() -> Path:
    return data_dir() / "publish_state.json"


def load_publish_state() -> dict | None:
    p = publish_state_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def build_publish_payload() -> dict:
    """The exact payload that would be published: redacted + verified.

    Raises RuntimeError if no assessment exists or verification finds
    private data (publish refuses rather than scrubbing silently).
    """
    src = profile_path()
    if not src.is_file():
        from cruise_ai.paths import cli_invocation

        raise RuntimeError(f"No assessment found. Run `{cli_invocation()} assess` first.")

    with open(src) as f:
        profile = json.load(f)

    shareable = build_shareable_profile(profile, load_visibility_config())
    violations = verify_artifact_json(shareable)
    if violations:
        raise RuntimeError(
            "Refusing to publish: private data detected: " + "; ".join(violations[:5])
        )
    return shareable


def _request(
    method: str, url: str, body: dict | None = None, token: str | None = None
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode() or "{}")
            return resp.status, payload
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except (json.JSONDecodeError, ValueError):
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, OSError) as e:
        from cruise_ai.paths import cli_invocation

        raise RuntimeError(
            f"Could not reach registry at {url}: {e}. "
            f"Is a registry running? Start one with `{cli_invocation()} network serve`."
        ) from e


def registry_reachable(registry: str | None = None, timeout: float = 3.0) -> bool:
    """Quick health probe — lets `publish` fail BEFORE the consent
    ceremony instead of after the user typed 'publish'."""
    registry = (registry or DEFAULT_REGISTRY).rstrip("/")
    req = urllib.request.Request(f"{registry}/v1/health", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return bool(resp.status == 200)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def publish(registry: str | None = None) -> dict:
    """Publish (or republish) the curated shareable profile.

    Returns {builderId, registry, sections}. The caller is responsible
    for having obtained explicit user confirmation FIRST.
    """
    registry = (registry or DEFAULT_REGISTRY).rstrip("/")
    payload = build_publish_payload()

    state = load_publish_state()
    if state and state.get("registry") == registry:
        # Republish: update the existing record (idempotent)
        status, resp = _request(
            "PUT",
            f"{registry}/v1/builders/{state['builderId']}",
            body={"profile": payload},
            token=state.get("revokeToken"),
        )
        if status == 200:
            state["sections"] = sorted(payload.keys())
            state["updatedAt"] = resp.get("updatedAt")
            publish_state_path().write_text(json.dumps(state, indent=2))
            return {
                "builderId": state["builderId"],
                "registry": registry,
                "sections": state["sections"],
                "updated": True,
            }
        if status != 404:
            raise RuntimeError(f"Registry rejected republish ({status}): {resp.get('error', '')}")
        # 404: record gone server-side — fall through to a fresh publish

    status, resp = _request("POST", f"{registry}/v1/builders", body={"profile": payload})
    if status != 201:
        raise RuntimeError(f"Registry rejected publish ({status}): {resp.get('error', '')}")

    state = {
        "registry": registry,
        "builderId": resp["builderId"],
        "revokeToken": resp["revokeToken"],
        "publishedAt": resp.get("publishedAt"),
        "sections": sorted(payload.keys()),
    }
    publish_state_path().write_text(json.dumps(state, indent=2))
    return {
        "builderId": resp["builderId"],
        "registry": registry,
        "sections": state["sections"],
        "updated": False,
    }


# ── Multi-device sync (user's own git repo — explicit, derived-only,
#    revocable). Transport is the git binary; this stays in network.py
#    because pushing to a remote is an outbound operation, exactly like
#    publish. The merge logic itself is local (sync_merge.py). ──────────────


def sync_config_path() -> Path:
    return data_dir() / "sync_config.json"


def load_sync_config() -> dict | None:
    p = sync_config_path()
    if not p.is_file():
        return None
    try:
        cfg = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("repoUrl") else None


def _sync_repo_dir() -> Path:
    from cruise_ai.paths import user_home

    return user_home() / "sync_repo"


def _git(args: list, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    """Run git non-interactively; never let it prompt for credentials."""
    import os
    import subprocess

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, (proc.stderr or proc.stdout or "").strip()
    except FileNotFoundError:
        return 127, "git binary not found"
    except subprocess.TimeoutExpired:
        return 124, "git timed out (offline or unreachable remote?)"


def _sync_error(out: str) -> RuntimeError:
    low = out.lower()
    if "terminal prompts disabled" in low or "authentication" in low or "403" in low:
        return RuntimeError(
            "GitHub auth failed. Sync needs push access to YOUR repo — set up "
            "an SSH key or a credential helper (e.g. `gh auth setup-git`), then "
            "retry. Local assessment is unaffected."
        )
    if "could not resolve host" in low or "unable to access" in low or "timed out" in low:
        return RuntimeError(
            "Could not reach the sync repo (offline?). Sync deferred — your "
            "local assessment still works; run `sync` again when online."
        )
    return RuntimeError(f"git failed: {out[:300]}")


def _ensure_sync_clone(repo_url: str) -> Path:
    """Clone (or refresh) the user's sync repo into the local cache."""
    repo_dir = _sync_repo_dir()
    if not (repo_dir / ".git").is_dir():
        code, out = _git(["clone", "--depth", "1", repo_url, str(repo_dir)])
        if code != 0:
            raise _sync_error(out)
        return repo_dir
    code, out = _git(["fetch", "origin"], cwd=repo_dir)
    if code != 0:
        raise _sync_error(out)
    # Other devices' files only change on their machines; ours is
    # rewritten below — remote state is the truth to start from.
    code, out = _git(["reset", "--hard", "origin/HEAD"], cwd=repo_dir)
    if code != 0:
        code2, out2 = _git(["reset", "--hard", "FETCH_HEAD"], cwd=repo_dir)
        if code2 != 0:
            raise _sync_error(out2 or out)
    return repo_dir


_SYNC_README = """# cruise_ai sync store

Derived-only multi-device snapshots written by `cruise_ai sync`.
One JSON per device: session IDs + per-day counts, per-repo commit-day
counts, repo names. No prompts, transcripts, code, or file paths.
Remove a device with `cruise_ai sync --revoke` on that device.
"""


def sync_run(repo_url: str | None = None) -> dict:
    """Push this device's snapshot, pull every device's, mirror locally.

    Last-write-wins per device file (each device only writes its own).
    Returns {devices, pushed, repo}. Raises RuntimeError with a friendly
    message on auth/offline failures — callers must leave local use
    untouched.
    """
    import shutil

    from cruise_ai.sync_merge import device_identity, devices_dir, write_own_snapshot

    cfg = load_sync_config()
    if repo_url:
        from cruise_ai.scanner import iso_now

        cfg = {"repoUrl": repo_url, "configuredAt": iso_now()}
        sync_config_path().write_text(json.dumps(cfg, indent=2))
    if not cfg:
        raise RuntimeError(
            "No sync repo configured. Run `cruise_ai sync --repo "
            "git@github.com:YOU/your-private-sync-repo.git` (a PRIVATE repo "
            "you own)."
        )

    repo_dir = _ensure_sync_clone(cfg["repoUrl"])
    dev_dir = repo_dir / "devices"
    dev_dir.mkdir(exist_ok=True)

    # Write our snapshot into the repo
    own = write_own_snapshot()  # also refreshes the local mirror
    ident = device_identity()
    (dev_dir / own.name).write_text(own.read_text())
    readme = repo_dir / "README.md"
    if not readme.is_file():
        readme.write_text(_SYNC_README)

    pushed = False
    code, out = _git(["add", "-A"], cwd=repo_dir)
    if code != 0:
        raise _sync_error(out)
    code, out = _git(["status", "--porcelain"], cwd=repo_dir)
    if out.strip():
        code, out = _git(
            [
                "-c",
                "user.name=cruise_ai-sync",
                "-c",
                "user.email=sync@localhost",
                "commit",
                "-m",
                f"sync from {ident['deviceName']}",
            ],
            cwd=repo_dir,
        )
        if code != 0:
            raise _sync_error(out)
        code, out = _git(["push", "origin", "HEAD"], cwd=repo_dir)
        if code != 0:
            # One retry after re-syncing with the remote (another device
            # may have pushed in between)
            _ensure_sync_clone(cfg["repoUrl"])
            (dev_dir / own.name).write_text(own.read_text())
            _git(["add", "-A"], cwd=repo_dir)
            _git(
                [
                    "-c",
                    "user.name=cruise_ai-sync",
                    "-c",
                    "user.email=sync@localhost",
                    "commit",
                    "-m",
                    f"sync from {ident['deviceName']}",
                ],
                cwd=repo_dir,
            )
            code, out = _git(["push", "origin", "HEAD"], cwd=repo_dir)
            if code != 0:
                raise _sync_error(out)
        pushed = True

    # Mirror every device snapshot locally (assessment reads this dir)
    mirror = devices_dir()
    count = 0
    for f in sorted(dev_dir.glob("*.json")):
        shutil.copyfile(str(f), str(mirror / f.name))
        count += 1

    return {"devices": count, "pushed": pushed, "repo": cfg["repoUrl"]}


def sync_revoke() -> str:
    """Remove THIS device from the sync store (repo + local mirror)."""
    from cruise_ai.sync_merge import device_identity, devices_dir

    cfg = load_sync_config()
    ident = device_identity()
    fname = f"{ident['deviceId']}.json"

    if cfg:
        repo_dir = _ensure_sync_clone(cfg["repoUrl"])
        target = repo_dir / "devices" / fname
        if target.is_file():
            target.unlink()
            _git(["add", "-A"], cwd=repo_dir)
            code, out = _git(
                [
                    "-c",
                    "user.name=cruise_ai-sync",
                    "-c",
                    "user.email=sync@localhost",
                    "commit",
                    "-m",
                    f"revoke device {ident['deviceName']}",
                ],
                cwd=repo_dir,
            )
            if code != 0:
                raise _sync_error(out)
            code, out = _git(["push", "origin", "HEAD"], cwd=repo_dir)
            if code != 0:
                raise _sync_error(out)

    # Local cleanup: our snapshot, pulled snapshots, config
    for f in devices_dir().glob("*.json"):
        f.unlink()
    sync_config_path().unlink(missing_ok=True)
    return (
        "Device removed from the sync store; local mirror and sync config "
        "cleared. Other devices keep their own snapshots."
    )


def unpublish() -> str:
    """Revoke: delete the published record and local publish state."""
    state = load_publish_state()
    if not state:
        return "Not published — nothing to unpublish."

    status, resp = _request(
        "DELETE",
        f"{state['registry']}/v1/builders/{state['builderId']}",
        token=state.get("revokeToken"),
    )
    if status in (200, 204, 404):  # 404 = already gone server-side
        publish_state_path().unlink(missing_ok=True)
        return "Unpublished. Your profile was removed from the registry."
    raise RuntimeError(f"Registry refused unpublish ({status}): {resp.get('error', '')}")
