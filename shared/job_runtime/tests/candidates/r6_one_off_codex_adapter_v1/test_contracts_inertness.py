from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from shared.job_runtime.candidates.r6_one_off_codex_adapter_v1 import (
    FakeCodexBoundary, execute_stage_a, stage_a_template,
)
from shared.job_runtime.candidates.r6_one_off_codex_adapter_v1.contracts import (
    ARCHIVE_BYTES, ARCHIVE_PATH, ARCHIVE_SHA256, BINARY_BYTES, BINARY_REALPATH,
    BINARY_SHA256, CANONICAL_ARGV, CATALOG_PARSER_ID,
    CATALOG_PARSER_SOURCE_SHA256, CUTOFF_SHA256, ContractError, EFFECTS, EFFORT,
    FROZEN_REFS, LIMITS, MODEL, OFFICIAL_ASSET, OTHER_AUTHORITY_BYTES, OTHER_AUTHORITY_PATH, OTHER_AUTHORITY_SHA256, PROMPT_BYTES, PROMPT_SHA256,
    PROVIDER, RELEASE, artifact_ref, canonical_bytes, sha256_bytes,
    validate_stage_b_seal,
)

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "shared/job_runtime/candidates/r6_one_off_codex_adapter_v1"
FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_codex_adapter_v1"
ARCH = ROOT / "tuning/architecture/r6_one_off_codex_adapter_v1"


def ref(path):
    return artifact_ref(path, ROOT)


def write_ref(base, name, value):
    path = base / name
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return artifact_ref(path.relative_to(ROOT).as_posix(), ROOT)


