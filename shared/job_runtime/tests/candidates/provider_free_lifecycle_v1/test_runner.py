import json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from _loader import module
class RunnerTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.c=module("contracts");cls.r=module("runner");cls.fx=Path(__file__).resolve().parents[2]/"fixtures"/"provider_free_lifecycle_v1"
 def run_case(self,name):
  binding=self.c.binding_from_mapping(json.loads((self.fx/name).read_text()))
  with tempfile.TemporaryDirectory() as directory:
   workspace=Path(directory).resolve(strict=True)
   root=workspace/".job-runtime"/"engine"
   return self.r.run_provider_free_experiment(binding=binding,workspace_root=workspace,state_root=root,now=datetime(2030,1,1,tzinfo=timezone.utc))
 def test_nominal_vertical(self):
  result=self.run_case("nominal.json");self.assertEqual((result.slot_status,result.attempt_status,result.dispatch_count),("succeeded","succeeded",1));self.assertFalse(result.replay_authorized)
 def test_post_admission_unknown_reconstructs_without_replay(self):
  result=self.run_case("post-submit-failure.json");self.assertEqual((result.slot_status,result.attempt_status,result.dispatch_count),("unknown","unknown",1));self.assertEqual(result.reconstructed_dispatch_count,1)
 def test_inert_import_and_no_effect_symbols(self):
  text=(Path(__file__).resolve().parents[3]/"candidates"/"provider_free_lifecycle_v1"/"runner.py").read_text()
  roots=[Path(__file__).resolve().parents[3]/"candidates"/"provider_free_lifecycle_v1", Path(__file__).resolve().parents[5]/"tuning"/"architecture"/"provider_free_lifecycle_v1"]
  combined="".join(q.read_text() for root in roots for q in root.glob("*.py"))
  for token in ("import socket", "import urllib", "import requests", "import anthropic"):
   self.assertNotIn(token, combined)
 def test_clean_interpreter_import_closure(self):
  import subprocess,sys
  root=Path(__file__).resolve().parents[3]/"candidates"/"provider_free_lifecycle_v1"
  code="import importlib.util,sys,types,pathlib;root=pathlib.Path(sys.argv[1]);p=types.ModuleType(\"provider_free_lifecycle_v1\");p.__path__=[str(root)];sys.modules[p.__name__]=p;s=importlib.util.spec_from_file_location(\"provider_free_lifecycle_v1.__init__\",root/\"__init__.py\");m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);assert not any(x==\"shared.job_runtime\" or x.startswith(\"shared.job_runtime.\") for x in sys.modules)"
  done=subprocess.run([sys.executable,"-I","-c",code,str(root)],capture_output=True,text=True,timeout=10)
  self.assertEqual((done.returncode,done.stderr),(0,""))

 def test_engine_loader_rejects_preseeded_namespace(self):
  import sys,types
  name="_pfl_canonical_engine_v1"
  sys.modules[name]=types.ModuleType(name)
  try:
   with self.assertRaisesRegex(RuntimeError,"^PFL_ENGINE_NAMESPACE_OCCUPIED$"):
    self.r._load_engine()
  finally:sys.modules.pop(name,None)
  sub=name+".engine";sys.modules[sub]=types.ModuleType(sub)
  try:
   with self.assertRaisesRegex(RuntimeError,"^PFL_ENGINE_NAMESPACE_OCCUPIED$"):
    self.r._load_engine()
  finally:sys.modules.pop(sub,None)

 def test_every_effect_capability_is_denied_and_counted(self):
  fake=module("fake_provider");recorder=fake.DenyEffectRecorder();caps=fake.EffectCapabilities(recorder)
  for name in ("provider","network","process","host","email","business"):
   with self.assertRaisesRegex(RuntimeError,"^PFL_EFFECT_DENIED$"):getattr(caps,name)()
  self.assertEqual(dict(recorder.snapshot()),{name:1 for name in ("provider","network","process","host","email","business")})

 def test_verified_bytes_not_reopened_from_changed_path(self):
  import types
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/"module.py";path.write_bytes(b"VALUE=1\n");raw=path.read_bytes();path.write_bytes(b"VALUE=2\n")
   module=types.ModuleType("verified_bytes_test");module.__file__=str(path)
   self.r._execute_verified(raw,path,module)
   self.assertEqual(module.VALUE,1)
 def test_baseexception_partial_load_cleans_namespace(self):
  import sys
  original=self.r._execute_verified;calls=[]
  def interrupted(raw,path,module):
   calls.append(path.name)
   if len(calls)==2:raise KeyboardInterrupt()
   return original(raw,path,module)
  self.r._execute_verified=interrupted
  try:
   with self.assertRaises(KeyboardInterrupt):self.r._load_engine()
  finally:self.r._execute_verified=original
  self.assertFalse(any(name=="_pfl_canonical_engine_v1" or name.startswith("_pfl_canonical_engine_v1.") for name in sys.modules))
