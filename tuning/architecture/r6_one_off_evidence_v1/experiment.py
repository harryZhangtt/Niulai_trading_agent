"""Run the three frozen provider-free O1 vertical cases in disposable state."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Dict

from shared.job_runtime.candidates.r6_one_off_evidence_v1.runner import (
    execute_provider_free, materialize_provider_free_case,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "shared" / "job_runtime" / "tests" / "fixtures" / "r6_one_off_evidence_v1"


def _load(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _transport(scenario: str):
    def invoke(_request):
        if scenario == "nominal":
            return {"terminal": "exact", "cleanup": "complete",
                    "raw": b'{"type":"synthetic.completed","ok":true}\n'}
        if scenario == "post_admission_unknown":
            return {"terminal": "truncated", "cleanup": "fault",
                    "raw": b'{"type":"synthetic.delta","cut":'}
        raise AssertionError("pre-dispatch STOP must not forward")
    return invoke


def run_experiment() -> Dict[str, Any]:
    historical = _load("historical-identities-v1.json")
    jobs = tuple(historical["logical_job_ids"])
    nonces = tuple(historical["preflight_nonces"])
    cases = []
    with tempfile.TemporaryDirectory(dir=FIXTURES) as temporary:
        base = Path(temporary)
        for scenario in ("nominal", "post_admission_unknown", "pre_dispatch_stop"):
            prepared = materialize_provider_free_case(
                base / scenario, scenario, jobs, nonces)
            try:
                if scenario == "pre_dispatch_stop":
                    prepared.inject_drift("config")
                execution = execute_provider_free(
                    prepared, _transport(scenario), jobs, nonces)
                cases.append({
                    "scenario": scenario,
                    "decision": execution.evidence["decision"],
                    "countable": execution.evidence["countable"],
                    "logical_job_id": execution.grant["logical_job_id"],
                    "preflight_nonce_sha256": execution.evidence["preflight_nonce_sha256"],
                    "engine": execution.evidence["engine"],
                    "counters": execution.evidence["counters"],
                    "publication": execution.publication,
                })
            finally:
                prepared.close()
    return {
        "version": 1, "kind": "PROVIDER_FREE_ARCHITECTURE_EXPERIMENT",
        "countable": False, "effects": {
            "provider": False, "network": False, "account": False,
            "login": False, "private_live_root": False, "email": False,
            "socket": False, "subprocess": False, "host": False,
        },
        "cases": cases,
    }


if __name__ == "__main__":
    print(json.dumps(run_experiment(), sort_keys=True, separators=(",", ":")))
