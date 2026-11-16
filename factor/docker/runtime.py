"""Fail-closed Docker argv and static readiness policy for factor workloads."""
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "factor/docker/policy.json"
IMAGE_LOCK_PATH = ROOT / "factor/docker/image-lock.json"
DIGEST_IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")


class DockerPolicyError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise DockerPolicyError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read_json(path):
    value = json.loads(Path(path).read_text())
    require(isinstance(value, dict), "DOCKER_POLICY_JSON_INVALID")
    return value


def validate_policy(policy):
    require(policy.get("schema_version") == 1 and policy.get("status") == "development-only-blocked",
            "DOCKER_POLICY_STATUS_INVALID")
    require(policy.get("base", {}).get("manifest_digest") ==
            "sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370",
            "DOCKER_BASE_DIGEST_INVALID")
    require(policy.get("engine", {}).get("rdagent_revision") ==
            "484776c211e4fbbeef03e0ec00d6bbee7362a4f4" and
            policy.get("engine", {}).get("qlib_revision") ==
            "2fb9380b342556ddb50a4b24e4fe8655d548b2b8" and
            policy.get("engine", {}).get("standalone_qlib_allowed") is False,
            "DOCKER_ENGINE_IDENTITY_INVALID")
    require(policy.get("identity") == {"uid": 65532, "gid": 65532},
            "DOCKER_USER_POLICY_INVALID")
    require(policy.get("executor", {}).get("network") == "none" and
            policy.get("controller", {}).get("network") == "factor-provider-internal",
            "DOCKER_NETWORK_POLICY_INVALID")
    return policy


def validate_image_lock(image_lock, policy):
    require(image_lock.get("schema_version") == 1, "DOCKER_IMAGE_LOCK_SCHEMA")
    require(image_lock.get("policy_sha256") == hashlib.sha256(canonical(policy)).hexdigest(),
            "DOCKER_IMAGE_POLICY_MISMATCH")
    if image_lock.get("status") != "accepted":
        raise DockerPolicyError("DOCKER_IMAGE_LOCK_UNACCEPTED")
    images = {}
    for role in ("controller", "executor"):
        item = image_lock.get(role)
        require(isinstance(item, dict) and DIGEST_IMAGE.fullmatch(item.get("image", "")) and
                re.fullmatch(r"sha256:[a-f0-9]{64}", item.get("manifest_digest", "")) and
                re.fullmatch(r"[a-f0-9]{64}", item.get("lock_sha256", "")) and
                re.fullmatch(r"[a-f0-9]{64}", item.get("sbom_sha256", "")) and
                re.fullmatch(r"[a-f0-9]{64}", item.get("provenance_sha256", "")),
                "DOCKER_IMAGE_IDENTITY_INVALID")
        images[role] = item["image"]
    return images


def readiness(docker_path=None):
    policy = validate_policy(read_json(POLICY_PATH))
    image_lock = read_json(IMAGE_LOCK_PATH)
    blockers = list(policy.get("blockers", [])) + list(image_lock.get("blockers", []))
    if docker_path is None or not Path(docker_path).is_absolute() or not Path(docker_path).exists():
        blockers.append("docker-cli-unavailable")
    if image_lock.get("status") != "accepted":
        blockers.append("image-lock-unaccepted")
    return {"schema_version": 1, "status": "blocked" if blockers else "ready",
            "policy_sha256": hashlib.sha256(canonical(policy)).hexdigest(),
            "blockers": sorted(set(blockers))}


def _path(value, code):
    path = Path(value)
    require(path.is_absolute() and "," not in str(path) and "\n" not in str(path), code)
    return str(path)


def _identity(run_id, attempt, role):
    require(isinstance(run_id, str) and NAME.fullmatch(run_id) and type(attempt) is int and
            1 <= attempt <= 99, "DOCKER_RUN_ID_INVALID")
    return f"factor-{role}-{run_id}-{attempt}"


def _base_argv(name, policy, image):
    require(DIGEST_IMAGE.fullmatch(image), "DOCKER_IMAGE_IDENTITY_INVALID")
    limits = policy["controller" if "ctl" in name else "executor"]
    return ["docker", "run", "--name", name, "--init", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges=true", "--user", "65532:65532",
            "--pids-limit", str(limits["pids"]), "--cpus", limits["cpus"],
            "--memory", limits["memory"], "--memory-swap", limits["memory"],
            "--ulimit", f"nproc={limits['pids']}:{limits['pids']}",
            "--ulimit", "core=0:0", "--stop-timeout", "10"]


def controller_argv(run_id, attempt, request_path, output_path, image, *, feedback_path=None):
    policy = validate_policy(read_json(POLICY_PATH))
    name = _identity(run_id, attempt, "ctl")
    argv = _base_argv(name, policy, image)
    argv += ["--network", policy["controller"]["network"],
             "--mount", f"type=bind,src={_path(request_path, 'DOCKER_REQUEST_PATH_INVALID')},dst=/run/input/request.json,readonly"]
    command = "prepare"
    if feedback_path is not None:
        argv += ["--mount", f"type=bind,src={_path(feedback_path, 'DOCKER_FEEDBACK_PATH_INVALID')},dst=/run/input/feedback.json,readonly"]
        command = "feedback"
    argv += ["--mount", f"type=bind,src={_path(output_path, 'DOCKER_OUTPUT_PATH_INVALID')},dst=/run/output",
             "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={policy['controller']['tmpfs_mb']}m",
             "--tmpfs", "/home/runner:rw,noexec,nosuid,nodev,size=64m",
             "--env", "PROVIDER_BASE_URL=http://provider-proxy:8080/v1", image,
             command, "--request", "/run/input/request.json", "--output", "/run/output"]
    return argv


def executor_argv(run_id, attempt, request_path, bundle_path, dataset_path, output_path,
                  image, seccomp_path):
    policy = validate_policy(read_json(POLICY_PATH))
    name = _identity(run_id, attempt, "exec")
    argv = _base_argv(name, policy, image)
    argv += ["--network", "none", "--security-opt",
             f"seccomp={_path(seccomp_path, 'DOCKER_SECCOMP_PATH_INVALID')}",
             "--mount", f"type=bind,src={_path(request_path, 'DOCKER_REQUEST_PATH_INVALID')},dst=/run/input/request.json,readonly",
             "--mount", f"type=bind,src={_path(bundle_path, 'DOCKER_BUNDLE_PATH_INVALID')},dst=/run/input/bundle,readonly",
             "--mount", f"type=bind,src={_path(dataset_path, 'DOCKER_DATASET_PATH_INVALID')},dst=/run/input/dataset,readonly",
             "--mount", f"type=bind,src={_path(output_path, 'DOCKER_OUTPUT_PATH_INVALID')},dst=/run/output",
             "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={policy['executor']['tmpfs_mb']}m",
             "--tmpfs", "/home/runner:rw,noexec,nosuid,nodev,size=128m", image,
             "execute", "--request", "/run/input/request.json", "--bundle", "/run/input/bundle",
             "--dataset", "/run/input/dataset", "--output", "/run/output"]
    return argv
