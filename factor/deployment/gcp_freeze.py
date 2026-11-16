"""Validate the immutable, disabled GCP factor-mining deployment candidate."""
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "factor/deployment/gcp-freeze-v1.json"
MAX_MANIFEST_BYTES = 512 * 1024
SHA = re.compile(r"[a-f0-9]{64}\Z")
SAFE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
SCOPE_ROOTS = (
    "docs/plans/factor-mining-production-selection-gcp-20261105.md",
    "tuning/factor_mining/trusted_authority/gcp",
    "factor/docker/gcp",
    "factor/source_inventory",
    "factor/deployment/__init__.py",
    "factor/deployment/gcp_freeze.py",
    "factor/deployment/tests/__init__.py",
    "factor/deployment/tests/test_gcp_freeze.py",
)
BLOCKERS = [
    "gcp-billing-account-unconfigured",
    "gcp-projects-unprovisioned",
    "gcp-locations-unselected",
    "gcp-apis-disabled",
    "gcp-service-accounts-unprovisioned",
    "gcp-storage-and-retention-unprovisioned",
    "gcp-kms-purpose-keys-unprovisioned",
    "gcp-cloud-run-jobs-unprovisioned",
    "gcp-vpc-firewall-vpcsc-unverified",
    "provider-entitlements-and-licenses-unverified",
    "protected-label-custody-unprovisioned",
    "account-side-conformance-unrun",
]
NONCLAIMS = [
    "no-cloud-account-access",
    "no-billing-or-api-enablement",
    "no-credentials-or-service-account-keys",
    "no-resource-provisioning",
    "no-real-provider-data-or-protected-labels",
    "no-runtime-invocation-or-publication",
    "no-factor-quality-alpha-ev-or-kelly-claim",
]


class FreezeError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise FreezeError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "GCP_FREEZE_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_strict(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST_BYTES,
            "GCP_FREEZE_MANIFEST_SIZE")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               FreezeError("GCP_FREEZE_NONFINITE")))
    except FreezeError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise FreezeError("GCP_FREEZE_JSON_INVALID") from None
    require(type(value) is dict, "GCP_FREEZE_SCHEMA")
    return value


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise FreezeError("GCP_FREEZE_JSON_INVALID") from None


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _safe_file(root, relative):
    require(type(relative) is str and SAFE_PATH.fullmatch(relative) and
            ".." not in Path(relative).parts, "GCP_FREEZE_PATH_INVALID")
    path = root / relative
    require(path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(root.resolve()), "GCP_FREEZE_PATH_INVALID")
    return path


def _scope_files(root):
    files = set()
    for relative in SCOPE_ROOTS:
        path = root / relative
        if path.is_dir():
            require(not path.is_symlink(), "GCP_FREEZE_SCOPE_INVALID")
            for child in path.rglob("*"):
                if "__pycache__" in child.parts or child.suffix == ".pyc":
                    continue
                require(not child.is_symlink(), "GCP_FREEZE_SCOPE_INVALID")
                if child.is_file():
                    files.add(str(child.relative_to(root)))
        else:
            files.add(str(_safe_file(root, relative).relative_to(root)))
    return files


def validate_manifest(value, root=ROOT):
    expected_keys = {"schema_version", "kind", "design_id", "status", "frozen_at",
                     "scope_roots", "files", "tests", "blockers", "nonclaims"}
    require(set(value) == expected_keys and type(value["schema_version"]) is int and
            value["schema_version"] == 1 and value["kind"] == "gcp_factor_deployment_freeze" and
            value["design_id"] == "gcp-cloud-run-factor-mining-20261105-v1" and
            value["status"] == "frozen-disabled" and
            value["frozen_at"] == "2026-11-05" and
            value["scope_roots"] == list(SCOPE_ROOTS) and
            value["blockers"] == BLOCKERS and value["nonclaims"] == NONCLAIMS,
            "GCP_FREEZE_SCHEMA")
    files = value["files"]
    require(type(files) is list and files and
            [item.get("path") for item in files] == sorted(item.get("path") for item in files),
            "GCP_FREEZE_FILES")
    seen = set()
    for item in files:
        require(type(item) is dict and set(item) == {"path", "sha256", "size_bytes"} and
                item["path"] not in seen and type(item["sha256"]) is str and
                SHA.fullmatch(item["sha256"]) and type(item["size_bytes"]) is int and
                item["size_bytes"] >= 0, "GCP_FREEZE_FILES")
        seen.add(item["path"])
        raw = _safe_file(root, item["path"]).read_bytes()
        require(len(raw) == item["size_bytes"] and digest_bytes(raw) == item["sha256"],
                "GCP_FREEZE_DRIFT")
    require(seen == _scope_files(root), "GCP_FREEZE_SCOPE_DRIFT")
    tests = value["tests"]
    require(type(tests) is list and len(tests) == 4, "GCP_FREEZE_TESTS")
    expected = {
        "gcp-authority": 8,
        "gcp-cloud-run": 8,
        "source-inventory": 29,
        "freeze-validator": 4,
    }
    require({item.get("id"): item.get("expected_tests") for item in tests} == expected and
            all(type(item) is dict and set(item) == {"id", "command", "expected_tests"} and
                type(item["command"]) is str and item["command"]
                for item in tests), "GCP_FREEZE_TESTS")
    return value


def load_and_validate(path=MANIFEST, root=ROOT):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise FreezeError("GCP_FREEZE_MANIFEST_UNAVAILABLE") from None
    return validate_manifest(loads_strict(raw), Path(root))


def main():
    try:
        value = load_and_validate()
    except FreezeError as error:
        print(json.dumps({"status": "GCP_FREEZE_FAILED", "code": str(error)},
                         sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps({"status": "GCP_FREEZE_OK", "design_id": value["design_id"],
                      "manifest_sha256": digest_bytes(MANIFEST.read_bytes()),
                      "files": len(value["files"])},
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
