"""Verify pinned, source-only RD-Agent and Qlib checkouts without importing them."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "factor/upstream/sources.lock.json"
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
REPOSITORIES = {
    "rd-agent": "https://github.com/microsoft/RD-Agent.git",
    "qlib-rdagent-compatible": "https://github.com/microsoft/qlib.git",
    "qlib-standalone-candidate": "https://github.com/microsoft/qlib.git",
}
SOURCE_KEYS = {
    "id", "repository", "release", "revision", "tree", "tracked_file_count",
    "runtime_path", "license_path", "license_sha256", "profile",
    "required_qlib_profile", "upstream_pin_evidence",
}


class VerificationError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise VerificationError(code)


def read_regular(path, maximum=2 * 1024 * 1024):
    path = Path(path)
    require(path.resolve().is_relative_to(ROOT.resolve()) and not path.is_symlink(),
            "FACTOR_SOURCE_PATH_REJECTED")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise VerificationError("FACTOR_SOURCE_FILE_INVALID") from None
    try:
        details = os.fstat(descriptor)
        require(stat.S_ISREG(details.st_mode) and 0 < details.st_size <= maximum,
                "FACTOR_SOURCE_FILE_INVALID")
        data = b""
        while len(data) < details.st_size:
            chunk = os.read(descriptor, min(65536, details.st_size - len(data)))
            require(chunk, "FACTOR_SOURCE_FILE_INVALID")
            data += chunk
        return data
    finally:
        os.close(descriptor)


def git(checkout, *arguments, binary=False):
    command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never",
               "-C", str(checkout), *arguments]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, check=False)
    require(result.returncode == 0, "FACTOR_SOURCE_GIT_FAILED")
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def validate_lock(value):
    require(isinstance(value, dict) and set(value) ==
            {"schema_version", "verified_on", "execution_status", "sources"},
            "FACTOR_SOURCE_LOCK_SCHEMA")
    require(value["schema_version"] == 1 and value["verified_on"] == "2026-11-04" and
            value["execution_status"] == "source-only-not-installed-not-executed",
            "FACTOR_SOURCE_LOCK_HEADER")
    require(isinstance(value["sources"], list) and len(value["sources"]) == 3,
            "FACTOR_SOURCE_ROSTER")
    ids = set()
    paths = set()
    for source in value["sources"]:
        require(isinstance(source, dict) and set(source) == SOURCE_KEYS,
                "FACTOR_SOURCE_ENTRY_SCHEMA")
        source_id = source["id"]
        require(NAME.fullmatch(source_id) and source_id not in ids and
                source["repository"] == REPOSITORIES.get(source_id), "FACTOR_SOURCE_IDENTITY")
        require(source["release"] is None or isinstance(source["release"], str) and
                re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", source["release"]),
                "FACTOR_SOURCE_RELEASE")
        require(SHA40.fullmatch(source["revision"]) and SHA40.fullmatch(source["tree"]) and
                SHA64.fullmatch(source["license_sha256"]), "FACTOR_SOURCE_DIGEST")
        require(type(source["tracked_file_count"]) is int and source["tracked_file_count"] > 0,
                "FACTOR_SOURCE_FILE_COUNT")
        require(isinstance(source["runtime_path"], str) and
                source["runtime_path"].startswith("factor/runtime/upstream/") and
                source["runtime_path"] not in paths, "FACTOR_SOURCE_RUNTIME_PATH")
        require(source["license_path"] == "LICENSE" and isinstance(source["profile"], str) and
                source["profile"], "FACTOR_SOURCE_METADATA")
        require(source["required_qlib_profile"] is None or
                source["required_qlib_profile"] in REPOSITORIES,
                "FACTOR_SOURCE_DEPENDENCY")
        require(isinstance(source["upstream_pin_evidence"], list) and
                all(isinstance(path, str) and path and not Path(path).is_absolute() and ".." not in Path(path).parts
                    for path in source["upstream_pin_evidence"]), "FACTOR_SOURCE_EVIDENCE")
        ids.add(source_id)
        paths.add(source["runtime_path"])
    by_id = {source["id"]: source for source in value["sources"]}
    require(by_id["rd-agent"]["required_qlib_profile"] == "qlib-rdagent-compatible" and
            by_id["qlib-rdagent-compatible"]["revision"] ==
            "2fb9380b342556ddb50a4b24e4fe8655d548b2b8" and
            by_id["qlib-standalone-candidate"]["revision"] !=
            by_id["qlib-rdagent-compatible"]["revision"], "FACTOR_SOURCE_COMPATIBILITY")
    return value


def verify(lock_path=LOCK):
    lock = validate_lock(json.loads(read_regular(lock_path)))
    verified = []
    by_id = {source["id"]: source for source in lock["sources"]}
    for source in lock["sources"]:
        checkout = ROOT / source["runtime_path"]
        require(checkout.is_dir() and not checkout.is_symlink() and
                checkout.resolve().is_relative_to(ROOT.resolve()), "FACTOR_SOURCE_CHECKOUT_MISSING")
        require(git(checkout, "rev-parse", "HEAD") == source["revision"],
                "FACTOR_SOURCE_REVISION_MISMATCH")
        require(git(checkout, "rev-parse", "HEAD^{tree}") == source["tree"],
                "FACTOR_SOURCE_TREE_MISMATCH")
        require(git(checkout, "status", "--porcelain=v1") == "", "FACTOR_SOURCE_DIRTY")
        require(git(checkout, "remote", "get-url", "origin") == source["repository"],
                "FACTOR_SOURCE_REMOTE_MISMATCH")
        tracked = git(checkout, "ls-files", "-z", binary=True).split(b"\0")
        tracked_count = len([path for path in tracked if path])
        require(tracked_count == source["tracked_file_count"], "FACTOR_SOURCE_FILE_COUNT_MISMATCH")
        license_bytes = read_regular(checkout / source["license_path"])
        require(hashlib.sha256(license_bytes).hexdigest() == source["license_sha256"],
                "FACTOR_SOURCE_LICENSE_MISMATCH")
        if source["release"] is not None:
            require(source["release"] in git(checkout, "tag", "--points-at", "HEAD").splitlines(),
                    "FACTOR_SOURCE_TAG_MISMATCH")
        for evidence_path in source["upstream_pin_evidence"]:
            evidence = read_regular(checkout / evidence_path).decode("utf-8")
            required_revision = by_id[source["required_qlib_profile"]]["revision"]
            require(required_revision in evidence, "FACTOR_SOURCE_PIN_EVIDENCE_MISMATCH")
        verified.append({"id": source["id"], "revision": source["revision"],
                         "tree": source["tree"], "tracked_file_count": tracked_count})
    return {"status": "FACTOR_SOURCES_OK", "execution_status": lock["execution_status"],
            "sources": verified}


def main():
    try:
        result = verify()
    except (VerificationError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        code = str(error) if isinstance(error, VerificationError) else "FACTOR_SOURCE_VERIFY_FAILED"
        print(json.dumps({"status": "FACTOR_SOURCES_FAILED", "code": code}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
