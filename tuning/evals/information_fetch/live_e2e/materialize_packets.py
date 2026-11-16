"""Materialize four provider-free live-E2E readiness and session packets.

This helper joins immutable host-materialization results to four sealed lanes. It
writes private JSON only and never invokes a provider, resolves credentials,
stages a scheduler job, sends email, or creates execution roots.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any, Mapping

from tuning.evals.information_fetch.live_e2e import readiness
from shared.research_sources.live_session_custody import (
    build_live_session_custody, publish_private_json_bundle,
    validate_four_lane_isolation,
)


VERSION = "live-e2e-packet-materializer-1"
INPUT_VERSION = "live-e2e-packet-materialization-input-1"
SESSION_VERSION = "acquisition-live-session-2"
ENVELOPE_VERSION = "acquisition-live-session-envelope-2"
MATERIALIZER_VERSION = "host-profile-materializer-1"
ROOT = Path(__file__).resolve().parents[4]
MAX_INPUT = 512 * 1024
MAX_OUTPUT = 512 * 1024
_SHA256 = re.compile(r"[a-f0-9]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
LANES = ("codex_smoke", "claude_smoke", "codex_narrow", "claude_narrow")
SMOKE_QUERY = 'site:newsroom.servicenow.com "ServiceNow Reports First Quarter 2025 Financial Results"'
_HOST = {
    "codex": ("codex_native_web", "native_tools.web__run"),
    "claude": ("claude_code_web", "claude_code.web"),
}
_REQUIRED_STOPS = [
    "no_find", "no_second_query", "no_unchanged_retry", "no_second_alternate",
    "no_provider_switch", "no_curl_substitution", "stop_on_unknown_outcome",
    "stop_on_policy_transient_circuit_or_post_dispatch_deadline",
]


class PacketMaterializationError(ValueError):
    """Stable provider-free packet materialization rejection."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise PacketMaterializationError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise PacketMaterializationError("PACKET_MATERIALIZE_JSON") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _need(key not in result, "PACKET_MATERIALIZE_INPUT")
        result[key] = value
    return result


def _strict(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    _need(isinstance(value, dict) and set(value) == keys, code)
    return value


def _private_file(root: Path, value: Any, code: str) -> Path:
    _need(isinstance(value, str) and value and len(value) <= 512, code)
    relative = Path(value)
    _need(not relative.is_absolute() and relative.parts and ".." not in relative.parts,
          code)
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        info = path.stat()
    except (OSError, ValueError):
        raise PacketMaterializationError(code) from None
    _need(path.is_file() and not path.is_symlink() and stat.S_ISREG(info.st_mode)
          and info.st_uid == os.getuid() and info.st_nlink == 1
          and stat.S_IMODE(info.st_mode) & 0o077 == 0
          and 0 < info.st_size <= MAX_INPUT, code)
    return resolved


def _ref(root: Path, row: Any, code: str) -> tuple[Path, dict[str, str]]:
    _need(isinstance(row, dict)
          and set(row) in ({"path", "sha256"}, {"path", "sha256", "reused"})
          and ("reused" not in row or type(row["reused"]) is bool), code)
    _need(isinstance(row["sha256"], str) and _SHA256.fullmatch(row["sha256"]), code)
    path = _private_file(root, row["path"], code)
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], code)
    return path, {"path": str(path.relative_to(root)), "sha256": row["sha256"]}


def _json_file(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError, RecursionError):
        raise PacketMaterializationError(code) from None
    _need(isinstance(value, dict), code)
    return value


def _hash_ref(root: Path, row: Any, code: str) -> tuple[dict[str, Any], dict[str, str]]:
    path, public = _ref(root, row, code)
    _need(Path(public["path"]).parts[0] == ".research-sources", code)
    return _json_file(path, code), public


def _identifier(value: Any, code: str) -> str:
    _need(isinstance(value, str) and _ID.fullmatch(value) is not None, code)
    return value


def _relative(value: Any, code: str) -> Path:
    _need(isinstance(value, str) and value and len(value) <= 512, code)
    path = Path(value)
    _need(not path.is_absolute() and path.parts and ".." not in path.parts
          and all(part not in {"", "."} for part in path.parts), code)
    return path


