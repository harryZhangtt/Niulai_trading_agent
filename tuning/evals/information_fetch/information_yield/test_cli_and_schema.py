from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from jsonschema import Draft202012Validator
from investment.research.acquisition_eiy_checker import check_eiy_evaluation_v4
from investment.research.tests.test_acquisition_eiy_v3 import EiyV3Fixture
from shared.research_sources.artifacts import ROOT
from .__main__ import main,evaluate_path
from ._v4_support import build_batch
from .contracts import InformationYieldError,canonical,digest
class CliV4Tests(unittest.TestCase):
 def output(self):
  t=tempfile.TemporaryDirectory(dir=ROOT,prefix='.eiy-v4-output-');self.addCleanup(t.cleanup);return str((Path(t.name)/'result.json').relative_to(ROOT))
 def test_cli_nominal_replay_conflict_and_one_batch_checker(self):
  fixtures,_evaluation,_custody,manifest=build_batch(self);out=self.output();args=['evaluate','--workspace-root',str(ROOT),'--manifest',manifest['path'],'--output',out]
  with redirect_stdout(StringIO()):self.assertEqual(main(args),0)
  result=json.loads((ROOT/out).read_text());self.assertEqual(result['verdict'],'pass')
  with redirect_stdout(StringIO()):self.assertEqual(main(args),0)
  (ROOT/out).write_text('{}')
  with redirect_stdout(StringIO()):self.assertEqual(main(args),2)
  spy=Mock(side_effect=check_eiy_evaluation_v4);evaluate_path(manifest['path'],workspace_root=ROOT,checker=spy);self.assertEqual(spy.call_count,1)
 def test_inverse_cli_family_fixed_fails_without_publication(self):
  row={'case_id':'case-1','issuer_id':'ISSUER-1','subject':'NOW','window_id':'2026Q1','cutoff':'2026-01-01T00:00:00Z','evidence_level':'diagnostic','split':'diagnostic','arm_order':['B0','F']};now=EiyV3Fixture(self,mode='now_diagnostic',subject='NOW',all_case_rows=[row],all_case_ids=['case-1'],evidence_level='diagnostic',split='diagnostic');_custody,now_manifest=now.batch();out=self.output();stdout=StringIO()
  with redirect_stdout(stdout):self.assertEqual(main(['evaluate','--workspace-root',str(ROOT),'--manifest',now_manifest['path'],'--output',out]),1)
  self.assertEqual(json.loads(stdout.getvalue())['code'],'EIY_NOW_CONFIRMATION_FORBIDDEN');self.assertFalse((ROOT/out).exists())
  _fixtures,_evaluation,_custody,normal_manifest=build_batch(self);out=self.output();stdout=StringIO()
  with redirect_stdout(stdout):self.assertEqual(main(['diagnose-now','--workspace-root',str(ROOT),'--manifest',normal_manifest['path'],'--output',out]),1)
  self.assertEqual(json.loads(stdout.getvalue())['code'],'EIY_NOW_ONLY');self.assertFalse((ROOT/out).exists())
 def test_v3_manifest_fixed_fails(self):
  f=EiyV3Fixture(self)
  with self.assertRaisesRegex(InformationYieldError,'EIY_V3_EVALUATION_CONTEXT_REQUIRED'):evaluate_path(f.manifest_ref['path'],workspace_root=ROOT)
 def test_now_cli_separate_and_no_promotion_fields(self):
  row={'case_id':'case-1','issuer_id':'ISSUER-1','subject':'NOW','window_id':'2026Q1','cutoff':'2026-01-01T00:00:00Z','evidence_level':'diagnostic','split':'diagnostic','arm_order':['B0','F']};f=EiyV3Fixture(self,mode='now_diagnostic',subject='NOW',all_case_rows=[row],all_case_ids=['case-1'],evidence_level='diagnostic',split='diagnostic');custody,manifest=f.batch();out=self.output()
  with redirect_stdout(StringIO()):self.assertEqual(main(['diagnose-now','--workspace-root',str(ROOT),'--manifest',manifest['path'],'--output',out]),0)
  result=json.loads((ROOT/out).read_text());self.assertEqual(result['schema_version'],'information-yield-now-diagnostic-result-4');self.assertNotIn('verdict',result);self.assertNotIn('statistics',result)
 def test_cli_fixed_non_echo_and_relative_only(self):
  marker='github_pat_SYNTHETIC_CANARY_1234567890';out,err=StringIO(),StringIO()
  with redirect_stdout(out),redirect_stderr(err):self.assertEqual(main([marker]),2)
  self.assertNotIn(marker,out.getvalue());self.assertEqual(err.getvalue(),'')
  _f,_e,_c,m=build_batch(self)
  with redirect_stdout(StringIO()):self.assertEqual(main(['evaluate','--workspace-root',str(ROOT),'--manifest',str((ROOT/m['path']).absolute()),'--output',self.output()]),2)
 def test_all_schemas_closed_and_results_validate(self):
  paths=[*Path('shared/research_sources/schemas').glob('*v4*.json'),*Path(__file__).parent.joinpath('schemas').glob('*.json')]
  for p in paths:s=json.loads(p.read_text());Draft202012Validator.check_schema(s);self.assertFalse(s['additionalProperties'])
  _fixtures,_evaluation,_custody,manifest=build_batch(self);result,_=evaluate_path(manifest['path'],workspace_root=ROOT);Draft202012Validator(json.loads((Path(__file__).parent/'schemas/evaluation-result.schema.json').read_text())).validate(result)
if __name__=='__main__':unittest.main()
