"""Shared immutable custody contract for provider live-session artifacts.

The contract binds one session to the current source closure, an exact
materialized host generation, an admitted future root and the canonical session
spec.  It is an integrity and crash/replay boundary under the workspace's
same-user operational trust model; it is not remote attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from shared.research_sources.host_adapter_contracts import (
    AdapterId, Capability, CredentialReadinessReceipt, CredentialReadinessStatus,
    CredentialRef, CredentialSource, HostAdapterProfile, HostBudget,
    HostContractError, HostExecutionBinding, Operation, RuntimeProfileRef,
    ToolBinding, WorkspaceFileRef,
)

VERSION = "live-session-custody-1"
NON_CRYPTO_LIMITATION = (
    "Operational host evidence is locally retained and does not resist malicious "
    "same-user file forgery."
)
_SHA = "sha256"
_MAX = 2 * 1024 * 1024


class LiveSessionCustodyError(ValueError):
    pass


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise LiveSessionCustodyError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise LiveSessionCustodyError("LIVE_CUSTODY_JSON") from error


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash(value: str, code: str) -> str:
    _need(isinstance(value, str) and len(value) == 64
          and all(c in "0123456789abcdef" for c in value), code)
    return value


def _safe_relative(value: Any, code: str) -> Path:
    _need(isinstance(value, str) and value and len(value) <= 512, code)
    path = Path(value)
    _need(not path.is_absolute() and path.parts and ".." not in path.parts
          and all(part not in {"", "."} for part in path.parts), code)
    return path


def _safe_file(root: Path, ref: Mapping[str, Any], code: str) -> tuple[Path, bytes]:
    _need(isinstance(ref, Mapping)
          and set(ref) in ({"path", "sha256"}, {"path", "sha256", "reused"})
          and ("reused" not in ref or type(ref["reused"]) is bool), code)
    relative = _safe_relative(ref.get("path"), code)
    _hash(ref.get("sha256"), code)
    current = root
    for part in relative.parts:
        current = current / part
        _need(not current.is_symlink(), code)
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
        info = current.stat()
    except (OSError, ValueError):
        raise LiveSessionCustodyError(code) from None
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
          and info.st_nlink == 1 and 0 < info.st_size <= _MAX, code)
    raw = current.read_bytes()
    _need(sha256_bytes(raw) == ref["sha256"], code)
    return resolved, raw


def normalized_ref(ref: Mapping[str, Any], code: str = "LIVE_CUSTODY_REF") -> dict[str, str]:
    _need(isinstance(ref, Mapping)
          and set(ref) in ({"path", "sha256"}, {"path", "sha256", "reused"}), code)
    return {"path": str(ref["path"]), "sha256": _hash(ref["sha256"], code)}


def _json_ref(root: Path, ref: Mapping[str, Any], code: str) -> dict[str, Any]:
    _path, raw = _safe_file(root, ref, code)
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        raise LiveSessionCustodyError(code) from None
    _need(isinstance(value, dict), code)
    return value


def _snapshot(root: Path, patterns: Sequence[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for pattern in patterns:
        _need(isinstance(pattern, str) and pattern and not Path(pattern).is_absolute()
              and ".." not in Path(pattern).parts, "LIVE_CUSTODY_SETUP_LOCK")
        for path in root.glob(pattern):
            if (path.is_file() and not path.is_symlink()
                    and "node_modules" not in path.parts
                    and "__pycache__" not in path.parts
                    and path.suffix not in {".pyc", ".pyo"}):
                rows[str(path.relative_to(root))] = sha256_bytes(path.read_bytes())
    return dict(sorted(rows.items()))


def current_source_closure(root: Path) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    lock_path = root / "docs/deployment/setup-lock.json"
    _need(lock_path.is_file() and not lock_path.is_symlink(), "LIVE_CUSTODY_SETUP_LOCK")
    raw = lock_path.read_bytes()
    try:
        lock = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        raise LiveSessionCustodyError("LIVE_CUSTODY_SETUP_LOCK") from None
    _need(isinstance(lock, dict) and lock.get("schema_version") == 1
          and isinstance(lock.get("source_patterns"), list), "LIVE_CUSTODY_SETUP_LOCK")
    sources = _snapshot(root, lock["source_patterns"])
    return {
        "setup_lock_ref": {"path": "docs/deployment/setup-lock.json",
                           "sha256": sha256_bytes(raw)},
        "source_patterns_sha256": sha256_bytes(canonical_bytes(lock["source_patterns"])),
        "sources": sources,
        "sources_sha256": sha256_bytes(canonical_bytes(sources)),
    }


def revalidate_source_closure(root: Path, closure: Mapping[str, Any]) -> None:
    _need(isinstance(closure, Mapping) and set(closure) == {
        "setup_lock_ref", "source_patterns_sha256", "sources", "sources_sha256"},
        "LIVE_CUSTODY_SOURCE_CLOSURE")
    observed = current_source_closure(root)
    _need(observed == dict(closure), "LIVE_CUSTODY_SOURCE_DRIFT")


def _profile_from_public(value: Mapping[str, Any]) -> HostAdapterProfile:
    try:
        runtime = value["runtime"]
        credential = value["credential"]
        return HostAdapterProfile(
            adapter_id=AdapterId(value["adapter_id"]),
            configured_backend=value["configured_backend"],
            tool_bindings=tuple(ToolBinding(Operation(row["operation"]),
                                            row["observed_tool_identity"])
                                for row in value["tool_bindings"]),
            capabilities=frozenset(Capability(row) for row in value["capabilities"]),
            runtime=RuntimeProfileRef(runtime["runtime_identity"],
                                      WorkspaceFileRef(**runtime["interpreter_ref"]),
                                      WorkspaceFileRef(**runtime["profile_ref"])),
            credential=CredentialRef(credential["owner_ref"],
                                     CredentialSource(credential["source"]),
                                     credential["profile_ref"],
                                     credential.get("fingerprint_sha256")),
            mcp=None,
        )
    except (KeyError, TypeError, ValueError, HostContractError) as error:
        raise LiveSessionCustodyError("LIVE_CUSTODY_PROFILE") from error


def _binding_from_public(value: Mapping[str, Any]) -> HostExecutionBinding:
    _need(isinstance(value, Mapping) and set(value) == {
        "version", "profile", "execution_id", "trace_id", "dispatch_namespace",
        "artifact_root", "cache_root", "budget", "binding_sha256"},
        "LIVE_CUSTODY_BINDING")
    unsigned = {key: row for key, row in value.items() if key != "binding_sha256"}
    _need(value.get("binding_sha256") == sha256_bytes(canonical_bytes(unsigned)),
          "LIVE_CUSTODY_BINDING")
    try:
        return HostExecutionBinding(
            profile=_profile_from_public(value["profile"]),
            execution_id=value["execution_id"], trace_id=value["trace_id"],
            dispatch_namespace=value["dispatch_namespace"],
            artifact_root=value["artifact_root"], cache_root=value["cache_root"],
            budget=HostBudget(**value["budget"]),
        )
    except (KeyError, TypeError, HostContractError) as error:
        raise LiveSessionCustodyError("LIVE_CUSTODY_BINDING") from error


def _fresh(receipt: CredentialReadinessReceipt, now: datetime) -> None:
    try:
        checked = datetime.fromisoformat(receipt.checked_at.replace("Z", "+00:00"))
    except ValueError:
        raise LiveSessionCustodyError("LIVE_CUSTODY_CREDENTIAL_TIME") from None
    age = (now.astimezone(timezone.utc) - checked.astimezone(timezone.utc)).total_seconds()
    _need(-5 <= age <= 900 and receipt.status is CredentialReadinessStatus.READY
          and receipt.live_acceptance_eligible, "LIVE_CUSTODY_CREDENTIAL_STALE")


def reopen_and_validate_materialized_bundle(root: Path, *, head_ref: Mapping[str, Any],
                                            profile_ref: Mapping[str, Any],
                                            credential_ref: Mapping[str, Any],
                                            binding_ref: Mapping[str, Any],
                                            host: str, now: datetime | None = None,
                                            require_live: bool = True) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    head = _json_ref(root, head_ref, "LIVE_CUSTODY_HEAD")
    _need(set(head) == {"kind", "version", "mcp", "generation",
                        "generation_sha256", "files", "hosts"}
          and head["kind"] == "host_profile_materialization_head"
          and head["mcp"] == "not_used", "LIVE_CUSTODY_HEAD")
    generation_sha = _hash(head["generation_sha256"], "LIVE_CUSTODY_HEAD")
    _need(head["generation"] == f"generation-{generation_sha}", "LIVE_CUSTODY_HEAD")
    _need(host in {"codex", "claude"}, "LIVE_CUSTODY_HOST")
    expected = {
        f"{host}-profile.json": profile_ref["sha256"],
        f"{host}-credential-readiness.json": credential_ref["sha256"],
        f"{host}-binding.json": binding_ref["sha256"],
    }
    _need(all(head.get("files", {}).get(name) == digest for name, digest in expected.items())
          and isinstance(head.get("hosts", {}).get(host, {}).get("ready_for_live"), bool)
          and (not require_live or head["hosts"][host]["ready_for_live"] is True),
          "LIVE_CUSTODY_HEAD")
    for ref, suffix in ((profile_ref, "profile"), (credential_ref, "credential-readiness"),
                        (binding_ref, "binding")):
        path = _safe_relative(ref["path"], "LIVE_CUSTODY_REF")
        _need(path.parent.name == head["generation"]
              and path.name == f"{host}-{suffix}.json", "LIVE_CUSTODY_REF")
    profile = _json_ref(root, profile_ref, "LIVE_CUSTODY_PROFILE")
    credential = _json_ref(root, credential_ref, "LIVE_CUSTODY_CREDENTIAL")
    binding_value = _json_ref(root, binding_ref, "LIVE_CUSTODY_BINDING")
    binding = _binding_from_public(binding_value)
    parsed_profile = _profile_from_public(profile)
    _need(binding.profile == parsed_profile, "LIVE_CUSTODY_PROFILE_BINDING")
    try:
        receipt = CredentialReadinessReceipt.from_public_dict(credential)
    except HostContractError as error:
        raise LiveSessionCustodyError("LIVE_CUSTODY_CREDENTIAL") from error
    expected_adapter = AdapterId.CODEX_NATIVE_WEB if host == "codex" else AdapterId.CLAUDE_CODE_WEB
    _need(parsed_profile.adapter_id is expected_adapter
          and receipt.adapter_id is expected_adapter
          and receipt.owner_ref == parsed_profile.credential.owner_ref
          and receipt.profile_ref == parsed_profile.credential.profile_ref
          and receipt.profile_fingerprint_sha256 == parsed_profile.credential.fingerprint_sha256,
          "LIVE_CUSTODY_CREDENTIAL")
    if require_live:
        _fresh(receipt, now or datetime.now(timezone.utc))
    return {"head": head, "profile": profile, "credential": credential,
            "binding": binding_value, "binding_object": binding,
            "receipt_object": receipt}


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_four_lane_isolation(rows: Mapping[str, Mapping[str, Any]], *, root: Path) -> None:
    required = {"codex_smoke", "claude_smoke", "codex_narrow", "claude_narrow"}
    _need(isinstance(rows, Mapping) and set(rows) == required, "LIVE_CUSTODY_LANES")
    for field in ("experiment_id", "execution_id", "trace_id", "dispatch_namespace", "host_session_id"):
        values = [rows[name].get(field) for name in sorted(required)]
        _need(all(isinstance(value, str) and value for value in values) and len(set(values)) == 4,
              f"LIVE_CUSTODY_LANE_{field.upper()}")
    workspace = Path(root).resolve(strict=True); lane_roots = {}
    for name in sorted(required):
        values=[]
        for field in ("session_root","artifact_root","cache_root","registry_root","publication_root","unknown_outcome_fence"):
            relative=_safe_relative(rows[name].get(field),"LIVE_CUSTODY_LANE_ROOT")
            path=(workspace/relative).resolve(strict=False);_need(path.is_relative_to(workspace),"LIVE_CUSTODY_LANE_ROOT");values.append(path)
        session,artifact,cache,registry,publication,fence=values
        _need(artifact.is_relative_to(session) and cache.is_relative_to(session),"LIVE_CUSTODY_LANE_ROOT")
        for left,right in ((registry,publication),(registry,fence),(publication,fence)):
            _need(not _overlap(left,right),"LIVE_CUSTODY_LANE_ROOT")
        lane_roots[name]=values
    names=sorted(required)
    for index,left_name in enumerate(names):
        for right_name in names[index+1:]:
            for left in lane_roots[left_name]:
                for right in lane_roots[right_name]:
                    _need(not _overlap(left,right),"LIVE_CUSTODY_LANE_ROOT_SHARED")


def session_spec_core(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in spec.items() if key != "custody_ref"}


def build_live_session_custody(root: Path, *, spec_core: Mapping[str, Any],
                               host: str, future_root: str,
                               four_lane_identity_sha256: str | None = None,
                               now: datetime | None = None) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    bundle = reopen_and_validate_materialized_bundle(
        root, head_ref=spec_core["host_materialization_manifest_ref"],
        profile_ref=spec_core["host_profile_ref"],
        credential_ref=spec_core["credential_readiness_ref"],
        binding_ref=spec_core["host_binding_ref"], host=host, now=now)
    binding = bundle["binding_object"]
    _need(binding.execution_id == spec_core["identities"]["execution_id"]
          and binding.trace_id == spec_core["identities"]["trace_id"],
          "LIVE_CUSTODY_IDENTITY")
    relative = _safe_relative(future_root, "LIVE_CUSTODY_FUTURE_ROOT")
    _need(relative.parts[0] == ".research-sources", "LIVE_CUSTODY_FUTURE_ROOT")
    future_path = root / relative
    _need(not future_path.exists(), "LIVE_CUSTODY_FUTURE_ROOT_EXISTS")
    closure = current_source_closure(root)
    value: dict[str, Any] = {
        "version": VERSION,
        "source_closure": closure,
        "materialization_head_ref": normalized_ref(spec_core["host_materialization_manifest_ref"]),
        "host_profile_ref": normalized_ref(spec_core["host_profile_ref"]),
        "credential_readiness_ref": normalized_ref(spec_core["credential_readiness_ref"]),
        "host_binding_ref": normalized_ref(spec_core["host_binding_ref"]),
        "future_root_admission": {
            "root": str(relative), "execution_id": binding.execution_id,
            "expected_absent": True, "mode": "0700",
        },
        "session_spec_core_sha256": sha256_bytes(canonical_bytes(dict(spec_core))),
        "four_lane_identity_sha256": four_lane_identity_sha256,
        "trust_policy": "operational_host_evidence",
        "limitations": [NON_CRYPTO_LIMITATION],
    }
    value["custody_sha256"] = sha256_bytes(canonical_bytes(value))
    return value


def validate_live_session_custody(root: Path, custody: Mapping[str, Any], *,
                                  spec: Mapping[str, Any], directory: Path,
                                  root_state: str, now: datetime | None = None) -> dict[str, Any]:
    required = {"version", "source_closure", "materialization_head_ref",
                "host_profile_ref", "credential_readiness_ref", "host_binding_ref",
                "future_root_admission", "session_spec_core_sha256",
                "four_lane_identity_sha256", "trust_policy", "limitations",
                "custody_sha256"}
    _need(isinstance(custody, Mapping) and set(custody) == required
          and custody["version"] == VERSION, "LIVE_CUSTODY_INVALID")
    unsigned = {key: value for key, value in custody.items() if key != "custody_sha256"}
    _need(custody["custody_sha256"] == sha256_bytes(canonical_bytes(unsigned)),
          "LIVE_CUSTODY_INVALID")
    _need(custody["session_spec_core_sha256"]
          == sha256_bytes(canonical_bytes(session_spec_core(spec))),
          "LIVE_CUSTODY_SESSION_SPEC")
    for key in ("host_profile_ref", "credential_readiness_ref", "host_binding_ref"):
        _need(custody[key] == normalized_ref(spec[key]), "LIVE_CUSTODY_SESSION_SPEC")
    _need(custody["materialization_head_ref"] == normalized_ref(spec["host_materialization_manifest_ref"]),
          "LIVE_CUSTODY_SESSION_SPEC")
    revalidate_source_closure(root, custody["source_closure"])
    host = "codex" if spec["host_adapter"] == "codex_native_web" else "claude"
    bundle = reopen_and_validate_materialized_bundle(
        root, head_ref=custody["materialization_head_ref"],
        profile_ref=custody["host_profile_ref"],
        credential_ref=custody["credential_readiness_ref"],
        binding_ref=custody["host_binding_ref"], host=host, now=now)
    admission = custody["future_root_admission"]
    _need(isinstance(admission, Mapping) and set(admission) == {
        "root", "execution_id", "expected_absent", "mode"}, "LIVE_CUSTODY_ROOT_ADMISSION")
    relative = _safe_relative(admission["root"], "LIVE_CUSTODY_ROOT_ADMISSION")
    expected = (Path(root).resolve(strict=True) / relative).resolve(strict=False)
    actual = Path(directory).resolve(strict=False)
    _need(actual == expected and admission["execution_id"] == spec["identities"]["execution_id"]
          and admission["expected_absent"] is True and admission["mode"] == "0700",
          "LIVE_CUSTODY_ROOT_ADMISSION")
    _need(root_state in {"absent", "initialize", "active"}, "LIVE_CUSTODY_ROOT_STATE")
    if root_state == "absent":
        _need(not actual.exists(), "LIVE_CUSTODY_ROOT_EXISTS")
    else:
        _need(actual.is_dir() and not actual.is_symlink()
              and stat.S_IMODE(actual.stat().st_mode) == 0o700,
              "LIVE_CUSTODY_ROOT_CONSUME")
        if root_state == "initialize":
            _need(not any(actual.iterdir()), "LIVE_CUSTODY_ROOT_CONSUME")
        else:
            _need((actual / "session.json").is_file(), "LIVE_CUSTODY_ROOT_ACTIVE")
    return {"custody_sha256": custody["custody_sha256"], "bundle": bundle,
            "source_closure_sha256": custody["source_closure"]["sources_sha256"]}


def build_terminal_custody(*, custody_ref: Mapping[str, Any], custody_sha256: str,
                           readiness_packet_sha256: str, dispatch_namespace: str,
                           checker_ref: Mapping[str, Any], reconciliation_ref: Mapping[str, Any],
                           result_ref: Mapping[str, Any]) -> dict[str, Any]:
    value = {
        "version": VERSION,
        "custody_ref": dict(custody_ref), "custody_sha256": custody_sha256,
        "readiness_packet_sha256": _hash(readiness_packet_sha256, "LIVE_TERMINAL_CUSTODY"),
        "dispatch_namespace": dispatch_namespace,
        "checker_ref": dict(checker_ref), "reconciliation_ref": dict(reconciliation_ref),
        "result_ref": dict(result_ref),
    }
    value["terminal_sha256"] = sha256_bytes(canonical_bytes(value))
    return value


def validate_terminal_custody(value: Mapping[str, Any]) -> None:
    required = {"version", "custody_ref", "custody_sha256", "readiness_packet_sha256",
                "dispatch_namespace", "checker_ref", "reconciliation_ref", "result_ref",
                "terminal_sha256"}
    _need(isinstance(value, Mapping) and set(value) == required
          and value["version"] == VERSION, "LIVE_TERMINAL_CUSTODY")
    unsigned = {key: row for key, row in value.items() if key != "terminal_sha256"}
    _need(value["terminal_sha256"] == sha256_bytes(canonical_bytes(unsigned)),
          "LIVE_TERMINAL_CUSTODY")


def publish_private_json_bundle(root: Path, output_relative: str | Path,
                                values: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Publish a complete private JSON directory with one no-partial-visibility rename."""
    root = Path(root).resolve(strict=True)
    relative = _safe_relative(str(output_relative), "LIVE_CUSTODY_BUNDLE_PATH")
    _need(relative.parts[0] == ".research-sources", "LIVE_CUSTODY_BUNDLE_PATH")
    output = root / relative
    _need(not output.exists(), "LIVE_CUSTODY_BUNDLE_EXISTS")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        _need(current.is_dir() and not current.is_symlink()
              and current.stat().st_uid == os.getuid()
              and stat.S_IMODE(current.stat().st_mode) == 0o700,
              "LIVE_CUSTODY_BUNDLE_PARENT")
    staging = output.parent / f".{output.name}.staging-{os.getpid()}"
    _need(not staging.exists(), "LIVE_CUSTODY_BUNDLE_STAGING")
    staging.mkdir(mode=0o700)
    refs: dict[str, dict[str, str]] = {}
    try:
        for name, value in sorted(values.items()):
            _need(Path(name).name == name and name.endswith(".json"),
                  "LIVE_CUSTODY_BUNDLE_MEMBER")
            raw = canonical_bytes(value) + b"\n"
            _need(len(raw) <= _MAX, "LIVE_CUSTODY_BUNDLE_MEMBER")
            path = staging / name
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            try:
                view = memoryview(raw); written = 0
                while written < len(view):
                    count = os.write(descriptor, view[written:])
                    _need(count > 0, "LIVE_CUSTODY_BUNDLE_WRITE")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            refs[name] = {"path": str(relative / name), "sha256": sha256_bytes(raw)}
        directory_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _need(not output.exists(), "LIVE_CUSTODY_BUNDLE_EXISTS")
        os.rename(staging, output)
        parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        _need(output.is_dir() and not output.is_symlink()
              and set(path.name for path in output.iterdir()) == set(values),
              "LIVE_CUSTODY_BUNDLE_VERIFY")
        for name, ref in refs.items():
            _safe_file(root, ref, "LIVE_CUSTODY_BUNDLE_VERIFY")
        return refs
    except Exception:
        if staging.exists():
            for path in staging.iterdir():
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            try:
                staging.rmdir()
            except OSError:
                pass
        raise
