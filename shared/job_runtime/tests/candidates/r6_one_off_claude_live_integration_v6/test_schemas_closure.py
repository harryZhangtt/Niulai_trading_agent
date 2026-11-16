from __future__ import annotations
import ast, copy, hashlib, json, pathlib, tempfile, unittest, sys
ROOT=pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0,str(ROOT))
PKG=ROOT/'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v6'
TESTS=ROOT/'shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v6'
SCHEMAS=PKG/'schemas'
ARCH=ROOT/'tuning/architecture/r6_one_off_claude_live_integration_v6'
FIX=ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1'
REVIEW=ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v4-independent-review-20261111-001.json'
EXPECTED_HISTORY={'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/__init__.py': (221,
                                                                                     '9784ce03b5d67d831e0b7c2d3bc9749848b1c3166f7972361b60844970c0ae93'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/authority.py': (7279,
                                                                                      '5db4d9989efabf3363154f088978be835d86b56bab58002595a43f4c378bbbdb'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/contracts.py': (18874,
                                                                                      '4e7dbcd8bef492809541d3be0deb31b73e7c080a1de24c23afc9f91e618a6157'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/ferry.py': (3548,
                                                                                  '5d9a7d8aadd40ab157b669421664eccd320c3e6b35528bdef49e84e3acb8f1fe'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/process.py': (16455,
                                                                                    '72e5e61c38137618bf7ec96dd7e2b9d35210683b98381ffeb6131acb9573e2b3'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/runner.py': (19548,
                                                                                   '7a787b0a351f8038201ddbda85b4643b2e822eef8e2da7776a23e26abef340a1'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/schemas/p0-output-v5.schema.json': (862,
                                                                                                          '722a8f1f3829915fc9326a67e5218656fc6af8f6d98bc36adc6955d9574bfff6'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/schemas/pending-publication-v5.schema.json': (12138,
                                                                                                                    '1f2f0f165438715b0a030b2cba163ba595fc748c9274ba0aaba7420c70b8bcd2'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/schemas/post-run-seal-v5.schema.json': (11143,
                                                                                                              '91582be94cb7c896c5a9aa6c3ab03fe0de77ef17275b89018a79fb9c430cd210'),
 'shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5/schemas/unknown-fence-v5.schema.json': (11821,
                                                                                                              '0d8c50efef2af522d65bf12f9fee9d2f7b8f299472def406f00433ea1e8a02a3'),
 'shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v5/__init__.py': (72,
                                                                                           '40b2ca0c2915421f41a64439814059fff27b080496abded6e2dcc73aa498f7c4'),
 'shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v5/test_integration.py': (15235,
                                                                                                   'd95beffc16372d7870dbd20990a0dca5d319633b93a0768f0736d02cac67a9f4'),
 'shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v5/test_schemas_closure.py': (7842,
                                                                                                       'e3d248d2b98a7856a32d95aec5ad3a643a3f1f7e08f2ec3c44ba31580474c9d8'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/decision-v1.json': (1076,
                                                                                'b8915c0102b0e75dddbfb94a08c6dc5e414b3b6fb359d5230dc8fd382fa48913'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/decision-v2.json': (1057,
                                                                                '3d47ffd5b588fc9ad138d0f8538f42284c2108c451a143c49eac5fd3c9e6976e'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/decision-v3.json': (620,
                                                                                'd8dd42a53cc3ca9403698b908d26bbdf1c639d42675f55239eddb15dc6525ce2'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/decision-v4.json': (2434,
                                                                                '62a0e97123a3e4f98f244a819d216faec952b43c6685cfe26ca82536e8b944c3'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/decision-v5.json': (2538,
                                                                                '27672d01f2ef96c6dc5a7299f00666e4ae0ce035f0217767d5c401dad01b3562'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/experiment-v5.py': (609,
                                                                                'fff159ff385cd0888570d04899465dd11782de72e8ce797bb6de1f52c49aa15a'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/experiment.py': (539,
                                                                             'dec2118407dc64c0bde375f486bf494c5a9a081836eb4dbcd0289217265c03b5'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/producer-verification-v1-final.json': (3066,
                                                                                                   '7a2d053a8eb93c5ec60d2cf8bf1bd179637b3501db3bc3a0276e5ed98b66704e'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/producer-verification-v2-final.json': (3570,
                                                                                                   'be365e5b75ebe621ec98b0430c013518c12722f79b29f907199920dd0ab82ff4'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/producer-verification-v3-final.json': (2674,
                                                                                                   '3d551495380798099bb736af63414a510258f68067bef2ff399ae381d57757fa'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/producer-verification-v4-final.json': (6096,
                                                                                                   '030fb71dea665dd416b13fb3641fdf5b034cc1010baa1494ea64aff458434fe2'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/producer-verification-v5-final.json': (3355,
                                                                                                   'afe8472e690ee4cddea8df1b2241e7ad70650c00e27168166e7ec2d494862cce'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/protocol-v1.json': (3381,
                                                                                'b7cedfceb9430936c6aab0d6f0a3a8cfe5213bc71f3e0ff5261fe9c301ebc6c4'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/protocol-v2.json': (1259,
                                                                                '62f3b05a96f5d54736a232926cde9508637e5458b9a3b8e8275a7485bec26765'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/protocol-v3.json': (722,
                                                                                '76d7c53ace07305b8c81958263ba8d253e5f31a701c7404e8fc6cfd006cba967'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/protocol-v4.json': (2942,
                                                                                '053b5aa0875c558fae98d858007d877f65788433f17d4ac817bfd27159f1a1a5'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/protocol-v5.json': (2389,
                                                                                '75e0fe131783f9a95e3eef5bbe55dac0dc50710d2e6ae2653c2c348054d6fea6'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/source-closure-v1.json': (3775,
                                                                                      '49ec9f07d76f53963057ec2fc5479fe9dee1117a021d4fd7eb69482d22ce1b1f'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/source-closure-v2.json': (6355,
                                                                                      '93aae22985abedee97cdfef3c6f11674d210ea68055645701921d9031e024efb'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/source-closure-v3.json': (7484,
                                                                                      'f8554858dfcf442dc298d7c0779757b5e9124ce575cbd79ac36f795f855dc52e'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/source-closure-v4.json': (12229,
                                                                                      '23eb1182b9395140a3a83674c65b5824c76c2c3ca808afbcf21a1d3016024df3'),
 'tuning/architecture/r6_one_off_claude_live_integration_v1/source-closure-v5.json': (10912,
                                                                                      '0a2f1a7560f4fa329423cfc500463011a5d02b4b0b63f4b41f7a5e35560ac0bf')}

