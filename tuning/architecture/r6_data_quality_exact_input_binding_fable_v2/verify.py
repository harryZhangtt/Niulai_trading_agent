#!/usr/bin/env python3
"""Dependency-independent path/content verifier for R6 exact-input binding v2."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Mapping, Sequence
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
MANIFEST = PACKAGE / "current-input-manifest-v2.json"
SCHEMA = PACKAGE / "input-manifest-v2.schema.json"
ALLOWED_ROOT = "mentor/runtime/scheduler-midresponse-recovery-20261107"
COMMON_BYTES = 2417
COMMON_SHA = "4a3e3ecc0aec340d3e7d760c70a4671878f77f1a23348d5a520425e417bf24ec"
PROMPT_SHA = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
CELLS = {"R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3"}
DIR_MODES = {"mentor": 0o755, "mentor/runtime": 0o755, ALLOWED_ROOT: 0o700}
EXPECTED = {
    "payload": {"path": ALLOWED_ROOT + "/schema9-isolated-canary-q1-ab-payload-v1.json", "mode": "0644", "bytes": 2065, "sha256": "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a", "content_sha256": "b1941934d2aa879c52e42bbce5b2d0c49001732342aa5f6b25f1dc6c66b2cd5c"},
    "source_cutoff": {"path": ALLOWED_ROOT + "/schema9-isolated-canary-q1-ab-source-cutoff-v1.json", "mode": "0644", "bytes": 1044, "sha256": "32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072", "content_sha256": "2c4f69d233e90b7047dbf23d70167a5e4d59366a4d83ea1a1aa959ec06633f9c"},
    "rubric": {"path": ALLOWED_ROOT + "/schema9-isolated-canary-q1-ab-rubric.json", "mode": "0600", "bytes": 2259, "sha256": "81069b2ce57f30e56d70e7a2edd4672991838ebce1e2369b48effb8adde53d8f", "content_sha256": "35c155ab610cdc8bb6dc9ea639fce16ca51256b5703b99d0849279831685f790"},
    "thresholds": {"path": ALLOWED_ROOT + "/schema9-isolated-canary-q1-ab-thresholds-v2.json", "mode": "0644", "bytes": 3597, "sha256": "41bbb8c07c26aadb9fe0e795b1ac8e5d3a17c88d60cba77692845b135dd4b95b", "content_sha256": "98ca21509f9a920f42fa79bda31696023422575d49040070c696519183e1d8e9"},
    "evaluation_schema": {"path": ALLOWED_ROOT + "/schema9-isolated-canary-q1-ab-evidence-schema.json", "mode": "0600", "bytes": 1876, "sha256": "8f28c800b70c968af9ee02ec8ddbd897d33a253474273d20e7f9f5b4868b74d5", "content_sha256": "cafbfe18e695e4dfa2ff9bf2cfab0d0b29ff89c8e58a34bf3c42f8c9a6676f9c"},
}
LEAK_TOKENS = frozenset(("provider", "model", "addon", "order", "private", "internal", "claude", "codex", "opus", "gpt", "fable", "sonnet", "haiku", "treatment", "baseline", "layer", "dq", "on", "off", "sol"))


class VerificationError(ValueError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise VerificationError(code)


def strict_loads(raw: bytes) -> Any:
    require(not raw.startswith(b"\xef\xbb\xbf"), "UTF8_BOM")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise VerificationError("UTF8_INVALID") from exc
    def hook(pairs: Sequence[tuple[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in pairs:
            require(key not in out, "JSON_DUPLICATE_KEY:" + key)
            out[key] = value
        return out
    def bad(value: str) -> None:
        raise VerificationError("JSON_NONFINITE:" + value)
    try:
        return json.loads(text, object_pairs_hook=hook, parse_constant=bad)
    except VerificationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationError("JSON_INVALID") from exc


def strict_load(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VerificationError("CANONICAL_INVALID") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def resolve_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    require(ref.startswith("#/"), "SCHEMA_REF_EXTERNAL")
    current: Any = root
    for part in ref[2:].split("/"):
        require(isinstance(current, Mapping) and part in current, "SCHEMA_REF_MISSING")
        current = current[part]
    require(isinstance(current, Mapping), "SCHEMA_REF_NOT_OBJECT")
    return current


def validate_schema(instance: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str = "$") -> None:
    if "$ref" in schema:
        validate_schema(instance, resolve_ref(root, schema["$ref"]), root, path); return
    if "const" in schema: require(instance == schema["const"], "SCHEMA_CONST:" + path)
    if "enum" in schema: require(instance in schema["enum"], "SCHEMA_ENUM:" + path)
    kind = schema.get("type")
    if kind == "object":
        require(isinstance(instance, dict), "SCHEMA_OBJECT:" + path)
        required = set(schema.get("required", [])); require(required <= set(instance), "SCHEMA_REQUIRED:" + path)
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False: require(set(instance) <= set(props), "SCHEMA_EXTRA:" + path)
        for key, value in instance.items():
            if key in props: validate_schema(value, props[key], root, path + "." + key)
    elif kind == "array":
        require(isinstance(instance, list), "SCHEMA_ARRAY:" + path)
        require(len(instance) >= schema.get("minItems", 0), "SCHEMA_MIN_ITEMS:" + path)
        if "maxItems" in schema: require(len(instance) <= schema["maxItems"], "SCHEMA_MAX_ITEMS:" + path)
        for index, value in enumerate(instance): validate_schema(value, schema.get("items", {}), root, f"{path}[{index}]")
    elif kind == "string": require(isinstance(instance, str), "SCHEMA_STRING:" + path)
    elif kind == "integer": require(isinstance(instance, int) and not isinstance(instance, bool), "SCHEMA_INTEGER:" + path)
    elif kind == "boolean": require(isinstance(instance, bool), "SCHEMA_BOOLEAN:" + path)


def locator_tokens(path: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", path).casefold()
    return set(re.findall(r"[a-z0-9]+", normalized))


def validate_locator(path: str, expected: str) -> None:
    require(isinstance(path, str) and path.isascii(), "PATH_NOT_ASCII")
    require(unicodedata.normalize("NFC", path) == path and unicodedata.normalize("NFKC", path) == path, "PATH_NORMALIZATION")
    require("\\" not in path and "//" not in path and not path.startswith("/"), "PATH_LEXICAL")
    pure = PurePosixPath(path)
    require(not pure.is_absolute(), "PATH_ABSOLUTE")
    require(all(part not in ("", ".", "..") for part in path.split("/")), "PATH_COMPONENT")
    require(tuple(pure.parts) == tuple(path.split("/")), "PATH_NORMALIZED_DRIFT")
    require(path == expected, "PATH_NOT_EXACT_AUTHORITY")
    require(path == path.casefold(), "PATH_CASE_DRIFT")
    require(not (locator_tokens(path) & LEAK_TOKENS), "PATH_LABEL_LEAK")
    require(path.startswith(ALLOWED_ROOT + "/"), "PATH_OUTSIDE_ALLOWED_ROOT")


def verify_final_stat(st: Any, mode: int) -> None:
    require(stat.S_ISREG(st.st_mode), "PATH_NOT_REGULAR")
    require(st.st_uid == os.getuid(), "PATH_WRONG_OWNER")
    require(stat.S_IMODE(st.st_mode) == mode, "PATH_WRONG_MODE")


def secure_read_workspace_path(path: str, mode: int) -> bytes:
    """Component-wise no-follow read for an already lexically validated relative path."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    require(nofollow != 0 and directory != 0, "NOFOLLOW_UNAVAILABLE")
    root_st = os.lstat(ROOT)
    require(stat.S_ISDIR(root_st.st_mode) and not stat.S_ISLNK(root_st.st_mode) and root_st.st_uid == os.getuid(), "WORKSPACE_ROOT")
    fd = os.open(str(ROOT), flags | directory | nofollow)
    walked: list[str] = []
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            walked.append(part)
            child = os.open(part, flags | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = child
            st = os.fstat(fd); rel = "/".join(walked)
            require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid(), "PATH_PARENT_OWNER_TYPE")
            if rel in DIR_MODES: require(stat.S_IMODE(st.st_mode) == DIR_MODES[rel], "PATH_PARENT_MODE")
        final = os.open(parts[-1], flags | nofollow, dir_fd=fd)
        try:
            st = os.fstat(final); verify_final_stat(st, mode)
            chunks = []
            while True:
                chunk = os.read(final, 65536)
                if not chunk: break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(final)
    except OSError as exc:
        raise VerificationError("PATH_NOFOLLOW_OPEN") from exc
    finally:
        try: os.close(fd)
        except OSError: pass


