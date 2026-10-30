"""Owner-validated bridge to the existing private Tiger OAuth store.

No consent, seeding, force-refresh, trading, or standalone credential copy API.
Run in a dedicated process; the legacy SDK callback is bound only in memory.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import select
import sys
import tempfile
import time
import types
from urllib import error, parse, request
import uuid
from .queries import execute_query, validate_query


class TigerBridgeError(RuntimeError):
    """Only fixed, credential-free error codes may cross the CLI boundary."""


class TigerDeadline(BaseException):
    """Bypass per-request SDK exception handlers when the run budget expires."""


def require(condition, code):
    if not condition:
        raise TigerBridgeError(code)


def safe_failure(exc):
    report = {"status": "failed", "error": "TIGER_BRIDGE_FAILED", "reauthorization_assumed_required": False}
    if isinstance(exc, TigerDeadline):
        report["error"] = "TIGER_RUN_DEADLINE"
    elif isinstance(exc, TigerBridgeError):
        report["error"] = str(exc)
    else:
        n = sys.modules.get("niulai_tiger")
        if n is not None and isinstance(exc, getattr(n, "ReadOnlyError", ())):
            # Explicit authorization/preflight codes only, not arbitrary provider text.
            allowed = {"LOGIN_REQUIRED", "REAUTHORIZATION_REQUIRED", "QUOTE_READ_CONSENT_REQUIRED",
                       "TOKEN_SCOPE_REJECTED", "PROFILE_BUSY", "ISSUER_MISMATCH", "SDK_VERSION_MISMATCH",
                       "OAUTH_ENDPOINT_MISMATCH", "READ_SCOPES_UNAVAILABLE", "READ_ENDPOINT_ONLY"}
            if str(exc) in allowed:
                report["error"] = str(exc)
        if type(exc).__module__.startswith("tigeropen."):
            for attr in ("error", "code", "error_code"):
                observed = getattr(exc, attr, None)
                if isinstance(observed, str) and observed in {"invalid_grant", "invalid_token", "access_denied"}:
                    report["provider_error"] = observed
            observed_status = getattr(exc, "status", None)
            if type(observed_status) is int and 100 <= observed_status <= 599:
                report["provider_http_status"] = observed_status
    return report


def private_directory(path: Path, root: Path) -> Path:
    root = root.resolve()
    require(root.is_dir(), "WORKSPACE_MISSING")
    candidate = Path(os.path.abspath(path))
    require(candidate.is_relative_to(root) and candidate != root, "PATH_OUTSIDE_WORKSPACE")
    for part in [candidate, *candidate.parents]:
        if part == root:
            break
        require(not part.is_symlink(), "PRIVATE_PATH_SYMLINK")
        if part.exists():
            require(part.is_dir() and part.stat().st_uid == os.getuid(), "PRIVATE_PATH_OWNER")
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    # All task-owned private parents, not the workspace itself.
    for part in [candidate, *candidate.parents]:
        if part == root:
            break
        part.chmod(0o700)
    return candidate


def write_json(path: Path, value):
    require(not path.is_symlink(), "PRIVATE_FILE_SYMLINK")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_policy(path, workspace):
    """Read only an owner-private regular file without following symlinks."""
    import stat
    root = Path(workspace).resolve() / ".niulai-state"
    path = Path(os.path.abspath(path))
    require(path.is_relative_to(root) and path.resolve().is_relative_to(root), "PRIVATE_POLICY_REQUIRED")
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        require(not parent.is_symlink(), "PRIVATE_POLICY_REQUIRED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
                and st.st_mode & 0o077 == 0 and st.st_size <= 65536, "PRIVATE_POLICY_REQUIRED")
        policy = json.load(stream)
    require(isinstance(policy, dict), "TIGER_POLICY_INCOMPLETE")
    return policy


def validate_site(site: dict, policy: dict) -> dict:
    """Validate a fresh native get_site structured result, never a saved bearer."""
    require(isinstance(site, dict) and isinstance(policy, dict), "TIGER_POLICY_INCOMPLETE")
    required = {"project_id", "origin", "owner_email"}
    require(required <= policy.keys(), "TIGER_POLICY_INCOMPLETE")
    origin = policy["origin"]
    url = parse.urlsplit(origin)
    require(url.scheme == "https" and url.hostname and url.hostname.endswith(".chatgpt.site")
            and not url.username and not url.password and not url.port
            and not url.path and not url.query and not url.fragment, "TIGER_ORIGIN_REJECTED")
    require(site.get("id") == policy["project_id"] and site.get("current_user_role") == "owner"
            and site.get("status") == "active", "TIGER_SITE_IDENTITY_REJECTED")
    require(site.get("current_live_url", "").rstrip("/") == origin, "TIGER_SITE_ORIGIN_MISMATCH")
    access = site.get("access_policy") or {}
    require(site.get("access_mode") == "custom" and access.get("access_mode") == "custom"
            and access.get("project_id") == policy["project_id"], "TIGER_SITE_NOT_PRIVATE")
    users = access.get("allowed_users")
    require(isinstance(users, list) and len(users) == 1, "TIGER_SITE_AUDIENCE_REJECTED")
    owner = users[0]
    require(owner.get("email") == policy["owner_email"] and owner.get("role") == "owner"
            and not owner.get("is_external") and not owner.get("pending"), "TIGER_SITE_OWNER_REJECTED")
    require(access.get("allowed_account_user_ids") == [owner.get("account_user_id")]
            and bool(owner.get("account_user_id")), "TIGER_SITE_ALLOWLIST_REJECTED")
    require(not access.get("allowed_groups") and not access.get("allowed_workspace_group_ids")
            and not access.get("allowed_tenant_group_ids") and access.get("external_visitor_count", 0) == 0,
            "TIGER_SITE_SHARED")
    require(all(e.get("account_user_id") == owner["account_user_id"] and e.get("role") == "owner"
                and not e.get("is_external") and not e.get("pending")
                for e in access.get("allowed_editors", [])), "TIGER_SITE_EDITORS_REJECTED")
    bearer = site.get("siwc_bypass_bearer_token")
    require(isinstance(bearer, str) and bearer and "\n" not in bearer and "\r" not in bearer,
            "TIGER_SERVICE_ACCESS_MISSING")
    return {"origin": origin, "bearer": bearer}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class StoreClient:
    """Retries reuse serialized idempotency keys; never calls OAuth endpoints."""
    def __init__(self, session, *, opener=None, sleep=time.sleep):
        self.session = session
        self.opener = opener or request.build_opener(NoRedirect())
        self.sleep = sleep

    def rpc(self, path, body=None):
        require(path in ("/lease/acquire", "/lease/checkpoint", "/lease/release"), "STORE_ROUTE_REJECTED")
        require(isinstance(body, dict), "STORE_BODY_REQUIRED")
        # Acquire/checkpoint have server protocol idempotency identities. Release
        # has no operation identity and is attempted once, never blindly retried.
        stable = (path == "/lease/acquire" and bool(body.get("request_id"))) or (
            path == "/lease/checkpoint" and bool(body.get("commit_id")) and bool(body.get("lease_id")))
        raw = json.dumps(body, sort_keys=True).encode()
        req = request.Request(self.session["origin"] + path, data=raw, method="POST", headers={
            "OAI-Sites-Authorization": "Bearer " + self.session["bearer"], "Content-Type": "application/json"})
        attempts = 3 if stable else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(req, timeout=15) as response:
                    raw_response = response.read(2 * 1024 * 1024 + 1)
                    require(len(raw_response) <= 2 * 1024 * 1024, "STORE_RESPONSE_INVALID")
                    result = json.loads(raw_response)
                    require(isinstance(result, dict), "STORE_RESPONSE_INVALID")
                    return result
            except error.HTTPError as exc:
                code = "STORE_HTTP_" + str(exc.code)
                transient = exc.code in (408, 429, 500, 502, 503, 504)
                if not transient or attempt + 1 == attempts:
                    raise TigerBridgeError(code) from None
            except (error.URLError, TimeoutError):
                if attempt + 1 == attempts:
                    raise TigerBridgeError("STORE_NETWORK_OUTCOME_UNCONFIRMED") from None
            except (ValueError, UnicodeError):
                raise TigerBridgeError("STORE_RESPONSE_INVALID") from None
            self.sleep((1, 2)[attempt])


def restore_profile(profile: Path, value):
    require(isinstance(value, dict) and isinstance(value.get("files"), dict) and value["files"],
            "STORE_PROFILE_MISSING")
    for relative, text in value["files"].items():
        p = Path(relative)
        allowed = (len(p.parts) == 1 and relative in ("account-refs.json", "account-pin.json")) or (
            len(p.parts) >= 2 and p.parts[0] in ("tokens", "clients") and p.suffix == ".json")
        require(not p.is_absolute() and ".." not in p.parts and allowed, "PROFILE_PATH_REJECTED")
        require(isinstance(text, str) and len(text) < 1024 * 1024, "PROFILE_CONTENT_REJECTED")
        target = profile / p
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for parent in [target.parent, *target.parent.parents]:
            if parent == profile.parent:
                break
            require(not parent.is_symlink(), "PROFILE_SYMLINK_REJECTED")
            parent.chmod(0o700)
        write_json(target, json.loads(text))


def collect_profile(profile: Path):
    files = {}
    for p in profile.rglob("*"):
        require(not p.is_symlink(), "PROFILE_SYMLINK_REJECTED")
        if p.is_file() and p.suffix == ".json":
            rel = p.relative_to(profile)
            if (len(rel.parts) == 1 and p.name in ("account-refs.json", "account-pin.json")) or (
                    len(rel.parts) > 1 and rel.parts[0] in ("clients", "tokens")):
                text = p.read_text()
                json.loads(text)
                files[str(rel)] = text
    require(bool(files), "PROFILE_EMPTY")
    return {"files": files}


def stage_source(workspace: Path, staging: Path, taxonomy=None):
    """Copy code into a private run directory; imports must not write snapshot."""
    source = workspace / "niulai" / "holdings"
    require(source.is_dir(), "HOLDINGS_SOURCE_MISSING")
    staging.mkdir(mode=0o700)
    for p in source.glob("*.py"):
        require(not p.is_symlink(), "SOURCE_SYMLINK_REJECTED")
        shutil.copyfile(p, staging / p.name)
    if (source / "fonts").is_dir():
        require(not any(p.is_symlink() for p in (source / "fonts").rglob("*")), "SOURCE_SYMLINK_REJECTED")
        shutil.copytree(source / "fonts", staging / "fonts")
    if taxonomy:
        p = Path(taxonomy)
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(workspace), "TAXONOMY_REJECTED")
        shutil.copyfile(p, staging / "taxonomy.json")


def run_bridge(workspace, policy, site, out, mode="verify", *, query=None):
    require(mode in ("verify", "run", "query"), "TIGER_MODE_REJECTED")
    if mode == "query":
        query = validate_query(query, require)  # Before any lease, fence or credential IO.
    workspace = Path(workspace).resolve()
    requested_out = Path(os.path.abspath(out))
    require(requested_out.is_relative_to(workspace / ".niulai-state")
            and requested_out.resolve().is_relative_to(workspace / ".niulai-state"), "OUTPUT_NOT_PRIVATE_STATE")
    state = private_directory(workspace / ".niulai-state" / "tiger", workspace)
    out = private_directory(requested_out, workspace)
    session = validate_site(site, policy)
    # A previous uncertainty must not be resolved by a fresh profile/token copy.
    blocker = state / "unresolved.json"
    require(not blocker.exists(), "TIGER_PRIOR_OUTCOME_REQUIRES_RECONCILIATION")
    import fcntl
    fd = os.open(state / "bridge.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TigerBridgeError("TIGER_BRIDGE_BUSY") from None
        require(not blocker.exists(), "TIGER_PRIOR_OUTCOME_REQUIRES_RECONCILIATION")
        if mode == "query":
            require(not any((out / name).exists() for name in (
                "tiger_status.json", "query.json", "holdings.json", "assets.json")), "TIGER_OUTPUT_EXISTS")
        try:
            return _run_locked(workspace, state, out, mode, policy, session, blocker, query=query)
        except BaseException as exc:
            write_json(out / "tiger_status.json", {**safe_failure(exc), "mode": mode,
                       "automatic_retry": False, "reconciliation_required": blocker.exists()})
            raise
    finally:
        os.close(fd)


def _run_locked(workspace, state, out, mode, policy, session, blocker, *, query=None):
    client = StoreClient(session)
    attempt_id = str(uuid.uuid4())
    # Crash fence starts BEFORE remote acquisition; no automatic replay after crash.
    write_json(blocker, {"attempt_id": attempt_id, "phase": "acquiring", "automatic_retry": False})
    try:
        lease = client.rpc("/lease/acquire", {"request_id": attempt_id})
    except TigerBridgeError as exc:
        # Sites rejected service authorization before the lease operation. A fresh
        # native service token is appropriate; this is not Tiger consent failure.
        if str(exc) in ("STORE_HTTP_401", "STORE_HTTP_403"):
            blocker.unlink()
        raise
    require(isinstance(lease.get("lease_id"), str) and lease["lease_id"], "STORE_LEASE_INVALID")
    lease_id = lease["lease_id"]
    run_dir = Path(tempfile.mkdtemp(dir=state, prefix="attempt-"))
    run_dir.chmod(0o700)
    profile = run_dir / "profile"
    profile.mkdir(mode=0o700)
    released = False
    old_path = list(sys.path)
    old_marker = os.environ.get("NIULAI_PROFILE_SESSION_JSON")
    previous_shim = sys.modules.get("private_profile")
    try:
        restore_profile(profile, lease.get("profile"))
        stage_source(workspace, run_dir / "code", policy.get("taxonomy"))
        sys.path.insert(0, str(run_dir / "code"))
        n = importlib.import_module("niulai_tiger")
        write_json(blocker, {"attempt_id": attempt_id, "phase": "broker_read", "automatic_retry": False,
                             "profile_retained": str(run_dir.relative_to(workspace))})

        def checkpoint(path, release=False):
            require(Path(path).resolve() == profile.resolve(), "CHECKPOINT_PROFILE_MISMATCH")
            commit_id = str(uuid.uuid4())
            write_json(blocker, {"attempt_id": attempt_id, "phase": "checkpoint", "commit_id": commit_id,
                                 "automatic_retry": False, "profile_retained": str(run_dir.relative_to(workspace))})
            receipt = client.rpc("/lease/checkpoint", {"lease_id": lease_id, "commit_id": commit_id,
                                                       "profile": collect_profile(profile), "release": release})
            require(receipt.get("committed") is True, "STORE_COMMIT_UNCONFIRMED")
            return {"committed": True, "release_requested": release}

        shim = types.ModuleType("private_profile")
        shim.checkpoint_from_environment = checkpoint
        # Marker only: legacy ReadSession tests its presence. No bearer in env.
        os.environ["NIULAI_PROFILE_SESSION_JSON"] = "runtime-memory-callback"
        sys.modules["private_profile"] = shim
        if mode in ("verify", "query"):
            actual_query = query if mode == "query" else validate_query({"tool": "snapshot", "arguments": {}}, require)
            result = execute_query(n, profile, actual_query, require, write_json, out)
            if mode == "verify":
                result["status"] = "verified"
        else:
            require((run_dir / "code" / "taxonomy.json").is_file(), "PRIVATE_TAXONOMY_REQUIRED")
            pipeline = importlib.import_module("daily_compact_pipeline")
            pipeline.preflight(profile)
            fetch = importlib.import_module("fetch_five_day")
            with contextlib.redirect_stdout(io.StringIO()):
                fetch.main(out, 1, str(profile))
                result = pipeline.build_report(out)
            result["email_status"] = "not_sent"
        result.update(checkpoint(profile, True))
        released = True
        result.update(mode=mode, authorization_prompted=False, broker_retries_added=0,
                      source="existing_owner_private_store", attempt_id=attempt_id)
        write_json(out / "tiger_status.json", result)
        blocker.unlink()
        return result
    except Exception as exc:
        # Do not release an uncertain remote lease, wipe newly rotated local
        # tokens, or create a second refresh writer. Human reconciliation needed.
        write_json(out / "tiger_status.json", {**safe_failure(exc), "mode": mode,
                   "automatic_retry": False, "reauthorization_assumed_required": False,
                   "reconciliation_required": True})
        raise
    finally:
        sys.path[:] = old_path
        if previous_shim is None:
            sys.modules.pop("private_profile", None)
        else:
            sys.modules["private_profile"] = previous_shim
        if old_marker is None:
            os.environ.pop("NIULAI_PROFILE_SESSION_JSON", None)
        else:
            os.environ["NIULAI_PROFILE_SESSION_JSON"] = old_marker
        if released:
            shutil.rmtree(run_dir)


def hidden_input(*, timeout_seconds=120, max_bytes=1024 * 1024):
    import termios
    require(sys.stdin.isatty(), "PRIVATE_STDIN_TTY_REQUIRED")
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = list(old)
    # macOS canonical input has a small line limit. A full Sites response can
    # exceed it, so read bounded raw bytes with echo disabled. Keep ISIG for ^C.
    new[3] &= ~(termios.ECHO | termios.ICANON)
    new[6] = list(old[6])
    new[6][termios.VMIN] = 1
    new[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, new)
    try:
        print("Ready for fresh owner-validated Sites JSON on hidden stdin.", flush=True)
        deadline = time.monotonic() + timeout_seconds
        chunks = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "PRIVATE_STDIN_TIMEOUT")
            ready, _, _ = select.select([fd], [], [], remaining)
            require(bool(ready), "PRIVATE_STDIN_TIMEOUT")
            chunk = os.read(fd, min(65536, max_bytes + 1 - len(chunks)))
            require(bool(chunk), "PRIVATE_STDIN_EOF")
            chunks.extend(chunk)
            require(len(chunks) <= max_bytes, "PRIVATE_STDIN_TOO_LARGE")
            if b"\n" in chunks:
                line, tail = bytes(chunks).split(b"\n", 1)
                require(not tail.strip(), "PRIVATE_STDIN_EXTRA_DATA")
                break
        value = json.loads(line)
        require(isinstance(value, dict), "SITE_RESPONSE_INVALID")
        return value
    finally:
        # Discard any queued remainder before re-enabling echo (oversized or
        # cancelled input must not later appear in a canonical terminal line).
        termios.tcflush(fd, termios.TCIFLUSH)
        termios.tcsetattr(fd, termios.TCSANOW, old)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("verify", "run"), default="verify")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        policy = load_policy(args.policy, args.workspace)
        site = hidden_input()
        def deadline(signum, frame):
            raise TigerDeadline()
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(600)
        try:
            result = run_bridge(args.workspace, policy, site, args.out, args.mode)
        finally:
            signal.alarm(0)
        print(json.dumps(result))
        return 0
    except (Exception, TigerDeadline) as exc:
        print(json.dumps(safe_failure(exc)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
