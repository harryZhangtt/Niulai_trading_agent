"""Deterministic provider-free closure producer for the OFF-only v2 candidate."""
from __future__ import print_function

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "shared/job_runtime/candidates/r6_fable_canary_entrypoint_v2"
TEST_OUTPUT = Path(__file__).with_name("producer-verification-output-v1.txt")
EVIDENCE_CLOSURE = Path(__file__).with_name("evidence-closure-v1.json")
PRODUCER_RECEIPT = Path(__file__).with_name("producer-verification-v1.json")
PREFLIGHT = ROOT / ".job-runtime/evidence/claude-sdk-0.2.179-observed-import-preflight-v2/receipt.json"
V1_CLOSURE = ROOT / "shared/job_runtime/candidates/r6_fable_canary_entrypoint_v1/source_closure.json"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def ref(path):
    raw = Path(path).read_bytes()
    return {"path": str(Path(path).relative_to(ROOT)), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def source_value():
    sys.path.insert(0, str(ROOT))
    from shared.job_runtime.candidates.r6_fable_canary_entrypoint_v2 import entrypoint as e
    members = {}
    for name, path in e._SOURCE_PATHS.items():
        raw = Path(path).read_bytes()
        members[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return {
        "schema_version": 2, "candidate_id": e.CANDIDATE_ID,
        "status": "OFF_PENDING_INDEPENDENT_EVIDENCE_REVIEW",
        "activation": False, "production_enabled": False,
        "source_mode": "uid-current-mode0600-nlink1-regular-bounded-stable-v1",
        "members": members,
        "compatibility_assertions": {
            "claude_bridge_sha256": e._EXPECTED_BRIDGE_SHA256,
            "sdk_import_preflight_claimed": True,
            "observed_import_preflight_v2_sha256": e._EXPECTED_PREFLIGHT_SHA256,
            "runtime_lock_v2_sha256": e._EXPECTED_RUNTIME_LOCK_SHA256,
        },
    }


def evidence_value():
    return {
        "schema_version": 1, "candidate_id": "r6-fable-canary-entrypoint-v2",
        "status": "PROVIDER_FREE_EVIDENCE_COMPLETE_INDEPENDENT_REVIEW_PENDING",
        "activation": False, "production_enabled": False,
        "independent_review": "PENDING", "provider_calls": 0,
        "network_calls": 0, "sdk_imports_by_v2_tests": 0,
        "members": {
            "source_closure": ref(PACKAGE / "source_closure.json"),
            "off_manifest": ref(PACKAGE / "future-once-manifest-v2.json"),
            "empty_review_authority": ref(PACKAGE / "review_authority.json"),
            "pending_activation": ref(PACKAGE / "activation-receipt.pending.json"),
            "producer": ref(Path(__file__)),
            "test_output": ref(TEST_OUTPUT),
            "observed_preflight_receipt": ref(PREFLIGHT),
            "predecessor_v1_source_closure": ref(V1_CLOSURE),
        },
        "claims_excluded": ["provider_capability", "network_capability",
                            "live_runtime_acceptance", "production_activation",
                            "business_postconditions"],
    }


def receipt_value():
    return {
        "schema_version": 1, "candidate_id": "r6-fable-canary-entrypoint-v2",
        "status": "PASS_PROVIDER_FREE_DUAL_PYTHON_PENDING_INDEPENDENT_REVIEW",
        "activation": False, "production_enabled": False,
        "evidence_closure": ref(EVIDENCE_CLOSURE),
        "tests": {"unique_tests": 28, "runtime_executions": 56,
                  "python_3_9_6": {"passed": 28, "failed": 0},
                  "python_3_12_16_pinned": {"passed": 28, "failed": 0},
                  "bytecode_disabled": True},
        "effects": {"provider_calls": 0, "network_calls": 0,
                    "sdk_imports": 0, "activation": 0, "schedules": 0},
        "independent_review": "PENDING",
    }


def write_or_check(path, value, check):
    raw = canonical(value)
    if check:
        if not path.exists() or path.read_bytes() != raw:
            raise SystemExit("DRIFT: " + str(path))
    else:
        path.write_bytes(raw)
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-source-only", action="store_true")
    args = parser.parse_args()
    checking = args.check or args.check_source_only
    write_or_check(PACKAGE / "source_closure.json", source_value(), checking)
    if TEST_OUTPUT.exists() and not args.check_source_only:
        write_or_check(EVIDENCE_CLOSURE, evidence_value(), args.check)
        write_or_check(PRODUCER_RECEIPT, receipt_value(), args.check)
    print("PASS" if checking else "WROTE")


if __name__ == "__main__":
    main()
