from __future__ import annotations
import ast,copy,hashlib,inspect,json,os,stat,sys,tempfile,types,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from jsonschema import Draft202012Validator
from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v5 import chronology,transaction
from shared.job_runtime.tests.candidates.r6_data_quality_blind_map_commitment_v5.fixtures import _build_examples
REAL=Path(__file__).resolve().parents[5]

class V5(unittest.TestCase):
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
 def _opening_probe(self,g3_required:bool,*,include_g3_pins:bool=True,reject_registry:bool=False):
  ex=_build_examples(g3_required);values={**ex['chain_values'],**ex['external_artifacts']};chain_pins={p:chronology._value_ref(p,v) for p,v in values.items()}
  names=('REGISTRY','REGISTRY_REVIEW','G1','G1_REVIEW','G2','G2_REVIEW')+(('G3','G3_REVIEW') if g3_required and include_g3_pins else ())
  human_pins={chronology.HUMAN_PATHS[n]:ex['human_pins'][chronology.HUMAN_PATHS[n]] for n in names};events=[]
  class Store:
   def read(self,path):events.append(('chain',path));return values[path]
  class RegistryError(ValueError):pass
  class Registry:
   ContractError=RegistryError
   def validate_registry_attestations(self,root,g3_triggered=False):
    events.append(('registry',root,g3_triggered))
    if reject_registry:raise RegistryError('forged')
    return {'decision':'VALIDATED_FOR_SEPARATE_EXPLICIT_PINNING_NOT_LIVE','g3_triggered':g3_triggered,'validated_roles':['G1','G2']+(['G3'] if g3_triggered else []),'activation':False,'countable':False}
   def _secure_read(self,root,path,mode,code):
    pin=human_pins[path];events.append(('human',path));return {},pin['sha256'],pin['bytes']
  aliases={c:ex['chain_values'][chronology.ATTEMPT_PATHS[c]]['blind_alias'] for c in chronology.CELL_IDS}
  private_map={'cell_order':list(chronology.CELL_IDS),'labels':[aliases[c] for c in chronology.CELL_IDS]}
  def pair(read_map):events.append(('private',read_map));return {},{},private_map,ex['binding']
  with mock.patch.object(chronology,'AUTHENTIC_CHAIN_PINS',chain_pins),mock.patch.object(chronology,'AUTHENTIC_HUMAN_PINS',human_pins),mock.patch.object(chronology,'_FixedArtifactStore',return_value=Store()),mock.patch.object(chronology,'_load_fixed_human_validator',return_value=Registry()),mock.patch.object(transaction,'_read_complete_pair',side_effect=pair):
   result=chronology.authorize_opening()
  return result,events
 def test_zero_arg_current_state_denies_before_private_map_and_fixed_bytes_ignore_duck(self):
  self.create();self.assertEqual({},dict(inspect.signature(chronology.authorize_opening).parameters));called=[]
  def forged(*args,**kwargs):called.append((args,kwargs));return {'decision':'forged'}
  forged.__module__=chronology.HUMAN_VALIDATOR_MODULE
  fake=types.SimpleNamespace(__file__=str(REAL/'shared/job_runtime/candidates/r6_human_grader_registry_v1/registry.py'),ContractError=ValueError,validate_registry_attestations=forged)
  with mock.patch.dict(sys.modules,{chronology.HUMAN_VALIDATOR_MODULE:fake}):loaded=chronology._load_fixed_human_validator()
  self.assertIsNot(loaded,fake);self.assertIs(loaded.validate_registry_attestations.__globals__,loaded.__dict__);self.assertFalse(called)
  original=transaction._read_complete_pair;reads=[]
  def track(read_map):
   reads.append(read_map)
   if read_map:raise AssertionError('private map read')
   return original(read_map)
  with mock.patch.object(transaction,'_read_complete_pair',side_effect=track):result=chronology.authorize_opening()
  self.assertEqual('DENY_BEFORE_PRIVATE_MAP_READ',result['decision']);self.assertFalse(result['private_map_read']);self.assertNotIn(True,reads)
 def test_manifest_first_g3_false_and_true_authority(self):
  for required in (False,True):
   result,events=self._opening_probe(required)
   self.assertEqual('FIXED_CHAIN_VALIDATED_STILL_DISABLED',result['decision'])
   self.assertEqual(('chain',chronology.MANIFEST_PATH),events[0]);registry_event=next(e for e in events if e[0]=='registry')
   self.assertEqual((chronology.FIXED_WORKSPACE_ROOT,required),registry_event[1:]);self.assertEqual(('private',True),events[-1])
 def test_missing_and_forged_g3_authority_deny_before_private_map(self):
  for kwargs in ({'include_g3_pins':False},{'reject_registry':True}):
   result,events=self._opening_probe(True,**kwargs)
   self.assertEqual('DENY_BEFORE_PRIVATE_MAP_READ',result['decision']);self.assertFalse(result['private_map_read']);self.assertFalse(any(e[0]=='private' for e in events))
 def test_exact_global_chronology_and_fully_resealed_interleavings_reject(self):
  for g3_required in (False,True):self.assertEqual('VALID_CHAIN_VALUES_NOT_AUTHORITY',chronology.validate_chain_values(_build_examples(g3_required)['chain_values'])['status'])
  ex=_build_examples();bad=copy.deepcopy(ex['chain_values']);c=chronology.CELL_IDS[0];bad[chronology.PACKET_PATHS[c]]['produced_sequence']=9
  for role,seq in (('G1',12),('G2',13)):
   bad[chronology.GRADE_PATHS[(c,role)]]['produced_sequence']=seq;bad[chronology.GRADE_PATHS[(c,role)]]['packet_record_ref']=chronology._value_ref(chronology.PACKET_PATHS[c],bad[chronology.PACKET_PATHS[c]])
  metrics=bad[chronology.METRICS_PATH];metrics['cells'][0]['packet_record_ref']=chronology._value_ref(chronology.PACKET_PATHS[c],bad[chronology.PACKET_PATHS[c]]);metrics['cells'][0]['grade_record_refs']=[chronology._value_ref(chronology.GRADE_PATHS[(c,r)],bad[chronology.GRADE_PATHS[(c,r)]]) for r in ('G1','G2')]
  manifest=bad[chronology.MANIFEST_PATH];manifest['evaluation_packet_record_refs'][0]=chronology._value_ref(chronology.PACKET_PATHS[c],bad[chronology.PACKET_PATHS[c]])
  for role in ('G1','G2'):
   idx=list(('G1','G2')).index(role)*4;manifest['human_grade_record_refs'][idx]=chronology._value_ref(chronology.GRADE_PATHS[(c,role)],bad[chronology.GRADE_PATHS[(c,role)]])
  manifest['derived_metrics_record_ref']=chronology._value_ref(chronology.METRICS_PATH,metrics)
  with self.assertRaises(chronology.ChronologyError):chronology.validate_chain_values(bad)
 def test_eleven_schemas_are_runtime_exact_for_positional_map(self):
  self.create();schemas=self.schemas();self.assertEqual(11,len(schemas))
  for v in schemas.values():Draft202012Validator.check_schema(v.schema);self.assertFalse(v.schema['additionalProperties'])
  ex=_build_examples();g3=_build_examples(True);_,commitment,pmap,_=transaction._read_complete_pair(True);receipt=json.loads((transaction._root_path()/transaction.RECEIPT_NAME).read_text())
  positives={'blind-map-v5.schema.json':pmap,'blind-map-commitment-v5.schema.json':commitment,'transaction-receipt-v5.schema.json':receipt,'artifact-ref-v5.schema.json':ex['grant']['human_authority_refs'][0],'block-grant-v5.schema.json':ex['grant'],'block-grant-review-v5.schema.json':ex['grant_review'],'attempt-receipt-v5.schema.json':ex['attempt'],'evaluation-packet-record-v5.schema.json':ex['packet'],'human-grade-record-v5.schema.json':ex['grade'],'derived-metrics-record-v5.schema.json':ex['metrics'],'chronology-manifest-v5.schema.json':ex['manifest']}
  for n,v in positives.items():schemas[n].validate(v)
  schemas['derived-metrics-record-v5.schema.json'].validate(g3['metrics']);schemas['chronology-manifest-v5.schema.json'].validate(g3['manifest'])
  probes=[]
  x=copy.deepcopy(pmap);x['labels'][1]=x['labels'][0];probes.append(x)
  x=copy.deepcopy(pmap);x['cell_order']=list(reversed(x['cell_order']));probes.append(x)
  for value in probes:
   self.assertTrue(list(schemas['blind-map-v5.schema.json'].iter_errors(value)))
   with self.assertRaises(transaction.CommitmentError):transaction._validate_map(value)
 def test_no_public_builder_external_effects_and_value_suppressing_scan(self):
  public=[n for n,v in vars(chronology).items() if not n.startswith('_') and callable(v)];self.assertFalse([n for n in public if any(x in n.lower() for x in ('build','example','fixture'))])
  self.assertEqual({'CommitmentError','authorize_opening','create_commitment','recover_incomplete','scan_label_leaks','validate_commitment'},set(__import__('shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v5',fromlist=['']).__all__))
  imports={n.names[0].name.split('.')[0] for n in ast.walk(ast.parse(Path(chronology.__file__).read_text())) if isinstance(n,ast.Import)}|{(n.module or '').split('.')[0] for n in ast.walk(ast.parse(Path(chronology.__file__).read_text())) if isinstance(n,ast.ImportFrom)};self.assertTrue(imports.isdisjoint({'subprocess','socket','requests','httpx','smtplib','bytedcli'}))
  self.create();result=chronology.scan_label_leaks();private=json.loads((transaction._root_path()/transaction.PRIVATE_MAP_NAME).read_text());rendered=json.dumps(result,sort_keys=True);self.assertFalse(result['label_values_disclosed']);self.assertTrue(all(x not in rendered for x in private['labels']))
 def test_closure_exact_lstat_fstat_modes_and_mode_drift_reject(self):
  p=REAL/'tuning/architecture/r6_data_quality_blind_map_commitment_v5/source-closure-v5.json';closure=json.loads(p.read_text());rows=sum((closure[k] for k in ('preserved_v1_v4_history_bindings','v5_runtime_bindings','v5_source_schema_test_and_design_bindings')),[])
  def actual(row):
   path=REAL/row['path'];lst=os.lstat(path);fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
   try:
    fst=os.fstat(fd);raw=b''
    while True:
     chunk=os.read(fd,65536)
     if not chunk:break
     raw+=chunk
   finally:os.close(fd)
   self.assertEqual((lst.st_dev,lst.st_ino),(fst.st_dev,fst.st_ino));return {'path':row['path'],'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'mode':format(stat.S_IMODE(fst.st_mode),'04o')}
  self.assertTrue(all(actual(row)==row for row in rows));v2=next(r for r in rows if r['path'].endswith('commitment-v2-independent-review-open-v1-20261111.json'));self.assertEqual('0600',v2['mode'])
  drift=dict(v2,mode='0644');self.assertNotEqual(actual(drift),drift)
 def test_v1_v4_open_history_unchanged(self):
  expected={'mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v2-independent-review-open-v1-20261111.json':(11517,'d7a453c4b04442c233bf830d8a8b5747400b15e237f3337a95e0474f6a602963','0600'),'mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v4-independent-review-open-v1-fable-20261111.json':(11626,'df79e13a5bbfcfce8f3a1fb0f12dee01f7783598dfe9e89d8a12ef200e7113ba','0644')}
  for rel,want in expected.items():
   p=REAL/rel;b=p.read_bytes();self.assertEqual(want,(len(b),hashlib.sha256(b).hexdigest(),format(stat.S_IMODE(os.lstat(p).st_mode),'04o')),rel)
if __name__=='__main__':unittest.main()
