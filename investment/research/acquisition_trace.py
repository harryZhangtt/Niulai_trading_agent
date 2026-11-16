"""Read-only acquisition trace checking and terminal ledger reconciliation.

The checker reopens content-addressed artifacts.  Driver, runner, reconciliation
and UI summaries are inputs to distrust, not evidence accepted at face value.
"""
import json

from shared.research_sources.artifacts import SourceError, digest, read, save
from investment.research.acquisition_review import verify_reviewer_decision
from investment.research.acquisition_runner import RunnerError, verify_dispatch_receipt
from shared.research_sources.acquisition_contracts import CheckedEiyCaseRequest, ContractError
from shared.research_sources.host_adapter_contracts import (
    CredentialReadinessReceipt, HostContractError, HostInvocationReceipt,
    OperationalTrustPolicy,
)


VERSION = "acquisition-trace-0.1.0"


def _gate(name, passed, passed_reason, failed_reason):
    return {"gate": name, "passed": bool(passed),
            "reasons": [passed_reason if passed else failed_reason]}


def _refs(values):
    return list(values) if isinstance(values, (list, tuple)) else []


def _ref_key(ref):
    return (ref.get("path"), ref.get("sha256")) if isinstance(ref, dict) else None


def _receipt_arguments(receipt):
    request_ref = receipt.get("request_ref")
    if not request_ref:
        return None
    request = read(request_ref)
    return request.get("arguments")


_BACKEND_TOOLS = {
    "native_tools.web__run": {
        "search": "native_tools.web__run", "open": "native_tools.web__run"},
    "claude_code.web": {
        "search": "claude_code.WebSearch", "open": "claude_code.WebFetch"},
}


def _tool_identity_ok(host, dispatches, host_receipts):
    backend = host.get("backend")
    allowed = _BACKEND_TOOLS.get(backend)
    receipts = {row.get("operation_id"): row for row in host_receipts
                if row.get("fetch_executed") is True}
    if len(receipts) != len(dispatches):
        return False
    for dispatch in dispatches:
        receipt = receipts.get(dispatch.get("operation_id"))
        operation = receipt and receipt.get("operation")
        expected = allowed.get(operation) if allowed else backend
        if not expected or dispatch.get("observed_backend") != expected:
            return False
    return True


def _host_evidence(driver):
    host = read(driver["host_run_ref"])
    receipts = [read(ref) for ref in
                host.get("search_receipt_refs", []) + host.get("open_receipt_refs", [])]
    exposure = read(host["exposure_ref"])
    events = [read(ref) for ref in exposure.get("event_refs", [])]
    return host, receipts, events


def _host_readiness_evidence(host_profile_ref, credential_readiness_ref, backend):
    try:
        profile_artifact = read(host_profile_ref)
        credential_artifact = read(credential_readiness_ref)
        profile = profile_artifact["profile"]
        credential = profile["credential"]
        receipt = CredentialReadinessReceipt.from_public_dict(
            credential_artifact["receipt"])
        ok = (profile_artifact.get("kind") == "acquisition_host_profile"
              and credential_artifact.get("kind") == "acquisition_credential_readiness"
              and profile.get("configured_backend") == backend
              and credential.get("credential_value_present") is False
              and profile.get("mcp") is None
              and receipt.profile_ref == credential.get("profile_ref"))
        return ok, receipt.live_acceptance_eligible
    except (SourceError, HostContractError, OSError, ValueError, KeyError, TypeError):
        return False, False


def _operational_invocation_evidence(host_invocation_refs, dispatches, *, backend,
                                     expected_adapter, expected_session_id):
    try:
        artifacts = [read(ref) for ref in _refs(host_invocation_refs)]
        receipts = [HostInvocationReceipt.from_public_dict(row["receipt"])
                    for row in artifacts
                    if row.get("kind") == "acquisition_host_invocation_receipt"]
    except (SourceError, HostContractError, OSError, ValueError, KeyError, TypeError):
        return False, False
    dispatch_by_id = {row.get("dispatch_id"): row for row in dispatches}
    if len(receipts) != len(dispatches) or len(dispatch_by_id) != len(dispatches):
        return False, False
    for receipt in receipts:
        dispatch = dispatch_by_id.get(receipt.dispatch_id)
        if (not dispatch or receipt.adapter_id.value != expected_adapter
                or receipt.configured_backend != backend
                or receipt.host_session_id != expected_session_id
                or receipt.acquisition_arguments_sha256
                    != dispatch.get("arguments_sha256")
                or receipt.result_sha256 != dispatch.get("evidence_sha256")
                or receipt.observed_tool_identity
                    != dispatch.get("observed_backend")):
            return False, False
    return True, all(receipt.live_acceptance_eligible for receipt in receipts)


def _controller_evidence(driver):
    controller = read(driver["controller_summary_ref"])
    manifest = read(controller["manifest_ref"])
    transitions = [read(ref) for ref in controller.get("transition_refs", [])]
    return controller, manifest, transitions


