"""OFF-only reviewed-real-bridge canary entrypoint v2.

Threat model: cooperative same-user/test-only staging.  Descriptor custody closes
ordinary pathname races, module-global replacement and callback replacement after
admission.  Malicious Python reflection, process-memory mutation, ptrace/debugger
control, kernel compromise, and hostile code already executing as this UID are
explicitly out of scope.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
from types import MappingProxyType, SimpleNamespace

from shared.job_runtime.provider_contract import ProviderResultV1
from .reviewed_runner import EXPECTED_PROFILE, make_reviewed_runner


class CanaryEntrypointError(ValueError):
    """Stable local denial; never includes filesystem or callback text."""


CANDIDATE_ID = "r6-fable-canary-entrypoint-v2"
_PACKAGE = Path(__file__).absolute().parent
_JOB_RUNTIME = _PACKAGE.parents[1]
_REPO = _PACKAGE.parents[3]
_AUTHORITY_SOURCE = _PACKAGE / "review_authority.json"
_BRIDGE_COMPAT_SOURCE = _JOB_RUNTIME / "claude_bridge.py"
_SOURCE_CLOSURE_SOURCE = _PACKAGE / "source_closure.json"
_RUNTIME_LOCK_SOURCE = _JOB_RUNTIME / "candidates" / "claude_sdk_0_2_179_py312_macos_arm64_v1" / "post_install_runtime_lock_v2.json"
_EXPECTED_PREFLIGHT_SHA256 = "44f29e81f7c00374a9b540c9d768233b92e8c0dbf775c697a9ee682f985b330b"
_EXPECTED_RUNTIME_LOCK_SHA256 = "f6334dd1ef9b696ef397feeedf20c3777c8ab7e19cdd2d978876bb3abcdef9c5"
_EXPECTED_BRIDGE_SHA256 = "da48b5a9c521ce4463d96f633d6a8971a7735dca88aa4dc068077d13102233c3"
_EXPECTED_TREE_SHA256 = "96ca6774cfa68c0306336fc40268ed4afc18f09e4102210098c9aed699fde423"
_EXPECTED_RECORD_RAW_SHA256 = "17b64b092f6a3af6273ce3de9a34e2a7b20183ac61b1e4aa47f2705298571ad8"
_EXPECTED_RECORD_TEXT_SHA256 = "4476d8b36aee0f444ca3ebc09ba8d1d466de35d0ac08c8cd359ba3aaf3317b87"
_SOURCE_PATHS = MappingProxyType({
    "job_runtime_init": _JOB_RUNTIME / "__init__.py",
    "candidate_init": _PACKAGE / "__init__.py",
    "entrypoint": _PACKAGE / "entrypoint.py",
    "reviewed_runner": _PACKAGE / "reviewed_runner.py",
    "future_once_manifest": _PACKAGE / "future-once-manifest-v2.json",
    "service": _JOB_RUNTIME / "service.py",
    "claude_bridge": _BRIDGE_COMPAT_SOURCE,
    "runtime_lock_v2": _RUNTIME_LOCK_SOURCE,
    "provider_contract": _JOB_RUNTIME / "provider_contract.py",
    "retry_policy": _JOB_RUNTIME / "retry_policy.py",
    "tests_entrypoint": _JOB_RUNTIME / "tests" / "candidates" / "r6_fable_canary_entrypoint_v2" / "test_entrypoint.py",
    "tests_artifacts": _JOB_RUNTIME / "tests" / "candidates" / "r6_fable_canary_entrypoint_v2" / "test_artifacts.py",
    "fixture_profile": _JOB_RUNTIME / "tests" / "fixtures" / "r6_fable_canary_entrypoint_v2" / "expected-profile.json",
    "fixture_threat_model": _JOB_RUNTIME / "tests" / "fixtures" / "r6_fable_canary_entrypoint_v2" / "threat-model.json",
    "fixture_disabled_activation": _JOB_RUNTIME / "tests" / "fixtures" / "r6_fable_canary_entrypoint_v2" / "disabled-activation.json",
})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}\Z")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
_MAX_JSON = 1024 * 1024
_MAX_SOURCE = 4 * 1024 * 1024
_MAX_TTL_SECONDS = 300
_MAX_FUTURE_SKEW_SECONDS = 5
_AUTHORITY_FIELDS = frozenset({"schema_version", "candidate_id", "expected_reviews"})
_ACTIVATION_FIELDS = frozenset({
    "schema_version", "candidate_id", "test_only", "production_enabled",
    "review_id", "review_receipt_file", "review_receipt_sha256",
    "source_closure_sha256", "config_sha256", "profile", "nonce",
    "issued_at", "expires_at", "preflight_receipt_sha256",
    "runtime_lock_sha256", "bridge_sha256", "future_once_manifest_sha256",
})
_REVIEW_FIELDS = frozenset({
    "schema_version", "contract", "candidate_id", "review_id", "verdict",
    "reviewer_independent", "source_closure_sha256", "config_sha256",
    "profile_sha256", "activation", "effects", "reviewed_at",
    "preflight_receipt_sha256", "runtime_lock_sha256", "bridge_sha256",
    "future_once_manifest_sha256",
})
_CLOSURE_FIELDS = frozenset({
    "schema_version", "candidate_id", "status", "activation",
    "production_enabled", "source_mode", "members", "compatibility_assertions",
})
_EFFECTS = MappingProxyType({
    "provider": 0, "network": 0, "sdk_import": 0, "live": 0,
    "activation": 0, "business": 0, "email": 0,
})


def _fail(code):
    raise CanaryEntrypointError(code)


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError):
        _fail("FABLE_CANARY_JSON_INVALID")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _close_all(descriptors):
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _walk_parent(path, code):
    """Walk from / with O_NOFOLLOW and retain every directory descriptor."""
    path = Path(path)
    if not path.is_absolute() or any(part in ("", ".", "..") for part in path.parts[1:]):
        _fail(code)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    held = []
    try:
        held.append(os.open("/", flags))
        root = os.fstat(held[-1])
        if not stat.S_ISDIR(root.st_mode) or root.st_uid not in (0, os.getuid()) or root.st_mode & 0o022:
            _fail(code)
        for component in path.parts[1:-1]:
            held.append(os.open(component, flags, dir_fd=held[-1]))
            info = os.fstat(held[-1])
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid())
                    or info.st_mode & 0o022):
                _fail(code)
        return held[-1], path.parts[-1], held
    except CanaryEntrypointError:
        _close_all(held)
        raise
    except OSError:
        _close_all(held)
        _fail(code)


def _read_private(path, code, maximum):
    """Read one exact-0600, single-link regular file under held ancestry."""
    fd = None
    held = []
    try:
        parent, leaf, held = _walk_parent(path, code)
        fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= maximum):
            _fail(code)
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(131072, remaining))
            if not chunk:
                _fail(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            _fail(code)
        after = os.fstat(fd)
        try:
            named = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except OSError:
            _fail(code)
        if _identity(before) != _identity(after) or _identity(named) != _identity(after):
            _fail(code)
        return b"".join(chunks)
    except CanaryEntrypointError:
        raise
    except OSError:
        _fail(code)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        _close_all(held)


def _strict_json(raw, code, canonical_required=True):
    if not isinstance(raw, bytes) or len(raw) > _MAX_JSON:
        _fail(code)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        _fail(code)

    def reject_constant(_value):
        _fail(code)

    def pairs(rows):
        value = {}
        for key, item in rows:
            if type(key) is not str or key in value:
                _fail(code)
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError, ValueError):
        _fail(code)
    if type(value) is not dict:
        _fail(code)
    count = [0]

    def bounded(item, depth=0):
        count[0] += 1
        if count[0] > 4096 or depth > 32:
            _fail(code)
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if not -(2 ** 63) <= item <= 2 ** 63 - 1:
                _fail(code)
            return
        if type(item) is float:
            if not math.isfinite(item):
                _fail(code)
            return
        if type(item) is str:
            if len(item) > 8192:
                _fail(code)
            return
        if type(item) is list:
            for child in item:
                bounded(child, depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if not key or len(key) > 256:
                    _fail(code)
                bounded(child, depth + 1)
            return
        _fail(code)

    bounded(value)
    if canonical_required and raw != _canonical(value):
        _fail(code)
    return value


def _time(value, code):
    if type(value) is not str or len(value) > 40:
        _fail(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        _fail(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code)
    return parsed.astimezone(timezone.utc)


def _verify_source_closure(closure, paths):
    if (set(closure) != _CLOSURE_FIELDS or closure.get("schema_version") != 2
            or closure.get("candidate_id") != CANDIDATE_ID
            or closure.get("status") != "OFF_PENDING_INDEPENDENT_EVIDENCE_REVIEW"
            or closure.get("activation") is not False
            or closure.get("production_enabled") is not False
            or closure.get("source_mode") != "uid-current-mode0600-nlink1-regular-bounded-stable-v1"
            or type(closure.get("members")) is not dict
            or set(closure["members"]) != set(paths)):
        _fail("FABLE_CANARY_SOURCE_CLOSURE_INVALID")
    observed = {}
    source_bytes = {}
    for name, path in paths.items():
        raw = _read_private(path, "FABLE_CANARY_SOURCE_DRIFT", _MAX_SOURCE)
        source_bytes[name] = raw
        observed[name] = _sha(raw)
        member = closure["members"].get(name)
        if (type(member) is not dict or set(member) != {"sha256", "bytes"}
                or member.get("sha256") != observed[name]
                or member.get("bytes") != len(raw)):
            _fail("FABLE_CANARY_SOURCE_DRIFT")
    assertions = closure.get("compatibility_assertions")
    if (type(assertions) is not dict
            or set(assertions) != {"claude_bridge_sha256", "sdk_import_preflight_claimed",
                                       "observed_import_preflight_v2_sha256",
                                       "runtime_lock_v2_sha256"}
            or assertions.get("sdk_import_preflight_claimed") is not True
            or assertions.get("observed_import_preflight_v2_sha256") != _EXPECTED_PREFLIGHT_SHA256
            or assertions.get("runtime_lock_v2_sha256") != _EXPECTED_RUNTIME_LOCK_SHA256
            or type(assertions.get("claude_bridge_sha256")) is not str
            or _SHA.fullmatch(assertions["claude_bridge_sha256"]) is None):
        _fail("FABLE_CANARY_SOURCE_CLOSURE_INVALID")
    bridge_raw = source_bytes["claude_bridge"]
    if (_sha(bridge_raw) != assertions["claude_bridge_sha256"]
            or assertions["claude_bridge_sha256"] != _EXPECTED_BRIDGE_SHA256):
        _fail("FABLE_CANARY_SOURCE_DRIFT")
    return MappingProxyType(source_bytes)


def _service_dispatcher_from_source(service_raw):
    """Compile only service.py's reviewed dispatcher definition with fixed capabilities."""
    try:
        tree = ast.parse(service_raw.decode("utf-8"), filename="shared/job_runtime/service.py")
    except (UnicodeDecodeError, SyntaxError, ValueError):
        _fail("FABLE_CANARY_SOURCE_DRIFT")
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == "dispatcher"]
    if len(nodes) != 1 or not isinstance(nodes[0], ast.FunctionDef):
        _fail("FABLE_CANARY_SOURCE_DRIFT")

    result_type = ProviderResultV1
    deepcopy = copy.deepcopy
    stop = threading.Event()

    class LocalPromptError(Exception):
        pass

    class LocalArtifact:
        __slots__ = ("text", "length")
        def __init__(self, text):
            self.text = text
            self.length = len(text.encode("utf-8"))

    class LocalLease:
        def __init__(self, raw):
            self._raw = raw
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def chunks(self):
            return (self._raw,)

    class LocalStore:
        def __init__(self, _workspace):
            pass
        def open(self, artifact):
            if not isinstance(artifact, LocalArtifact) or artifact.length > 1024 * 1024:
                raise LocalPromptError("invalid provider-free prompt fixture")
            return LocalLease(artifact.text.encode("utf-8"))

    def typed_failure(provider, operation_id, code, unknown=False, **_extra):
        return result_type(
            provider=provider, operation_id=operation_id, phase="submitted" if unknown else "not_started",
            submission="possibly_submitted" if unknown else "not_submitted",
            terminal_proof="absent", status="unknown" if unknown else "failed",
            code=code, failure_kind="unknown" if unknown else "local_config",
            provider_should_retry=False, receipt={"test_only": True})

    def provider_registry(overrides=None):
        if type(overrides) is not dict or set(overrides) != {"claude_host"}:
            raise ValueError("FABLE_CANARY_PROVIDER_REGISTRY_INVALID")
        return MappingProxyType(dict(overrides))

    namespace = {
        "__builtins__": __builtins__, "copy": SimpleNamespace(deepcopy=deepcopy),
        "_provider_registry": provider_registry, "_typed_failure": typed_failure,
        "STOP": stop, "ProviderResultV1": result_type,
        "PromptArtifactDescriptorV1": object, "PromptArtifactStore": LocalStore,
        "PromptLease": LocalLease, "PromptCustodyError": LocalPromptError,
        "datetime": datetime, "timezone": timezone,
    }
    code = compile(ast.Module(body=[nodes[0]], type_ignores=[]),
                   "shared/job_runtime/service.py", "exec", dont_inherit=True)
    exec(code, namespace)
    return namespace["dispatcher"], LocalArtifact