def scan_manifest_paths(value: Any, key: str = "") -> None:
    if isinstance(value, Mapping):
        for child_key, child in value.items(): scan_manifest_paths(child, child_key)
    elif isinstance(value, list):
        for child in value: scan_manifest_paths(child, key)
    elif isinstance(value, str) and key in ("path", "normalized_path"):
        require(not (locator_tokens(value) & LEAK_TOKENS), "MANIFEST_PATH_LABEL_LEAK")


def validate_semantics(manifest: Mapping[str, Any], artifacts: Mapping[str, Any]) -> None:
    payload, cutoff = artifacts["payload"], artifacts["source_cutoff"]
    prompt = payload["prompt_utf8"]; prompt_raw = prompt.encode("utf-8")
    require((len(prompt_raw), hashlib.sha256(prompt_raw).hexdigest()) == (526, PROMPT_SHA), "PROMPT_IDENTITY")
    require(payload["payload_bytes"] == 526 and payload["payload_sha256"] == PROMPT_SHA, "PAYLOAD_PROMPT_BINDING")
    require(payload["source_cutoff"]["sha256"] == EXPECTED["source_cutoff"]["sha256"], "PAYLOAD_CUTOFF_BINDING")
    require(payload["bindings"]["rubric_sha256"] == EXPECTED["rubric"]["sha256"], "PAYLOAD_RUBRIC_BINDING")
    require(payload["bindings"]["thresholds_v2_sha256"] == EXPECTED["thresholds"]["sha256"], "PAYLOAD_THRESHOLD_BINDING")
    require(payload["bindings"]["evidence_schema_sha256"] == EXPECTED["evaluation_schema"]["sha256"], "PAYLOAD_SCHEMA_BINDING")
    require(cutoff["cutoff_at"] == "2026-11-09T00:00:00Z", "CUTOFF_AT")
    require(len(cutoff["allowed_sources"]) == 2 and all("official" in item.lower() for item in cutoff["allowed_sources"]), "OFFICIAL_ONLY")
    private_terms = ("bytedcli", "private source", "internal source", "intranet", "employee-only")
    require(not any(x in (prompt + json.dumps(cutoff)).lower() for x in private_terms), "PRIVATE_SOURCE_DEPENDENCY")
    prompt_leaks = ("claude", "codex", "gpt", "opus", "addon", "baseline", "treatment", "call order", "call_order")
    require(not any(x in prompt.lower() for x in prompt_leaks) and "order" not in prompt.lower(), "PROMPT_LEAK")
    rubric_text = json.dumps(artifacts["rubric"], sort_keys=True).lower(); threshold_text = json.dumps(artifacts["thresholds"], sort_keys=True).lower()
    bad_metrics = ("financial return", "investment return", "pnl", "profit", "sharpe", "sortino", "claude", "codex", "gpt", "opus")
    require(not any(x in rubric_text for x in bad_metrics), "RUBRIC_RETURN_PREFERENCE")
    require(not any(x in threshold_text for x in bad_metrics), "THRESHOLD_RETURN_PREFERENCE")


