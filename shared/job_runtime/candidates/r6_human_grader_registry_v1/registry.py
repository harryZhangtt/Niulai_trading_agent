"""Read-only, provider-free validator for owner-private human grader attestations.

This module cannot sign, review, install, activate, or call a provider. It only
validates exact fixed-path artifacts and always reports activation/countability
as false; a separate explicit pinning change remains necessary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple


class ContractError(ValueError):
    pass


WORKSPACE_ROOT = Path(__file__).absolute().parents[4]
RUNTIME = "mentor/runtime/scheduler-midresponse-recovery-20261107"
ROLE_ASSIGNMENT = {
    "path": RUNTIME + "/r6-data-quality-human-grader-role-assignment-v1.json",
    "sha256": "62db631b77d728c98ae5349a43862c079e2fdafa6b3eb6701b9c908df2de6935",
    "bytes": 2407,
    "mode": "0600",
}
EVALUATION = {
    "contract": {
        "path": RUNTIME + "/r6-data-quality-2x2-evaluation-contract-v3.json",
        "sha256": "8bef52f4f1c7511ec8897b17dbee2f542b0a822acaf22ebbe2e0e267d7c6714d",
        "bytes": 9944,
        "mode": "0644",
    },
    "producer_verification": {
        "path": "tuning/architecture/r6_data_quality_2x2_evaluation_v3/producer-verification-v3.json",
        "sha256": "2df4cae89b8942a8eb38b766608381f4bc41aeb8f4c984a9d32aa677068718ea",
        "bytes": 2588,
        "mode": "0644",
    },
    "clean_review": {
        "path": RUNTIME + "/r6-data-quality-2x2-evaluation-v3-independent-review.json",
        "sha256": "da36e2ae03c7a74ef7b5dce91eb7fc7e627b3cb431a0064c6efde37ef744b429",
        "bytes": 10585,
        "mode": "0644",
    },
}
ROLE_IDS = {"G1": "HGR-7A41", "G2": "HGR-29C8", "G3": "HGR-93F2"}
REGISTRY_ID = "R6DQ-HUMAN-GRADER-REGISTRY-V1"
REGISTRY_PATH = RUNTIME + "/r6-data-quality-human-grader-registry-subject-v1.json"
GRANT_PATHS = {
    role: RUNTIME + "/r6-data-quality-human-grader-%s-role-grant-subject-v1.json" % role.lower()
    for role in ("G1", "G2", "G3")
}
REVIEW_PATHS = {
    "REGISTRY": RUNTIME + "/r6-data-quality-human-grader-registry-subject-v1-independent-review.json",
    **{
        role: RUNTIME + "/r6-data-quality-human-grader-%s-role-grant-subject-v1-independent-review.json" % role.lower()
        for role in ("G1", "G2", "G3")
    },
}
ZERO_EFFECTS = {key: 0 for key in (
    "account", "business", "credential", "email", "live", "network",
    "private_state", "provider", "scheduler", "subagent",
)}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _closed(value: Any, fields: Sequence[str], code: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), code + "_TYPE")
    _require(set(value) == set(fields), code + "_FIELDS")
    return value


def _json_no_duplicates(raw: bytes, code: str) -> Any:
    def pairs(items: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ContractError(code + "_DUPLICATE_KEY")
            out[key] = value
        return out
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(code + "_JSON") from exc


def _secure_read(root: Path, relpath: str, expected_mode: int, code: str) -> Tuple[Any, str, int]:
    _require(root.is_absolute(), "ROOT_NOT_ABSOLUTE")
    rst = os.lstat(str(root))
    _require(stat.S_ISDIR(rst.st_mode) and not stat.S_ISLNK(rst.st_mode), "ROOT_INVALID")
    _require(rst.st_uid == os.getuid(), "ROOT_OWNER")
    parts = relpath.split("/")
    _require(bool(parts) and all(p not in ("", ".", "..") for p in parts) and "\\" not in relpath, code + "_PATH")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    opened = []
    try:
        descriptor = os.open(str(root), flags_dir)
        opened.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, flags_dir, dir_fd=descriptor)
            opened.append(descriptor)
            dst = os.fstat(descriptor)
            _require(stat.S_ISDIR(dst.st_mode) and dst.st_uid == os.getuid(), code + "_PARENT")
        descriptor = os.open(parts[-1], flags_file, dir_fd=descriptor)
        opened.append(descriptor)
        fst = os.fstat(descriptor)
        _require(stat.S_ISREG(fst.st_mode), code + "_NOT_REGULAR")
        _require(fst.st_uid == os.getuid(), code + "_OWNER")
        _require(stat.S_IMODE(fst.st_mode) == expected_mode, code + "_MODE")
        chunks = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    except FileNotFoundError as exc:
        raise ContractError(code + "_MISSING") from exc
    except OSError as exc:
        raise ContractError(code + "_NOFOLLOW") from exc
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
    return _json_no_duplicates(raw, code), hashlib.sha256(raw).hexdigest(), len(raw)


def _read_frozen(root: Path, ref: Mapping[str, Any], code: str) -> Any:
    value, digest, length = _secure_read(root, str(ref["path"]), int(str(ref["mode"]), 8), code)
    _require(digest == ref["sha256"], code + "_HASH")
    _require(length == ref["bytes"], code + "_BYTES")
    return value


def _signature(value: Any, code: str) -> None:
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{16,512}", value) is not None, code)
    upper = value.upper()
    _require(not any(token in upper for token in ("PENDING", "PLACEHOLDER", "FIXTURE", "AI-GENERATED", "SELF-MINT")), code)


def _validate_frozen(root: Path) -> None:
    assignment = _read_frozen(root, ROLE_ASSIGNMENT, "ROLE_ASSIGNMENT")
    _require(assignment.get("version") == "r6-data-quality-human-grader-role-assignment-v1", "ROLE_ASSIGNMENT_VERSION")
    roles = assignment.get("roles")
    _require(isinstance(roles, list), "ROLE_ASSIGNMENT_ROLES")
    _require({row.get("role"): row.get("human_reviewer_id") for row in roles} == ROLE_IDS, "ROLE_ASSIGNMENT_IDS")
    contract = _read_frozen(root, EVALUATION["contract"], "EVALUATION_CONTRACT")
    producer = _read_frozen(root, EVALUATION["producer_verification"], "EVALUATION_PRODUCER")
    review = _read_frozen(root, EVALUATION["clean_review"], "EVALUATION_CLEAN_REVIEW")
    _require(contract.get("version") == "r6-data-quality-2x2-evaluation-contract-v3", "EVALUATION_CONTRACT_VERSION")
    _require(producer.get("verdict") == "PASS" and producer.get("activation") is False, "EVALUATION_PRODUCER_STATUS")
    clean = "CLEAN_PROVIDER_FREE_2X2_EVALUATION_V3"
    _require(review.get("status") == clean and review.get("verdict") == clean, "EVALUATION_REVIEW_NOT_CLEAN")


def _validate_registry(value: Any) -> None:
    pending = value.get("status") == "PENDING_HUMAN_SIGNATURE" if isinstance(value, Mapping) else False
    base = ("version", "artifact_kind", "status", "activation", "registry_id", "role_assignment", "evaluation", "roles", "attestations")
    fields = base if pending else base + ("attested_at", "human_signature_attestation")
    _closed(value, fields, "REGISTRY")
    _require(value["version"] == "r6-human-grader-registry-subject-v1", "REGISTRY_VERSION")
    _require(value["artifact_kind"] == "HUMAN_GRADER_REGISTRY" and value["activation"] is False, "REGISTRY_KIND")
    _require(value["status"] == "HUMAN_SIGNED_ATTESTATION", "REGISTRY_PENDING_HUMAN_SIGNATURE")
    _require(value["registry_id"] == REGISTRY_ID, "REGISTRY_ID")
    _require(value["role_assignment"] == ROLE_ASSIGNMENT and value["evaluation"] == EVALUATION, "REGISTRY_BINDINGS")
    _require(value["roles"] == [{"role": r, "human_reviewer_id": ROLE_IDS[r]} for r in ("G1", "G2", "G3")], "REGISTRY_ROLE_BINDING")
    _require(len({row["role"] for row in value["roles"]}) == 3 and len({row["human_reviewer_id"] for row in value["roles"]}) == 3, "REGISTRY_DUPLICATE_HUMAN_OR_ROLE")
    _require(value["attestations"] == {"human_controlled": True, "not_ai_or_fixture_generated": True, "no_names_emails_or_credentials": True}, "REGISTRY_ATTESTATIONS")
    _require(isinstance(value["attested_at"], str) and bool(value["attested_at"].strip()), "REGISTRY_ATTESTED_AT")
    _signature(value["human_signature_attestation"], "REGISTRY_HUMAN_SIGNATURE")


def _validate_review(value: Any, subject_path: str, subject_sha: str, subject_bytes: int) -> str:
    fields = ("version", "artifact_kind", "status", "subject_path", "subject_sha256", "subject_bytes", "reviewer_opaque_id", "independent_human_reviewer", "independent_of_all_graders", "conflict_disclosure", "review_created_by_human", "reviewed_at", "human_signature_attestation")
    _closed(value, fields, "REVIEW")
    _require(value["version"] == "r6-human-grader-independent-review-v1" and value["artifact_kind"] == "INDEPENDENT_HUMAN_ATTESTATION_REVIEW", "REVIEW_VERSION")
    _require(value["status"] == "CLEAN", "REVIEW_NOT_CLEAN")
    _require(value["subject_path"] == subject_path and value["subject_sha256"] == subject_sha and value["subject_bytes"] == subject_bytes, "REVIEW_SUBJECT_BINDING")
    reviewer = value["reviewer_opaque_id"]
    _require(isinstance(reviewer, str) and re.fullmatch(r"HGRV-[0-9A-F]{4,16}", reviewer) is not None, "REVIEWER_OPAQUE_ID")
    _require(reviewer not in ROLE_IDS.values(), "REVIEWER_NOT_INDEPENDENT")
    _require(value["independent_human_reviewer"] is True and value["independent_of_all_graders"] is True, "REVIEWER_NOT_INDEPENDENT")
    _require(value["conflict_disclosure"] == "NO_KNOWN_CONFLICT" and value["review_created_by_human"] is True, "REVIEW_CONFLICT_OR_ORIGIN")
    _require(isinstance(value["reviewed_at"], str) and bool(value["reviewed_at"].strip()), "REVIEWED_AT")
    _signature(value["human_signature_attestation"], "REVIEW_HUMAN_SIGNATURE")
    return reviewer


def _validate_grant(value: Any, role: str, registry_sha: str) -> None:
    pending = value.get("status") == "PENDING_HUMAN_SIGNATURE" if isinstance(value, Mapping) else False
    base = ("version", "artifact_kind", "status", "activation", "registry_id", "role", "human_reviewer_id", "role_assignment", "blind", "countable", "valid_from_ms", "valid_through_ms", "independence", "conflict_disclosure", "blind_commitment_acknowledged", "no_blind_map_access")
    fields = base if pending else base + ("registry_subject_sha256", "attested_at", "human_signature_attestation")
    _closed(value, fields, "GRANT_" + role)
    _require(value["version"] == "r6-human-grader-role-grant-subject-v1" and value["artifact_kind"] == "HUMAN_GRADER_ROLE_GRANT", "GRANT_VERSION")
    _require(value["status"] == "HUMAN_SIGNED_ATTESTATION", "GRANT_" + role + "_PENDING_HUMAN_SIGNATURE")
    _require(value["activation"] is False and value["registry_id"] == REGISTRY_ID, "GRANT_REGISTRY")
    _require(value["role"] == role and value["human_reviewer_id"] == ROLE_IDS[role], "GRANT_ROLE_OR_ID")
    _require(value["role_assignment"] == ROLE_ASSIGNMENT and value["registry_subject_sha256"] == registry_sha, "GRANT_BINDINGS")
    _require(value["blind"] is True and value["countable"] is True, "GRANT_POLICY")
    _require(isinstance(value["valid_from_ms"], int) and isinstance(value["valid_through_ms"], int) and value["valid_from_ms"] < value["valid_through_ms"], "GRANT_TIME")
    _require(value["independence"] == {"human_is_independent": True, "independent_from_other_graders": True, "no_joint_grading": True}, "GRANT_INDEPENDENCE")
    _require(value["conflict_disclosure"] == "NO_KNOWN_CONFLICT", "GRANT_CONFLICT")
    _require(value["blind_commitment_acknowledged"] is True and value["no_blind_map_access"] is True, "GRANT_BLIND_ACKNOWLEDGEMENT")
    _require(isinstance(value["attested_at"], str) and bool(value["attested_at"].strip()), "GRANT_ATTESTED_AT")
    _signature(value["human_signature_attestation"], "GRANT_HUMAN_SIGNATURE")


def validate_registry_attestations(workspace_root: Path = WORKSPACE_ROOT, g3_triggered: bool = False) -> Dict[str, Any]:
    """Validate fixed artifacts without producing, modifying, or activating them."""
    root = Path(workspace_root)
    _validate_frozen(root)
    registry, registry_sha, registry_bytes = _secure_read(root, REGISTRY_PATH, 0o600, "REGISTRY_SUBJECT")
    _validate_registry(registry)
    registry_review, _, _ = _secure_read(root, REVIEW_PATHS["REGISTRY"], 0o600, "REGISTRY_REVIEW")
    reviewers = [_validate_review(registry_review, REGISTRY_PATH, registry_sha, registry_bytes)]
    roles = ["G1", "G2"] + (["G3"] if g3_triggered else [])
    seen_humans = set()
    for role in roles:
        grant, grant_sha, grant_bytes = _secure_read(root, GRANT_PATHS[role], 0o600, role + "_SUBJECT")
        _validate_grant(grant, role, registry_sha)
        _require(grant["human_reviewer_id"] not in seen_humans, "DUPLICATE_HUMAN")
        seen_humans.add(grant["human_reviewer_id"])
        grant_review, _, _ = _secure_read(root, REVIEW_PATHS[role], 0o600, role + "_REVIEW")
        reviewers.append(_validate_review(grant_review, GRANT_PATHS[role], grant_sha, grant_bytes))
    _require(ROLE_IDS["G1"] != ROLE_IDS["G2"], "G1_EQUALS_G2")
    if g3_triggered:
        _require(ROLE_IDS["G3"] not in (ROLE_IDS["G1"], ROLE_IDS["G2"]), "G3_NOT_INDEPENDENT")
    return {
        "version": "r6-human-grader-validation-report-v1",
        "activation": False,
        "provider_calls_permitted": False,
        "countable": False,
        "decision": "VALIDATED_FOR_SEPARATE_EXPLICIT_PINNING_NOT_LIVE",
        "g3_triggered": bool(g3_triggered),
        "validated_roles": roles,
        "human_attestation_claim": "DECLARED_AND_INDEPENDENTLY_REVIEWED_NOT_CRYPTOGRAPHIC_IDENTITY_PROOF",
        "effects": dict(ZERO_EFFECTS),
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Validate fixed R6 human grader attestations; never activates them.")
    parser.add_argument("--workspace-root", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--g3-triggered", action="store_true")
    args = parser.parse_args(list(argv) if argv else None)
    try:
        result = validate_registry_attestations(args.workspace_root, args.g3_triggered)
    except ContractError as exc:
        print(json.dumps({"activation": False, "countable": False, "decision": "DENY", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
