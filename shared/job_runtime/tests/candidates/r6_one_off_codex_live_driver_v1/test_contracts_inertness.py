import ast,json,unittest
from decimal import Decimal
from ._support import ROOT,Clock,config,preflight
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import ContractError,EffectGuard,strict_json_loads,validate_config,validate_preflight,verify_frozen_predecessors
class ContractsTests(unittest.TestCase):
 def test_config_predecessors_and_finite_fixed_point(self):validate_config(config());verify_frozen_predecessors(ROOT);g=EffectGuard('0.01','0.02',200,Clock());g.check('reserve','0.01');self.assertEqual(g.reserved,Decimal('0.01'))
 def test_nonfinite_out_of_range_and_overcap_rejected(self):
  for provider,combined in [('NaN','0.02'),('Infinity','0.02'),('0.01','NaN'),('0.01','0.0201'),('0.00','0.02'),('0.01','-0.01')]:
   p=preflight();p['budget'].update(provider_remaining=provider,combined_remaining=combined)
   with self.assertRaises((ContractError,ArithmeticError)):validate_preflight(p)
 def test_duplicate_extra_and_all_held_roles(self):
  with self.assertRaises(ContractError):strict_json_loads('{"a":1,"a":2}')
  c=config();c['extra']=1
  with self.assertRaises(ContractError):validate_config(c)
  self.assertEqual(set(config()['held']),{'binary','argv','config','parser','gateway','prompt','source_closure','grant'})
 def test_inert_blocked_absent_exact_files(self):
  src=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_driver_v1'
  for p in src.glob('*.py'):ast.parse(p.read_text());self.assertNotIn('codex_live_evidence_r6_live_v1',p.read_text())
  self.assertEqual({p.name for p in src.glob('*.py')},{'__init__.py','contracts.py','custody.py','driver.py','gateway.py','process.py','publication.py','terminal.py'})
 def test_schemas_recursive_closed_draft(self):
  def walk(v):
   if isinstance(v,dict):
    if v.get('type')=='object':self.assertFalse(v.get('additionalProperties',True));self.assertFalse(v.get('unevaluatedProperties',True))
    for x in v.values():walk(x)
   elif isinstance(v,list):
    for x in v:walk(x)
  for p in (ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_driver_v1/schemas').glob('*.json'):
   s=json.loads(p.read_text());self.assertEqual(s['$schema'],'https://json-schema.org/draft/2020-12/schema');walk(s)
if __name__=='__main__':unittest.main()
