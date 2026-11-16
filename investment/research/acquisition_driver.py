"""Application-owned bridge between acquisition control and HostWeb.

The driver records each cross-component handoff before the next step is allowed.
It does not invoke a provider or certify semantic/economic support.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path

from investment.research.acquisition_review import (
    record_reviewer_decision,
    verify_reviewer_decision,
)
from investment.research.acquisition_runner import (
    HostedAcquisitionRunner,
    RunnerError,
    verify_dispatch_receipt,
)
from shared.job_runtime.service import atomic
from shared.research_sources.acquisition_validation import operation_identifier, question_identifier
from shared.research_sources.acquisition_contracts import ExactArguments
from shared.research_sources.artifacts import (
    SourceError,
    digest,
    private_path,
    read,
    require,
    save,
)


VERSION = "acquisition-driver-0.2.0"
_CAPTURE_STATES = {"captured", "unknown"}
_CAPTURE_IMPORT_STATES = {"invocation_started", "possibly_dispatched"}
_FINALIZABLE_STATES = {"controller_committed", "review_saved"}


class AcquisitionDriver:
    """Single-writer durable handoff ledger for one controller and HostWeb run."""

    def __init__(self, directory, *, controller, portal, experiment_id, execution_id, trace_id):
        self.directory = private_path(directory, create=True)
        self.head = self.directory / "state.json"
        self.controller = controller
        self.portal = portal
        identities = {
            "experiment_id": question_identifier(experiment_id, "ACQ_DRIVER_EXPERIMENT_ID"),
            "execution_id": question_identifier(execution_id, "ACQ_DRIVER_EXECUTION_ID"),
            "trace_id": question_identifier(trace_id, "ACQ_DRIVER_TRACE_ID"),
        }
        require(portal.config["execution_id"] == execution_id, "ACQ_DRIVER_EXECUTION_MISMATCH")
        with self._lock():
            if self.head.exists():
                require(read(self._head())["identities"] == identities, "ACQ_DRIVER_IDENTITY_CONFLICT")
            else:
                self._write({
                    "version": VERSION,
                    "identities": identities,
                    "operations": {},
                    "assessment_refs": [],
                    "unit_refs": [],
                    "review_refs": [],
                    "final_ref": None,
                })

    @contextmanager
    def _lock(self):
        fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SourceError("ACQ_DRIVER_BUSY") from None
            yield
        finally:
            os.close(fd)

    def _head(self):
        require(self.head.is_file() and not self.head.is_symlink()
                and self.head.stat().st_size <= 131072, "ACQ_DRIVER_STATE_INVALID")
        return json.loads(self.head.read_bytes())

    def _write(self, state):
        atomic(self.head, save(self.directory, state))

    def _active(self):
        state = read(self._head())
        require(state["final_ref"] is None, "ACQ_DRIVER_FINISHED")
        return state

    @staticmethod
    def _event(operation, name, **fields):
        operation["state"] = name
        operation["history"].append({"sequence": len(operation["history"]), "state": name, **fields})
        operation.update(fields)

    def reserve(self, proposal):
        """Reserve controller budget once and durably bind the exact proposal."""
        operation_id = proposal.get("operation_id") if isinstance(proposal, dict) else None
        operation_identifier(operation_id, "ACQ_DRIVER_OPERATION_ID")
        proposal_sha256 = digest(proposal)
        with self._lock():
            state = self._active()
            existing = state["operations"].get(operation_id)
            if existing is not None:
                require(existing["proposal_sha256"] == proposal_sha256, "ACQ_DRIVER_OPERATION_CONFLICT")
                return existing["controller_dispatch"]
            dispatch = self.controller.prepare(proposal)
            operation = {
                "operation_id": operation_id,
                "proposal_sha256": proposal_sha256,
                "proposal": proposal,
                "controller_dispatch": dispatch,
                "state": "reserved",
                "history": [{"sequence": 0, "state": "reserved",
                             "controller_decision_ref": dispatch["decision_ref"]}],
                "host_result": None,
                "controller_result": None,
                "assessment_refs": [],
                "unit_refs": [],
                "review_refs": [],
            }
            state["operations"][operation_id] = operation
            self._write(state)
            return dispatch

    def import_controller_reservation(self, proposal):
        """Import an already-committed controller reservation without calling prepare."""
        operation_id = proposal.get("operation_id") if isinstance(proposal, dict) else None
        operation_identifier(operation_id, "ACQ_DRIVER_OPERATION_ID")
        proposal_sha256 = digest(proposal)
        controller_state = read(self.controller._head())
        pending = controller_state.get("pending")
        require(pending is not None and all(pending.get(key) == value for key, value in proposal.items()),
                "ACQ_DRIVER_RESERVATION_NOT_COMMITTED")
        dispatch = {
            "operation_id": operation_id,
            "arguments": pending["arguments"],
            "requirement_ids": pending["question_ids"],
            "fallback_of": pending.get("fallback_of"),
            "decision_ref": pending["decision_ref"],
        }
        require(dispatch["decision_ref"] in controller_state["transition_refs"],
                "ACQ_DRIVER_RESERVATION_NOT_COMMITTED")
        with self._lock():
            state = self._active()
            existing = state["operations"].get(operation_id)
            if existing is not None:
                require(existing["proposal_sha256"] == proposal_sha256
                        and existing["controller_dispatch"] == dispatch,
                        "ACQ_DRIVER_OPERATION_CONFLICT")
                return dispatch
            state["operations"][operation_id] = {
                "operation_id": operation_id,
                "proposal_sha256": proposal_sha256,
                "proposal": proposal,
                "controller_dispatch": dispatch,
                "state": "reserved",
                "history": [{"sequence": 0, "state": "reserved",
                             "controller_decision_ref": dispatch["decision_ref"]}],
                "host_result": None,
                "controller_result": None,
                "assessment_refs": [],
                "unit_refs": [],
                "review_refs": [],
            }
            self._write(state)
            return dispatch

    def prepare_host(self, operation_id):
        """Create or recover the exact HostWeb intent without claiming dispatch."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "reserved", "ACQ_DRIVER_STATE")
            dispatch = operation["controller_dispatch"]
            prepared = self.portal.prepare(
                operation_id,
                dispatch["arguments"],
                fallback_of=dispatch.get("fallback_of"),
                requirement_ids=dispatch["requirement_ids"],
                alternate_descriptor=dispatch.get("alternate_descriptor"),
            )
            if prepared["status"] in {"dispatch", "pending"}:
                self._event(operation, "host_intent", host_intent_ref=prepared["intent_ref"])
            elif prepared["status"] == "cache_hit":
                host_result = {
                    "status": "returned", "code": None, "packet": prepared["packet"],
                    "operation_ref": None, "source_refs": [row["source_ref"] for row in prepared["packet"]["documents"]],
                }
                self._event(operation, "captured", host_result=host_result, cache_hit=True)
            else:
                raise SourceError("ACQ_DRIVER_RECONCILE_REQUIRED")
            self._write(state)
            return prepared

    def import_host_intent(self, operation_id, intent_ref):
        """Bind the exact HostWeb intent already committed by HostWeb."""
        intent = read(intent_ref)
        portal_state = read(self.portal._head())
        require(portal_state["operations"].get(operation_id) == intent_ref
                and intent.get("kind") == "host_web_intent"
                and intent.get("operation_id") == operation_id
                and intent.get("status") == "pending",
                "ACQ_DRIVER_HOST_INTENT_NOT_COMMITTED")
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            require(intent["arguments"] == operation["controller_dispatch"]["arguments"]
                    and intent["requirement_ids"] == operation["controller_dispatch"]["requirement_ids"],
                    "ACQ_DRIVER_HOST_INTENT_CONFLICT")
            if operation["state"] == "host_intent":
                require(operation["host_intent_ref"] == intent_ref,
                        "ACQ_DRIVER_HOST_INTENT_CONFLICT")
                return intent_ref
            require(operation["state"] == "reserved", "ACQ_DRIVER_STATE")
            self._event(operation, "host_intent", host_intent_ref=intent_ref)
            self._write(state)
            return intent_ref

    def claim_dispatch(self, operation_id):
        """Fence the external call; only this state permits capture."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            require(operation["state"] in {"host_intent", "definitely_not_dispatched"},
                    "ACQ_DRIVER_RECONCILE_REQUIRED")
            self._event(operation, "dispatch_claimed")
            self._write(state)
            return operation["controller_dispatch"]["arguments"]

    def record_invocation_started(self, operation_id):
        """Fence an invocation before provider entry; this never returns arguments."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "dispatch_claimed",
                    "ACQ_DRIVER_RECONCILE_REQUIRED")
            self._event(operation, "invocation_started")
            self._write(state)

    def record_possibly_dispatched(self, operation_id):
        """Persist a lost-callback fence which cannot authorize redispatch."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "invocation_started",
                    "ACQ_DRIVER_RECONCILE_REQUIRED")
            self._event(operation, "possibly_dispatched")
            self._write(state)

    def import_definitely_not_dispatched(self, operation_id, *, runner, dispatch_id):
        """Authorize a fresh claim only from the runner's validated durable journal."""
        require(isinstance(runner, HostedAcquisitionRunner),
                "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
        try:
            journal = list(runner.journal(dispatch_id))
        except Exception as error:
            raise SourceError("ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID") from None
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "dispatch_claimed",
                    "ACQ_DRIVER_RECONCILE_REQUIRED")
            arguments_sha256 = ExactArguments.from_mapping(
                operation["controller_dispatch"]["arguments"]).sha256
            require(bool(journal)
                    and all(row.get("dispatch_id") == dispatch_id
                            and row.get("sequence") == index
                            for index, row in enumerate(journal))
                    and journal[0].get("state") == "prepared"
                    and journal[0].get("arguments_sha256") == arguments_sha256
                    and journal[-1].get("state") == "definitely_not_dispatched"
                    and journal[-1].get("evidence_sha256"),
                    "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
            evidence_ref = save(self.directory, {
                "kind": "acquisition_dispatch_reconciliation",
                "version": VERSION,
                **state["identities"],
                "operation_id": operation_id,
                "dispatch_id": dispatch_id,
                "journal": journal,
            })
            self._event(operation, "definitely_not_dispatched", dispatch_evidence_ref=evidence_ref,
                        dispatch_id=dispatch_id)
            self._write(state)
            return evidence_ref

    def capture_host(self, operation_id, capture, *, runner, dispatch_id,
                     dispatch_ref=None):
        """Accept capture only after matching runner-owned invocation evidence."""
        require(isinstance(runner, HostedAcquisitionRunner),
                "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] in _CAPTURE_IMPORT_STATES,
                    "ACQ_DRIVER_CAPTURE_REPLAY")
            expected_hash = ExactArguments.from_mapping(
                operation["controller_dispatch"]["arguments"]).sha256
            try:
                binding = runner.dispatch_binding(dispatch_id)
                require(binding.get("execution_id") == state["identities"]["execution_id"]
                        and binding.get("operation_id") == operation_id
                        and binding.get("attempt_id") == f"{operation_id}:1"
                        and binding.get("dispatch_id") == dispatch_id
                        and binding.get("arguments_sha256") == expected_hash,
                        "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
                if capture.get("status") == "unknown":
                    require(operation["state"] == "possibly_dispatched"
                            and binding.get("state") == "possibly_dispatched"
                            and dispatch_ref is None,
                            "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
                else:
                    verified = verify_dispatch_receipt(dispatch_ref)
                    require(operation["state"] == "invocation_started"
                            and binding.get("state") == "captured"
                            and verified.get("dispatch_id") == dispatch_id
                            and verified.get("operation_id") == operation_id
                            and verified.get("execution_id") == state["identities"]["execution_id"]
                            and verified.get("arguments_sha256") == expected_hash
                            and verified.get("canonical_arguments") == ExactArguments.from_mapping(
                                capture.get("actual_arguments")).canonical_json,
                            "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
            except (RunnerError, SourceError, TypeError, ValueError):
                raise SourceError("ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID") from None
            try:
                result = self.portal.capture(operation_id, capture)
            except SourceError as error:
                if str(error) == "HOST_WEB_CAPTURE_REPLAY":
                    raise SourceError("ACQ_DRIVER_RECONCILE_REQUIRED") from None
                raise
            next_state = "unknown" if result["status"] == "unknown" else "captured"
            self._event(operation, next_state, host_result=result,
                        dispatch_id=dispatch_id, dispatch_ref=dispatch_ref)
            self._write(state)
            return result

    def import_host_capture(self, operation_id, operation_ref, *, runner,
                            dispatch_id, dispatch_ref):
        """Import HostWeb capture only when matching runner evidence is durable."""
        require(isinstance(runner, HostedAcquisitionRunner),
                "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
        try:
            verified_dispatch = verify_dispatch_receipt(dispatch_ref)
            binding = runner.dispatch_binding(dispatch_id)
        except (RunnerError, SourceError, TypeError, ValueError):
            raise SourceError("ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID") from None
        receipt = read(operation_ref)
        portal_state = read(self.portal._head())
        completed_ref = portal_state["operations"].get(operation_id)
        require(completed_ref is not None, "ACQ_DRIVER_HOST_CAPTURE_NOT_COMMITTED")
        completed = read(completed_ref)
        require(completed.get("operation_ref") == operation_ref
                and receipt.get("kind") == "acquisition_operation_receipt"
                and receipt.get("operation_id") == operation_id,
                "ACQ_DRIVER_HOST_CAPTURE_NOT_COMMITTED")
        status = {"success": "returned", "failed": "failed", "unknown": "unknown"}.get(receipt.get("status"))
        require(status is not None, "ACQ_DRIVER_HOST_CAPTURE_INVALID")
        source_refs = [ref for ref in portal_state.get("source_refs", [])
                       if ref["sha256"] in receipt.get("source_sha256s", [])]
        require({ref["sha256"] for ref in source_refs} == set(receipt.get("source_sha256s", [])),
                "ACQ_DRIVER_HOST_CAPTURE_INVALID")
        packet = {}
        if status == "returned" and receipt["operation"] == "open":
            packet = {"documents": [{
                "source_ref": ref,
                "url": read(ref)["source_url"],
                "text": read(read(ref)["text"], json_value=False).decode(),
            } for ref in source_refs]}
        elif status == "returned" and receipt["operation"] == "search":
            require(len(source_refs) == 1, "ACQ_DRIVER_HOST_CAPTURE_INVALID")
            packet = {"urls": read(source_refs[0]).get("candidates", [])}
        result = {
            "status": status,
            "code": receipt.get("code"),
            "operation_ref": operation_ref,
            "source_refs": source_refs,
            "packet": packet,
            "warning": None,
        }
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            expected_hash = ExactArguments.from_mapping(
                operation["controller_dispatch"]["arguments"]).sha256
            if operation["state"] in _CAPTURE_STATES:
                require(operation["host_result"] == result, "ACQ_DRIVER_HOST_CAPTURE_CONFLICT")
                return result
            require(operation["state"] == "invocation_started"
                    and binding.get("state") == "captured"
                    and binding.get("execution_id") == state["identities"]["execution_id"]
                    and binding.get("operation_id") == operation_id
                    and binding.get("dispatch_id") == dispatch_id
                    and binding.get("arguments_sha256") == expected_hash
                    and verified_dispatch.get("dispatch_id") == dispatch_id
                    and verified_dispatch.get("operation_id") == operation_id
                    and verified_dispatch.get("arguments_sha256") == expected_hash,
                    "ACQ_DRIVER_DISPATCH_EVIDENCE_INVALID")
            self._event(operation, "unknown" if status == "unknown" else "captured",
                        host_result=result)
            self._write(state)
            return result

    def commit_controller(self, operation_id, assessments=()):
        """Commit HostWeb's durable result to the deterministic controller."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] in _CAPTURE_STATES, "ACQ_DRIVER_STATE")
            result = operation["host_result"]
            rows = list(assessments)
            capture = {
                "status": result["status"],
                "code": result.get("code"),
                "packet": result.get("packet", {}),
                "assessments": rows,
            }
            controller_result = self.controller.capture(operation_id, capture)
            self._event(operation, "controller_committed",
                        controller_result=controller_result, assessments=rows)
            recovery = controller_result.get("next_dispatch")
            if recovery:
                recovery_id = recovery["operation_id"]
                require(recovery_id not in state["operations"], "ACQ_DRIVER_RECOVERY_CONFLICT")
                state["operations"][recovery_id] = {
                    "operation_id": recovery_id,
                    "proposal_sha256": None,
                    "proposal": None,
                    "controller_dispatch": recovery,
                    "state": "reserved",
                    "history": [{"sequence": 0, "state": "reserved",
                                 "controller_decision_ref": controller_result["decision_ref"]}],
                    "host_result": None,
                    "controller_result": None,
                    "assessment_refs": [],
                    "unit_refs": [],
                    "review_refs": [],
                }
            self._write(state)
            return controller_result

    def import_controller_capture(self, operation_id, decision_ref, assessments=()):
        """Import an already-committed controller transition and queue recovery once."""
        transition = read(decision_ref)
        controller_state = read(self.controller._head())
        require(decision_ref in controller_state["transition_refs"]
                and transition.get("kind") == "acquisition_decision"
                and transition.get("decision") == "capture"
                and transition.get("operation_id") == operation_id,
                "ACQ_DRIVER_CONTROLLER_CAPTURE_NOT_COMMITTED")
        rows = list(assessments)
        require(isinstance(rows, list), "ACQ_DRIVER_ASSESSMENT_INVALID")
        controller_result = {
            "state_ref": self.controller._head(),
            "decision_ref": decision_ref,
            "next_dispatch": transition.get("next_dispatch"),
        }
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            if operation["state"] == "controller_committed":
                require(operation["controller_result"]["decision_ref"] == decision_ref
                        and operation.get("assessments", []) == rows,
                        "ACQ_DRIVER_CONTROLLER_CAPTURE_CONFLICT")
                return operation["controller_result"]
            require(operation["state"] in _CAPTURE_STATES, "ACQ_DRIVER_STATE")
            documents = operation["host_result"].get("packet", {}).get("documents", [])
            for row in rows:
                require(isinstance(row, dict)
                        and set(row) == {"question_id", "quote", "disposition"}
                        and row["question_id"] in transition["question_ids"]
                        and row["disposition"] in {"candidate_support", "not_supporting"}
                        and len(documents) == 1 and row["quote"] in documents[0]["text"],
                        "ACQ_DRIVER_ASSESSMENT_INVALID")
            self._event(operation, "controller_committed", controller_result=controller_result,
                        assessments=rows)
            recovery = controller_result.get("next_dispatch")
            if recovery:
                recovery_id = recovery["operation_id"]
                existing = state["operations"].get(recovery_id)
                if existing is not None:
                    require(existing["controller_dispatch"] == recovery,
                            "ACQ_DRIVER_RECOVERY_CONFLICT")
                else:
                    state["operations"][recovery_id] = {
                        "operation_id": recovery_id,
                        "proposal_sha256": None,
                        "proposal": None,
                        "controller_dispatch": recovery,
                        "state": "reserved",
                        "history": [{"sequence": 0, "state": "reserved",
                                     "controller_decision_ref": decision_ref}],
                        "host_result": None,
                        "controller_result": None,
                        "assessment_refs": [],
                        "unit_refs": [],
                        "review_refs": [],
                    }
            self._write(state)
            return controller_result

    def save_assessments(self, operation_id, *, assessor_version):
        """Persist quote-bound provisional assessments after controller admission."""
        require(isinstance(assessor_version, str) and assessor_version,
                "ACQ_DRIVER_ASSESSOR_VERSION")
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "controller_committed",
                    "ACQ_DRIVER_STATE")
            rows = operation.get("assessments", [])
            documents = operation["host_result"].get("packet", {}).get("documents", [])
            require(len(documents) == 1 and rows, "ACQ_DRIVER_ASSESSMENT_REQUIRED")
            document = documents[0]
            source_ref = document["source_ref"]
            source = read(source_ref)
            refs = []
            for index, row in enumerate(rows):
                require(row["quote"] in document["text"], "ACQ_DRIVER_QUOTE_MISMATCH")
                artifact = {
                    "kind": "acquisition_quote_assessment",
                    "version": VERSION,
                    **state["identities"],
                    "assessment_id": digest([state["identities"], operation_id, index, row]),
                    "operation_id": operation_id,
                    "attempt_id": f"{operation_id}:1",
                    "question_id": row["question_id"],
                    "source_ref": source_ref,
                    "source_sha256": source_ref["sha256"],
                    "source_version": source["source_version"],
                    "raw_sha256": source["raw"]["sha256"],
                    "text_sha256": source["text"]["sha256"],
                    "quote": row["quote"],
                    "disposition": row["disposition"],
                    "assessor_version": assessor_version,
                    "assessment_author_id": assessor_version,
                    "cutoff": self.portal.config["cutoff"],
                    "screened_at": read(operation["host_result"]["operation_ref"])["finished_at"]
                        if operation["host_result"].get("operation_ref") else None,
                }
                refs.append(save(self.directory, artifact))
            operation["assessment_refs"] = refs
            state["assessment_refs"].extend(refs)
            self._event(operation, "assessment_saved", assessment_refs=refs)
            self._write(state)
            return refs

    def import_assessments(self, operation_id, assessment_refs):
        """Import exact assessment artifacts left durable before a driver update."""
        refs = list(assessment_refs)
        require(bool(refs), "ACQ_DRIVER_ASSESSMENT_REQUIRED")
        rows = [read(ref) for ref in refs]
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            if operation["state"] == "assessment_saved":
                require(operation["assessment_refs"] == refs, "ACQ_DRIVER_ASSESSMENT_CONFLICT")
                return refs
            require(operation["state"] == "controller_committed", "ACQ_DRIVER_STATE")
            documents = operation["host_result"].get("packet", {}).get("documents", [])
            require(len(documents) == 1, "ACQ_DRIVER_ASSESSMENT_REQUIRED")
            committed_rows = operation.get("assessments", [])
            require(len(rows) == len(committed_rows), "ACQ_DRIVER_ASSESSMENT_INVALID")
            source = read(documents[0]["source_ref"])
            for index, (row, committed) in enumerate(zip(rows, committed_rows)):
                require(row.get("kind") == "acquisition_quote_assessment"
                        and row.get("version") == VERSION
                        and row.get("operation_id") == operation_id
                        and all(row.get(key) == value for key, value in state["identities"].items())
                        and row.get("assessment_id") == digest(
                            [state["identities"], operation_id, index, committed])
                        and row.get("question_id") == committed["question_id"]
                        and row.get("quote") == committed["quote"]
                        and row.get("disposition") == committed["disposition"]
                        and row.get("source_ref") == documents[0]["source_ref"]
                        and row.get("source_sha256") == documents[0]["source_ref"]["sha256"]
                        and row.get("raw_sha256") == source["raw"]["sha256"]
                        and row.get("text_sha256") == source["text"]["sha256"]
                        and isinstance(row.get("assessment_author_id"), str)
                        and row.get("assessment_author_id") == row.get("assessor_version"),
                        "ACQ_DRIVER_ASSESSMENT_INVALID")
            operation["assessment_refs"] = refs
            for ref in refs:
                if ref not in state["assessment_refs"]:
                    state["assessment_refs"].append(ref)
            self._event(operation, "assessment_saved", assessment_refs=refs)
            self._write(state)
            return refs

    def attach_units(self, operation_id):
        """Attach candidate units without converting provisional support to truth."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "assessment_saved",
                    "ACQ_DRIVER_STATE")
            refs = []
            for assessment_ref in operation["assessment_refs"]:
                assessment = read(assessment_ref)
                if assessment["disposition"] != "candidate_support":
                    continue
                unit = {
                    "kind": "acquisition_candidate_unit",
                    "version": VERSION,
                    **state["identities"],
                    "unit_id": digest([assessment["assessment_id"], "candidate-unit"]),
                    "question_id": assessment["question_id"],
                    "assessment_ref": assessment_ref,
                    "source_ref": assessment["source_ref"],
                    "quote": assessment["quote"],
                    "status": "candidate_support_not_semantic_admission",
                }
                refs.append(save(self.directory, unit))
            operation["unit_refs"] = refs
            state["unit_refs"].extend(refs)
            self._event(operation, "unit_attached", unit_refs=refs)
            self._write(state)
            return refs

    def import_units(self, operation_id, unit_refs):
        """Import exact candidate units left durable before a driver update."""
        refs = list(unit_refs)
        rows = [read(ref) for ref in refs]
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            if operation["state"] == "unit_attached":
                require(operation["unit_refs"] == refs, "ACQ_DRIVER_UNIT_CONFLICT")
                return refs
            require(operation["state"] == "assessment_saved", "ACQ_DRIVER_STATE")
            assessments = {ref["sha256"]: ref for ref in operation["assessment_refs"]}
            expected = [ref for ref in operation["assessment_refs"]
                        if read(ref)["disposition"] == "candidate_support"]
            require(len(rows) == len(expected), "ACQ_DRIVER_UNIT_INVALID")
            for row in rows:
                assessment_ref = row.get("assessment_ref")
                assessment = read(assessment_ref) if isinstance(assessment_ref, dict) else {}
                require(row.get("kind") == "acquisition_candidate_unit"
                        and row.get("version") == VERSION
                        and all(row.get(key) == value for key, value in state["identities"].items())
                        and isinstance(assessment_ref, dict)
                        and assessment_ref.get("sha256") in assessments
                        and row.get("unit_id") == digest([assessment.get("assessment_id"), "candidate-unit"])
                        and row.get("question_id") == assessment.get("question_id")
                        and row.get("source_ref") == assessment.get("source_ref")
                        and row.get("quote") == assessment.get("quote")
                        and row.get("status") == "candidate_support_not_semantic_admission",
                        "ACQ_DRIVER_UNIT_INVALID")
            operation["unit_refs"] = refs
            for ref in refs:
                if ref not in state["unit_refs"]:
                    state["unit_refs"].append(ref)
            self._event(operation, "unit_attached", unit_refs=refs)
            self._write(state)
            return refs

    def save_review(self, operation_id, *, reviewer_id, assessment_author_id,
                    live_operator_id, disposition, checks, reason):
        """Persist one canonical, independently verified reviewer decision."""
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None and operation["state"] == "unit_attached"
                    and len(operation["assessment_refs"]) == len(operation["unit_refs"]) == 1,
                    "ACQ_DRIVER_REVIEW_REQUIRED")
            assessment_ref = operation["assessment_refs"][0]
            unit_ref = operation["unit_refs"][0]
            assessment = read(assessment_ref)
            require(assessment.get("assessment_author_id") == assessment_author_id,
                    "ACQ_DRIVER_REVIEW_AUTHOR_MISMATCH")
            ref = record_reviewer_decision(
                self.directory,
                assessment_ref=assessment_ref,
                unit_ref=unit_ref,
                reviewer_id=reviewer_id,
                assessment_author_id=assessment_author_id,
                operator_id=live_operator_id,
                disposition=disposition,
                checks=checks,
                reason=reason,
            )
            operation["review_refs"] = [ref]
            state.setdefault("review_refs", []).append(ref)
            self._event(operation, "review_saved", review_refs=[ref])
            self._write(state)
            return ref

    def import_reviews(self, operation_id, review_refs):
        """Import exact reviewer decisions left durable before a driver update."""
        refs = list(review_refs)
        require(bool(refs), "ACQ_DRIVER_REVIEW_REQUIRED")
        rows = [read(ref) for ref in refs]
        with self._lock():
            state = self._active()
            operation = state["operations"].get(operation_id)
            require(operation is not None, "ACQ_DRIVER_OPERATION_UNKNOWN")
            if operation["state"] == "review_saved":
                require(operation["review_refs"] == refs, "ACQ_DRIVER_REVIEW_CONFLICT")
                return refs
            require(operation["state"] == "unit_attached" and len(refs) == len(operation["unit_refs"]),
                    "ACQ_DRIVER_REVIEW_REQUIRED")
            assessment_refs = {ref["sha256"]: ref for ref in operation["assessment_refs"]}
            unit_refs = {ref["sha256"]: ref for ref in operation["unit_refs"]}
            for ref in refs:
                try:
                    row = verify_reviewer_decision(ref)
                except (KeyError, OSError, TypeError, ValueError, SourceError):
                    raise SourceError("ACQ_DRIVER_REVIEW_INVALID") from None
                binding = row.get("binding", {})
                assessment_ref = binding.get("assessment_ref")
                unit_ref = binding.get("unit_ref")
                require(isinstance(assessment_ref, dict) and isinstance(unit_ref, dict)
                        and assessment_ref.get("sha256") in assessment_refs
                        and unit_ref.get("sha256") in unit_refs
                        and all(row.get(key) == value for key, value in state["identities"].items()),
                        "ACQ_DRIVER_REVIEW_INVALID")
            operation["review_refs"] = refs
            for ref in refs:
                if ref not in state.setdefault("review_refs", []):
                    state["review_refs"].append(ref)
            self._event(operation, "review_saved", review_refs=refs)
            self._write(state)
            return refs

    def finish(self):
        """Finalize both components only after every handoff is terminal."""
        with self._lock():
            state = read(self._head())
            if state["final_ref"]:
                return {"final_ref": state["final_ref"], "final": read(state["final_ref"])}
            require(state["operations"] and all(
                row["state"] in _FINALIZABLE_STATES
                and not (row["state"] == "controller_committed" and row.get("assessments"))
                for row in state["operations"].values()), "ACQ_DRIVER_NOT_TERMINAL")
            controller = self.controller.finish()
            host = self.portal.finish(state["unit_refs"])
            for operation in state["operations"].values():
                self._event(operation, "finalized")
            final = {
                "kind": "acquisition_driver_run",
                "version": VERSION,
                **state["identities"],
                "controller_summary_ref": controller["summary_ref"],
                "host_run_ref": host["run_ref"],
                "assessment_refs": state["assessment_refs"],
                "unit_refs": state["unit_refs"],
                "review_refs": state.get("review_refs", []),
                "operation_states": {key: value["history"] for key, value in state["operations"].items()},
                "scope": "synthetic_or_cooperative_pipeline_not_live_quality_or_alpha",
            }
            final_ref = save(self.directory, final)
            state["final_ref"] = final_ref
            self._write(state)
            return {"final_ref": final_ref, "final": final}

    def reconcile_finalization(self):
        """Resume partial component finalization; component finishes are idempotent."""
        return self.finish()
