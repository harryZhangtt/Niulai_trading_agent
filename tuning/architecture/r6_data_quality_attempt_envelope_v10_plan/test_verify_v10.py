from __future__ import annotations
import copy, hashlib, json, os, subprocess, sys, unittest
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_v10 as v
class V10DesignTests(unittest.TestCase):
    def snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()}
    def test_structure_valid_but_pending(self):
        artifacts, pins = v.verify_structure()
        self.assertEqual(artifacts['decision']['status'], v.STATUS)
        self.assertEqual(len(pins), 16)
        self.assertIn('p0_v10_contract_bytes_sha256', pins)
        self.assertIn('p0_v10_fresh_independent_review_bytes_sha256', pins)
        self.assertIn('claude_boundary_v9_evidence_only_contract_closure_producer_and_clean_review_bytes_sha256', pins)
        self.assertIn('blind_map_v6_contract_closure_producer_and_clean_review_bytes_sha256', pins)
        self.assertIn('execution_window_v2_template_closure_and_review_bytes_sha256', pins)
        self.assertIn('runner_v3_contract_closure_producer_and_clean_review_bytes_sha256', pins)
    def test_default_verifier_fails_with_exact_unresolved_list_and_no_writes(self):
        before = self.snapshot()
        env = dict(os.environ); env['PYTHONDONTWRITEBYTECODE'] = '1'
        run = subprocess.run([sys.executable, str(HERE/'verify_v10.py')], cwd=str(HERE), env=env, text=True, capture_output=True, check=False)
        self.assertEqual(run.returncode, 2, run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload['status'], 'FAIL_UNRESOLVED_PINS')
        self.assertEqual(payload['unresolved_pins'], v.load(HERE/'acceptance-v10.json')['unresolved_pins'])
        self.assertEqual(before, self.snapshot())
    def test_structure_only_is_not_promotion(self):
        run = subprocess.run([sys.executable, str(HERE/'verify_v10.py'), '--structure-only'], text=True, capture_output=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload['status'], 'STRUCTURE_VALID_DESIGN_ONLY')
        self.assertEqual(payload['design_status'], v.STATUS)
    def test_closure_drift_is_detected(self):
        graph = copy.deepcopy(v.load(HERE/'source-graph-v10.json'))
        graph['nodes'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(v.VerificationError, 'CLOSURE_DRIFT:AGGREGATE'):
            v.verify_source_graph(graph)
    def test_conditional_and_identity_contracts(self):
        schemas = v.load(HERE/'schemas-v10.json')
        v.verify_schemas(schemas)
        cond = schemas['$defs']['checks_enabled_dq_checks_conditional']['allOf'][0]
        self.assertEqual(set(cond), {'if','then','else'})
        caller = schemas['$defs']['public_caller_input_no_provider_identity']['properties']
        self.assertNotIn('provider_identity', caller)
        self.assertEqual(schemas['$defs']['owner_uid_bound_artifact_ref']['properties']['owner_uid'], {'const':501})
        self.assertEqual(schemas['$defs']['runner_v2_public_predecessor_identity']['properties']['history_status'], {'const':'OPEN'})
    def test_predecessor_and_open_review_are_distinct(self):
        graph = v.load(HERE/'source-graph-v10.json')
        self.assertEqual(graph['anchors']['p0_v9_clean_review']['verdict'], 'CLEAN_P0_V9')
        self.assertEqual(graph['anchors']['runner_v8_open_review']['verdict'], 'OPEN')
        self.assertEqual(graph['anchors']['p0_embedded_v8_open_review']['verdict'], 'OPEN')
        self.assertEqual(graph['anchors']['blind_map_v5_historical_review_revoked']['current_status'], 'CONTRADICTED_HISTORY_ONLY_BY_13_FINDING_OPEN_REVIEW')
        self.assertEqual(graph['anchors']['blind_map_v5_open_review_revoking_clean']['verdict'], 'OPEN')
        self.assertEqual(graph['anchors']['blind_map_v5_open_review_revoking_clean']['finding_count'], 13)
        self.assertEqual(graph['successor_requirements']['blind_map_v6']['status'], 'UNRESOLVED_CONTRACT_CLOSURE_PRODUCER_AND_CLEAN_REVIEW')
        self.assertEqual(graph['successor_requirements']['execution_window_v2']['status'], 'UNRESOLVED_V2_TEMPLATE_CLOSURE_AND_REVIEW')
        self.assertEqual(graph['anchors']['codex_v6_clean_review']['verdict'], 'CLEAN_CODEX_LIVE_BOUNDARY_V6_PENDING_P0_V10')
        self.assertEqual(graph['successor_requirements']['codex_boundary_v6']['status'], 'CLEAN_CONSUMER_READY_FOR_FINAL_CLOSURE_LAST')
        self.assertEqual(graph['anchors']['claude_v8_open_review']['verdict'], 'OPEN')
        self.assertEqual(graph['anchors']['claude_v8_open_review']['technical_parity'], 'PASS')
        self.assertEqual(graph['successor_requirements']['claude_evidence_only_v9']['status'], 'UNRESOLVED_CONTRACT_CLOSURE_PRODUCER_AND_CLEAN_REVIEW')
        self.assertEqual(graph['anchors']['runner_v2_open_review']['verdict'], 'OPEN')
        self.assertIn('OPEN-P0-V9-G3-SCHEMA-002', graph['anchors']['runner_v2_open_review']['findings'])
        self.assertEqual(graph['successor_requirements']['runner_v3']['status'], 'UNRESOLVED_CONTRACT_CLOSURE_PRODUCER_AND_CLEAN_REVIEW')
if __name__ == '__main__': unittest.main()
