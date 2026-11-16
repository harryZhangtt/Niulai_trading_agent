import copy,hashlib,hmac,json,threading,unittest
from pathlib import Path
from tuning.factor_mining.trusted_authority.gcp import contract
SHA_A,SHA_B,SHA_C=(c*64 for c in"abc");T0="2026-11-05T00:00:00Z";T1="2026-11-05T01:00:00Z";T2="2026-11-05T02:00:00Z";T3="2026-11-08T00:00:00Z"
class FixtureVerifier:
 fixture_only=True
 def __init__(self):self.secrets={p:(p.encode()*32)[:32]for p in(*contract.PURPOSES,"approver-a","approver-b")}
 def key_version(self,p):
  project="factor-control-proj"if p in{"checkpoint","revocation"}else"factor-custody-proj";return f"projects/{project}/locations/us/keyRings/factor/cryptoKeys/{p}/cryptoKeyVersions/1"
 def public_hash(self,p):return hashlib.sha256((p+"-public").encode()).hexdigest()
 def keys(self):return{p:{"key_version":self.key_version(p),"public_key_sha256":self.public_hash(p)}for p in contract.PURPOSES}
 def approval_keys(self):return{p:{"key_version":self.key_version(p),"public_key_sha256":self.public_hash(p)}for p in("approver-a","approver-b")}
 def sign(self,v,p):
  x=copy.deepcopy(v);x.update(trust_class="synthetic_fixture",signer_key_version=self.key_version(p),signer_public_key_sha256=self.public_hash(p),signature_encoding="FIXTURE_HMAC_SHA256_HEX",signature="pending");x["signature"]=hmac.new(self.secrets[p],contract.canonical({k:x[k]for k in x if k!="signature"}),hashlib.sha256).hexdigest();return x
 def verify(self,unsigned_bytes,signature,*,encoding,key_version,public_key_sha256,purpose):
  names=[purpose]if purpose!="approval"else["approver-a","approver-b"]
  return any(encoding=="FIXTURE_HMAC_SHA256_HEX"and key_version==self.key_version(p)and public_key_sha256==self.public_hash(p)and hmac.compare_digest(hmac.new(self.secrets[p],unsigned_bytes,hashlib.sha256).hexdigest(),signature)for p in names)
def status(v,p="checkpoint",state="active",when=T0):
 x={"schema_version":1,"kind":"gcp_kms_key_status","key_version":v.key_version(p),"purpose":p,"algorithm":"EC_SIGN_P256_SHA256","public_key_sha256":v.public_hash(p),"status":state,"effective_at":when,"previous_status_sha256":None,"signer_permission_revoked":state!="active","policy_sha256":SHA_B};return v.sign(x,"revocation")
def checkpoint(v,s,seq=1,prev=None,epoch=1,transition=None):
 manifest=SHA_A if seq==1 else SHA_B;req,evidence,receipt=s.prepare_manifest(bucket="factor-checkpoints",object_name=f"checkpoints/{seq:020d}.json",content_sha256=manifest,verified_at=T0,retain_until=T3,minimum_retention_days=1);x={"schema_version":1,"kind":"gcp_checkpoint","epoch":epoch,"sequence":seq,"previous_checkpoint_sha256":prev,"manifest_sha256":manifest,"idempotency_key":f"run-{seq}","storage_request":req,"storage_receipt_sha256":contract.digest(receipt),"issued_at":T1 if seq==1 else T2,"key_status_sha256":contract.digest(status(v)),"recovery_transition_sha256":transition};return v.sign(x,"checkpoint"),evidence

