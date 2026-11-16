import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from factor.docker import runtime, verify


ROOT = Path(__file__).resolve().parents[3]
CONTROLLER = "registry.example/factor-controller@sha256:" + "a" * 64
EXECUTOR = "registry.example/factor-executor@sha256:" + "b" * 64


class DockerRunnerTests(unittest.TestCase):
    def paths(self):
        base = ROOT / "factor/runtime/docker-tests"
        return [str((base / name).absolute()) for name in
                ("request.json", "output", "bundle", "dataset", "feedback.json")]

    def test_static_profile_is_verified_but_not_runnable(self):
        result = verify.verify()
        self.assertEqual(result["status"], "FACTOR_DOCKER_STATIC_OK")
        self.assertFalse(result["runnable"])
        self.assertIn("image-lock-unaccepted", result["blockers"])
        self.assertIn("docker-cli-unavailable", result["blockers"])

    def test_controller_argv_is_digest_only_nonroot_bounded_and_socket_free(self):
        request, output, _bundle, _dataset, feedback = self.paths()
        for argv in (runtime.controller_argv("run-a", 1, request, output, CONTROLLER),
                     runtime.controller_argv("run-a", 2, request, output, CONTROLLER,
                                             feedback_path=feedback)):
            joined = " ".join(argv)
            self.assertNotIn("--rm", argv)
            self.assertNotIn("docker.sock", joined)
            self.assertNotIn("API_KEY", joined)
            self.assertIn("--read-only", argv); self.assertIn("ALL", argv)
            self.assertIn("no-new-privileges=true", argv)
            self.assertIn("65532:65532", argv)
            self.assertIn("factor-provider-internal", argv)
            self.assertIn(CONTROLLER, argv)
            self.assertNotIn(":latest", joined)

    def test_executor_argv_has_no_network_and_exact_security_policy(self):
        request, output, bundle, dataset, _feedback = self.paths()
        seccomp = str((ROOT / "factor/docker/seccomp-executor.json").absolute())
        argv = runtime.executor_argv("run-a", 1, request, bundle, dataset, output,
                                     EXECUTOR, seccomp)
        joined = " ".join(argv)
        network = argv[argv.index("--network") + 1]
        self.assertEqual(network, "none")
        self.assertIn("--read-only", argv); self.assertIn("--cap-drop", argv)
        self.assertIn("no-new-privileges=true", argv)
        self.assertIn("65532:65532", argv); self.assertIn("--pids-limit", argv)
        self.assertIn("seccomp=" + seccomp, argv)
        self.assertNotIn("docker.sock", joined); self.assertNotIn("PROVIDER", joined)
        self.assertNotIn("--rm", argv); self.assertIn(EXECUTOR, argv)

    def test_tags_relative_paths_and_injection_are_rejected(self):
        request, output, bundle, dataset, _feedback = self.paths()
        seccomp = str((ROOT / "factor/docker/seccomp-executor.json").absolute())
        with self.assertRaisesRegex(runtime.DockerPolicyError, "IMAGE_IDENTITY"):
            runtime.executor_argv("run-a", 1, request, bundle, dataset, output,
                                  "registry/factor:latest", seccomp)
        with self.assertRaisesRegex(runtime.DockerPolicyError, "REQUEST_PATH"):
            runtime.controller_argv("run-a", 1, "relative/request.json", output, CONTROLLER)
        with self.assertRaisesRegex(runtime.DockerPolicyError, "RUN_ID"):
            runtime.controller_argv("../../bad", 1, request, output, CONTROLLER)
        with self.assertRaises(runtime.DockerPolicyError):
            runtime.controller_argv("run-a", 1, request + ",dst=/escape", output, CONTROLLER)

    def test_image_lock_cannot_be_accepted_without_complete_digest_evidence(self):
        policy = runtime.validate_policy(runtime.read_json(runtime.POLICY_PATH))
        lock = runtime.read_json(runtime.IMAGE_LOCK_PATH)
        with self.assertRaisesRegex(runtime.DockerPolicyError, "UNACCEPTED"):
            runtime.validate_image_lock(lock, policy)
        accepted = copy.deepcopy(lock); accepted["status"] = "accepted"
        accepted["blockers"] = []
        for role, image in (("controller", CONTROLLER), ("executor", EXECUTOR)):
            accepted[role] = {"image": image, "manifest_digest": image.split("@", 1)[1],
                              "linux_amd64_digest": "sha256:" + "c" * 64,
                              "linux_arm64_digest": "sha256:" + "d" * 64,
                              "lock_sha256": "e" * 64, "sbom_sha256": "f" * 64,
                              "provenance_sha256": "1" * 64}
        self.assertEqual(runtime.validate_image_lock(accepted, policy),
                         {"controller": CONTROLLER, "executor": EXECUTOR})

    def test_workers_expose_health_only_and_refuse_real_phases(self):
        cases = [("controller_worker.py", "health", 0, "source-only"),
                 ("controller_worker.py", "prepare", 2, "blocked"),
                 ("executor_worker.py", "health", 0, "source-only"),
                 ("executor_worker.py", "execute", 2, "blocked")]
        for worker, command, code, status in cases:
            result = subprocess.run([sys.executable, "-I", str(ROOT / "factor/docker/workers" / worker), command],
                                    capture_output=True, text=True, timeout=5)
            with self.subTest(worker=worker, command=command):
                self.assertEqual(result.returncode, code)
                self.assertEqual(json.loads(result.stdout)["status"], status)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
