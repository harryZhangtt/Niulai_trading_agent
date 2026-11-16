from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "shared" / "job_runtime" / "tests" / "fixtures" / "r6_one_off_evidence_v1"


def load(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def historical() -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    value = load("historical-identities-v1.json")
    return (tuple(value["logical_job_ids"]), tuple(value["preflight_nonces"]),
            tuple(value["engine_ids"]))


def transport_for(scenario: str, observed: list) -> Any:
    def transport(request):
        observed.append(dict(request))
        if scenario == "nominal":
            return {"terminal": "exact", "cleanup": "complete",
                    "raw": b'{"type":"synthetic.completed","ok":true}\n'}
        if scenario == "post_admission_unknown":
            return {"terminal": "truncated", "cleanup": "fault",
                    "raw": b'{"type":"synthetic.delta","cut":'}
        raise AssertionError("transport must not run")
    return transport


def temporary_parent():
    return tempfile.TemporaryDirectory(dir=FIXTURES)