def publication_bundle(v,*,evaluation_time=T1,checker_time=T1,approval_times=(T1,T1),authorization_time=T2,expires=T3,now=T2):
 s=contract.FixtureStorage();cp,evidence=checkpoint(v,s);cpks=status(v);evks=status(v,"evaluation");ckks=status(v,"checker");pubks=status(v,"publication");state=contract.FixtureCurrentState(cp,{"checkpoint":cpks,"evaluation":evks,"checker":ckks,"publication":pubks});ev=v.sign({"schema_version":1,"kind":"gcp_evaluation_aggregate_receipt","manifest_sha256":SHA_B,"checkpoint_sha256":contract.digest(cp),"aggregate_schema_id":"factor-eval-v1","aggregate_schema_version":1,"aggregate_sha256":SHA_C,"key_status_sha256":contract.digest(evks),"issued_at":evaluation_time},"evaluation");checker=v.sign({"schema_version":1,"kind":"gcp_independent_checker_receipt","manifest_sha256":SHA_B,"checkpoint_sha256":contract.digest(cp),"aggregate_schema_id":"factor-checker-v1","aggregate_schema_version":1,"evaluator_receipt_sha256":contract.digest(ev),"checker_attestation_sha256":SHA_A,"key_status_sha256":contract.digest(ckks),"issued_at":checker_time},"checker");aps=[]
 for when,who in zip(approval_times,("approver-a","approver-b")):aps.append(v.sign({"schema_version":1,"kind":"gcp_publication_approval","approval_id":"approval-"+who[-1],"approver_id":who,"checkpoint_sha256":contract.digest(cp),"manifest_sha256":SHA_B,"approval_policy_version":"approval-policy-v1","issued_at":when,"expires_at":expires,"decision":"approved"},who))
 u={"schema_version":1,"kind":"gcp_publication_authorization","authorization_id":"auth-one","epoch":1,"sequence":1,"checkpoint_sha256":contract.digest(cp),"purpose":"performance_publication","manifest_sha256":SHA_B,"evaluation_receipt_sha256":contract.digest(ev),"evaluator_schema_id":"factor-eval-v1","evaluator_schema_version":1,"checker_receipt_sha256":contract.digest(checker),"checker_schema_id":"factor-checker-v1","checker_schema_version":1,"approval_policy_version":"approval-policy-v1","approvals":[contract.digest(x)for x in aps],"key_status_sha256":contract.digest(pubks),"issued_at":authorization_time,"expires_at":expires,"state":"active"};auth=v.sign(u,"publication");kwargs=dict(current_checkpoint=cp,current_checkpoint_storage_evidence=evidence,checkpoint_key_status=cpks,storage_verifier=s,current_state=state,manifest_sha256=SHA_B,evaluation_receipt=ev,evaluation_key_status=evks,checker_receipt=checker,checker_key_status=ckks,approvals=aps,approval_keys=v.approval_keys(),purpose="performance_publication",key_status=pubks,verifier=v,keys=v.keys(),now=now);return auth,kwargs
