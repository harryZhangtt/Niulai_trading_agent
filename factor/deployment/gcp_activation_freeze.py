"""Validate the immutable, apply-disabled GCP activation scaffold."""
import hashlib
import json
from pathlib import Path
import re

from factor.deployment import gcp_freeze

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "factor/deployment/gcp-activation-freeze-v1.json"
PARENT_SHA256 = "593b5d6078ff6bdcb8d4777ae7123ae754a373b55b4e47433a5e9acd7ba7188d"
MAX_BYTES = 256 * 1024
SHA = re.compile(r"[a-f0-9]{64}\Z")
SAFE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
SCOPE_ROOTS = (
    "factor/deployment/gcp_activation",
    "factor/deployment/gcp_activation_freeze.py",
    "factor/deployment/activation_freeze_tests",
)
BLOCKERS = [
    "gcp-account-and-billing-unconfigured",
    "gcp-project-and-location-identities-null",
    "account-side-conformance-unrun",
    "runtime-acceptance-receipt-null",
    "irreversible-owner-approval-null",
]
NONCLAIMS = [
    "no-terraform-apply-or-cloud-call",
    "no-provider-or-backend-configuration",
    "no-google-credential-or-resource",
    "no-runtime-publication-or-bucket-lock",
]

class ActivationFreezeError(ValueError):
    pass

def require(condition, code):
    if not condition:
        raise ActivationFreezeError(code)

def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "GCP_ACTIVATION_FREEZE_DUPLICATE_KEY")
        value[key] = item
    return value

def loads_strict(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES,
            "GCP_ACTIVATION_FREEZE_MANIFEST_SIZE")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               ActivationFreezeError("GCP_ACTIVATION_FREEZE_NONFINITE")))
    except ActivationFreezeError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise ActivationFreezeError("GCP_ACTIVATION_FREEZE_JSON_INVALID") from None
    require(type(value) is dict, "GCP_ACTIVATION_FREEZE_SCHEMA")
    return value

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def _safe(root, relative):
    require(type(relative) is str and SAFE_PATH.fullmatch(relative) and
            ".." not in Path(relative).parts, "GCP_ACTIVATION_FREEZE_PATH")
    path = root / relative
    require(path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(root.resolve()), "GCP_ACTIVATION_FREEZE_PATH")
    return path

def _scope_files(root):
    files = set()
    for relative in SCOPE_ROOTS:
        path = root / relative
        if path.is_dir():
            require(not path.is_symlink(), "GCP_ACTIVATION_FREEZE_SCOPE")
            for child in path.rglob("*"):
                if "__pycache__" in child.parts or child.suffix == ".pyc":
                    continue
                require(not child.is_symlink(), "GCP_ACTIVATION_FREEZE_SCOPE")
                if child.is_file():
                    files.add(str(child.relative_to(root)))
        else:
            files.add(str(_safe(root, relative).relative_to(root)))
    return files

def validate(value, root=ROOT):
    require(set(value) == {"schema_version", "kind", "design_id", "parent_design_id",
                            "parent_manifest_sha256", "status", "frozen_at", "scope_roots",
                            "files", "tests", "blockers", "nonclaims"} and
            value["schema_version"] == 1 and
            value["kind"] == "gcp_factor_activation_freeze" and
            value["design_id"] == "gcp-factor-activation-20261105-v1" and
            value["parent_design_id"] == "gcp-cloud-run-factor-mining-20261105-v1" and
            value["parent_manifest_sha256"] == PARENT_SHA256 and
            value["status"] == "frozen-disabled" and value["frozen_at"] == "2026-11-05" and
            value["scope_roots"] == list(SCOPE_ROOTS) and value["blockers"] == BLOCKERS and
            value["nonclaims"] == NONCLAIMS, "GCP_ACTIVATION_FREEZE_SCHEMA")
    parent = gcp_freeze.load_and_validate(root=Path(root))
    require(parent["design_id"] == value["parent_design_id"] and
            digest((Path(root) / "factor/deployment/gcp-freeze-v1.json").read_bytes()) == PARENT_SHA256,
            "GCP_ACTIVATION_FREEZE_PARENT")
    files = value["files"]
    require(type(files) is list and files and
            [item.get("path") for item in files] == sorted(item.get("path") for item in files),
            "GCP_ACTIVATION_FREEZE_FILES")
    seen = set()
    for item in files:
        require(type(item) is dict and set(item) == {"path", "sha256", "size_bytes"} and
                item["path"] not in seen and type(item["sha256"]) is str and
                SHA.fullmatch(item["sha256"]) and type(item["size_bytes"]) is int and
                item["size_bytes"] >= 0, "GCP_ACTIVATION_FREEZE_FILES")
        seen.add(item["path"])
        raw = _safe(Path(root), item["path"]).read_bytes()
        require(len(raw) == item["size_bytes"] and digest(raw) == item["sha256"],
                "GCP_ACTIVATION_FREEZE_DRIFT")
    require(seen == _scope_files(Path(root)), "GCP_ACTIVATION_FREEZE_SCOPE_DRIFT")
    require(value["tests"] == [
        {"id": "gcp-activation", "command": "PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/deployment/gcp_activation/tests -v", "expected_tests": 11},
        {"id": "activation-freeze", "command": "PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/deployment/activation_freeze_tests -v", "expected_tests": 4},
    ], "GCP_ACTIVATION_FREEZE_TESTS")
    return value

def load_and_validate(path=MANIFEST, root=ROOT):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise ActivationFreezeError("GCP_ACTIVATION_FREEZE_UNAVAILABLE") from None
    return validate(loads_strict(raw), Path(root))

def main():
    try:
        value = load_and_validate()
    except (ActivationFreezeError, gcp_freeze.FreezeError) as error:
        print(json.dumps({"status": "GCP_ACTIVATION_FREEZE_FAILED", "code": str(error)},
                         sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps({"status": "GCP_ACTIVATION_FREEZE_OK", "design_id": value["design_id"],
                      "manifest_sha256": digest(MANIFEST.read_bytes()), "files": len(value["files"])},
                     sort_keys=True, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