def _research_relative(value: Any, code: str) -> Path:
    path = _relative(value, code)
    _need(path.parts[0] == ".research-sources", code)
    return path


def _resolved(root: Path, value: Any, code: str) -> Path:
    relative = _relative(value, code)
    current = root
    for part in relative.parts:
        current = current / part
        _need(not current.is_symlink(), code)
    try:
        result = current.resolve(strict=False)
        result.relative_to(root)
    except (OSError, ValueError):
        raise PacketMaterializationError(code) from None
    _need(not current.exists() or (current.is_dir() and not any(current.iterdir())), code)
    return result


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _binding_hash(binding: dict[str, Any]) -> str:
    value = dict(binding)
    claimed = value.pop("binding_sha256", None)
    _need(isinstance(claimed, str) and _SHA256.fullmatch(claimed),
          "PACKET_MATERIALIZE_BINDING")
    _need(hashlib.sha256(canonical_bytes(value)).hexdigest() == claimed,
          "PACKET_MATERIALIZE_BINDING")
    return claimed


def _load_materialized(root: Path, row: Any, kind: str) -> dict[str, Any]:
    result, result_ref = _hash_ref(root, row, "PACKET_MATERIALIZE_HOST_RESULT")
    required = {"version", "output_directory", "mcp", "hosts", "generation",
                "manifest", "bundle_sha256"}
    _strict(result, required, "PACKET_MATERIALIZE_HOST_RESULT")
    _need(result["version"] == MATERIALIZER_VERSION and result["mcp"] == "not_used"
          and set(result["hosts"]) == {"codex", "claude"},
          "PACKET_MATERIALIZE_HOST_RESULT")
    generation = _strict(result["generation"], {"path", "sha256", "reused"},
                         "PACKET_MATERIALIZE_HOST_RESULT")
    manifest, manifest_ref = _hash_ref(root, result["manifest"],
                                       "PACKET_MATERIALIZE_HOST_MANIFEST")
    _need(result["bundle_sha256"] == manifest_ref["sha256"]
          and manifest.get("kind") == "host_profile_materialization_head"
          and manifest.get("generation") == Path(generation["path"]).name
          and manifest.get("generation_sha256") == generation["sha256"],
          "PACKET_MATERIALIZE_HOST_MANIFEST")
    _need(isinstance(manifest.get("files"), dict)
          and set(manifest["files"]) == {
              f"{host}-{suffix}.json"
              for host in ("codex", "claude")
              for suffix in ("profile", "credential-readiness", "binding")
          }
          and isinstance(manifest.get("hosts"), dict),
          "PACKET_MATERIALIZE_HOST_MANIFEST")
    generation_path = _relative(generation["path"], "PACKET_MATERIALIZE_HOST_MANIFEST")
    _need(generation_path.name == manifest["generation"]
          and generation["sha256"] == manifest["generation_sha256"],
          "PACKET_MATERIALIZE_HOST_MANIFEST")
    hosts: dict[str, Any] = {}
    for host in ("codex", "claude"):
        host_row = _strict(result["hosts"][host],
                           {"profile", "credential_readiness", "binding", "ready_for_live"},
                           "PACKET_MATERIALIZE_HOST_RESULT")
        _need(host_row["ready_for_live"] is True, "PACKET_MATERIALIZE_HOST_NOT_READY")
        profile, profile_ref = _hash_ref(root, host_row["profile"],
                                         "PACKET_MATERIALIZE_PROFILE")
        credential, credential_ref = _hash_ref(root, host_row["credential_readiness"],
                                               "PACKET_MATERIALIZE_CREDENTIAL")
        binding, binding_ref = _hash_ref(root, host_row["binding"],
                                         "PACKET_MATERIALIZE_BINDING")
        adapter, backend = _HOST[host]
        refs = {"profile": profile_ref, "credential-readiness": credential_ref,
                "binding": binding_ref}
        _need(all(Path(row["path"]).parent == generation_path
                  and Path(row["path"]).name == f"{host}-{suffix}.json"
                  and manifest["files"].get(f"{host}-{suffix}.json") == row["sha256"]
                  for suffix, row in refs.items())
              and manifest["hosts"].get(host, {}).get("ready_for_live") is True,
              "PACKET_MATERIALIZE_HOST_MANIFEST")
        _need(profile.get("adapter_id") == adapter
              and profile.get("configured_backend") == backend
              and credential.get("adapter_id") == adapter
              and credential.get("capability_observed") == backend
              and credential.get("status") == "ready"
              and credential.get("source") == "host_returned_operational"
              and credential.get("trust_policy") == "operational_host_evidence"
              and credential.get("host_session_id")
              and credential.get("credential_values_present") is False
              and binding.get("profile") == profile,
              "PACKET_MATERIALIZE_HOST_MISMATCH")
        _binding_hash(binding)
        budget = binding.get("budget")
        _need(isinstance(budget, dict) and set(budget) == {
            "search_items", "open_items", "provider_items", "concurrency",
            "call_timeout_seconds", "run_timeout_seconds"},
            "PACKET_MATERIALIZE_BUDGET")
        expected = {"search_items": 1, "open_items": 0 if kind == "smoke" else 2,
                    "provider_items": 1 if kind == "smoke" else 3,
                    "concurrency": 1}
        _need(all(budget.get(key) == value for key, value in expected.items())
              and type(budget.get("call_timeout_seconds")) is int
              and type(budget.get("run_timeout_seconds")) is int
              and 1 <= budget["call_timeout_seconds"] <= budget["run_timeout_seconds"] <= 600,
              "PACKET_MATERIALIZE_BUDGET")
        hosts[host] = {
            "profile": profile, "credential": credential, "binding": binding,
            "profile_ref": profile_ref, "credential_ref": credential_ref,
            "binding_ref": binding_ref,
        }
    return {"result_ref": result_ref, "manifest_ref": manifest_ref,
            "generation": generation, "hosts": hosts}


