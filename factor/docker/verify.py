"""Static verification for the blocked scalable factor Docker runner profile."""
import hashlib
import json
from pathlib import Path
import re

from . import runtime


ROOT = Path(__file__).resolve().parents[2]
BASE = "python:3.10-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370"


class DockerVerifyError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise DockerVerifyError(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_dockerfile(path, role):
    text = Path(path).read_text()
    from_lines = re.findall(r"^FROM\s+(?:--platform=\$TARGETPLATFORM\s+)?(\S+)", text, re.M)
    require(from_lines == [BASE], "DOCKERFILE_BASE_INVALID")
    require("USER 65532:65532" in text and
            re.search(r'^ENTRYPOINT \["/usr/local/bin/python", "-I", "/opt/factor/[a-z_]+\.py"\]$', text, re.M),
            "DOCKERFILE_IDENTITY_INVALID")
    require("--network=none" in text and "--require-hashes" in text and "--no-index" in text,
            "DOCKERFILE_OFFLINE_INSTALL_REQUIRED")
    lowered = text.lower()
    for forbidden in ("/var/run/docker.sock", "docker:dind", ":latest", "git clone", "curl |", "wget |"):
        require(forbidden not in lowered, "DOCKERFILE_FORBIDDEN_CONTENT")
    require(f"requirements/{role}.requirements.lock" in text and
            f"wheelhouse/{role}/" in text, "DOCKERFILE_ROLE_CONTEXT_INVALID")
    return {"path": str(Path(path).relative_to(ROOT)), "sha256": sha(path)}


def verify():
    policy = runtime.validate_policy(runtime.read_json(runtime.POLICY_PATH))
    lock = runtime.read_json(runtime.IMAGE_LOCK_PATH)
    require(lock.get("status") == "unresolved" and
            "dependency-locks-unresolved" in lock.get("blockers", []),
            "DOCKER_IMAGE_LOCK_SHOULD_BLOCK")
    require(lock.get("policy_sha256") == hashlib.sha256(runtime.canonical(policy)).hexdigest(),
            "DOCKER_IMAGE_POLICY_MISMATCH")
    require(lock.get("seccomp_sha256") == sha(ROOT / "factor/docker/seccomp-executor.json"),
            "DOCKER_SECCOMP_DIGEST_MISMATCH")
    require(lock.get("source_lock_sha256") == sha(ROOT / "factor/upstream/sources.lock.json"),
            "DOCKER_SOURCE_LOCK_DIGEST_MISMATCH")
    dockerfiles = [verify_dockerfile(ROOT / f"factor/docker/{role}.Dockerfile", role)
                   for role in ("controller", "executor")]
    for role in ("controller", "executor"):
        unresolved = runtime.read_json(ROOT / f"factor/docker/requirements/{role}.unresolved.json")
        require(unresolved.get("status") == "unresolved" and unresolved.get("role") == role,
                "DOCKER_DEPENDENCY_STATE_INVALID")
        require(not (ROOT / f"factor/docker/requirements/{role}.requirements.lock").exists(),
                "DOCKER_UNREVIEWED_LOCK_PRESENT")
    status = runtime.readiness()
    require(status["status"] == "blocked" and "image-lock-unaccepted" in status["blockers"] and
            "docker-cli-unavailable" in status["blockers"], "DOCKER_READINESS_MUST_BLOCK")
    return {"status": "FACTOR_DOCKER_STATIC_OK", "runnable": False,
            "dockerfiles": dockerfiles, "blockers": status["blockers"]}


def main():
    try:
        result = verify()
    except (DockerVerifyError, runtime.DockerPolicyError, OSError, ValueError, json.JSONDecodeError) as error:
        code = str(error) if isinstance(error, (DockerVerifyError, runtime.DockerPolicyError)) else "DOCKER_STATIC_VERIFY_FAILED"
        print(json.dumps({"status": "FACTOR_DOCKER_STATIC_FAILED", "code": code})); return 2
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
