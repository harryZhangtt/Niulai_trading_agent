import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from factor.docker.local import validator


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[4]


def bool_for_integer_mutations(value, path="$"):
    if isinstance(value, dict):
        for key, item in value.items():
            for changed_item, changed_path in bool_for_integer_mutations(item, f"{path}.{key}"):
                changed = copy.deepcopy(value)
                changed[key] = changed_item
                yield changed, changed_path
    elif isinstance(value, list):
        for index, item in enumerate(value):
            for changed_item, changed_path in bool_for_integer_mutations(item, f"{path}[{index}]"):
                changed = copy.deepcopy(value)
                changed[index] = changed_item
                yield changed, changed_path
    elif type(value) is int:
        yield True, path


def mutations(value, path="$", *, limit=None):
    """Yield one-leaf-at-a-time mutations, including empty containers."""
    produced = 0
    if isinstance(value, dict):
        for key, item in value.items():
            for changed_item, changed_path in mutations(item, f"{path}.{key}"):
                changed = copy.deepcopy(value)
                changed[key] = changed_item
                yield changed, changed_path
                produced += 1
                if limit is not None and produced >= limit:
                    return
        if not value:
            yield {"unexpected": True}, path
    elif isinstance(value, list):
        if not value:
            yield ["unexpected"], path
        else:
            for index, item in enumerate(value):
                for changed_item, changed_path in mutations(item, f"{path}[{index}]"):
                    changed = copy.deepcopy(value)
                    changed[index] = changed_item
                    yield changed, changed_path
    elif isinstance(value, bool):
        yield not value, path
    elif value is None:
        yield "unexpected-resolved-value", path
    elif isinstance(value, int):
        yield value + 1, path
    elif isinstance(value, float):
        yield value + 0.5, path
    elif isinstance(value, str):
        yield value + "-changed", path
    else:
        raise AssertionError(f"unhandled mutation type at {path}: {type(value)}")


class LocalDockerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = validator.load_json(ROOT / "runtime-profile.json")
        cls.services = validator.load_json(ROOT / "service-declarations.json")
        cls.sources = validator.load_json(ROOT / "source-inventory.json")

    def test_valid_fixtures_match_and_validate(self):
        fixtures = {
            "valid-runtime-profile.json": (self.profile, validator.validate_profile),
            "valid-service-declarations.json": (self.services, validator.validate_services),
            "valid-source-inventory.json": (self.sources, validator.validate_sources),
        }
        for name, (expected, validate) in fixtures.items():
            with self.subTest(name=name):
                value = validator.load_json(ROOT / "fixtures" / name)
                self.assertEqual(value, expected)
                self.assertIs(validate(value), value)

    def test_bundle_validates_and_is_apply_disabled(self):
        hashes = validator.validate_bundle()
        self.assertEqual(set(hashes), {
            "runtime-profile.json", "service-declarations.json", "source-inventory.json"
        })
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))
        self.assertFalse(self.profile["runnable"])
        self.assertFalse(self.profile["apply_allowed"])
        self.assertFalse(self.services["apply_allowed"])
        self.assertIsNone(self.services["compose_file"])

    def test_colima_home_profile_and_docker_context_are_workspace_scoped(self):
        host = self.profile["host_state"]
        self.assertEqual(host, validator.HOST_STATE)
        self.assertEqual(host["colima_environment"], {
            "COLIMA_HOME": "$WORKSPACE/factor/runtime/local/colima",
            "COLIMA_PROFILE": "factor-mining",
        })
        self.assertEqual(host["colima_config"], {"autoActivate": False})
        self.assertEqual(host["default_colima_home"], "~/.colima")
        self.assertEqual(host["default_colima_home_policy"], "prohibited-fail-closed")
        self.assertEqual(host["expected_docker_context"], "colima-factor-mining")
        self.assertEqual(host["context_discovery"],
                         "future-activation-discover-and-validate")
        self.assertFalse(host["change_global_current_docker_context"])
        self.assertEqual(host["docker_wrapper_required_args"],
                         ["--context", "colima-factor-mining"])
        probes = [
            "factor/runtime/local/colima/probe",
            "factor/runtime/local/cache/probe",
            "factor/runtime/local/runtime/probe",
        ]
        for probe in probes:
            result = subprocess.run(
                ["git", "check-ignore", "--quiet", "--", probe], cwd=WORKSPACE,
                check=False, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, f"not ignored: {probe}: {result.stderr}")
        unsafe = []
        default_home = copy.deepcopy(self.profile)
        default_home["host_state"]["colima_environment"]["COLIMA_HOME"] = "~/.colima"
        unsafe.append(default_home)
        global_context = copy.deepcopy(self.profile)
        global_context["host_state"]["change_global_current_docker_context"] = True
        unsafe.append(global_context)
        implicit_context = copy.deepcopy(self.profile)
        implicit_context["host_state"]["docker_wrapper_required_args"] = []
        unsafe.append(implicit_context)
        auto_activate = copy.deepcopy(self.profile)
        auto_activate["host_state"]["colima_config"]["autoActivate"] = True
        unsafe.append(auto_activate)
        for changed in unsafe:
            with self.assertRaises(validator.LocalContractError):
                validator.validate_profile(changed)

    def test_profile_capacity_platform_and_pressure_policy_are_exact(self):
        self.assertEqual(self.profile["platform"], {
            "provider": "colima", "container_runtime": "docker", "vm_type": "vz",
            "cpu": 6, "memory_bytes": 12 * 1024**3, "disk_bytes": 40 * 1024**3,
        })
        self.assertEqual(self.profile["capacity"], {
            "default_executor_concurrency": 1, "burst_executor_concurrency_max": 2,
            "burst_requires_explicit_authority": True, "autoscaling": False,
            "preemption": False, "assumptions_measured": False,
            "static_host_headroom_primary": True,
        })
        self.assertEqual(self.profile["orchestration"], {
            "compose_scaling": "explicit-only", "custom_pressure_daemon": False,
            "kubernetes": False, "swarm": False, "redis": False,
        })
        self.assertEqual(self.profile["pressure_policy"]["colima_stop_preconditions"],
                         ["queue-drained", "no-running-attempt", "no-unknown-attempt"])
        self.assertFalse(self.profile["pressure_policy"]["auto_shrink_running_memory"])

    def test_retry_restart_and_unknown_fence_are_exact(self):
        authority = self.profile["authority"]
        self.assertEqual(authority["lease_owner"], "engine")
        self.assertEqual(authority["retry_owner"], "engine")
        self.assertEqual(authority["max_retries_per_attempt"], 1)
        self.assertTrue(authority["retry_transient_only"])
        self.assertFalse(authority["permanent_failure_retry"])
        self.assertEqual(authority["unknown_outcome_action"],
                         "fence-and-reconcile-before-retry")
        self.assertEqual(authority["stable_service_restart"], "no")
        self.assertEqual(authority["attempt_service_restart"], "no")
        for service in self.services["stable"].values():
            self.assertEqual(service["restart"], "no")
            self.assertEqual(service["restart_owner"], "host-authority")
        for service in self.services["attempt"].values():
            self.assertEqual(service["restart"], "no")
            self.assertEqual(service["restart_owner"], "engine")

    def test_executor_containment_and_resources_are_exact(self):
        executor = self.services["attempt"]["executor"]
        self.assertEqual(executor["network_mode"], "none")
        self.assertTrue(executor["read_only_root"])
        self.assertEqual([item["target"] for item in executor["tmpfs"]], ["/tmp", "/run"])
        self.assertEqual(executor["mounts"], [])
        self.assertFalse(executor["docker_socket"])
        self.assertEqual(executor["secrets"], [])
        self.assertEqual(executor["cap_drop"], ["ALL"])
        self.assertEqual(executor["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(executor["resources"], {
            "cpu_hard": 2.0, "memory_hard_bytes": 4 * 1024**3,
            "memory_reservation_bytes": 2 * 1024**3,
            "memory_swap_bytes": 4 * 1024**3, "additional_swap_bytes": 0,
            "pids_limit": 512, "cpu_shares": 256,
        })

    def test_controller_and_logging_limits_are_exact(self):
        controller = self.services["stable"]["controller"]
        self.assertEqual(controller["resources"], {
            "cpu_hard": 1.0, "memory_hard_bytes": 1024**3,
            "memory_swap_bytes": 1024**3, "additional_swap_bytes": 0,
            "pids_limit": 512,
        })
        for group in (self.services["stable"], self.services["attempt"]):
            for service in group.values():
                resources = service["resources"]
                self.assertEqual(resources["pids_limit"], 512)
                self.assertEqual(resources["memory_swap_bytes"],
                                 resources["memory_hard_bytes"])
                self.assertEqual(resources["additional_swap_bytes"], 0)
                self.assertEqual(service["logging"], {
                    "driver": "local", "max_size": "10m", "max_files": 3,
                })
                self.assertEqual(service["replicas"], 1)
                self.assertEqual(service["scale_mode"], "explicit-only")
                self.assertEqual(service["mounts"], [])

    def test_future_io_network_lifecycle_and_image_contracts_are_closed(self):
        io = self.profile["future_io_contract"]
        self.assertEqual(io["active_mounts"], [])
        self.assertFalse(io["arbitrary_mounts"])
        self.assertFalse(io["docker_socket"])
        self.assertFalse(io["secrets"])
        self.assertEqual(set(io["closed_inputs"]), {"request", "bundle", "dataset"})
        for name, item in io["closed_inputs"].items():
            self.assertIsNone(item["source_identity"])
            self.assertEqual(item["destination"], f"/input/{name}")
            self.assertTrue(item["read_only"])
            self.assertFalse(item["allow_symlinks"])
            self.assertEqual(item["path_escape_policy"], "reject")
        promotion = io["output_promotion"]
        self.assertEqual(promotion["promotion_owner"], "engine")
        self.assertEqual(promotion["max_bytes"], 1024**3)
        self.assertIsNone(promotion["host_destination_root"])
        self.assertEqual(promotion["unknown_outcome_action"],
                         "fence-and-reconcile-before-promotion-or-retry")

        network = self.profile["future_network_contract"]
        self.assertEqual(network["network_identities"], {"internal": None, "egress": None})
        self.assertEqual(network["attachments"]["controller"], ["internal"])
        self.assertEqual(network["attachments"]["proxy"], ["internal", "egress"])
        for role in ("executor", "evaluator", "checker"):
            self.assertEqual(network["attachments"][role], [])
        self.assertFalse(network["policies"]["controller_egress_attachment"])
        self.assertFalse(network["policies"]["controller_bypass"])
        self.assertTrue(network["policies"]["proxy_is_sole_egress_bridge"])

        lifecycle = self.profile["stable_lifecycle_contract"]
        self.assertEqual(lifecycle["owner"], "host-authority")
        self.assertEqual(lifecycle["docker_restart_policy"], "no")
        self.assertEqual(lifecycle["max_restarts"], 3)
        self.assertEqual(lifecycle["backoff_seconds"], [5, 15, 45])
        self.assertEqual(lifecycle["restart_storm_action"],
                         "block-new-leases-fence-stable-services-and-reconcile")
        self.assertEqual(lifecycle["host_reconciliation"]["unknown_state_action"],
                         "fence-and-reconcile-before-restart")

        for role, image in self.profile["image_contracts"].items():
            self.assertTrue(image["linux_userspace_required"], role)
            self.assertEqual(image["oci_os"], "linux")
            self.assertIsNone(image["base_release"])
            self.assertIsNone(image["base_image_digest"])
            self.assertIsNone(image["oci_architecture"])
            self.assertIsNone(image["immutable_image_digest"])
            self.assertTrue(image["host_verifier_required"])
            self.assertTrue(image["in_image_verifier_is_additive"])
            self.assertIsNone(image["in_image_verifier_digest"])

    def test_recursive_type_exactness_rejects_bool_for_every_integer(self):
        contracts = [
            (self.profile, validator.validate_profile),
            (self.services, validator.validate_services),
            (self.sources, validator.validate_sources),
        ]
        tested = 0
        for value, validate in contracts:
            for changed, path in bool_for_integer_mutations(value):
                tested += 1
                with self.subTest(path=path), self.assertRaises(validator.LocalContractError):
                    validate(changed)
        self.assertGreaterEqual(tested, 45)
        autoscaling = copy.deepcopy(self.profile)
        autoscaling["capacity"]["autoscaling"] = 0
        with self.assertRaises(validator.LocalContractError):
            validator.validate_profile(autoscaling)
        socket = copy.deepcopy(self.services)
        socket["attempt"]["executor"]["docker_socket"] = 0
        with self.assertRaises(validator.LocalContractError):
            validator.validate_services(socket)

    def test_all_live_and_artifact_identities_are_null_blockers(self):
        self.assertTrue(all(value is None for value in self.profile["live_identity"].values()))
        self.assertTrue(all(value is None for value in
                            self.profile["artifacts"]["image_digests"].values()))
        self.assertIsNone(self.profile["artifacts"]["release_digest"])
        self.assertEqual(self.profile["blockers"], validator.BLOCKERS)
        for role in validator.ROLES:
            group = self.services["stable"] if role in validator.STABLE else self.services["attempt"]
            self.assertIsNone(group[role]["image_digest"])
            self.assertIn(group[role]["image_blocker"], self.profile["blockers"])

    def test_every_profile_leaf_is_machine_enforced(self):
        count = 0
        for changed, path in mutations(self.profile):
            count += 1
            with self.subTest(path=path), self.assertRaises(validator.LocalContractError):
                validator.validate_profile(changed)
        self.assertGreaterEqual(count, 60)

    def test_every_service_leaf_is_machine_enforced(self):
        count = 0
        for changed, path in mutations(self.services):
            count += 1
            with self.subTest(path=path), self.assertRaises(validator.LocalContractError):
                validator.validate_services(changed)
        self.assertEqual(count, 154)

    def test_every_source_inventory_leaf_is_machine_enforced(self):
        count = 0
        for changed, path in mutations(self.sources):
            count += 1
            with self.subTest(path=path), self.assertRaises(validator.LocalContractError):
                validator.validate_sources(changed)
        self.assertEqual(count, 53)

    def test_strict_json_rejects_duplicates_nonfinite_and_unknown_fields(self):
        with self.assertRaisesRegex(validator.LocalContractError, "DUPLICATE_KEY"):
            validator.load_json(ROOT / "fixtures" / "invalid" / "duplicate-key.json")
        with self.assertRaisesRegex(validator.LocalContractError, "NONFINITE"):
            validator.loads_strict('{"value": NaN}')
        changed = copy.deepcopy(self.profile)
        changed["credential"] = "synthetic-secret"
        with self.assertRaisesRegex(validator.LocalContractError, "PROFILE_CONTRACT"):
            validator.validate_profile(changed)

    def test_adversarial_fixtures_fail_closed(self):
        cases = [
            ("enabled-profile.json", validator.validate_profile),
            ("networked-executor.json", validator.validate_services),
            ("false-source-claim.json", validator.validate_sources),
        ]
        for name, validate in cases:
            with self.subTest(name=name), self.assertRaises(validator.LocalContractError):
                validate(validator.load_json(ROOT / "fixtures" / "invalid" / name))

    def test_schemas_close_every_object_and_match_contracts(self):
        instances = {
            "runtime-profile-v1.schema.json": self.profile,
            "service-declarations-v1.schema.json": self.services,
            "source-inventory-v1.schema.json": self.sources,
        }
        for name, instance in instances.items():
            schema = validator.load_json(ROOT / name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            body = {key: value for key, value in schema.items()
                    if key not in {"$schema", "$id"}}
            validator.validate_exact_schema(instance, body)
            stack = [body]
            while stack:
                node = stack.pop()
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                    stack.extend(node["properties"].values())

    def test_schema_weakening_is_rejected(self):
        schema = validator.load_json(ROOT / "runtime-profile-v1.schema.json")
        body = {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}
        body["additionalProperties"] = True
        with self.assertRaisesRegex(validator.LocalContractError, "NOT_CLOSED"):
            validator.validate_exact_schema(self.profile, body)

    def test_sources_are_official_references_but_not_live_evidence(self):
        self.assertFalse(self.sources["live_fetch_performed"])
        report = self.sources["coordinating_session_verification"]
        self.assertTrue(report["reported_live_verified"])
        self.assertFalse(report["exact_receipts_available_to_this_artifact"])
        self.assertFalse(report["receipt_urls_imported"])
        self.assertEqual(report["evidence_status"],
                         "reported-but-unavailable-not-adopted")
        self.assertIn("official-source-live-verification-receipts-unavailable",
                      self.profile["blockers"])
        self.assertGreaterEqual(len(self.sources["sources"]), 6)
        for source in self.sources["sources"]:
            self.assertTrue(source["official"])
            self.assertTrue(source["url"].startswith("https://"))
            self.assertFalse(source["live_fetched_in_task"])
            self.assertEqual(source["evidence_status"], "reference-not-live-verified")
            self.assertTrue(source["claims"])

    def test_cli_reports_hashes_without_runtime_action(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "factor.docker.local.validator"],
            cwd=WORKSPACE, check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["apply_allowed"])
        self.assertEqual(set(payload["sha256"]), {
            "runtime-profile.json", "service-declarations.json", "source-inventory.json"
        })


if __name__ == "__main__":
    unittest.main()
