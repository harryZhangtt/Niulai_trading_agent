import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import private_profile as p
import niulai_tiger as n

class PrivateProfileTests(unittest.TestCase):
 def test_rejects_insecure_origin_and_redirect_targets(self):
  for url in ['http://example.chatgpt.site','https://evil.test','https://ok.chatgpt.site?secret=x']:
   with self.assertRaises(n.ReadOnlyError):p.rpc({'origin':url,'bearer':'synthetic'},'/health')
 def test_restore_rejects_traversal(self):
  with tempfile.TemporaryDirectory() as path:
   for name in ['../bad.json','/tmp/bad.json']:
    with self.assertRaises(n.ReadOnlyError):p.restore(Path(path),{'files':{name:'{}'}})
 def test_restore_recover_new_directory_with_private_permissions(self):
  with tempfile.TemporaryDirectory() as path:
   root=Path(path)/'fresh';p.restore(root,{'files':{'tokens/test.json':'{"test":1}'}})
   self.assertEqual(root.stat().st_mode&0o777,0o700);self.assertEqual((root/'tokens/test.json').stat().st_mode&0o777,0o600);self.assertEqual(p.collect(root),{'files':{'tokens/test.json':'{\n  "test": 1\n}\n'}})
 def test_unrelated_json_not_exported(self):
  with tempfile.TemporaryDirectory() as path:
   root=Path(path);n.write_private(root/'account-refs.json',{});n.write_private(root/'unrelated.json',{'private':'not OAuth'});self.assertEqual(set(p.collect(root)['files']),{'account-refs.json'})
 def test_symbolic_link_credentials_rejected(self):
  with tempfile.TemporaryDirectory() as path:
   root=Path(path);(root/'tokens').mkdir();(root/'tokens/token.json').symlink_to(root/'missing')
   with self.assertRaises(n.ReadOnlyError):p.collect(root)
 def test_checkpoint_requires_positive_ack(self):
  with tempfile.TemporaryDirectory() as path:
   root=Path(path);n.write_private(root/'account-refs.json',{})
   with patch.object(p,'rpc',return_value={'committed':False}):
    with self.assertRaises(n.ReadOnlyError):p.checkpoint(root,{'lease_id':'synthetic'})
 def test_request_retries_reuse_identical_commit_body(self):
  with tempfile.TemporaryDirectory() as path:
   root=Path(path);n.write_private(root/'account-refs.json',{})
   with patch.object(p,'rpc',return_value={'committed':True}) as call:
    p.checkpoint(root,{'lease_id':'lease'},True);body=call.call_args.args[2];self.assertTrue(body['release']);self.assertEqual(body['lease_id'],'lease');self.assertEqual(len(body['commit_id']),36)
 def test_fake_context_without_matching_remote_profile_is_rejected(self):
  with tempfile.TemporaryDirectory() as path,patch.dict(p.os.environ,{'NIULAI_PROFILE_SESSION_JSON':json.dumps({'lease_id':'lease'})}),patch.object(p,'rpc',return_value={'lease_id':'lease','profile':{'files':{'account-refs.json':'{"source":"remote"}'}},'revision':2}):
   root=Path(path);n.write_private(root/'account-refs.json',{'source':'local'})
   with self.assertRaisesRegex(n.ReadOnlyError,'PRIVATE_PROFILE_SOURCE_MISMATCH'):p.verify_remote_context(root)

if __name__=='__main__':unittest.main()
