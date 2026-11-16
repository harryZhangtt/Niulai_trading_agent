from copy import deepcopy
import hashlib,json,unittest
from pathlib import Path
from shared.research_sources.information_yield_v5_contracts import ArtifactRefV5,InformationYieldV5ContractError
from .policy_v5 import CANONICAL_GATE_ORDER_V5,CANONICAL_METRIC_POLICY_V5_PATH,CANONICAL_METRIC_POLICY_V5_SHA256,GATE_RECORD_FIELDS_V5,GATE_SPECS_V5,PolicyV5Error,canonical_policy_ref_v5,load_canonical_metric_policy_v5,require_canonical_policy_ref_v5,verify_gate_set_v5
class PolicyV5Tests(unittest.TestCase):
 def test_canonical_bytes_relative_ref_and_unchanged_thresholds(self):
  raw=CANONICAL_METRIC_POLICY_V5_PATH.read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),CANONICAL_METRIC_POLICY_V5_SHA256);ArtifactRefV5.from_mapping(canonical_policy_ref_v5());self.assertFalse(Path(canonical_policy_ref_v5()['path']).is_absolute())
  v5=load_canonical_metric_policy_v5();v4=json.loads(Path(__file__).with_name('metric-policy-v4.json').read_text());keys={'complete_trace_ratio','confirmation_case_count','confirmation_order_counts','maximum_aggregate_wall_ratio','maximum_arm_wall_seconds','maximum_case_wall_ratio','minimum_aggregate_lineage_delta','minimum_case_delta','minimum_case_lineage_delta','minimum_eiy_d','minimum_eiy_r','minimum_positive_cases','minimum_precision_delta','require_positive_issuer_loo','zero_critical_unsupported','zero_hard_failures'};self.assertEqual({k:v5[k] for k in keys},{k:v4[k] for k in keys})
 def test_noncanonical_policy_path_alias_rejected(self):
  for path in ['/absolute/policy.json','../policy.json','tuning/./policy.json','.niulai-state/policy.json','niulai-private/policy.json']:
   with self.assertRaises((PolicyV5Error,InformationYieldV5ContractError)):require_canonical_policy_ref_v5({'path':path,'sha256':CANONICAL_METRIC_POLICY_V5_SHA256})
 def test_artifact_refs_reject_absolute_dot_hidden_and_backslash(self):
  for path in ['/tmp/x','a/../x','a/./x','.private/x','a/.private/x','niulai-private/x',r'a\x']:
   with self.assertRaises(InformationYieldV5ContractError,msg=path):ArtifactRefV5(path,'0'*64)
  ArtifactRefV5('investment/runtime/x.json','0'*64)
 def test_exact_gate_authority_and_corruption(self):
  self.assertEqual(len(CANONICAL_GATE_ORDER_V5),18);self.assertEqual([x['ordinal'] for x in GATE_SPECS_V5 if x['decisive']],list(range(12,18)));self.assertEqual(len(GATE_RECORD_FIELDS_V5),12)
  ids={'C':['c1'],'E':['c1','d1']};gates=[{**s,'population_case_ids':ids[s['population']],'status':'pass','observed':None,'threshold':None,'numerator':None,'denominator':None,'case_results':[],'reason_codes':[]} for s in GATE_SPECS_V5];verify_gate_set_v5(gates,population_case_ids=ids)
  bad=deepcopy(gates);bad[0]['name']='wrong'
  with self.assertRaisesRegex(PolicyV5Error,'EIY_V5_GATE_ORDER'):verify_gate_set_v5(bad,population_case_ids=ids)
  bad=deepcopy(gates);bad[0]['population']='E'
  with self.assertRaisesRegex(PolicyV5Error,'EIY_V5_GATE_POPULATION'):verify_gate_set_v5(bad,population_case_ids=ids)
 def test_all_ten_schemas_recursively_close_every_object(self):
  root=Path(__file__).resolve().parents[4]/'shared/research_sources/schemas';names=['information-yield-check-request-v5','information-yield-checked-fact-v5','information-yield-evaluation-custody-v5','information-yield-evaluation-context-v5','information-yield-policy-gates-v5','information-yield-metric-policy-v5','information-yield-result-5','information-yield-now-diagnostic-result-5','information-yield-result-custody-v1','information-yield-result-index-entry-v1']
  for name in names:
   value=json.loads((root/f'{name}.schema.json').read_text());self.assertEqual(value['$id'],name)
   def walk(node):
    if isinstance(node,dict):
     if node.get('type')=='object':self.assertIs(node.get('additionalProperties'),False,name)
     for child in node.values():walk(child)
    elif isinstance(node,list):
     for child in node:walk(child)
   walk(value)
if __name__=='__main__':unittest.main()
