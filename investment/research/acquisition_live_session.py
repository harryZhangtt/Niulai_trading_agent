"""Bounded cooperative entrypoint for one hosted-native acquisition session.

This module never calls a provider. A trusted Codex or Claude Code host calls
``next``, invokes exactly the returned host tool input once, writes the exact JSON
result to a private file, and calls ``capture``. Raw provider output is never
printed. Local success is structural evidence, not acquisition-quality evidence.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from investment.research.acquisition_claude_code import (
    CLAUDE_CODE_FETCH,
    CLAUDE_CODE_SEARCH,
    prepare_claude_code_call,
)
from investment.research.acquisition_driver import AcquisitionDriver
from investment.research.acquisition_orchestration import (
    AcquisitionController,
    compile_prefetch_manifest,
)
from investment.research.acquisition_review import record_reviewer_decision
from investment.research.acquisition_runner import (
    HostedAcquisitionRunner,
    HostedProviderResponse,
    RunnerError,
)
from investment.research.acquisition_trace import (
    check_acquisition_smoke_trace,
    check_acquisition_trace,
    reconcile_terminal_ledgers,
)
from shared.job_runtime.service import atomic
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchIdentity,
    DispatchState,
    ExactArguments,
    RunIdentity,
)
from shared.research_sources.artifacts import ROOT, SourceError, private_path, read, require, save
from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    Capability,
    CredentialReadinessReceipt,
    CredentialReadinessStatus,
    CredentialRef,
    CredentialSource,
    HostAdapterProfile,
    HostContractError,
    HostInvocationReceipt,
    NON_CRYPTO_LIMITATION,
    Operation,
    OperationalEvidenceSource,
    OperationalTerminalStatus,
    OperationalTrustPolicy,
    ReviewerSessionReceipt,
    RuntimeProfileRef,
    ToolBinding,
    WorkspaceFileRef,
)
from shared.research_sources.live_session_custody import (
    LiveSessionCustodyError, build_terminal_custody,
    validate_live_session_custody, validate_terminal_custody,
)
from shared.research_sources.host_web import HostWeb, freeze_config
from tuning.evals.information_fetch.live_e2e.readiness import (
    VERSION as READINESS_V2,
    derive_live_contract,
    load_and_validate,
)


VERSION = "acquisition-live-session-1"
SESSION_SPEC_V2 = "acquisition-live-session-2"
MAX_INPUT = 256 * 1024
MAX_RAW = 65536
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")
_BACKEND = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SECRET_MARKER = re.compile(r"(?i)(?:^sk-|bearer|api[_-]?key|access[_-]?token|password|secret)")
_HOST_ADAPTERS = {
    "codex_native_web": {
        "configured_backend": "native_tools.web__run",
        "search_tool": "native_tools.web__run",
        "open_tool": "native_tools.web__run",
    },
    "claude_code_web": {
        "configured_backend": "claude_code.web",
        "search_tool": CLAUDE_CODE_SEARCH,
        "open_tool": CLAUDE_CODE_FETCH,
    },
}


class LiveSessionError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise LiveSessionError(code)


def _load_json(path, maximum=MAX_INPUT):
    path = private_path(path)
    _need(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum,
          "ACQ_LIVE_INPUT_INVALID")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        raise LiveSessionError("ACQ_LIVE_INPUT_INVALID") from None
    _need(isinstance(value, dict), "ACQ_LIVE_INPUT_INVALID")
    return value


def _load_workspace_ref(row, code):
    try:
        ref = WorkspaceFileRef(**row)
        path = ref.verify(ROOT, code)
        value = json.loads(path.read_bytes())
    except (HostContractError, TypeError, OSError, json.JSONDecodeError):
        raise LiveSessionError(code) from None
    _need(isinstance(value, dict), code)
    return ref, value


def _validate_host_readiness(spec):
    profile_ref, profile = _load_workspace_ref(
        spec.get("host_profile_ref"), "ACQ_LIVE_HOST_PROFILE_INVALID")
    credential_ref, credential = _load_workspace_ref(
        spec.get("credential_readiness_ref"), "ACQ_LIVE_CREDENTIAL_READINESS_INVALID")
    adapter = _HOST_ADAPTERS.get(spec.get("host_adapter"))
    _need(set(profile) == {"version", "adapter_id", "configured_backend",
                           "tool_bindings", "capabilities", "runtime",
                           "credential", "mcp"},
          "ACQ_LIVE_HOST_PROFILE_INVALID")
    _need(isinstance(credential, dict),
          "ACQ_LIVE_CREDENTIAL_READINESS_INVALID")
    expected_adapter = (AdapterId.CODEX_NATIVE_WEB.value
                        if spec.get("host_adapter") == "codex_native_web"
                        else AdapterId.CLAUDE_CODE_WEB.value)
    _need(adapter is not None and profile.get("version") == "host-adapter-contracts-1"
          and profile.get("adapter_id") == expected_adapter
          and profile.get("configured_backend") == adapter["configured_backend"],
          "ACQ_LIVE_HOST_PROFILE_INVALID")
    bindings = {row.get("operation"): row.get("observed_tool_identity")
                for row in profile.get("tool_bindings", []) if isinstance(row, dict)}
    _need(bindings.get("search") == adapter["search_tool"]
          and bindings.get("open") == adapter["open_tool"],
          "ACQ_LIVE_HOST_PROFILE_INVALID")
    public_credential = profile.get("credential")
    try:
        parsed_credential = CredentialRef(
            owner_ref=public_credential["owner_ref"],
            source=CredentialSource(public_credential["source"]),
            profile_ref=public_credential["profile_ref"],
            fingerprint_sha256=public_credential.get("fingerprint_sha256"),
        )
    except (KeyError, TypeError, ValueError, HostContractError):
        raise LiveSessionError("ACQ_LIVE_HOST_PROFILE_INVALID") from None
    try:
        runtime = profile["runtime"]
        parsed_profile = HostAdapterProfile(
            adapter_id=AdapterId(profile["adapter_id"]),
            configured_backend=profile["configured_backend"],
            tool_bindings=tuple(ToolBinding(
                operation=Operation(row["operation"]),
                observed_tool_identity=row["observed_tool_identity"])
                for row in profile["tool_bindings"]),
            capabilities=frozenset(Capability(value)
                                   for value in profile["capabilities"]),
            runtime=RuntimeProfileRef(
                runtime_identity=runtime["runtime_identity"],
                interpreter_ref=WorkspaceFileRef(**runtime["interpreter_ref"]),
                profile_ref=WorkspaceFileRef(**runtime["profile_ref"]),
            ),
            credential=parsed_credential,
            mcp=None,
        )
        parsed_profile.verify(ROOT)
    except (KeyError, TypeError, ValueError, HostContractError):
        raise LiveSessionError("ACQ_LIVE_HOST_PROFILE_INVALID") from None
    _need(public_credential.get("credential_value_present") is False
          and profile.get("mcp") is None,
          "ACQ_LIVE_HOST_PROFILE_INVALID")
    try:
        operational_credential = CredentialReadinessReceipt.from_public_dict(credential)
    except HostContractError:
        raise LiveSessionError("ACQ_LIVE_CREDENTIAL_READINESS_INVALID") from None
    checked = datetime.fromisoformat(
        operational_credential.checked_at.replace("Z", "+00:00"))
    age_seconds = (datetime.now(timezone.utc) - checked).total_seconds()
    _need(operational_credential.adapter_id.value == expected_adapter
          and operational_credential.owner_ref == parsed_credential.owner_ref
          and operational_credential.profile_ref == parsed_credential.profile_ref
          and operational_credential.profile_fingerprint_sha256
              == parsed_credential.fingerprint_sha256
          and operational_credential.profile_fingerprint_sha256 is not None
          and operational_credential.capability_observed
              == adapter["configured_backend"]
          and operational_credential.status is CredentialReadinessStatus.READY
          and operational_credential.trust_policy
              is OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE
          and -5 <= age_seconds <= 900
          and credential.get("credential_values_present") is False,
          "ACQ_LIVE_CREDENTIAL_READINESS_INVALID")
    return (profile_ref, profile, credential_ref, credential, operational_credential,
            parsed_profile)



def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise LiveSessionError("ACQ_LIVE_HOST_BINDING_INVALID") from error


def _validate_host_binding(spec, *, parsed_profile, identities, budgets, directory, packet):
    binding_ref, binding = _load_workspace_ref(
        spec.get("host_binding_ref"), "ACQ_LIVE_HOST_BINDING_INVALID")
    manifest_ref, manifest = _load_workspace_ref(
        spec.get("host_materialization_manifest_ref"),
        "ACQ_LIVE_MATERIALIZATION_MANIFEST_INVALID")
    required = {"version", "profile", "execution_id", "trace_id",
                "dispatch_namespace", "artifact_root", "cache_root", "budget",
                "binding_sha256"}
    _need(set(binding) == required and binding.get("version") == "host-adapter-contracts-1",
          "ACQ_LIVE_HOST_BINDING_INVALID")
    unsigned = {key: value for key, value in binding.items() if key != "binding_sha256"}
    _need(binding.get("binding_sha256") == hashlib.sha256(_canonical(unsigned)).hexdigest()
          and binding.get("profile") == parsed_profile.to_public_dict()
          and binding.get("execution_id") == identities["execution_id"]
          and binding.get("trace_id") == identities["trace_id"],
          "ACQ_LIVE_HOST_BINDING_INVALID")
    budget = binding.get("budget")
    _need(isinstance(budget, dict) and set(budget) == {
              "search_items", "open_items", "provider_items", "concurrency",
              "call_timeout_seconds", "run_timeout_seconds"}
          and all(type(budget[key]) is int for key in budget)
          and budget["search_items"] == budgets["search_items"]
          and budget["open_items"] == budgets["open_items"]
          and budget["provider_items"] == budgets["provider_items"]
          and budget["concurrency"] == budgets["concurrency"] == 1
          and budget["call_timeout_seconds"] == budgets["provider_call_seconds"]
          and budget["run_timeout_seconds"] == budgets["run_wall_seconds"],
          "ACQ_LIVE_HOST_BINDING_BUDGET_MISMATCH")
    expected_artifact = str((directory / "artifacts").relative_to(ROOT))
    expected_cache = str((directory / "cache").relative_to(ROOT))
    _need(binding.get("artifact_root") == expected_artifact
          and binding.get("cache_root") == expected_cache
          and packet.get("artifacts", {}).get("artifact_root") == str(directory / "artifacts")
          and packet.get("artifacts", {}).get("runtime_root") == str(directory),
          "ACQ_LIVE_HOST_BINDING_ROOT_MISMATCH")
    _need(isinstance(binding.get("dispatch_namespace"), str)
          and _BACKEND.fullmatch(binding["dispatch_namespace"]),
          "ACQ_LIVE_HOST_BINDING_INVALID")
    _need(isinstance(manifest, dict) and set(manifest) == {
              "kind", "version", "mcp", "generation", "generation_sha256",
              "files", "hosts"}
          and manifest.get("kind") == "host_profile_materialization_head"
          and manifest.get("mcp") == "not_used"
          and isinstance(manifest.get("files"), dict),
          "ACQ_LIVE_MATERIALIZATION_MANIFEST_INVALID")
    host = "codex" if spec["host_adapter"] == "codex_native_web" else "claude"
    _need(manifest["files"].get(f"{host}-profile.json")
              == spec["host_profile_ref"]["sha256"]
          and manifest["files"].get(f"{host}-credential-readiness.json")
              == spec["credential_readiness_ref"]["sha256"]
          and manifest["files"].get(f"{host}-binding.json") == binding_ref.sha256
          and manifest.get("hosts", {}).get(host, {}).get("ready_for_live") is True,
          "ACQ_LIVE_MATERIALIZATION_MANIFEST_MISMATCH")
    return binding_ref, binding, manifest_ref, manifest

def _dummy_provider(_arguments, _deadline):
    raise RunnerError("ACQ_LIVE_PROVIDER_MUST_BE_HOSTED")


class LiveAcquisitionSession:
    """Persistent one-case state machine driven by a cooperative hosted tool cell."""

    def __init__(self, directory):
        self.directory = private_path(directory, create=True)
        self.head = self.directory / "session.json"

    def _state(self):
        _need(self.head.is_file() and not self.head.is_symlink()
              and self.head.stat().st_size <= MAX_INPUT, "ACQ_LIVE_STATE_INVALID")
        try:
            state = json.loads(self.head.read_bytes())
        except (OSError, json.JSONDecodeError):
            raise LiveSessionError("ACQ_LIVE_STATE_INVALID") from None
        _need(state.get("version") == VERSION, "ACQ_LIVE_STATE_INVALID")
        return state

    def _write(self, state):
        atomic(self.head, state)

    def _stack(self, state):
        controller = AcquisitionController(self.directory / "controller")
        portal = HostWeb(self.directory / "host")
        driver = AcquisitionDriver(
            self.directory / "driver", controller=controller, portal=portal,
            **state["identities"],
        )
        runner = HostedAcquisitionRunner(
            self.directory / "runner", provider=_dummy_provider,
            configured_backend=state["configured_backend"],
            run_deadline=state["run_deadline_monotonic"], raw_byte_limit=MAX_RAW,
        )
        return controller, portal, driver, runner

    def initialize(self, spec):
        _need(not self.head.exists(), "ACQ_LIVE_ALREADY_INITIALIZED")
        for name in ("artifacts", "controller", "host", "driver", "runner", "cache"):
            path = self.directory / name
            _need(not path.exists(), "ACQ_LIVE_RUNTIME_ROOT_NOT_EMPTY")
        _need(isinstance(spec, dict), "ACQ_LIVE_SPEC_INVALID")
        v2 = spec.get("schema_version") == SESSION_SPEC_V2
        v1_required = {"readiness_envelope", "identities", "question", "model_sha256",
                       "host_adapter", "host_identity", "tool_identity", "proposals",
                       "host_profile_ref", "credential_readiness_ref",
                       "run_wall_seconds", "provider_call_seconds"}
        v2_required = {"schema_version", "readiness_envelope", "identities", "model_sha256",
                       "host_adapter", "host_identity", "tool_identity",
                       "host_profile_ref", "credential_readiness_ref",
                       "host_binding_ref", "host_materialization_manifest_ref",
                       "custody_ref", "run_wall_seconds", "provider_call_seconds"}
        _need(set(spec) == (v2_required if v2 else v1_required),
              "ACQ_LIVE_SPEC_INVALID")
        verdict = load_and_validate(Path(spec["readiness_envelope"]))
        _need(verdict["ready_for_provider_authorization_request"] is True,
              "ACQ_LIVE_READINESS_BLOCKED")
        readiness = _load_json(spec["readiness_envelope"])
        packet = readiness["packet"]
        if v2:
            _need(packet.get("schema_version") == READINESS_V2,
                  "ACQ_LIVE_READINESS_VERSION")
            authority = derive_live_contract(packet)
            run_kind = authority["run_kind"]
            question = authority["question"]
            proposals = authority["proposals"]
            budgets = packet["budgets"]
            _need(spec["run_wall_seconds"] == budgets["run_wall_seconds"]
                  and spec["provider_call_seconds"] == budgets["provider_call_seconds"],
                  "ACQ_LIVE_DEADLINE_MISMATCH")
        else:
            run_kind = "narrow"
            question = spec["question"]
            proposals = spec["proposals"]
            budgets = {"search_items": 1, "open_items": 2, "provider_items": 3,
                       "fallbacks": 1}
        identities = spec["identities"]
        _need(isinstance(identities, dict) and set(identities) == {
            "experiment_id", "execution_id", "trace_id"}, "ACQ_LIVE_IDENTITY_INVALID")
        RunIdentity(**identities)
        try:
            _need(str(uuid.UUID(identities["execution_id"])) == identities["execution_id"],
                  "ACQ_LIVE_EXECUTION_INVALID")
        except ValueError:
            raise LiveSessionError("ACQ_LIVE_EXECUTION_INVALID") from None
        _need(isinstance(spec["host_adapter"], str)
              and spec["host_adapter"] in _HOST_ADAPTERS,
              "ACQ_LIVE_HOST_ADAPTER_UNSUPPORTED")
        adapter = _HOST_ADAPTERS[spec["host_adapter"]]
        _need(isinstance(spec["host_identity"], str)
              and _BACKEND.fullmatch(spec["host_identity"]),
              "ACQ_LIVE_HOST_IDENTITY_INVALID")
        _need(spec["tool_identity"] == adapter["configured_backend"],
              "ACQ_LIVE_TOOL_IDENTITY_MISMATCH")
        (profile_file_ref, profile, credential_file_ref, credential_readiness,
         operational_credential, parsed_profile) = _validate_host_readiness(spec)
        _need(profile["credential"]["source"] == (
                  "codex_profile" if spec["host_adapter"] == "codex_native_web"
                  else "claude_profile"), "ACQ_LIVE_HOST_PROFILE_INVALID")
        _need(spec["host_identity"] == operational_credential.host_session_id,
              "ACQ_LIVE_CREDENTIAL_SESSION_MISMATCH")
        _need(type(spec["run_wall_seconds"]) is int and 1 <= spec["run_wall_seconds"] <= 600
              and type(spec["provider_call_seconds"]) is int
              and 1 <= spec["provider_call_seconds"] <= spec["run_wall_seconds"],
              "ACQ_LIVE_DEADLINE_INVALID")
        if v2:
            (binding_file_ref, host_binding, materialization_manifest_file_ref,
             materialization_manifest) = _validate_host_binding(
                spec, parsed_profile=parsed_profile, identities=identities, budgets=budgets,
                directory=self.directory, packet=packet)
            custody_file_ref, custody = _load_workspace_ref(
                spec.get("custody_ref"), "ACQ_LIVE_CUSTODY_INVALID")
            try:
                custody_verdict = validate_live_session_custody(
                    ROOT, custody, spec=spec, directory=self.directory,
                    root_state="initialize")
            except LiveSessionCustodyError as error:
                raise LiveSessionError(str(error)) from None
        else:
            binding_file_ref = host_binding = materialization_manifest_file_ref = None
            materialization_manifest = None
            custody_file_ref = custody = custody_verdict = None
        question_keys = {"id", "facet", "question", "evidence_to_seek", "source_roles",
                         "capability_ids", "depends_on", "priority", "stop_rule"}
        _need(isinstance(question, dict) and set(question) == question_keys,
              "ACQ_LIVE_QUESTION_INVALID")
        expected_proposals = 1 if run_kind == "smoke" else 2
        _need(isinstance(proposals, list) and len(proposals) == expected_proposals
              and all(isinstance(row, dict) for row in proposals)
              and "search_query" in proposals[0].get("arguments", {}),
              "ACQ_LIVE_PROPOSALS_INVALID")
        if run_kind == "narrow":
            _need("open" in proposals[1].get("arguments", {}),
                  "ACQ_LIVE_PROPOSALS_INVALID")

        artifacts = private_path(self.directory / "artifacts", create=True)
        readiness_ref = save(artifacts, readiness)
        sealed_host_profile_ref = save(artifacts, {
            "kind": "acquisition_host_profile", "workspace_ref": {
                "path": profile_file_ref.path, "sha256": profile_file_ref.sha256},
            "profile": profile,
        })
        sealed_credential_readiness_ref = save(artifacts, {
            "kind": "acquisition_credential_readiness", "workspace_ref": {
                "path": credential_file_ref.path, "sha256": credential_file_ref.sha256},
            "receipt": credential_readiness,
        })
        sealed_host_binding_ref = (save(artifacts, {
            "kind": "acquisition_host_binding", "workspace_ref": {
                "path": binding_file_ref.path, "sha256": binding_file_ref.sha256},
            "binding": host_binding,
        }) if v2 else None)
        sealed_materialization_manifest_ref = (save(artifacts, {
            "kind": "acquisition_host_materialization_manifest", "workspace_ref": {
                "path": materialization_manifest_file_ref.path,
                "sha256": materialization_manifest_file_ref.sha256},
            "manifest": materialization_manifest,
        }) if v2 else None)
        sealed_custody_ref = (save(artifacts, {
            "kind": "acquisition_live_session_custody", "workspace_ref": {
                "path": custody_file_ref.path, "sha256": custody_file_ref.sha256},
            "custody": custody,
        }) if v2 else None)
        sealed_session_spec_ref = save(artifacts, spec)
        context_ref = save(artifacts, {"kind": "live_readiness_context",
                                      "readiness_ref": readiness_ref,
                                      "host_profile_ref": sealed_host_profile_ref,
                                      "credential_readiness_ref": sealed_credential_readiness_ref,
                                      "host_binding_ref": sealed_host_binding_ref,
                                      "host_materialization_manifest_ref": sealed_materialization_manifest_ref,
                                      "custody_ref": sealed_custody_ref})
        plan_ref = save(artifacts, {
            "scope": "retrieval_plan_only", "context_ref": context_ref,
            "proposal": {"questions": [question]},
        })
        manifest_ref = compile_prefetch_manifest(
            plan_ref, artifacts, search_items=budgets["search_items"],
            open_items=budgets["open_items"], provider_items=budgets["provider_items"],
            reserve_provider_items=0)
        controller = AcquisitionController(self.directory / "controller",
                                           manifest_ref=manifest_ref)
        host_config = freeze_config({
            "schema_version": 1, "execution_id": identities["execution_id"],
            "arm": "A", "question": question["question"], "baseline_ref": context_ref,
            "cutoff": packet["source_contract"]["cutoff"],
            "model_sha256": spec["model_sha256"], "backend": spec["tool_identity"],
            "cohort": "cold", "cache_enabled": False, "cache_max_age_seconds": 0,
            "max_fallbacks": budgets["fallbacks"], "requirement_ids": [question["id"]],
            "budget": {"search_items": budgets["search_items"],
                       "open_items": budgets["open_items"],
                       "provider_items": budgets["provider_items"],
                       "wall_seconds": spec["run_wall_seconds"]},
        })
        portal = HostWeb(self.directory / "host", config=host_config,
                         cache_directory=self.directory / "cache")
        AcquisitionDriver(self.directory / "driver", controller=controller, portal=portal,
                          **identities)
        HostedAcquisitionRunner(
            self.directory / "runner", provider=_dummy_provider,
            configured_backend=spec["tool_identity"],
            run_deadline=time.monotonic() + spec["run_wall_seconds"], raw_byte_limit=MAX_RAW)
        proposal_refs = [save(artifacts, {"kind": "acquisition_proposal", **row})
                         for row in proposals]
        state = {
            "version": VERSION, "session_spec_version": SESSION_SPEC_V2 if v2 else "legacy-v1",
            "compatibility_only": not v2,
            "run_kind": run_kind, "readiness_packet_sha256": verdict["packet_sha256"],
            "sealed_primary_pdf_url": packet["case"]["primary_pdf_url"],
            "sealed_alternate_html_url": packet["case"]["alternate_html_url"],
            "identities": identities, "host_adapter": spec["host_adapter"],
            "host_identity": spec["host_identity"], "tool_identity": spec["tool_identity"],
            "configured_backend": spec["tool_identity"],
            "host_profile_ref": sealed_host_profile_ref,
            "credential_readiness_ref": sealed_credential_readiness_ref,
            "host_binding_ref": sealed_host_binding_ref,
            "host_materialization_manifest_ref": sealed_materialization_manifest_ref,
            "custody_ref": sealed_custody_ref,
            "custody_workspace_ref": ({"path": custody_file_ref.path,
                                       "sha256": custody_file_ref.sha256} if v2 else None),
            "custody_sha256": (custody_verdict["custody_sha256"] if v2 else None),
            "source_closure_sha256": (custody_verdict["source_closure_sha256"] if v2 else None),
            "session_spec_ref": sealed_session_spec_ref,
            "dispatch_namespace": (host_binding["dispatch_namespace"] if v2 else None),
            "credential_live_eligible": operational_credential.live_acceptance_eligible,
            "trust_policy": OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value,
            "provider_call_seconds": spec["provider_call_seconds"],
            "run_deadline_monotonic": time.monotonic() + spec["run_wall_seconds"],
            "queue": proposals, "proposal_refs": proposal_refs, "active": None,
            "dispatch_refs": [], "host_invocation_refs": [], "review_refs": [],
            "phase": "ready", "final_ref": None,
        }
        self._write(state)
        return {"status": "ready", "run_kind": run_kind,
                "readiness_packet_sha256": verdict["packet_sha256"],
                "host_profile_sha256": sealed_host_profile_ref["sha256"],
                "credential_readiness_sha256": sealed_credential_readiness_ref["sha256"],
                "host_binding_sha256": (sealed_host_binding_ref or {}).get("sha256"),
                "materialization_manifest_sha256": (sealed_materialization_manifest_ref or {}).get("sha256"),
                "credential_live_eligible": bool(v2 and operational_credential.live_acceptance_eligible),
                "compatibility_only": not v2,
                "trust_policy": OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value,
                "cryptographic_remote_attestation": False,
                "mcp_status": "not_used", "structural_evidence_only": True}

    def _revalidate_custody(self, state):
        if state.get("compatibility_only"):
            return None
        spec = read(state["session_spec_ref"])
        try:
            _ref, custody = _load_workspace_ref(
                state["custody_workspace_ref"], "ACQ_LIVE_CUSTODY_INVALID")
            verdict = validate_live_session_custody(
                ROOT, custody, spec=spec, directory=self.directory,
                root_state="active")
        except LiveSessionCustodyError as error:
            raise LiveSessionError(str(error)) from None
        _need(verdict["custody_sha256"] == state["custody_sha256"]
              and verdict["source_closure_sha256"] == state["source_closure_sha256"],
              "ACQ_LIVE_CUSTODY_DRIFT")
        return verdict

    @staticmethod
    def _identity(state, operation_id, dispatch_id):
        return AcquisitionIdentity(
            RunIdentity(**state["identities"]),
            DispatchIdentity(operation_id, f"{operation_id}:1", dispatch_id),
        )

    def next_dispatch(self):
        state = self._state()
        self._revalidate_custody(state)
        _need(state["final_ref"] is None, "ACQ_LIVE_FINISHED")
        _need(state["active"] is None, "ACQ_LIVE_CAPTURE_REQUIRED")
        _need(state["phase"] in {"ready", "dispatch"}, "ACQ_LIVE_ACTION_REQUIRED")
        _need(time.monotonic() < state["run_deadline_monotonic"],
              "ACQ_LIVE_RUN_DEADLINE")
        _controller, _portal, driver, runner = self._stack(state)
        _need(bool(state["queue"]), "ACQ_LIVE_NO_DISPATCH")
        item = state["queue"].pop(0)
        if item.get("controller_dispatch"):
            operation_id = item["controller_dispatch"]["operation_id"]
        else:
            operation_id = item["operation_id"]
            driver.reserve(item)
        prepared = driver.prepare_host(operation_id)
        _need(prepared.get("dispatch") is True, "ACQ_LIVE_HOST_DISPATCH_BLOCKED")
        arguments = driver.claim_dispatch(operation_id)
        dispatch_id = f"{state['identities']['execution_id'][:8]}-{operation_id}-1"
        identity = self._identity(state, operation_id, dispatch_id)
        exact = ExactArguments.from_mapping(arguments)
        absolute_deadline = min(time.monotonic() + state["provider_call_seconds"],
                                state["run_deadline_monotonic"])
        ticket = runner.begin_external_invocation(
            identity, exact, absolute_deadline=absolute_deadline)
        _need(ticket["arguments"] == exact.canonical_json,
              "ACQ_LIVE_ARGUMENT_MISMATCH")
        driver.record_invocation_started(operation_id)
        if state["host_adapter"] == "claude_code_web":
            claude_call = prepare_claude_code_call(identity, arguments).spec.public_call()
            host_tool = claude_call["configured_backend"]
            tool_input = claude_call["tool_input"]
            tool_input_sha256 = claude_call["tool_input_sha256"]
            representation_scope = claude_call["representation_scope"]
            limitations = claude_call["limitations"]
        else:
            host_tool = _HOST_ADAPTERS[state["host_adapter"]][
                "search_tool" if "search_query" in arguments else "open_tool"]
            tool_input = arguments
            tool_input_sha256 = exact.sha256
            representation_scope = ("current_search_metadata_only"
                                    if "search_query" in arguments else "native_open_passage")
            limitations = ["Native host output is not publisher-original byte attestation."]
        state["active"] = {
            "operation_id": operation_id, "dispatch_id": dispatch_id,
            "arguments": arguments, "arguments_sha256": exact.sha256,
            "host_tool": host_tool, "tool_input": tool_input,
            "tool_input_sha256": tool_input_sha256,
            "representation_scope": representation_scope,
            "absolute_deadline": ticket["absolute_deadline"],
        }
        state["phase"] = "await_capture"
        self._write(state)
        return {"status": "dispatch", "operation_id": operation_id,
                "dispatch_id": dispatch_id, "arguments": arguments,
                "arguments_sha256": exact.sha256,
                "host_adapter": state["host_adapter"],
                "host_identity": state["host_identity"],
                "configured_backend": state["configured_backend"],
                "tool_identity": host_tool, "tool_input": tool_input,
                "tool_input_sha256": tool_input_sha256,
                "representation_scope": representation_scope,
                "limitations": limitations, "raw_result_limit_bytes": MAX_RAW,
                "instruction": "Invoke the exact host tool input once, then capture the exact JSON result privately."}

    def capture(self, payload, raw_path):
        state = self._state()
        self._revalidate_custody(state)
        _need(state["phase"] == "await_capture" and state["active"] is not None,
              "ACQ_LIVE_CAPTURE_STATE")
        receipt_key = ("host_invocation_receipt_ref"
                       if state.get("session_spec_version") == SESSION_SPEC_V2
                       else "host_invocation_receipt")
        required_identity = {"host_adapter", "host_identity", "tool_identity", receipt_key}
        allowed = {"status", "code", "diagnostic", "documents", "observed_backend",
                   "actual_tool_input", "captured_at", *required_identity}
        _need(isinstance(payload, dict) and required_identity <= set(payload) <= allowed
              and payload.get("status") in {"returned", "failed", "unknown"},
              "ACQ_LIVE_CAPTURE_INVALID")
        active = state["active"]
        now = time.monotonic()
        if now > active["absolute_deadline"] or now > state["run_deadline_monotonic"]:
            _controller, _portal, driver, runner = self._stack(state)
            runner.fence_external_unknown(active["dispatch_id"], "HOST_WEB_DEADLINE")
            driver.record_possibly_dispatched(active["operation_id"])
            state["active"] = None
            state["phase"] = "blocked_unknown"
            self._write(state)
            raise LiveSessionError("ACQ_LIVE_CAPTURE_DEADLINE")
        _need(payload["host_adapter"] == state["host_adapter"]
              and payload["host_identity"] == state["host_identity"]
              and payload["tool_identity"] == active["host_tool"],
              "ACQ_LIVE_HOST_IDENTITY_MISMATCH")
        raw_path = private_path(raw_path)
        _need(raw_path.is_file() and not raw_path.is_symlink()
              and raw_path.stat().st_size <= MAX_RAW, "ACQ_LIVE_RAW_INVALID")
        raw_bytes = raw_path.read_bytes()
        try:
            raw_value = json.loads(raw_bytes)
        except json.JSONDecodeError:
            raise LiveSessionError("ACQ_LIVE_RAW_INVALID") from None
        receipt_workspace_ref = None
        try:
            if receipt_key == "host_invocation_receipt_ref":
                receipt_workspace_ref, receipt_value = _load_workspace_ref(
                    payload[receipt_key], "ACQ_LIVE_OPERATIONAL_RECEIPT_INVALID")
            else:
                receipt_value = payload[receipt_key]
            operational_receipt = HostInvocationReceipt.from_public_dict(receipt_value)
        except HostContractError:
            raise LiveSessionError("ACQ_LIVE_OPERATIONAL_RECEIPT_INVALID") from None
        if state.get("compatibility_only"):
            _need(operational_receipt.source is OperationalEvidenceSource.SYNTHETIC,
                  "ACQ_LIVE_V1_OPERATIONAL_EVIDENCE_FORBIDDEN")
        expected_adapter = (AdapterId.CODEX_NATIVE_WEB
                            if state["host_adapter"] == "codex_native_web"
                            else AdapterId.CLAUDE_CODE_WEB)
        expected_terminal = {
            "returned": OperationalTerminalStatus.CAPTURED,
            "failed": OperationalTerminalStatus.FAILED,
            "unknown": OperationalTerminalStatus.UNKNOWN,
        }[payload["status"]]
        _need(operational_receipt.adapter_id is expected_adapter
              and operational_receipt.configured_backend == state["configured_backend"]
              and operational_receipt.observed_tool_identity == active["host_tool"]
              and operational_receipt.host_session_id == state["host_identity"]
              and operational_receipt.dispatch_id == active["dispatch_id"]
              and operational_receipt.acquisition_arguments_sha256
                  == active["arguments_sha256"]
              and operational_receipt.tool_input_sha256
                  == active["tool_input_sha256"]
              and operational_receipt.result_sha256
                  == hashlib.sha256(raw_bytes).hexdigest()
              and operational_receipt.terminal_status is expected_terminal
              and operational_receipt.terminal_code
                  == (payload.get("code") if payload["status"] != "returned" else None)
              and operational_receipt.trust_policy
                  is OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
              "ACQ_LIVE_OPERATIONAL_RECEIPT_MISMATCH")
        operational_ref = save(self.directory / "artifacts", {
            "kind": "acquisition_host_invocation_receipt",
            "workspace_ref": (None if receipt_workspace_ref is None else {
                "path": receipt_workspace_ref.path, "sha256": receipt_workspace_ref.sha256}),
            "receipt": operational_receipt.to_public_dict(),
        })
        state["host_invocation_refs"].append(operational_ref)
        identity = self._identity(state, active["operation_id"], active["dispatch_id"])
        if state["host_adapter"] == "claude_code_web":
            _need("actual_tool_input" in payload and "captured_at" in payload,
                  "ACQ_LIVE_CAPTURE_INVALID")
            try:
                claude_capture = prepare_claude_code_call(identity, active["arguments"]).capture(
                    dispatch_id=active["dispatch_id"],
                    observed_tool=payload["tool_identity"],
                    actual_tool_input=payload["actual_tool_input"],
                    raw_result_json=raw_bytes,
                    captured_at=payload["captured_at"],
                    raw_byte_limit=MAX_RAW,
                )
            except ValueError as error:
                code = str(error) if re.fullmatch(r"ACQ_[A-Z0-9_]+", str(error)) else "ACQ_LIVE_CAPTURE_INVALID"
                raise LiveSessionError(code) from None
            observed_backend = claude_capture.provider_response().observed_backend
        else:
            observed_backend = payload.get("observed_backend")
            _need(payload["status"] == "unknown" and observed_backend is None
                  or observed_backend == active["host_tool"],
                  "ACQ_LIVE_HOST_IDENTITY_MISMATCH")
        _controller, _portal, driver, runner = self._stack(state)
        dispatch_ref = None
        if payload["status"] == "unknown":
            runner.fence_external_unknown(
                active["dispatch_id"], payload.get("code") or "HOST_WEB_RESULT_UNKNOWN")
            driver.record_possibly_dispatched(active["operation_id"])
        else:
            receipt = runner.capture_external_result(
                active["dispatch_id"], raw_bytes, observed_backend=observed_backend)
            dispatch_ref = receipt["dispatch_ref"]
            state["dispatch_refs"].append(dispatch_ref)
        capture = {
            "actual_arguments": active["arguments"],
            "raw_result": raw_value,
            "status": payload["status"],
        }
        for key in ("code", "diagnostic", "documents"):
            if key in payload:
                capture[key] = payload[key]
        result = driver.capture_host(
            active["operation_id"], capture, runner=runner,
            dispatch_id=active["dispatch_id"], dispatch_ref=dispatch_ref,
        )
        operation_id = active["operation_id"]
        state["active"] = None
        is_search = "search_query" in active["arguments"]
        if payload["status"] == "returned" and is_search:
            driver.commit_controller(operation_id)
            if state["run_kind"] == "smoke":
                _need(not state["queue"], "ACQ_LIVE_SMOKE_EXTRA_OPERATION")
                state["phase"] = "ready_to_finalize_smoke"
                self._write(state)
                return {"status": "callable", "code": None,
                        "operation_id": operation_id, "next": state["phase"],
                        "operational_receipt_sha256": operational_ref["sha256"],
                        "live_acceptance_eligible": operational_receipt.live_acceptance_eligible,
                        "cryptographic_remote_attestation": False}
            observed_urls = set(result.get("packet", {}).get("urls", []))
            sealed_urls = {state["sealed_primary_pdf_url"],
                           state["sealed_alternate_html_url"]}
            if not sealed_urls.issubset(observed_urls):
                state["queue"] = []
                state["phase"] = "blocked_inconclusive"
                self._write(state)
                return {"status": "inconclusive", "code": "ACQ_LIVE_SEARCH_PAIR_MISSING",
                        "operation_id": operation_id, "next": state["phase"],
                        "operational_receipt_sha256": operational_ref["sha256"],
                        "live_acceptance_eligible": False,
                        "cryptographic_remote_attestation": False}
            state["phase"] = "dispatch"
            self._write(state)
            return {"status": "returned", "code": None,
                    "operation_id": operation_id, "next": state["phase"],
                    "operational_receipt_sha256": operational_ref["sha256"],
                    "live_acceptance_eligible": operational_receipt.live_acceptance_eligible,
                    "cryptographic_remote_attestation": False}
        if payload["status"] == "unknown":
            driver.commit_controller(operation_id)
            state["phase"] = "blocked_unknown"
        elif is_search and result["status"] != "returned":
            driver.commit_controller(operation_id)
            state["queue"] = []
            state["phase"] = "blocked"
        elif result["status"] == "returned" and result.get("packet", {}).get("documents"):
            state["phase"] = "await_assessment"
        else:
            committed = driver.commit_controller(operation_id)
            recovery = committed.get("next_dispatch")
            if recovery:
                recovery_ref = save(self.directory / "artifacts", {
                    "kind": "acquisition_proposal", "operation_id": recovery["operation_id"],
                    "question_ids": recovery["requirement_ids"],
                    "arguments": recovery["arguments"],
                })
                state["proposal_refs"].append(recovery_ref)
                state["queue"].insert(0, {"controller_dispatch": recovery})
            state["phase"] = "dispatch" if state["queue"] else "blocked"
        self._write(state)
        public = {"status": result["status"], "code": result.get("code"),
                  "operation_id": operation_id, "next": state["phase"],
                  "operational_receipt_sha256": operational_ref["sha256"],
                  "live_acceptance_eligible": operational_receipt.live_acceptance_eligible,
                  "cryptographic_remote_attestation": False}
        if state["phase"] == "await_assessment":
            public["screened_packet"] = {
                "documents": [{
                    "url": row.get("url"),
                    "text": row.get("text"),
                } for row in result["packet"].get("documents", [])]
            }
        return public

    def assess(self, payload):
        state = self._state()
        self._revalidate_custody(state)
        _need(state["phase"] == "await_assessment", "ACQ_LIVE_ASSESS_STATE")
        _need(isinstance(payload, dict) and set(payload) == {
            "operation_id", "assessor_version", "assessments"},
            "ACQ_LIVE_ASSESS_INVALID")
        _controller, _portal, driver, _runner = self._stack(state)
        driver.commit_controller(payload["operation_id"], payload["assessments"])
        assessments = driver.save_assessments(
            payload["operation_id"], assessor_version=payload["assessor_version"])
        units = driver.attach_units(payload["operation_id"])
        _need(len(assessments) == len(units) == 1, "ACQ_LIVE_ASSESS_INVALID")
        state["phase"] = "await_review"
        state["assessed_operation_id"] = payload["operation_id"]
        self._write(state)
        return {"status": "await_review",
                "assessment_sha256": assessments[0]["sha256"],
                "unit_sha256": units[0]["sha256"]}

    def review(self, payload):
        state = self._state()
        self._revalidate_custody(state)
        _need(state["phase"] == "await_review", "ACQ_LIVE_REVIEW_STATE")
        reviewer_key = ("reviewer_session_receipt_ref"
                        if state.get("session_spec_version") == SESSION_SPEC_V2
                        else "reviewer_session_receipt")
        required = {"reviewer_id", "assessment_author_id", "live_operator_id",
                    "disposition", "checks", "reason", reviewer_key, "trust_policy"}
        _need(isinstance(payload, dict) and set(payload) == required,
              "ACQ_LIVE_REVIEW_INVALID")
        reviewer_workspace_ref = None
        try:
            if reviewer_key == "reviewer_session_receipt_ref":
                reviewer_workspace_ref, reviewer_value = _load_workspace_ref(
                    payload[reviewer_key], "ACQ_LIVE_REVIEWER_RECEIPT_INVALID")
            else:
                reviewer_value = payload[reviewer_key]
            reviewer_receipt = ReviewerSessionReceipt.from_public_dict(reviewer_value)
        except HostContractError:
            raise LiveSessionError("ACQ_LIVE_REVIEWER_RECEIPT_INVALID") from None
        if state.get("compatibility_only"):
            _need(reviewer_receipt.source is OperationalEvidenceSource.SYNTHETIC,
                  "ACQ_LIVE_V1_OPERATIONAL_EVIDENCE_FORBIDDEN")
        expected_adapter = (AdapterId.CODEX_NATIVE_WEB
                            if state["host_adapter"] == "codex_native_web"
                            else AdapterId.CLAUDE_CODE_WEB)
        _need(payload["trust_policy"]
                  == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
              and reviewer_receipt.adapter_id is expected_adapter
              and reviewer_receipt.host_session_id != state["host_identity"]
              and reviewer_receipt.principal_ref == payload["reviewer_id"]
              and reviewer_receipt.principal_ref
                  not in {payload["assessment_author_id"], payload["live_operator_id"]},
              "ACQ_LIVE_REVIEWER_RECEIPT_MISMATCH")
        _controller, _portal, driver, _runner = self._stack(state)
        driver_state = read(driver._head())
        operation = driver_state["operations"].get(state["assessed_operation_id"])
        _need(operation is not None
              and len(operation.get("assessment_refs", [])) == 1
              and len(operation.get("unit_refs", [])) == 1,
              "ACQ_LIVE_REVIEW_STATE")
        ref = record_reviewer_decision(
            self.directory / "driver",
            assessment_ref=operation["assessment_refs"][0],
            unit_ref=operation["unit_refs"][0],
            reviewer_id=payload["reviewer_id"],
            assessment_author_id=payload["assessment_author_id"],
            operator_id=payload["live_operator_id"],
            disposition=payload["disposition"], checks=payload["checks"],
            reason=payload["reason"],
            reviewer_session_receipt=reviewer_receipt.to_public_dict(),
            reviewer_session_receipt_ref=(None if reviewer_workspace_ref is None else {
                "path": reviewer_workspace_ref.path,
                "sha256": reviewer_workspace_ref.sha256}),
            trust_policy=payload["trust_policy"],
        )
        driver.import_reviews(state["assessed_operation_id"], [ref])
        state["review_refs"].append(ref)
        state["phase"] = "ready_to_finalize"
        self._write(state)
        return {"status": "ready_to_finalize", "review_sha256": ref["sha256"],
                "review_live_eligible": reviewer_receipt.live_acceptance_eligible}

    @staticmethod
    def _public_final(result, final_ref):
        verdict = result["checker_verdict"]
        return {"status": "callable" if result.get("run_kind") == "smoke" else "passed",
                "run_kind": result.get("run_kind", "narrow"),
                "experiment_id": result["experiment_id"],
                "execution_id": result["execution_id"], "trace_id": result["trace_id"],
                "host_adapter": result["host_adapter"],
                "host_identity": result["host_identity"],
                "configured_backend": result["configured_backend"],
                "observed_tool_identities": result["observed_tool_identities"],
                "host_profile_sha256": result["host_profile_ref"]["sha256"],
                "credential_readiness_sha256": result["credential_readiness_ref"]["sha256"],
                "host_binding_sha256": (result.get("host_binding_ref") or {}).get("sha256"),
                "materialization_manifest_sha256": (result.get("host_materialization_manifest_ref") or {}).get("sha256"),
                "mcp_status": result["mcp_status"],
                "trust_policy": result["trust_policy"],
                "live_acceptance_eligible": result["live_acceptance_eligible"],
                "cryptographic_remote_attestation": False,
                "checker_status": verdict["status"],
                "complete_chains": verdict["complete_chains"],
                "credited_units": verdict["credited_units"],
                "verdict_sha256": verdict["verdict_sha256"],
                "result_sha256": final_ref["sha256"],
                "scope": result["scope"]}

    def finalize(self):
        state = self._state()
        self._revalidate_custody(state)
        if state["final_ref"]:
            result = read(state["final_ref"])
            if state.get("terminal_custody_ref"):
                terminal = read(state["terminal_custody_ref"])
                try:
                    validate_terminal_custody(terminal)
                except LiveSessionCustodyError as error:
                    raise LiveSessionError(str(error)) from None
                _need(terminal["result_ref"] == state["final_ref"],
                      "ACQ_LIVE_TERMINAL_CUSTODY_INVALID")
            return self._public_final(result, state["final_ref"])
        smoke = state.get("run_kind") == "smoke"
        required_phase = "ready_to_finalize_smoke" if smoke else "ready_to_finalize"
        _need(state["phase"] == required_phase and state["active"] is None
              and not state["queue"], "ACQ_LIVE_FINALIZE_STATE")
        _controller, _portal, driver, _runner = self._stack(state)
        final = driver.finish()
        expected = 1 if smoke else 3
        reconciliation = reconcile_terminal_ledgers(
            self.directory / "artifacts", driver_ref=final["final_ref"],
            dispatch_refs=state["dispatch_refs"],
            host_invocation_refs=state["host_invocation_refs"],
            review_refs=state["review_refs"], expected_dispatches=expected,
            trust_policy=state["trust_policy"],
            host_session_id=state["host_identity"], host_adapter=state["host_adapter"])
        common = {
            "driver_ref": final["final_ref"], "dispatch_refs": state["dispatch_refs"],
            "host_invocation_refs": state["host_invocation_refs"],
            "proposal_refs": state["proposal_refs"],
            "reconciliation_ref": reconciliation["reconciliation_ref"],
            "host_profile_ref": state["host_profile_ref"],
            "credential_readiness_ref": state["credential_readiness_ref"],
            "trust_policy": state["trust_policy"],
            "host_session_id": state["host_identity"], "host_adapter": state["host_adapter"],
        }
        if smoke:
            verdict = check_acquisition_smoke_trace(**common)
            _need(reconciliation["reconciliation"]["status"] == "pass"
                  and verdict["status"] == "pass"
                  and verdict["actual_dispatches"] == 1
                  and verdict["complete_chains"] == verdict["credited_units"] == 0,
                  "ACQ_LIVE_SMOKE_CHECKER_FAILED")
        else:
            verdict = check_acquisition_trace(
                review_refs=state["review_refs"], expected_dispatches=3, **common)
            _need(reconciliation["reconciliation"]["status"] == "pass"
                  and verdict["status"] == "pass"
                  and verdict["complete_chains"] == verdict["credited_units"] == 1,
                  "ACQ_LIVE_CHECKER_FAILED")
        observed_tools = sorted({read(ref).get("observed_backend")
                                 for ref in state["dispatch_refs"]
                                 if read(ref).get("observed_backend")})
        result = {"kind": "acquisition_live_session_result", "version": VERSION,
                  "run_kind": state["run_kind"],
                  "session_spec_version": state["session_spec_version"],
                  "compatibility_only": state["compatibility_only"],
                  **state["identities"],
                  "host_adapter": state["host_adapter"],
                  "host_identity": state["host_identity"],
                  "configured_backend": state["configured_backend"],
                  "observed_tool_identities": observed_tools,
                  "host_profile_ref": state["host_profile_ref"],
                  "credential_readiness_ref": state["credential_readiness_ref"],
                  "host_binding_ref": state.get("host_binding_ref"),
                  "host_materialization_manifest_ref": state.get("host_materialization_manifest_ref"),
                  "custody_ref": state.get("custody_ref"),
                  "custody_sha256": state.get("custody_sha256"),
                  "source_closure_sha256": state.get("source_closure_sha256"),
                  "readiness_packet_sha256": state.get("readiness_packet_sha256"),
                  "dispatch_namespace": state.get("dispatch_namespace"),
                  "mcp_status": "not_used", "driver_ref": final["final_ref"],
                  "reconciliation_ref": reconciliation["reconciliation_ref"],
                  "checker_verdict": verdict, "dispatch_refs": state["dispatch_refs"],
                  "host_invocation_refs": state["host_invocation_refs"],
                  "review_refs": state["review_refs"], "trust_policy": state["trust_policy"],
                  "live_acceptance_eligible": bool(
                      not state.get("compatibility_only")
                      and reconciliation["reconciliation"].get("live_acceptance_eligible")
                      and verdict.get("live_acceptance_eligible")
                      and state.get("credential_live_eligible")),
                  "cryptographic_remote_attestation": False,
                  "scope": ("live_callability_only_not_full_e2e_or_quality" if smoke else
                            "live_structural_integration_not_quality_improvement_or_alpha")}
        state["final_ref"] = save(self.directory / "artifacts", result)
        if not state.get("compatibility_only"):
            checker_ref = verdict.get("verdict_ref") or state["final_ref"]
            terminal = build_terminal_custody(
                custody_ref=state["custody_ref"], custody_sha256=state["custody_sha256"],
                readiness_packet_sha256=state["readiness_packet_sha256"],
                dispatch_namespace=state["dispatch_namespace"], checker_ref=checker_ref,
                reconciliation_ref=reconciliation["reconciliation_ref"],
                result_ref=state["final_ref"])
            state["terminal_custody_ref"] = save(self.directory / "artifacts", terminal)
        state["phase"] = "finalized"
        self._write(state)
        return self._public_final(result, state["final_ref"])

    def status(self):
        state = self._state()
        self._revalidate_custody(state)
        final_result = None
        terminal = None
        if state.get("final_ref"):
            final_result = read(state["final_ref"])
            if not state.get("compatibility_only"):
                _need(state.get("terminal_custody_ref") is not None,
                      "ACQ_LIVE_TERMINAL_CUSTODY_INVALID")
                terminal = read(state["terminal_custody_ref"])
                try:
                    validate_terminal_custody(terminal)
                except LiveSessionCustodyError as error:
                    raise LiveSessionError(str(error)) from None
                _need(terminal["result_ref"] == state["final_ref"],
                      "ACQ_LIVE_TERMINAL_CUSTODY_INVALID")
        evidence = final_result or state
        return {"version": VERSION, "phase": state["phase"],
                "run_kind": state.get("run_kind", "narrow"),
                "session_spec_version": state.get("session_spec_version", "legacy-v1"),
                "compatibility_only": state.get("compatibility_only", True),
                "host_adapter": state["host_adapter"],
                "host_identity": state["host_identity"],
                "configured_backend": state["configured_backend"],
                "host_profile_sha256": state["host_profile_ref"]["sha256"],
                "credential_readiness_sha256": state["credential_readiness_ref"]["sha256"],
                "host_binding_sha256": (evidence.get("host_binding_ref") or {}).get("sha256"),
                "materialization_manifest_sha256": (evidence.get("host_materialization_manifest_ref") or {}).get("sha256"),
                "custody_sha256": evidence.get("custody_sha256"),
                "source_closure_sha256": evidence.get("source_closure_sha256"),
                "readiness_packet_sha256": evidence.get("readiness_packet_sha256"),
                "dispatch_namespace": evidence.get("dispatch_namespace"),
                "terminal_custody_sha256": ((state.get("terminal_custody_ref") or {}).get("sha256")),
                "trust_policy": state["trust_policy"],
                "credential_live_eligible": state["credential_live_eligible"],
                "cryptographic_remote_attestation": False,
                "mcp_status": "not_used",
                "active_tool_identity": state["active"]["host_tool"] if state["active"] else None,
                "active_operation_id": state["active"]["operation_id"] if state["active"] else None,
                "dispatches_captured": len(state["dispatch_refs"]),
                "operational_receipts": len(state["host_invocation_refs"]),
                "finalized": state["final_ref"] is not None,
                "scope": "structural_status_no_raw_provider_output"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "next", "capture", "assess", "review", "finalize", "status"])
    parser.add_argument("--directory", required=True)
    parser.add_argument("--input-file")
    parser.add_argument("--raw-result-file")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        session = LiveAcquisitionSession(args.directory)
        payload = _load_json(args.input_file) if args.input_file else {}
        if args.command == "init":
            result = session.initialize(payload)
        elif args.command == "next":
            result = session.next_dispatch()
        elif args.command == "capture":
            _need(args.raw_result_file is not None, "ACQ_LIVE_RAW_REQUIRED")
            result = session.capture(payload, args.raw_result_file)
        elif args.command == "assess":
            result = session.assess(payload)
        elif args.command == "review":
            result = session.review(payload)
        elif args.command == "finalize":
            result = session.finalize()
        else:
            result = session.status()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception as error:
        code = str(error) if isinstance(error, (LiveSessionError, SourceError, RunnerError)) \
            and re.fullmatch(r"[A-Z][A-Z0-9_]{2,99}", str(error)) else "ACQ_LIVE_FAILED"
        print(json.dumps({"status": "failed", "code": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
