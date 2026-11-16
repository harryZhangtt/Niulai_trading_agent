"""Fixed structural worker; it never executes generated or upstream code."""
import re
import types

from . import contracts

WORKER_VERSION = "rdagent-v2-fixed-structural-worker-v1"
REQUIRED_BINDINGS = (
    "builder_receipt_sha256", "observation_set_sha256", "feature_snapshot_sha256",
    "evaluation_population_sha256", "split_fingerprints",
)


def build_artifact(request):
    """Return outcome-free bytes solely from the authority-validated request binding."""
    contracts.validate_request(request)
    binding = request["authority_binding"]
    if not all(key in binding for key in REQUIRED_BINDINGS):
        raise contracts.ContractError("ADAPTER_V2_BINDING_SCHEMA")
    payload = {
        "schema_version": 1,
        "kind": "synthetic_authority_binding_proof",
        "worker_version": WORKER_VERSION,
        "request_sha256": contracts.request_sha256(request),
        "builder_receipt_sha256": binding["builder_receipt_sha256"],
        "observation_set_sha256": binding["observation_set_sha256"],
        "feature_snapshot_sha256": binding["feature_snapshot_sha256"],
        "evaluation_population_sha256": binding["evaluation_population_sha256"],
        "split_fingerprints": binding["split_fingerprints"],
        "outcome_accessed": False,
        "protected_labels_accessed": False,
        "performance_claim": "withheld",
    }
    return contracts.canonical(payload)


def _code_value(value):
    if isinstance(value, types.CodeType):
        return {"bytecode": value.co_code.hex(), "names": list(value.co_names),
                "varnames": list(value.co_varnames),
                "constants": [_code_value(item) for item in value.co_consts]}
    if isinstance(value, re.Pattern):
        return {"pattern": value.pattern, "flags": value.flags}
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, (set, frozenset)):
        return sorted((_code_value(item) for item in value), key=contracts.canonical)
    if isinstance(value, (tuple, list)):
        return [_code_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _code_value(item) for key, item in sorted(value.items())}
    return {"type": type(value).__name__, "repr": repr(value)}


def implementation_sha256():
    return contracts.digest({
        "worker_version": WORKER_VERSION,
        "required_bindings": _code_value(REQUIRED_BINDINGS),
        "build_artifact": _code_value(build_artifact.__code__),
    })