def _write_state(fd, value, fsync):
    raw = _canonical(value)
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    written = 0
    while written < len(raw):
        amount = os.write(fd, raw[written:])
        if amount <= 0:
            raise OSError("state write failed")
        written += amount
    fsync(fd)


def _make_factory(authority_path, closure_path, source_paths, clock, fsync,
                  preflight_path=None, runtime_lock_path=None, bridge_resolver=None):
    """Internal test seam; all capabilities are captured before a builder is returned."""
    authority_source = Path(authority_path)
    closure_source = Path(closure_path)
    paths = MappingProxyType({name: Path(path) for name, path in source_paths.items()})
    trusted_clock = clock
    sync = fsync
    runner_factory = make_reviewed_runner
    expected_profile = dict(EXPECTED_PROFILE)
    deepcopy = copy.deepcopy
    def build(config, workspace, activation_path):
        try:
            now = trusted_clock()
        except Exception:
            _fail("FABLE_CANARY_CLOCK_INVALID")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            _fail("FABLE_CANARY_CLOCK_INVALID")
        now = now.astimezone(timezone.utc)
        workspace_path = Path(workspace).absolute()
        canary_root = workspace_path / ".job-runtime" / "canary"
        dispatch_authority_root = workspace_path / ".job-runtime" / "r6-fable-canary-authority"
        activation_file = Path(activation_path).absolute()
        expected_parent = canary_root
        if activation_file.parent != expected_parent:
            _fail("FABLE_CANARY_REVIEW_REQUIRED")

        closure_raw = _read_private(closure_source, "FABLE_CANARY_SOURCE_CLOSURE_INVALID", _MAX_JSON)
        closure = _strict_json(closure_raw, "FABLE_CANARY_SOURCE_CLOSURE_INVALID")
        source_bytes = _verify_source_closure(closure, paths)
        service_dispatcher_factory, artifact_type = _service_dispatcher_from_source(source_bytes["service"])
        closure_sha = _sha(closure_raw)

        authority_raw = _read_private(authority_source, "FABLE_CANARY_AUTHORITY_INVALID", _MAX_JSON)
        authority = _strict_json(authority_raw, "FABLE_CANARY_AUTHORITY_INVALID")
        if (set(authority) != _AUTHORITY_FIELDS or authority.get("schema_version") != 2
                or authority.get("candidate_id") != CANDIDATE_ID
                or type(authority.get("expected_reviews")) is not dict):
            _fail("FABLE_CANARY_AUTHORITY_INVALID")

        activation_raw = _read_private(activation_file, "FABLE_CANARY_REVIEW_REQUIRED", _MAX_JSON)
        activation = _strict_json(activation_raw, "FABLE_CANARY_REVIEW_REQUIRED")
        if (set(activation) != _ACTIVATION_FIELDS or activation.get("schema_version") != 1
                or activation.get("candidate_id") != CANDIDATE_ID
                or activation.get("test_only") is not True
                or activation.get("production_enabled") is not False
                or type(activation.get("review_id")) is not str
                or _SAFE_NAME.fullmatch(activation["review_id"]) is None
                or type(activation.get("review_receipt_file")) is not str
                or _SAFE_NAME.fullmatch(activation["review_receipt_file"]) is None
                or type(activation.get("nonce")) is not str
                or _NONCE.fullmatch(activation["nonce"]) is None
                or activation.get("profile") != expected_profile):
            _fail("FABLE_CANARY_REVIEW_REQUIRED")
        for key in ("review_receipt_sha256", "source_closure_sha256", "config_sha256",
                    "preflight_receipt_sha256", "runtime_lock_sha256", "bridge_sha256",
                    "future_once_manifest_sha256"):
            if type(activation.get(key)) is not str or _SHA.fullmatch(activation[key]) is None:
                _fail("FABLE_CANARY_REVIEW_REQUIRED")
        preadmitted = authority["expected_reviews"].get(activation["review_id"])
        if type(preadmitted) is not str or _SHA.fullmatch(preadmitted) is None:
            _fail("FABLE_CANARY_REVIEW_REQUIRED")
        if activation["source_closure_sha256"] != closure_sha:
            _fail("FABLE_CANARY_SOURCE_DRIFT")

        issued = _time(activation.get("issued_at"), "FABLE_CANARY_REVIEW_REQUIRED")
        expires = _time(activation.get("expires_at"), "FABLE_CANARY_REVIEW_REQUIRED")
        ttl = (expires - issued).total_seconds()
        if (ttl <= 0 or ttl > _MAX_TTL_SECONDS
                or issued > now + timedelta(seconds=_MAX_FUTURE_SKEW_SECONDS)
                or now >= expires):
            _fail("FABLE_CANARY_REVIEW_EXPIRED")

        review_path = canary_root / activation["review_receipt_file"]
        review_raw = _read_private(review_path, "FABLE_CANARY_REVIEW_REQUIRED", _MAX_JSON)
        review = _strict_json(review_raw, "FABLE_CANARY_REVIEW_REQUIRED")
        review_sha = _sha(review_raw)
        if (preadmitted != review_sha
                or activation["review_receipt_sha256"] != review_sha):
            _fail("FABLE_CANARY_REVIEW_REQUIRED")
        profile_sha = _sha(_canonical(expected_profile))
        if (set(review) != _REVIEW_FIELDS or review.get("schema_version") != 1
                or review.get("contract") != "r6-fable-canary-independent-off-evidence-review-v2"
                or review.get("candidate_id") != CANDIDATE_ID
                or review.get("review_id") != activation["review_id"]
                or review.get("verdict") != "CLEAN_OFF_ONLY_REAL_BRIDGE_CANDIDATE"
                or review.get("reviewer_independent") is not True
                or review.get("source_closure_sha256") != closure_sha
                or review.get("config_sha256") != activation["config_sha256"]
                or review.get("profile_sha256") != profile_sha
                or review.get("preflight_receipt_sha256") != activation["preflight_receipt_sha256"]
                or review.get("runtime_lock_sha256") != activation["runtime_lock_sha256"]
                or review.get("bridge_sha256") != activation["bridge_sha256"]
                or review.get("future_once_manifest_sha256") != activation["future_once_manifest_sha256"]
                or review.get("activation") is not False
                or review.get("effects") != dict(_EFFECTS)):
            _fail("FABLE_CANARY_REVIEW_REQUIRED")
        _time(review.get("reviewed_at"), "FABLE_CANARY_REVIEW_REQUIRED")

        receipt_source = (Path(preflight_path) if preflight_path is not None else
                          workspace_path / ".job-runtime" / "evidence" /
                          "claude-sdk-0.2.179-observed-import-preflight-v2" / "receipt.json")
        receipt_raw = _read_private(receipt_source, "FABLE_CANARY_PREFLIGHT_INVALID", _MAX_JSON)
        receipt = _strict_json(receipt_raw, "FABLE_CANARY_PREFLIGHT_INVALID", False)
        lock_raw = source_bytes["runtime_lock_v2"]
        lock = _strict_json(lock_raw, "FABLE_CANARY_RUNTIME_LOCK_INVALID", False)
        manifest_raw = source_bytes["future_once_manifest"]
        manifest = _strict_json(manifest_raw, "FABLE_CANARY_MANIFEST_INVALID")
        static = receipt.get("static_evidence") if type(receipt) is dict else None
        validated = receipt.get("validated_output") if type(receipt) is dict else None
        if (_sha(receipt_raw) != _EXPECTED_PREFLIGHT_SHA256
                or activation["preflight_receipt_sha256"] != _EXPECTED_PREFLIGHT_SHA256
                or receipt.get("schema_version") != 3
                or receipt.get("contract") != "claude-agent-sdk-observed-import-preflight-receipt-v3"
                or receipt.get("status") != "PASS" or receipt.get("blockers") != []
                or receipt.get("candidate_lock_sha256") != _EXPECTED_RUNTIME_LOCK_SHA256
                or receipt.get("provider_queries_observed") != 0
                or receipt.get("network_calls_observed") != 0
                or receipt.get("bundled_cli_executions_observed") != 0
                or receipt.get("child_processes_observed") != 0
                or receipt.get("production_activated") is not False
                or type(static) is not dict or type(validated) is not dict
                or static.get("distribution_tree_sha256") != _EXPECTED_TREE_SHA256
                or static.get("record_raw_bytes_sha256") != _EXPECTED_RECORD_RAW_SHA256
                or static.get("record_importlib_text_utf8_sha256") != _EXPECTED_RECORD_TEXT_SHA256
                or validated.get("package_tree_sha256") != _EXPECTED_TREE_SHA256
                or validated.get("expected_record_raw_bytes_sha256") != _EXPECTED_RECORD_RAW_SHA256
                or validated.get("expected_record_importlib_text_utf8_sha256") != _EXPECTED_RECORD_TEXT_SHA256
                or static.get("unrecorded_sdk_paths") != []
                or validated.get("status") != "READY_OFFLINE"
                or validated.get("network_used") is not False
                or validated.get("install_performed") is not False):
            _fail("FABLE_CANARY_PREFLIGHT_INVALID")
        if (_sha(lock_raw) != _EXPECTED_RUNTIME_LOCK_SHA256
                or activation["runtime_lock_sha256"] != _EXPECTED_RUNTIME_LOCK_SHA256
                or lock.get("schema_version") != 2
                or lock.get("contract") != "claude-agent-sdk-canonical-post-install-runtime-lock-v2"
                or lock.get("expected_distribution_tree_sha256") != _EXPECTED_TREE_SHA256
                or lock.get("expected_record_raw_bytes_sha256") != _EXPECTED_RECORD_RAW_SHA256
                or lock.get("expected_record_importlib_text_utf8_sha256") != _EXPECTED_RECORD_TEXT_SHA256):
            _fail("FABLE_CANARY_RUNTIME_LOCK_INVALID")
        if (activation["bridge_sha256"] != _EXPECTED_BRIDGE_SHA256
                or _sha(source_bytes["claude_bridge"]) != _EXPECTED_BRIDGE_SHA256):
            _fail("FABLE_CANARY_BRIDGE_DRIFT")
        if (_sha(manifest_raw) != activation["future_once_manifest_sha256"]
                or manifest.get("enabled") is not False
                or manifest.get("activation") is not False
                or manifest.get("invocation_prohibited") is not True
                or manifest.get("provider_invocation_allowed") is not False
                or manifest.get("production_enabled") is not False
                or manifest.get("activation_authority") != {}):
            _fail("FABLE_CANARY_MANIFEST_INVALID")

        if type(config) is not dict:
            _fail("FABLE_CANARY_CONFIG_DRIFT")
        try:
            captured_config = deepcopy(config)
            config_sha = _sha(_canonical(captured_config))
        except CanaryEntrypointError:
            raise
        except Exception:
            _fail("FABLE_CANARY_CONFIG_DRIFT")
        if config_sha != activation["config_sha256"]:
            _fail("FABLE_CANARY_CONFIG_DRIFT")
        expected_config = {"schema_version": 2, "model_profiles": {
            "fable": {"provider": "claude_host", **expected_profile}}}
        if captured_config != expected_config:
            _fail("FABLE_CANARY_PROFILE_DRIFT")
        runner = runner_factory(config_sha, bridge_resolver)
        base_dispatch = service_dispatcher_factory(
            captured_config, workspace_path, {"claude_host": runner})

        nonce = activation["nonce"]
        admitted_issued = issued
        admitted_expires = expires
        dispatch_clock = trusted_clock
        digest_cap = hashlib.sha256
        dumps_cap = json.dumps
        open_cap, close_cap = os.open, os.close
        read_stat_cap, named_stat_cap = os.fstat, os.stat
        write_cap, seek_cap, truncate_cap = os.write, os.lseek, os.ftruncate
        rename_cap, unlink_cap = os.rename, os.unlink
        pid_cap, thread_id_cap = os.getpid, threading.get_ident
        is_regular_cap, is_directory_cap, mode_cap = stat.S_ISREG, stat.S_ISDIR, stat.S_IMODE
        uid_cap = os.getuid
        readonly = os.O_RDONLY
        seek_set = os.SEEK_SET
        readwrite, create, exclusive = os.O_RDWR, os.O_CREAT, os.O_EXCL
        writeonly, nofollow = os.O_WRONLY, getattr(os, "O_NOFOLLOW", 0)
        utc_cap, datetime_type = timezone.utc, datetime
        skew_delta = timedelta(seconds=_MAX_FUTURE_SKEW_SECONDS)
        error_type = CanaryEntrypointError
        candidate_id = CANDIDATE_ID
        state_name = "dispatch-" + digest_cap(nonce.encode("ascii")).hexdigest() + ".json"
        terminal_name = "terminal-" + digest_cap(nonce.encode("ascii")).hexdigest() + ".json"
        review_binding = review_sha
        activation_binding = digest_cap(activation_raw).hexdigest()
        lock = threading.Lock()
        local_used = [False]
        _state_parent, _state_leaf, admission_held = _walk_parent(
            dispatch_authority_root / "sentinel", "FABLE_CANARY_STATE_INVALID")
        try:
            authority_info = read_stat_cap(_state_parent)
            if (not is_directory_cap(authority_info.st_mode)
                    or authority_info.st_uid != uid_cap()
                    or mode_cap(authority_info.st_mode) != 0o700
                    or authority_info.st_nlink < 2):
                _fail("FABLE_CANARY_STATE_INVALID")
            held_identities = tuple(
                (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
                for info in (read_stat_cap(fd) for fd in admission_held))
        finally:
            _close_all(admission_held)
        chain_components = (dispatch_authority_root / "sentinel").parts[1:-1]
        directory_flags = readonly | getattr(os, "O_DIRECTORY", 0) | nofollow

        def deny(code):
            raise error_type(code)

        def canonical_record(value):
            return dumps_cap(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")

        def reopen_admitted_chain():
            reopened = []
            try:
                reopened.append(open_cap("/", directory_flags))
                for component in chain_components:
                    reopened.append(open_cap(component, directory_flags, dir_fd=reopened[-1]))
                if len(reopened) != len(held_identities):
                    deny("FABLE_CANARY_STATE_INVALID")
                for index, descriptor in enumerate(reopened):
                    info = read_stat_cap(descriptor)
                    identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
                    if (not is_directory_cap(info.st_mode)
                            or info.st_uid not in (0, uid_cap())
                            or info.st_mode & 0o022
                            or identity != held_identities[index]):
                        deny("FABLE_CANARY_STATE_INVALID")
                leaf = read_stat_cap(reopened[-1])
                if (leaf.st_uid != uid_cap() or mode_cap(leaf.st_mode) != 0o700
                        or leaf.st_nlink < 2):
                    deny("FABLE_CANARY_STATE_INVALID")
                return reopened
            except error_type:
                for descriptor in reversed(reopened):
                    try:
                        close_cap(descriptor)
                    except OSError:
                        pass
                raise
            except OSError:
                for descriptor in reversed(reopened):
                    try:
                        close_cap(descriptor)
                    except OSError:
                        pass
                deny("FABLE_CANARY_STATE_INVALID")


        def write_state_local(fd, value):
            raw = canonical_record(value)
            seek_cap(fd, 0, seek_set)
            truncate_cap(fd, 0)
            written = 0
            while written < len(raw):
                amount = write_cap(fd, raw[written:])
                if amount <= 0:
                    raise OSError("state write failed")
                written += amount
            sync(fd)

        def publish_terminal(parent, record):
            temporary = terminal_name + ".tmp-" + str(pid_cap()) + "-" + str(thread_id_cap())
            terminal_fd = None
            try:
                terminal_fd = open_cap(temporary, writeonly | create | exclusive | nofollow,
                                       0o600, dir_fd=parent)
                created = read_stat_cap(terminal_fd)
                if (not is_regular_cap(created.st_mode) or created.st_uid != uid_cap()
                        or mode_cap(created.st_mode) != 0o600 or created.st_nlink != 1):
                    raise OSError("terminal custody invalid")
                raw = canonical_record(record)
                written = 0
                while written < len(raw):
                    amount = write_cap(terminal_fd, raw[written:])
                    if amount <= 0:
                        raise OSError("terminal write failed")
                    written += amount
                sync(terminal_fd)
                close_cap(terminal_fd); terminal_fd = None
                rename_cap(temporary, terminal_name, src_dir_fd=parent, dst_dir_fd=parent)
                sync(parent)
            finally:
                if terminal_fd is not None:
                    try:
                        close_cap(terminal_fd)
                    except OSError:
                        pass
                try:
                    unlink_cap(temporary, dir_fd=parent)
                except OSError:
                    pass

        def dispatch(job, context):
            with lock:
                if local_used[0]:
                    deny("FABLE_CANARY_REPLAY_REJECTED")
                local_used[0] = True
            state_fd = None
            reopened_held = []
            parent = None
            try:
                try:
                    dispatch_now = dispatch_clock()
                except Exception:
                    deny("FABLE_CANARY_CLOCK_INVALID")
                if (not isinstance(dispatch_now, datetime_type) or dispatch_now.tzinfo is None
                        or dispatch_now.utcoffset() is None):
                    deny("FABLE_CANARY_CLOCK_INVALID")
                dispatch_now = dispatch_now.astimezone(utc_cap)
                if dispatch_now < admitted_issued - skew_delta or dispatch_now >= admitted_expires:
                    deny("FABLE_CANARY_REVIEW_EXPIRED")
                reopened_held = reopen_admitted_chain()
                parent = reopened_held[-1]
                parent_info = read_stat_cap(parent)
                if (not is_directory_cap(parent_info.st_mode) or parent_info.st_uid != uid_cap()
                        or parent_info.st_mode & 0o022):
                    deny("FABLE_CANARY_STATE_INVALID")
                claim = {
                    "schema_version": 1, "candidate_id": candidate_id,
                    "status": "CLAIMED", "nonce_sha256": digest_cap(nonce.encode("ascii")).hexdigest(),
                    "activation_sha256": activation_binding,
                    "review_receipt_sha256": review_binding,
                    "source_closure_sha256": closure_sha,
                    "config_sha256": config_sha,
                    "preflight_receipt_sha256": _EXPECTED_PREFLIGHT_SHA256,
                    "runtime_lock_sha256": _EXPECTED_RUNTIME_LOCK_SHA256,
                    "bridge_sha256": _EXPECTED_BRIDGE_SHA256,
                    "future_once_manifest_sha256": activation["future_once_manifest_sha256"],
                }
                try:
                    state_fd = open_cap(state_name, readwrite | create | exclusive | nofollow,
                                        0o600, dir_fd=parent)
                except FileExistsError:
                    try:
                        named_stat_cap(terminal_name, dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        unknown = dict(claim)
                        unknown.update({"status": "UNKNOWN",
                                        "result_code": "FABLE_CANARY_PRIOR_DISPATCH_AMBIGUOUS"})
                        try:
                            publish_terminal(parent, unknown)
                        except Exception:
                            pass
                    deny("FABLE_CANARY_REPLAY_REJECTED")
                created = read_stat_cap(state_fd)
                if (not is_regular_cap(created.st_mode) or created.st_uid != uid_cap()
                        or mode_cap(created.st_mode) != 0o600 or created.st_nlink != 1):
                    deny("FABLE_CANARY_STATE_INVALID")
                write_state_local(state_fd, claim)
                sync(parent)
                try:
                    dispatch_context = deepcopy(context)
                    prompt_text = dispatch_context.get("prompt_artifact")
                    if type(prompt_text) is not str:
                        deny("FABLE_CANARY_INVOCATION_INVALID")
                    dispatch_context["prompt_artifact"] = artifact_type(prompt_text)
                    result = base_dispatch(job, dispatch_context)
                    if getattr(result, "status", None) is None:
                        terminal = "UNKNOWN"
                    else:
                        status_value = getattr(result.status, "value", result.status)
                        terminal = "success" if status_value == "succeeded" else (
                            "failed" if status_value in ("failed", "retryable") else "UNKNOWN")
                    record = dict(claim)
                    record.update({"status": terminal,
                                   "result_code": getattr(result, "code", "FABLE_CANARY_RESULT_INVALID")})
                    publish_terminal(parent, record)
                    return result
                except BaseException:
                    unknown = dict(claim)
                    unknown.update({"status": "UNKNOWN",
                                    "result_code": "FABLE_CANARY_DISPATCH_AMBIGUOUS"})
                    try:
                        publish_terminal(parent, unknown)
                    except Exception:
                        pass
                    deny("FABLE_CANARY_DISPATCH_UNKNOWN")
            except error_type:
                raise
            except OSError:
                deny("FABLE_CANARY_STATE_INVALID")
            finally:
                if state_fd is not None:
                    try:
                        close_cap(state_fd)
                    except OSError:
                        pass
                for descriptor in reversed(reopened_held):
                    try:
                        close_cap(descriptor)
                    except OSError:
                        pass

        return dispatch

    return build


def _system_clock(_datetime=datetime, _utc=timezone.utc):
    return _datetime.now(_utc)


_DEFAULT_FACTORY = _make_factory(
    _AUTHORITY_SOURCE, _SOURCE_CLOSURE_SOURCE, _SOURCE_PATHS, _system_clock, os.fsync)


def build_test_only_dispatcher(config, workspace, activation_path):
    """Use shipped empty review authority; cannot dispatch before independent review."""
    return _DEFAULT_FACTORY(config, workspace, activation_path)


__all__ = ["CanaryEntrypointError", "build_test_only_dispatcher"]
