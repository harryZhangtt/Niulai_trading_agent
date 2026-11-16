import importlib.util,json,sys,tempfile,unittest,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]/"candidates"/"claude_visible_cli_v1"
def load():
 name="claude_visible_cli_v1.contracts";pkg=type(sys)("claude_visible_cli_v1");pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
 spec=importlib.util.spec_from_file_location(name,ROOT/'contracts.py');m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
class TestCli(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.m=load();cls.binary=Path(shutil.which('claude')).resolve(strict=True)
 def test_exact_disabled_contract(self):
  value=self.m.load_contract(self.binary);self.assertFalse(value['enabled']);self.assertTrue(value['invocation_prohibited']);self.assertFalse(value['semantics']['resume_allowed']);self.assertFalse(value['semantics']['max_turns_cli_supported']);self.assertFalse(value['semantics']['max_budget_cli_supported'])
 def test_exact_control_grammar(self):
  value=self.m.load_contract(self.binary);self.assertEqual(value['semantics']['stop'],('stop','<id>'));self.assertEqual(value['semantics']['list'],('agents','--json','--all','--cwd'));self.assertIn('--settings',value['semantics']['launch']);self.assertNotIn('--max-budget-usd',value['semantics']['launch'])
 def test_deep_immutability(self):
  value=self.m.load_contract(self.binary)
  with self.assertRaises(TypeError):value['semantics']['resume_allowed']=True
  with self.assertRaises(TypeError):value['fixtures'][0]['sha256']='0'*64
 def test_binary_drift_fails(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'claude';p.write_bytes(b'wrong')
   with self.assertRaises(self.m.CliContractError):self.m.load_contract(p)
 def test_import_has_no_invocation_surface(self):
  text=(ROOT/'contracts.py').read_text();self.assertNotIn('subprocess',text);self.assertNotIn('os.system',text);self.assertNotIn('__main__',text)
 def test_fixture_mutation_fails(self):
  original=self.m.FIXTURE_ROOT
  with tempfile.TemporaryDirectory() as d:
   target=Path(d)
   for p in original.iterdir():target.joinpath(p.name).write_bytes(p.read_bytes())
   target.joinpath('root-help.txt').write_text('mutated');self.m.FIXTURE_ROOT=target
   try:
    with self.assertRaises(self.m.CliContractError):self.m.load_contract(self.binary)
   finally:self.m.FIXTURE_ROOT=original
 def test_missing_fixture_row_fails(self):
  value=json.loads((ROOT/"contract.json").read_text());value["fixtures"]=[row for row in value["fixtures"] if row["name"]!="version.txt"]
  with tempfile.TemporaryDirectory() as d:
   contract=Path(d)/"contract.json";contract.write_text(json.dumps(value))
   with self.assertRaises(self.m.CliContractError):self.m.load_contract(self.binary,contract)

if __name__=='__main__':unittest.main()
