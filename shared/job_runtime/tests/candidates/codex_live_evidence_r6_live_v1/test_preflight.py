import os,tempfile,unittest
from pathlib import Path
from _loader import module
from _support import NOW,make
class T(unittest.TestCase):
 def test_holds_every_artifact_descriptor_and_path_swap(self):
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d);lease=module("preflight").prepare(v,a,NOW,Path(d).resolve());self.assertEqual(set(lease.artifacts),{"binary","argv","config","catalog","parser","prompt"})
   p=Path(v["prompt"]["native_prompt_path"]);p.rename(p.with_suffix(".old"));p.write_bytes(b"replacement");p.chmod(0o400);self.assertEqual(lease.artifacts["prompt"]["data"],b"synthetic prompt\n");lease.close()
 def test_component_symlink_and_all_artifact_drift_stop(self):
  fields=(("binary","canonical_path"),("canonical_invocation","argv_path"),("canonical_invocation","config_path"),("catalog","raw_catalog_private_path"),("catalog","catalog_parser_path"),("prompt","native_prompt_path"))
  for section,key in fields:
   with tempfile.TemporaryDirectory() as d:
    v,a=make(d);p=Path(v[section][key]);p.chmod(0o600);p.write_bytes(b"drift");p.chmod(0o400);r=module("preflight").run_preflight(v,a,NOW,Path(d).resolve());self.assertEqual((r["decision"],r["catalog_preflight_count"]),("STOP",0))
  with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as out:
   v,a=make(d);p=Path(v["prompt"]["native_prompt_path"]);p.unlink();Path(d,"link").symlink_to(out,target_is_directory=True);v["prompt"]["native_prompt_path"]=str(Path(d,"link","x"));r=module("preflight").run_preflight(v,a,NOW,Path(d).resolve());self.assertEqual(r["decision"],"STOP")
 def test_every_malformed_map_is_stop(self):
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d);v["catalog"]=[];r=module("preflight").run_preflight(v,a,NOW,Path(d).resolve());self.assertEqual((r["decision"],r["catalog_preflight_count"]),("STOP",0))
