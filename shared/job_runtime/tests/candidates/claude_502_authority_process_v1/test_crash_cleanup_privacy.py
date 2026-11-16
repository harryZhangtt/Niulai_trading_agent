import hashlib,json,unittest
from pathlib import Path
from ._support import CAP,REG,KEY,PKG,FIX,fixture,load_package,make_authority,session
P=load_package()
class PrivacyClaimTests(unittest.TestCase):
 def test_import_inertness(self):
    self.assertFalse(P.ENABLED); self.assertFalse(P.CAPABILITY_OPEN); self.assertFalse(P.LIVE)
    source='\n'.join(p.read_text() for p in PKG.glob('*.py'))
    for forbidden in ('import socket','import subprocess','import anthropic','Popen(','fork(','execve(','socket.socket(','if __name__'): self.assertNotIn(forbidden,source)
 def test_client_no_key_and_zeroes_capability(self):
    c=P.AuthorityClient(lambda *_:{},CAP,'privacy-session'); self.assertNotIn('key',c.__dict__); c.close(); self.assertEqual(bytes(c._capability),b'\0'*32)
 def test_journal_is_sanitized_and_no_capabilities_or_key(self):
    a=make_authority(); session(a,'registrar','privacy-reg').call('register_expected_binding',fixture('binding.json')); text=json.dumps(a.journal_snapshot(),sort_keys=True)
    self.assertNotIn(CAP.decode(),text); self.assertNotIn(REG.decode(),text); self.assertNotIn(KEY.decode(),text); self.assertNotIn('credential',text.lower()); self.assertNotIn('raw_header',text.lower())
 def test_design_hash_closure(self):
    path=Path('/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/claude-502-authority-process-contract.json'); raw=path.read_bytes(); self.assertEqual(len(raw),5161); self.assertEqual(hashlib.sha256(raw).hexdigest(),P.DESIGN_CONTRACT_SHA256)
 def test_canonical_json_artifacts(self):
    for path in list(PKG.glob('*.schema.json'))+list(FIX.glob('*.json')):
      raw=path.read_bytes().rstrip(b'\n'); value=json.loads(raw); self.assertEqual(raw,json.dumps(value,sort_keys=True,separators=(',',':')).encode())
