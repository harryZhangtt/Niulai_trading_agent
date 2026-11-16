"""Maintained offline suite for the deterministic leveraged-fund operator."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / ".job-runtime/calculation"
FOCUSED_MODULE = "shared.calculation.validation.test_leveraged_operator"
LEGACY_TEST = ROOT / "shared/calculation/legacy/valuation/test_leveraged_funds.py"
LEGACY_DIR = LEGACY_TEST.parent
EXPECTED_FOCUSED = 22
EXPECTED_LEGACY = 31


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_legacy_test_module():
    name = "_calculation_validation_legacy_leveraged_tests"
    spec = importlib.util.spec_from_file_location(name, LEGACY_TEST)
    if spec is None or spec.loader is None:
        raise ValueError("LEVERAGED_LEGACY_TEST_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    inserted = str(LEGACY_DIR)
    sys.path.insert(0, inserted)
    try:
        spec.loader.exec_module(module)
    finally:
        if sys.path and sys.path[0] == inserted:
            sys.path.pop(0)
        elif inserted in sys.path:
            sys.path.remove(inserted)
    return module


def _ids(rows):
    return [case.id() for case, _traceback in rows]


def run(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    focused = unittest.defaultTestLoader.loadTestsFromName(FOCUSED_MODULE)
    legacy = unittest.defaultTestLoader.loadTestsFromModule(_load_legacy_test_module())
    focused_count = focused.countTestCases()
    legacy_count = legacy.countTestCases()
    stream = io.StringIO()
    observed = unittest.TextTestRunner(stream=stream, verbosity=1).run(
        unittest.TestSuite([focused, legacy])
    )
    failures = _ids(observed.failures)
    errors = _ids(observed.errors)
    skipped = [case.id() for case, _reason in observed.skipped]
    count_ok = focused_count == EXPECTED_FOCUSED and legacy_count == EXPECTED_LEGACY
    passed = observed.wasSuccessful() and count_ok and observed.testsRun == focused_count + legacy_count
    targets = [
        ROOT / "shared/calculation/operators/leveraged_funds.py",
        ROOT / "shared/calculation/validation/test_leveraged_operator.py",
        ROOT / "shared/calculation/legacy/valuation/leveraged_funds.py",
        LEGACY_TEST,
        ROOT / "shared/calculation/manifest.json",
    ]
    result = {
        "suite": "leveraged_operator",
        "protocol": "leveraged-operator-validation-1",
        "status": "passed" if passed else "failed",
        "tests": {
            "focused_expected": EXPECTED_FOCUSED,
            "focused_observed": focused_count,
            "legacy_expected": EXPECTED_LEGACY,
            "legacy_observed": legacy_count,
            "total_observed": observed.testsRun,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
        },
        "candidate_hashes": {str(path.relative_to(ROOT)): _sha(path) for path in targets},
        "checks": [
            "strict versioned operator contract",
            "legacy arithmetic regression",
            "positive-wealth underflow containment",
            "bounded output and moving-block expansion",
            "exact empirical quantile/tail boundary oracle",
            "backend manifest and digest binding",
            "atomic replace and durability-unknown classification",
        ],
        "limitations": [
            "Synthetic and mechanical validation only; no calibrated probability or alpha claim.",
            "No data fetching, position sizing, entry selection, order, broker, or trade capability.",
            "Local runner evidence does not replace future scheduled native-host acceptance.",
        ],
        "evidence_paths": [],
    }
    path = output_dir / "leveraged-operator-result.json"
    result["evidence_paths"] = [str(path.relative_to(ROOT))]
    raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return result
