"""Describe a no-side-effect, one-shot Codex/Claude live acceptance handoff.

This helper validates sealed live-session inputs and returns files that an operator
may later materialize and stage.  It never writes those files, calls a provider,
loads a scheduler, sends email, or reads credential values.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
from typing import Any

from investment.research.acquisition_claude_code import FETCH_PROMPT
from tuning.evals.information_fetch.live_e2e.readiness import (
    derive_live_contract, load_and_validate,
)
from shared.research_sources.live_session_custody import (
    LiveSessionCustodyError, current_source_closure,
    validate_live_session_custody,
)


VERSION = "acquisition-once-acceptance-1"
ENVELOPE_VERSION = "acquisition-live-session-envelope-1"
ENVELOPE_VERSION_V2 = "acquisition-live-session-envelope-2"
ROOT = Path(__file__).resolve().parents[4]
_SHA256 = re.compile(r"[a-f0-9]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
SOURCE_PATHS = (
    "investment/research/acquisition_live_session.py",
    "investment/research/acquisition_claude_code.py",
    "investment/research/acquisition_runner.py",
    "investment/research/acquisition_driver.py",
    "investment/research/acquisition_trace.py",
    "investment/research/acquisition_acceptance.py",
    "investment/research/acquisition_acceptance_cli.py",
    "shared/research_sources/host_web.py",
    "shared/research_sources/host_adapter_contracts.py",
    "shared/job_runtime/engine.py",
    "shared/job_runtime/model.py",
    "tuning/evals/information_fetch/live_e2e/readiness.py",
    "tuning/evals/information_fetch/live_e2e/materialize_host.py",
    "tuning/evals/information_fetch/live_e2e/once_acceptance.py",
)


class OnceAcceptanceError(ValueError):
    """A stable, secret-safe preparation error."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise OnceAcceptanceError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise OnceAcceptanceError("ONCE_ACCEPTANCE_JSON_INVALID") from error


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_file(root: Path, relative: str, code: str) -> Path:
    _need(isinstance(relative, str) and relative and not Path(relative).is_absolute()
          and ".." not in Path(relative).parts, code)
    path = root / relative
    _need(path.is_file() and not path.is_symlink()
          and path.resolve().is_relative_to(root.resolve()), code)
    return path


def _load_json(path: Path, root: Path, code: str) -> dict[str, Any]:
    _need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024 * 1024
          and path.resolve().is_relative_to(root.resolve()), code)
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        raise OnceAcceptanceError(code) from None
    _need(isinstance(value, dict), code)
    return value