class ContractInertnessTests(unittest.TestCase):
    def test_frozen_design_review_engine_and_shared_closure(self):
        for name in ("design", "design_review", "engine", "shared_source_closure"):
            path, size, digest = FROZEN_REFS[name]
            raw = (ROOT / path).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (size, digest))

    def test_imports_blocked_package_removal_and_effect_modules_absent(self):
        blocked = "codex_" + "live_evidence_r6_" + "live_v1"
        forbidden = {"socket", "subprocess", "urllib", "http", "smtplib"}
        for root in (SRC, ARCH):
            for path in root.glob("*.py"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(blocked, text, path)
                tree = ast.parse(text, filename=str(path))
                imports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split(".")[0])
                self.assertTrue(imports.isdisjoint(forbidden), (path, imports & forbidden))
        runtime = ROOT / "shared/job_runtime"
        self.assertFalse(any("r6_one_off_codex_adapter_v1" in path.read_text(encoding="utf-8") for path in runtime.glob("*.py")))

    def _assert_objects_closed(self, value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                self.assertFalse(value.get("additionalProperties", True))
                self.assertEqual(set(value.get("required", ())), set(value.get("properties", ())))
            for nested in value.values():
                self._assert_objects_closed(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_objects_closed(nested)

    def test_three_draft_schemas_close_every_nested_object(self):
        paths = list((SRC / "schemas").glob("*.schema.json"))
        self.assertEqual(len(paths), 8)
        for path in paths:
            value = json.loads(path.read_text())
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self._assert_objects_closed(value)

    def build_seal(self, temp, now):
        refs = {name: ref(path) for name, (path, _, __) in FROZEN_REFS.items()}
        closure = write_ref(temp, "closure.json", {"status": "FROZEN"})
        refs["stage_a_source_closure"] = closure
        request_id, operation_id = "request/fresh-0001", "operation/fresh-0001"
        process_id, gateway_id = "process/fresh-0001", "gateway/fresh-0001"
        fingerprint = "b" * 64
        admission_key = sha256_bytes((operation_id + fingerprint).encode())
        start, end = now - timedelta(minutes=1), now - timedelta(minutes=1) + timedelta(minutes=30)
        iso = lambda value: value.isoformat().replace("+00:00", "Z")
        observed_at = iso(now - timedelta(seconds=1))
        payload = json.loads((ROOT / FROZEN_REFS["payload"][0]).read_text())
        prompt_bytes = payload["prompt_utf8"].encode()
        self.assertEqual((len(prompt_bytes), sha256_bytes(prompt_bytes)), (PROMPT_BYTES, PROMPT_SHA256))
        prompt_path = temp / "held-prompt"; prompt_path.write_bytes(prompt_bytes)
        held = {"prompt": artifact_ref(prompt_path.relative_to(ROOT).as_posix(), ROOT)}
        held["argv"] = write_ref(temp, "held-argv", {"version": 1, "binary_realpath": BINARY_REALPATH, "argv": CANONICAL_ARGV, "model": MODEL, "effort": EFFORT, "request_id": request_id, "operation_id": operation_id, "stdin": {"transport": "stdin_exact_bytes", "bytes": PROMPT_BYTES, "sha256": PROMPT_SHA256, "occurrences": 1}})
        held["config"] = write_ref(temp, "held-config", {"version": 1, "provider": PROVIDER, "release": RELEASE, "configured_model": MODEL, "effort": EFFORT, "request_retries": 0, "stream_retries": 0, "max_attempts": 1, "concurrency": 1, "countable_observation": False, "request_id": request_id})
        held["catalog"] = write_ref(temp, "held-catalog", {"version": 1, "request_id": request_id, "observed_at": observed_at, "models": [{"token": MODEL, "entitled": True}]})
        parser_output = {"request_id": request_id, "selected_model_token": MODEL, "selected_model_occurrences": 1, "model_entitled": True}
        held["catalog_parser"] = write_ref(temp, "held-catalog-parser", {"version": 1, "parser_id": CATALOG_PARSER_ID, "parser_source_sha256": CATALOG_PARSER_SOURCE_SHA256, "raw_catalog_sha256": held["catalog"]["sha256"], "request_id": request_id, "output": parser_output, "output_sha256": sha256_bytes(canonical_bytes(parser_output))})
        held["process_receipt"] = write_ref(temp, "held-process-receipt", {"process_start_identity": process_id, "request_id": request_id, "operation_id": operation_id, "binary_sha256": BINARY_SHA256, "argv_sha256": held["argv"]["sha256"], "config_sha256": held["config"]["sha256"], "prompt_sha256": PROMPT_SHA256})
        held["gateway_receipt"] = write_ref(temp, "held-gateway-receipt", {"gateway_id": gateway_id, "provider_process_start_identity": process_id, "request_id": request_id, "operation_id": operation_id, "request_fingerprint": fingerprint, "admission_key": admission_key, "prompt_sha256": PROMPT_SHA256})
        custody_hashes = {name: held[name]["sha256"] for name in ("argv", "config", "catalog", "catalog_parser", "prompt", "process_receipt", "gateway_receipt")}
        held["custody_receipt"] = write_ref(temp, "held-custody-receipt", {"version": 1, "kind": "R6_CODEX_CUSTODY_RECEIPT", "execution_id": "execution/fresh-0001", "provider": PROVIDER, "root_class": ".job-runtime/live-provider-evidence/r6-one-off/codex_cli/<execution_id>", "observed_owner_uid": 501, "observed_mode": "0700", "nofollow_components": True, "atomic_finalization": True, "credential_values_present": False, "held_artifact_sha256": custody_hashes})
        held["publication_receipt"] = write_ref(temp, "held-publication-receipt", {"version": 1, "kind": "R6_CODEX_PUBLICATION_CLEANUP_RECEIPT", "execution_id": "execution/fresh-0001", "custody_receipt_sha256": held["custody_receipt"]["sha256"], "process_receipt_sha256": held["process_receipt"]["sha256"], "gateway_receipt_sha256": held["gateway_receipt"]["sha256"], "secret_scan": {"recursive": True, "passed": True, "matches": 0}, "publication": {"allowlist_only": True, "raw_included": False, "staged": True, "fsynced": True, "validated": True, "atomic_no_overwrite": True, "complete": True}, "cleanup": {"process_reaped": True, "observer_closed": True, "descriptors_closed": True, "temporary_evidence_policy": "removed_or_owner_private_unknown", "persistent_resources": 0}})
        seal = {"version": 1, "kind": "EXTERNALLY_SEALED_R6_CODEX_FINAL_GRANT_VALIDATION", "authority_owner": "independent_dual_provider_authority", "self_minted": False, "independent_review_verdict": "CLEAN", "refs": refs, "identity": {"provider": PROVIDER, "release": RELEASE, "model": MODEL, "effort": EFFORT, "profile_selector": "current CLI profile", "expected_account_fingerprint_sha256": "a" * 64, "observed_account_fingerprint_sha256": "a" * 64, "credential_reference": "opaque-ref://codex/current", "credential_reference_sha256": sha256_bytes(b"opaque-ref://codex/current"), "model_entitled": True}, "binary": {"realpath": BINARY_REALPATH, "bytes": BINARY_BYTES, "sha256": BINARY_SHA256, "owner_uid": 501, "mode": "0o755", "archive_path": ARCHIVE_PATH, "archive_bytes": ARCHIVE_BYTES, "archive_sha256": ARCHIVE_SHA256, "official_asset": OFFICIAL_ASSET}, "held_artifacts": held, "command": {"native_exec": True, "shell": False, "prompt_transport": "stdin_exact_bytes", "prompt_occurrences": 1, "machine_readable_terminal": True, "binary_realpath": BINARY_REALPATH, "argv_ref": held["argv"]}, "config": {"provider": PROVIDER, "release": RELEASE, "model": MODEL, "effort": EFFORT, "request_retries": 0, "stream_retries": 0, "max_attempts": 1, "concurrency": 1, "countable_observation": False, "config_ref": held["config"]}, "catalog": {"request_count": 1, "selected_model_token": MODEL, "selected_model_occurrences": 1, "entitlement_confirmed": True, "observed_at": observed_at, "raw_ref": held["catalog"], "parser_ref": held["catalog_parser"]}, "prompt": {"bytes": PROMPT_BYTES, "sha256": PROMPT_SHA256, "cutoff_sha256": CUTOFF_SHA256, "mutation": "forbidden", "artifact_ref": held["prompt"], "operation_binding_sha256": PROMPT_SHA256}, "window_budget": {"currency": "USD", "codex_subcap_usd": .01, "combined_cap_usd": .02, "prior_dual_provider_spend_usd": 0, "remaining_combined_budget_usd": .02, "not_before": iso(start), "deadline": iso(end)}, "engine": {"generated_by": "shared.job_runtime.engine", "execution_id": "execution/fresh-0001", "job_id": "job/fresh-0001", "slot_id": "slot/fresh-0001", "attempt_id": "attempt/fresh-0001", "operation_id": operation_id, "request_id": request_id, "request_fingerprint": fingerprint, "prompt_binding_sha256": PROMPT_SHA256, "atomic_counts": {"job": 1, "slot": 1, "attempt": 1, "operation": 1, "provider_result": 1}}, "gateway": {"gateway_id": gateway_id, "provider_process_start_identity": process_id, "admission_key": admission_key, "request_fingerprint": fingerprint, "admission_count": 1, "dispatch_count": 1, "upstream_attempt_count": 1, "inference_count": 1, "terminal_presence": True, "status_calls": 0, "reconciliation_dispatch": 0}, "custody": {"root_class": ".job-runtime/live-provider-evidence/r6-one-off/codex_cli/<execution_id>", "mode": "0700", "owner_uid": 501, "nofollow_components": True, "provider_separate": True, "credential_values_forbidden": True, "atomic_finalization": True}, "publication_cleanup": {"allowlist_only": True, "recursive_secret_scan": True, "stage_fsync_validate_atomic_no_overwrite": True, "raw_private": True, "process_reaped": True, "observer_closed": True, "descriptors_closed": True, "temporary_evidence_policy": "removed_or_owner_private_unknown", "persistent_resources": 0}, "terminal_policy": {"exclusive": ["PASS", "STOP", "UNKNOWN"], "pass_requires": "exact_terminal_cleanup_and_publication", "stop_requires": "definitely_not_submitted_upstream_zero", "unknown_durable": True, "unknown_retry": False, "unknown_replay": False, "unknown_status_calls": 0, "unknown_reconciliation_dispatch": False, "countable_observation": False}, "effect_dependencies": {name: {"injected": True, "default": "DENY"} for name in EFFECTS}, "limits": dict(LIMITS)}
        codex_subject = {"identity": seal["identity"], "treatment": {"provider": PROVIDER, "release": RELEASE, "model": MODEL, "effort": EFFORT}, "binary_archive": dict(seal["binary"], asset_binding_ref=refs["asset_binding"]), "bindings": {"argv": held["argv"], "config": held["config"], "parser": held["catalog_parser"], "prompt": held["prompt"], "engine_source": refs["engine"], "gateway": held["gateway_receipt"], "process": held["process_receipt"], "custody": held["custody_receipt"], "publication": held["publication_receipt"], "source_closure": closure}, "request": {"execution_id": seal["engine"]["execution_id"], "operation_id": operation_id, "request_id": request_id, "request_fingerprint": fingerprint, "gateway_id": gateway_id, "process_start_identity": process_id, "custody_root_class": seal["custody"]["root_class"]}, "budget_window": {"currency": "USD", "provider_subcap_usd": .01, "combined_cap_usd": .02, "prior_dual_provider_spend_usd": 0, "remaining_combined_budget_usd": .02, "not_before": iso(start), "deadline": iso(end)}, "limits": dict(LIMITS), "effects": copy.deepcopy(seal["effect_dependencies"])}
        registry_path = ROOT / OTHER_AUTHORITY_PATH
        self.assertEqual((len(registry_path.read_bytes()), sha256_bytes(registry_path.read_bytes())), (OTHER_AUTHORITY_BYTES, OTHER_AUTHORITY_SHA256))
        registry = json.loads(registry_path.read_text())
        registry_ref = artifact_ref(OTHER_AUTHORITY_PATH, ROOT)
        other_subject = {"identity": registry["identity"], "treatment": registry["treatment"], "binary_archive": dict(registry["binary_archive"], asset_binding_ref=registry_ref), "bindings": {"argv": held["argv"], "config": held["config"], "parser": held["catalog_parser"], "prompt": held["prompt"], "engine_source": refs["engine"], "gateway": held["gateway_receipt"], "process": held["process_receipt"], "custody": held["custody_receipt"], "publication": held["publication_receipt"], "source_closure": closure}, "request": {"execution_id": seal["engine"]["execution_id"], "operation_id": operation_id, "request_id": request_id, "request_fingerprint": fingerprint, "gateway_id": gateway_id, "process_start_identity": process_id, "custody_root_class": registry["projection"]["custody_root_class"]}, "budget_window": {"currency": "USD", "provider_subcap_usd": .01, "combined_cap_usd": .02, "prior_dual_provider_spend_usd": 0, "remaining_combined_budget_usd": .02, "not_before": iso(start), "deadline": iso(end)}, "limits": dict(LIMITS), "effects": copy.deepcopy(seal["effect_dependencies"])}
        checks = {name: True for name in ("authorization", "identity", "treatment", "binary_archive", "bindings", "budget_window", "limits", "effects")}
        codex_grant = write_ref(temp, "codex-grant.json", {"version": 1, "kind": "R6_PROVIDER_FINAL_GRANT", "issuer_role": "independent_authorization_owner", "self_minted": False, "provider": PROVIDER, "authorization": refs["authorization"], "authorization_review": refs["authorization_review"], "subject": codex_subject})
        codex_review = write_ref(temp, "codex-review.json", {"version": 1, "kind": "R6_PROVIDER_FINAL_GRANT_REVIEW", "reviewer_role": "independent_reviewer", "verdict": "CLEAN", "subject": codex_grant, "checks": checks})
        other_grant = write_ref(temp, "other-grant.json", {"version": 1, "kind": "R6_PROVIDER_FINAL_GRANT", "issuer_role": "independent_authorization_owner", "self_minted": False, "provider": "claude_cli", "authorization": refs["authorization"], "authorization_review": refs["authorization_review"], "subject": other_subject})
        other_review = write_ref(temp, "other-review.json", {"version": 1, "kind": "R6_PROVIDER_FINAL_GRANT_REVIEW", "reviewer_role": "independent_reviewer", "verdict": "CLEAN", "subject": other_grant, "checks": checks})
        refs.update({"codex_final_grant": codex_grant, "codex_final_grant_review": codex_review, "other_provider_final_grant": other_grant, "other_provider_final_grant_review": other_review})
        return seal

    def _set(self, value, dotted, replacement):
        target = value
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = replacement

    def _assert_mutation(self, seal, now, dotted, value, code):
        bad = copy.deepcopy(seal)
        self._set(bad, dotted, value)
        with self.assertRaisesRegex(ContractError, code):
            validate_stage_b_seal(bad, ROOT, now)

    def _assert_rehashed_held_rejected(self, seal, now, name, mutate, code):
        path = ROOT / seal["held_artifacts"][name]["path"]
        original = path.read_bytes()
        try:
            content = json.loads(original)
            mutate(content)
            path.write_text(json.dumps(content, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            bad = copy.deepcopy(seal)
            changed = artifact_ref(path.relative_to(ROOT).as_posix(), ROOT)
            bad["held_artifacts"][name] = changed
            if name == "argv": bad["command"]["argv_ref"] = changed
            if name == "config": bad["config"]["config_ref"] = changed
            if name == "catalog": bad["catalog"]["raw_ref"] = changed
            if name == "catalog_parser": bad["catalog"]["parser_ref"] = changed
            with self.assertRaisesRegex(ContractError, code):
                validate_stage_b_seal(bad, ROOT, now)
        finally:
            path.write_bytes(original)

    def test_stage_b_exact_full_contract_and_fail_closed_mutations(self):
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc)
            seal = self.build_seal(Path(td), now)
            validate_stage_b_seal(seal, ROOT, now)
            cases = [("self_minted", True, "STAGE_B_NO_SELF_MINT"), ("binary.sha256", "0" * 64, "BINARY_IDENTITY_DRIFT"), ("identity.observed_account_fingerprint_sha256", "c" * 64, "ACCOUNT_OR_ENTITLEMENT_INVALID"), ("catalog.selected_model_occurrences", 2, "CATALOG_MEMBERSHIP_INVALID"), ("gateway.status_calls", 1, "GATEWAY_COUNTS_INVALID"), ("publication_cleanup.process_reaped", False, "PUBLICATION_CLEANUP_INCOMPLETE"), ("effect_dependencies.network.default", "ALLOW", "EFFECT_NOT_DENY_BY_DEFAULT"), ("identity.model_entitled", False, "ACCOUNT_OR_ENTITLEMENT_INVALID"), ("config.model", "other", "CONFIG_CONSTANT_INVALID"), ("custody.mode", "0755", "CUSTODY_CONSTANT_INVALID"), ("command.prompt_occurrences", 2, "COMMAND_SEMANTICS_INVALID")]
            for dotted, value, code in cases:
                self._assert_mutation(seal, now, dotted, value, code)

    def test_rehashed_contradictory_held_content_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc)
            seal = self.build_seal(Path(td), now)
            cases = [
                ("argv", lambda v: v.update(binary_realpath="/wrong/codex"), "HELD_ARGV_CONTENT_INVALID"),
                ("argv", lambda v: v.update(model="other"), "HELD_ARGV_CONTENT_INVALID"),
                ("argv", lambda v: v["stdin"].update(occurrences=2), "HELD_ARGV_CONTENT_INVALID"),
                ("config", lambda v: v.update(request_retries=1), "HELD_CONFIG_CONTENT_INVALID"),
                ("config", lambda v: v.update(concurrency=2), "HELD_CONFIG_CONTENT_INVALID"),
                ("catalog", lambda v: v["models"].append({"token": MODEL, "entitled": True}), "HELD_CATALOG_MODEL_INVALID"),
                ("catalog", lambda v: v["models"][0].update(entitled=False), "HELD_CATALOG_MEMBERSHIP_INVALID"),
                ("catalog_parser", lambda v: v.update(parser_id="other_parser"), "HELD_PARSER_CONTENT_INVALID"),
                ("catalog_parser", lambda v: v["output"].update(selected_model_occurrences=0), "HELD_PARSER_CONTENT_INVALID"),
                ("process_receipt", lambda v: v.update(request_id="request/other-0001"), "PROCESS_RECEIPT_BINDING_INVALID"),
                ("gateway_receipt", lambda v: v.update(operation_id="operation/other-0001"), "GATEWAY_RECEIPT_BINDING_INVALID"),
            ]
            for name, mutate, code in cases:
                self._assert_rehashed_held_rejected(seal, now, name, mutate, code)

    def _rewrite_grant_pair(self, seal, grant_key, review_key, mutate):
        grant_path = ROOT / seal["refs"][grant_key]["path"]
        review_path = ROOT / seal["refs"][review_key]["path"]
        grant = json.loads(grant_path.read_text()); mutate(grant)
        grant_path.write_text(json.dumps(grant, sort_keys=True, separators=(",", ":")))
        grant_ref = artifact_ref(grant_path.relative_to(ROOT).as_posix(), ROOT)
        review = json.loads(review_path.read_text()); review["subject"] = grant_ref
        review_path.write_text(json.dumps(review, sort_keys=True, separators=(",", ":")))
        seal["refs"][grant_key] = grant_ref
        seal["refs"][review_key] = artifact_ref(review_path.relative_to(ROOT).as_posix(), ROOT)

    def test_closed_grants_reviews_reject_minimal_drift_and_mismatch(self):
        mutations = [
            (lambda g: g.clear(), "FINAL_GRANT_KEYS_INVALID"),
            (lambda g: g["subject"]["identity"].update(observed_account_fingerprint_sha256="e" * 64), "FINAL_GRANT_ACCOUNT_INVALID"),
            (lambda g: (g["subject"]["identity"].update(model="other"), g["subject"]["treatment"].update(model="other")), "CODEX_FINAL_GRANT_SEAL_MISMATCH"),
            (lambda g: g["subject"]["budget_window"].update(provider_subcap_usd=.02), "FINAL_GRANT_CAP_INVALID"),
            (lambda g: g["subject"]["budget_window"].update(deadline="2026-01-01T00:00:00Z"), "FINAL_GRANT_WINDOW_INVALID"),
            (lambda g: g["subject"]["bindings"].update(argv=g["subject"]["bindings"]["config"]), "CODEX_FINAL_GRANT_SEAL_MISMATCH"),
        ]
        for mutate, code in mutations:
            with tempfile.TemporaryDirectory(dir=FIX) as td:
                now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
                self._rewrite_grant_pair(seal, "codex_final_grant", "codex_final_grant_review", mutate)
                with self.assertRaisesRegex(ContractError, code): validate_stage_b_seal(seal, ROOT, now)
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
            review_path = ROOT / seal["refs"]["codex_final_grant_review"]["path"]
            review = json.loads(review_path.read_text()); review["subject"]["path"] = "swapped.json"
            review_path.write_text(json.dumps(review, sort_keys=True, separators=(",", ":")))
            seal["refs"]["codex_final_grant_review"] = artifact_ref(review_path.relative_to(ROOT).as_posix(), ROOT)
            with self.assertRaisesRegex(ContractError, "FINAL_GRANT_REVIEW_SUBJECT_MISMATCH"): validate_stage_b_seal(seal, ROOT, now)

    def test_duplicate_keys_in_grants_and_reviews_reject(self):
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
            grant_path = ROOT / seal["refs"]["codex_final_grant"]["path"]
            body = grant_path.read_text(); grant_path.write_text('{"provider":"codex_cli",' + body[1:])
            grant_ref = artifact_ref(grant_path.relative_to(ROOT).as_posix(), ROOT)
            review_path = ROOT / seal["refs"]["codex_final_grant_review"]["path"]
            review = json.loads(review_path.read_text()); review["subject"] = grant_ref
            review_path.write_text(json.dumps(review, sort_keys=True, separators=(",", ":")))
            seal["refs"]["codex_final_grant"] = grant_ref
            seal["refs"]["codex_final_grant_review"] = artifact_ref(review_path.relative_to(ROOT).as_posix(), ROOT)
            with self.assertRaisesRegex(ContractError, "FINAL_GRANT_DUPLICATE_KEY"):
                validate_stage_b_seal(seal, ROOT, now)
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
            review_path = ROOT / seal["refs"]["codex_final_grant_review"]["path"]
            body = review_path.read_text(); review_path.write_text('{"verdict":"CLEAN",' + body[1:])
            seal["refs"]["codex_final_grant_review"] = artifact_ref(review_path.relative_to(ROOT).as_posix(), ROOT)
            with self.assertRaisesRegex(ContractError, "FINAL_GRANT_REVIEW_DUPLICATE_KEY"):
                validate_stage_b_seal(seal, ROOT, now)

    def _leaf_paths(self, value, prefix=()):
        if isinstance(value, dict):
            for key in sorted(value):
                yield from self._leaf_paths(value[key], prefix + (key,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from self._leaf_paths(item, prefix + (index,))
        else:
            yield prefix

    def _drift_leaf(self, value):
        if value is None: return "drift"
        if isinstance(value, bool): return not value
        if isinstance(value, int): return value + 1
        if isinstance(value, float): return value + .001
        if isinstance(value, str): return value + "-drift"
        raise AssertionError(type(value))

    def _assign_path(self, value, path, replacement):
        target = value
        for part in path[:-1]: target = target[part]
        target[path[-1]] = replacement

    def test_external_other_authority_accepts_exact_and_rejects_every_leaf_replacement(self):
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
            validate_stage_b_seal(seal, ROOT, now)
            grant = json.loads((ROOT / seal["refs"]["other_provider_final_grant"]["path"]).read_text())
            grant_paths = list(self._leaf_paths(grant))
            review = json.loads((ROOT / seal["refs"]["other_provider_final_grant_review"]["path"]).read_text())
            review_paths = list(self._leaf_paths(review))
        for path in grant_paths:
            with self.subTest(kind="grant", path=path), tempfile.TemporaryDirectory(dir=FIX) as td:
                now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
                def mutate(value, selected=path):
                    current = value
                    for part in selected: current = current[part]
                    self._assign_path(value, selected, self._drift_leaf(current))
                self._rewrite_grant_pair(seal, "other_provider_final_grant", "other_provider_final_grant_review", mutate)
                with self.assertRaises(ContractError): validate_stage_b_seal(seal, ROOT, now)
        for path in review_paths:
            with self.subTest(kind="review", path=path), tempfile.TemporaryDirectory(dir=FIX) as td:
                now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
                review_path = ROOT / seal["refs"]["other_provider_final_grant_review"]["path"]
                value = json.loads(review_path.read_text()); current = value
                for part in path: current = current[part]
                self._assign_path(value, path, self._drift_leaf(current))
                review_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
                seal["refs"]["other_provider_final_grant_review"] = artifact_ref(review_path.relative_to(ROOT).as_posix(), ROOT)
                with self.assertRaises(ContractError): validate_stage_b_seal(seal, ROOT, now)

    def test_strict_custody_and_publication_receipts_reject_contradictions(self):
        cases = [
            ("custody_receipt", lambda v: v.clear(), "CUSTODY_RECEIPT_BINDING_INVALID"),
            ("custody_receipt", lambda v: v.update(observed_mode="0755"), "CUSTODY_RECEIPT_BINDING_INVALID"),
            ("custody_receipt", lambda v: v.update(nofollow_components=False), "CUSTODY_RECEIPT_BINDING_INVALID"),
            ("custody_receipt", lambda v: v.update(credential_values_present=True), "CUSTODY_RECEIPT_BINDING_INVALID"),
            ("publication_receipt", lambda v: v["secret_scan"].update(passed=False), "PUBLICATION_RECEIPT_BINDING_INVALID"),
            ("publication_receipt", lambda v: v["publication"].update(raw_included=True), "PUBLICATION_RECEIPT_BINDING_INVALID"),
            ("publication_receipt", lambda v: v["cleanup"].update(process_reaped=False), "PUBLICATION_RECEIPT_BINDING_INVALID"),
            ("publication_receipt", lambda v: v["cleanup"].update(observer_closed=False), "PUBLICATION_RECEIPT_BINDING_INVALID"),
            ("publication_receipt", lambda v: v["cleanup"].update(descriptors_closed=False), "PUBLICATION_RECEIPT_BINDING_INVALID"),
            ("publication_receipt", lambda v: v["cleanup"].update(persistent_resources=1), "PUBLICATION_RECEIPT_BINDING_INVALID"),
        ]
        for name, mutate, code in cases:
            with tempfile.TemporaryDirectory(dir=FIX) as td:
                now = datetime.now(timezone.utc); seal = self.build_seal(Path(td), now)
                self._assert_rehashed_held_rejected(seal, now, name, mutate, code)

    def test_draft202012_valid_instances_and_nested_adversaries(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("Draft 2020-12 validator unavailable")
        schemas = {path.name: json.loads(path.read_text()) for path in (SRC / "schemas").glob("*.json")}
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        with tempfile.TemporaryDirectory(dir=FIX) as td:
            now = datetime.now(timezone.utc)
            seal = self.build_seal(Path(td), now)
            template = stage_a_template("a" * 64, "opaque-ref://codex/current")
            evidence = execute_stage_a(Path(td) / "stage-a-stop", template, FakeCodexBoundary(), "auth_stop").evidence
            instances = {"stage-a-template-v1.schema.json": template, "stage-a-evidence-v1.schema.json": evidence, "stage-b-seal-v1.schema.json": seal}
            for key in ("codex_final_grant", "other_provider_final_grant"):
                instances.setdefault("provider-final-grant-v1.schema.json", []).append(json.loads((ROOT / seal["refs"][key]["path"]).read_text()))
            for key in ("codex_final_grant_review", "other_provider_final_grant_review"):
                instances.setdefault("provider-final-grant-review-v1.schema.json", []).append(json.loads((ROOT / seal["refs"][key]["path"]).read_text()))
            instances["custody-receipt-v1.schema.json"] = json.loads((ROOT / seal["held_artifacts"]["custody_receipt"]["path"]).read_text())
            instances["publication-cleanup-receipt-v1.schema.json"] = json.loads((ROOT / seal["held_artifacts"]["publication_receipt"]["path"]).read_text())
            instances["other-provider-authority-v1.schema.json"] = json.loads((ROOT / OTHER_AUTHORITY_PATH).read_text())
            for name, instance in instances.items():
                for value in instance if isinstance(instance, list) else [instance]:
                    Draft202012Validator(schemas[name]).validate(value)
            adversaries = []
            for name, dotted, replacement in [
                ("stage-a-template-v1.schema.json", "limits", {}),
                ("stage-a-template-v1.schema.json", "effects.extra", 0),
                ("stage-a-template-v1.schema.json", "codex_subcap_usd", .02),
                ("stage-a-evidence-v1.schema.json", "effects.network", 1),
                ("stage-a-evidence-v1.schema.json", "inference_count", 2),
                ("stage-b-seal-v1.schema.json", "identity", {}),
                ("stage-b-seal-v1.schema.json", "command.extra", True),
                ("stage-b-seal-v1.schema.json", "window_budget.codex_subcap_usd", .02),
                ("stage-b-seal-v1.schema.json", "gateway.dispatch_count", 2),
                ("stage-b-seal-v1.schema.json", "effect_dependencies.network.default", "ALLOW"),
                ("provider-final-grant-v1.schema.json", "subject", {}),
                ("provider-final-grant-v1.schema.json", "subject.budget_window.provider_subcap_usd", .02),
                ("provider-final-grant-review-v1.schema.json", "checks.identity", False),
                ("custody-receipt-v1.schema.json", "observed_mode", "0755"),
                ("custody-receipt-v1.schema.json", "held_artifact_sha256.extra", "0" * 64),
                ("publication-cleanup-receipt-v1.schema.json", "cleanup.persistent_resources", 1),
                ("other-provider-authority-v1.schema.json", "identity.model", "other"),
            ]:
                base = instances[name][0] if isinstance(instances[name], list) else instances[name]
                bad = copy.deepcopy(base)
                self._set(bad, dotted, replacement)
                adversaries.append((name, bad))
            for name, bad in adversaries:
                self.assertFalse(Draft202012Validator(schemas[name]).is_valid(bad), name)


if __name__ == "__main__":
    unittest.main()