def reconcile_terminal_ledgers(directory, *, driver_ref, dispatch_refs, review_refs,
                               expected_dispatches, host_invocation_refs=(),
                               trust_policy=None, host_session_id=None,
                               host_adapter=None):
    """Recompute and persist terminal cross-ledger accounting.

    `dispatch_refs` are durable actual-invocation receipts, not reservations.  The
    report records every gate and remains evidence to be independently reopened by
    `check_acquisition_trace`; its own verdict is never trusted by that checker.
    """
    driver = read(driver_ref)
    controller, _, transitions = _controller_evidence(driver)
    host, host_receipts, _ = _host_evidence(driver)
    dispatches = [verify_dispatch_receipt(ref) for ref in _refs(dispatch_refs)]
    reviews = [verify_reviewer_decision(ref) for ref in _refs(review_refs)]
    expected_adapter = ("codex_native_web" if host.get("backend") == "native_tools.web__run"
                        else "claude_code_web" if host.get("backend") == "claude_code.web"
                        else None)
    operational_ok, invocation_live = _operational_invocation_evidence(
        host_invocation_refs, dispatches, backend=host.get("backend"),
        expected_adapter=expected_adapter, expected_session_id=host_session_id)
    review_operational_ok = all(
        row.get("trust_policy") == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
        and isinstance(row.get("reviewer_session_receipt"), dict)
        for row in reviews)
    review_live = review_operational_ok and all(
        row.get("live_acceptance_eligible") is True for row in reviews)

    identities = {key: driver.get(key) for key in
                  ("experiment_id", "execution_id", "trace_id")}
    operation_ids = set(driver.get("operation_states", {}))
    controller_ids = {row.get("operation_id") for row in transitions
                      if row.get("decision") == "capture"}
    host_ids = {row.get("operation_id") for row in host_receipts}
    dispatch_ids = [row.get("dispatch_id") for row in dispatches]
    dispatch_operations = {row.get("operation_id") for row in dispatches}
    actual = sum(row.get("provider_items", 1) for row in dispatches
                 if row.get("status") in {"captured", "returned", "failed"}
                 and row.get("invocation_started") is True)
    host_actual = sum(row.get("provider_items", 0) for row in host_receipts
                      if row.get("fetch_executed") is True)
    controller_usage = controller.get("usage", {}).get("provider_items")
    host_usage = host.get("usage", {}).get("provider_items")

    gates = [
        _gate("identity", all(identities.values())
              and host.get("execution_id") == identities["execution_id"]
              and all(row.get("execution_id") == identities["execution_id"]
                      for row in dispatches + reviews),
              "experiment, execution and trace identities agree",
              "identity mismatch across driver, host, dispatch or review ledgers"),
        _gate("configured_backend", isinstance(host.get("backend"), str)
              and bool(host["backend"])
              and all(row.get("configured_backend") == host["backend"] for row in dispatches),
              "runner dispatches match the frozen HostWeb backend",
              "runner and HostWeb configured backend identities differ"),
        _gate("observed_tool_identity", _tool_identity_ok(host, dispatches, host_receipts),
              "every dispatch used the operation-compatible tool for its frozen backend",
              "an observed host tool is missing or incompatible with its operation/backend"),
        _gate("terminal_operations", bool(operation_ids)
              and all(history and history[-1].get("state") == "finalized"
                      for history in driver.get("operation_states", {}).values()),
              "all driver operations are finalized",
              "one or more driver operations are absent or non-terminal"),
        _gate("operation_sets", operation_ids == controller_ids == host_ids
              and dispatch_operations == {row.get("operation_id") for row in host_receipts
                                           if row.get("fetch_executed") is True},
              "driver, controller, HostWeb and actual-dispatch operations reconcile",
              "operation identities differ across terminal ledgers"),
        _gate("dispatch_uniqueness", len(dispatch_ids) == len(set(dispatch_ids))
              and all(isinstance(value, str) and value for value in dispatch_ids),
              "every actual dispatch has one unique durable dispatch id",
              "a dispatch id is missing or duplicated"),
        _gate("dispatch_cardinality", type(expected_dispatches) is int
              and expected_dispatches >= 0 and actual == host_actual == expected_dispatches,
              f"actual and HostWeb dispatch cardinality is {expected_dispatches}",
              f"dispatch cardinality differs: actual={actual}, host={host_actual}, expected={expected_dispatches}"),
        _gate("usage_accounting", controller_usage == host_usage == host_actual,
              "controller reservations, HostWeb usage and actual dispatches reconcile",
              f"usage differs: controller={controller_usage}, host={host_usage}, actual={host_actual}"),
        _gate("review_ledger", {_ref_key(ref) for ref in driver.get("unit_refs", [])}
              == {_ref_key(row["binding"]["unit_ref"]) for row in reviews}
              and len(reviews) == len({_ref_key(row["binding"]["unit_ref"]) for row in reviews})
              and all(row["disposition"] in {"approve", "reject"} for row in reviews),
              "every terminal candidate unit has exactly one verified review",
              "terminal unit and verified-review ledgers differ"),
    ]
    if trust_policy is not None:
        gates.extend([
            _gate("operational_invocation_receipts",
                  trust_policy == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
                  and operational_ok,
                  "every dispatch is bound to matching operational host evidence",
                  "operational invocation evidence is missing or mismatched"),
            _gate("operational_reviewer_session", review_operational_ok,
                  "review is bound to a distinct operational reviewer session",
                  "reviewer operational-session evidence is missing or invalid"),
        ])
    live_acceptance_eligible = bool(
        trust_policy == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
        and operational_ok and invocation_live and review_live)
    report = {
        "kind": "acquisition_terminal_reconciliation",
        "version": VERSION,
        **identities,
        "driver_ref": driver_ref,
        "dispatch_refs": _refs(dispatch_refs),
        "host_invocation_refs": _refs(host_invocation_refs),
        "review_refs": _refs(review_refs),
        "trust_policy": trust_policy,
        "host_session_id": host_session_id,
        "host_adapter": host_adapter,
        "expected_dispatches": expected_dispatches,
        "actual_dispatches": actual,
        "gates": gates,
        "status": "pass" if all(row["passed"] for row in gates) else "fail",
        "live_acceptance_eligible": live_acceptance_eligible,
        "cryptographic_remote_attestation": False,
        "operational_evidence_limit": "does_not_resist_malicious_same_user_file_forgery",
        "scope": "terminal_structural_reconciliation_not_provider_quality_or_alpha",
    }
    return {"reconciliation_ref": save(directory, report), "reconciliation": report}


