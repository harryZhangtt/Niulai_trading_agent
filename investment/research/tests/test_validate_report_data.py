from __future__ import annotations
import copy, hashlib, importlib.util, json, shutil, tempfile, unittest
from pathlib import Path

REPO_ROOT=Path(__file__).resolve().parents[3]
SOURCE=REPO_ROOT/'investment/research/validate_report_data.py'
SPEC=importlib.util.spec_from_file_location('validate_report_data',SOURCE); assert SPEC and SPEC.loader
validator=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(validator)
CURRENT=REPO_ROOT/validator.CURRENT_REPORT_REL
EXTENSION_PATHS=(
 ('sections','evidence_states','claim_state_authority'),
 ('sections','historical_support','index_identity_and_boundaries'),
 ('sections','leveraged_paths','model_boundaries_ref'),
 ('sections','leveraged_paths','decomposition_equation'),
 ('sections','leveraged_paths','residual_definition'),
 ('sections','leveraged_paths','decompositions'),
)

def get(root,path):
 for part in path: root=root[part] if isinstance(part,str) else root[part]
 return root

def parent(root,path): return get(root,path[:-1]),path[-1]

def walk(value,path=()):
 yield path,value
 if isinstance(value,dict):
  for key,child in value.items(): yield from walk(child,path+(key,))
 elif isinstance(value,list):
  for i,child in enumerate(value): yield from walk(child,path+(i,))

def wrong(value):
 if isinstance(value,bool): return 'not_boolean'
 if value is None:return 'not_null'
 if isinstance(value,str):return 17
 if isinstance(value,(int,float)):return 'not_number'
 if isinstance(value,list):return {'not':'array'}
 if isinstance(value,dict):return ['not_object']
 raise AssertionError(type(value))

class ReportDataValidatorTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.raw=CURRENT.read_bytes();cls.report=validator.load(CURRENT);cls.base=CURRENT.parent
 def assertRejects(self,doc,code=None,base=None,final=False):
  with self.assertRaises(ValueError) as caught:validator.validate(doc,base or self.base,final)
  if code:self.assertTrue(str(caught.exception).startswith(code),(code,str(caught.exception)))
 def test_exact_current_freeze_and_real_validation(self):
  self.assertEqual(len(self.raw),14275);self.assertEqual(hashlib.sha256(self.raw).hexdigest(),'218a1ee24f248f66290826ff0316962ce268246958ca9ea14c2b4997da4efac6')
  self.assertEqual(validator.validate_current()['resolved_refs'],32)
 def test_every_new_object_field_omission_rejected(self):
  attacks=[]
  for root_path in EXTENSION_PATHS:
   root=get(self.report,root_path)
   if isinstance(root,dict):
    attacks += [(root_path+path+(key,)) for path,node in walk(root) if isinstance(node,dict) for key in node]
  self.assertEqual(len(attacks),33)
  for path in attacks:
   with self.subTest(path=path):
    doc=copy.deepcopy(self.report);container,key=parent(doc,path);del container[key];self.assertRejects(doc)
 def test_every_new_object_extra_rejected(self):
  attacks=[]
  for root_path in EXTENSION_PATHS:
   root=get(self.report,root_path)
   if isinstance(root,dict) or isinstance(root,list):
    attacks += [root_path+path for path,node in walk(root) if isinstance(node,dict)]
  self.assertEqual(len(attacks),12)
  for path in attacks:
   with self.subTest(path=path):
    doc=copy.deepcopy(self.report);get(doc,path)['unexpected_extension']='spoof';self.assertRejects(doc,'SCHEMA_ADDITIONAL')
 def test_every_new_field_type_attack_rejected(self):
  attacks=[]
  for root_path in EXTENSION_PATHS:
   attacks += [root_path+path for path,node in walk(get(self.report,root_path)) if not path or not isinstance(node,(dict,list))]
  self.assertEqual(len(attacks),82)
  for path in attacks:
   with self.subTest(path=path):
    doc=copy.deepcopy(self.report);container,key=parent(doc,path);container[key]=wrong(container[key]);self.assertRejects(doc)
 def test_schema_const_enum_and_numeric_types_distinguish_bool_int(self):
  attacks=[
   (False,{'const':0}),(0,{'const':False}),(True,{'const':1}),(1,{'const':True}),
   ({'x':[False,{'y':True}]},{'const':{'x':[0,{'y':1}]}}),
   ({'x':[0,{'y':1}]},{'const':{'x':[False,{'y':True}]}}),
   (False,{'enum':[0]}),(0,{'enum':[False]}),(True,{'enum':[1]}),(1,{'enum':[True]}),
   (False,{'type':'integer'}),(True,{'type':'number'})]
  for value,schema in attacks:
   with self.subTest(value=value,schema=schema):
    with self.assertRaises(ValueError):validator.schema_check(value,schema)
 def test_every_report_boolean_leaf_rejects_integer_substitution(self):
  paths=[path for path,value in walk(self.report) if isinstance(value,bool)]
  self.assertEqual(len(paths),21)
  for path in paths:
   with self.subTest(path=path):
    
    for integer in (0,1):
     doc=copy.deepcopy(self.report);container,key=parent(doc,path);container[key]=integer;self.assertRejects(doc)
 def test_every_report_numeric_leaf_rejects_both_booleans(self):
  paths=[path for path,value in walk(self.report) if isinstance(value,(int,float)) and not isinstance(value,bool)]
  self.assertEqual(len(paths),22)
  for path in paths:
   for boolean in (False,True):
    with self.subTest(path=path,boolean=boolean):
     doc=copy.deepcopy(self.report);container,key=parent(doc,path);container[key]=boolean;self.assertRejects(doc)
 def test_identity_spoofs_rejected(self):
  for path,value in [
   (('sections','evidence_states','claim_state_authority','consequential_authority'),True),
   (('sections','historical_support','index_identity_and_boundaries','aliases',0,'symbol'),'COMP'),
   (('sections','historical_support','index_identity_and_boundaries','oneq_proxy_boundary','exact_IXIC_membership'),True),
   (('sections','leveraged_paths','decompositions',0,'exact_reset_benchmark'),'Nasdaq-100'),
   (('sections','leveraged_paths','decompositions',0,'investable_proxy_identities',0,'symbol'),'QQQ')]:
   with self.subTest(path=path):
    doc=copy.deepcopy(self.report);container,key=parent(doc,path);container[key]=value;self.assertRejects(doc)
 def artifact_attack(self,mutate,expected):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);shutil.copy2(self.base/'source-registry-v3.json',root/'source-registry-v3.json');shutil.copy2(self.base/'chart-data-v3.json',root/'chart-data-v3.json')
   report=copy.deepcopy(self.report);registry=json.loads((root/'source-registry-v3.json').read_text());chart=json.loads((root/'chart-data-v3.json').read_text());mutate(registry,chart)
   boundaries=registry['model_boundaries'];wrapper=chart['model_boundaries'];wrapper['canonical_object']=copy.deepcopy(boundaries);wrapper['visible_object']=copy.deepcopy(boundaries);wrapper['accessible_object']=copy.deepcopy(boundaries);wrapper['canonical_object_sha256']=validator.canonical_sha(boundaries)
   for name,data in [('source-registry-v3.json',registry),('chart-data-v3.json',chart)]:
    raw=(json.dumps(data,indent=2,ensure_ascii=False)+'\n').encode();(root/name).write_bytes(raw);aid='source_registry' if name.startswith('source') else 'chart_data';next(a for a in report['artifacts'] if a['id']==aid)['sha256']=hashlib.sha256(raw).hexdigest()
   self.assertRejects(report,expected,root) if expected else self.assertRejects(report,base=root)
 def test_every_model_boundary_boolean_leaf_rejects_integer_substitution(self):
  registry=json.loads((self.base/'source-registry-v3.json').read_text())
  paths=[path for path,value in walk(registry['model_boundaries']) if isinstance(value,bool)]
  self.assertEqual(len(paths),15)
  for path in paths:
   with self.subTest(path=path):
    for integer in (0,1):
     def mutate(r,c,path=path,integer=integer):
      container,key=parent(r['model_boundaries'],path);container[key]=integer
     self.artifact_attack(mutate,None)
 def test_model_probability_action_object_is_exactly_closed(self):
  for key in ('current_probability','actions','blocked'):
   with self.subTest(attack='omit',key=key):
    self.artifact_attack(lambda r,c,key=key:r['model_boundaries']['probability_and_actions'].pop(key),None)
  self.artifact_attack(lambda r,c:r['model_boundaries']['probability_and_actions'].__setitem__('broker_order',None),None)
  for key in ('current_probability','actions'):
   for value in (False,True):
    with self.subTest(attack='type',key=key,value=value):self.artifact_attack(lambda r,c,key=key,value=value:r['model_boundaries']['probability_and_actions'].__setitem__(key,value),None)
  for value in (0,1):
   with self.subTest(attack='blocked_int',value=value):self.artifact_attack(lambda r,c,value=value:r['model_boundaries']['probability_and_actions'].__setitem__('blocked',value),None)
 def test_merged_target_and_causal_attacks_rejected(self):
  self.artifact_attack(lambda r,c:r['model_boundaries'].__setitem__('targets_merged',True),'MODEL_MERGING')
  self.artifact_attack(lambda r,c:r['model_boundaries'].__setitem__('common_factor_is_causal',True),'CAUSAL_SPOOF')
 def test_nav_and_probability_boundary_attacks_rejected(self):
  self.artifact_attack(lambda r,c:r['model_boundaries'].__setitem__('market_price_equivalent_to_NAV',True),'NAV_SPOOF')
  self.artifact_attack(lambda r,c:r['model_boundaries']['probability_and_actions'].__setitem__('current_probability',0.6),'PROBABILITY_ACTION_BOUNDARY')
 def test_null_probability_and_action_outputs_rejected(self):
  self.artifact_attack(lambda r,c:r['null_outputs']['current_probability'].__setitem__('value',0.6),'NULL_OUTPUT_TYPE_OR_VALUE:current_probability')
  self.artifact_attack(lambda r,c:r['null_outputs']['calibration'].__setitem__('value',0),'NULL_OUTPUT_TYPE_OR_VALUE:calibration')
  self.artifact_attack(lambda r,c:r['policy_outputs'].__setitem__('recommendation','buy'),'ACTION_OUTPUT')
 def test_policy_outputs_exact_closed_shape_attacks(self):
  canonical=json.loads((self.base/'source-registry-v3.json').read_text())['policy_outputs'];self.assertEqual(set(canonical),{'recommendation','personalized_position_size','alert_write','automatic_execution','reason'})
  for key in canonical:
   with self.subTest(attack='omit',key=key):self.artifact_attack(lambda r,c,key=key:r['policy_outputs'].pop(key),None)
  for key in ('broker_order','current_probability_override','trade','execution','position','unexpected_output'):
   with self.subTest(attack='extra',key=key):self.artifact_attack(lambda r,c,key=key:r['policy_outputs'].__setitem__(key,None),None)
  for key in canonical:
   for value in (False,True):
    with self.subTest(attack='type',key=key,value=value):self.artifact_attack(lambda r,c,key=key,value=value:r['policy_outputs'].__setitem__(key,value),None)
 def test_null_outputs_exact_closed_shape_attacks(self):
  canonical=json.loads((self.base/'source-registry-v3.json').read_text())['null_outputs'];self.assertEqual(set(canonical),{'backtest','calibration','current_probability','ood','prospective','support'})
  attacks=0
  for key in canonical:
   attacks+=1;self.artifact_attack(lambda r,c,key=key:r['null_outputs'].pop(key),None)
  for key in ('broker_order','current_probability_override','trade','execution','position','unexpected_output'):
   attacks+=1;self.artifact_attack(lambda r,c,key=key:r['null_outputs'].__setitem__(key,{}),None)
  for output,row in canonical.items():
   for field in row:
    attacks+=1;self.artifact_attack(lambda r,c,output=output,field=field:r['null_outputs'][output].pop(field),None)
   attacks+=1;self.artifact_attack(lambda r,c,output=output:r['null_outputs'][output].__setitem__('broker_order',None),None)
   for field in row:
    for value in (False,True):
     attacks+=1;self.artifact_attack(lambda r,c,output=output,field=field,value=value:r['null_outputs'][output].__setitem__(field,value),None)
  self.assertEqual(attacks,72)
 def test_exact_audit_binding_spoofs_rejected(self):
  for path,value,code in [
   (('sections','audit_appendix','artifact_refs'),['source_registry#/projection_targets/trust_gate'],'AUDIT_SECTION_BINDINGS'),
   (('sections','leveraged_paths','table_ref'),'chart_data#/tables/audit_appendix','AUDIT_SECTION_BINDINGS'),
   (('sections','calibration','reliability_evidence','bins_ref'),'chart_data#/reliability/counts',None),
   (('source_ledger_ref',),'source_registry#/evidence_binding','AUDIT_GLOBAL_BINDINGS')]:
   with self.subTest(path=path):
    doc=copy.deepcopy(self.report);container,key=parent(doc,path);container[key]=value;self.assertRejects(doc,code)
 def test_reconciliation_and_separate_targets_rejected(self):
  doc=copy.deepcopy(self.report);doc['sections']['leveraged_paths']['decompositions'][1]['target']='SOXL';self.assertRejects(doc,'REPORT_DECOMPOSITION_DRIFT')
  doc=copy.deepcopy(self.report);doc['sections']['leveraged_paths']['decompositions'][0]['reconciliation']['intercept_log_return']+=0.1;self.assertRejects(doc,'REPORT_DECOMPOSITION_DRIFT')
 def test_all_legacy_invalid_fixtures_reject(self):
  root=REPO_ROOT/'mentor/runtime/probabilistic-manifold-leverage-20261107/fixtures'
  self.assertEqual(len(validator.LEGACY_INVALID_FIXTURES),15)
  for name in validator.LEGACY_INVALID_FIXTURES:
   with self.subTest(name=name):self.assertRejects(validator.legacy_document(root/name),validator.LEGACY_EXPECTED[name],root,name=='invalid-report-stale-final-ref.json')

if __name__=='__main__':unittest.main()