def validate_manifest(manifest: Mapping[str, Any], check_mode: bool = True) -> Dict[str, Any]:
    schema = strict_load(SCHEMA); validate_schema(manifest, schema, schema); scan_manifest_paths(manifest)
    if check_mode:
        pstat = os.lstat(PACKAGE); mstat = os.lstat(MANIFEST)
        require(stat.S_ISDIR(pstat.st_mode) and not stat.S_ISLNK(pstat.st_mode) and pstat.st_uid == os.getuid() and stat.S_IMODE(pstat.st_mode) == 0o700, "PACKAGE_PRIVATE")
        require(stat.S_ISREG(mstat.st_mode) and not stat.S_ISLNK(mstat.st_mode) and mstat.st_uid == os.getuid() and stat.S_IMODE(mstat.st_mode) == 0o600, "MANIFEST_PRIVATE")
    identity = manifest["common_binding"]["identity"]
    require(identity["allowed_root"] == ALLOWED_ROOT, "ALLOWED_ROOT")
    artifacts: Dict[str, Any] = {}
    rebuilt: Dict[str, Any] = {}
    for name, expected in EXPECTED.items():
        ref = identity["artifacts"][name]
        validate_locator(ref["path"], expected["path"])
        require(ref["normalized_path"] == ref["path"], "PATH_IDENTITY_MISMATCH")
        require(ref["mode"] == expected["mode"], "REF_MODE_PIN")
        raw = secure_read_workspace_path(ref["path"], int(ref["mode"], 8))
        require(len(raw) == ref["bytes"] == expected["bytes"], "REF_BYTES:" + name)
        require(hashlib.sha256(raw).hexdigest() == ref["sha256"] == expected["sha256"], "REF_RAW_HASH:" + name)
        value = strict_loads(raw); content = digest(value)
        require(content == ref["content_sha256"] == expected["content_sha256"], "REF_CONTENT_HASH:" + name)
        artifacts[name] = value; rebuilt[name] = copy.deepcopy(ref)
    observed_identity = {"allowed_root": ALLOWED_ROOT, "artifacts": rebuilt}
    require(observed_identity == identity, "COMMON_IDENTITY_REBUILD")
    require(len(canonical_bytes(identity)) == manifest["common_binding"]["canonical_utf8_bytes"] == COMMON_BYTES, "COMMON_BYTES")
    require(digest(identity) == manifest["common_binding"]["canonical_sha256"] == COMMON_SHA, "COMMON_HASH")
    require(set(manifest["cell_bindings"]) == CELLS, "CELL_SET")
    cells = list(manifest["cell_bindings"].values())
    require(len({canonical_bytes(x) for x in cells}) == 1, "CELL_BINDINGS_NOT_IDENTICAL")
    for cell in cells:
        require(cell == manifest["common_binding"], "CELL_FULL_IDENTITY_MISMATCH")
    pins = manifest["unresolved_pins"]
    require([x["pin"] for x in pins] == ["tool_roster", "time_window", "final_grants"], "PENDING_PINS")
    require(manifest["countable"] is False and not any(manifest["effects"].values()) and not any(manifest["dependencies"].values()), "NONCOUNTABLE_EFFECTS")
    validate_semantics(manifest, artifacts)
    return {"common_binding": {"canonical_utf8_bytes": COMMON_BYTES, "canonical_sha256": COMMON_SHA}, "artifacts": {name: {"path": value["path"], "bytes": value["bytes"], "sha256": value["sha256"], "content_sha256": value["content_sha256"]} for name, value in rebuilt.items()}}