def check_acquisition_smoke_trace(*, driver_ref, dispatch_refs, proposal_refs,
                                  host_invocation_refs, host_profile_ref,
                                  credential_readiness_ref, trust_policy,
                                  host_session_id, host_adapter,
                                  reconciliation_ref=None):
    """Verify one real search call without semantic unit/reviewer requirements."""
    gates = []
    try:
        driver = read(driver_ref)
        host, host_receipts, _events = _host_evidence(driver)
        dispatches = [verify_dispatch_receipt(ref) for ref in _refs(dispatch_refs)]
        proposals = [read(ref) for ref in _refs(proposal_refs)]
        backend = host.get("backend")
        expected_adapter = ("codex_native_web" if backend == "native_tools.web__run"
                            else "claude_code_web" if backend == "claude_code.web"
                            else None)
        operational_ok, invocation_live = _operational_invocation_evidence(
            host_invocation_refs, dispatches, backend=backend,
            expected_adapter=expected_adapter, expected_session_id=host_session_id)
        credential_ok, credential_live = _host_readiness_evidence(
            host_profile_ref, credential_readiness_ref, backend)
    except (SourceError, RunnerError, OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        return {"kind": "acquisition_smoke_trace_verdict", "version": VERSION,
                "status": "fail", "actual_dispatches": 0,
                "gates": [_gate("artifacts_reopened", False, "",
                                f"artifact reopen failed: {type(error).__name__}")],
                "live_acceptance_eligible": False,
                "scope": "live_callability_only_not_full_e2e_or_quality"}
    identities = {key: driver.get(key) for key in
                  ("experiment_id", "execution_id", "trace_id")}
    search_receipts = [row for row in host_receipts
                       if row.get("operation") == "search"
                       and row.get("fetch_executed") is True]
    no_semantics = (not driver.get("assessment_refs") and not driver.get("unit_refs"))
    gates.extend([
        _gate("identity", all(identities.values()) and host.get("execution_id") == identities["execution_id"],
              "smoke identities agree", "smoke identity mismatch"),
        _gate("single_search", len(proposals) == len(dispatches) == len(search_receipts) == 1
              and "search_query" in proposals[0].get("arguments", {}),
              "exactly one search operation was dispatched", "smoke is not exactly one search"),
        _gate("observed_tool_identity", _tool_identity_ok(host, dispatches, host_receipts),
              "search used the operation-compatible tool", "search tool identity mismatch"),
        _gate("operational_invocation_receipt", trust_policy == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
              and operational_ok, "dispatch is bound to operational host evidence",
              "operational host evidence is missing or mismatched"),
        _gate("host_credential_readiness", credential_ok,
              "host profile and fresh credential readiness are bound",
              "host profile or credential readiness is invalid"),
        _gate("no_semantic_credit", no_semantics,
              "smoke contains no assessments or credited units",
              "smoke improperly contains semantic credit"),
    ])
    if reconciliation_ref is not None:
        try:
            prior = read(reconciliation_ref)
            reconciled = (prior.get("driver_ref") == driver_ref
                          and prior.get("dispatch_refs") == _refs(dispatch_refs)
                          and prior.get("host_invocation_refs") == _refs(host_invocation_refs)
                          and prior.get("expected_dispatches") == 1
                          and prior.get("actual_dispatches") == 1)
        except (SourceError, OSError, ValueError, KeyError, TypeError):
            reconciled = False
        gates.append(_gate("reconciliation_binding", reconciled,
                           "smoke reconciliation matches the reopened inputs",
                           "smoke reconciliation is absent or mismatched"))
    status = "pass" if all(row["passed"] for row in gates) else "fail"
    live = bool(status == "pass" and invocation_live and credential_live)
    return {"kind": "acquisition_smoke_trace_verdict", "version": VERSION,
            **identities, "status": status, "actual_dispatches": len(dispatches),
            "complete_chains": 0, "credited_units": 0, "gates": gates,
            "trust_policy": trust_policy, "host_session_id": host_session_id,
            "host_adapter": host_adapter, "live_acceptance_eligible": live,
            "cryptographic_remote_attestation": False,
            "verdict_sha256": digest([identities, status, gates, trust_policy,
                                      host_session_id, host_adapter, live]),
            "scope": "live_callability_only_not_full_e2e_or_quality"}


def derive_acquisition_chain_authority(*, driver_ref, dispatch_refs, review_refs,
                                       proposal_refs, host_invocation_refs=(),
                                       host_session_id=None, arm=None):
    """Reopen and join acquisition evidence into one private chain fact table.

    This is the sole semantic join core for public trace verdicts and EIY v3.
    Its output is private checker data, not a publication or remote attestation.
    """
    if arm not in {None, "B0", "F"}:
        raise SourceError("ACQ_CHAIN_ARM_INVALID")
    driver = read(driver_ref)
    controller, manifest, transitions = _controller_evidence(driver)
    host = read(driver["host_run_ref"])
    host_receipts = [read(ref) for ref in
                     host.get("search_receipt_refs", []) + host.get("open_receipt_refs", [])]
    exposure_index = []
    exposure_manifest = read(host["exposure_ref"])
    for exposure_ref in exposure_manifest.get("event_refs", []):
        event = read(exposure_ref)
        for source_ref in event.get("exposed_source_refs", []):
            exposure_index.append({"operation_id": event.get("operation_id"),
                                   "source_ref": source_ref,
                                   "exposure_ref": exposure_ref})
    dispatches = [verify_dispatch_receipt(ref) for ref in _refs(dispatch_refs)]
    proposals = [read(ref) for ref in _refs(proposal_refs)]
    reviews = [verify_reviewer_decision(ref) for ref in _refs(review_refs)]
    identities = {key: driver.get(key) for key in ("experiment_id", "execution_id", "trace_id")}
    expected_adapter = ("codex_native_web" if host.get("backend") == "native_tools.web__run"
                        else "claude_code_web" if host.get("backend") == "claude_code.web"
                        else None)
    operational_ok, invocation_live = _operational_invocation_evidence(
        host_invocation_refs, dispatches, backend=host.get("backend"),
        expected_adapter=expected_adapter, expected_session_id=host_session_id)
    questions = {row.get("id"): row for row in manifest.get("questions", [])}
    proposal_by_operation = {row.get("operation_id"): row for row in proposals}
    receipt_by_operation = {row.get("operation_id"): row for row in host_receipts}
    dispatch_by_operation = {row.get("operation_id"): row for row in dispatches}
    exposures = {(row["operation_id"], row["source_ref"].get("sha256")): row
                 for row in exposure_index}
    assessment_refs = {_ref_key(ref) for ref in driver.get("assessment_refs", [])}
    unit_refs = {_ref_key(ref) for ref in driver.get("unit_refs", [])}
    chains, rejected = [], []
    for review in reviews:
        binding = review.get("binding", {})
        reasons = []
        try:
            assessment = read(binding["assessment_ref"])
            unit = read(binding["unit_ref"])
            source = read(binding["source_ref"])
            text_bytes = read(source["text"], json_value=False)
            text = text_bytes.decode("utf-8")
        except (SourceError, OSError, KeyError, UnicodeError, TypeError):
            rejected.append({"review_id": review.get("review_id"),
                             "reasons": ["artifact_reopen_failed"]})
            continue
        operation_id = assessment.get("operation_id")
        proposal = proposal_by_operation.get(operation_id)
        receipt = receipt_by_operation.get(operation_id)
        dispatch = dispatch_by_operation.get(operation_id)
        question_id = assessment.get("question_id")
        if question_id not in questions: reasons.append("question_missing")
        if not proposal or question_id not in proposal.get("question_ids", []):
            reasons.append("proposal_missing_or_unbound")
        arguments = receipt and _receipt_arguments(receipt)
        if (not proposal or proposal.get("arguments") != arguments or not dispatch
                or json.loads(dispatch.get("canonical_arguments", b"{}")) != proposal.get("arguments")):
            reasons.append("exact_arguments_mismatch")
        if (dispatch and host.get("backend") is not None
                and dispatch.get("configured_backend") != host.get("backend")):
            reasons.append("configured_backend_mismatch")
        if (not assessment.get("attempt_id") or not dispatch
                or dispatch.get("attempt_id") != assessment.get("attempt_id")
                or not dispatch.get("dispatch_id") or dispatch.get("invocation_started") is not True):
            reasons.append("attempt_or_dispatch_missing")
        if (not receipt or receipt.get("fetch_executed") is not True
                or binding["source_ref"].get("sha256") not in receipt.get("source_sha256s", [])):
            reasons.append("source_not_bound_to_receipt")
        exposure = exposures.get((operation_id, binding["source_ref"].get("sha256")))
        if not exposure: reasons.append("source_not_exposed")
        if (source.get("source_version") != assessment.get("source_version")
                or source.get("raw", {}).get("sha256") != assessment.get("raw_sha256")
                or source.get("text", {}).get("sha256") != assessment.get("text_sha256")):
            reasons.append("source_version_mismatch")
        quote = assessment.get("quote")
        quote_bytes = quote.encode("utf-8") if isinstance(quote, str) else b""
        occurrence_count = text_bytes.count(quote_bytes) if quote_bytes else 0
        if occurrence_count != 1:
            reasons.append("quote_occurrence_not_unique")
            quote_start = quote_end = None
        else:
            quote_start = text_bytes.index(quote_bytes); quote_end = quote_start + len(quote_bytes)
        if (_ref_key(binding.get("assessment_ref")) not in assessment_refs
                or _ref_key(binding.get("unit_ref")) not in unit_refs
                or unit.get("assessment_ref") != binding.get("assessment_ref")):
            reasons.append("assessment_or_unit_not_terminal")
        if any(review.get(key) != identities[key] for key in identities):
            reasons.append("review_identity_mismatch")
        fact = {
            "arm": arm or "trace",
            **identities,
            "operation_id": operation_id,
            "attempt_id": assessment.get("attempt_id"),
            "dispatch_id": dispatch.get("dispatch_id") if dispatch else None,
            "arguments_sha256": digest(arguments) if arguments is not None else None,
            "source_ref_sha256": binding.get("source_ref", {}).get("sha256"),
            "source_url": source.get("source_url"),
            "source_version": source.get("source_version"),
            "raw_sha256": source.get("raw", {}).get("sha256"),
            "text_sha256": source.get("text", {}).get("sha256"),
            "exposure_ref_sha256": (exposure or {}).get("exposure_ref", {}).get("sha256"),
            "question_id": question_id,
            "assessment_ref_sha256": binding.get("assessment_ref", {}).get("sha256"),
            "quote_sha256": digest(quote) if isinstance(quote, str) else None,
            "quote_utf8_start": quote_start,
            "quote_utf8_end": quote_end,
            "unit_id": unit.get("unit_id"),
            "unit_ref_sha256": binding.get("unit_ref", {}).get("sha256"),
            "review_id": review.get("review_id"),
            "review_ref_sha256": next((r.get("sha256") for r in _refs(review_refs)
                                        if read(r).get("review_id") == review.get("review_id")), None),
            "disposition": review.get("disposition"),
        }
        fact["chain_id"] = digest(["acquisition-chain-1", fact])
        if reasons:
            rejected.append({"review_id": review.get("review_id"),
                             "unit_id": unit.get("unit_id"), "reasons": sorted(set(reasons))})
        else:
            chains.append(fact)
    unsigned = {"schema_version": "acquisition-chain-authority-1",
                "identities": identities, "backend": host.get("backend"),
                "chains": chains, "rejected": rejected}
    return {**unsigned, "authority_sha256": digest(unsigned),
            "driver": driver, "controller": controller, "manifest": manifest,
            "transitions": transitions, "host": host,
            "host_receipts": host_receipts, "dispatches": dispatches,
            "proposals": proposals, "reviews": reviews,
            "operational_ok": operational_ok, "invocation_live": invocation_live}


def check_acquisition_trace(*, driver_ref, dispatch_refs, review_refs,
                            proposal_refs, expected_dispatches, expected_credited_units=1,
                            reconciliation_ref=None, host_profile_ref=None,
                            credential_readiness_ref=None,
                            host_invocation_refs=(), trust_policy=None,
                            host_session_id=None, host_adapter=None):
    """Independently require complete approved chains through the shared join core."""
    try:
        authority = derive_acquisition_chain_authority(
            driver_ref=driver_ref, dispatch_refs=dispatch_refs,
            review_refs=review_refs, proposal_refs=proposal_refs,
            host_invocation_refs=host_invocation_refs, host_session_id=host_session_id)
    except (SourceError, RunnerError, OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        code = str(error) if isinstance(error, SourceError) else type(error).__name__
        return {"kind": "acquisition_trace_verdict", "version": VERSION,
                "status": "fail", "complete_chains": 0, "credited_units": 0,
                "gates": [_gate("artifacts_reopened", False, "", f"artifact reopen failed: {code}")],
                "scope": "structural_trace_only_not_provider_quality_or_alpha"}
    driver=authority["driver"];host=authority["host"];dispatches=authority["dispatches"]
    reviews=authority["reviews"];host_receipts=authority["host_receipts"]
    identities=authority["identities"];chains=authority["chains"]
    approved=[row for row in reviews if row.get("disposition")=="approve"]
    complete=len([row for row in chains if row.get("disposition")=="approve"]);credited=len(approved)
    gates=[_gate("artifacts_reopened",True,"all referenced artifacts were reopened and hash-verified","")]
    identity_ok=(all(isinstance(v,str) and v for v in identities.values())
                 and host.get("execution_id")==identities["execution_id"]
                 and all(all(row.get(k)==v for k,v in identities.items()) for row in dispatches+reviews))
    gates.append(_gate("identity",identity_ok,"experiment, execution and trace identities are present and consistent","experiment, execution or trace identity is missing or inconsistent"))
    backend_ok=(isinstance(host.get("backend"),str) and bool(host["backend"])
                and all(row.get("configured_backend")==host["backend"] for row in dispatches))
    gates.append(_gate("configured_backend",backend_ok,"every runner dispatch is bound to the frozen HostWeb backend","runner and HostWeb configured backend identities differ"))
    gates.append(_gate("observed_tool_identity",_tool_identity_ok(host,dispatches,host_receipts),"every dispatch used the operation-compatible tool for its frozen backend","an observed host tool is missing or incompatible with its operation/backend"))
    credential_ok=credential_live=False
    if host_profile_ref is not None or credential_readiness_ref is not None:
        if host_profile_ref is not None and credential_readiness_ref is not None:
            credential_ok,credential_live=_host_readiness_evidence(host_profile_ref,credential_readiness_ref,host.get("backend"))
        gates.append(_gate("host_credential_readiness",credential_ok,"sanitized host profile and operational credential readiness are bound; MCP is not used","host profile or operational credential readiness binding is missing or invalid"))
    review_operational_ok=all(row.get("trust_policy")==OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value and isinstance(row.get("reviewer_session_receipt"),dict) for row in reviews)
    review_live=review_operational_ok and all(row.get("live_acceptance_eligible") is True for row in reviews)
    if trust_policy is not None:
        gates.extend([_gate("operational_invocation_receipts",trust_policy==OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value and authority["operational_ok"],"every dispatch is bound to matching operational host evidence","operational invocation evidence is missing or mismatched"),_gate("operational_reviewer_session",review_operational_ok,"review is bound to a distinct operational reviewer session","reviewer operational-session evidence is missing or invalid")])
    chain_reason="; ".join(f"{row.get('unit_id','unknown')}:"+",".join(row["reasons"]) for row in authority["rejected"])
    gates.append(_gate("complete_chains",type(expected_credited_units) is int and expected_credited_units>=0 and credited==expected_credited_units and complete==credited,f"exactly {expected_credited_units} approved units have complete independently reopened chains",chain_reason or f"required {expected_credited_units}/{expected_credited_units} complete chains, observed {complete}/{credited}"))
    actual=sum(row.get("provider_items",1) for row in dispatches if row.get("invocation_started") is True and row.get("status") in {"captured","returned","failed"})
    unique=[row.get("dispatch_id") for row in dispatches]
    gates.append(_gate("actual_dispatches",actual==expected_dispatches and len(unique)==len(set(unique)) and all(unique),f"exactly {expected_dispatches} unique actual dispatches were reopened",f"expected {expected_dispatches} unique actual dispatches, observed {actual}"))
    expected_operations={row.get("operation_id") for row in host_receipts if row.get("fetch_executed") is True}
    gates.append(_gate("dispatch_operation_coverage",{row.get("operation_id") for row in dispatches}==expected_operations==set(driver.get("operation_states",{})),"every terminal search/open operation has one verified runner dispatch","verified runner, HostWeb and driver operation sets differ"))
    gates.append(_gate("search_not_credited",all(read(review["binding"]["source_ref"]).get("access_level")!="metadata" for review in approved),"no metadata-only search source received unit credit","a metadata-only search source received unit credit"))
    if reconciliation_ref is not None:
        try:
            prior=read(reconciliation_ref);recomputed=(prior.get("driver_ref")==driver_ref and prior.get("dispatch_refs")==_refs(dispatch_refs) and prior.get("host_invocation_refs")==_refs(host_invocation_refs) and prior.get("review_refs")==_refs(review_refs) and prior.get("trust_policy")==trust_policy and prior.get("host_session_id")==host_session_id and prior.get("host_adapter")==host_adapter and prior.get("expected_dispatches")==expected_dispatches)
        except (SourceError,OSError,ValueError,KeyError,TypeError):recomputed=False
        gates.append(_gate("reconciliation_binding",recomputed,"reconciliation inputs match independently reopened inputs","reconciliation is missing, unreadable or bound to different inputs"))
    status="pass" if all(row["passed"] for row in gates) else "fail"
    live=bool(status=="pass" and trust_policy==OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value and credential_live and authority["invocation_live"] and review_live)
    return {"kind":"acquisition_trace_verdict","version":VERSION,**identities,"status":status,"complete_chains":complete,"credited_units":credited,"gates":gates,"trust_policy":trust_policy,"host_session_id":host_session_id,"host_adapter":host_adapter,"live_acceptance_eligible":live,"cryptographic_remote_attestation":False,"operational_evidence_limit":"does_not_resist_malicious_same_user_file_forgery","verdict_sha256":digest([identities,status,complete,credited,gates,trust_policy,host_session_id,host_adapter,live]),"scope":"structural_trace_only_not_provider_quality_or_alpha"}

EIY_MATCHED_CASE_VERSION = "information-yield-matched-case-2"


def _eiy_require(ok, code):
    if not ok:
        raise SourceError(code)


def _eiy_exact(value, keys, code):
    _eiy_require(isinstance(value, dict) and set(value) == set(keys), code)
    return value


def _eiy_id(value, code):
    import re
    _eiy_require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value), code)
    return value