class Tests(unittest.TestCase):
 def setUp(self):self.v=FixtureVerifier();self.keys=self.v.keys()
 def test_profile(self):
  p=contract.load_profile();self.assertEqual(p,contract.expected_profile());self.assertFalse(p["activation_allowed"]);self.assertEqual(set(p["kms_keys"]),set(contract.PURPOSES))
 def test_disabled_mutation(self):
  p=contract.expected_profile();p["projects"]["control"]="factor-control"
  with self.assertRaises(contract.GcpAuthorityError):contract.validate_profile(p)
 def test_storage_restart_idempotency(self):
  s=contract.FixtureStorage();c,e=checkpoint(self.v,s);ks=status(self.v)
  with self.assertRaises(contract.UnknownOutcome):s.commit(c,storage_evidence=e,key_status=ks,verifier=self.v,keys=self.keys,unknown_after_write=True)
  r=contract.FixtureStorage(s.snapshot());self.assertTrue(r.reconcile("run-1",contract.digest(c)));self.assertFalse(r.commit(c,storage_evidence=e,key_status=ks,verifier=self.v,keys=self.keys)[1])
 def test_storage_signature_and_provider_evidence(self):
  s=contract.FixtureStorage();c,e=checkpoint(self.v,s);ks=status(self.v);self.assertEqual(contract.validate_checkpoint(c,key_status=ks,verifier=self.v,keys=self.keys,storage_verifier=s,storage_evidence=e),c)
  for change in(lambda x:x.update(signature="0"*64),lambda x:x["storage_request"].update(if_generation_match=1),lambda x:x.update(storage_receipt_sha256=SHA_C),lambda x:x.update(trust_class="production")):
   bad=copy.deepcopy(c);change(bad)
   with self.assertRaises(contract.GcpAuthorityError):contract.validate_checkpoint(bad,key_status=ks,verifier=self.v,keys=self.keys,storage_verifier=s,storage_evidence=e)
  class BoolVerifier:
   fixture_only=False
   def verify(self,*a,**k):return True
  with self.assertRaises(contract.GcpAuthorityError):contract.validate_checkpoint(c,key_status=ks,verifier=self.v,keys=self.keys,storage_verifier=BoolVerifier(),storage_evidence={})
 def test_recovery_validates_current_and_time(self):
  s=contract.FixtureStorage();first,e1=checkpoint(self.v,s);ks=status(self.v);rks=status(self.v,"revocation");u={"schema_version":1,"kind":"gcp_recovery_epoch_transition","from_location":"us-central1","to_location":"us-east1","new_epoch":2,"prior_checkpoint_sha256":contract.digest(first),"writer_fenced":True,"chain_verified":True,"merge_heads":False,"key_status_sha256":contract.digest(rks),"issued_at":T2};tr=self.v.sign(u,"revocation");second,e2=checkpoint(self.v,s,2,contract.digest(first),2,contract.digest(tr));self.assertEqual(contract.validate_checkpoint(second,first,key_status=ks,current_key_status=ks,verifier=self.v,keys=self.keys,storage_verifier=s,storage_evidence=e2,current_storage_evidence=e1,recovery=tr,recovery_key_status=rks),second)
  bad=copy.deepcopy(tr);bad["issued_at"]=T0
  with self.assertRaises(contract.GcpAuthorityError):contract.validate_checkpoint(second,first,key_status=ks,current_key_status=ks,verifier=self.v,keys=self.keys,storage_verifier=s,storage_evidence=e2,current_storage_evidence=e1,recovery=bad,recovery_key_status=rks)
 def test_publication_full_quorum_and_current_keys(self):
  s=contract.FixtureStorage();cp,e=checkpoint(self.v,s);cpks=status(self.v);evks=status(self.v,"evaluation");ckks=status(self.v,"checker");pubks=status(self.v,"publication");state=contract.FixtureCurrentState(cp,{"checkpoint":cpks,"evaluation":evks,"checker":ckks,"publication":pubks});ev=self.v.sign({"schema_version":1,"kind":"gcp_evaluation_aggregate_receipt","manifest_sha256":SHA_B,"checkpoint_sha256":contract.digest(cp),"aggregate_schema_id":"factor-eval-v1","aggregate_schema_version":1,"aggregate_sha256":SHA_C,"key_status_sha256":contract.digest(evks),"issued_at":T1},"evaluation");checker=self.v.sign({"schema_version":1,"kind":"gcp_independent_checker_receipt","manifest_sha256":SHA_B,"checkpoint_sha256":contract.digest(cp),"aggregate_schema_id":"factor-checker-v1","aggregate_schema_version":1,"evaluator_receipt_sha256":contract.digest(ev),"checker_attestation_sha256":SHA_A,"key_status_sha256":contract.digest(ckks),"issued_at":T1},"checker");aps=[]
  for who in("approver-a","approver-b"):aps.append(self.v.sign({"schema_version":1,"kind":"gcp_publication_approval","approval_id":"approval-"+who[-1],"approver_id":who,"checkpoint_sha256":contract.digest(cp),"manifest_sha256":SHA_B,"approval_policy_version":"approval-policy-v1","issued_at":T1,"expires_at":T3,"decision":"approved"},who))
  u={"schema_version":1,"kind":"gcp_publication_authorization","authorization_id":"auth-one","epoch":1,"sequence":1,"checkpoint_sha256":contract.digest(cp),"purpose":"performance_publication","manifest_sha256":SHA_B,"evaluation_receipt_sha256":contract.digest(ev),"evaluator_schema_id":"factor-eval-v1","evaluator_schema_version":1,"checker_receipt_sha256":contract.digest(checker),"checker_schema_id":"factor-checker-v1","checker_schema_version":1,"approval_policy_version":"approval-policy-v1","approvals":[contract.digest(x)for x in aps],"key_status_sha256":contract.digest(pubks),"issued_at":T2,"expires_at":T3,"state":"active"};auth=self.v.sign(u,"publication");kwargs=dict(current_checkpoint=cp,current_checkpoint_storage_evidence=e,checkpoint_key_status=cpks,storage_verifier=s,current_state=state,manifest_sha256=SHA_B,evaluation_receipt=ev,evaluation_key_status=evks,checker_receipt=checker,checker_key_status=ckks,approvals=aps,approval_keys=self.v.approval_keys(),purpose="performance_publication",key_status=pubks,verifier=self.v,keys=self.keys,now=T2);self.assertEqual(contract.validate_authorization(auth,**kwargs),auth)
  dup=[aps[0],copy.deepcopy(aps[0])]
  with self.assertRaises(contract.GcpAuthorityError):contract.validate_authorization(auth,**{**kwargs,"approvals":dup})
  stale=contract.FixtureCurrentState(cp,{"checkpoint":cpks,"evaluation":evks,"checker":ckks,"publication":status(self.v,"publication","revoked",T2)})
  with self.assertRaises(contract.GcpAuthorityError):contract.validate_authorization(auth,**{**kwargs,"current_state":stale})
 def test_publication_causal_time_order_edges_reject(self):
  cases=[
   {"evaluation_time":T0},
   {"evaluation_time":T2,"checker_time":T1,"approval_times":(T2,T2)},
   {"checker_time":T2,"approval_times":(T1,T1)},
   {"approval_times":("2026-11-05T02:30:00Z","2026-11-05T02:30:00Z"),"authorization_time":T2,"now":"2026-11-05T02:30:00Z"},
   {"authorization_time":"2026-11-05T02:30:00Z","now":T2},
   {"authorization_time":T2,"expires":T3,"now":T3},
  ]
  for patch in cases:
   auth,kwargs=publication_bundle(self.v,**patch)
   with self.subTest(patch=patch),self.assertRaises(contract.GcpAuthorityError):contract.validate_authorization(auth,**kwargs)
 def test_schemas(self):
  root=Path(contract.PACKAGE);self.assertEqual(json.loads((root/"gcp-authority-profile-v1.schema.json").read_text())["const"],contract.expected_profile());schemas={"checkpoint-v1.schema.json":contract.CHECKPOINT_KEYS,"storage-receipt-v1.schema.json":contract.STORAGE_RECEIPT_KEYS,"key-status-v1.schema.json":contract.KEY_STATUS_KEYS,"recovery-transition-v1.schema.json":contract.RECOVERY_KEYS,"evaluation-receipt-v1.schema.json":contract.EVALUATION_KEYS,"checker-receipt-v1.schema.json":contract.CHECKER_KEYS,"approval-v1.schema.json":contract.APPROVAL_KEYS,"authorization-v1.schema.json":contract.AUTH_KEYS}
  for n,f in schemas.items():s=json.loads((root/n).read_text());self.assertEqual(set(s["required"]),f);self.assertEqual(set(s["properties"]),f)
  [json.loads(p.read_text())for p in root.glob("*.json")]
if __name__=="__main__":unittest.main()