def _snapshot(root: Path, patterns: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for pattern in patterns:
        _need(isinstance(pattern, str) and pattern and not Path(pattern).is_absolute()
              and ".." not in Path(pattern).parts, "ONCE_ACCEPTANCE_SETUP_LOCK_INVALID")
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink() and "node_modules" not in path.parts:
                values[str(path.relative_to(root))] = _sha(path.read_bytes())
    return dict(sorted(values.items()))


def require_setup_sync(root: Path) -> str:
    """Reproduce the setup audit comparison without refreshing or writing its lock."""
    lock_path = root / "docs/deployment/setup-lock.json"
    lock = _load_json(lock_path, root, "ONCE_ACCEPTANCE_SETUP_LOCK_INVALID")
    required = {"schema_version", "source_patterns", "documentation_patterns",
                "sources", "documentation"}
    _need(set(lock) == required and lock["schema_version"] == 1
          and isinstance(lock["source_patterns"], list)
          and isinstance(lock["documentation_patterns"], list),
          "ONCE_ACCEPTANCE_SETUP_LOCK_INVALID")
    current = {
        "schema_version": 1,
        "source_patterns": lock["source_patterns"],
        "documentation_patterns": lock["documentation_patterns"],
        "sources": _snapshot(root, lock["source_patterns"]),
        "documentation": _snapshot(root, lock["documentation_patterns"]),
    }
    _need(current == lock, "ONCE_ACCEPTANCE_SETUP_SYNC_REQUIRED")
    return _sha(canonical_bytes(lock))


def _workspace_ref(root: Path, row: Any, code: str) -> str:
    _need(isinstance(row, dict) and set(row) == {"path", "sha256"}
          and isinstance(row.get("sha256"), str)
          and _SHA256.fullmatch(row["sha256"]) is not None, code)
    path = _safe_file(root, row.get("path"), code)
    actual = _sha(path.read_bytes())
    _need(actual == row["sha256"], code)
    return actual


def _workspace_json_ref(root: Path, row: Any, code: str) -> tuple[dict[str, Any], str]:
    digest = _workspace_ref(root, row, code)
    path = _safe_file(root, row["path"], code)
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        raise OnceAcceptanceError(code) from None
    _need(isinstance(value, dict), code)
    return value, digest


def _session_binding(root: Path, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    binding, _digest = _workspace_json_ref(
        root, spec["host_binding_ref"], "ONCE_ACCEPTANCE_BINDING_CHANGED")
    manifest, _manifest_digest = _workspace_json_ref(
        root, spec["host_materialization_manifest_ref"],
        "ONCE_ACCEPTANCE_MATERIALIZATION_MANIFEST_CHANGED")
    required = {"version", "profile", "execution_id", "trace_id",
                "dispatch_namespace", "artifact_root", "cache_root", "budget",
                "binding_sha256"}
    _need(set(binding) == required
          and binding.get("version") == "host-adapter-contracts-1"
          and binding.get("execution_id") == spec["identities"]["execution_id"]
          and binding.get("trace_id") == spec["identities"]["trace_id"]
          and binding.get("profile", {}).get("adapter_id") == spec["host_adapter"],
          "ONCE_ACCEPTANCE_BINDING_INVALID")
    unsigned = {key: value for key, value in binding.items() if key != "binding_sha256"}
    _need(binding["binding_sha256"] == _sha(canonical_bytes(unsigned)),
          "ONCE_ACCEPTANCE_BINDING_INVALID")
    _need(isinstance(manifest, dict)
          and set(manifest) == {"kind", "version", "mcp", "generation",
                                "generation_sha256", "files", "hosts"}
          and manifest.get("kind") == "host_profile_materialization_head"
          and manifest.get("mcp") == "not_used",
          "ONCE_ACCEPTANCE_MATERIALIZATION_MANIFEST_INVALID")
    host = "codex" if spec["host_adapter"] == "codex_native_web" else "claude"
    _need(manifest.get("files", {}).get(f"{host}-profile.json")
              == spec["host_profile_ref"]["sha256"]
          and manifest.get("files", {}).get(f"{host}-credential-readiness.json")
              == spec["credential_readiness_ref"]["sha256"]
          and manifest.get("files", {}).get(f"{host}-binding.json")
              == spec["host_binding_ref"]["sha256"]
          and manifest.get("hosts", {}).get(host, {}).get("ready_for_live") is True,
          "ONCE_ACCEPTANCE_MATERIALIZATION_MANIFEST_INVALID")
    return binding, manifest


def load_session_envelope(path: Path, *, root: Path, expected_adapter: str) -> tuple[dict[str, Any], str]:
    envelope = _load_json(path, root, "ONCE_ACCEPTANCE_ENVELOPE_INVALID")
    _need(set(envelope) == {"schema_version", "session_spec", "seal"}
          and envelope["schema_version"] == ENVELOPE_VERSION_V2
          and isinstance(envelope["session_spec"], dict)
          and envelope["seal"] == {"algorithm": "sha256",
                                   "session_spec_sha256": _sha(canonical_bytes(envelope["session_spec"]))},
          "ONCE_ACCEPTANCE_ENVELOPE_INVALID")
    spec = envelope["session_spec"]
    required = {"schema_version", "readiness_envelope", "identities", "model_sha256",
                "host_adapter", "host_identity", "tool_identity",
                "host_profile_ref", "credential_readiness_ref",
                "host_binding_ref", "host_materialization_manifest_ref",
                "custody_ref", "run_wall_seconds", "provider_call_seconds"}
    _need(set(spec) == required and spec.get("host_adapter") == expected_adapter
          and spec.get("schema_version") == "acquisition-live-session-2",
          "ONCE_ACCEPTANCE_SESSION_SPEC_INVALID")
    expected_tool = "native_tools.web__run" if expected_adapter == "codex_native_web" else "claude_code.web"
    _need(spec.get("tool_identity") == expected_tool,
          "ONCE_ACCEPTANCE_SESSION_SPEC_INVALID")
    identities = spec.get("identities")
    _need(isinstance(identities, dict)
          and set(identities) == {"experiment_id", "execution_id", "trace_id"}
          and all(isinstance(value, str) and value for value in identities.values()),
          "ONCE_ACCEPTANCE_IDENTITY_INVALID")
    _need(type(spec.get("run_wall_seconds")) is int
          and type(spec.get("provider_call_seconds")) is int
          and 1 <= spec["provider_call_seconds"] <= spec["run_wall_seconds"] <= 600,
          "ONCE_ACCEPTANCE_DEADLINE_INVALID")
    readiness = _safe_file(root, spec["readiness_envelope"],
                           "ONCE_ACCEPTANCE_READINESS_INVALID")
    verdict = load_and_validate(readiness, root=root)
    _need(verdict.get("ready_for_provider_authorization_request") is True,
          "ONCE_ACCEPTANCE_READINESS_BLOCKED")
    _workspace_ref(root, spec["host_profile_ref"], "ONCE_ACCEPTANCE_PROFILE_CHANGED")
    _workspace_ref(root, spec["credential_readiness_ref"],
                   "ONCE_ACCEPTANCE_CREDENTIAL_RECEIPT_CHANGED")
    _session_binding(root, spec)
    custody, _custody_digest = _workspace_json_ref(
        root, spec["custody_ref"], "ONCE_ACCEPTANCE_CUSTODY_CHANGED")
    admission = custody.get("future_root_admission", {})
    try:
        validate_live_session_custody(
            root, custody, spec=spec, directory=root / admission.get("root", ""),
            root_state="absent")
    except LiveSessionCustodyError as error:
        raise OnceAcceptanceError(str(error)) from None
    return spec, envelope["seal"]["session_spec_sha256"]


def _private_relative(root: Path, value: str, code: str) -> str:
    _need(isinstance(value, str) and value and not Path(value).is_absolute()
          and ".." not in Path(value).parts, code)
    path = (root / value).absolute()
    private = (root / ".research-sources").absolute()
    _need(path.is_relative_to(private) and path != private, code)
    for ancestor in [path, *path.parents]:
        if ancestor == root:
            break
        _need(not ancestor.is_symlink(), code)
    return str(path)


def candidate_fingerprint(root: Path, runtime_config: str,
                          specs: tuple[dict[str, Any], ...], *,
                          session_roots: dict[str, str]) -> dict[str, Any]:
    config_path = _safe_file(root, runtime_config, "ONCE_ACCEPTANCE_RUNTIME_CONFIG_INVALID")
    sessions = {}
    source_closures = []
    for spec in specs:
        adapter = spec["host_adapter"]
        readiness_path = _safe_file(
            root, spec["readiness_envelope"], "ONCE_ACCEPTANCE_READINESS_INVALID")
        verdict = load_and_validate(readiness_path, root=root)
        readiness = _load_json(readiness_path, root, "ONCE_ACCEPTANCE_READINESS_INVALID")
        contract = derive_live_contract(readiness["packet"])
        binding, _manifest = _session_binding(root, spec)
        custody, custody_digest = _workspace_json_ref(
            root, spec["custody_ref"], "ONCE_ACCEPTANCE_CUSTODY_CHANGED")
        source_closures.append(custody["source_closure"])
        session_root = Path(session_roots[adapter])
        _need((root / binding["artifact_root"]).absolute() == session_root / "artifacts"
              and (root / binding["cache_root"]).absolute() == session_root / "cache",
              "ONCE_ACCEPTANCE_BINDING_ROOT_MISMATCH")
        sessions[adapter] = {
            "session_spec_sha256": _sha(canonical_bytes(spec)),
            "readiness_packet_sha256": verdict["packet_sha256"],
            "run_kind": contract["run_kind"],
            "exact_calls_sha256": _sha(canonical_bytes(contract["proposals"])),
            "identities_sha256": _sha(canonical_bytes(spec["identities"])),
            "session_root": session_roots[adapter],
            "host_profile_sha256": spec["host_profile_ref"]["sha256"],
            "credential_readiness_sha256": spec["credential_readiness_ref"]["sha256"],
            "host_binding_sha256": spec["host_binding_ref"]["sha256"],
            "materialization_manifest_sha256": spec["host_materialization_manifest_ref"]["sha256"],
            "custody_sha256": custody["custody_sha256"],
            "custody_ref_sha256": custody_digest,
            "source_closure_sha256": custody["source_closure"]["sources_sha256"],
        }
    _need(source_closures and all(row == source_closures[0] for row in source_closures),
          "ONCE_ACCEPTANCE_SOURCE_CLOSURE_MISMATCH")
    value = {"source_files": source_closures[0]["sources"],
             "setup_lock_sha256": source_closures[0]["setup_lock_ref"]["sha256"],
             "runtime_config_sha256": _sha(config_path.read_bytes()),
             "sessions": sessions}
    return {**value, "sha256": _sha(canonical_bytes(value))}


def _codex_prompt(*, root: Path, init_file: str, session_root: str,
                  terminal_receipt: str, expected_candidate_sha256: str,
                  session_binding: dict[str, Any]) -> str:
    python = shlex.quote(str(root / ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"))
    module = "investment.research.acquisition_live_session"
    directory = shlex.quote(session_root)
    init_path = shlex.quote(init_file)
    receipt = shlex.quote(terminal_receipt)
    return f"""Run exactly one sealed Codex native-web acquisition acceptance.
Candidate fingerprint: {expected_candidate_sha256}
Session spec SHA-256: {session_binding["session_spec_sha256"]}
Readiness packet SHA-256: {session_binding["readiness_packet_sha256"]}
Run kind: {session_binding["run_kind"]}
Exact calls SHA-256: {session_binding["exact_calls_sha256"]}
Identities SHA-256: {session_binding["identities_sha256"]}
Session root: {session_binding["session_root"]}
MCP status: not_used. Do not send email, trade, modify credentials, enable MCP, or alter scheduler state.
Use only the sealed init JSON at {init_path}; do not change its IDs, proposals, URLs, budgets, profiles, or deadlines.

1. Set `PYTHONPYCACHEPREFIX={shlex.quote(str(root / ".job-runtime/tmp/live-acceptance-pycache"))}` and run `{python} -B -m {module} init --directory {directory} --input-file {init_path}` once.
2. Run `{python} -B -m {module} next --directory {directory}`. For every dispatch, require tool_identity exactly `native_tools.web__run`, invoke that tool exactly once with the returned tool_input bytes/JSON, and first persist the exact JSON result in the private session root. Never substitute curl, another web tool, another query, or another URL.
3. Create the immutable host invocation receipt first and include its exact `host_invocation_receipt_ref` in capture input with returned host_adapter, host_identity, tool_identity, status, and observed backend. The receipt must bind dispatch/input/result hashes and times. Run `capture` once with that input and the exact private raw-result file. If the call outcome is unknown, capture status `unknown`, publish a terminal blocked receipt, and STOP: no retry, fallback, assessment, review, or finalization.
4. Continue `next` only when the session requests another dispatch. Respect the sealed fallback and all returned limits. Stop on permission denial, identity mismatch, deadline, policy/transient/circuit failure, or any unknown outcome.
5. When a screened packet is returned, create the bounded assessment input from literal captured text only and run `assess`. Before `review`, create the immutable reviewer-session receipt and include exact `reviewer_session_receipt_ref`; run `review` only with the sealed distinct reviewer/operator/author identities and immutable screened references; do not infer investment importance or claim independence not actually present.
6. Run `finalize` once, then `status`. Finalize runs reconciliation and the independent trace checker; require status passed, checker_status pass, complete_chains 1, credited_units 1, finalized true, and mcp_status not_used.
7. Publish one sanitized terminal JSON receipt atomically at {receipt}. It must bind the candidate fingerprint, envelope/session IDs, scheduled slot/attempt/thread IDs when available, due/start/end times, final/status JSON, result/verdict hashes, and any failure/unknown code. Include no raw provider output, prompt body, credentials, addresses, or tokens. A missing terminal receipt is failure.

This is one attempt. Never replay an existing or possibly-dispatched operation. Do not report acceptance merely from a shell exit code or your own assertion.
"""


def claude_packet(spec: dict[str, Any], *, session_root: str,
                  init_file: str, candidate_sha256: str) -> dict[str, Any]:
    return {
        "kind": "claude_cooperative_execution_packet",
        "version": VERSION,
        "scheduled": False,
        "current_host_cooperative_only": True,
        "candidate_sha256": candidate_sha256,
        "session_spec_sha256": _sha(canonical_bytes(spec)),
        "session_root": session_root,
        "init_input_file": init_file,
        "mcp_status": "not_used",
        "tool_specs": [
            {"tool_identity": "claude_code.WebSearch", "exact_input": {"query": "<next.tool_input.query>"},
             "allowed_when": "next.tool_identity == claude_code.WebSearch",
             "representation_scope": "current_search_metadata_only"},
            {"tool_identity": "claude_code.WebFetch",
             "exact_input": {"url": "<next.tool_input.url>", "prompt": FETCH_PROMPT},
             "allowed_when": "next.tool_identity == claude_code.WebFetch",
             "representation_scope": "rendered_extracted_representation"},
        ],
        "capture_steps": [
            "Run init once with the sealed Claude session spec, then run next.",
            "Verify the returned tool_identity and invoke exactly the returned tool_input once.",
            "Persist the exact JSON tool result privately before writing prose.",
            "Create an immutable host invocation receipt, then capture input with its host_invocation_receipt_ref, exact host/tool identities, exact actual_tool_input, captured_at, and returned/failed/unknown status.",
            "Run capture with the private raw-result file; on unknown outcome stop without retry or fallback.",
            "Repeat only when next returns another authorized operation; then assess, create a reviewer-session receipt, review with reviewer_session_receipt_ref, finalize, and status as permitted.",
            "Keep raw output private and report only bounded screened/final receipts.",
        ],
        "stop_rules": ["unknown_outcome", "permission_denied", "identity_mismatch",
                       "argument_mismatch", "deadline", "policy_or_transient_failure",
                       "unrequested_operation"],
        "claim_limit": "Not scheduled and not executed; this packet is preparation evidence only.",
    }


def describe() -> dict[str, Any]:
    return {
        "version": VERSION,
        "side_effects": [],
        "commands": ["describe", "setup"],
        "setup_output": ["one disabled-by-default future Codex once allocation",
                         "one Codex prompt", "sealed init input materializations",
                         "one unscheduled Claude cooperative packet"],
        "hard_gates": ["setup_sync", "sealed_ready_envelopes", "source_config_profile_fingerprint",
                       "distinct_host_ids_and_roots", "future_due_time", "one_non_replay_safe_attempt"],
        "never_performed": ["provider_call", "scheduler_stage_or_reload", "email", "credential_read",
                            "mcp_activation", "file_write"],
    }


def setup(*, change_id: str, due: datetime, codex_envelope: Path,
          runtime_config: str, codex_root: str, model_profile: str,
          claude_envelope: Path | None = None, claude_root: str | None = None,
          now: datetime | None = None, root: Path = ROOT) -> dict[str, Any]:
    """Return a staging manifest. The caller must explicitly materialize and stage it later."""
    root = root.resolve()
    _need(_ID.fullmatch(change_id or "") is not None, "ONCE_ACCEPTANCE_CHANGE_ID_INVALID")
    setup_lock_sha256 = require_setup_sync(root)
    codex_spec, codex_sha = load_session_envelope(codex_envelope, root=root,
                                                   expected_adapter="codex_native_web")
    claude_spec = claude_sha = claude_session_root = None
    if claude_envelope is not None or claude_root is not None:
        _need(claude_envelope is not None and claude_root is not None,
              "ONCE_ACCEPTANCE_CLAUDE_ARGUMENTS_INCOMPLETE")
        claude_spec, claude_sha = load_session_envelope(
            claude_envelope, root=root, expected_adapter="claude_code_web")
        _need(codex_sha != claude_sha and codex_spec["identities"] != claude_spec["identities"],
              "ONCE_ACCEPTANCE_HOST_IDENTITIES_NOT_DISTINCT")
        for key in codex_spec["identities"]:
            _need(codex_spec["identities"][key] != claude_spec["identities"][key],
                  "ONCE_ACCEPTANCE_HOST_IDENTITIES_NOT_DISTINCT")
    codex_session_root = _private_relative(root, codex_root, "ONCE_ACCEPTANCE_ROOT_INVALID")
    if claude_root is not None:
        claude_session_root = _private_relative(root, claude_root, "ONCE_ACCEPTANCE_ROOT_INVALID")
        _need(codex_session_root != claude_session_root,
              "ONCE_ACCEPTANCE_ROOTS_NOT_DISTINCT")
    _need(not Path(codex_session_root).exists(), "ONCE_ACCEPTANCE_ROOT_NOT_EMPTY")
    codex_custody, _ = _workspace_json_ref(
        root, codex_spec["custody_ref"], "ONCE_ACCEPTANCE_CUSTODY_CHANGED")
    _need(str((root / codex_custody["future_root_admission"]["root"]).absolute())
          == codex_session_root, "ONCE_ACCEPTANCE_ROOT_ADMISSION_MISMATCH")
    if claude_root is not None:
        _need(not Path(claude_session_root).exists(), "ONCE_ACCEPTANCE_ROOT_NOT_EMPTY")
        claude_custody, _ = _workspace_json_ref(
            root, claude_spec["custody_ref"], "ONCE_ACCEPTANCE_CUSTODY_CHANGED")
        _need(str((root / claude_custody["future_root_admission"]["root"]).absolute())
              == claude_session_root, "ONCE_ACCEPTANCE_ROOT_ADMISSION_MISMATCH")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _need(isinstance(due, datetime) and due.tzinfo is not None and due.utcoffset() is not None,
          "ONCE_ACCEPTANCE_DUE_INVALID")
    due = due.astimezone(timezone.utc)
    _need(now + timedelta(seconds=60) <= due <= now + timedelta(minutes=10),
          "ONCE_ACCEPTANCE_DUE_INVALID")
    _need(_ID.fullmatch(model_profile or "") is not None,
          "ONCE_ACCEPTANCE_MODEL_PROFILE_INVALID")
    specs = (codex_spec,) if claude_spec is None else (codex_spec, claude_spec)
    roots = {"codex_native_web": codex_session_root}
    if claude_session_root is not None:
        roots["claude_code_web"] = claude_session_root
    fingerprint = candidate_fingerprint(root, runtime_config, specs, session_roots=roots)
    base = root / ".job-runtime/acceptance" / change_id
    codex_init = str(base / "codex-init.json")
    claude_init = str(base / "claude-init.json")
    prompt_path = str(base / "codex-prompt.txt")
    terminal_receipt = str(base / "codex-terminal-receipt.json")
    prompt = _codex_prompt(root=root, init_file=codex_init,
                            session_root=codex_session_root,
                            terminal_receipt=terminal_receipt,
                            expected_candidate_sha256=fingerprint["sha256"],
                            session_binding=fingerprint["sessions"]["codex_native_web"])
    job = {
        "id": f"acquisition-{change_id}", "enabled": True,
        "schedule": {"kind": "once", "at": due.isoformat(), "grace_seconds": 180},
        "replay_safe": False, "model_profile": model_profile,
        "prompt_file": str(Path(prompt_path).relative_to(root)),
    }
    return {
        "version": VERSION,
        "prepared_at": now.isoformat(),
        "staged": False,
        "provider_called": False,
        "scheduler_called": False,
        "email_sent": False,
        "mcp_status": "not_used",
        "setup_lock_sha256": setup_lock_sha256,
        "candidate": fingerprint,
        "criteria": {"future_once": True, "one_attempt": True,
                     "max_start_lateness_seconds": 180,
                     "run_wall_seconds": codex_spec["run_wall_seconds"],
                     "provider_call_seconds": codex_spec["provider_call_seconds"]},
        "materialize_later": {
            "codex_init": {"path": codex_init, "value": codex_spec, "sha256": codex_sha},
            **({"claude_init": {"path": claude_init, "value": claude_spec,
                                  "sha256": claude_sha}} if claude_spec is not None else {}),
            "codex_prompt": {"path": prompt_path, "value": prompt, "sha256": _sha(prompt.encode())},
            "codex_allocation": {"schema_version": 1, "jobs": [job]},
            "terminal_receipt_path": terminal_receipt,
        },
        "claude": (claude_packet(claude_spec, session_root=claude_session_root,
                                 init_file=claude_init,
                                 candidate_sha256=fingerprint["sha256"])
                   if claude_spec is not None else None),
        "allowed_claim": "Provider-free setup description only; neither host has run and nothing is staged.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["describe", "setup"])
    parser.add_argument("--change-id")
    parser.add_argument("--due")
    parser.add_argument("--codex-envelope", type=Path)
    parser.add_argument("--claude-envelope", type=Path)
    parser.add_argument("--runtime-config", default=".job-runtime/config/runtime.json")
    parser.add_argument("--codex-root")
    parser.add_argument("--claude-root")
    parser.add_argument("--model-profile", default="research-source-acceptance")
    args = parser.parse_args()
    try:
        if args.command == "describe":
            result = describe()
        else:
            _need(all((args.change_id, args.due, args.codex_envelope, args.codex_root)),
                  "ONCE_ACCEPTANCE_ARGUMENT_REQUIRED")
            try:
                due = datetime.fromisoformat(args.due.replace("Z", "+00:00"))
            except ValueError:
                raise OnceAcceptanceError("ONCE_ACCEPTANCE_DUE_INVALID") from None
            result = setup(change_id=args.change_id, due=due,
                           codex_envelope=args.codex_envelope,
                           claude_envelope=args.claude_envelope,
                           runtime_config=args.runtime_config,
                           codex_root=args.codex_root, claude_root=args.claude_root,
                           model_profile=args.model_profile)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except OnceAcceptanceError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
