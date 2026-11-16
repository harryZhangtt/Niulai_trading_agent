from __future__ import annotations
import hashlib, json, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0,str(ROOT))
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v2 import constants as C
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v2 import engine
STATUS='DISABLED_PROVIDER_FREE_PENDING_GRANTS_CLEAN_P0_V10_AND_FRESH_REVIEW'
TUNING=ROOT/'tuning/architecture/r6_claude_metadata_preflight_v2'

class ArtifactTests(unittest.TestCase):
    def test_all_architecture_artifacts_remain_disabled(self):
        for name in ('architecture-v2.json','protocol-v2.json','decision-v2.json','source-closure-v2.json','producer-verification-v2.json'):
            value=json.loads((TUNING/name).read_text())
            self.assertEqual(value['status'],STATUS,name)
            self.assertIs(value['activation'],False,name)
            self.assertIs(value['registration'],False,name)
            self.assertEqual(value['live_effects'],0,name)
            self.assertEqual(value['v1_open_review'],{'path':'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-claude-metadata-preflight-v1-independent-review-open-fable-20261115-a0efa3e1.json','bytes':13066,'sha256':'548ae003bf8a29f21b60753942b3414895c058daf68b9a656839d7b0fad319b5','verdict':'OPEN','findings_total':6,'closed':5,'open':1,'open_finding':'R6-CLAUDE-METADATA-PREFLIGHT-V1-005','terminal':'OPEN_HELD_BINARY_CLEANUP_REQUIRED'},name)

    def test_future_gates_bind_v9_clean_and_leave_p0_v10_unresolved(self):
        pending=('auth_grant','auth_grant_review','catalog_grant','catalog_grant_review','p0_v10_clean')
        self.assertTrue(all(C.FUTURE_AUTHORITY[name]['bytes'] is None and C.FUTURE_AUTHORITY[name]['sha256'] is None for name in pending))
        self.assertEqual(C.FUTURE_AUTHORITY['claude_v9_clean_review'],{'path':C.CURRENT_V9_CLEAN_REVIEW_REF[0],'bytes':10250,'sha256':'fb7fbe185b6b403aa67cd8bfeb64bdc9baf636c7788b39cd6fba6258f48e515f'})
        review_path=ROOT/C.CURRENT_V9_CLEAN_REVIEW_REF[0]; raw=review_path.read_bytes()
        self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),C.CURRENT_V9_CLEAN_REVIEW_REF[1:])
        self.assertEqual(json.loads(raw)['verdict'],'CLEAN_CLAUDE_LIVE_BOUNDARY_V9_EVIDENCE_RESEAL_PENDING_P0_V10')

    def test_v1_open_history_remains_exact_and_unmodified(self):
        refs={
            'shared/job_runtime/candidates/r6_claude_metadata_preflight_v1/engine.py':(20814,'1fdb98ffce6f4301a87a0da9c381874118146a0ba44badb9b8cf28c49979d00d'),
            'shared/job_runtime/candidates/r6_claude_metadata_preflight_v1/constants.py':(4958,'6a225f7f927cf3044d876d8b84443ac4d14d6034b652ccdfa66cef6e984f3f69'),
            'tuning/architecture/r6_claude_metadata_preflight_v1/decision-v1.json':(1860,'50102d09c0cd21910fe70e44886f0a3867a1ff4496b31f805967c10fb11ce5c0'),
            'tuning/architecture/r6_claude_metadata_preflight_v1/source-closure-v1.json':(9735, '0fb58c599583eeb79832732b01048dd0fdb5b65abdaedf0a492fa5d2a1f17384'),
            'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-claude-metadata-preflight-v1-independent-review-open-fable-20261115-a0efa3e1.json':(13066,'548ae003bf8a29f21b60753942b3414895c058daf68b9a656839d7b0fad319b5'),
        }
        for name,expected in refs.items():
            raw=(ROOT/name).read_bytes(); self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),expected,name)
        review=json.loads((ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v8-independent-review-open-fable-20261113-8e9a8076.json').read_bytes())
        self.assertEqual(review['verdict'],'OPEN')

    def test_parser_and_fixed_fixture_authority_are_exact(self):
        for ref in (C.CATALOG_PARSER_REF,C.CATALOG_PARSER_REVIEW_REF):
            raw=(ROOT/ref[0]).read_bytes()
            self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),ref[1:])
        self.assertEqual(engine._verify_test_authority(),engine._REGISTRY.sha256)
        self.assertNotIn('authority',engine._runtime_for_test.__annotations__)

    def test_source_closure_exact(self):
        closure=json.loads((TUNING/'source-closure-v2.json').read_text())
        digests=[]
        for item in closure['members']:
            raw=(ROOT/item['path']).read_bytes()
            self.assertEqual(len(raw),item['bytes'],item['path'])
            digest=hashlib.sha256(raw).hexdigest(); self.assertEqual(digest,item['sha256'],item['path'])
            digests.append(digest)
        aggregate=hashlib.sha256(('\n'.join(digests)+'\n').encode()).hexdigest()
        self.assertEqual(aggregate,closure['aggregate_sha256'])

if __name__=='__main__': unittest.main()
