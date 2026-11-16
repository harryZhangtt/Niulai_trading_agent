"""In-process fixed synthetic runner for request/receipt v2.

The raw authority nonce is accepted out of band, consumed once in RunnerState, and
never serialized into requests, receipts, artifacts, errors, or files.
"""
import hashlib
import threading

from tuning.factor_mining.admission_authority.authority import (AuthorityError, FixtureAuthority,
                                                                  implementation_sha256 as authority_implementation_sha256)

from . import contracts, fixed_worker


class RunnerError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise RunnerError(code)


def implementation_sha256():
    return _compute_implementation_sha256()


class RunnerState:
    """One runner-lifetime nonce fence; not a durable production fence."""
    def __init__(self):
        self._lock = threading.Lock()
        self._consumed = set()

    def consume(self, nonce_sha256):
        with self._lock:
            require(nonce_sha256 not in self._consumed, "ADAPTER_V2_NONCE_REUSED")
            self._consumed.add(nonce_sha256)


def _failure_receipt(request):
    return {
        "schema_version": 2,
        "kind": "rdagent_synthetic_runner_receipt",
        "request_sha256": contracts.request_sha256(request),
        "authority_binding": request["authority_binding"],
        "runner_implementation_sha256": implementation_sha256(),
        "status": "failed",
        "artifact": None,
        "failure_code": "FIXED_WORKER_REJECTED",
        "outcome_accessed": False,
        "protected_labels_accessed": False,
        "performance_claim": "withheld",
    }


def run_fixed(request, raw_nonce, state, authority_instance):
    request = contracts.validate_request(request)
    require(isinstance(state, RunnerState), "ADAPTER_V2_RUNNER_STATE_INVALID")
    require(isinstance(authority_instance, FixtureAuthority),
            "ADAPTER_V2_AUTHORITY_INVALID")
    require(type(raw_nonce) is str and len(raw_nonce) == 64 and
            all(character in "0123456789abcdef" for character in raw_nonce),
            "ADAPTER_V2_NONCE_INVALID")
    nonce_sha = hashlib.sha256(bytes.fromhex(raw_nonce)).hexdigest()
    require(nonce_sha == request["authority_binding"]["nonce_sha256"],
            "ADAPTER_V2_NONCE_MISMATCH")
    try:
        authority_instance.verify_fixture_binding(raw_nonce, request["authority_binding"])
    except AuthorityError as error:
        if str(error) == "AUTHORITY_NONCE_ALREADY_CLAIMED":
            raise RunnerError("ADAPTER_V2_NONCE_CLAIM_REJECTED") from None
        raise RunnerError("ADAPTER_V2_AUTHORITY_BINDING_INVALID") from None
    except Exception:
        raise RunnerError("ADAPTER_V2_AUTHORITY_BINDING_INVALID") from None
    try:
        authority_instance.claim_fixture_nonce(raw_nonce, request["authority_binding"])
    except Exception:
        raise RunnerError("ADAPTER_V2_NONCE_CLAIM_REJECTED") from None
    state.consume(nonce_sha)
    try:
        artifact_bytes = fixed_worker.build_artifact(request)
        require(0 < len(artifact_bytes) <= request["limits"]["artifact_bytes"],
                "ADAPTER_V2_ARTIFACT_BUDGET")
        receipt = {
            "schema_version": 2,
            "kind": "rdagent_synthetic_runner_receipt",
            "request_sha256": contracts.request_sha256(request),
            "authority_binding": request["authority_binding"],
            "runner_implementation_sha256": implementation_sha256(),
            "status": "synthetic-structural-complete",
            "artifact": {"id": "structural-proof", "kind": "authority-binding-proof",
                         "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                         "size_bytes": len(artifact_bytes)},
            "failure_code": None,
            "outcome_accessed": False,
            "protected_labels_accessed": False,
            "performance_claim": "withheld",
        }
        contracts.validate_receipt(receipt, request)
        return {"receipt": receipt, "receipt_sha256": contracts.digest(receipt),
                "artifact": artifact_bytes}
    except Exception:
        receipt = _failure_receipt(request)
        contracts.validate_receipt(receipt, request)
        return {"receipt": receipt, "receipt_sha256": contracts.digest(receipt),
                "artifact": None}


def _compute_implementation_sha256():
    material = {
        "version": "rdagent-adapter-v2-synthetic-runner-v1",
        "worker_version": fixed_worker.WORKER_VERSION,
        "run_fixed": contracts._code_semantics(run_fixed.__code__),
        "require": contracts._code_semantics(require.__code__),
        "failure_receipt": contracts._code_semantics(_failure_receipt.__code__),
        "state_init": contracts._code_semantics(RunnerState.__init__.__code__),
        "state_consume": contracts._code_semantics(RunnerState.consume.__code__),
        "fixed_worker_implementation_sha256": fixed_worker.implementation_sha256(),
        "contracts_implementation_sha256": contracts.implementation_sha256(),
        "authority_implementation_sha256": authority_implementation_sha256(),
        "engine": contracts.engine_contract(),
        "purpose": contracts.PURPOSE,
    }
    return contracts.digest(material)
