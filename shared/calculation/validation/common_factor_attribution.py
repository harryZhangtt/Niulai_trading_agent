"""Standalone focused-suite harness for common-factor attribution."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import platform
import unittest

import numpy as np
import scipy

ROOT = Path(__file__).resolve().parents[3]
FOCUSED_MODULE = "shared.calculation.validation.test_common_factor_attribution"
EXPECTED_FOCUSED = 18
PROTOCOL = "common-factor-attribution-validation-1"
LOCK_PATH = ROOT / "shared/calculation/validation/requirements-lock.txt"
FROZEN_REQUIREMENTS_LOCK_SHA256 = "e2fc05dec11c31df19955f6e866070a65687596ad3fb107b5be2e7a54f74ccb7"
TARGETS = (
    ROOT / "shared/calculation/operators/common_factor_attribution.py",
    ROOT / "shared/calculation/validation/test_common_factor_attribution.py",
)
FROZEN_CANDIDATE_HASHES = {
    "shared/calculation/operators/common_factor_attribution.py": "f488eaf2e74ac3bf9c17cea31037c1a0336d10980b835926b7cb23e488f512fb",
    "shared/calculation/validation/test_common_factor_attribution.py": "4be7970d5e4b869caed1fa916172c385d96e979aee5f8e972f7f9e367ad8a618",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_ids(rows):
    return [case.id() for case, _traceback in rows]


def run(output_dir):
    """Run only the focused tests and write one deterministic local receipt."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromName(FOCUSED_MODULE)
    observed_count = suite.countTestCases()
    stream = io.StringIO()
    observed = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    candidate_hashes = {str(path.relative_to(ROOT)): _sha(path) for path in TARGETS}
    hashes_match = candidate_hashes == FROZEN_CANDIDATE_HASHES
    observed_environment = {
        "python": platform.python_version(),
        "python_major_minor": f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}",
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }
    expected_environment = {
        "python": "3.12.16",
        "python_major_minor": "3.12",
        "numpy": "2.3.5",
        "scipy": "1.18.1",
    }
    environment_match = all(
        observed_environment[name] == value for name, value in expected_environment.items()
    )
    lock_hash = _sha(LOCK_PATH)
    lock_matches = lock_hash == FROZEN_REQUIREMENTS_LOCK_SHA256
    passed = (observed.wasSuccessful() and observed.testsRun == observed_count
              and observed_count == EXPECTED_FOCUSED and hashes_match
              and environment_match and lock_matches)
    result = {
        "suite": "common_factor_attribution",
        "protocol": PROTOCOL,
        "status": "passed" if passed else "failed",
        "tests": {
            "focused_expected": EXPECTED_FOCUSED,
            "focused_observed": observed_count,
            "total_observed": observed.testsRun,
            "failures": _case_ids(observed.failures),
            "errors": _case_ids(observed.errors),
            "skipped": [case.id() for case, _reason in observed.skipped],
        },
        "candidate_hashes": candidate_hashes,
        "frozen_candidate_hashes": dict(FROZEN_CANDIDATE_HASHES),
        "hashes_match": hashes_match,
        "dependency_policy": {
            "expected": expected_environment,
            "observed": observed_environment,
            "environment_match": environment_match,
            "requirements_lock": {
                "path": "shared/calculation/validation/requirements-lock.txt",
                "expected_sha256": FROZEN_REQUIREMENTS_LOCK_SHA256,
                "observed_sha256": lock_hash,
                "matches": lock_matches,
            },
            "fit": "numpy.linalg.svd-max-abs-column-scaled-float64",
            "independent_coefficient_oracle": "scipy.linalg.qr-pivoted",
        },
        "tolerance_policy": {
            "rank": "eps*max(rows,columns)*largest_scaled_singular_value",
            "condition_number_maximum": 100000000.0,
            "minimum_factor_span": "64*float64_eps",
            "coefficient_qr_comparison_rtol": 1e-12,
            "coefficient_qr_comparison_atol": 1e-14,
            "maximum_result_components": 100000,
        },
        "checks": [
            "exact synthetic coefficient recovery",
            "independent SOXL and TQQQ single-target calls",
            "daily and aggregate factor/group/common/residual identities",
            "name-canonical factor permutation",
            "strict dates, shapes, finiteness and nonoverlapping windows",
            "fail-closed rank, conditioning, scale, overflow and result-size diagnostics",
            "max-abs scaling across finite float64 extremes and overflowing mathematical spans",
            "canonical input hash and exact/proxy source identity preservation",
            "independent pivoted-QR coefficient recomputation",
        ],
        "limitations": [
            "Caller supplies already aligned log-total-return panels, factors and groups.",
            "Coefficients are descriptive linear decompositions, not causal or probabilistic claims.",
            "No acquisition, factor selection, presentation, action, order or network capability.",
            "The fixed condition, scale and size policies are numerical gates, not statistical significance tests.",
            "Synthetic validation does not establish empirical factor quality for SOXL or TQQQ.",
            "Determinism is verified in the pinned local Python, NumPy and SciPy environment; cross-platform BLAS bitwise equivalence is not claimed.",
            "This suite is registered through the maintained runner and worker owner and is required by acceptance; future scheduled native-host acceptance remains separate.",
        ],
        "evidence_paths": [],
    }
    path = output / "common-factor-attribution-result.json"
    result["evidence_paths"] = [str(path.relative_to(ROOT))]
    raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return result