def expect_failure(name: str, action: Any) -> str:
    try: action()
    except (VerificationError, UnicodeError, ValueError, TypeError, OSError): return "PASS_DENIED"
    raise AssertionError("adversary accepted: " + name)


def reseal_manifest(manifest: Mapping[str, Any], new_ref: Mapping[str, Any]) -> Dict[str, Any]:
    bad = copy.deepcopy(manifest)
    identity = bad["common_binding"]["identity"]
    identity["artifacts"]["payload"] = dict(new_ref)
    b = canonical_bytes(identity)
    bad["common_binding"]["canonical_utf8_bytes"] = len(b)
    bad["common_binding"]["canonical_sha256"] = hashlib.sha256(b).hexdigest()
    for cell in bad["cell_bindings"]: bad["cell_bindings"][cell] = copy.deepcopy(bad["common_binding"])
    return bad


def run_adversaries(manifest: Mapping[str, Any]) -> Dict[str, str]:
    results: Dict[str, str] = {}
    results["duplicate_key"] = expect_failure("duplicate_key", lambda: strict_loads(b'{"x":1,"x":2}'))
    results["invalid_utf8"] = expect_failure("invalid_utf8", lambda: strict_loads(b'{"x":"\xff"}'))
    results["nonfinite_json"] = expect_failure("nonfinite_json", lambda: strict_loads(b'{"x":NaN}'))
    expected = EXPECTED["payload"]["path"]
    source = ROOT / expected
    temporary = Path(tempfile.mkdtemp(prefix="adversary-", dir=PACKAGE)); os.chmod(temporary, 0o700)
    try:
        copy_path = temporary / "payload-copy.json"; shutil.copyfile(source, copy_path); os.chmod(copy_path, 0o600)
        relative = copy_path.relative_to(ROOT).as_posix()
        results["same_byte_absolute_path"] = expect_failure("same_byte_absolute_path", lambda: validate_locator(str(copy_path), expected))
        results["alternate_same_byte_relative_path"] = expect_failure("alternate_same_byte_relative_path", lambda: validate_locator(relative, expected))
        labeled_dir = temporary / "claude-model-addon-order-private-internal"; labeled_dir.mkdir(mode=0o700)
        labeled = labeled_dir / "payload.json"; shutil.copyfile(source, labeled); os.chmod(labeled, 0o600)
        labeled_rel = labeled.relative_to(ROOT).as_posix()
        results["labeled_same_byte_relative_path"] = expect_failure("labeled_same_byte_relative_path", lambda: validate_locator(labeled_rel, expected))
        symlink = temporary / "payload-symlink.json"; symlink.symlink_to(source)
        symlink_rel = symlink.relative_to(ROOT).as_posix()
        results["symlink_alias"] = expect_failure("symlink_alias", lambda: secure_read_workspace_path(symlink_rel, 0o644))
        real_dir = temporary / "real"; real_dir.mkdir(mode=0o700); inner = real_dir / "payload.json"; shutil.copyfile(source, inner); os.chmod(inner, 0o600)
        link_dir = temporary / "linkdir"; link_dir.symlink_to(real_dir, target_is_directory=True)
        link_rel = (link_dir / "payload.json").relative_to(ROOT).as_posix()
        results["symlink_intermediate"] = expect_failure("symlink_intermediate", lambda: secure_read_workspace_path(link_rel, 0o600))
        results["case_variant"] = expect_failure("case_variant", lambda: validate_locator("Mentor/" + expected.split("/", 1)[1], expected))
        fullwidth = expected.replace("mentor", "mentｏr", 1)
        results["normalization_variant"] = expect_failure("normalization_variant", lambda: validate_locator(fullwidth, expected))
        results["traversal_variant"] = expect_failure("traversal_variant", lambda: validate_locator(ALLOWED_ROOT + "/../" + source.name, expected))
        ref = copy.deepcopy(manifest["common_binding"]["identity"]["artifacts"]["payload"])
        ref["path"] = labeled_rel; ref["normalized_path"] = labeled_rel; ref["mode"] = "0600"
        bad = reseal_manifest(manifest, ref)
        require(bad["common_binding"]["canonical_sha256"] != COMMON_SHA, "RESEAL_DIGEST_DID_NOT_CHANGE")
        results["path_digest_resealing"] = expect_failure("path_digest_resealing", lambda: validate_manifest(bad, False))
        results["wrong_mode"] = expect_failure("wrong_mode", lambda: secure_read_workspace_path(relative, 0o644))
        results["nonregular_final"] = expect_failure("nonregular_final", lambda: secure_read_workspace_path(temporary.relative_to(ROOT).as_posix(), 0o700))
        fake = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=os.getuid() + 1)
        results["wrong_owner"] = expect_failure("wrong_owner", lambda: verify_final_stat(fake, 0o644))
    finally:
        shutil.rmtree(temporary)
    return results


def main() -> int:
    manifest = strict_load(MANIFEST)
    positive = validate_manifest(manifest)
    adversaries = run_adversaries(manifest)
    result = {"version": "r6-data-quality-exact-input-verification-v2", "status": "PASS_PATH_BOUND_PROVIDER_FREE_NONCOUNTABLE", "strict_json_and_schema": "PASS", "positive_checks": positive, "adversarial_checks": adversaries, "adversarial_passed": sum(v == "PASS_DENIED" for v in adversaries.values()), "adversarial_total": len(adversaries), "effects": {"provider": False, "network": False, "account": False, "private_state": False, "email": False, "business": False, "host": False, "scheduler": False}, "countable": False}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
