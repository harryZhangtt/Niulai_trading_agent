from __future__ import annotations
import hashlib, json, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0,str(ROOT))
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v1 import constants as C
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v1 import engine
STATUS='DISABLED_PROVIDER_FREE_PENDING_CLAUDE_V8_P0_V10_GRANTS_AND_FRESH_REVIEW'
TUNING=ROOT/'tuning/architecture/r6_claude_metadata_preflight_v1'

class ArtifactTests(unittest.TestCase):
    def test_all_architecture_artifacts_remain_disabled(self):
        for name in ('architecture-v1.json','protocol-v1.json','decision-v1.json','source-closure-v1.json','producer-verification-v1.json'):
            value=json.loads((TUNING/name).read_text())
            self.assertEqual(value['status'],STATUS,name)
            self.assertIs(value['activation'],False,name)
            self.assertIs(value['registration'],False,name)
            self.assertEqual(value['live_effects'],0,name)

    def test_future_authority_is_absent_and_current_v8_is_open(self):
        self.assertTrue(all(item['bytes'] is None and item['sha256'] is None for item in C.FUTURE_AUTHORITY.values()))
        review_path=ROOT/C.CURRENT_V8_OPEN_REVIEW_REF[0]
        raw=review_path.read_bytes()
        self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),C.CURRENT_V8_OPEN_REVIEW_REF[1:])
        self.assertEqual(json.loads(raw)['verdict'],'OPEN')

    def test_parser_and_fixed_fixture_authority_are_exact(self):
        for ref in (C.CATALOG_PARSER_REF,C.CATALOG_PARSER_REVIEW_REF):
            raw=(ROOT/ref[0]).read_bytes()
            self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),ref[1:])
        self.assertEqual(engine._verify_test_authority(),engine._REGISTRY.sha256)
        self.assertNotIn('authority',engine._runtime_for_test.__annotations__)

    def test_source_closure_exact(self):
        closure=json.loads((TUNING/'source-closure-v1.json').read_text())
        digests=[]
        for item in closure['members']:
            raw=(ROOT/item['path']).read_bytes()
            self.assertEqual(len(raw),item['bytes'],item['path'])
            digest=hashlib.sha256(raw).hexdigest(); self.assertEqual(digest,item['sha256'],item['path'])
            digests.append(digest)
        aggregate=hashlib.sha256(('\n'.join(digests)+'\n').encode()).hexdigest()
        self.assertEqual(aggregate,closure['aggregate_sha256'])

if __name__=='__main__': unittest.main()