class SchemaClosureV6Tests(unittest.TestCase):
 def test_candidate_is_inert_and_has_no_provider_sdk_registration_or_bytedcli(self):
  for path in PKG.glob('*.py'):
   text=path.read_text(); tree=ast.parse(text); imports=[]
   for node in ast.walk(tree):
    if isinstance(node,ast.Import): imports += [item.name for item in node.names]
    elif isinstance(node,ast.ImportFrom): imports += [node.module or '']
   self.assertFalse(any(item.startswith(('requests','httpx','anthropic')) for item in imports))
   self.assertNotIn('bytedcli',text.lower())
  runtime=ROOT/'shared/job_runtime'
  self.assertFalse(any('r6_one_off_claude_live_integration_v6' in p.read_text() for p in runtime.glob('*.py')))

 def test_v1_through_v5_history_and_open_v4_review_are_byte_preserved(self):
  for rel,identity in EXPECTED_HISTORY.items():
   raw=(ROOT/rel).read_bytes(); self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),identity,rel)
  raw=REVIEW.read_bytes(); self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(11769,'e7eaf166d50a91a39d37cc043f1ee2932d633ca1688f5ab615efba3048720d96'))
  self.assertEqual(json.loads(raw)['verdict'],'OPEN')
  lineage=json.loads((ARCH/'lineage-v6.json').read_text())
  self.assertEqual(lineage['status'],'OPEN')
  self.assertEqual(lineage['v5_claim_disposition'],'CONTRADICTED_NEVER_RELY_AS_PASS')
  self.assertFalse(lineage['stopped_review_has_terminal_verdict'])

 def test_draft_2020_12_recursive_strictness_instances_and_contradictions(self):
  from jsonschema import Draft202012Validator
  def walk(value):
   if isinstance(value,dict):
    if value.get('type')=='object': self.assertIs(value.get('additionalProperties'),False)
    for child in value.values(): walk(child)
   elif isinstance(value,list):
    for child in value: walk(child)
  names=('post-run-seal-v6.schema.json','unknown-fence-v6.schema.json','pending-publication-v6.schema.json','p0-output-v6.schema.json')
  schemas={}
  for name in names:
   schema=json.loads((SCHEMAS/name).read_text()); Draft202012Validator.check_schema(schema); walk(schema); schemas[name]=schema
  from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import LocalOnlyProcessEffect,p0_output,run
  from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import runner
  with tempfile.TemporaryDirectory(dir=FIX) as temp:
   root=pathlib.Path(temp); passed=run(root/'pass',effect=LocalOnlyProcessEffect(True)); unknown=run(root/'unknown',effect=LocalOnlyProcessEffect(True),scenario='timeout')
   pass_pending=json.loads((root/'pass/public'/runner.PUBLIC_PENDING_NAME).read_text()); pass_marker=json.loads((root/'pass/public'/runner.PUBLIC_NAME).read_text())
   fence_pending=json.loads((root/'unknown'/runner.FENCE_PENDING_NAME).read_text()); fence_marker=json.loads((root/'unknown'/runner.FENCE_NAME).read_text())
  validators={name:Draft202012Validator(schema) for name,schema in schemas.items()}
  sealv=validators['post-run-seal-v6.schema.json']; markerv=validators['unknown-fence-v6.schema.json']; pendingv=validators['pending-publication-v6.schema.json']
  for value in (passed,unknown): sealv.validate(value)
  for value in (pass_marker,fence_marker): markerv.validate(value)
  for value in (pass_pending,fence_pending): pendingv.validate(value)
  validators['p0-output-v6.schema.json'].validate(p0_output(unknown))
  bad=[]
  for path,value in ((('process','descendants_reaped'),False),(('publication','readback_verified'),False),(('cleanup','exception_count'),1),(('state_authority','state'),'UNKNOWN')):
   item=copy.deepcopy(passed); item[path[0]][path[1]]=value; bad.append(item)
  item=copy.deepcopy(unknown); item['unknown_fence']['durability']='NON_DURABLE'; item['unknown_fence']['durable']=False; bad.append(item)
  item=copy.deepcopy(unknown); item['state_authority']['state']='PASS'; bad.append(item)
  item=copy.deepcopy(passed); item['state_authority']['extra']=True; bad.append(item)
  for item in bad: self.assertFalse(sealv.is_valid(item),item)
  item=copy.deepcopy(pass_marker); item['authoritative']=True; self.assertFalse(markerv.is_valid(item))
  item=copy.deepcopy(pass_pending); item['candidate_seal']['extra']=True; self.assertFalse(pendingv.is_valid(item))

 def test_closure_manifest_is_complete_for_every_v6_dependency(self):
  closure=json.loads((ARCH/'source-closure-v6.json').read_text())
  actual={str(p.relative_to(ROOT)) for base in (PKG,TESTS) for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
  authority={ref[0] for ref in __import__('shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6.authority',fromlist=['*']).__dict__.values() if isinstance(ref,tuple) and len(ref)==3 and isinstance(ref[0],str)}
  expected=actual|authority
  manifested={item['path'] for item in closure['artifacts']}
  self.assertEqual(manifested,expected)
  for item in closure['artifacts']:
   raw=(ROOT/item['path']).read_bytes(); self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(item['bytes'],item['sha256']))

if __name__=='__main__': unittest.main()
