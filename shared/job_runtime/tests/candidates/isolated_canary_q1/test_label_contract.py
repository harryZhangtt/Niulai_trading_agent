from pathlib import PurePosixPath
import json
import unittest

from _loader import submodule


class LabelContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = submodule("label_contract")
        cls.production = "com.local.trading-agent.job-runtime"

    def test_table_and_reserved_cases(self):
        fixture = json.loads((__import__('pathlib').Path(__file__).resolve().parents[2] / "fixtures" / "isolated_canary_q1" / "label-cases-v1.json").read_text())
        for value in fixture["valid"]:
            scope = self.m.label_scope(value, production_service_label=self.production)
            self.assertEqual(scope.watchdog_label, value + ".watchdog")
        for case in fixture["invalid"]:
            with self.subTest(case=case), self.assertRaisesRegex(self.m.CanaryContractError, f"^{case['code']}$"):
                self.m.label_scope(case["value"], production_service_label=self.production)

    def plan(self, label):
        return self.m.build_launchd_plan({"schema_version": 1, "service_label": label}, production_service_label=self.production, workspace=PurePosixPath("/fixture/workspace"), config_path=PurePosixPath("/fixture/workspace/.job-runtime/config/runtime.json"), python_bin=PurePosixPath("/fixture/workspace/.job-runtime/.venv/bin/python"), launcher_path=PurePosixPath("/fixture/workspace/shared/job_runtime/launcher.py"), uid=501, home_directory=PurePosixPath("/fixture/home"))

    def test_every_target_is_scope_bound_and_session_only(self):
        plan = self.plan("org.example.canary-a")
        a = self.m.as_closed_mapping(plan)
        text_a = json.dumps(a, sort_keys=True)
        self.assertNotIn("canary-b", text_a)
        self.assertNotIn(self.production + '"', text_a)
        self.assertEqual(plan.targets.watchdog_print_target, "gui/501/org.example.canary-a.watchdog")
        self.assertTrue(plan.targets.watchdog_bootstrap_path.endswith("org.example.canary-a.watchdog.plist"))
        self.assertEqual(plan.targets.watchdog_kill_target, plan.targets.watchdog_print_target)
        self.assertEqual(plan.targets.generate_paths, (plan.targets.install_bootstrap_paths[0], plan.targets.install_bootstrap_paths[1]))
        self.assertEqual(plan.targets.install_print_targets, plan.targets.status_targets)
        self.assertEqual(plan.targets.reload_target, plan.targets.status_targets[0])
        self.assertEqual(plan.targets.uninstall_targets, tuple(reversed(plan.targets.status_targets)))
        self.assertIn(plan.scope.service_label, plan.service_plist.program_arguments)
        self.assertIn(plan.scope.service_label, plan.watchdog_plist.program_arguments)
        self.assertIn(plan.scope.service_label, plan.service_plist.standard_out_path)
        self.assertIn(plan.scope.watchdog_label, plan.watchdog_plist.standard_out_path)
        self.assertEqual(plan.targets.persistent_links, ())
        with self.assertRaisesRegex(TypeError, "CANARY_IMMUTABLE"):
            a["schema_version"] = 2

    def test_pairwise_generated_labels_do_not_overlap(self):
        labels = [f"org.example.canary-{i}" for i in range(24)]
        scopes = [self.m.label_scope(x, production_service_label=self.production) for x in labels]
        for i, a in enumerate(scopes):
            own = {a.service_label, a.watchdog_label, a.service_plist_filename, a.watchdog_plist_filename}
            for j, b in enumerate(scopes):
                if i != j:
                    self.assertTrue(own.isdisjoint({b.service_label, b.watchdog_label, b.service_plist_filename, b.watchdog_plist_filename}))

    def test_path_controls_and_label_length(self):
        with self.assertRaisesRegex(self.m.CanaryContractError, "^CANARY_PLAN_PATH_INVALID$"):
            self.m.build_launchd_plan({"schema_version":1,"service_label":"org.example.canary"}, production_service_label=self.production, workspace=PurePosixPath("/fixture/workspace\nBAD"), config_path=PurePosixPath("/fixture/workspace/config"), python_bin=PurePosixPath("/fixture/workspace/python"), launcher_path=PurePosixPath("/fixture/workspace/launcher"), uid=1, home_directory=PurePosixPath("/fixture/home"))
        label = "a." + "b" * 63 + "." + "c" * 63 + "." + "d" * 63 + "." + "e" * 46
        self.assertEqual(len(label.encode()), 240)
        scope = self.m.label_scope(label, production_service_label=self.production)
        self.assertEqual(len(scope.watchdog_plist_filename.encode()), 255)

    def test_errors_never_echo_rejected_value(self):
        secret = "TOKEN_private/Path\n"
        try:
            self.m.label_scope(secret, production_service_label=self.production)
        except self.m.CanaryContractError as error:
            self.assertNotIn(secret, str(error))
            self.assertEqual(str(error), error.code)


if __name__ == "__main__":
    unittest.main()
