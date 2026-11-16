"""Provider-free Codex adapter experiment; no provider or external effects."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
from shared.job_runtime.candidates.r6_one_off_codex_adapter_v1 import FakeCodexBoundary, execute_stage_a, stage_a_template
ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_codex_adapter_v1"

def run_experiment():
    template = stage_a_template("a" * 64, "opaque-ref://codex/current")
    cases = []
    with tempfile.TemporaryDirectory(dir=FIXTURE) as temporary:
        for scenario in ("nominal", "sealed_input_drift", "post_admission_unknown", "terminal_fault"):
            boundary = FakeCodexBoundary(terminal="truncated", cleanup="fault") if scenario in {"post_admission_unknown", "terminal_fault"} else FakeCodexBoundary()
            result = execute_stage_a(Path(temporary) / scenario, template, boundary, scenario)
            cases.append({"scenario": scenario, "outcome": result.evidence["outcome"], "countable_observation": result.evidence["countable_observation"], "admission_count": result.evidence["admission_count"], "upstream_attempt_count": result.evidence["upstream_attempt_count"], "retry_count": result.evidence["retry_count"], "replay_count": result.evidence["replay_count"], "provider_status_calls": result.evidence["provider_status_calls"], "reconstruction_dispatch": result.evidence["reconstruction_dispatch"], "effects": result.evidence["effects"]})
    return {"version": 1, "kind": "PROVIDER_FREE_CODEX_ADAPTER_EXPERIMENT", "cases": cases}

if __name__ == "__main__":
    print(json.dumps(run_experiment(), sort_keys=True, separators=(",", ":")))
