"""Deterministic control around agent-proposed hosted-web acquisition.

The agent proposes one search/open at a time. This module owns admission, budgets,
deduplication, typed recovery, structural post-fetch checks and stopping. It does
not decide whether a quotation is economically important or semantically proves
a research claim; those remain separately reviewed agent/evaluation decisions.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from shared.job_runtime.service import atomic
from shared.research_sources.acquisition_contracts import (
    AlternateDescriptor,
    AlternateRelationship,
    ExactArguments,
    FailureCode,
    RepresentationKind,
    classify_failure,
    fallback_allowed,
)
from shared.research_sources.acquisition_validation import (
    public_https_url,
    question_identifier,
    validate_dispatch,
)
from shared.research_sources.artifacts import (
    SourceError,
    digest,
    private_path,
    read,
    require,
    save,
)

VERSION = "acquisition-orchestration-0.3.0"
FAILURE_CODES = {code.value for code in FailureCode}


def _alternate(value):
    """Validate and normalize one frozen alternate descriptor."""
    require(isinstance(value, dict) and set(value) == {
        "representation_kind", "exact_arguments", "source_role", "required_capability",
        "required_access_level", "canonical_disclosure_id", "relationship_to_primary",
        "semantic_equivalence_rationale", "permitted_trigger_codes", "budget_cost",
    }, "ACQ_ALTERNATE_INVALID")
    try:
        descriptor = AlternateDescriptor(
            representation_kind=RepresentationKind(value["representation_kind"]),
            exact_arguments=ExactArguments.from_mapping(value["exact_arguments"]),
            source_role=value["source_role"],
            required_capability=value["required_capability"],
            required_access_level=value["required_access_level"],
            canonical_disclosure_id=value["canonical_disclosure_id"],
            relationship_to_primary=AlternateRelationship(value["relationship_to_primary"]),
            semantic_equivalence_rationale=value["semantic_equivalence_rationale"],
            permitted_trigger_codes=frozenset(FailureCode(code) for code in value["permitted_trigger_codes"]),
            budget_cost=value["budget_cost"],
        )
    except (TypeError, ValueError) as error:
        raise SourceError("ACQ_ALTERNATE_INVALID") from error
    arguments = descriptor.exact_arguments.to_dict()
    operation, _, item = _operation(arguments)
    require(operation == "open" and descriptor.budget_cost == 1, "ACQ_ALTERNATE_INVALID")
    return json.loads(json.dumps({**value, "exact_arguments": arguments,
        "permitted_trigger_codes": sorted(code.value for code in descriptor.permitted_trigger_codes)},
        sort_keys=True))


def _url(value):
    return public_https_url(value, "ACQ_URL_INVALID")


def classify_native_failure(code, raw_text=""):
    """Accept only the closed structured code; raw provider text is never a classifier."""
    require(isinstance(code, str) and isinstance(raw_text, str), "ACQ_FAILURE_INVALID")
    try:
        return classify_failure(code).code.value
    except (TypeError, ValueError) as error:
        raise SourceError("ACQ_FAILURE_CODE_INVALID") from error


def compile_prefetch_manifest(plan_ref, directory, *, search_items, open_items,
                              provider_items, reserve_provider_items=2):
    """Project a compiled question plan into an executable, frozen fetch list."""
    plan = read(plan_ref)
    require(plan.get("scope") == "retrieval_plan_only", "ACQ_PLAN_SCOPE")
    budget = {
        "search_items": search_items,
        "open_items": open_items,
        "provider_items": provider_items,
        "reserve_provider_items": reserve_provider_items,
    }
    require(all(type(value) is int and value >= 0 for value in budget.values()), "ACQ_BUDGET_INVALID")
    require(provider_items >= reserve_provider_items, "ACQ_RESERVE_INVALID")
    rows = []
    for question in plan["proposal"]["questions"]:
        rows.append({key: question[key] for key in (
            "id", "facet", "question", "evidence_to_seek", "source_roles",
            "capability_ids", "depends_on", "priority", "stop_rule"
        )})
    require(rows and len({row["id"] for row in rows}) == len(rows), "ACQ_QUESTION_INVALID")
    for row in rows:
        question_identifier(row["id"], "ACQ_QUESTION_INVALID")
    manifest = {
        "version": VERSION,
        "plan_ref": plan_ref,
        "context_ref": plan["context_ref"],
        "questions": rows,
        "budget": budget,
        "policy": {
            "proposal_owner": "agent",
            "admission_accounting_retry_stop_owner": "deterministic_controller",
            "semantic_support_owner": "separate_reviewer",
            "same_failed_operation_retry": False,
            "max_alternate_urls_per_open": 3,
        },
        "scope": "prefetch_manifest_not_retrieval_or_semantic_support",
    }
    return save(directory, manifest)


def _operation(arguments):
    require(isinstance(arguments, dict) and set(arguments) <= {"search_query", "open", "find", "response_length"},
            "ACQ_ARGUMENTS_INVALID")
    keys = [key for key in ("search_query", "open", "find") if key in arguments]
    require(len(keys) == 1 and arguments.get("response_length", "long") in {"short", "medium", "long"},
            "ACQ_ARGUMENTS_INVALID")
    key = keys[0]
    items = arguments[key]
    require(isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict),
            "ACQ_ONE_ITEM_AT_A_TIME")
    if key == "search_query":
        require(set(items[0]) <= {"q", "domains", "recency"} and isinstance(items[0].get("q"), str)
                and 0 < len(items[0]["q"]) <= 1000, "ACQ_QUERY_INVALID")
        return "search", key, items[0]
    if key == "open":
        require(set(items[0]) <= {"ref_id", "lineno"} and "ref_id" in items[0], "ACQ_OPEN_INVALID")
        _url(items[0]["ref_id"])
        return "open", key, items[0]
    require(set(items[0]) == {"ref_id", "pattern"} and isinstance(items[0]["pattern"], str)
            and 0 < len(items[0]["pattern"]) <= 400, "ACQ_FIND_INVALID")
    _url(items[0]["ref_id"])
    return "open", key, items[0]


class AcquisitionController:
    """Single-writer deterministic state machine for cooperative HostWeb calls."""

    def __init__(self, directory, *, manifest_ref=None):
        self.directory = private_path(directory, create=True)
        self.head = self.directory / "state.json"
        if manifest_ref is not None:
            manifest = read(manifest_ref)
            require(manifest.get("version") == VERSION, "ACQ_MANIFEST_VERSION")
            with self._lock():
                if self.head.exists():
                    require(read(self._head())["manifest_ref"]["sha256"] == manifest_ref["sha256"],
                            "ACQ_MANIFEST_CONFLICT")
                else:
                    questions = {row["id"]: {
                        "facet": row["facet"],
                        "priority": row["priority"],
                        "status": "unresolved",
                        "attempts": 0,
                        "source_refs": [],
                        "gaps": [],
                    } for row in manifest["questions"]}
                    self._write({
                        "version": VERSION,
                        "manifest_ref": manifest_ref,
                        "questions": questions,
                        "usage": {"search_items": 0, "open_items": 0, "provider_items": 0},
                        "seen_fingerprints": [],
                        "failed_urls": [],
                        "pending": None,
                        "queued_recovery": None,
                        "transition_refs": [],
                        "finished_ref": None,
                    })
        self.state = read(self._head())
        self.manifest = read(self.state["manifest_ref"])

    @contextmanager
    def _lock(self):
        fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SourceError("ACQ_BUSY") from None
            yield
        finally:
            os.close(fd)

    def _head(self):
        require(self.head.is_file() and not self.head.is_symlink() and self.head.stat().st_size <= 8192,
                "ACQ_STATE_INVALID")
        return json.loads(self.head.read_bytes())

    def _write(self, state):
        atomic(self.head, save(self.directory, state))

    def _active(self):
        state = read(self._head())
        require(state["finished_ref"] is None, "ACQ_FINISHED")
        return state

    def _question_rows(self):
        return {row["id"]: row for row in self.manifest["questions"]}

    def _reserve_allows(self, state, question_ids, cost):
        priorities = {self._question_rows()[qid]["priority"] for qid in question_ids}
        if priorities != {"required"}:
            remaining = self.manifest["budget"]["provider_items"] - state["usage"]["provider_items"] - cost
            require(remaining >= self.manifest["budget"]["reserve_provider_items"], "ACQ_REQUIRED_RESERVE")

    def prepare(self, proposal):
        """Admit one agent proposal and return exact HostWeb dispatch arguments."""
        required = {"operation_id", "question_ids", "source_role", "reason", "arguments", "alternates"}
        require(isinstance(proposal, dict) and set(proposal) == required, "ACQ_PROPOSAL_INVALID")
        require(isinstance(proposal["reason"], str) and 0 < len(proposal["reason"]) <= 1800,
                "ACQ_REASON_INVALID")
        question_ids = proposal["question_ids"]
        rows = self._question_rows()
        validate_dispatch(
            proposal["operation_id"], proposal["arguments"], questions=rows,
            question_ids=question_ids, source_role=proposal["source_role"], one_item=True,
        )
        operation, key, item = _operation(proposal["arguments"])
        require(isinstance(proposal["alternates"], list) and len(proposal["alternates"]) <= 3,
                "ACQ_ALTERNATE_INVALID")
        alternates = [_alternate(value) for value in proposal["alternates"]]
        require(all(value["source_role"] == proposal["source_role"]
                    and all(value["required_capability"] in rows[qid]["capability_ids"] for qid in question_ids)
                    for value in alternates), "ACQ_ALTERNATE_INCOMPATIBLE")
        require(len({value["canonical_disclosure_id"] for value in alternates}) <= 1,
                "ACQ_ALTERNATE_INCOMPATIBLE")
        fingerprints = [digest(value["exact_arguments"]) for value in alternates]
        require(len(set(fingerprints)) == len(fingerprints), "ACQ_ALTERNATE_INVALID")
        proposal = {**proposal, "alternates": alternates}
        if operation == "open":
            primary = item["ref_id"]
            require(all(value["exact_arguments"]["open"][0]["ref_id"] != primary for value in alternates),
                    "ACQ_ALTERNATE_INVALID")
            if urlsplit(primary).path.lower().endswith(".pdf"):
                require(bool(alternates), "ACQ_PDF_ALTERNATE_REQUIRED")
        else:
            require(not alternates, "ACQ_ALTERNATE_INVALID")
        fingerprint = digest(proposal["arguments"])
        with self._lock():
            state = self._active()
            if state["pending"] is not None:
                pending = state["pending"]
                prior = {name: pending[name] for name in required}
                require(prior == proposal, "ACQ_PENDING")
                return {"operation_id": proposal["operation_id"], "arguments": proposal["arguments"],
                        "requirement_ids": question_ids, "fallback_of": pending["fallback_of"],
                        "decision_ref": pending["decision_ref"]}
            require(state["queued_recovery"] is None, "ACQ_PENDING")
            require(proposal["operation_id"] not in {read(ref)["operation_id"] for ref in state["transition_refs"]},
                    "ACQ_OPERATION_REPLAY")
            require(fingerprint not in state["seen_fingerprints"], "ACQ_DUPLICATE_OPERATION")
            require(all(state["questions"][qid]["status"] not in {"blocked", "supported"} for qid in question_ids),
                    "ACQ_QUESTION_CLOSED")
            if operation == "open":
                require(item["ref_id"] not in state["failed_urls"], "ACQ_FAILED_URL_RETRY")
            budget = self.manifest["budget"]
            require(state["usage"][operation + "_items"] + 1 <= budget[operation + "_items"]
                    and state["usage"]["provider_items"] + 1 <= budget["provider_items"], "ACQ_BUDGET")
            self._reserve_allows(state, question_ids, 1)
            state["usage"][operation + "_items"] += 1
            state["usage"]["provider_items"] += 1
            state["seen_fingerprints"].append(fingerprint)
            transition = save(self.directory, {"kind": "acquisition_decision", "decision": "admit",
                "operation_id": proposal["operation_id"], "question_ids": question_ids,
                "source_role": proposal["source_role"], "reason": proposal["reason"],
                "arguments_sha256": fingerprint, "usage_after": state["usage"]})
            state["pending"] = {**proposal, "operation": operation, "native_key": key, "fingerprint": fingerprint,
                                "fallback_of": None, "fallback_index": 0, "decision_ref": transition}
            state["transition_refs"].append(transition)
            self._write(state)
        return {"operation_id": proposal["operation_id"], "arguments": proposal["arguments"],
                "requirement_ids": question_ids, "fallback_of": None, "decision_ref": transition}

    def _queue_fallback(self, state, pending, failure):
        require(fallback_allowed(failure, unparseable_predeclared=True), "ACQ_FALLBACK_FORBIDDEN")
        remaining = [descriptor for descriptor in pending["alternates"]
                     if failure in descriptor["permitted_trigger_codes"]
                     and descriptor["exact_arguments"]["open"][0]["ref_id"] not in state["failed_urls"]
                     and digest(descriptor["exact_arguments"]) not in state["seen_fingerprints"]]
        budget = self.manifest["budget"]
        priorities = {self._question_rows()[qid]["priority"] for qid in pending["question_ids"]}
        reserve_blocked = priorities != {"required"} and (
            budget["provider_items"] - state["usage"]["provider_items"] - 1
            < budget["reserve_provider_items"]
        )
        if not remaining or reserve_blocked or state["usage"]["open_items"] >= budget["open_items"] \
                or state["usage"]["provider_items"] >= budget["provider_items"]:
            for qid in pending["question_ids"]:
                state["questions"][qid]["status"] = "blocked"
                state["questions"][qid]["gaps"].append(failure)
            return None
        descriptor = remaining[0]
        index = pending["fallback_index"] + 1
        operation_id = (pending["operation_id"][:52] + f"-fallback-{index}")[:64]
        arguments = descriptor["exact_arguments"]
        fingerprint = digest(arguments)
        state["usage"]["open_items"] += 1
        state["usage"]["provider_items"] += 1
        state["seen_fingerprints"].append(fingerprint)
        queued = {**pending, "operation_id": operation_id, "arguments": arguments,
                  "fingerprint": fingerprint, "fallback_of": pending["operation_id"],
                  "fallback_index": index, "alternates": remaining[1:],
                  "alternate_descriptor": descriptor}
        state["pending"] = queued
        return {"operation_id": operation_id, "arguments": arguments,
                "requirement_ids": pending["question_ids"], "fallback_of": pending["operation_id"],
                "alternate_descriptor": descriptor}

    def capture(self, operation_id, capture):
        """Consume HostWeb output, validate handoff and deterministically recover."""
        allowed = {"status", "code", "packet", "raw_text", "assessments"}
        require(isinstance(capture, dict) and set(capture) <= allowed and capture.get("status") in {"returned", "failed", "unknown"},
                "ACQ_CAPTURE_INVALID")
        with self._lock():
            state = self._active()
            pending = state["pending"]
            require(pending is not None and pending["operation_id"] == operation_id, "ACQ_CAPTURE_MISMATCH")
            state["pending"] = None
            for qid in pending["question_ids"]:
                state["questions"][qid]["attempts"] += 1
            failure = classify_native_failure(capture.get("code") or "HOST_WEB_BODY_UNPARSEABLE",
                                              capture.get("raw_text", ""))
            next_dispatch = None
            if capture["status"] != "returned":
                require(failure in FAILURE_CODES, "ACQ_FAILURE_CODE_INVALID")
                if pending["operation"] == "open":
                    state["failed_urls"].append(pending["arguments"][pending["native_key"]][0]["ref_id"])
                if fallback_allowed(failure, unparseable_predeclared=True):
                    next_dispatch = self._queue_fallback(state, pending, failure)
                else:
                    for qid in pending["question_ids"]:
                        state["questions"][qid]["status"] = "blocked"
                        state["questions"][qid]["gaps"].append(failure)
            elif pending["operation"] == "search":
                urls = capture.get("packet", {}).get("urls")
                require(isinstance(urls, list) and urls, "ACQ_SEARCH_EMPTY")
                for url in urls:
                    _url(url)
                for qid in pending["question_ids"]:
                    state["questions"][qid]["status"] = "candidate_found"
            else:
                documents = capture.get("packet", {}).get("documents")
                require(isinstance(documents, list) and len(documents) == 1, "ACQ_DOCUMENT_INVALID")
                document = documents[0]
                require(isinstance(document, dict) and set(document) >= {"source_ref", "url", "text"}
                        and isinstance(document["text"], str) and len(document["text"]) >= 80, "ACQ_DOCUMENT_INVALID")
                _url(document["url"])
                expected_url = pending["arguments"][pending["native_key"]][0]["ref_id"]
                require(document["url"] == expected_url, "ACQ_DOCUMENT_URL_MISMATCH")
                assessments = capture.get("assessments", [])
                require(isinstance(assessments, list) and len(assessments) <= 12, "ACQ_ASSESSMENT_INVALID")
                supported = set()
                for row in assessments:
                    require(isinstance(row, dict) and set(row) == {"question_id", "quote", "disposition"}
                            and row["question_id"] in pending["question_ids"]
                            and row["disposition"] in {"candidate_support", "not_supporting"}
                            and isinstance(row["quote"], str) and 8 <= len(row["quote"]) <= 1200
                            and row["quote"] in document["text"], "ACQ_ASSESSMENT_INVALID")
                    if row["disposition"] == "candidate_support":
                        supported.add(row["question_id"])
                for qid in pending["question_ids"]:
                    question = state["questions"][qid]
                    question["source_refs"].append(document["source_ref"])
                    question["status"] = "supported_partial" if qid in supported else "body_read"
            transition = save(self.directory, {"kind": "acquisition_decision", "decision": "capture",
                "operation_id": operation_id, "status": capture["status"], "failure": failure if capture["status"] != "returned" else None,
                "question_ids": pending["question_ids"], "next_dispatch": next_dispatch,
                "semantic_limit": "candidate_support_is_not_final_semantic_admission"})
            state["transition_refs"].append(transition)
            self._write(state)
        return {"state_ref": self._head(), "decision_ref": transition, "next_dispatch": next_dispatch}

    def finish(self):
        with self._lock():
            state = read(self._head())
            if state["finished_ref"]:
                return {"summary_ref": state["finished_ref"], "summary": read(state["finished_ref"])}
            require(state["pending"] is None, "ACQ_PENDING")
            rows = [{"question_id": qid, **value} for qid, value in state["questions"].items()]
            summary = {"version": VERSION, "manifest_ref": state["manifest_ref"], "questions": rows,
                "usage": state["usage"], "transition_refs": state["transition_refs"],
                "status": "completed_with_gaps" if any(row["status"] in {"unresolved", "blocked", "body_read"} for row in rows) else "completed",
                "scope": "structural_acquisition_control_not_semantic_quality_or_investment_alpha"}
            state["finished_ref"] = save(self.directory, summary)
            self._write(state)
            return {"summary_ref": state["finished_ref"], "summary": summary}
