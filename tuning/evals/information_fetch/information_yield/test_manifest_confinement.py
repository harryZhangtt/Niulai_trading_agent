from hashlib import sha256
import json,os,tempfile,unittest
from pathlib import Path
from shared.research_sources.artifacts import ROOT
from .contracts import InformationYieldError,canonical
from .manifest import HeldWorkspace
class HeldWorkspaceTests(unittest.TestCase):
 def setUp(self):
  parent=ROOT/'investment/runtime/eiy-v3-path-tests';parent.mkdir(parents=True,exist_ok=True,mode=0o700);self.t=tempfile.TemporaryDirectory(dir=parent);self.root=Path(self.t.name);self.root.chmod(0o700);(self.root/'inputs').mkdir(mode=0o700);raw=canonical({'ok':True});self.path=self.root/'inputs/data.json';self.path.write_bytes(raw);self.path.chmod(0o600);self.ref={'path':'inputs/data.json','sha256':sha256(raw).hexdigest()}
 def tearDown(self):self.t.cleanup()
 def test_nominal_read_and_replay_conflict(self):
  with HeldWorkspace(self.root) as held:
   self.assertEqual(held.reopen_json(self.ref),{'ok':True});self.assertFalse(held.publish('results/result.json',{'ok':True},input_paths={self.ref['path']}));self.assertTrue(held.publish('results/result.json',{'ok':True},input_paths={self.ref['path']}))
   with self.assertRaisesRegex(InformationYieldError,'EIY_OUTPUT_CONFLICT'):held.publish('results/result.json',{'ok':False},input_paths={self.ref['path']})
 def test_absolute_parent_and_output_overlap_rejected(self):
  with HeldWorkspace(self.root) as held:
   for path in ('/tmp/x','../x'):
    with self.subTest(path=path),self.assertRaisesRegex(InformationYieldError,'EIY_PATH'):held.read_json(path)
   with self.assertRaisesRegex(InformationYieldError,'EIY_OUTPUT_OVERLAP'):held.publish('inputs/result.json',{'ok':True},input_paths={self.ref['path']})
 def test_symlink_hardlink_fifo_and_insecure_mode_rejected(self):
  symlink=self.root/'inputs/link.json';symlink.symlink_to(self.path);hard=self.root/'inputs/hard.json';os.link(self.path,hard);fifo=self.root/'inputs/pipe';os.mkfifo(fifo,0o600)
  refs=[{'path':'inputs/link.json','sha256':self.ref['sha256']},{'path':'inputs/hard.json','sha256':self.ref['sha256']},{'path':'inputs/pipe','sha256':'0'*64}]
  with HeldWorkspace(self.root) as held:
   for ref in refs:
    with self.subTest(path=ref['path']),self.assertRaises(InformationYieldError):held.reopen_json(ref)
  hard.unlink();self.path.chmod(0o666)
  with HeldWorkspace(self.root) as held:
   with self.assertRaisesRegex(InformationYieldError,'EIY_PATH_TYPE'):held.reopen_json(self.ref)
 def test_parent_swap_cannot_redirect(self):
  outside=self.root/'outside';outside.mkdir(mode=0o700);(outside/'data.json').write_text('{"forged":true}');(outside/'data.json').chmod(0o600);held_parent=self.root/'held-inputs'
  with HeldWorkspace(self.root) as held:
   (self.root/'inputs').rename(held_parent);(self.root/'inputs').symlink_to(outside,target_is_directory=True)
   with self.assertRaises(InformationYieldError):held.reopen_json(self.ref)
if __name__=='__main__':unittest.main()
