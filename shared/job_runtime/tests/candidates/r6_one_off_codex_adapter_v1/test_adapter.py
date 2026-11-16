from __future__ import annotations
import copy
from pathlib import Path
import smtplib
import socket
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.request
from shared.job_runtime.candidates.r6_one_off_codex_adapter_v1 import FakeCodexBoundary, execute_stage_a, stage_a_template, validate_stage_a_template
from shared.job_runtime.candidates.r6_one_off_codex_adapter_v1.contracts import ContractError
ROOT = Path(__file__).resolve().parents[5]
FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_codex_adapter_v1"

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.template = stage_a_template("a" * 64, "opaque-ref://codex/current")
        self.temp = tempfile.TemporaryDirectory(dir=FIX)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.serial = 0
    def run_case(self, scenario="nominal", boundary=None, template=None):
        self.serial += 1; forbidden = AssertionError("external effect attempted")
        with mock.patch.object(socket,"socket",side_effect=forbidden), mock.patch.object(socket,"create_connection",side_effect=forbidden), mock.patch.object(subprocess,"Popen",side_effect=forbidden), mock.patch.object(subprocess,"run",side_effect=forbidden), mock.patch.object(subprocess,"call",side_effect=forbidden), mock.patch.object(urllib.request,"urlopen",side_effect=forbidden), mock.patch.object(smtplib,"SMTP",side_effect=forbidden):
            return execute_stage_a(self.root/(scenario+str(self.serial)), template or self.template, boundary or FakeCodexBoundary(), scenario)
    def test_nominal_exact_once_and_second_admission_rejected(self):
        boundary=FakeCodexBoundary(); result=self.run_case(boundary=boundary)
        self.assertEqual(result.evidence["outcome"],"PASS"); self.assertEqual((boundary.membership_checks,boundary.inference_requests),(1,1))
        self.assertEqual(result.evidence["admission_count"],1); self.assertEqual(result.shared_execution.evidence["counters"]["admission_stop"],1)
        self.assertFalse(result.evidence["countable_observation"]); self.assertTrue(all(v==0 for v in result.evidence["effects"].values()))
    def test_all_preflight_stops_have_zero_upstream(self):
        for name in ("auth_stop","account_stop","cost_stop","window_stop","config_stop","custody_stop","secret_stop","sealed_input_drift"):
            result=self.run_case(name); self.assertEqual(result.evidence["outcome"],"STOP",name); self.assertEqual(result.evidence["upstream_attempt_count"],0,name)
    def test_catalog_absent_duplicate_and_malformed_stop_once(self):
        for raw in (b"other\n",b"gpt-6.1-sol\ngpt-6.1-sol\n",b"\xff"):
            boundary=FakeCodexBoundary(catalog=raw); result=self.run_case("catalog",boundary)
            self.assertEqual(result.evidence["outcome"],"STOP"); self.assertEqual((boundary.membership_checks,boundary.inference_requests),(1,0))
    def test_ambiguity_terminal_cleanup_publication_are_unknown_no_replay(self):
        for name in ("post_admission_unknown","terminal_fault","cleanup_failure","publication_failure"):
            boundary=FakeCodexBoundary(terminal="truncated",cleanup="fault"); result=self.run_case(name,boundary)
            self.assertEqual(result.evidence["outcome"],"UNKNOWN"); self.assertEqual((result.evidence["retry_count"],result.evidence["replay_count"],result.evidence["provider_status_calls"],result.evidence["reconstruction_dispatch"]),(0,0,0,0)); self.assertEqual(boundary.inference_requests,1)
    def test_stage_a_closed_permanently_nonauthorizing_and_secret_free(self):
        for field,value,code in (("enabled",True,"STAGE_A_AUTHORITY_INVALID"),("provider_authorized",True,"STAGE_A_AUTHORITY_INVALID"),("model","other","STAGE_A_TREATMENT_INVALID"),("codex_subcap_usd",.02,"CAP_INVALID")):
            bad=copy.deepcopy(self.template); bad[field]=value
            with self.assertRaisesRegex(ContractError,code): validate_stage_a_template(bad)
        bad=copy.deepcopy(self.template); bad["extra"]=1
        with self.assertRaisesRegex(ContractError,"STAGE_A_KEYS_INVALID"): validate_stage_a_template(bad)
        bad=copy.deepcopy(self.template); bad["credential_reference"]="secret_value/cleartext"
        with self.assertRaises(ContractError): validate_stage_a_template(bad)
if __name__=="__main__": unittest.main()
