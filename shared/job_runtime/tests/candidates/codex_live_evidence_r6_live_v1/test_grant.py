import copy,tempfile,unittest
from pathlib import Path
from _loader import module
from _support import NOW,make,resign
class T(unittest.TestCase):
 def test_stage_a_and_direct_authorization_denied(self):
  g=module("grant");v=g.stage_a_template();g.validate_stage_a(v);self.assertTrue(all(x==g.PLACEHOLDER for x in v["external_fields"].values()))
  with self.assertRaises(module("contracts").ContractError):module("contracts").LiveAuthorization("a"*64,"b"*64,"n","c"*64)
 def test_trusted_provenance_and_drift(self):
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d);module("grant").validate_grant_seal(v,a,NOW);p=Path(v["authority"]["independent_grant_review_path"]);p.chmod(0o600);p.write_bytes(b'{"verdict":"CLEAN"}');p.chmod(0o400)
   with self.assertRaises(module("contracts").ContractError):module("grant").TrustedAuthorizationVerifier.issue(v,Path(d).resolve(),NOW)
 def test_empty_wrong_credential_and_nested_malformed(self):
  for ref in ("","plain-value","ref://contains space"):
   with tempfile.TemporaryDirectory() as d:
    v,_=make(d);v["account"]["credential_reference"]=ref
    with self.assertRaises(module("contracts").ContractError):resign(v,d)
  with tempfile.TemporaryDirectory() as d:
   v,_=make(d);v["model"]["extra"]=1
   with self.assertRaises(module("contracts").ContractError):module("grant").validate_grant_structure(v,NOW)
 def test_all_prompt_identity_cross_bindings(self):
  for key in ("native_prompt_identity","engine_identity"):
   with tempfile.TemporaryDirectory() as d:
    v,_=make(d);v["prompt"][key]="wrong"
    with self.assertRaises(module("contracts").ContractError):resign(v,d)