def _eiy_sha(value, code):
    import re
    _eiy_require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value), code)
    return value


def _checked_eiy_arm(name, arm, case):
    config = read(arm.config_ref)
    admission = read(arm.admission_ref)
    driver = read(arm.driver_ref)
    _eiy_exact(config, {"schema_version", "arm", "backend", "model_sha256", "effort",
                        "prompt_sha256", "tool_sha256", "safety_sha256", "catalog_sha256",
                        "taxonomy_sha256", "budget", "deadlines", "cache_namespace",
                        "order_index", "cutoff", "expected_dispatches", "expected_credited_units", "trust_policy",
                        "experiment_id", "execution_id", "trace_id",
                        "host_session_id", "host_adapter"}, "ACQ_EIY_CONFIG_FIELDS")
    _eiy_require(config["schema_version"] == "information-yield-arm-config-2"
                 and config["arm"] == name and config["cutoff"] == case["cutoff"]
                 and all(config[k] == driver.get(k) for k in ("experiment_id","execution_id","trace_id")),
                 "ACQ_EIY_CONFIG_BINDING")
    for key in ("model_sha256", "prompt_sha256", "tool_sha256", "safety_sha256",
                "catalog_sha256", "taxonomy_sha256"):
        _eiy_sha(config[key], "ACQ_EIY_CONFIG_HASH")
    _eiy_require(type(config["expected_dispatches"]) is int and config["expected_dispatches"] >= 0,
                 "ACQ_EIY_DISPATCH_BUDGET")
    verdict = check_acquisition_trace(
        driver_ref=arm.driver_ref, dispatch_refs=arm.dispatch_refs, review_refs=arm.review_refs,
        proposal_refs=arm.proposal_refs, expected_dispatches=config["expected_dispatches"], expected_credited_units=config["expected_credited_units"],
        reconciliation_ref=arm.reconciliation_ref, host_profile_ref=arm.host_profile_ref,
        credential_readiness_ref=arm.credential_readiness_ref,
        host_invocation_refs=arm.host_invocation_refs, trust_policy=config["trust_policy"],
        host_session_id=config["host_session_id"], host_adapter=config["host_adapter"])
    _eiy_require(verdict.get("status") == "pass"
                 and verdict.get("complete_chains") == verdict.get("credited_units"),
                 "ACQ_EIY_TRACE_REJECTED")
    _eiy_exact(admission, {"schema_version", "arm", "execution_id", "canonical_units",
                           "required_fields", "precision", "freshness", "financial_readiness",
                           "hard_failures", "recovery_opportunities"}, "ACQ_EIY_ADMISSION_FIELDS")
    _eiy_require(admission["schema_version"] == "information-yield-arm-admission-2"
                 and admission["arm"] == name
                 and admission["execution_id"] == driver.get("execution_id"),
                 "ACQ_EIY_ADMISSION_BINDING")
    unit_refs = {row["sha256"]: row for row in driver.get("unit_refs", [])}
    review_refs = {row["sha256"]: row for row in driver.get("review_refs", [])}
    checked_units = []
    evidence_ids = set()
    canonical_semantics = {}
    for row in admission["canonical_units"]:
        _eiy_exact(row, {"unit_ref", "review_ref", "canonical_key_sha256", "canonical_id",
                         "novelty_class", "lineage_sha256", "evidence_unit_sha256s", "source_arm"},
                   "ACQ_EIY_UNIT_FIELDS")
        _eiy_require(row["source_arm"] == name and row["novelty_class"] in
                     {"new_fact", "refinement", "counterevidence"}, "ACQ_EIY_UNIT_ADMISSION")
        unit_sha = row["unit_ref"].get("sha256") if isinstance(row["unit_ref"], dict) else None
        review_sha = row["review_ref"].get("sha256") if isinstance(row["review_ref"], dict) else None
        _eiy_require(unit_sha in unit_refs and review_sha in review_refs, "ACQ_EIY_UNIT_REF")
        unit = read(unit_refs[unit_sha]); review = verify_reviewer_decision(review_refs[review_sha])
        _eiy_require(review.get("disposition") == "approve"
                     and review.get("binding", {}).get("unit_ref", {}).get("sha256") == unit_sha,
                     "ACQ_EIY_UNIT_REVIEW")
        key = _eiy_sha(row["canonical_key_sha256"], "ACQ_EIY_CANONICAL_KEY")
        semantic = (row["canonical_id"], row["novelty_class"], row["lineage_sha256"])
        _eiy_require(key not in canonical_semantics or canonical_semantics[key] == semantic,
                     "ACQ_EIY_CANONICAL_CONFLICT")
        canonical_semantics[key] = semantic
        ids = row["evidence_unit_sha256s"]
        _eiy_require(isinstance(ids, list) and ids and len(ids) == len(set(ids))
                     and all(isinstance(x, str) and len(x) == 64 for x in ids),
                     "ACQ_EIY_EVIDENCE_UNITS")
        evidence_ids.update(ids)
        checked_units.append({"canonical_key_sha256": key,
                              "canonical_id": _eiy_id(row["canonical_id"], "ACQ_EIY_CANONICAL_ID"),
                              "novelty_class": row["novelty_class"],
                              "lineage_sha256": _eiy_sha(row["lineage_sha256"], "ACQ_EIY_LINEAGE"),
                              "evidence_unit_sha256s": sorted(ids)})
    checked_fields = []
    states = {"unknown", "partial", "resolved"}
    for row in admission["required_fields"]:
        _eiy_exact(row, {"field_id", "baseline_state", "post_state", "reviewed",
                         "evidence_unit_sha256s"}, "ACQ_EIY_FIELD_FIELDS")
        _eiy_require(row["baseline_state"] in states and row["post_state"] in states
                     and row["reviewed"] is True, "ACQ_EIY_FIELD_STATE")
        refs = row["evidence_unit_sha256s"]
        _eiy_require(isinstance(refs, list) and all(ref in evidence_ids for ref in refs)
                     and (row["post_state"] == "unknown" or bool(refs)), "ACQ_EIY_FIELD_EVIDENCE")
        checked_fields.append({"field_id": _eiy_id(row["field_id"], "ACQ_EIY_FIELD_ID"),
                               "baseline_state": row["baseline_state"], "post_state": row["post_state"],
                               "evidence_unit_sha256s": sorted(refs)})
    precision = admission["precision"]
    _eiy_exact(precision, {"status", "supported_numerator", "judged_denominator", "pooled_total",
                           "unjudged_unknown_count"}, "ACQ_EIY_PRECISION_FIELDS")
    if precision["status"] == "known":
        vals = [precision[k] for k in ("supported_numerator", "judged_denominator", "pooled_total",
                                      "unjudged_unknown_count")]
        _eiy_require(all(type(x) is int and x >= 0 for x in vals)
                     and precision["judged_denominator"] > 0
                     and precision["judged_denominator"] + precision["unjudged_unknown_count"]
                         == precision["pooled_total"]
                     and precision["supported_numerator"] <= precision["judged_denominator"],
                     "ACQ_EIY_PRECISION_COUNTS")
    else:
        _eiy_require(precision["status"] == "unavailable", "ACQ_EIY_PRECISION_STATUS")
    freshness = admission["freshness"]
    _eiy_exact(freshness, {"targets"}, "ACQ_EIY_FRESHNESS_FIELDS")
    targets = []
    for target in freshness["targets"]:
        _eiy_exact(target, {"target_id", "target_sha256", "availability_status", "exposure_status",
                            "on_time", "lag_seconds"}, "ACQ_EIY_TARGET_FIELDS")
        targets.append(dict(target))
    readiness = admission["financial_readiness"]
    _eiy_exact(readiness, {"status", "elements"}, "ACQ_EIY_READINESS_FIELDS")
    _eiy_require(readiness["status"] in {"known", "unavailable"}
                 and isinstance(readiness["elements"], list)
                 and (readiness["status"] != "known" or bool(readiness["elements"])),
                 "ACQ_EIY_READINESS_STATUS")
    for element in readiness["elements"]:
        _eiy_exact(element, {"element_id", "ready", "unknown_reason"}, "ACQ_EIY_ELEMENT_FIELDS")
    recovery = admission["recovery_opportunities"]
    _eiy_require(isinstance(recovery, list)
                 and all(isinstance(x, dict) and set(x) == {"opportunity_id", "classification",
                                                            "outcome_known_at_classification"}
                         and x["outcome_known_at_classification"] is False for x in recovery),
                 "ACQ_EIY_RECOVERY_CLASSIFICATION")
    return {"arm": name,
            "execution": {key: config[key] for key in ("experiment_id", "execution_id", "trace_id", "backend", "model_sha256", "effort",
                         "prompt_sha256", "tool_sha256", "safety_sha256", "catalog_sha256",
                         "taxonomy_sha256", "budget", "deadlines", "cache_namespace", "order_index")},
            "canonical_units": checked_units, "required_fields": checked_fields,
            "precision": precision, "freshness": {"targets": targets},
            "financial_readiness": readiness,
            "hard_failures": sorted(set(admission["hard_failures"])),
            "trace_accounting": {"complete_chains": verdict["complete_chains"],
                                  "credited_units": verdict["credited_units"]}}


