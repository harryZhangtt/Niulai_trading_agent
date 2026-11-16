from dataclasses import replace
from pathlib import Path
import json
import unittest

from _loader import submodule


class BundleMonitorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = submodule("bundle")
        cls.m = submodule("monitor")
        data = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "isolated_canary_q1" / "valid" / "bundle-input-v1.json").read_text())
        cls.inputs = cls.b.CanaryInputsV1(**data)

    def test_bundle_is_deterministic_deeply_immutable_and_digest_bound(self):
        one = self.b.build_bundle(self.inputs)
        self.assertEqual(one, self.b.build_bundle(self.inputs)); self.b.validate_bundle(one)
        self.assertTrue(all(job["enabled"] is False and job["replay_contract"]["effect"] == "none" for job in one.allocation["jobs"]))
        self.assertIn(self.inputs.prompt_source_name, one.allocation["jobs"][0]["prompt_file"])
        with self.assertRaisesRegex(TypeError, "CANARY_IMMUTABLE"):
            one.config["max_workers"] = 2
        with self.assertRaisesRegex(self.b.BundleError, "^CANARY_BUNDLE_DIGEST_MISMATCH$"):
            self.b.render_documents(replace(one, bundle_sha256="0" * 64))

    def test_prompt_name_changes_bundle_and_invalid_name_fails(self):
        other = self.b.build_bundle(replace(self.inputs, prompt_source_name="other.txt"))
        self.assertNotEqual(self.b.build_bundle(self.inputs).bundle_sha256, other.bundle_sha256)
        with self.assertRaisesRegex(self.b.BundleError, "^CANARY_INPUT_INVALID$"):
            self.b.build_bundle(replace(self.inputs, prompt_source_name="../escape"))
        with self.assertRaisesRegex(self.b.BundleError, "^CANARY_INPUT_INVALID$"):
            self.b.CanaryInputsV1(7, 1, self.inputs.created_at, self.inputs.slot_01_at, self.inputs.slot_02_at, "prompt.txt", "a"*64, "b"*64, "c"*64)

    def base(self):
        return {"sequence": 1, "observed_at": "2030-01-01T00:10:00Z", "candidate_id": self.inputs.candidate_id, "bundle_sha256": "a" * 64, "workspace_identity_sha256": "b" * 64, "job_identity_sha256": None, "slot_ordinal": None, "attempt_ordinal": None, "event_type": "workspace_prepared", "slot_status": "ready", "code": "CANARY_DISABLED", "process_present": False, "label_present": False, "counts": {"claims": 0, "attempts": 0, "running": 0, "terminal": 0}}

    def test_monitor_requires_two_slot_terminals_and_preserves_aggregate(self):
        base = self.base(); first = self.m.make_monitor_event(base, None)
        slot1 = self.m.make_monitor_event({**base, "sequence":2, "observed_at":"2030-01-01T00:11:00Z", "job_identity_sha256":"c"*64, "slot_ordinal":1, "attempt_ordinal":1, "event_type":"slot_terminal", "slot_status":"succeeded", "code":"CANARY_FIXTURE_COMPLETED", "counts":{"claims":1,"attempts":1,"running":0,"terminal":1}}, first["event_sha256"])
        with self.assertRaisesRegex(self.m.MonitorError, "^CANARY_MONITOR_TERMINAL_INCOMPLETE$"):
            self.m.project_monitor([first, slot1])
        slot2 = self.m.make_monitor_event({**base, "sequence":3, "observed_at":"2030-01-01T00:12:00Z", "job_identity_sha256":"d"*64, "slot_ordinal":2, "attempt_ordinal":1, "event_type":"slot_terminal", "slot_status":"unknown", "code":"CANARY_PROCESS_EXITED_OUTCOME_UNKNOWN", "counts":{"claims":2,"attempts":2,"running":0,"terminal":2}}, slot1["event_sha256"])
        result = self.m.project_monitor([first, slot1, slot2])
        self.assertEqual((result["slot_terminal_count"], result["status"]), (2, "unknown"))
        with self.assertRaisesRegex(self.m.MonitorError, "^CANARY_MONITOR_EVENT_INVALID$"):
            self.m.make_monitor_event({**base, "event_type":"slot_terminal", "slot_status":"succeeded"}, None)

    def test_monitor_identity_secret_and_event_id_rejection(self):
        base=self.base(); first=self.m.make_monitor_event(base,None)
        with self.assertRaisesRegex(self.m.MonitorError, "^CANARY_MONITOR_SECRET_REJECTED$"):
            self.m.make_monitor_event({**base,"prompt":"secret"},None)
        tampered=dict(first); tampered["event_id"]="0"*24; tampered["event_sha256"]=submodule("canonical").canonical_sha256({k:v for k,v in tampered.items() if k!="event_sha256"})
        with self.assertRaisesRegex(self.m.MonitorError, "^CANARY_MONITOR_CHAIN_INVALID$"):
            self.m.validate_monitor_event(tampered,None)


if __name__ == "__main__": unittest.main()
