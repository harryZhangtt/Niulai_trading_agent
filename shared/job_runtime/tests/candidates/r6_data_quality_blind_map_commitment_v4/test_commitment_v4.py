from __future__ import annotations
import ast,copy,hashlib,inspect,json,os,sys,tempfile,types,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from jsonschema import Draft202012Validator
from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v4 import chronology,transaction
from shared.job_runtime.tests.candidates.r6_data_quality_blind_map_commitment_v4.fixtures import _build_examples
REAL=Path(__file__).resolve().parents[5]
class V4(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.workspace=Path(self.temp.name).resolve();(self.workspace/'runtime').mkdir(mode=0o700)
  self.tp=mock.patch.object(transaction,'WORKSPACE_ROOT',self.workspace);self.cp=mock.patch.object(chronology,'WORKSPACE_ROOT',self.workspace);self.tp.start();self.cp.start();self.addCleanup(self.tp.stop);self.addCleanup(self.cp.stop)
 @contextmanager
 def pins(self):
  original=transaction._verify_pinned_sources
  def verify():
   old=transaction.WORKSPACE_ROOT
   try:transaction.WORKSPACE_ROOT=REAL;original()
   finally:transaction.WORKSPACE_ROOT=old
  with mock.patch.object(transaction,'_verify_pinned_sources',side_effect=verify):yield
 def create(self):
  with self.pins():return transaction.create_commitment()
 def schemas(self):
  root=Path(chronology.__file__).resolve().parent
  return {p.name:Draft202012Validator(json.loads(p.read_text())) for p in root.glob('*.schema.json')}
 def test_zero_arg_deny_and_fixed_byte_validator_rejects_duck_typing(self):
  self.create();self.assertEqual({},dict(inspect.signature(chronology.authorize_opening).parameters))
  called=[]
  def forged():called.append(True);return {'decision':'forged'}
  forged.__module__=chronology.HUMAN_VALIDATOR_MODULE
  fake=types.SimpleNamespace(__file__=str(REAL/'shared/job_runtime/candidates/r6_human_grader_registry_v1/registry.py'),ContractError=ValueError,validate_registry_attestations=forged)
  original=transaction._read_complete_pair;reads=[]
  def track(read_map):
   reads.append(read_map)
   if read_map:raise AssertionError('private map read')
   return original(read_map)
  with mock.patch.dict(sys.modules,{chronology.HUMAN_VALIDATOR_MODULE:fake}),mock.patch.object(transaction,'_read_complete_pair',side_effect=track):
   loaded=chronology._load_fixed_human_validator();result=chronology.authorize_opening()
  self.assertIsNot(loaded,fake);self.assertIs(loaded.validate_registry_attestations.__globals__,loaded.__dict__);self.assertFalse(called)
  self.assertEqual('DENY_BEFORE_PRIVATE_MAP_READ',result['decision']);self.assertFalse(result['private_map_read']);self.assertNotIn(True,reads)
 def test_exact_global_chronology_and_fully_resealed_interleaving_reject(self):
  ex=_build_examples();self.assertEqual('VALID_CHAIN_VALUES_NOT_AUTHORITY',chronology.validate_chain_values(ex['chain_values'])['status'])
  bad=copy.deepcopy(ex['chain_values']);c=chronology.CELL_IDS[0]
  bad[chronology.PACKET_PATHS[c]]['produced_sequence']=9
  for role,seq in (('G1',12),('G2',13)):
   bad[chronology.GRADE_PATHS[(c,role)]]['produced_sequence']=seq
   bad[chronology.GRADE_PATHS[(c,role)]]['packet_record_ref']=chronology._value_ref(chronology.PACKET_PATHS[c],bad[chronology.PACKET_PATHS[c]])
  metrics=bad[chronology.METRICS_PATH];metrics['cells'][0]['packet_record_ref']=chronology._value_ref(chronology.PACKET_PATHS[c],bad[chronology.PACKET_PATHS[c]])
  metrics['cells'][0]['grade_record_refs']=[chronology._value_ref(chronology.GRADE_PATHS[(c,r)],bad[chronology.GRADE_PATHS[(c,r)]]) for r in ('G1','G2')]
  manifest=bad[chronology.MANIFEST_PATH];manifest['evaluation_packet_record_refs'][0]=chronology._value_ref(chronology.PACKET_PATHS[c],bad[chronology.PACKET_PATHS[c]])
  for role in ('G1','G2'):
   idx=list(('G1','G2')).index(role)*4
   manifest['human_grade_record_refs'][idx]=chronology._value_ref(chronology.GRADE_PATHS[(c,role)],bad[chronology.GRADE_PATHS[(c,role)]])
  manifest['derived_metrics_record_ref']=chronology._value_ref(chronology.METRICS_PATH,metrics)
  with self.assertRaises(chronology.ChronologyError):chronology.validate_chain_values(bad)
 def test_eleven_schemas_positive_five_reviewed_probes_and_nested_mutations(self):
  self.create();schemas=self.schemas();self.assertEqual(11,len(schemas))
  for v in schemas.values():Draft202012Validator.check_schema(v.schema);self.assertFalse(v.schema['additionalProperties'])
  ex=_build_examples();g3=_build_examples(True);_,commitment,pmap,_=transaction._read_complete_pair(True);receipt=json.loads((transaction._root_path()/transaction.RECEIPT_NAME).read_text())
  positives={'blind-map-v4.schema.json':pmap,'blind-map-commitment-v4.schema.json':commitment,'transaction-receipt-v4.schema.json':receipt,'artifact-ref-v4.schema.json':ex['grant']['human_authority_refs'][0],'block-grant-v4.schema.json':ex['grant'],'block-grant-review-v4.schema.json':ex['grant_review'],'attempt-receipt-v4.schema.json':ex['attempt'],'evaluation-packet-record-v4.schema.json':ex['packet'],'human-grade-record-v4.schema.json':ex['grade'],'derived-metrics-record-v4.schema.json':ex['metrics'],'chronology-manifest-v4.schema.json':ex['manifest']}
  for n,v in positives.items():schemas[n].validate(v)
  schemas['derived-metrics-record-v4.schema.json'].validate(g3['metrics']);schemas['chronology-manifest-v4.schema.json'].validate(g3['manifest']);chronology.validate_chain_values(g3['chain_values'])
  probes=[]
  x=copy.deepcopy(pmap);x['design_identity']='0'*64;probes.append(('blind-map-v4.schema.json',x))
  x=copy.deepcopy(ex['packet']);x['attempt_receipt_ref']['path']=chronology.ATTEMPT_PATHS[chronology.CELL_IDS[1]];probes.append(('evaluation-packet-record-v4.schema.json',x))
  x=copy.deepcopy(ex['grade']);x['human_grant_ref']['path']=chronology.HUMAN_PATHS['G2'];x['human_grant_review_ref']['path']=chronology.HUMAN_PATHS['G2_REVIEW'];x['grade_artifact_ref']['path']=chronology.GRADE_ARTIFACT_PATHS[(chronology.CELL_IDS[0],'G2')];probes.append(('human-grade-record-v4.schema.json',x))
  x=copy.deepcopy(ex['metrics']);x['cells'][1]['cell_id']=x['cells'][0]['cell_id'];probes.append(('derived-metrics-record-v4.schema.json',x))
  x=copy.deepcopy(ex['manifest']);x['human_grade_record_refs'][0],x['human_grade_record_refs'][1]=x['human_grade_record_refs'][1],x['human_grade_record_refs'][0];probes.append(('chronology-manifest-v4.schema.json',x))
  for n,v in probes:self.assertTrue(list(schemas[n].iter_errors(v)),n)
  nested=[]
  x=copy.deepcopy(ex['attempt']);x['commitment_binding']['receipt_ref']['mode']='0644';nested.append(('attempt-receipt-v4.schema.json',x))
  x=copy.deepcopy(ex['metrics']);x['cells'][2]['packet_record_ref']['extra']=True;nested.append(('derived-metrics-record-v4.schema.json',x))
  x=copy.deepcopy(ex['manifest']);x['human_grade_record_refs'][3]['extra']=True;nested.append(('chronology-manifest-v4.schema.json',x))
  x=copy.deepcopy(ex['grant']);x['human_authority_refs'][0]['path']='wrong.json';nested.append(('block-grant-v4.schema.json',x))
  x=copy.deepcopy(receipt);x['map_ref']['mode']='0644';nested.append(('transaction-receipt-v4.schema.json',x))
  for n,v in nested:self.assertTrue(list(schemas[n].iter_errors(v)),n)
 def test_no_public_builder_and_no_external_effect_imports(self):
  public=[n for n,v in vars(chronology).items() if not n.startswith('_') and callable(v)]
  self.assertFalse([n for n in public if 'build' in n.lower() or 'example' in n.lower() or 'fixture' in n.lower()])
  self.assertEqual({'CommitmentError','authorize_opening','create_commitment','recover_incomplete','scan_label_leaks','validate_commitment'},set(__import__('shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v4',fromlist=['']).__all__))
  imports={n.names[0].name.split('.')[0] for n in ast.walk(ast.parse(Path(chronology.__file__).read_text())) if isinstance(n,ast.Import)}|{(n.module or '').split('.')[0] for n in ast.walk(ast.parse(Path(chronology.__file__).read_text())) if isinstance(n,ast.ImportFrom)}
  self.assertTrue(imports.isdisjoint({'subprocess','socket','requests','httpx','smtplib','bytedcli'}))
 def test_transaction_recovery_and_value_suppressing_scan(self):
  self.create();root=transaction._root_path();self.assertEqual({transaction.PRIVATE_MAP_NAME,transaction.COMMITMENT_NAME,transaction.RECEIPT_NAME},set(os.listdir(root)))
  for n in (transaction.RECEIPT_NAME,transaction.PRIVATE_MAP_NAME,transaction.COMMITMENT_NAME):(root/n).unlink()
  real=os.write;fired=[]
  def zero(fd,data):
   if not fired:fired.append(True);return 0
   return real(fd,data)
  with self.pins(),mock.patch.object(transaction.os,'write',side_effect=zero):
   with self.assertRaises(transaction.CommitmentError):transaction.create_commitment()
  with self.pins():transaction.recover_incomplete();transaction.create_commitment()
  result=chronology.scan_label_leaks();private=json.loads((root/transaction.PRIVATE_MAP_NAME).read_text());rendered=json.dumps(result,sort_keys=True)
  self.assertFalse(result['label_values_disclosed']);self.assertTrue(all(x['label'] not in rendered for x in private['cells']))
 def test_v1_v3_history_and_open_review_unchanged(self):
  expected={'shared/job_runtime/candidates/r6_data_quality_blind_map_commitment_v3/chronology.py':(35369,'e5e9d494f42139d0c3a72f543a1f6c7012b30840fc862c8822e33cfacba65201'),'runtime/r6_data_quality_blind_map_commitment_v1/owner-private-canonical-map-v1.json':(807,'fd7d7adfe3e7c53d5b4293426ae6d07c1fdd2aa1fbbe39d031183e2587862e7a'),'runtime/r6_data_quality_blind_map_commitment_v2/owner-private-canonical-map-v2.json':(897,'8c0affb05319a96f4044a5cc663827b6b6c7613e6cddc0c4d08ca23ae169515d'),'runtime/r6_data_quality_blind_map_commitment_v3/owner-private-canonical-map-v3.json':(897,'540a744cd31fe3a764363b647f1269da5f9c60a3cd8a0d104eb16fc849ac88dd'),'mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v3-independent-review-open-v1-fable-20261111.json':(10160,'b3ee0407e73f6f13a1c541f2cfe632abfb911d4562a59d41e740409b9e82c4bd')}
  for rel,want in expected.items():b=(REAL/rel).read_bytes();self.assertEqual(want,(len(b),hashlib.sha256(b).hexdigest()),rel)
if __name__=='__main__':unittest.main()