def check_eiy_matched_case(request):
    """Rejected v2 entry point retained only for deterministic migration failure."""
    raise SourceError("EIY_SELF_ASSERTED_BUNDLE_DISABLED")
    try:
        req = request if isinstance(request, CheckedEiyCaseRequest) else CheckedEiyCaseRequest.from_mapping(request)
    except ContractError as exc:
        raise SourceError(str(exc)) from None
    case = read(req.case_contract_ref)
    _eiy_exact(case, {"schema_version", "evaluation_id", "case_id", "issuer_id", "subject", "window_id",
                      "cutoff", "evidence_level", "split", "arm_order"}, "ACQ_EIY_CASE_FIELDS")
    _eiy_require(case["schema_version"] == "information-yield-case-contract-2"
                 and case["evaluation_id"] == req.evaluation_id
                 and case["evidence_level"] in {"development", "confirmation"}
                 and case["split"] in {"development", "untouched"}
                 and case["arm_order"] in [["B0", "F"], ["F", "B0"]], "ACQ_EIY_CASE_INVALID")
    for key in ("evaluation_id","case_id","issuer_id","subject","window_id"):
        _eiy_id(case[key], "ACQ_EIY_CASE_ID")
    _eiy_require(isinstance(case["cutoff"],str) and 0<len(case["cutoff"])<=64 and "<" not in case["cutoff"] and ">" not in case["cutoff"], "ACQ_EIY_CASE_CUTOFF")
    policy = read(req.metric_policy_ref)
    _eiy_require(policy.get("schema_version") == "information-yield-metric-policy-1"
                 and policy.get("source_contract_sha256")
                     == "72f93cfac1c8e47084fd3c86b6d5cdb4ba7e4e8b11df90f20895fa1166b1ce9f",
                 "ACQ_EIY_POLICY_INVALID")
    metadata = {}
    values = {}
    for name in ("case_roster_ref", "allocation_ref", "baseline_ref", "reference_set_ref",
                 "required_fields_ref", "freshness_targets_ref", "financial_element_roster_ref",
                 "custody_ref"):
        ref = getattr(req, name); value = read(ref)
        _eiy_require(isinstance(value, dict) and value.get("schema_version"), "ACQ_EIY_CUSTODY_INVALID")
        metadata[name.removesuffix("_ref") + "_sha256"] = ref["sha256"]
        values[name.removesuffix("_ref")] = value
    def hashes(value, key):
        rows=value.get(key); _eiy_require(isinstance(rows,list) and len(rows)==len(set(rows)) and all(isinstance(x,str) and len(x)==64 for x in rows), "ACQ_EIY_ROSTER_INVALID"); return sorted(rows)
    def ids(value, key):
        rows=value.get(key); _eiy_require(isinstance(rows,list) and len(rows)==len(set(rows)), "ACQ_EIY_ROSTER_INVALID"); return sorted(_eiy_id(x,"ACQ_EIY_ROSTER_INVALID") for x in rows)
    baseline_keys=hashes(values["baseline"],"canonical_key_sha256s")
    reference_keys=hashes(values["reference_set"],"canonical_key_sha256s")
    required_ids=ids(values["required_fields"],"field_ids")
    freshness_ids=ids(values["freshness_targets"],"target_ids")
    financial_ids=ids(values["financial_element_roster"],"element_ids")
    arms = {name: _checked_eiy_arm(name, req.arms[name], case) for name in ("B0", "F")}
    for arm in arms.values():
        _eiy_require(not ({u["canonical_key_sha256"] for u in arm["canonical_units"]} & set(baseline_keys)), "ACQ_EIY_BASELINE_CONFLICT")
        _eiy_require({f["field_id"] for f in arm["required_fields"]} == set(required_ids), "ACQ_EIY_FIELD_ROSTER")
        _eiy_require({t["target_id"] for t in arm["freshness"]["targets"]} == set(freshness_ids), "ACQ_EIY_FRESHNESS_ROSTER")
        _eiy_require({e["element_id"] for e in arm["financial_readiness"]["elements"]} == set(financial_ids), "ACQ_EIY_FINANCIAL_ROSTER")
    ignored={"experiment_id","execution_id","trace_id","cache_namespace","order_index"}
    matched = ({k:v for k,v in arms["B0"]["execution"].items() if k not in ignored}
               == {k:v for k,v in arms["F"]["execution"].items() if k not in ignored})
    _eiy_require(matched and arms["B0"]["execution"]["cache_namespace"]
                 != arms["F"]["execution"]["cache_namespace"], "ACQ_EIY_PAIR_MISMATCH")
    _eiy_require(all(arms[name]["execution"]["order_index"] == case["arm_order"].index(name)
                     for name in ("B0", "F")), "ACQ_EIY_ORDER_INVALID")
    hard = sorted(set(arms["B0"]["hard_failures"] + arms["F"]["hard_failures"]))
    complete = sum(arm["trace_accounting"]["complete_chains"] for arm in arms.values())
    credited = sum(arm["trace_accounting"]["credited_units"] for arm in arms.values())
    value = {"schema_version": EIY_MATCHED_CASE_VERSION, "checker_version": VERSION,
             "evaluation_id": req.evaluation_id, "case_id": case["case_id"],
             "issuer_id": case["issuer_id"], "subject": case["subject"], "window_id": case["window_id"],
             "cutoff": case["cutoff"], "evidence_level": case["evidence_level"],
             "split": case["split"], "metric_policy_sha256": req.metric_policy_ref["sha256"],
             **metadata, "baseline_canonical_key_sha256s": baseline_keys,
             "reference_canonical_key_sha256s": reference_keys, "required_field_ids": required_ids,
             "freshness_target_ids": freshness_ids, "financial_element_ids": financial_ids,
             "arm_order": case["arm_order"], "checker_status": "passed",
             "reason_codes": [], "arms": arms,
             "pair_custody": {"matched": True, "cache_isolated": True,
                              "recovery_preclassified": True},
             "hard_failures": hard,
             "trace_accounting": {"complete_chains": complete, "credited_units": credited}}
    value["bundle_sha256"] = digest(value)
    return value


def issue_eiy_matched_case(directory, *, request):
    """Rejected v2 publication entry point retained for deterministic failure."""
    raise SourceError("EIY_SELF_ASSERTED_BUNDLE_DISABLED")