def _repository_evidence(root: Path, template: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for row in template["packet"]["repository_evidence"]:
        path = root / row["path"]
        _need(path.is_file() and not path.is_symlink(), "PACKET_MATERIALIZE_REPOSITORY")
        rows.append({"path": row["path"],
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def _ready_packet(root: Path, template: dict[str, Any], *, host: str, kind: str,
                  lane: dict[str, Any], materialized: dict[str, Any], cutoff: str,
                  owners: dict[str, str]) -> dict[str, Any]:
    packet = deepcopy(template["packet"])
    packet["schema_version"] = readiness.VERSION
    packet["run_kind"] = kind
    packet["status"] = "ready"
    packet["unresolved"] = []
    packet["case"]["search_query"] = SMOKE_QUERY
    packet["budgets"].update({
        "search_items": 1, "open_items": 0 if kind == "smoke" else 2,
        "provider_items": 1 if kind == "smoke" else 3,
        "fallbacks": 0 if kind == "smoke" else 1, "concurrency": 1,
        "cache_enabled": False, "raw_result_limit_bytes": 65536,
        "run_wall_seconds": lane["run_wall_seconds"],
        "provider_call_seconds": lane["provider_call_seconds"],
    })
    binding = materialized["hosts"][host]["binding"]
    packet["artifacts"].update({
        "artifact_root": str(root / binding["artifact_root"]),
        "runtime_root": str(root / lane["session_root"]),
        "raw_retention": owners["raw_retention"],
        "reconciliation_owner": owners["reconciliation_owner"],
        "retention_owner": owners["retention_owner"],
        "rollback_target": owners["rollback_target"],
    })
    packet["source_contract"]["cutoff"] = cutoff
    packet["effective_config"] = readiness.canonical_effective_config(root)
    packet["repository_evidence"] = _repository_evidence(root, template)
    packet["identity_rules"]["experiment_id"] = lane["experiment_id"]
    packet["stop_rules"] = list(_REQUIRED_STOPS)
    return packet


def _session_spec(root: Path, readiness_ref: dict[str, str], host: str,
                  lane: dict[str, Any], materialized: dict[str, Any],
                  model_sha256: str) -> dict[str, Any]:
    row = materialized["hosts"][host]
    binding = row["binding"]
    credential = row["credential"]
    adapter, backend = _HOST[host]
    return {
        "schema_version": SESSION_VERSION,
        "readiness_envelope": readiness_ref["path"],
        "identities": {"experiment_id": lane["experiment_id"],
                       "execution_id": binding["execution_id"],
                       "trace_id": binding["trace_id"]},
        "model_sha256": model_sha256,
        "host_adapter": adapter,
        "host_identity": credential["host_session_id"],
        "tool_identity": backend,
        "host_profile_ref": row["profile_ref"],
        "credential_readiness_ref": row["credential_ref"],
        "host_binding_ref": row["binding_ref"],
        "host_materialization_manifest_ref": materialized["manifest_ref"],
        "run_wall_seconds": lane["run_wall_seconds"],
        "provider_call_seconds": lane["provider_call_seconds"],
    }


def _atomic_json(path: Path, value: Any, *, root: Path) -> dict[str, str]:
    data = canonical_bytes(value) + b"\n"
    _need(len(data) <= MAX_OUTPUT, "PACKET_MATERIALIZE_OUTPUT_LIMIT")
    temp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise PacketMaterializationError("PACKET_MATERIALIZE_WRITE") from None
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            _need(count > 0, "PACKET_MATERIALIZE_WRITE")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        raise PacketMaterializationError("PACKET_MATERIALIZE_WRITE") from None
    return {"path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(data).hexdigest()}


def materialize_packets(value: dict[str, Any], *, workspace_root: Path = ROOT) -> dict[str, Any]:
    root = Path(workspace_root).resolve(strict=True)
    required = {"schema_version", "output_directory", "cutoff", "model_sha256",
                "owners", "materialized", "lanes"}
    _strict(value, required, "PACKET_MATERIALIZE_INPUT")
    _need(value["schema_version"] == INPUT_VERSION
          and isinstance(value["model_sha256"], str)
          and _SHA256.fullmatch(value["model_sha256"]), "PACKET_MATERIALIZE_INPUT")
    try:
        cutoff = datetime.fromisoformat(value["cutoff"])
    except (TypeError, ValueError):
        raise PacketMaterializationError("PACKET_MATERIALIZE_CUTOFF") from None
    _need(cutoff.tzinfo is not None and cutoff.utcoffset() is not None,
          "PACKET_MATERIALIZE_CUTOFF")
    owners = _strict(value["owners"], {"raw_retention", "reconciliation_owner",
                     "retention_owner", "rollback_target"}, "PACKET_MATERIALIZE_OWNERS")
    _need(all(isinstance(item, str) and item.strip() for item in owners.values()),
          "PACKET_MATERIALIZE_OWNERS")
    materialized_rows = _strict(value["materialized"], {"smoke", "narrow"},
                                "PACKET_MATERIALIZE_HOST_RESULT")
    materialized = {kind: _load_materialized(root, materialized_rows[kind], kind)
                    for kind in ("smoke", "narrow")}
    lane_rows = _strict(value["lanes"], set(LANES), "PACKET_MATERIALIZE_LANES")
    lanes: dict[str, dict[str, Any]] = {}
    roots: list[Path] = []
    session_roots: dict[str, Path] = {}
    for lane_name in LANES:
        lane = _strict(lane_rows[lane_name], {"session_root", "registry_path",
                       "publication_root", "unknown_outcome_fence", "experiment_id",
                       "run_wall_seconds", "provider_call_seconds"},
                       "PACKET_MATERIALIZE_LANE")
        _identifier(lane["experiment_id"], "PACKET_MATERIALIZE_IDENTITY")
        _need(type(lane["run_wall_seconds"]) is int
              and type(lane["provider_call_seconds"]) is int
              and 1 <= lane["provider_call_seconds"] <= lane["run_wall_seconds"] <= 600,
              "PACKET_MATERIALIZE_DEADLINE")
        _research_relative(lane["session_root"], "PACKET_MATERIALIZE_ROOT")
        session_root = _resolved(root, lane["session_root"], "PACKET_MATERIALIZE_ROOT")
        session_roots[lane_name] = session_root
        roots.append(session_root)
        for key in ("publication_root", "unknown_outcome_fence"):
            _research_relative(lane[key], "PACKET_MATERIALIZE_ROOT")
            roots.append(_resolved(root, lane[key], "PACKET_MATERIALIZE_ROOT"))
        registry = _research_relative(lane["registry_path"], "PACKET_MATERIALIZE_ROOT")
        _need(registry.suffix == ".json", "PACKET_MATERIALIZE_ROOT")
        roots.append(_resolved(root, str(registry.parent), "PACKET_MATERIALIZE_ROOT"))
        lanes[lane_name] = lane
    for kind in ("smoke", "narrow"):
        for host in ("codex", "claude"):
            binding = materialized[kind]["hosts"][host]["binding"]
            lane_name = f"{host}_{kind}"
            session_root = session_roots[lane_name]
            _research_relative(binding["artifact_root"], "PACKET_MATERIALIZE_ROOT")
            _research_relative(binding["cache_root"], "PACKET_MATERIALIZE_ROOT")
            artifact = _resolved(root, binding["artifact_root"], "PACKET_MATERIALIZE_ROOT")
            cache = _resolved(root, binding["cache_root"], "PACKET_MATERIALIZE_ROOT")
            _need(artifact == session_root / "artifacts" and cache == session_root / "cache",
                  "PACKET_MATERIALIZE_BINDING_ROOT")
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            _need(not _overlap(left, right), "PACKET_MATERIALIZE_ROOT_OVERLAP")
    isolation = {}
    for lane_name in LANES:
        host, kind = lane_name.split("_", 1)
        lane = lanes[lane_name]
        binding = materialized[kind]["hosts"][host]["binding"]
        credential = materialized[kind]["hosts"][host]["credential"]
        isolation[lane_name] = {
            "experiment_id": lane["experiment_id"],
            "execution_id": binding["execution_id"],
            "trace_id": binding["trace_id"],
            "dispatch_namespace": binding["dispatch_namespace"],
            "host_session_id": credential["host_session_id"],
            "session_root": lane["session_root"],
            "artifact_root": binding["artifact_root"],
            "cache_root": binding["cache_root"],
            "registry_root": str(Path(lane["registry_path"]).parent),
            "publication_root": lane["publication_root"],
            "unknown_outcome_fence": lane["unknown_outcome_fence"],
        }
    validate_four_lane_isolation(isolation, root=root)
    four_lane_identity_sha256 = hashlib.sha256(canonical_bytes(isolation)).hexdigest()
    output_relative = _research_relative(
        value["output_directory"], "PACKET_MATERIALIZE_OUTPUT")
    output = root / output_relative
    _need(not output.exists() and not any(_overlap(output.resolve(strict=False), item)
                                         for item in roots), "PACKET_MATERIALIZE_OUTPUT")
    parent = output.parent
    _need(parent.is_dir() and not parent.is_symlink()
          and parent.stat().st_uid == os.getuid()
          and stat.S_IMODE(parent.stat().st_mode) == 0o700,
          "PACKET_MATERIALIZE_OUTPUT")
    template = _json_file(root / "tuning/evals/information_fetch/live_e2e/readiness-template.json",
                          "PACKET_MATERIALIZE_TEMPLATE")
    values: dict[str, Any] = {}
    result: dict[str, Any] = {"version": VERSION, "lanes": {}}
    for lane_name in LANES:
        host, kind = lane_name.split("_", 1)
        lane = lanes[lane_name]
        packet = _ready_packet(root, template, host=host, kind=kind, lane=lane,
                               materialized=materialized[kind], cutoff=value["cutoff"],
                               owners=owners)
        envelope = readiness.seal_packet(packet)
        verdict = readiness.validate_envelope(envelope, root=root)
        _need(verdict["ready_for_provider_authorization_request"] is True,
              "PACKET_MATERIALIZE_READINESS")
        readiness_name = f"{lane_name}-readiness.json"
        readiness_ref = {"path": str(output_relative / readiness_name),
                         "sha256": hashlib.sha256(canonical_bytes(envelope)+b"\n").hexdigest()}
        spec = _session_spec(root, readiness_ref, host, lane,
                             materialized[kind], value["model_sha256"])
        custody = build_live_session_custody(
            root, spec_core=spec, host=host, future_root=lane["session_root"],
            four_lane_identity_sha256=four_lane_identity_sha256)
        custody_name = f"{lane_name}-custody.json"
        custody_ref = {"path": str(output_relative / custody_name),
                       "sha256": hashlib.sha256(canonical_bytes(custody)+b"\n").hexdigest()}
        spec["custody_ref"] = custody_ref
        spec_name = f"{lane_name}-session-spec.json"
        spec_ref = {"path": str(output_relative / spec_name),
                    "sha256": hashlib.sha256(canonical_bytes(spec)+b"\n").hexdigest()}
        outer = {"schema_version": ENVELOPE_VERSION, "session_spec": spec,
                 "seal": {"algorithm": "sha256",
                          "session_spec_sha256": hashlib.sha256(canonical_bytes(spec)).hexdigest()}}
        envelope_name = f"{lane_name}-session-envelope.json"
        session_ref = {"path": str(output_relative / envelope_name),
                       "sha256": hashlib.sha256(canonical_bytes(outer)+b"\n").hexdigest()}
        values.update({readiness_name: envelope, custody_name: custody,
                       spec_name: spec, envelope_name: outer})
        result["lanes"][lane_name] = {
            "run_kind": kind, "host": host, "readiness": readiness_ref,
            "session_spec": spec_ref, "session_envelope": session_ref,
            "host_profile_ref": spec["host_profile_ref"],
            "credential_readiness_ref": spec["credential_readiness_ref"],
            "host_binding_ref": spec["host_binding_ref"], "custody_ref": custody_ref,
            "session_root": lane["session_root"], "registry_path": lane["registry_path"],
            "publication_root": lane["publication_root"],
            "unknown_outcome_fence": lane["unknown_outcome_fence"],
        }
    result["materialized"] = {
        kind: {"result_ref": materialized[kind]["result_ref"],
               "manifest_ref": materialized[kind]["manifest_ref"],
               "generation": materialized[kind]["generation"]}
        for kind in ("smoke", "narrow")}
    result["smoke_query"] = SMOKE_QUERY
    result["claim_limit"] = "Provider-free packet sealing only; no provider authorization or call."
    manifest_name = "packet-materialization-manifest.json"
    values[manifest_name] = result
    refs = publish_private_json_bundle(root, output_relative, values)
    # Verify predicted references match the atomic publisher.
    for lane in result["lanes"].values():
        for key in ("readiness", "session_spec", "session_envelope", "custody_ref"):
            _need(refs[Path(lane[key]["path"]).name] == lane[key], "PACKET_MATERIALIZE_WRITE")
    result["manifest"] = refs[manifest_name]
    return json.loads(canonical_bytes(result))


def describe() -> dict[str, Any]:
    return {"version": VERSION, "commands": ["describe", "materialize"],
            "lanes": list(LANES), "smoke_query": SMOKE_QUERY,
            "provider_called": False, "scheduler_called": False, "mcp": "not_used"}


def _load_input(path: Path) -> dict[str, Any]:
    try:
        value = str(path.relative_to(ROOT) if path.is_absolute() else path)
    except ValueError:
        raise PacketMaterializationError("PACKET_MATERIALIZE_INPUT_FILE") from None
    path = _private_file(ROOT, value, "PACKET_MATERIALIZE_INPUT_FILE")
    return _json_file(path, "PACKET_MATERIALIZE_INPUT_FILE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="materialize_packets")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe")
    materialize_cmd = commands.add_parser("materialize")
    materialize_cmd.add_argument("--input-file", required=True)
    args = parser.parse_args(argv)
    try:
        result = describe() if args.command == "describe" else materialize_packets(
            _load_input(Path(args.input_file)))
    except PacketMaterializationError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
