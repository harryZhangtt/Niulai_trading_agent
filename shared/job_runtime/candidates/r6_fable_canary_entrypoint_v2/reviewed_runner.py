"""Deferred real-bridge adapter; importing this module never imports the SDK."""
from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path
import threading
from types import MappingProxyType


EXPECTED_PROFILE = MappingProxyType({
    "model": "claude-fable-5-1",
    "effort": "low",
    "max_budget_usd": 0.02,
    "timeout_seconds": 5,
    "auth_home": ".job-runtime/auth",
})
_AUTH_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
_ENV_LOCK = threading.Lock()


def make_reviewed_runner(expected_config_sha256, bridge_resolver=None):
    """Return a one-shot runner with a minimal child environment boundary."""
    if type(expected_config_sha256) is not str or len(expected_config_sha256) != 64:
        raise ValueError("FABLE_CANARY_CONFIG_DRIFT")
    expected_profile = dict(EXPECTED_PROFILE)
    if bridge_resolver is None:
        import_module = importlib.import_module
        def resolver():
            return import_module("shared.job_runtime.claude_bridge").run_claude_host
    else:
        resolver = bridge_resolver
    used = [False]
    environ = os.environ
    environment_lock = _ENV_LOCK

    def run_claude_host(profile, prompt, workspace, run_dir, operation_id, context):
        if used[0]:
            raise ValueError("FABLE_CANARY_RUNNER_REPLAY_REJECTED")
        used[0] = True
        if type(profile) is not dict or profile != expected_profile:
            raise ValueError("FABLE_CANARY_PROFILE_DRIFT")
        if type(prompt) is not str or not prompt or type(operation_id) is not str:
            raise ValueError("FABLE_CANARY_INVOCATION_INVALID")
        workspace_path = Path(workspace).resolve(strict=True)
        auth_home = (workspace_path / expected_profile["auth_home"]).resolve(strict=True)
        auth_info = auth_home.stat()
        if (not auth_home.is_relative_to(workspace_path / ".job-runtime")
                or not stat.S_ISDIR(auth_info.st_mode)
                or auth_info.st_uid != os.getuid()
                or stat.S_IMODE(auth_info.st_mode) != 0o700):
            raise ValueError("FABLE_CANARY_AUTH_HOME_INVALID")
        prompt_bytes = prompt.encode("utf-8", errors="strict")
        bridge_profile = dict(expected_profile)
        bridge_profile["auth_home"] = str(auth_home)
        bridge = resolver()
        with environment_lock:
            original = dict(environ)
            bounded = {key: original[key] for key in _AUTH_ENV if key in original}
            bounded.update({"HOME": str(auth_home), "PATH": "/usr/bin:/bin",
                            "PYTHONNOUSERSITE": "1"})
            try:
                environ.clear()
                environ.update(bounded)
                return bridge(bridge_profile, prompt_bytes, workspace_path,
                              run_dir, operation_id, context)
            finally:
                environ.clear()
                environ.update(original)

    return run_claude_host


__all__ = ["EXPECTED_PROFILE", "make_reviewed_runner"]
