import unittest,tempfile
from types import SimpleNamespace
from niulai_tiger import SCOPES, QUOTE_SCOPES, ISSUER, ReadOnlyError, validate_token, login_for_scopes, sdk_classes

def token(scopes):return SimpleNamespace(issuer=ISSUER,scope=' '.join(scopes))
class QuoteScopeTests(unittest.TestCase):
 def test_accept_exact_old_and_quote_read_scopes_only(self):
  validate_token(token(SCOPES));validate_token(token(QUOTE_SCOPES),require_quotes=True)
  with self.assertRaisesRegex(ReadOnlyError,'QUOTE_READ_CONSENT_REQUIRED'):validate_token(token(SCOPES),require_quotes=True)
  for scopes in [QUOTE_SCOPES|{'api.trade:write'},SCOPES|{'unexpected:read'},frozenset({'api.quote:read'})]:
   with self.assertRaisesRegex(ReadOnlyError,'TOKEN_SCOPE_REJECTED'):validate_token(token(scopes))
 def test_explicit_upgrade_forces_device_consent(self):
  calls=[];s=SimpleNamespace(login_with_device_code=lambda cb:(calls.append('force') or token(QUOTE_SCOPES)),login_with_device_code_if_needed=lambda cb:(calls.append('reuse') or token(SCOPES)))
  login_for_scopes(s,token(SCOPES),True,True,lambda x:None);self.assertEqual(calls,['force'])
 def test_existing_quote_grant_reuses_and_base_login_compatible(self):
  calls=[];s=SimpleNamespace(login_if_needed=lambda cb:(calls.append('reuse') or token(QUOTE_SCOPES)),login=lambda cb:(calls.append('force') or token(QUOTE_SCOPES)))
  login_for_scopes(s,token(QUOTE_SCOPES),True,False,lambda x:None);login_for_scopes(s,token(SCOPES),False,False,lambda x:None);self.assertEqual(calls,['reuse','reuse'])
 def test_quote_request_metadata_is_exact_read_only(self):
  from tigeropen.auth.oauth2.metadata import OAuth2Metadata
  Session,_=sdk_classes(include_quotes=True)
  with tempfile.TemporaryDirectory() as directory:
   s=Session(issuer=ISSUER,home=directory,surface='test',client_name='test')
   s._metadata=OAuth2Metadata(issuer=ISSUER,authorization_endpoint=ISSUER+'/authorize',token_endpoint=ISSUER+'/token',scopes_supported=[*QUOTE_SCOPES,'api.trade:write'])
   self.assertEqual(set(s.scopes.split()),QUOTE_SCOPES)
if __name__=='__main__':unittest.main()
